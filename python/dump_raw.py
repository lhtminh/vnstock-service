#!/usr/bin/env python
"""Raw vnstock dump for exploration ("raw data first" — no schema mapping).

For each ticker in a universe (default: the VN100 group), calls every vnstock
endpoint that is actually reachable from this network/library version and writes
the UNTRANSFORMED dataframe to CSV — one CSV per endpoint, with a `ticker`
column prepended, under ./raw. Plus market-wide dumps: index OHLCV and the
current VN30/VN100 membership snapshots.

Only VCI-reachable endpoints are included. Deliberately NOT attempted (verified
unavailable in this vnstock: sources are KBS/VCI/MSN/FMP, TCBS is gone):
foreign/proprietary flows, company.dividends, insider_deals, capital_history.

Usage (from repo root):
    set PYTHONUTF8=1
    .venv/Scripts/python python/dump_raw.py                 # VN100, quarter
    .venv/Scripts/python python/dump_raw.py --limit 10      # first 10 (smoke)
    .venv/Scripts/python python/dump_raw.py --period year --start 2015-01-01

Notes:
  * vnstock prints a Vietnamese promo banner to stdout that crashes on Windows
    cp1252. We reconfigure stdout to UTF-8 AND swallow stdout for the whole run
    (thread-safe: set once, never swapped), routing progress to stderr.
  * CSVs are written utf-8-sig so Excel renders Vietnamese correctly.
  * Prices from VCI are split/dividend-ADJUSTED and in VND-thousands here (raw,
    unscaled — this dump does NOT apply the x1000 that python/fetch.py does).
"""
import argparse
import collections
import datetime
import io
import os
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

warnings.filterwarnings("ignore")

# --- make output robust on Windows consoles and silence vnstock banners -------
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
_ERR = sys.stderr
sys.stdout = io.StringIO()  # swallow vnstock's banner/promo spam for the whole run


def log(msg: str) -> None:
    print(msg, file=_ERR, flush=True)


import pandas as pd  # noqa: E402  (after stdout is swapped)
import vnstock  # noqa: E402
from vnstock import Listing, Vnstock  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
SOURCE = "VCI"
INDEX_CODES = ["VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPCOMINDEX"]


class RateLimiter:
    """Block so no more than `rpm` calls happen in any rolling 60s window.

    vnstock hard-stops (and may terminate the process) when its per-minute cap
    is exceeded, so we self-govern well under it: guest=20, community key=60.
    """

    def __init__(self, rpm: int):
        self.rpm = rpm
        self._lock = threading.Lock()
        self._calls = collections.deque()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60:
                    self._calls.popleft()
                if len(self._calls) < self.rpm:
                    self._calls.append(now)
                    return
                wait = 60 - (now - self._calls[0]) + 0.05
            time.sleep(min(max(wait, 0.05), 5))


LIMITER = RateLimiter(18)  # replaced in main() once we know the tier


def dedup_columns(cols):
    seen, out = {}, []
    for c in cols:
        c = str(c)
        if c in seen:
            seen[c] += 1
            out.append(f"{c}.{seen[c]}")
        else:
            seen[c] = 0
            out.append(c)
    return out


def tag(df, **cols):
    """Prepend id columns (e.g. ticker=...) to a raw dataframe, de-duping labels."""
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    df.columns = dedup_columns(df.columns)
    for k, v in reversed(list(cols.items())):
        if k in df.columns:  # endpoint already returns this id col (e.g. events has 'ticker')
            df = df.drop(columns=[k])
        df.insert(0, k, v)
    return df


def dump_ticker(ticker: str, start: str, end: str, period: str):
    """Return {endpoint_name: dataframe|None} of raw pulls for one ticker."""
    out = {}

    def grab(name, fn):
        try:
            LIMITER.acquire()
            out[name] = tag(fn(), ticker=ticker)
        except SystemExit:
            # vnstock tried to exit on a rate-limit hit; back off, keep going.
            out[name] = None
            log(f"  RATE {ticker:6} {name:16} backing off 60s")
            time.sleep(60)
        except Exception as e:
            out[name] = None
            log(f"  FAIL {ticker:6} {name:16} {type(e).__name__}: {str(e)[:70]}")

    st = Vnstock().stock(symbol=ticker, source=SOURCE)
    grab("daily_prices", lambda: st.quote.history(start=start, end=end, interval="1D"))
    grab("balance_sheet", lambda: st.finance.balance_sheet(period=period, lang="en"))
    grab("income_statement", lambda: st.finance.income_statement(period=period, lang="en"))
    grab("cash_flow", lambda: st.finance.cash_flow(period=period, lang="en"))
    grab("financial_ratio", lambda: st.finance.ratio(period=period, lang="en"))
    grab("company_events", lambda: st.company.events())
    grab("shareholders", lambda: st.company.shareholders())
    grab("officers", lambda: st.company.officers())
    grab("overview", lambda: st.company.overview())
    grab("ratio_summary", lambda: st.company.ratio_summary())
    return ticker, out


