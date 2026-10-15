"""Read each site's submission for a quarter into one shape, and record every problem found.

Nothing is dropped silently. A value that can't be right (more absences than
days enrolled, more program hours than the quarter allows, a percentage over
100) is set aside from the measure it would distort, the participant still
counts as enrolled, and an issue is recorded that names the site, the rows
and what to fix.
"""

import csv
import re
from datetime import date
from pathlib import Path

from . import quarters
from .xlsx import read_xlsx

FILE_RE = re.compile(r"^(?P<site>[a-z0-9-]+)__(?P<received>\d{4}-\d{2}-\d{2})(?:__(?P<part>[a-z_]+))?\.(?P<ext>xlsx|csv)$")


def issue(site, severity, code, message, rows=None):
    return {"site": site, "severity": severity, "code": code, "message": message,
            "rows": rows or [], "count": len(rows) if rows else 1}


def text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def number(v):
    t = text(v).replace(",", "")
    if t == "":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def read_table(path, sheet=0, header_contains=None):
    if path.suffix == ".xlsx":
        rows = read_xlsx(path, sheet)
    else:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    start = 0
    if header_contains:
        start = next((i for i, r in enumerate(rows) if header_contains in [text(c) for c in r]), None)
        if start is None:
            raise ValueError(f"no header row containing {header_contains!r}")
    header = [text(c) for c in rows[start]]
    return header, [r for r in rows[start + 1:]]


def find_submissions(folder):
    """Group files in a quarter folder by site: {site: {received, files: {part: path}}}."""
    found, stray = {}, []
    for path in sorted(Path(folder).iterdir()):
        m = FILE_RE.match(path.name)
        if not m:
            stray.append(path.name)
            continue
        entry = found.setdefault(m["site"], {"received": date.fromisoformat(m["received"]), "files": {}})
        entry["received"] = max(entry["received"], date.fromisoformat(m["received"]))
        entry["files"][m["part"] or "main"] = path
    return found, stray


def to_bool(site_cfg, field, raw):
    t = text(raw)
    if t in site_cfg.get("true_values", []):
        return True
    if t == "" and field in site_cfg.get("blank_means_not_assessed", []):
        return None
    if t in site_cfg.get("not_assessed_values", []):
        return None
    if t in site_cfg.get("false_values", []):
        return False
    return "invalid"


def validate_participants(site_cfg, people, qid, cfg, issues):
    """Range checks on the normalized rows. Bad values become None so they can't distort a measure."""
    sid = site_cfg["id"]
    weekdays = quarters.weekdays(qid, cfg["fiscal_year_start_month"])
    max_hours = weekdays * cfg["max_program_hours_per_weekday"]
    bad_days, bad_hours, bad_grade, bad_flags = [], [], [], []
    for p in people:
        de, da = p["days_enrolled"], p["days_attended"]
        if de is None or da is None or de <= 0 or de > weekdays or da < 0 or da > de:
            bad_days.append(f"{p['pid']} (enrolled {text(p['raw_enrolled'])}, {p['raw_attendance_label']} {text(p['raw_attendance'])})")
            p["days_enrolled"] = p["days_attended"] = None
        h = p["program_hours"]
        if h is None or h < 0 or h > max_hours:
            bad_hours.append(f"{p['pid']} ({text(p['raw_hours']) or 'blank'} hours)")
            p["program_hours"] = None
        if p["grade"] not in site_cfg["grades"]:
            bad_grade.append(f"{p['pid']} (grade {p['grade']})")
        for f in ("on_track", "family_engaged"):
            if p[f] == "invalid":
                bad_flags.append(f"{p['pid']} ({f.replace('_', ' ')} value not recognized)")
                p[f] = None
    if bad_days:
        issues.append(issue(sid, "error", "out_of_range",
                            f"Attendance days that can't be right (attended more than enrolled, or enrolled more than the {weekdays} weekdays in the quarter). "
                            "Left out of attendance and chronic absence; still counted as enrolled.", bad_days))
    if bad_hours:
        issues.append(issue(sid, "error", "out_of_range",
                            f"Program hours missing or above the {max_hours}-hour ceiling for the quarter. Left out of dosage; still counted as enrolled.", bad_hours))
    if bad_grade:
        issues.append(issue(sid, "warning", "grade_out_of_range",
                            f"Grade outside the grades this site serves ({site_cfg['grades'][0]}-{site_cfg['grades'][-1]}). Counted; ask the site to correct it.", bad_grade))
    if bad_flags:
        issues.append(issue(sid, "warning", "unrecognized_value", "Yes/no values the site config doesn't recognize. Treated as blank.", bad_flags))


def dedupe(site_cfg, people, issues):
    seen, out, dupes = {}, [], []
    for p in people:
        if p["pid"] in seen:
            dupes.append(p["pid"])
            continue
        seen[p["pid"]] = p
        out.append(p)
    if dupes:
        issues.append(issue(site_cfg["id"], "warning", "duplicate_rows",
                            "The same participant ID appears more than once. Kept the first row.", dupes))
    return out


