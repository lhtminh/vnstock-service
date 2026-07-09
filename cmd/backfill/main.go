// Command backfill loads full daily history for every symbol into Postgres.
// Run it once (it's idempotent, so re-running is safe).
package main

import (
	"bufio"
	"context"
	"flag"
	"log"
	"os"
	"strings"
	"sync"
	"time"

	"vnstock-service/internal/httpx"
	"vnstock-service/internal/provider"
	"vnstock-service/internal/store"
)

func main() {
	var (
		seed         = flag.String("seed", "symbols.seed.txt", "file with one ticker per line, used if the symbols table is empty and -fetch-symbols is off")
		fetchSymbols = flag.Bool("fetch-symbols", false, "fetch the full listed universe from VNDirect instead of the seed file")
		fromStr      = flag.String("from", "2005-01-01", "earliest date to fetch (YYYY-MM-DD)")
		workers      = flag.Int("workers", 6, "number of symbols fetched concurrently")
		reqPerSec    = flag.Int("rps", 5, "global request rate limit (shared across workers)")
	)
	flag.Parse()

	dsn := env("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/vnstock?sslmode=disable")
	from, err := time.Parse("2006-01-02", *fromStr)
	must(err)
	to := time.Now()

	ctx := context.Background()
	st, err := store.Open(ctx, dsn)
	must(err)
	defer st.Close()
	must(st.EnsureSchema(ctx))

	client := httpx.New(*reqPerSec, 4)
	vnd := provider.NewVNDirect(client)
	src := provider.NewChain(
		provider.NewTCBS(client),
		vnd,
	)

	syms, err := st.ListSymbols(ctx)
	must(err)
	if len(syms) == 0 {
		if *fetchSymbols {
			syms, err = vnd.ListSymbols(ctx)
			must(err)
			log.Printf("fetched %d symbols from VNDirect", len(syms))
		} else {
			syms = loadSeed(*seed)
			log.Printf("loaded %d symbols from %s", len(syms), *seed)
		}
		must(st.UpsertSymbols(ctx, syms))
	}

	jobs := make(chan provider.Symbol)
	var wg sync.WaitGroup
	for w := 0; w < *workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for sy := range jobs {
				bars, err := src.DailyHistory(ctx, sy.Ticker, from, to)
				if err != nil {
					log.Printf("[%s] fetch error: %v", sy.Ticker, err)
					continue
				}
				if len(bars) == 0 {
					log.Printf("[%s] no data", sy.Ticker)
					continue
				}
				if err := st.UpsertBars(ctx, sy.Ticker, src.Name(), bars); err != nil {
					log.Printf("[%s] store error: %v", sy.Ticker, err)
					continue
				}
				log.Printf("[%s] %d bars (%s -> %s)", sy.Ticker, len(bars),
					bars[0].Date.Format("2006-01-02"), bars[len(bars)-1].Date.Format("2006-01-02"))
			}
		}()
	}
	for _, sy := range syms {
		jobs <- sy
	}
	close(jobs)
	wg.Wait()
	log.Println("backfill complete")
}

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
