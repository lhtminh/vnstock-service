# vnstock-service

Fetches Vietnamese daily stock history (OHLCV) and stores it in Postgres.
Go + pgx for orchestration/storage; data is sourced through the maintained
[`vnstock`](https://github.com/thinh-vu/vnstock) Python library. One-time
**backfill** + daily **update**.

## Why the Python bridge

The service originally called the TCBS and VNDirect JSON endpoints directly from
Go. Both are now unusable:

- **TCBS** (`apipubaws.tcbs.com.vn`) IP-blocks non-allowlisted egress — every
  route returns a blanket `404 {"message":"Service not found"}`.
- **VNDirect** (`finfo-api.vndirect.com.vn`) was decommissioned — the hostname
  resolves to a private `10.x` address even via public DNS, so it is
  unreachable from the internet.

So daily bars now come from **VCI (Vietcap)** via `vnstock`, which is still
reachable. The Go `Provider` interface is unchanged: `internal/provider/vnstock.go`
shells out to `python/fetch.py`, which returns JSON that decodes into `[]Bar`.
The old `tcbs.go` / `vndirect.go` remain in the chain as (currently dead)
fallbacks so the moment either recovers it is used again automatically.

## Layout

```
cmd/backfill/    one-time full history load
cmd/update/      incremental daily refresh (run from cron)
python/
    fetch.py     vnstock bridge: emits OHLCV / symbol-universe JSON
internal/httpx/  shared HTTP client: global rate limit + retry/backoff
internal/provider/
    provider.go  the Provider interface + Bar/Symbol types
    vnstock.go   PRIMARY source — bridges to python/fetch.py (VCI/Vietcap)
    tcbs.go      legacy HTTP source (currently IP-blocked)
    vndirect.go  legacy HTTP source + symbol listing (currently decommissioned)
    chain.go     fallback chain across providers
internal/store/  Postgres schema + pgx upserts
```

## Setup

1. **Python 3.11 environment with vnstock.** Use 3.11 (or 3.10/3.12) — do NOT
   use 3.14 yet: its only Windows numpy build is an experimental MinGW wheel
   that segfaults on import.

   ```bash
   py -3.11 -m venv .venv                     # Windows; use python3.11 elsewhere
   .venv/Scripts/python -m pip install -U pip
   .venv/Scripts/python -m pip install -r requirements.txt
   ```

   The Go provider auto-discovers `./.venv` when run from the repo root. To point
   at a different interpreter or script, set `VNSTOCK_PYTHON` / `VNSTOCK_SCRIPT`.
   `.venv/` is git-ignored — keep it locally, recreate it from `requirements.txt`;
   don't commit it.

2. **Postgres** (Docker is easiest):

   ```bash
   docker run --name vnstock-pg -e POSTGRES_PASSWORD=postgres \
     -e POSTGRES_DB=vnstock -p 5432:5432 -d postgres:16
   export DATABASE_URL='postgres://postgres:postgres@localhost:5432/vnstock?sslmode=disable'
   ```

3. **Go deps:**

   ```bash
   go mod tidy
   ```

## Verify the source FIRST

`vnstock` wraps unofficial broker feeds; field names and units drift. Confirm
once before a big run (from the repo root):

```bash
.venv/Scripts/python python/fetch.py history --symbol FPT \
  --start 2024-01-02 --end 2024-01-10 --out fpt.json && cat fpt.json
```

Sanity checks:
- **Units.** `close` for FPT should be ~`70000` (VND), not ~`70`. VCI quotes in
  *thousands*; `fetch.py` multiplies by `PRICE_SCALE = 1000`. If a future
  vnstock/VCI change alters this, adjust `PRICE_SCALE`.
- **Adjustment.** VCI `history` returns **split/dividend-ADJUSTED** prices, not
  raw traded prices (see Gotchas).

## Run

Run from the repo root so the provider finds `./.venv` and `python/fetch.py`.

```bash
# Backfill from the seed file (26 blue chips):
go run ./cmd/backfill -from 2005-01-01

# Or backfill the full listed universe (~1500 tickers, from vnstock):
go run ./cmd/backfill -fetch-symbols -from 2005-01-01

# Daily incremental (cron, after market close ~15:30 ICT):
go run ./cmd/update
```

**Windows gotcha:** `go run ./cmd/update` (or any binary named `update.exe`)
triggers Windows UAC *Installer Detection* and fails with "requires elevation".
Build the daily command to a name that doesn't contain `update`/`install`/
`setup`/`patch`:

```powershell
go build -o vn-refresh.exe ./cmd/update
./vn-refresh.exe
```

Tunables: `-workers` (concurrent symbols) and `-rps`. **Note:** the vnstock path
does not use the shared rate-limited HTTP client — each symbol spawns a
short-lived Python process, so its request rate is bounded by `-workers`, not
`-rps` (`-rps` still governs the legacy TCBS/VNDirect fallbacks). Keep
`-workers` modest (≈3–6) to avoid VCI throttling and hold memory down; a
full-universe backfill pays a per-symbol Python startup cost, so expect it to be
slow (fine as an overnight one-off).

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
src := provider.NewChain(vnstk, provider.NewSSI(client), provider.NewTCBS(client))
```

SSI's deep-history feed is **FastConnect Data**, which needs a registered
consumer ID/secret and a token — and, unlike VCI, can serve **raw** (unadjusted)
prices, which is what `daily_prices` is meant to hold.

## Gotchas worth knowing

- **Adjusted vs raw prices — important.** `daily_prices` is designed to hold
  *raw* traded prices (adjustment is computed at feature time from
  `corporate_actions`). VCI, however, returns split/dividend-**adjusted** prices,
  so the current feed is in tension with that invariant. This is documented, not
  hidden; `daily_prices` now carries an `is_adjusted` BOOLEAN column (default
  `true`) that flags this — treat the stored series as adjusted until a raw feed
  (e.g. SSI FastConnect) is wired in and sets it `false`. Run the
  `quant-data-integrity` subagent on this change.
- **Price units.** Normalize everything to VND in the provider before returning
  a `Bar`. `fetch.py` handles the VCI ×1000 conversion.
- **Rate limits.** Keep `-workers` modest; VCI throttles and a full backfill is
  thousands of requests. The vnstock path bypasses the shared `httpx` limiter.
- **History depth.** "20 years" is aspirational: HOSE opened 2000, HNX 2005,
  UPCOM 2009, and VCI's depth varies by ticker. Expect many names to start
  ~2010–2015.
- **Survivorship.** The symbol listing returns only currently-LISTED names, so
  delisted tickers are not ingested by this path — the schema keeps them
  (`symbols.status`), but populating them needs a separate data source.
- **Idempotency.** Upserts use `ON CONFLICT (ticker, date)`, so re-running
  backfill or overlapping the daily update never duplicates rows.
- **Python 3.14.** Avoid for now — the only Windows numpy build available for it
  is an experimental MinGW wheel that segfaults. Use 3.11.
- **Responsible use.** These are public endpoints intended for personal/research
  use. Keep request rates modest and check terms before anything commercial.
```
