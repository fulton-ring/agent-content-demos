"""Static HTML for the quarterly report, the leadership dashboard and an index page.

Plain HTML, CSS and a little JavaScript with no external files, so the
output folder can be published anywhere as-is.
"""

import json
from html import escape

from .measures import DOSAGE_BANDS

CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6d68;--grid:#e1e0d9;--axis:#c3c2b7;
--border:rgba(11,11,11,.10);--accent:#2a78d6;--prior:#52514e;--good:#0ca30c;--good-ink:#006300;--warn:#fab219;--warn-ink:#8a5a00;
--crit:#d03b3b;--crit-ink:#b42626;--info:#2a78d6;--chip:#f0efec;--b1:#cde2fb;--b2:#86b6ef;--b3:#3987e5;--b4:#1c5cab}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--muted:#9a988f;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--accent:#3987e5;--prior:#c3c2b7;--good-ink:#0ca30c;--warn-ink:#fab219;
--crit-ink:#e66767;--chip:#262624;--b1:#184f95;--b2:#256abf;--b3:#5598e7;--b4:#9ec5f4}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a988f;--grid:#2c2c2a;
--axis:#383835;--border:rgba(255,255,255,.10);--accent:#3987e5;--prior:#c3c2b7;--good-ink:#0ca30c;--warn-ink:#fab219;--crit-ink:#e66767;--chip:#262624;
--b1:#184f95;--b2:#256abf;--b3:#5598e7;--b4:#9ec5f4}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:28px 16px 64px}
header.top{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;align-items:flex-end;margin-bottom:20px}
.eyebrow{color:var(--ink2);font-size:13px;margin:0}
h1{font-size:28px;line-height:1.2;margin:4px 0 6px}
h2{font-size:19px;margin:36px 0 10px}
h3{font-size:15px;margin:18px 0 6px}
p{margin:0 0 12px;max-width:72ch}
a{color:var(--accent)}
nav.links{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:14px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px}
.banner{border-left:4px solid var(--warn);background:var(--surface);border-radius:6px;padding:12px 16px;margin:16px 0}
.banner.crit{border-left-color:var(--crit)}
.meta{color:var(--muted);font-size:13px}
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:10px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--grid);vertical-align:top}
th{font-weight:600;color:var(--ink2);font-size:13px;white-space:nowrap}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.total td{font-weight:600;border-top:2px solid var(--axis)}
tr.prior td{color:var(--ink2)}
tr:last-child td{border-bottom:none}
.sub{display:block;color:var(--muted);font-size:12px;font-weight:400}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;background:var(--chip);white-space:nowrap}
.chip .dot{width:8px;height:8px;border-radius:50%}
.chip.ok .dot{background:var(--good)}.chip.ok{color:var(--good-ink)}
.chip.warning .dot{background:var(--warn)}.chip.warning{color:var(--warn-ink)}
.chip.error .dot{background:var(--crit)}.chip.error{color:var(--crit-ink)}
.chip.info .dot{background:var(--info)}.chip.info{color:var(--ink2)}
ul.notes{list-style:none;padding:0;margin:0}
ul.notes li{padding:10px 0;border-bottom:1px solid var(--grid)}
ul.notes li:last-child{border-bottom:none}
.rows{color:var(--muted);font-size:13px;margin-top:2px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tile .label{color:var(--ink2);font-size:13px}
.tile .value{font-size:30px;font-weight:650;line-height:1.15;margin:4px 0 2px}
.tile .delta{font-size:13px;color:var(--ink2)}
.nw{white-space:nowrap}
.grid2{display:grid;grid-template-columns:3fr 2fr;gap:16px;margin-top:16px}
@media (max-width:760px){.grid2{grid-template-columns:1fr}h1{font-size:23px}}
.seg{display:inline-flex;flex-wrap:wrap;gap:4px;background:var(--chip);border-radius:8px;padding:3px}
.seg button{font:inherit;font-size:13px;border:0;background:transparent;color:var(--ink2);padding:5px 10px;border-radius:6px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--surface);color:var(--ink);font-weight:600;box-shadow:0 0 0 1px var(--border)}
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:4px 0 12px}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink2);margin:6px 0}
.legend span{display:inline-flex;align-items:center;gap:6px}
.key-bar{width:14px;height:8px;border-radius:2px;background:var(--accent)}
.key-dot{width:9px;height:9px;border-radius:50%;background:var(--surface);border:2px solid var(--prior)}
svg text{fill:var(--ink2);font-size:12px}
svg .val{fill:var(--ink);font-weight:600}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--page);font-size:12px;padding:6px 8px;border-radius:6px;opacity:0;transition:opacity .1s;max-width:240px;z-index:5}
details summary{cursor:pointer;color:var(--accent);font-size:14px;margin-top:8px}
.status-list{list-style:none;margin:0;padding:0}
.status-list li{display:flex;justify-content:space-between;gap:8px;padding:8px 0;border-bottom:1px solid var(--grid);font-size:14px}
.status-list li:last-child{border-bottom:none}
footer{margin-top:48px;color:var(--muted);font-size:13px}
@media print{nav.links,.no-print{display:none}body{background:#fff}.card,.table-wrap{border-color:#ccc}}
"""

MEASURE_NOTES = [
    ("Enrolled", "Participants with at least one record this quarter. Everyone listed counts, including rows with problems."),
    ("Average daily attendance", "School days attended divided by school days enrolled. For the organization, each site's rate weighted by its enrollment, "
                                 "because summary-form sites send only a rate."),
    ("Chronically absent", "Missed 10% or more of the school days they were enrolled, for any reason, among students enrolled 10 or more days "
                           "(Attendance Works; U.S. Department of Education Full-Service Community Schools guidance)."),
    ("45+ program hours", "Share of participants with 45 or more hours of program time this quarter. The bands follow the 21st CCLC annual performance report."),
    ("On track", "Met the reading benchmark (grades K-8) or on track for credits (grades 9-12), among students assessed."),
    ("Family engaged", "A family member attended at least one family event or contact this quarter."),
    ("Attendance improved", "Of students at or below 90% attendance last quarter, the share whose attendance rate went up this quarter "
                            "(modeled on the 21st CCLC attendance measure). Needs student-level data from both quarters."),
]

SEVERITY_LABEL = {"error": "Needs fixing", "warning": "Check", "info": "Note", "ok": "OK"}


def fmt(v, kind="int"):
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "dec":
        return f"{v:,.1f}"
    return f"{v:,.0f}"


def chip(severity, text=None):
    return f'<span class="chip {severity}"><span class="dot"></span>{escape(text or SEVERITY_LABEL[severity])}</span>'


def status_chip(row):
    if row["status"] == "on_time":
        return chip("ok", "On time")
    if row["status"] == "late":
        return chip("warning", f"Late, {row['late_days']} days")
    if row["status"] == "missing":
        return chip("error", "Not received")
    return chip("error", "Unreadable")


def page(title, body, extra_head=""):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>{CSS}</style>{extra_head}</head>
<body><main>{body}
<footer>Every number on this page is synthetic, made up for a demonstration of how a quarterly report can rebuild itself from each site's files.
Built by Fulton Ring.</footer></main></body></html>"""


def nav(cfg, results, current=None, here="report"):
    links = ['<a href="index.html">All reports</a>', '<a href="dashboard.html">Leadership dashboard</a>']
    for r in results:
        if r["quarter"] == current and here == "report":
            links.append(f"<span>{escape(r['quarter'])} report</span>")
        else:
            links.append(f'<a href="report-{r["quarter"]}.html">{escape(r["quarter"])} report</a>')
    if current:
        links.append(f'<a href="checks-{current}.txt">Checks log</a>')
    return '<nav class="links">' + "".join(links) + "</nav>"


def change(cur, prev, unit="pts", better="up"):
    if cur is None or prev is None:
        return ""
    d = cur - prev
    if abs(d) < 0.05:
        return "no change"
    word = "up" if d > 0 else "down"
    return f"{word} {abs(d):.1f} {'point' if round(abs(d), 1) == 1 else 'points'}"


def summary_paragraphs(cfg, r, prev):
    t, rt = r["totals"], r["rates"]
    missing = [s["name"] for s in r["sites"] if not s.get("counts")]
    sites_txt = f"{r['sites_reporting']} of {r['sites_expected']} sites"
    paras = [f"{fmt(t['enrolled'])} students took part in the {escape(cfg['program'])} across {sites_txt} this quarter. "
             f"Average daily attendance was {fmt(rt['ada_pct'], 'pct')}, and {fmt(t['chronic'])} students "
             f"({fmt(rt['chronic_pct'], 'pct')} of those enrolled 10 or more days) were chronically absent. "
             f"{fmt(rt['hours_45_plus_pct'], 'pct')} of participants received 45 or more hours of programming, "
             f"{fmt(rt['on_track_pct'], 'pct')} of students assessed were on track, and families of {fmt(rt['family_pct'], 'pct')} "
             f"of participants came to at least one event."]
    if t.get("ada_sites") is not None and t["ada_sites"] < r["sites_reporting"]:
        no_ada = [s["name"] for s in r["sites"] if s.get("counts") and s["counts"].get("ada_pct") is None]
        paras[0] += (f" The attendance rate covers {t['ada_sites']} sites: {', '.join(no_ada)} sent an attendance figure that can't be right "
                     f"and is held out until corrected.")
    if prev:
        pr = prev["rates"]
        p = (f"Compared with {escape(prev['label'])}: attendance {change(rt['ada_pct'], pr['ada_pct'])}, chronic absence "
             f"{change(rt['chronic_pct'], pr['chronic_pct'])}, 45+ hours {change(rt['hours_45_plus_pct'], pr['hours_45_plus_pct'])}, "
             f"on track {change(rt['on_track_pct'], pr['on_track_pct'])}.")
        prev_sites = {s["id"] for s in prev["sites"] if s.get("counts")}
        cur_sites = {s["id"] for s in r["sites"] if s.get("counts")}
        if prev_sites != cur_sites:
            names = {s["id"]: s["name"] for s in r["sites"]}
            added = [names[i] for i in cur_sites - prev_sites]
            dropped = [names[i] for i in prev_sites - cur_sites]
            bits = []
            if added:
                bits.append(f"{', '.join(added)} reported this quarter but not last")
            if dropped:
                bits.append(f"{', '.join(dropped)} reported last quarter but not this one")
            p += " The set of sites changed (" + "; ".join(bits) + "), so part of each change comes from which sites are counted."
        paras.append(p)
    imp = t.get("improvement")
    if imp and imp["base"]:
        paras.append(f"Of {imp['base']} students at or below 90% attendance last quarter at sites that send student-level data, "
                     f"{imp['improved']} ({100 * imp['improved'] / imp['base']:.1f}%) attended a larger share of days this quarter.")
    if missing:
        paras.append(f"Not included: {', '.join(missing)} (see Data notes). Totals cover the sites that reported.")
    return "".join(f"<p>{p}</p>" for p in paras)


def report_page(cfg, r, prev, results, built_at):
    t, rt = r["totals"], r["rates"]
    errors = [i for i in r["issues"] if i["severity"] == "error"]
    warnings = [i for i in r["issues"] if i["severity"] == "warning"]
    body = [f"""<header class="top"><div><p class="eyebrow">{escape(cfg['organization'])} · {escape(cfg['program'])}</p>
<h1>Quarterly program report, {escape(r['label'])}</h1>
<p class="meta">Rebuilt from site submissions {escape(built_at)}. Submissions were due {escape(r['due'])}.
{len(errors)} {"problem needs" if len(errors) == 1 else "problems need"} fixing, {len(warnings)} to check.</p></div>{nav(cfg, results, r['quarter'])}</header>"""]
    missing = [s for s in r["sites"] if s["status"] in ("missing", "unreadable")]
    late = [s for s in r["sites"] if s["status"] == "late"]
    if missing or late:
        bits = [f"<strong>{escape(s['name'])}</strong>: {'no file received' if s['status'] == 'missing' else 'file could not be read'}" for s in missing]
        bits += [f"<strong>{escape(s['name'])}</strong>: received {s['late_days']} days late and included" for s in late]
        body.append(f'<div class="banner{" crit" if missing else ""}"><strong>{r["sites_reporting"]} of {r["sites_expected"]} sites are in this report.</strong> '
                    + "; ".join(bits) + ".</div>")
    body.append("<h2>Summary</h2>" + summary_paragraphs(cfg, r, prev))

    rows = []
    for s in r["sites"]:
        n = [i for i in r["issues"] if i["site"] == s["id"] and i["severity"] in ("error", "warning")]
        worst = "error" if any(i["severity"] == "error" for i in n) else ("warning" if n else "ok")
        checks = chip(worst, f"{len(n)} to review" if n else "Clean") if s["status"] not in ("missing", "unreadable") else "—"
        rows.append(f"<tr><td>{escape(s['name'])}<span class=sub>{escape(s['submits'])}</span></td>"
                    f"<td>{escape(s['received'] or '—')}</td><td>{status_chip(s)}</td><td>{checks}</td></tr>")
    body.append('<h2>Site submissions</h2><div class="table-wrap"><table><thead><tr><th>Site</th><th>Received</th><th>Status</th>'
                '<th>Checks</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")

    def measure_row(name, c, rr, cls=""):
        if not c:
            return f'<tr class="{cls}"><td>{escape(name)}</td><td class="num" colspan="7">Not received</td></tr>'
        return (f'<tr class="{cls}"><td>{escape(name)}</td><td class="num">{fmt(c["enrolled"])}</td><td class="num">{fmt(rr["ada_pct"], "pct")}</td>'
                f'<td class="num">{fmt(c["chronic"])} <span class=sub>{fmt(rr["chronic_pct"], "pct")}</span></td>'
                f'<td class="num">{fmt(rr["hours_45_plus_pct"], "pct")}</td><td class="num">{fmt(rr["avg_hours"], "dec")}</td>'
                f'<td class="num">{fmt(rr["on_track_pct"], "pct")}</td><td class="num">{fmt(rr["family_pct"], "pct")}</td></tr>')
    mrows = [measure_row(s["name"], s.get("counts"), s.get("rates")) for s in r["sites"]]
    mrows.append(measure_row(f"All sites ({r['sites_reporting']} of {r['sites_expected']})", t, rt, "total"))
    if prev:
        mrows.append(measure_row(f"Last quarter, {prev['quarter']} ({prev['sites_reporting']} of {prev['sites_expected']})",
                                 prev["totals"], prev["rates"], "prior"))
    body.append('<h2>Measures by site</h2><div class="table-wrap"><table><thead><tr><th>Site</th><th class=num>Enrolled</th>'
                '<th class=num>Avg daily attendance</th><th class=num>Chronically absent</th><th class=num>45+ program hours</th>'
                '<th class=num>Avg hours</th><th class=num>On track</th><th class=num>Family engaged</th></tr></thead><tbody>'
                + "".join(mrows) + "</tbody></table></div>")

    if t.get("dosage_bands"):
        brows = []
        for s in r["sites"]:
            b = (s.get("counts") or {}).get("dosage_bands")
            if b:
                tot = sum(b)
                brows.append(f"<tr><td>{escape(s['name'])}</td>" + "".join(f'<td class="num">{x} <span class=sub>{100 * x / tot:.0f}%</span></td>' for x in b) + "</tr>")
        tb = t["dosage_bands"]
        brows.append('<tr class="total"><td>Sites with student rows</td>' + "".join(f'<td class="num">{x} <span class=sub>{100 * x / sum(tb):.0f}%</span></td>' for x in tb) + "</tr>")
        body.append('<h2>Program hours per participant</h2><p class="meta">Sites that send student-level rows. Summary-form sites report only the 45+ count.</p>'
                    '<div class="table-wrap"><table><thead><tr><th>Site</th>' + "".join(f"<th class=num>{escape(b[0])} hours</th>" for b in DOSAGE_BANDS)
                    + "</tr></thead><tbody>" + "".join(brows) + "</tbody></table></div>")

    if t.get("improvement"):
        irows = []
        for s in r["sites"]:
            imp = s.get("improvement")
            if imp and imp["base"]:
                irows.append(f'<tr><td>{escape(s["name"])}</td><td class="num">{imp["base"]}</td><td class="num">{imp["improved"]}</td>'
                             f'<td class="num">{100 * imp["improved"] / imp["base"]:.1f}%</td></tr>')
        imp = t["improvement"]
        if imp["base"]:
            irows.append(f'<tr class="total"><td>Total</td><td class="num">{imp["base"]}</td><td class="num">{imp["improved"]}</td>'
                         f'<td class="num">{100 * imp["improved"] / imp["base"]:.1f}%</td></tr>')
        body.append('<h2>Attendance improvement</h2><p class="meta">Students at or below 90% attendance last quarter who were enrolled at the same site both quarters.</p>'
                    '<div class="table-wrap"><table><thead><tr><th>Site</th><th class=num>At or below 90% last quarter</th><th class=num>Improved</th>'
                    '<th class=num>Share improved</th></tr></thead><tbody>' + "".join(irows) + "</tbody></table></div>")

    names = {s["id"]: s["name"] for s in r["sites"]}
    order = {"error": 0, "warning": 1, "info": 2}
    notes = []
    for i in sorted(r["issues"], key=lambda i: (order[i["severity"]], i["site"])):
        rows_txt = ""
        if i["rows"]:
            shown = ", ".join(escape(x) for x in i["rows"][:6])
            more = f" and {len(i['rows']) - 6} more" if len(i["rows"]) > 6 else ""
            rows_txt = f'<div class="rows">{len(i["rows"])} affected: {shown}{more}</div>'
        notes.append(f"<li>{chip(i['severity'])} <strong>{escape(names.get(i['site'], i['site']))}</strong>: {escape(i['message'])}{rows_txt}</li>")
    body.append('<h2>Data notes</h2><p class="meta">Everything the refresh found in this quarter\'s files. Nothing is dropped without a note here.</p>'
                f'<div class="card"><ul class="notes">{"".join(notes) or "<li>No problems found.</li>"}</ul></div>')

    tk = lambda x: "dec" if x["measure"] == "program_hours" else "int"  # noqa: E731
    trows = "".join(f'<tr><td>{escape(x["measure"].replace("_", " "))}</td><td class="num">{fmt(x["total_row"], tk(x))}</td>'
                    f'<td class="num">{fmt(x["sum_of_sites"], tk(x))}</td><td class="num">{fmt(x["recount"], tk(x))}</td>'
                    f'<td>{chip("ok", "Ties") if x["ties"] else chip("error", "Does not tie")}</td></tr>' for x in r["ties"])
    body.append('<h2>Totals check</h2><p class="meta">Each count in the "All sites" row, the sum of the site rows, and a separate recount from every '
                'student row and summary form. All three must match.</p><div class="table-wrap"><table><thead><tr><th>Count</th><th class=num>All sites row</th>'
                '<th class=num>Sum of sites</th><th class=num>Recount from files</th><th>Result</th></tr></thead><tbody>' + trows + "</tbody></table></div>")

    body.append("<h2>How these measures are defined</h2><div class=card><ul class=notes>"
                + "".join(f"<li><strong>{escape(a)}.</strong> {escape(b)}</li>" for a, b in MEASURE_NOTES) + "</ul></div>")
    return page(f"{cfg['organization']}: {r['label']} report", "".join(body))


def checks_text(r):
    lines = [f"Checks for {r['label']} (due {r['due']})", ""]
    for s in r["sites"]:
        lines.append(f"{s['name']}: {s['status']}" + (f", received {s['received']}" if s["received"] else ""))
    lines.append("")
    for i in r["issues"]:
        lines.append(f"[{i['severity'].upper()}] {i['site']} {i['code']}: {i['message']}")
        if i["rows"]:
            lines.append("    " + "; ".join(i["rows"]))
    lines.append("")
    for x in r["ties"]:
        lines.append(f"tie {x['measure']}: total row {x['total_row']}, sum of sites {x['sum_of_sites']}, recount {x['recount']} -> {'OK' if x['ties'] else 'MISMATCH'}")
    return "\n".join(lines) + "\n"


def dashboard_page(cfg, results, built_at):
    data = []
    for r in results:
        data.append({
            "quarter": r["quarter"], "label": r["label"], "sitesReporting": r["sites_reporting"], "sitesExpected": r["sites_expected"],
            "totals": {**r["rates"], "enrolled": r["totals"]["enrolled"]},
            "issues": {sev: sum(1 for i in r["issues"] if i["severity"] == sev) for sev in ("error", "warning")},
            "bands": r["totals"].get("dosage_bands"),
            "sites": [{"id": s["id"], "name": s["name"], "status": s["status"], "lateDays": s.get("late_days"),
                       "issues": sum(1 for i in r["issues"] if i["site"] == s["id"] and i["severity"] in ("error", "warning")),
                       "worst": "error" if any(i["site"] == s["id"] and i["severity"] == "error" for i in r["issues"]) else "warning",
                       "enrolled": (s.get("counts") or {}).get("enrolled"), **(s.get("rates") or {})} for s in r["sites"]],
        })
    body = f"""<header class="top"><div><p class="eyebrow">{escape(cfg['organization'])} · Leadership dashboard</p>
<h1 id="title">Program dashboard</h1><p class="meta">Rebuilt {escape(built_at)} from the same site files as the quarterly report.</p></div>
{nav(cfg, results, None, 'dashboard')}</header>
<div class="controls"><span class="meta">Quarter</span><div class="seg" id="qsel" role="group" aria-label="Quarter"></div></div>
<div id="banner"></div>
<section class="tiles" id="tiles" aria-label="Headline measures"></section>
<div class="grid2">
 <section class="card"><h3 style="margin-top:0">By site</h3>
  <div class="controls"><div class="seg" id="msel" role="group" aria-label="Measure"></div></div>
  <div class="legend"><span><i class="key-bar"></i><b id="lg-cur"></b></span><span><i class="key-dot"></i><b id="lg-prev"></b></span></div>
  <div id="chart"></div>
  <details><summary>Show as a table</summary><div class="table-wrap" style="margin-top:8px"><table id="ctable"></table></div></details>
 </section>
 <section class="card"><h3 style="margin-top:0">Site submissions</h3><ul class="status-list" id="status"></ul>
  <h3>Program hours per participant</h3><p class="meta" style="margin-bottom:6px">Sites with student-level rows</p><div id="bands"></div>
 </section>
</div>
<div id="tip" role="tooltip"></div>
<script>
const DATA = {json.dumps(data)};
const BANDS = {json.dumps([b[0] for b in DOSAGE_BANDS])};
const MEASURES = [
 {{key:"ada_pct",label:"Attendance",long:"Average daily attendance",better:"up"}},
 {{key:"chronic_pct",label:"Chronic absence",long:"Chronically absent",better:"down"}},
 {{key:"hours_45_plus_pct",label:"45+ hours",long:"Participants with 45+ program hours",better:"up"}},
 {{key:"on_track_pct",label:"On track",long:"On track (reading or credits)",better:"up"}},
 {{key:"family_pct",label:"Family",long:"Families at 1+ event",better:"up"}}];
let qi = DATA.length-1, mk = "chronic_pct";
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}})[c]);
const pct = v => v==null ? "—" : v.toFixed(1)+"%";
const tip = $("#tip");
function showTip(e, html){{tip.innerHTML=html;tip.style.opacity=1;const x=Math.min(e.clientX+12, innerWidth-tip.offsetWidth-8);tip.style.left=x+"px";tip.style.top=(e.clientY+14)+"px";}}
function hideTip(){{tip.style.opacity=0;}}
function seg(el, items, cur, on){{el.innerHTML=items.map(([v,l])=>`<button type="button" data-v="${{v}}" aria-pressed="${{v==cur}}">${{esc(l)}}</button>`).join("");
 el.querySelectorAll("button").forEach(b=>b.onclick=()=>on(b.dataset.v));}}
function delta(cur, prev, better){{
 if(cur==null||prev==null) return "No earlier quarter";
 const d=cur-prev; if(Math.abs(d)<0.05) return "No change";
 const good=(d>0)===(better==="up");
 return `<span style="color:var(${{good?"--good-ink":"--crit-ink"}})">${{d>0?"▲":"▼"}} ${{Math.abs(d).toFixed(1)}} pts</span> <span class="nw">vs ${{esc(DATA[qi-1].quarter)}}</span>`;}}
function render(){{
 const q=DATA[qi], p=DATA[qi-1];
 $("#title").textContent="Program dashboard, "+q.label;
 seg($("#qsel"), DATA.map((d,i)=>[i,d.quarter]), qi, v=>{{qi=+v;render();}});
 seg($("#msel"), MEASURES.map(m=>[m.key,m.label]), mk, v=>{{mk=v;render();}});
 const miss=q.sites.filter(s=>s.status==="missing"||s.status==="unreadable");
 $("#banner").innerHTML = (miss.length||q.issues.error) ? `<div class="banner${{miss.length?" crit":""}}"><strong>${{q.sitesReporting}} of ${{q.sitesExpected}} sites reporting.</strong> ${{miss.map(s=>esc(s.name)+": not received").join("; ")}}${{miss.length&&q.issues.error?"; ":""}}${{q.issues.error?q.issues.error+(q.issues.error===1?" data problem needs":" data problems need")+" fixing (see the report's Data notes).":""}}</div>` : "";
 const tiles=[["Enrolled",q.totals.enrolled,p&&p.totals.enrolled,"up",v=>v.toLocaleString()]].concat(MEASURES.map(m=>[m.long,q.totals[m.key],p&&p.totals[m.key],m.better,pct]));
 $("#tiles").innerHTML=tiles.map(([l,v,pv,b,f])=>`<div class="card tile"><div class="label">${{esc(l)}}</div><div class="value">${{v==null?"—":f(v)}}</div><div class="delta">${{
   l==="Enrolled" ? (pv==null?"No earlier quarter":`${{v-pv>=0?"+":"−"}}${{Math.abs(v-pv)}} <span class="nw">vs ${{esc(p.quarter)}}</span>`) : delta(v,pv,b)}}</div></div>`).join("");
 const m=MEASURES.find(x=>x.key===mk);
 $("#lg-cur").textContent=q.quarter; $("#lg-prev").parentElement.style.display=p?"":"none"; if(p) $("#lg-prev").textContent=p.quarter;
 drawBars(q,p,m); drawStatus(q); drawBands(q);
 $("#ctable").innerHTML=`<thead><tr><th>Site</th><th class=num>${{esc(q.quarter)}}</th>${{p?`<th class=num>${{esc(p.quarter)}}</th>`:""}}</tr></thead><tbody>`+
  q.sites.map(s=>{{const ps=p&&p.sites.find(x=>x.id===s.id);return `<tr><td>${{esc(s.name)}}</td><td class=num>${{pct(s[mk])}}</td>${{p?`<td class=num>${{pct(ps&&ps[mk])}}</td>`:""}}</tr>`;}}).join("")+
  `<tr class=total><td>All sites</td><td class=num>${{pct(q.totals[mk])}}</td>${{p?`<td class=num>${{pct(p.totals[mk])}}</td>`:""}}</tr></tbody>`;
}}
function drawBars(q,p,m){{
 const el=$("#chart"), W=Math.max(280, el.clientWidth), narrow=W<480, rowH=narrow?52:40, labW=narrow?0:150, padR=58, H=q.sites.length*rowH+24;
 const vals=q.sites.map(s=>s[m.key]).concat(p?p.sites.map(s=>s[m.key]):[]).filter(v=>v!=null);
 const max = m.key==="ada_pct" ? 100 : Math.max(10, Math.ceil(Math.max(...vals,0)/10)*10);
 const x=v=>labW+(W-labW-padR)*v/max;
 let s=`<svg width="${{W}}" height="${{H}}" viewBox="0 0 ${{W}} ${{H}}" role="img" aria-label="${{esc(m.long)}} by site">`;
 for(let t=0;t<=max;t+=max/4){{s+=`<line x1="${{x(t)}}" x2="${{x(t)}}" y1="0" y2="${{H-20}}" stroke="var(--grid)"/><text x="${{x(t)}}" y="${{H-4}}" text-anchor="${{t===0&&labW===0?"start":"middle"}}">${{t}}%</text>`;}}
 q.sites.forEach((site,i)=>{{
  const y=i*rowH+(narrow?20:8), v=site[m.key], ps=p&&p.sites.find(z=>z.id===site.id), pv=ps?ps[m.key]:null;
  s+=`<text x="0" y="${{narrow?y:y+15}}">${{esc(site.name)}}</text>`;
  const tipHtml=`<b>${{esc(site.name)}}</b><br>${{esc(m.long)}}<br>${{esc(q.quarter)}}: ${{pct(v)}}${{p?`<br>${{esc(p.quarter)}}: ${{pct(pv)}}`:""}}`;
  if(v==null){{s+=`<text x="${{labW}}" y="${{y+15}}" class="val">${{site.status==="missing"?"Not received":"Not usable"}}</text>`;}}
  else{{const w=Math.max(2,x(v)-labW);
   s+=`<path d="M${{labW}} ${{y+4}}h${{w-4}}a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4h-${{w-4}}z" fill="var(--accent)"/>`;
   s+=`<text x="${{Math.max(x(v), pv!=null?x(pv)+4:0)+8}}" y="${{y+16}}" class="val">${{v.toFixed(1)}}%</text>`;}}
  if(pv!=null) s+=`<circle cx="${{x(pv)}}" cy="${{y+12}}" r="5" fill="var(--surface)" stroke="var(--prior)" stroke-width="2"/>`;
  s+=`<rect x="0" y="${{y-(narrow?16:4)}}" width="${{W}}" height="${{rowH}}" fill="transparent" data-tip="${{esc(tipHtml)}}"/>`;
 }});
 el.innerHTML=s+"</svg>";
 el.querySelectorAll("rect[data-tip]").forEach(r=>{{r.onmousemove=e=>showTip(e,r.dataset.tip);r.onmouseleave=hideTip;}});
}}
function drawStatus(q){{
 const c={{on_time:["ok","On time"],late:["warning","Late"],missing:["error","Not received"],unreadable:["error","Unreadable"]}};
 $("#status").innerHTML=q.sites.map(s=>{{const [k,l]=c[s.status];const lab=s.status==="late"?`Late, ${{s.lateDays}} days`:l;
  const iss=s.issues&&s.status!=="missing"?`<span class="chip ${{s.worst}}"><span class="dot"></span>${{s.issues}} to review</span>`:"";
  return `<li><span>${{esc(s.name)}}</span><span style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${{iss}}<span class="chip ${{k}}"><span class="dot"></span>${{lab}}</span></span></li>`;}}).join("");
}}
function drawBands(q){{
 const el=$("#bands"); if(!q.bands){{el.innerHTML="";return;}}
 const tot=q.bands.reduce((a,b)=>a+b,0), W=Math.max(260, el.clientWidth), cols=["var(--b1)","var(--b2)","var(--b3)","var(--b4)"];
 let x=0, s=`<svg width="${{W}}" height="34" viewBox="0 0 ${{W}} 34" role="img" aria-label="Program hours bands">`;
 q.bands.forEach((n,i)=>{{const w=W*n/tot; s+=`<rect x="${{x}}" y="0" width="${{Math.max(0,w-2)}}" height="24" rx="${{i===0||i===3?4:0}}" fill="${{cols[i]}}" data-tip="<b>${{BANDS[i]}} hours</b><br>${{n}} participants (${{(100*n/tot).toFixed(0)}}%)"/>`; x+=w;}});
 el.innerHTML=s+"</svg>"+`<div class="legend">${{q.bands.map((n,i)=>`<span><i style="width:10px;height:10px;border-radius:2px;background:${{cols[i]}}"></i>${{BANDS[i]}} h: ${{(100*n/tot).toFixed(0)}}%</span>`).join("")}}</div>`;
 el.querySelectorAll("rect[data-tip]").forEach(r=>{{r.onmousemove=e=>showTip(e,r.dataset.tip);r.onmouseleave=hideTip;}});
}}
let rt; addEventListener("resize",()=>{{clearTimeout(rt);rt=setTimeout(render,100);}});
render();
</script>"""
    return page(f"{cfg['organization']}: dashboard", body)


def index_page(cfg, results, built_at):
    rows = "".join(
        f'<tr><td><a href="report-{r["quarter"]}.html">{escape(r["label"])}</a></td><td class="num">{r["sites_reporting"]} of {r["sites_expected"]}</td>'
        f'<td class="num">{fmt(r["totals"]["enrolled"])}</td><td class="num">{sum(1 for i in r["issues"] if i["severity"] == "error")}</td>'
        f'<td><a href="checks-{r["quarter"]}.txt">checks</a> · <a href="data/{r["quarter"]}.json">data</a></td></tr>' for r in reversed(results))
    body = f"""<header class="top"><div><p class="eyebrow">{escape(cfg['organization'])}</p><h1>Quarterly program reports</h1>
<p class="meta">Rebuilt {escape(built_at)} from every quarter folder in the inbox.</p></div></header>
<p><a href="report.html">Latest quarterly report</a> · <a href="dashboard.html">Leadership dashboard</a></p>
<div class="table-wrap"><table><thead><tr><th>Quarter</th><th class=num>Sites reporting</th><th class=num>Enrolled</th><th class=num>Problems to fix</th><th>Files</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""
    return page(f"{cfg['organization']}: quarterly reports", body)