def read_roster(site_cfg, files, qid, cfg, issues):
    cols = site_cfg["columns"]
    header, rows = read_table(files["main"], site_cfg.get("sheet", 0), site_cfg.get("header_contains"))
    missing = [v for v in cols.values() if v not in header]
    if missing:
        raise ValueError(f"columns not found in {files['main'].name}: {', '.join(missing)}")
    idx = {k: header.index(v) for k, v in cols.items()}
    people, reported_total = [], None
    total_label = site_cfg.get("reported_total_label")
    for r in rows:
        cell = lambda k: r[idx[k]] if idx[k] < len(r) else None  # noqa: E731
        first = text(r[0]) if r else ""
        if total_label and first == total_label:
            reported_total = number(r[1]) if len(r) > 1 else None
            continue
        if not first:
            continue
        enrolled = number(cell("days_enrolled"))
        if "days_attended" in cols:
            att_raw, att_label = cell("days_attended"), "attended"
            attended = number(att_raw)
        else:
            att_raw, att_label = cell("days_absent"), "absent"
            absent = number(att_raw)
            attended = None if enrolled is None or absent is None else enrolled - absent
        people.append({
            "pid": text(cell("pid")), "grade": text(cell("grade")),
            "days_enrolled": enrolled, "days_attended": attended,
            "program_hours": number(cell("program_hours")),
            "on_track": to_bool(site_cfg, "on_track", cell("on_track")),
            "family_engaged": to_bool(site_cfg, "family_engaged", cell("family_engaged")),
            "raw_enrolled": cell("days_enrolled"), "raw_attendance": att_raw, "raw_attendance_label": att_label,
            "raw_hours": cell("program_hours"),
        })
    people = dedupe(site_cfg, people, issues)
    if reported_total is not None and int(reported_total) != len(people):
        issues.append(issue(site_cfg["id"], "warning", "total_mismatch",
                            f"The spreadsheet's typed \"{total_label}\" says {int(reported_total)}, but it lists {len(people)} students. "
                            f"The report uses the {len(people)} listed."))
    validate_participants(site_cfg, people, qid, cfg, issues)
    return people, {"reported_total": reported_total}


def read_cms_export(site_cfg, files, qid, cfg, issues):
    sid, cols = site_cfg["id"], site_cfg["columns"]
    for part in (site_cfg["services_file"], site_cfg["school_file"]):
        if part not in files:
            raise ValueError(f"expected a {part} file")
    header, rows = read_table(files[site_cfg["services_file"]])
    i = {k: header.index(cols[k]) for k in ("record_id", "pid", "grade", "service_type", "minutes")}
    seen, dupes, conflicts, people = {}, [], [], {}
    for r in rows:
        if not r or not text(r[0]):
            continue
        rid, key = text(r[i["record_id"]]), tuple(text(c) for c in r)
        if rid in seen:
            dupes.append(rid)
            if seen[rid] != key:
                conflicts.append(rid)
            continue
        seen[rid] = key
        pid = text(r[i["pid"]])
        p = people.setdefault(pid, {"pid": pid, "grade": text(r[i["grade"]]), "minutes": 0, "family_engaged": False})
        if text(r[i["service_type"]]) in site_cfg["family_service_types"]:
            p["family_engaged"] = True
        else:
            p["minutes"] += number(r[i["minutes"]]) or 0
    if dupes:
        issues.append(issue(sid, "warning", "duplicate_rows",
                            "Service records exported twice (same service record ID). Counted once.", dupes))
    if conflicts:
        issues.append(issue(sid, "error", "conflicting_rows",
                            "The same service record ID appears with different details. Kept the first; ask the site which is right.", conflicts))
    header, rows = read_table(files[site_cfg["school_file"]])
    j = {k: header.index(cols[k]) for k in ("school_pid", "days_enrolled", "days_absent", "on_track")}
    school = {text(r[j["school_pid"]]): r for r in rows if r and text(r[0])}
    no_school = sorted(set(people) - set(school))
    not_in_program = sorted(set(school) - set(people))
    out = []
    for pid, p in sorted(people.items()):
        s = school.get(pid)
        enrolled = number(s[j["days_enrolled"]]) if s else None
        absent = number(s[j["days_absent"]]) if s else None
        out.append({
            "pid": pid, "grade": p["grade"],
            "days_enrolled": enrolled,
            "days_attended": None if enrolled is None or absent is None else enrolled - absent,
            "program_hours": round(p["minutes"] / 60, 1),
            "on_track": to_bool(site_cfg, "on_track", s[j["on_track"]]) if s else None,
            "family_engaged": p["family_engaged"],
            "raw_enrolled": enrolled, "raw_attendance": absent, "raw_attendance_label": "absent", "raw_hours": p["minutes"] / 60,
        })
    if no_school:
        issues.append(issue(sid, "warning", "unmatched_ids",
                            "In the case-management export but not in the district attendance file. Counted as enrolled; "
                            "left out of attendance, chronic absence and reading.", no_school))
        for p in out:
            if p["pid"] in no_school:
                p["no_school_record"] = True
    if not_in_program:
        issues.append(issue(sid, "info", "unmatched_ids",
                            "In the district file but with no program services this quarter. Not counted.", not_in_program))
    # Rows without a school record have no days at all; that's already reported above, so skip the range message for them.
    validate_participants(site_cfg, [p for p in out if not p.get("no_school_record")], qid, cfg, issues)
    for p in out:
        if p.get("no_school_record") and not (0 <= p["program_hours"] <= quarters.weekdays(qid, cfg["fiscal_year_start_month"]) * cfg["max_program_hours_per_weekday"]):
            p["program_hours"] = None
    return out, {"service_rows": len(seen), "duplicate_service_rows": len(dupes)}


