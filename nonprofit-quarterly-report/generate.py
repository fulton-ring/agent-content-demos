"""Generate one quarter of synthetic site submissions into inbox/<quarter>/.

Every number here is made up. The participants are simulated once per site
(seeded, so every run produces the same files) and followed from quarter to
quarter. Each site then writes its data the way that site really would:
a hand-kept spreadsheet, a case-management export plus a district file,
a summary form, a spreadsheet with a title block, or the organization's
own CSV template. A few realistic problems are planted on purpose (see
PROBLEMS) so the refresh has something to catch.

    python3 generate.py FY26-Q1
"""

import csv
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pipeline import quarters  # noqa: E402
from pipeline.xlsx import write_xlsx  # noqa: E402

CONFIG = json.loads((HERE / "config" / "sites.json").read_text())
FY_START = CONFIG["fiscal_year_start_month"]

# Instructional days in each fiscal quarter (school starts late August).
SCHOOL_DAYS = {1: 28, 2: 54, 3: 58, 4: 50}
SITE_SIZE = {"eastgate": 112, "riverside": 138, "lincoln": 64, "westfield": 92, "harbor": 81}

# When each site's file arrives, in days relative to the due date
# (negative is early). None means nothing arrives.
ARRIVAL = {
    "FY26-Q1": {"eastgate": -6, "riverside": -3, "lincoln": -1, "westfield": -4, "harbor": None},
    "FY26-Q2": {"eastgate": -5, "riverside": -2, "lincoln": -3, "westfield": -1, "harbor": 12},
}
DEFAULT_ARRIVAL = {"eastgate": -5, "riverside": -2, "lincoln": -3, "westfield": -1, "harbor": -4}

# Problems planted in specific quarters, the kind each format tends to have.
PROBLEMS = {
    "FY26-Q1": {
        "riverside": {"duplicate_service_rows": 5, "cms_ids_missing_from_district": 2, "district_ids_not_in_cms": 1},
        "westfield": {"absences_over_enrolled": 1, "hours_out_of_range": 1},
    },
    "FY26-Q2": {
        "eastgate": {"typed_total_off_by": 2},
        "lincoln": {"ada_typo": True},
        "westfield": {"grade_out_of_range": 1},
        "riverside": {"duplicate_service_rows": 3},
    },
}


def excel_serial(d):
    return (d - date(1899, 12, 30)).days


def binomial(rng, n, p):
    return sum(rng.random() < p for _ in range(n))


def population(site):
    """Everyone who will ever enroll at this site, with fixed traits."""
    rng = random.Random(f"pop-{site['id']}")
    prefix = site["id"][:2].upper()
    people = []
    for i in range(int(SITE_SIZE[site["id"]] * 1.6)):
        roll = rng.random()
        att = rng.uniform(0.74, 0.90) if roll < 0.15 else rng.uniform(0.925, 0.995)
        people.append({
            "pid": f"{prefix}{1000 + i}",
            "grade_index": rng.randrange(len(site["grades"])),
            "att": att,
            "engagement": rng.uniform(0.25, 0.95),
            "reading": min(0.9, max(0.15, rng.gauss(0.5, 0.18) + (att - 0.9))),
            "family": rng.uniform(0.15, 0.75),
        })
    return people


def active_participants(site, qid):
    """Who is enrolled this quarter: the starting cohort, minus exits, plus new enrollees."""
    people = population(site)
    base = SITE_SIZE[site["id"]]
    k = quarter_index(qid)
    rng = random.Random(f"active-{site['id']}")
    active = people[:base]
    nxt = base
    for _ in range(k):
        active = [p for p in active if rng.random() > 0.06]
        joiners = round(base * 0.08)
        active += people[nxt:nxt + joiners]
        nxt += joiners
    return active, k


def quarter_index(qid):
    """Quarters since FY26-Q1, the first quarter of the program in this demo."""
    fy, q = int(qid[2:4]), int(qid[-1])
    return max(0, (fy - 26) * 4 + q - 1)


