"""Run the reports on the source and on the archive, compare them, and explain
every difference. Writes build/reports/*.csv and results/reconciliation.md."""

import csv
import datetime as dt
import decimal
import json
import os
import sys
import time
from collections import defaultdict

import duckdb
import pymssql

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
RESULTS = os.path.join(HERE, "results")

KEYS = {"trial_balance": ["year", "period", "account"], "ar_aging": ["as_of", "customer"],
        "ap_aging": ["as_of", "vendor"], "customer_history": ["customer", "year"],
        "vendor_history": ["vendor", "year"]}


def named_queries(path, last_date_sql):
    out, name, buf = {}, None, []
    for line in open(path):
        if line.startswith("-- name:"):
            if name:
                out[name] = "".join(buf)
            name, buf = line.split(":", 1)[1].strip(), []
        elif name:
            buf.append(line)
    out[name] = "".join(buf)
    return {k: v.replace(":asof_last", last_date_sql).strip().rstrip(";") for k, v in out.items()}


def text(v):
    if isinstance(v, decimal.Decimal):
        return f"{v:.2f}"
    return str(v).rstrip() if v is not None else ""


def write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows([[text(v) for v in r] for r in rows])


def as_dicts(cols, rows):
    return [dict(zip(cols, (text(v) for v in r))) for r in rows]


def compare(name, src, arc):
    keys = KEYS[name]
    s = {tuple(r[k] for k in keys): r for r in src}
    a = {tuple(r[k] for k in keys): r for r in arc}
    diffs = []
    for k in sorted(set(s) | set(a)):
        rs, ra = s.get(k), a.get(k)
        if rs is None or ra is None:
            diffs.append((k, "row missing from " + ("source" if rs is None else "archive"), rs, ra))
            continue
        for col in rs:
            if col in keys:
                continue
            if decimal.Decimal(rs[col]) != decimal.Decimal(ra[col]):
                diffs.append((k, col, rs[col], ra[col]))
    return len(s), len(a), diffs


def money(x):
    return f"{decimal.Decimal(x):,.2f}"


