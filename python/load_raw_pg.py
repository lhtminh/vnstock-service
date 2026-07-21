#!/usr/bin/env python
"""Load the raw/*.csv dumps into Postgres as raw_* landing tables.

Each CSV becomes a table `raw_<stem>` with ALL columns typed TEXT (faithful raw
landing — no coercion, no scaling). Loading is bulk COPY streamed into the
dockerized Postgres via `docker exec -i ... psql \\copy ... FROM STDIN`.

Deliberately does NOT write to the curated tables (daily_prices, index_series,
financial_statements, ...): the raw VCI prices are ADJUSTED and in THOUSANDS of
VND, so they must not be mixed into daily_prices (VND, raw-immutable invariant).
Normalization raw_* -> curated is a separate, reviewed step.

Usage (from repo root):
    .venv/Scripts/python python/load_raw_pg.py
    .venv/Scripts/python python/load_raw_pg.py --container vnstock-pg --db vnstock --user postgres
"""
import argparse
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"


def psql(container, user, db, sql):
    """Run a single SQL statement via docker exec psql, return stdout."""
    p = subprocess.run(
        ["docker", "exec", container, "psql", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-tAc", sql],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"psql failed: {sql[:60]}...\n{p.stderr.strip()}")
    return p.stdout.strip()


def header_of(path: Path):
    # utf-8-sig strips the BOM so the first column name is clean.
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return next(csv.reader(f))


def load_csv(container, user, db, path: Path):
    table = "raw_" + path.stem
    cols = header_of(path)
    coldefs = ", ".join(f'"{c}" TEXT' for c in cols)
    psql(container, user, db, f'DROP TABLE IF EXISTS "{table}"')
    psql(container, user, db, f'CREATE TABLE "{table}" ({coldefs})')

    # Stream the raw file bytes straight into psql's \copy (HEADER true skips the
    # header line, which also consumes the BOM). No re-encoding => Vietnamese safe.
    copy_sql = f"\\copy \"{table}\" FROM STDIN WITH (FORMAT csv, HEADER true)"
    with path.open("rb") as f:
        p = subprocess.run(
            ["docker", "exec", "-i", container, "psql", "-U", user, "-d", db,
             "-v", "ON_ERROR_STOP=1", "-c", copy_sql],
            stdin=f, capture_output=True, text=True,
        )
    if p.returncode != 0:
        raise RuntimeError(f"COPY failed for {table}:\n{p.stderr.strip()}")
    n = psql(container, user, db, f'SELECT count(*) FROM "{table}"')
    return table, len(cols), int(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="vnstock-pg")
    ap.add_argument("--db", default="vnstock")
    ap.add_argument("--user", default="postgres")
    args = ap.parse_args()

    csvs = sorted(p for p in RAW.glob("*.csv"))
    if not csvs:
        sys.exit(f"no CSVs in {RAW}")

    print(f"Loading {len(csvs)} CSVs into {args.container}/{args.db} as raw_* tables\n")
    total = 0
    for path in csvs:
        table, ncol, nrow = load_csv(args.container, args.user, args.db, path)
        total += nrow
        print(f"  {table:28} {nrow:8} rows  {ncol:3} cols")
    print(f"\nDone. {len(csvs)} tables, {total} rows total.")


if __name__ == "__main__":
    main()
