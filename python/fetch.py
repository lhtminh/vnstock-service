#!/usr/bin/env python
"""vnstock bridge for vnstock-service (Go).

The direct TCBS/VNDirect HTTP endpoints the Go providers used are no longer
usable (TCBS IP-blocks non-allowlisted egress with a blanket 404; VNDirect's
finfo API was decommissioned — its hostname now resolves to a private 10.x IP).
This helper fetches the same daily OHLCV through the maintained `vnstock`
library, whose VCI (Vietcap) source is still reachable.

Contract (kept narrow so the Go `vnstock` provider stays trivial):

  history:  fetch.py history --symbol FPT --start 2005-01-01 --end 2026-07-09 --out FILE
            writes a JSON array to FILE:
              [{"date":"YYYY-MM-DD","open":..,"high":..,"low":..,
                "close":..,"volume":..}, ...]  ascending by date, prices in VND.

  symbols:  fetch.py symbols --out FILE
            writes a JSON array to FILE:
              [{"ticker":"FPT","exchange":"HOSE"}, ...]

Why write to --out instead of stdout: vnstock prints promotional banners and
logs to stdout/stderr; routing the payload through a file keeps the JSON the Go
side parses free of that noise.

DATA-INTEGRITY NOTES (see also README "Gotchas"):
  * Price unit: VCI returns prices in THOUSANDS of VND, so we multiply by
    PRICE_SCALE (1000) to honor the "normalize to VND inside the provider"
    invariant. Verify against a chart if VCI ever changes this.
  * Adjustment: VCI `history` returns SPLIT/DIVIDEND-ADJUSTED prices, not raw
    traded prices. This is in tension with the daily_prices "raw + immutable"
    invariant (schema.sql). It is surfaced here rather than hidden; revisit if a
    raw feed becomes available (e.g. licensed SSI FastConnect).
"""
import argparse
import datetime
import json
import sys

PRICE_SCALE = 1000.0  # VCI quotes in thousands of VND -> VND
SOURCE = "VCI"
KEEP_EXCHANGES = {"HOSE", "HNX", "UPCOM"}


def fetch_history(symbol: str, start: str, end: str):
    from vnstock import Quote

    df = Quote(symbol=symbol, source=SOURCE).history(
        start=start, end=end, interval="1D"
    )
    if df is None or len(df) == 0:
        return []
    out = []
    for _, r in df.iterrows():
        t = r["time"]
        # Expect a pandas Timestamp / datetime / date. Fail loudly on anything
        # else rather than silently slicing str(t) into a bad date that the Go
        # side would then drop without a trace.
        if not isinstance(t, (datetime.datetime, datetime.date)) and not hasattr(t, "strftime"):
            raise TypeError(f"unexpected 'time' type from VCI for {symbol}: {type(t).__name__} ({t!r})")
        date = t.strftime("%Y-%m-%d")
        out.append(
            {
                "date": date,
                "open": round(float(r["open"]) * PRICE_SCALE, 2),
                "high": round(float(r["high"]) * PRICE_SCALE, 2),
                "low": round(float(r["low"]) * PRICE_SCALE, 2),
                "close": round(float(r["close"]) * PRICE_SCALE, 2),
                "volume": int(r["volume"]),
            }
        )
    out.sort(key=lambda b: b["date"])
    return out


def fetch_symbols():
    from vnstock import Listing

    df = Listing().symbols_by_exchange()
    out = []
    for _, r in df.iterrows():
        typ = str(r.get("type", "")).lower()
        if typ and typ != "stock":
            continue
        exch = str(r.get("exchange", "")).upper()
        if exch not in KEEP_EXCHANGES:
            continue
        out.append({"ticker": str(r["symbol"]).upper(), "exchange": exch})
    # de-dup while preserving order
    seen = set()
    uniq = []
    for s in out:
        if s["ticker"] in seen:
            continue
        seen.add(s["ticker"])
        uniq.append(s)
    return uniq


def main():
    ap = argparse.ArgumentParser(description="vnstock bridge for vnstock-service")
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("history")
    h.add_argument("--symbol", required=True)
    h.add_argument("--start", required=True)
    h.add_argument("--end", required=True)
    h.add_argument("--out", required=True)

    s = sub.add_parser("symbols")
    s.add_argument("--out", required=True)

    args = ap.parse_args()
    if args.cmd == "history":
        data = fetch_history(args.symbol, args.start, args.end)
    else:
        data = fetch_symbols()

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # surface a clean error to the Go side via stderr + exit
        sys.stderr.write(f"fetch.py error: {type(e).__name__}: {e}\n")
        sys.exit(1)
