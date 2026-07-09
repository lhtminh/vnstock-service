"""Throwaway probe: find which vnstock source is reachable from this machine
and what price scale it returns. Run: .venv/Scripts/python.exe python/_probe.py
"""
import sys, traceback

print("python:", sys.version)
try:
    import vnstock
    print("vnstock:", getattr(vnstock, "__version__", "?"))
except Exception as e:
    print("IMPORT FAIL:", e)
    sys.exit(1)


def try_history(source):
    """Fetch FPT recent daily bars via `source`, return (df or None, err)."""
    try:
        # vnstock 3.x style
        from vnstock import Quote
        q = Quote(symbol="FPT", source=source)
        df = q.history(start="2024-01-02", end="2024-01-31", interval="1D")
        return df, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


for source in ("VCI", "TCBS", "MSN"):
    print(f"\n===== source={source} =====")
    df, err = try_history(source)
    if err:
        print("  FAILED:", err)
        continue
    if df is None or len(df) == 0:
        print("  empty result")
        continue
    print("  columns:", list(df.columns))
    print("  rows:", len(df))
    # detect price scale: a large cap like FPT trades ~100k VND. If close ~100
    # the feed is in thousands; if ~100000 it's already VND.
    close_col = "close" if "close" in df.columns else df.columns[-2]
    try:
        last_close = float(df[close_col].iloc[-1])
        scale = "THOUSANDS (x1000 -> VND)" if last_close < 10000 else "already VND"
        print(f"  last close={last_close}  => {scale}")
    except Exception as e:
        print("  scale check failed:", e)
    print(df.tail(3).to_string())
