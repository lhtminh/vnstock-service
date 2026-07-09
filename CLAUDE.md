# CLAUDE.md

Guidance for Claude Code (and any AI agent) working in this repository. Read
this before making changes. It encodes design decisions that are easy to
accidentally undo.

## What this is

A Go + Postgres service that fetches Vietnamese daily stock history (OHLCV) from
public broker feeds (currently VCI/Vietcap via the `vnstock` Python library) and
stores it, structured so the data can later train quant
models (trend, liquidity, behaviour, alpha). Two entry points: a one-time
`backfill` and a daily incremental `update`.

## Architecture

- `internal/provider/` — a `Provider` interface over each data source.
  `vnstock.go` (**primary** — bridges to `python/fetch.py`, which reads VCI/Vietcap
  via the `vnstock` library; also supplies the symbol universe), `tcbs.go` /
  `vndirect.go` (legacy HTTP sources, currently non-functional — see "sources"
  below — kept in the chain as fallbacks), `chain.go` (tries providers in order,
  first non-empty wins; use `DailyHistorySourced` to record which provider served
  in the `source` column). Add a source by implementing `Provider`; do not
  special-case sources in callers.
- `python/fetch.py` — the vnstock bridge. Emits OHLCV / symbol JSON to a `--out`
  file (NOT stdout, which vnstock pollutes with promo banners) and normalizes
  VCI's thousands-of-VND to VND. Runs in a repo-local `./.venv` (Python 3.11).
- `internal/httpx/` — ONE shared rate-limited HTTP client with retry/backoff.
  Governs the legacy TCBS/VNDirect providers; the vnstock path does NOT use it.
- `internal/store/` — pgx/pgxpool persistence. `schema.sql` is embedded and run
  by `EnsureSchema`.
- `cmd/backfill`, `cmd/update` — orchestration (worker pool over symbols).

## Invariants — do NOT violate these

1. **Prices are normalized to VND inside each provider** before a `Bar` is
   returned. For the vnstock provider this happens in `python/fetch.py` (VCI
   quotes in thousands → ×1000 = VND); TCBS was already VND; VNDirect used
   `vndPriceScale`. Never push unit conversion downstream.
2. **Raw prices in `daily_prices` are immutable.** There is deliberately NO
   `adj_close` column. Split/dividend adjustment is computed at feature time
   from the `corporate_actions` table. Do not add a stored adjusted-price column
   — adjustment factors change with every new action and would silently mutate
   history, breaking reproducibility.
   ⚠ **KNOWN GAP:** the current primary feed (VCI via vnstock) returns
   split/dividend-**adjusted** prices, so `daily_prices` presently holds adjusted
   data — in tension with this invariant. Until a raw feed (e.g. SSI FastConnect)
   is wired in, treat the stored series as adjusted. Proposed mitigation is an
   additive `is_adjusted` flag; do NOT "resolve" this by adding a mutating
   `adj_close`.
3. **Point-in-time correctness.** `financial_statements.publish_date` and
   `index_membership.effective_date`/`end_date` exist to prevent look-ahead.
   Any feature query MUST filter by "knowable as of date D"
   (`publish_date <= D`, membership `effective_date <= D AND (end_date IS NULL
   OR end_date > D)`). Never join fundamentals on fiscal period alone.
4. **Survivorship safety.** `symbols` keeps delisted tickers (`status`,
   `delisted_date`). Never delete or filter out delisted names in storage. Note
   the current ingestion uses the vnstock listing (LISTED names only), which
   EXCLUDES delisted tickers — populating them needs a separate data path (not
   yet built).
5. **One shared rate-limited client.** The HTTP providers (TCBS/VNDirect) share
   the single `httpx.Client`; do not create per-provider clients or raise `-rps`
   casually — these APIs throttle by IP. The vnstock provider spawns a Python
   subprocess per call and does NOT go through `httpx`, so its effective rate is
   bounded by `-workers`, not `-rps`; keep `-workers` modest (~3–6) to avoid VCI
   throttling.
6. **Upserts are idempotent** (`ON CONFLICT`). Keep them that way so re-running
   backfill or overlapping the daily update never duplicates rows.
7. **`schema.sql` must stay idempotent and additive** (`CREATE TABLE IF NOT
   EXISTS`, `ADD COLUMN IF NOT EXISTS`). It doubles as the migration path for
   existing databases. Validated: applies cleanly on a fresh DB, upgrades a v1
   DB in place without touching existing rows, and runs twice with no errors.

## The data sources are unofficial — verify before trusting

These are public, reverse-engineered feeds that drift and break. Current state
(2026-07):
- **TCBS** (`apipubaws.tcbs.com.vn`) — IP-blocks non-allowlisted egress; every
  route returns a blanket `404 "Service not found"`. `tcbs.go` is dead from most
  networks.
