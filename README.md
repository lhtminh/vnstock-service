# vnstock-service

Fetches Vietnamese daily stock history (OHLCV) from multiple broker APIs and
stores it in Postgres. Go + pgx. One-time **backfill** + daily **update**.

## Layout

```
cmd/backfill/    one-time full history load
cmd/update/      incremental daily refresh (run from cron)
internal/httpx/  shared HTTP client: global rate limit + retry/backoff
internal/provider/
    provider.go  the Provider interface + Bar/Symbol types
    tcbs.go      primary source (VND prices, deep history)
    vndirect.go  fallback source + full-universe symbol listing
    chain.go     fallback chain across providers
internal/store/  Postgres schema + pgx upserts
```

## Setup

1. Postgres (Docker is easiest):

   ```bash
   docker run --name vnstock-pg -e POSTGRES_PASSWORD=postgres \
     -e POSTGRES_DB=vnstock -p 5432:5432 -d postgres:16
   ```

2. Point the app at it:

   ```bash
   export DATABASE_URL='postgres://postgres:postgres@localhost:5432/vnstock?sslmode=disable'
   ```

3. Pull deps:

   ```bash
   go mod tidy
   ```

## Verify the endpoints FIRST

These are public/unofficial broker APIs; field names and units drift. Confirm
each once before a big run:

```bash
# TCBS — prices should be in VND (e.g. FPT ~ 100000+)
curl 'https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/bars-long-term?ticker=FPT&type=stock&resolution=D&to=1720000000&countBack=5'

# VNDirect — check whether open/high/low/close are in VND or thousands
curl 'https://finfo-api.vndirect.com.vn/v4/stock_prices/?sort=date&size=5&page=1&q=code:FPT~date:gte:2024-01-01~date:lte:2024-02-01'
```

If VNDirect prices look like `100.5` instead of `100500`, set
`vndPriceScale = 1000` in `internal/provider/vndirect.go`.

## Run

```bash
# Backfill from the seed file (26 blue chips):
go run ./cmd/backfill -from 2005-01-01

# Or backfill the full listed universe (~1700 tickers):
go run ./cmd/backfill -fetch-symbols -from 2005-01-01

# Daily incremental (put this in cron after market close, ~15:30 ICT):
go run ./cmd/update
```

Tunables on both commands: `-workers` (concurrent symbols), `-rps` (global
requests/sec — keep this low, ~5, to avoid IP throttling).

Example cron:

```
30 15 * * 1-5 cd /path/to/vnstock-service && DATABASE_URL=... /usr/local/bin/go run ./cmd/update >> update.log 2>&1
```

## Add a source (e.g. SSI)

Implement one method:

```go
type SSI struct{ http *httpx.Client }
func (s *SSI) Name() string { return "ssi" }
func (s *SSI) DailyHistory(ctx context.Context, ticker string, from, to time.Time) ([]provider.Bar, error) {
    // call SSI, map to []Bar in VND, sort ascending by date
}
```

Then add it to the chain in both `cmd/backfill` and `cmd/update`:

```go
src := provider.NewChain(provider.NewTCBS(client), provider.NewSSI(client), vnd)
```

SSI's deep-history feed is **FastConnect Data**, which needs a registered
consumer ID/secret and a token — worth it if you want SSI as an authoritative
source rather than the limited public iBoard chart endpoint.

## Gotchas worth knowing

- **Rate limits.** All providers share one rate-limited client. Don't raise
  `-rps` much; these APIs throttle by IP and a full backfill is thousands of
  requests.
- **Price units.** Normalize everything to VND in the provider before returning
  a `Bar`. TCBS is already VND; verify VNDirect (see above).
- **Adjusted vs raw prices.** This stores raw traded prices. For backtesting you
  usually want split/dividend-adjusted series — VNDirect exposes `adClose` etc.;
  add an `adj_close` column and map it if you need it.
- **History depth.** "20 years" is aspirational: HOSE opened 2000, HNX 2005,
  UPCOM 2009, and free APIs vary in how far back they serve. Expect most tickers
  to start ~2006-2010.
- **Idempotency.** Upserts use `ON CONFLICT (ticker, date)`, so re-running
  backfill or overlapping the daily update never duplicates rows.
- **Responsible use.** These are public endpoints intended for personal/research
  use. Keep request rates modest and check each provider's terms if you plan
  anything commercial.
```
