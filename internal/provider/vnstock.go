package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"time"
)

// VNStock is the PRIMARY provider. It shells out to a Python script
// (python/fetch.py) that uses the `vnstock` library to read VCI (Vietcap).
//
// Why not call VCI directly in Go?
// The Go code used to call TCBS and VNDirect directly via HTTP, but both died:
//   - TCBS IP-blocks non-allowlisted traffic → blanket 404
//   - VNDirect was decommissioned → hostname resolves to private 10.x IP
// vnstock is a maintained Python library that still has a working VCI feed.
//
// Performance note: each call spawns a fresh Python process (imports pandas,
// numpy, etc.), which takes ~5-15 seconds. That's why the backfill is slow.
// The benefit is we don't need to maintain HTTP parsing for a third broker API.
//
// Price normalization (VCI returns thousands of VND → we multiply by 1000)
// happens inside fetch.py, so bars returned here are already in VND.
// VCI prices are split/dividend-ADJUSTED (see the data-integrity caveat).
type VNStock struct {
	python string // path to the Python interpreter (e.g. .venv/Scripts/python.exe)
	script string // path to fetch.py (e.g. python/fetch.py)
}

// NewVNStock finds the Python interpreter and fetch.py script.
// Two env vars override the defaults:
//   VNSTOCK_PYTHON — path to the Python executable
//   VNSTOCK_SCRIPT — path to fetch.py
// Otherwise it looks for .venv/Scripts/python.exe (Windows) or .venv/bin/python
// (Linux/Mac) relative to the current directory. This is why you must always
// run the backfill/update commands from the repo root.
func NewVNStock() (*VNStock, error) {
	py := os.Getenv("VNSTOCK_PYTHON")
	if py == "" {
		py = defaultPython()
	}
	script := os.Getenv("VNSTOCK_SCRIPT")
	if script == "" {
		script = filepath.Join("python", "fetch.py")
	}
	if _, err := os.Stat(script); err != nil {
		return nil, fmt.Errorf("vnstock helper not found at %q: %w (run from the repo root or set VNSTOCK_SCRIPT)", script, err)
	}
	return &VNStock{python: py, script: script}, nil
}

func (v *VNStock) Name() string   { return "vnstock" }
func (v *VNStock) Adjusted() bool { return true }

// DailyHistory runs `fetch.py history` and decodes the JSON it writes.
// The flow is:
//   1. Build command-line args (symbol, date range) for fetch.py
//   2. v.run() spawns Python, writes JSON to a temp file
//   3. Parse each JSON record, skip any with unparseable dates
//   4. Sort ascending by date (the Go side always sorts — belt and suspenders)
//   5. Return []Bar already in VND
func (v *VNStock) DailyHistory(ctx context.Context, ticker string, from, to time.Time) ([]Bar, error) {
	var recs []struct {
		Date   string  `json:"date"`
		Open   float64 `json:"open"`
		High   float64 `json:"high"`
		Low    float64 `json:"low"`
		Close  float64 `json:"close"`
		Volume int64   `json:"volume"`
	}
	if err := v.run(ctx, &recs, "history",
		"--symbol", ticker,
		"--start", from.Format("2006-01-02"),
		"--end", to.Format("2006-01-02"),
	); err != nil {
		return nil, fmt.Errorf("vnstock %s: %w", ticker, err)
	}
	bars := make([]Bar, 0, len(recs))
	for _, r := range recs {
		day, err := time.Parse("2006-01-02", r.Date)
		if err != nil {
			log.Printf("vnstock %s: skipping bar with unparseable date %q: %v", ticker, r.Date, err)
			continue
		}
		bars = append(bars, Bar{
			Date: day.UTC(), Open: r.Open, High: r.High, Low: r.Low,
			Close: r.Close, Volume: r.Volume,
		})
	}
	sort.Slice(bars, func(i, j int) bool { return bars[i].Date.Before(bars[j].Date) })
	return bars, nil
}

// ListSymbols runs `fetch.py symbols` for the current listed universe. Mirrors
// VNDirect.ListSymbols so cmd/backfill's -fetch-symbols path keeps working.
// (Like the old path, this returns only LISTED names — delisted-ticker
// ingestion for survivorship remains a separate, unbuilt data path.)
func (v *VNStock) ListSymbols(ctx context.Context) ([]Symbol, error) {
	var recs []struct {
		Ticker   string `json:"ticker"`
		Exchange string `json:"exchange"`
	}
	if err := v.run(ctx, &recs, "symbols"); err != nil {
		return nil, fmt.Errorf("vnstock symbols: %w", err)
	}
	out := make([]Symbol, 0, len(recs))
	for _, r := range recs {
		out = append(out, Symbol{Ticker: r.Ticker, Exchange: r.Exchange})
	}
	return out, nil
}

// run invokes fetch.py with the given subcommand/args, pointing --out at a temp
// file, then decodes that file into dst. The helper writes the payload to the
// file (not stdout) so vnstock's banner/log noise never corrupts the JSON.
func (v *VNStock) run(ctx context.Context, dst any, args ...string) error {
	f, err := os.CreateTemp("", "vnstock-*.json")
	if err != nil {
		return err
	}
	outPath := f.Name()
	f.Close()
	defer os.Remove(outPath)

	cmdArgs := append([]string{v.script}, append(args, "--out", outPath)...)
	cmd := exec.CommandContext(ctx, v.python, cmdArgs...)
	if diag, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("%v: %s", err, trimDiag(diag))
	}
	raw, err := os.ReadFile(outPath)
	if err != nil {
		return fmt.Errorf("read helper output: %w", err)
	}
	if err := json.Unmarshal(raw, dst); err != nil {
		return fmt.Errorf("decode helper output: %w", err)
	}
	return nil
}

// defaultPython prefers the repo-local virtualenv, falling back to PATH.
func defaultPython() string {
	var venv string
	if runtime.GOOS == "windows" {
		venv = filepath.Join(".venv", "Scripts", "python.exe")
	} else {
		venv = filepath.Join(".venv", "bin", "python")
	}
	if _, err := os.Stat(venv); err == nil {
		return venv
	}
	return "python"
}

func trimDiag(b []byte) string {
	s := string(b)
	if len(s) > 500 {
		s = s[len(s)-500:]
	}
	return s
}