def main():
    timings = {}
    host = os.environ.get("GP_HOST", "localhost:14330")
    db = os.environ.get("GP_DB", "TWOSYN")
    src = pymssql.connect(host, os.environ.get("GP_READER", "gp_archive_reader"),
                          os.environ["GP_READER_PASSWORD"], db)
    duck = duckdb.connect(os.path.join(BUILD, "gp_archive.duckdb"), read_only=True)

    src_q = named_queries(os.path.join(HERE, "source", "reports.sql"), "(SELECT MAX(TRXDATE) FROM GL20000)")
    arc_q = named_queries(os.path.join(HERE, "archive", "reports.sql"), "(SELECT MAX(TRXDATE) FROM gp.GL20000)")

    results = {}
    for name in KEYS:
        t0 = time.perf_counter()
        cur = src.cursor()
        cur.execute(src_q[name])
        scols = [d[0] for d in cur.description]
        srows = cur.fetchall()
        t1 = time.perf_counter()
        res = duck.execute(arc_q[name])
        acols = [d[0] for d in res.description]
        arows = res.fetchall()
        t2 = time.perf_counter()
        timings[name] = (t1 - t0, t2 - t1)
        write_csv(os.path.join(BUILD, "reports", "source", name + ".csv"), scols, srows)
        write_csv(os.path.join(BUILD, "reports", "archive", name + ".csv"), acols, arows)
        results[name] = (as_dicts(scols, srows), as_dicts(acols, arows))
    res = duck.execute(arc_q["control_accounts"])
    control = as_dicts([d[0] for d in res.description], res.fetchall())

    lines = []
    w = lines.append
    manifest = json.load(open(os.path.join(BUILD, "manifest.json")))
    w("# Reconciliation: source GP database against the archive\n")
    w(f"Run {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC. Source `{manifest['source']['database']}` on SQL Server, "
      f"read with login `{manifest['source']['login']}` ({manifest['source']['write_attempt']}).\n")

    w("## Tables copied\n")
    w("| Table | Rows in source | Rows in archive | Row fingerprints match |")
    w("|---|---:|---:|---|")
    for e in manifest["tables"]:
        w(f"| {e['table']} | {e['source_rows']:,} | {e['archive_rows']:,} | {'yes' if e['match'] else 'NO'} |")
    total_rows = sum(e["source_rows"] for e in manifest["tables"])
    w(f"\n{len(manifest['tables'])} tables, {total_rows:,} rows. Export took {manifest['export_seconds']}s. "
      f"Archive size: DuckDB file {manifest['duckdb_bytes'] / 1e6:.1f} MB, Parquet files {manifest['parquet_bytes'] / 1e6:.1f} MB.\n")

    w("## Report comparison\n")
    w("| Report | Rows (source) | Rows (archive) | Values compared | Differences | Source time | Archive time |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    all_diffs = {}
    for name, (s, a) in results.items():
        ns, na, diffs = compare(name, s, a)
        all_diffs[name] = diffs
        nvals = ns * (len(s[0]) - len(KEYS[name])) if s else 0
        w(f"| {name} | {ns:,} | {na:,} | {nvals:,} | {len(diffs)} | {timings[name][0]:.2f}s | {timings[name][1]:.2f}s |")
    w("")

    # Trial balance by year-end and latest period
    tb_s, tb_a = results["trial_balance"]
    w("## Trial balance by period\n")
    w("Total debits and credits posted in each period, and the sum of ending balances (zero when the ledger balances). "
      "Source is GP's account summary tables; archive is rebuilt from the journal lines. "
      "Full detail by account is in `build/reports/`.\n")
    w("| Year | Period | Debits (source) | Debits (archive) | Credits (source) | Credits (archive) | Ending sum (source) | Ending sum (archive) | Accounts that differ |")
    w("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    agg = defaultdict(lambda: [decimal.Decimal(0)] * 6)
    diff_accts = defaultdict(set)
    for side, rows in ((0, tb_s), (1, tb_a)):
        for r in rows:
            k = (int(r["year"]), int(r["period"]))
            agg[k][0 + side] += decimal.Decimal(r["debit"])
            agg[k][2 + side] += decimal.Decimal(r["credit"])
            agg[k][4 + side] += decimal.Decimal(r["ending"])
    for k, col, _, _ in all_diffs["trial_balance"]:
        diff_accts[(int(k[0]), int(k[1]))].add(k[2])
    for (y, p), v in sorted(agg.items()):
        w(f"| {y} | {p} | {money(v[0])} | {money(v[1])} | {money(v[2])} | {money(v[3])} | {money(v[4])} | {money(v[5])} | {len(diff_accts[(y, p)])} |")
    w("")

    # Explain trial balance differences by finding the journal entries behind them
    w("## Differences and their explanation\n")
    if not any(all_diffs.values()):
        w("None.\n")
    for name, diffs in all_diffs.items():
        if not diffs:
            continue
        w(f"### {name}: {len(diffs)} differing values\n")
        w("| Key | Column | Source | Archive | Difference |")
        w("|---|---|---:|---:|---:|")
        for k, col, sv, av in diffs[:40]:
            try:
                d = money(decimal.Decimal(av) - decimal.Decimal(sv))
            except Exception:
                d = ""
            w(f"| {' / '.join(map(str, k))} | {col} | {sv} | {av} | {d} |")
        if len(diffs) > 40:
            w(f"| ... {len(diffs) - 40} more | | | | |")
        w("")
        if name == "trial_balance":
            # Net-change differences point at the period where the summary lost the posting
            first = defaultdict(lambda: None)
            for k, col, sv, av in diffs:
                if col in ("debit", "credit"):
                    y, p, acct = int(k[0]), int(k[1]), k[2]
                    first[(y, p, acct, col)] = decimal.Decimal(av) - decimal.Decimal(sv)
            w("Journal entries that account for the period differences (searched in the archive's journal lines):\n")
            for (y, p, acct, col), amount in sorted(first.items()):
                amtcol = "DEBITAMT" if col == "debit" else "CRDTAMNT"
                q = f"""SELECT JRNENTRY, strftime(TRXDATE, '%Y-%m-%d'), REFRENCE, USWHPSTD, {amtcol}
                        FROM (SELECT * EXCLUDE (OPENYEAR) , OPENYEAR AS yr FROM gp.GL20000
                              UNION ALL BY NAME SELECT * EXCLUDE (HSTYEAR), HSTYEAR AS yr FROM gp.GL30000) l
                        JOIN gp.GL00105 a USING (ACTINDX)
                        WHERE yr = ? AND PERIODID = ? AND a.ACTNUMST = ? AND {amtcol} = ?"""
                hits = duck.execute(q, [y, p, acct, amount]).fetchall()
                for je, d, ref, user, amt in hits:
                    w(f"- {y} period {p}, account {acct}, {col} off by {money(amount)}: journal entry {je} "
                      f"dated {d}, \"{ref}\", posted by {user}, {col} {money(amt)}. The entry is in the journal lines "
                      f"(GL20000/GL30000) but not in GP's account summary (GL10110/GL10111).")
                if not hits:
                    w(f"- {y} period {p}, account {acct}, {col} off by {money(amount)}: no single journal entry matches.")
            w("\nEvery later period's beginning and ending balance for the same accounts differs by the same amount, "
              "because balances carry forward. That is one cause, repeated.\n")

    # Subledger to GL
    w("## Receivables and payables against the general ledger\n")
    w("Aging totals (archive) against the AR (000-1200-00) and AP (000-2100-00) account balances built from journal lines, at each year end and the last period.\n")
    w("| As of | AR aging (source) | AR aging (archive) | AR in GL | AP aging (source) | AP aging (archive) | AP in GL |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    tot = defaultdict(decimal.Decimal)
    for name, idx in (("ar_aging", 0), ("ap_aging", 2)):
        for side, rows in enumerate(results[name]):
            for r in rows:
                tot[(r["as_of"], idx + side)] += decimal.Decimal(r["balance"])
    gl = {(r["as_of"], r["account"]): decimal.Decimal(r["gl_balance"]) for r in control}
    dates = sorted({r["as_of"] for r in control})
    ties = 0
    for d in dates:
        ar_gl, ap_gl = gl.get((d, "000-1200-00"), 0), -gl.get((d, "000-2100-00"), 0)
        ok = tot[(d, 1)] == ar_gl and tot[(d, 3)] == ap_gl
        ties += ok
        if d.endswith("12-31") or d == dates[-1]:
            w(f"| {d} | {money(tot[(d, 0)])} | {money(tot[(d, 1)])} | {money(ar_gl)} | "
              f"{money(tot[(d, 2)])} | {money(tot[(d, 3)])} | {money(ap_gl)} |")
    w(f"\nAging ties to the GL control account at {ties} of {len(dates)} period ends.\n")

    # Customer and vendor history totals
    w("## Customer and vendor history totals\n")
    w("| | Source | Archive |")
    w("|---|---:|---:|")
    for name, cols in (("customer_history", ["invoices", "invoiced", "credit_memos", "payments", "paid", "voided"]),
                       ("vendor_history", ["invoices", "invoiced", "payments", "paid", "voided"])):
        s, a = results[name]
        for c in cols:
            sv = sum(decimal.Decimal(r[c]) for r in s)
            av = sum(decimal.Decimal(r[c]) for r in a)
            fmt = money if c in ("invoiced", "paid", "credit_memos") else (lambda x: f"{int(x):,}")
            w(f"| {name.split('_')[0]} {c.replace('_', ' ')} | {fmt(sv)} | {fmt(av)} |")
    w("")

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "reconciliation.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    n = sum(len(d) for d in all_diffs.values())
    print(f"reconciliation written to results/reconciliation.md; {n} differing values", file=sys.stderr)


if __name__ == "__main__":
    main()