def simulate(site, qid):
    active, k = active_participants(site, qid)
    q = int(qid[-1])
    start, end = quarters.parse(qid, FY_START)
    days = SCHOOL_DAYS[q]
    rng = random.Random(f"sim-{site['id']}-{qid}")
    rows = []
    for p in active:
        late_join = rng.random() < 0.08
        enrolled = rng.randint(6, days - 3) if late_join else days
        enroll_date = end - timedelta(days=int(enrolled * 1.4)) if late_join else (date(2025, 8, 20) if k == 0 else start)
        # The program effect is assumed, not measured: engaged students creep up a little each quarter.
        att = min(0.995, p["att"] + 0.015 * k * p["engagement"])
        absent = binomial(rng, enrolled, 1 - att)
        attended = enrolled - absent
        program_days = binomial(rng, attended, p["engagement"] * 0.8)
        if q == 1:  # Q1 also has the six-week summer program, three hours a day
            program_days += binomial(rng, 30, p["engagement"] * 0.6)
        hours = round(program_days * rng.choice([2.0, 2.5, 2.5, 3.0]), 1)
        reading = min(0.95, p["reading"] + 0.05 * k * p["engagement"])
        assessed = rng.random() > 0.05
        rows.append({
            "pid": p["pid"],
            "grade": site["grades"][p["grade_index"]],
            "enroll_date": enroll_date,
            "exit_date": None,
            "days_enrolled": enrolled,
            "days_absent": absent,
            "days_attended": attended,
            "program_hours": hours,
            "on_track": (rng.random() < reading) if assessed else None,
            "family_engaged": rng.random() < min(0.9, p["family"] + 0.04 * k),
        })
    rows.sort(key=lambda r: r["pid"])
    return rows


def yn(v, yes, no, blank=""):
    return blank if v is None else (yes if v else no)


def write_eastgate(site, rows, path, problems):
    header = list(site["columns"].values())
    out = [header]
    for r in rows:
        out.append([r["pid"], r["grade"], excel_serial(r["enroll_date"]), None, r["days_enrolled"],
                    r["days_attended"], r["program_hours"], yn(r["on_track"], "Met", "Not Met"),
                    "Y" if r["family_engaged"] else None])
    out.append([])
    out.append([site["reported_total_label"], len(rows) + problems.get("typed_total_off_by", 0)])
    write_xlsx(path.with_suffix(".xlsx"), [("Roster", out), ("Notes", [["Hours from sign-in sheets, entered weekly"]])])


def write_westfield(site, rows, path, problems, qid):
    rng = random.Random(f"wf-{qid}")
    bad = rows[:]
    rng.shuffle(bad)
    for r in bad[:problems.get("absences_over_enrolled", 0)]:
        r["days_absent"] = r["days_enrolled"] + rng.randint(2, 9)
    for r in bad[1:1 + problems.get("hours_out_of_range", 0)]:
        r["program_hours"] = 400
    for r in bad[2:2 + problems.get("grade_out_of_range", 0)]:
        r["grade"] = "13"
    yes_no = [("Yes", "No"), ("Y", "N"), (1, 0)]
    out = [["Westfield High School - Youth Success Program"], [f"Quarter: {quarters.label(qid, FY_START)}"], [],
           list(site["columns"].values())]
    for r in rows:
        y, n = rng.choice(yes_no)
        out.append([r["pid"], int(r["grade"]) if r["grade"].isdigit() else r["grade"], excel_serial(r["enroll_date"]), None,
                    r["days_enrolled"], r["days_absent"], r["program_hours"], yn(r["on_track"], y, n, None),
                    "Y" if r["family_engaged"] else "N"])
    write_xlsx(path.with_suffix(".xlsx"), [(f"{qid} Data", out)])


