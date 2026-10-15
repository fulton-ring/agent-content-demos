"""Rebuild every quarter's report and the dashboard from whatever is in inbox/.

This is the command a schedule runs (see schedule/). It needs no edits when a
new quarter's folder appears: it reads every inbox/<FYxx-Qn>/ folder, checks
each site's files, and writes output/.

    python3 refresh.py
"""

import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pipeline import build, quarters  # noqa: E402
from pipeline.ingest import ingest_quarter  # noqa: E402
from pipeline.measures import (attendance_improvement, org_totals, rates, site_counts_from_participants,  # noqa: E402
                               site_counts_from_summary, tie_out)

CONFIG = json.loads((HERE / "config" / "sites.json").read_text())
FY = CONFIG["fiscal_year_start_month"]


def refresh(inbox=HERE / "inbox", out=HERE / "output", quiet=False):
    t0 = time.perf_counter()
    folders = sorted([p for p in Path(inbox).iterdir() if p.is_dir() and quarters.QUARTER_RE.match(p.name)],
                     key=lambda p: quarters.parse(p.name, FY)[0]) if Path(inbox).exists() else []
    if not folders:
        sys.exit(f"no quarter folders (like FY26-Q1) in {inbox}")
    results, prior_sites = [], {}
    for folder in folders:
        qid = folder.name
        sites, issues, due = ingest_quarter(folder, qid, CONFIG)
        site_rows = []
        for s in sites.values():
            row = {k: s.get(k) for k in ("id", "name", "submits", "kind", "status", "received", "late_days", "files")}
            if "participants" in s:
                row["counts"] = site_counts_from_participants(s["participants"])
                prev = prior_sites.get(s["id"])
                row["improvement"] = attendance_improvement(s["participants"], prev.get("participants") if prev else None)
            elif "summary" in s:
                row["counts"] = site_counts_from_summary(s["summary"])
            if row.get("counts"):
                row["rates"] = rates(row["counts"])
            site_rows.append(row)
        totals = org_totals(site_rows)
        ties = tie_out(site_rows, totals, sites)
        if not all(t["ties"] for t in ties):
            issues.append({"site": "(all)", "severity": "error", "code": "totals_do_not_tie", "count": 1, "rows": [],
                           "message": "Organization totals don't match the sum of the sites: " +
                                      ", ".join(t["measure"] for t in ties if not t["ties"])})
        results.append({
            "quarter": qid, "label": quarters.label(qid, FY), "due": due.isoformat(),
            "sites": site_rows, "totals": totals, "rates": rates(totals), "ties": ties, "issues": issues,
            "sites_reporting": sum(1 for s in site_rows if s.get("counts")), "sites_expected": len(site_rows),
        })
        prior_sites = sites
    elapsed_ingest = time.perf_counter() - t0

    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for i, r in enumerate(results):
        prev = results[i - 1] if i else None
        (out / "data" / f"{r['quarter']}.json").write_text(json.dumps(r, indent=1, default=str))
        (out / f"report-{r['quarter']}.html").write_text(build.report_page(CONFIG, r, prev, results, built_at))
        (out / f"checks-{r['quarter']}.txt").write_text(build.checks_text(r))
    latest = results[-1]
    shutil.copy(out / f"report-{latest['quarter']}.html", out / "report.html")
    (out / "dashboard.html").write_text(build.dashboard_page(CONFIG, results, built_at))
    (out / "index.html").write_text(build.index_page(CONFIG, results, built_at))
    elapsed = time.perf_counter() - t0

    if not quiet:
        for r in results:
            n = {sev: sum(1 for i in r["issues"] if i["severity"] == sev) for sev in ("error", "warning", "info")}
            ties = "all totals tie" if all(t["ties"] for t in r["ties"]) else "TOTALS DO NOT TIE"
            print(f"{r['quarter']}: {r['sites_reporting']}/{r['sites_expected']} sites, {r['totals']['enrolled']} enrolled, "
                  f"{n['error']} errors, {n['warning']} warnings, {n['info']} notes, {ties}")
        print(f"refresh: read and checked {len(results)} quarter(s) in {elapsed_ingest:.2f}s, built pages in {elapsed - elapsed_ingest:.2f}s "
              f"-> {out.relative_to(HERE) if out.is_relative_to(HERE) else out}/")
    return results, elapsed


if __name__ == "__main__":
    refresh()