- **VNDirect** (`finfo-api.vndirect.com.vn`) — decommissioned; the hostname
  resolves to a private `10.x` IP even via public DNS. `vndirect.go` is dead.
- **VCI/Vietcap via `vnstock`** — the current working primary. Verify before a
  big run (from the repo root):
  `.venv/Scripts/python python/fetch.py history --symbol FPT --start 2024-01-02 --end 2024-01-10 --out fpt.json`
  Check `close` for FPT ≈ 70000 VND (not ~70 — VCI is in thousands, `fetch.py`
  ×1000), and remember VCI prices are **adjusted** (invariant #2 gap).

**History depth** is aspirational: HNX opened 2005, UPCOM 2009, and free feeds
vary; expect many tickers to start ~2010–2015. For guaranteed deep AND raw
(unadjusted) history, a licensed feed (SSI FastConnect) is needed.

## Build, run, and test

Dev database (throwaway Postgres):

```bash
docker run --name vnstock-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=vnstock \
  -p 5432:5432 -d postgres:16
export DATABASE_URL='postgres://postgres:postgres@localhost:5432/vnstock?sslmode=disable'
```

Python bridge (required for the vnstock provider — use Python 3.11, NOT 3.14
whose only Windows numpy build segfaults):

```bash
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # installs vnstock
```

Build and run (from the repo root, so the provider finds `./.venv` and
`python/fetch.py`):

```bash
go mod tidy                                       # needs network (pulls pgx)
go build ./...
go run ./cmd/backfill -from 2005-01-01            # seed-file universe
go run ./cmd/backfill -fetch-symbols -from 2005-01-01   # full listed universe
go run ./cmd/update                               # daily incremental (cron)
```

Windows: `go run ./cmd/update` produces `update.exe`, which trips UAC installer
detection ("requires elevation"). Build to a safe name instead:
`go build -o vn-refresh.exe ./cmd/update && ./vn-refresh.exe`.

Flags — backfill: `-from`, `-seed`, `-fetch-symbols`, `-workers`, `-rps`.
Flags — update: `-overlap-days`, `-workers`, `-rps`. `-rps` governs only the
legacy HTTP providers; the vnstock path is bounded by `-workers` (keep ~3–6).

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

Verify the data source before a big backfill (the vnstock/VCI path):

```bash
.venv/Scripts/python python/fetch.py history --symbol FPT \
  --start 2024-01-02 --end 2024-01-10 --out fpt.json
```

## Current status

Built and working: vnstock/VCI provider (via `python/fetch.py`) as primary with
TCBS/VNDirect as (currently dead) fallbacks, rate-limited client, Postgres store
with idempotent upserts, v2 quant-ready schema (8 tables), backfill + update
commands. Verified end-to-end: ~91k bars for the 26-symbol seed set, 2006→2026.

NOT yet built (the schema supports these; the writers do not exist):
- Store methods + provider calls for `corporate_actions`, `foreign_flows`,
  `financial_statements`, `index_series`, `index_membership`,
  `trading_calendar`.
- `daily_prices` currently only populates OHLCV + volume; `value`, price bands,
  put-through, and `bar_status` are unpopulated.
- Raw (unadjusted) prices — the VCI feed is adjusted; no raw source is wired in.
- Delisted-ticker ingestion (survivorship data path).
- A `cmd/probe` coverage check (proposed) to report earliest available date per
  source before a full backfill.
- Automated tests. There are no `*_test.go` files yet; `go test ./...` runs
  nothing. Good first targets: `vnstock.go` JSON decode into `Bar` (fixture
  table tests incl. the ×1000 scale) + `fetch.py`'s error path, and `UpsertBars`
  idempotency against a test DB.

## Conventions

- Standard Go layout. Run the pre-commit checks above (`gofmt -w`, `go vet`,
  `go build`) before committing.
- Keep provider response structs close to the raw JSON. For HTTP providers,
  comment with a curl that verifies the shape; for the vnstock provider, the
  contract is the `--out` JSON that `python/fetch.py` writes.
- The `.venv/` is git-ignored and must stay so — recreate it from
  `requirements.txt`; never commit the venv.
- Prefer small, reviewable changes gated by phase (Explore → Plan → Implement →
  Commit). When adding a data domain, land the schema, then the store writer,
  then the provider call, as separate steps.
- After changing a provider, the store, or `schema.sql`, invoke the
  `quant-data-integrity` subagent (`.claude/agents/`) on the diff — it checks the
  invariants above (look-ahead, survivorship, adjusted-price mutation, VND units,
  shared rate limiter, idempotency). Invoke it explicitly ("use the
  quant-data-integrity subagent on my last change"); don't rely on auto-routing.