def write_harbor(site, rows, path):
    with open(path.with_suffix(".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(site["columns"].values()))
        for r in rows:
            w.writerow([r["pid"], r["grade"], r["enroll_date"].isoformat(), "", r["days_enrolled"], r["days_attended"],
                        r["program_hours"], yn(r["on_track"], "yes", "no"), "yes" if r["family_engaged"] else "no"])


def write_riverside(site, rows, path, problems, qid):
    rng = random.Random(f"rv-{qid}")
    start, end = quarters.parse(qid, FY_START)
    cols = site["columns"]
    services = []
    for r in rows:
        minutes_left = int(r["program_hours"] * 60)
        while minutes_left > 0:
            m = min(minutes_left, rng.choice([60, 90, 120, 150]))
            kind = rng.choice(["Tutoring", "Tutoring", "Mentoring", "Enrichment"])
            day = start + timedelta(days=rng.randint(50 if int(qid[-1]) == 1 else 0, (end - start).days))
            services.append([r["pid"], r["grade"], r["enroll_date"].isoformat(), "", day.isoformat(), kind, m])
            minutes_left -= m
        if r["family_engaged"]:
            day = start + timedelta(days=rng.randint(55, (end - start).days))
            services.append([r["pid"], r["grade"], r["enroll_date"].isoformat(), "", day.isoformat(), "Family Event", 90])
    services.sort(key=lambda s: (s[4], s[0]))
    services = [[f"SVC-{qid[-1]}{n:05d}"] + s for n, s in enumerate(services)]
    for s in rng.sample(services, problems.get("duplicate_service_rows", 0)):
        services.append(list(s))  # the export repeats a record, ID and all
    services.sort(key=lambda s: (s[5], s[1]))
    with open(f"{path}__{site['services_file']}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([cols["record_id"], cols["pid"], cols["grade"], "Program Start", "Program End", "Service Date", cols["service_type"], cols["minutes"]])
        w.writerows(services)

    school = [r for r in rows]
    for r in rng.sample(school, problems.get("cms_ids_missing_from_district", 0)):
        school.remove(r)
    extra = problems.get("district_ids_not_in_cms", 0)
    with open(f"{path}__{site['school_file']}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([cols["school_pid"], cols["days_enrolled"], cols["days_absent"], cols["on_track"]])
        for r in school:
            w.writerow([r["pid"], r["days_enrolled"], r["days_absent"], yn(r["on_track"], "ON TRACK", "BELOW", "NOT TESTED")])
        for i in range(extra):
            w.writerow([f"RI{9000 + i}", SCHOOL_DAYS[int(qid[-1])], 3, "BELOW"])


def write_lincoln(site, rows, path, problems):
    m = site["measures"]
    eligible = [r for r in rows if r["days_enrolled"] >= 10]
    ada = 100 * sum(r["days_attended"] for r in rows) / sum(r["days_enrolled"] for r in rows)
    values = {
        "enrolled": len(rows),
        "ada_pct": round(ada, 1),
        "chronic_eligible": len(eligible),
        "chronic": sum(r["days_absent"] / r["days_enrolled"] >= 0.10 for r in eligible),
        "program_hours": round(sum(r["program_hours"] for r in rows)),
        "hours_45_plus": sum(r["program_hours"] >= 45 for r in rows),
        "assessed": sum(r["on_track"] is not None for r in rows),
        "on_track": sum(bool(r["on_track"]) for r in rows),
        "family_engaged": sum(r["family_engaged"] for r in rows),
    }
    if problems.get("ada_typo"):
        values["ada_pct"] = int(round(values["ada_pct"] * 10))  # 91.2 typed as 912
    with open(path.with_suffix(".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Measure", "Value"])
        for key, labl in m.items():
            w.writerow([labl, values[key]])
        w.writerow(["Prepared by", "Site coordinator"])


def generate(qid, inbox):
    quarters.parse(qid, FY_START)
    due = quarters.due_date(qid, CONFIG["submission_due_days_after_quarter"], FY_START)
    folder = inbox / qid
    folder.mkdir(parents=True, exist_ok=True)
    arrival = ARRIVAL.get(qid, DEFAULT_ARRIVAL)
    problems = PROBLEMS.get(qid, {})
    written = []
    for site in CONFIG["sites"]:
        offset = arrival.get(site["id"])
        if offset is None:
            continue
        received = due + timedelta(days=offset)
        path = folder / f"{site['id']}__{received.isoformat()}"
        rows = simulate(site, qid)
        p = problems.get(site["id"], {})
        if site["id"] == "eastgate":
            write_eastgate(site, rows, path, p)
        elif site["id"] == "riverside":
            write_riverside(site, rows, path, p, qid)
        elif site["id"] == "lincoln":
            write_lincoln(site, rows, path, p)
        elif site["id"] == "westfield":
            write_westfield(site, rows, path, p, qid)
        elif site["id"] == "harbor":
            write_harbor(site, rows, path)
        written.append(site["id"])
    return folder, written


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 generate.py FY26-Q1")
    folder, written = generate(sys.argv[1], HERE / "inbox")
    print(f"wrote {len(written)} site submissions to {folder.relative_to(HERE)}: {', '.join(written)}")
