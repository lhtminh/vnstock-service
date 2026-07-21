// Command update fetches RECENT bars for every known symbol and upserts them.
// Run this daily from cron after market close (~15:30 ICT).
//
// Unlike backfill, update only fetches a small window of recent data:
//   - It looks up the last stored date for each symbol.
//   - It fetches from [last_date - overlap_days] to today.
//   - The overlap catches any late corrections or adjustments.
//
// This makes the daily run fast (each symbol fetches ~7-14 days of data
// instead of 20 years).
package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"sync"
	"time"

	"vnstock-service/internal/provider"
	"vnstock-service/internal/store"
)

func main() {
	// -overlap-days: fetch this many extra days before the last known date.
	//   Broker APIs sometimes correct or adjust historical data — the overlap
	//   ensures those corrections are captured. 7 days is conservative.
	// -workers: same as backfill — each worker is a Python subprocess.
	var (
		overlap = flag.Int("overlap-days", 7, "re-fetch this many days before the last stored date to catch corrections")
		workers = flag.Int("workers", 6, "number of symbols fetched concurrently (also the effective rate limit for the vnstock path)")
	)
	flag.Parse()

	dsn := env("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/vnstock?sslmode=disable")
	// Same signal handling as the backfill command.
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, os.Kill)
	defer cancel()
	to := time.Now()

	st, err := store.Open(ctx, dsn)
	must(err)
	defer st.Close()
	must(st.EnsureSchema(ctx))

	// Update only works on symbols already in the database.
	syms, err := st.ListSymbols(ctx)
	must(err)
	if len(syms) == 0 {
		log.Fatal("no symbols in database — run the backfill command first")
	}

	vnstk, err := provider.NewVNStock()
	must(err)
	src := provider.NewChain(vnstk)

	// Same worker pool pattern as backfill, but without backfill tracking
	// (the daily update is expected to run every day and always complete).
	jobs := make(chan provider.Symbol)
	var wg sync.WaitGroup
	for w := 0; w < *workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for sy := range jobs {
				// Find the most recent date we have for this ticker.
				last, err := st.LastDate(ctx, sy.Ticker)
				if err != nil {
					log.Printf("[%s] last-date error: %v", sy.Ticker, err)
					continue
				}
				// Start from [last_date - overlap] so we catch any corrections.
				from := last.AddDate(0, 0, -*overlap)
				if last.IsZero() {
					// Never seen this ticker: pull the last year as a sane default.
					from = to.AddDate(-1, 0, 0)
				}
				bars, source, err := src.DailyHistorySourced(ctx, sy.Ticker, from, to)
				if err != nil {
					log.Printf("[%s] fetch error: %v", sy.Ticker, err)
					continue
				}
				if len(bars) == 0 {
					continue
				}
				if err := st.UpsertBars(ctx, sy.Ticker, source, src.ProviderAdjusted(source), bars); err != nil {
					log.Printf("[%s] store error: %v", sy.Ticker, err)
					continue
				}
				log.Printf("[%s] updated %d bars through %s", sy.Ticker, len(bars),
					bars[len(bars)-1].Date.Format("2006-01-02"))
			}
		}()
	}
	for _, sy := range syms {
		jobs <- sy
	}
	close(jobs)
	wg.Wait()
	log.Println("update complete")
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
