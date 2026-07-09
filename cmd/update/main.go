// Command update fetches only recent bars for every known symbol and upserts
// them. Run it daily (e.g. from cron after market close).
package main

import (
	"context"
	"flag"
	"log"
	"os"
	"sync"
	"time"

	"vnstock-service/internal/httpx"
	"vnstock-service/internal/provider"
	"vnstock-service/internal/store"
)

func main() {
	var (
		overlap   = flag.Int("overlap-days", 7, "re-fetch this many days before the last stored date to catch corrections")
		workers   = flag.Int("workers", 6, "number of symbols fetched concurrently")
		reqPerSec = flag.Int("rps", 5, "global request rate limit (shared across workers)")
	)
	flag.Parse()

	dsn := env("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/vnstock?sslmode=disable")
	ctx := context.Background()
	to := time.Now()

	st, err := store.Open(ctx, dsn)
	must(err)
	defer st.Close()
	must(st.EnsureSchema(ctx))

	syms, err := st.ListSymbols(ctx)
	must(err)
	if len(syms) == 0 {
		log.Fatal("no symbols in database — run the backfill command first")
	}

	vnstk, err := provider.NewVNStock()
	must(err)
	client := httpx.New(*reqPerSec, 4)
	// vnstock (VCI) is primary; TCBS/VNDirect remain as (currently dead) fallbacks.
	src := provider.NewChain(
		vnstk,
		provider.NewTCBS(client),
		provider.NewVNDirect(client),
	)

	jobs := make(chan provider.Symbol)
	var wg sync.WaitGroup
	for w := 0; w < *workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for sy := range jobs {
				last, err := st.LastDate(ctx, sy.Ticker)
				if err != nil {
					log.Printf("[%s] last-date error: %v", sy.Ticker, err)
					continue
				}
				from := last.AddDate(0, 0, -*overlap)
				if last.IsZero() {
					// Never seen this ticker: pull the last year as a sane default.
					from = to.AddDate(-1, 0, 0)
				}
				bars, err := src.DailyHistory(ctx, sy.Ticker, from, to)
				if err != nil {
					log.Printf("[%s] fetch error: %v", sy.Ticker, err)
					continue
				}
				if len(bars) == 0 {
					continue
				}
				if err := st.UpsertBars(ctx, sy.Ticker, src.Name(), bars); err != nil {
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
