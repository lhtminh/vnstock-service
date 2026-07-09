package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"time"
)

// VNStock fetches daily OHLCV by shelling out to the Python `vnstock` library
// (python/fetch.py), which reads the VCI (Vietcap) feed. We go through vnstock
// because the direct TCBS/VNDirect HTTP endpoints are no longer usable: TCBS
// IP-blocks non-allowlisted egress (blanket 404) and VNDirect's finfo API was
// decommissioned (hostname resolves to a private 10.x IP). See README.
//
// Normalization happens in fetch.py (VCI quotes in thousands -> VND), so a Bar
// returned here is already in VND, satisfying the "normalize in the provider"
// invariant. NOTE: VCI history is split/dividend-ADJUSTED, not raw — see the
// data-integrity caveat in fetch.py / README before treating it as raw.
//
// Unlike the HTTP providers, this one does NOT use the shared httpx client, so
// its request rate is governed by the worker-pool size (-workers), not -rps.
// Keep -workers modest; each call also spawns a short-lived Python process.
type VNStock struct {
	python string // path to the Python interpreter
	script string // path to fetch.py
}

// NewVNStock locates the interpreter and helper script. Both can be overridden
// with VNSTOCK_PYTHON / VNSTOCK_SCRIPT; otherwise it prefers the repo-local
// .venv and python/fetch.py (resolved from the current working directory, i.e.
// the repo root, matching how the cmd/* binaries are run).
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

func (v *VNStock) Name() string { return "vnstock" }

// DailyHistory runs `fetch.py history` and decodes the JSON it writes.
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