def read_summary(site_cfg, files, qid, cfg, issues):
    sid = site_cfg["id"]
    header, rows = read_table(files["main"])
    values = {text(r[0]): number(r[1]) for r in rows if len(r) > 1}
    s = {}
    for key, labl in site_cfg["measures"].items():
        if labl not in values or values[labl] is None:
            issues.append(issue(sid, "error", "missing_value", f"\"{labl}\" is blank or missing on the summary form."))
            s[key] = None
        else:
            s[key] = values[labl]
    max_hours = quarters.weekdays(qid, cfg["fiscal_year_start_month"]) * cfg["max_program_hours_per_weekday"]
    problems = []
    if s["ada_pct"] is not None and not 0 <= s["ada_pct"] <= 100:
        problems.append(f"average daily attendance {text(s['ada_pct'])}% (must be 0 to 100)")
        s["ada_pct"] = None
    pairs = [("chronic", "chronic_eligible"), ("chronic_eligible", "enrolled"), ("hours_45_plus", "enrolled"),
             ("on_track", "assessed"), ("assessed", "enrolled"), ("family_engaged", "enrolled")]
    names = site_cfg["measures"]
    for part, whole in pairs:
        if s[part] is not None and s[whole] is not None and s[part] > s[whole]:
            problems.append(f"\"{names[part]}\" ({text(s[part])}) is more than \"{names[whole]}\" ({text(s[whole])})")
            s[part] = None
    if s["program_hours"] is not None and s["enrolled"] and s["program_hours"] / s["enrolled"] > max_hours:
        problems.append(f"total program hours {text(s['program_hours'])} is more than {max_hours} per student")
        s["program_hours"] = None
    if problems:
        issues.append(issue(sid, "error", "out_of_range",
                            "Summary values that can't be right: " + "; ".join(problems) + ". Left out of the totals until the site corrects them."))
    issues.append(issue(sid, "info", "not_verifiable",
                        "Site sends totals only, so its numbers can be range-checked but not re-added from student rows, "
                        "and it can't be included in the attendance-improvement measure."))
    return s, {}


ADAPTERS = {"roster": read_roster, "cms_export": read_cms_export, "summary": read_summary}


def ingest_quarter(folder, qid, cfg):
    """Return (sites, issues) for one quarter folder."""
    fy = cfg["fiscal_year_start_month"]
    due = quarters.due_date(qid, cfg["submission_due_days_after_quarter"], fy)
    submissions, stray = find_submissions(folder)
    issues, sites = [], {}
    for name in stray:
        issues.append(issue("(inbox)", "warning", "unrecognized_file",
                            f"File {name} doesn't follow the <site>__<received date> naming, so it was not read."))
    known = {s["id"] for s in cfg["sites"]}
    for sid in sorted(set(submissions) - known):
        issues.append(issue(sid, "warning", "unknown_site", f"Files for site \"{sid}\", which isn't in config/sites.json. Not read."))
    for site_cfg in cfg["sites"]:
        sid = site_cfg["id"]
        sub = submissions.get(sid)
        result = {"id": sid, "name": site_cfg["name"], "submits": site_cfg["submits"], "kind": "summary" if site_cfg["adapter"] == "summary" else "participants"}
        if not sub:
            result.update(status="missing", received=None)
            issues.append(issue(sid, "error", "missing_submission",
                                f"No file received (due {due.isoformat()}). The site appears in the report as missing; nothing is carried over from last quarter."))
            sites[sid] = result
            continue
        late_days = (sub["received"] - due).days
        result.update(status="late" if late_days > 0 else "on_time", received=sub["received"].isoformat(),
                      late_days=max(0, late_days), files=[p.name for p in sub["files"].values()])
        if late_days > 0:
            issues.append(issue(sid, "warning", "late_submission",
                                f"Received {sub['received'].isoformat()}, {late_days} days after the {due.isoformat()} due date. Included."))
        try:
            data, extra = ADAPTERS[site_cfg["adapter"]](site_cfg, sub["files"], qid, cfg, issues)
        except (ValueError, KeyError, IndexError) as e:
            issues.append(issue(sid, "error", "unreadable", f"Couldn't read the submission: {e}. Left out of the report until fixed."))
            result["status"] = "unreadable"
            sites[sid] = result
            continue
        if result["kind"] == "summary":
            result["summary"] = data
        else:
            result["participants"] = data
        result.update(extra)
        sites[sid] = result
    return sites, issues, due