def write_concat(frames, name: str) -> int:
    frames = [f for f in frames if f is not None and len(f)]
    path = RAW / f"{name}.csv"
    if not frames:
        pd.DataFrame().to_csv(path, index=False)
        log(f"  {name:18}      0 rows  (empty)")
        return 0
    df = pd.concat(frames, ignore_index=True, sort=False)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    log(f"  {name:18} {len(df):6} rows -> raw/{name}.csv")
    return len(df)


def resolve_universe(limit: int):
    L = Listing()
    try:
        syms = list(L.symbols_by_group("VN100"))
    except Exception as e:
        log(f"VN100 group failed ({e}); falling back to HOSE listing")
        syms = list(L.symbols_by_group("HOSE"))
    syms = [str(s).upper() for s in syms][:limit]
    return syms


def dump_indices(start: str, end: str):
    frames = []
    for code in INDEX_CODES:
        try:
            LIMITER.acquire()
            df = Vnstock().stock(symbol=code, source=SOURCE).quote.history(
                start=start, end=end, interval="1D"
            )
            frames.append(tag(df, index_code=code))
        except Exception as e:
            log(f"  FAIL index {code}: {type(e).__name__}: {str(e)[:70]}")
    write_concat(frames, "index_series")


def dump_membership():
    today = datetime.date.today().isoformat()
    L = Listing()
    for grp in ("VN30", "VN100"):
        try:
            LIMITER.acquire()
            syms = [str(s).upper() for s in L.symbols_by_group(grp)]
            df = pd.DataFrame({"index_code": grp, "ticker": syms, "snapshot_date": today})
            df.to_csv(RAW / f"membership_{grp.lower()}.csv", index=False, encoding="utf-8-sig")
            log(f"  membership_{grp.lower():12} {len(df):6} rows -> raw/membership_{grp.lower()}.csv")
        except Exception as e:
            log(f"  FAIL membership {grp}: {type(e).__name__}: {str(e)[:70]}")


ENDPOINTS = [
    "daily_prices", "balance_sheet", "income_statement", "cash_flow",
    "financial_ratio", "company_events", "shareholders", "officers",
    "overview", "ratio_summary",
]


def main():
    global LIMITER
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--period", choices=["quarter", "year"], default="quarter")
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default=datetime.date.today().isoformat())
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--rpm", type=int, default=0, help="requests/min cap; 0 = auto by tier")
    args = ap.parse_args()

    # API key (community tier = 60/min). Passed via env so it never lands in a
    # process list or shell history.
    key = os.environ.get("VNSTOCK_API_KEY", "").strip()
    if key:
        try:
            ok = vnstock.change_api_key(key)
            log(f"Community API key applied (change_api_key -> {ok})")
        except Exception as e:
            log(f"WARNING: change_api_key failed ({type(e).__name__}: {e}); continuing as guest")
            key = ""
    else:
        log("WARNING: VNSTOCK_API_KEY not set — running as GUEST (20 req/min).")

    rpm = args.rpm or (55 if key else 18)
    LIMITER = RateLimiter(rpm)

    RAW.mkdir(exist_ok=True)
    tickers = resolve_universe(args.limit)
    log(f"Universe: {len(tickers)} tickers | period={args.period} | {args.start}..{args.end} "
        f"| workers={args.workers} | rpm={rpm}")
    pd.DataFrame({"ticker": tickers}).to_csv(RAW / "tickers.csv", index=False)

    def flush(buckets):
        for name in ENDPOINTS:
            write_concat(buckets.get(name, []), name)

    buckets: dict[str, list] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(dump_ticker, t, args.start, args.end, args.period): t for t in tickers}
        for fut in as_completed(futs):
            ticker, res = fut.result()
            for name, df in res.items():
                buckets.setdefault(name, []).append(df)
            done += 1
            if done % 10 == 0 or done == len(tickers):
                log(f"... {done}/{len(tickers)} tickers fetched")
            if done % 25 == 0 and done < len(tickers):
                log(f"  checkpoint at {done} tickers")
                flush(buckets)  # crash insurance

    log("Writing per-endpoint CSVs:")
    flush(buckets)
    log("Market-wide:")
    dump_indices(args.start, args.end)
    dump_membership()
    log(f"DONE -> {RAW}")


if __name__ == "__main__":
    main()
