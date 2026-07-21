// Command backfill loads the FULL historical daily OHLCV data for every known
// symbol into Postgres. This is a ONE-TIME operation.
//
// Why backfill separately from the daily update?
//   - Backfill may fetch 20 years of data per symbol (thousands of API calls).
//   - The daily update only fetches the last few days.
//   - Running them separately means you can backfill once (it's slow), then
//     run the update daily (it's fast).
//
// Idempotency: re-running is safe. Upserts use ON CONFLICT so duplicate rows
// are simply overwritten.
package main

import (
	"bufio"
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"strings"
	"sync"
	"time"

	"vnstock-service/internal/provider"
	"vnstock-service/internal/store"
)

func main() {
	// --- Command-line flags ---
	// -seed: file of ticker symbols to backfill (one per line).
	// -fetch-symbols: ignore the seed file, fetch the full listed universe
	//   from vnstock (~1500-1700 tickers). Warning: this takes much longer.
	// -from: only fetch data on or after this date. Default 2005-01-01.
	// -workers: how many symbols to process concurrently. Each worker spawns
	//   a separate Python process, so -workers IS the rate limit for vnstock.
	var (
		seed         = flag.String("seed", "symbols.seed.txt", "file with one ticker per line, used if the symbols table is empty and -fetch-symbols is off")
		fetchSymbols = flag.Bool("fetch-symbols", false, "fetch the full listed universe via vnstock instead of the seed file")
		fromStr      = flag.String("from", "2005-01-01", "earliest date to fetch (YYYY-MM-DD)")
		workers      = flag.Int("workers", 6, "number of symbols fetched concurrently (also the effective rate limit for the vnstock path)")
	)
	flag.Parse()

	dsn := env("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/vnstock?sslmode=disable")
	from, err := time.Parse("2006-01-02", *fromStr)
	must(err)
	to := time.Now()

	// signal.NotifyContext ensures Ctrl+C (SIGINT) or SIGKILL cleanly cancels
	// all in-flight operations instead of terminating mid-write. Without this,
	// killing the process could leave daily_prices in an inconsistent state.
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, os.Kill)
	defer cancel()
	st, err := store.Open(ctx, dsn)
	must(err)
	defer st.Close()
	must(st.EnsureSchema(ctx))

	vnstk, err := provider.NewVNStock()
	must(err)
	src := provider.NewChain(vnstk)

	// --- Load symbols (from DB, seed file, or live listing) ---
	// If symbols are already in the DB, skip loading. Otherwise, populate
	// from either the seed file or the vnstock live listing API.
	syms, err := st.ListSymbols(ctx)
	must(err)
	if len(syms) == 0 {
		if *fetchSymbols {
			syms, err = vnstk.ListSymbols(ctx)
			must(err)
			// If the listing API changes format and returns only a handful of
			// symbols, we want to fail noisily rather than silently backfill
			// a partial universe. The threshold of 500 is a sanity check —
			// the market has ~1500-1700 listed tickers.
			if len(syms) < 500 {
				log.Fatalf("vnstock returned only %d symbols — refusing to backfill a partial universe (likely a listing API change); investigate before proceeding", len(syms))
			}
			log.Printf("fetched %d symbols from vnstock", len(syms))
		} else {
			syms = loadSeed(*seed)
			log.Printf("loaded %d symbols from %s", len(syms), *seed)
		}
		must(st.UpsertSymbols(ctx, syms))
	}

	// --- Track this backfill run ---
	// If the process crashes mid-backfill, the backfill_runs table will have
	// a row with NULL completed_at. Consumers can detect this and know the
	// data may be incomplete.
	runID, err := st.StartBackfill(ctx, len(syms))
	must(err)

	// --- Worker pool ---
	// The classic Go concurrency pattern: a channel of jobs, a fixed number
	// of goroutine workers, and a results channel to aggregate counts.
	//
	// jobs channel: buffered? No — unbuffered means workers pull jobs as
	// they're ready, naturally load-balancing across workers.
	// res channel: buffered to len(syms) so workers never block sending results.
	type result struct{ bars int }
	res := make(chan result, len(syms))

	jobs := make(chan provider.Symbol)
	var wg sync.WaitGroup
	for w := 0; w < *workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for sy := range jobs {
				bars, source, err := src.DailyHistorySourced(ctx, sy.Ticker, from, to)
				if err != nil {
					log.Printf("[%s] fetch error: %v", sy.Ticker, err)
					continue
				}
				if len(bars) == 0 {
					log.Printf("[%s] no data", sy.Ticker)
					continue
				}
				// src.ProviderAdjusted(source) asks the provider itself whether
				// its prices are adjusted — no more hardcoded "source != 'ssi'".
				if err := st.UpsertBars(ctx, sy.Ticker, source, src.ProviderAdjusted(source), bars); err != nil {
					log.Printf("[%s] store error: %v", sy.Ticker, err)
					continue
				}
				log.Printf("[%s] %d bars (%s -> %s)", sy.Ticker, len(bars),
					bars[0].Date.Format("2006-01-02"), bars[len(bars)-1].Date.Format("2006-01-02"))
				res <- result{bars: len(bars)}
			}
		}()
	}

	// Feed all symbols into the job channel, then close it so workers
	// know there are no more jobs.
	for _, sy := range syms {
		jobs <- sy
	}
	close(jobs)

	// Close the results channel once all workers are done.
	go func() {
		wg.Wait()
		close(res)
	}()

	// Aggregate results and mark the backfill run as complete.
	var totalBars int64
	for r := range res {
		totalBars += int64(r.bars)
	}
	must(st.CompleteBackfill(ctx, runID, totalBars))
	log.Printf("backfill complete: %d symbols, %d bars (run %d)", len(syms), totalBars, runID)
}

// loadSeed reads a simple text file of ticker symbols, one per line.
// Lines starting with # are treated as comments and skipped.
// Tickers are converted to uppercase.
func loadSeed(path string) []provider.Symbol {
	f, err := os.Open(path)
	must(err)
	defer f.Close()
	var out []provider.Symbol
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		out = append(out, provider.Symbol{Ticker: strings.ToUpper(line)})
	}
	must(sc.Err())
	return out
}

// env reads an environment variable with a default fallback.
func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// must is a tiny helper that fatally exits on any error.
// Saves writing "if err != nil { log.Fatal(err) }" a hundred times.
func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
