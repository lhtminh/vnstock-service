# CLAUDE.md

Guidance for Claude Code (and any AI agent) working in this repository. Read
this before making changes. It encodes design decisions that are easy to
accidentally undo.

## What this is

A Go + Postgres service that fetches Vietnamese daily stock history (OHLCV) from
public broker APIs and stores it, structured so the data can later train quant
models (trend, liquidity, behaviour, alpha). Two entry points: a one-time
`backfill` and a daily incremental `update`.

## Architecture

- `internal/provider/` — a `Provider` interface over each data source. `tcbs.go`
  (primary, VND prices, deep history), `vndirect.go` (fallback + symbol
  universe), `chain.go` (tries providers in order, first non-empty wins). Add a
  source by implementing `Provider`; do not special-case sources in callers.
- `internal/httpx/` — ONE shared rate-limited HTTP client with retry/backoff.
- `internal/store/` — pgx/pgxpool persistence. `schema.sql` is embedded and run
  by `EnsureSchema`.
- `cmd/backfill`, `cmd/update` — orchestration (worker pool over symbols).

## Invariants — do NOT violate these

1. **Prices are normalized to VND inside each provider** before a `Bar` is
   returned. TCBS is already VND; VNDirect may return thousands (see
   `vndPriceScale`). Never push unit conversion downstream.
2. **Raw prices in `daily_prices` are immutable.** There is deliberately NO
   `adj_close` column. Split/dividend adjustment is computed at feature time
   from the `corporate_actions` table. Do not add a stored adjusted-price column
   — adjustment factors change with every new action and would silently mutate
   history, breaking reproducibility.
3. **Point-in-time correctness.** `financial_statements.publish_date` and
   `index_membership.effective_date`/`end_date` exist to prevent look-ahead.
   Any feature query MUST filter by "knowable as of date D"
   (`publish_date <= D`, membership `effective_date <= D AND (end_date IS NULL
   OR end_date > D)`). Never join fundamentals on fiscal period alone.
4. **Survivorship safety.** `symbols` keeps delisted tickers (`status`,
   `delisted_date`). Never delete or filter out delisted names in storage. Note
   the current ingestion uses VNDirect `status:LISTED`, which EXCLUDES delisted
   tickers — populating them needs a separate data path (not yet built).
5. **One shared rate-limited client.** All providers/workers share the single
   `httpx.Client`. Do not create per-provider clients or raise `-rps` casually;
   these APIs throttle by IP.
6. **Upserts are idempotent** (`ON CONFLICT`). Keep them that way so re-running
   backfill or overlapping the daily update never duplicates rows.
7. **`schema.sql` must stay idempotent and additive** (`CREATE TABLE IF NOT
   EXISTS`, `ADD COLUMN IF NOT EXISTS`). It doubles as the migration path for
   existing databases. Validated: applies cleanly on a fresh DB, upgrades a v1
   DB in place without touching existing rows, and runs twice with no errors.

## The endpoints are unofficial — verify before trusting

TCBS/VNDirect endpoints are public but reverse-engineered and drift over time.
Before any large run or when debugging empty results, confirm with curl (see
`README.md`), especially:
- VNDirect price **units** (VND vs thousands).
- Actual **history depth** per source. "20 years" is aspirational: HNX opened
  2005, UPCOM 2009, and free feeds are often only reliably deep to ~2015. The
  pagination code fetches as much as the source serves; it does not guarantee
  20 years. For guaranteed deep history, a licensed feed (SSI FastConnect) is
  needed.

## Build, run, and test

Dev database (throwaway Postgres):

```bash
docker run --name vnstock-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=vnstock \
  -p 5432:5432 -d postgres:16
export DATABASE_URL='postgres://postgres:postgres@localhost:5432/vnstock?sslmode=disable'
```

Build and run:

```bash
go mod tidy                                       # needs network (pulls pgx)
go build ./...
go run ./cmd/backfill -from 2005-01-01            # seed-file universe
go run ./cmd/backfill -fetch-symbols -from 2005-01-01   # full listed universe
go run ./cmd/update                               # daily incremental (cron)
```

Flags — backfill: `-from`, `-seed`, `-fetch-symbols`, `-workers`, `-rps`.
Flags — update: `-overlap-days`, `-workers`, `-rps`. Keep `-rps` low (~5).

Pre-commit checks:

```bash
gofmt -w .          # format
go vet ./...        # static checks
go build ./...      # must compile
go test ./...       # NOTE: no *_test.go files exist yet — this currently runs nothing
```

Validate the schema in isolation (this is what proves the idempotent upgrade
path — run it TWICE against a DB; the second run must complete with only
"already exists" notices, no errors):

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f internal/store/schema.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f internal/store/schema.sql   # idempotency check
```

(At runtime the app applies it automatically via `EnsureSchema`.)

Verify the unofficial endpoints before a big backfill (full commands in
`README.md`), e.g.:

```bash
curl 'https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/bars-long-term?ticker=FPT&type=stock&resolution=D&to=1720000000&countBack=5'
```

## Current status

Built and working: provider chain (TCBS + VNDirect), rate-limited client,
Postgres store with idempotent upserts, v2 quant-ready schema (8 tables),
backfill + update commands.

NOT yet built (the schema supports these; the writers do not exist):
- Store methods + provider calls for `corporate_actions`, `foreign_flows`,
  `financial_statements`, `index_series`, `index_membership`,
  `trading_calendar`.
- `daily_prices` currently only populates OHLCV + volume; `value`, price bands,
  put-through, and `bar_status` are unpopulated.
- Delisted-ticker ingestion (survivorship data path).
- A `cmd/probe` coverage check (proposed) to report earliest available date per
  source before a full backfill.
- Automated tests. There are no `*_test.go` files yet; `go test ./...` runs
  nothing. Good first targets: TCBS/VNDirect JSON decoding into `Bar` (table
  tests against captured fixtures), the backward-pagination termination logic,
  and `UpsertBars` idempotency against a test DB.

## Conventions

- Standard Go layout. Run the pre-commit checks above (`gofmt -w`, `go vet`,
  `go build`) before committing.
- Keep provider response structs close to the raw JSON, with a comment pointing
  to a curl command that verifies the shape.
- Prefer small, reviewable changes gated by phase (Explore → Plan → Implement →
  Commit). When adding a data domain, land the schema, then the store writer,
  then the provider call, as separate steps.
- After changing a provider, the store, or `schema.sql`, invoke the
  `quant-data-integrity` subagent (`.claude/agents/`) on the diff — it checks the
  invariants above (look-ahead, survivorship, adjusted-price mutation, VND units,
  shared rate limiter, idempotency). Invoke it explicitly ("use the
  quant-data-integrity subagent on my last change"); don't rely on auto-routing.
