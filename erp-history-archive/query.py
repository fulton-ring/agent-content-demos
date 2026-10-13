"""Run a saved auditor query against the archive. No SQL Server needed.

    python query.py trial_balance year=2024 period=12
    python query.py vendor_payment_history vendor=V0007
    python query.py open_ar_at_date as_of=2025-06-30
    python query.py journal_entries_by_user user=sa from=2023-01-01 to=2026-09-30
    python query.py document_trail document=INV0001234
    python query.py unusual_journal_entries from=2023-01-01 to=2026-09-30

Add --markdown to print a table, --csv FILE to save the result. The archive
is read from build/gp_archive.duckdb, or from build/parquet/ with --parquet.
"""

import argparse
import csv
import decimal
import os
import re
import sys

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))


def connect(parquet):
    if not parquet:
        return duckdb.connect(os.path.join(HERE, "build", "gp_archive.duckdb"), read_only=True)
    con = duckdb.connect()
    con.execute("CREATE SCHEMA gp")
    folder = os.path.join(HERE, "build", "parquet")
    for f in sorted(os.listdir(folder)):
        con.execute(f"CREATE VIEW gp.{f[:-8]} AS SELECT * FROM read_parquet('{os.path.join(folder, f)}')")
    return con


def run(name, params, parquet=False):
    sql = open(os.path.join(HERE, "queries", name + ".sql")).read()
    wanted = set(re.findall(r"\$(\w+)", sql))
    missing = wanted - set(params)
    if missing:
        sys.exit(f"{name} needs: {', '.join(sorted(missing))}")
    con = connect(parquet)
    res = con.execute(sql, {k: v for k, v in params.items() if k in wanted})
    cols = [d[0] for d in res.description]
    return cols, res.fetchall()


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, decimal.Decimal):
        return f"{v:,.2f}"
    return str(v)


def markdown(cols, rows):
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---:" if rows and isinstance(rows[0][i], (int, decimal.Decimal)) else "---"
                                                         for i in range(len(cols))) + "|"]
    out += ["| " + " | ".join(fmt(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("params", nargs="*", help="name=value")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--csv")
    ap.add_argument("--parquet", action="store_true")
    a = ap.parse_args()
    params = dict(p.split("=", 1) for p in a.params)
    for k in ("year", "period"):
        if k in params:
            params[k] = int(params[k])
    cols, rows = run(a.query, params, a.parquet)
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows([[fmt(v).replace(",", "") if isinstance(v, decimal.Decimal) else fmt(v) for v in r] for r in rows])
    if a.markdown or not a.csv:
        print(markdown(cols, rows))
    print(f"{len(rows)} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
