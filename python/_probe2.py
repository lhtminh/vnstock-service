"""Probe 2: listing/universe API, Quote.history signature (adjusted vs raw?),
and a second symbol's price scale. UTF-8 stdout to avoid cp1252 crashes.
"""
import sys, inspect
sys.stdout.reconfigure(encoding="utf-8")

from vnstock import Quote, Listing

print("=== Quote.history signature ===")
print(inspect.signature(Quote.history))
print("doc:", (Quote.history.__doc__ or "").strip()[:400])

print("\n=== Listing().all_symbols() ===")
try:
    ls = Listing()
    df = ls.all_symbols()
    print("columns:", list(df.columns), "rows:", len(df))
    print(df.head(3).to_string())
except Exception as e:
    print("all_symbols FAILED:", type(e).__name__, str(e)[:200])

print("\n=== Listing().symbols_by_exchange() ===")
try:
    df = Listing().symbols_by_exchange()
    print("columns:", list(df.columns), "rows:", len(df))
    print(df.head(5).to_string())
    if "exchange" in df.columns:
        print("exchange counts:\n", df["exchange"].value_counts().to_string())
except Exception as e:
    print("symbols_by_exchange FAILED:", type(e).__name__, str(e)[:200])

print("\n=== VNM scale sanity (VCI) ===")
try:
    df = Quote(symbol="VNM", source="VCI").history(start="2024-06-03", end="2024-06-07", interval="1D")
    print(df.to_string())
except Exception as e:
    print("VNM FAILED:", type(e).__name__, str(e)[:200])
