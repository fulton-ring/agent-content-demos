"""Site and organization measures, and the checks that the totals tie.

Counts are stored and every percentage is computed from counts, the way the
Full-Service Community Schools guidance asks for chronic absence. Values
set aside by ingest (None) are left out of the measure they belong to.
"""

COUNT_KEYS = ["enrolled", "chronic_eligible", "chronic", "hours_reported", "hours_45_plus", "program_hours",
              "assessed", "on_track", "family_engaged"]
DOSAGE_BANDS = [("Under 15", 0, 15), ("15-44", 15, 45), ("45-89", 45, 90), ("90+", 90, None)]


def site_counts_from_participants(people):
    days = [p for p in people if p["days_enrolled"] is not None]
    eligible = [p for p in days if p["days_enrolled"] >= 10]
    hours = [p["program_hours"] for p in people if p["program_hours"] is not None]
    return {
        "enrolled": len(people),
        "days_enrolled": sum(p["days_enrolled"] for p in days),
        "days_attended": sum(p["days_attended"] for p in days),
        "ada_pct": round(100 * sum(p["days_attended"] for p in days) / sum(p["days_enrolled"] for p in days), 1) if days else None,
        "chronic_eligible": len(eligible),
        "chronic": sum((p["days_enrolled"] - p["days_attended"]) / p["days_enrolled"] >= 0.10 for p in eligible),
        "hours_reported": len(hours),
        "hours_45_plus": sum(h >= 45 for h in hours),
        "program_hours": round(sum(hours), 1),
        "dosage_bands": [sum(lo <= h and (hi is None or h < hi) for h in hours) for _, lo, hi in DOSAGE_BANDS],
        "assessed": sum(p["on_track"] is not None for p in people),
        "on_track": sum(p["on_track"] is True for p in people),
        "family_engaged": sum(p["family_engaged"] is True for p in people),
    }


def site_counts_from_summary(s):
    c = {k: (int(s[k]) if s.get(k) is not None else None) for k in
         ["enrolled", "chronic_eligible", "chronic", "hours_45_plus", "assessed", "on_track", "family_engaged"]}
    c["program_hours"] = s.get("program_hours")
    c["hours_reported"] = c["enrolled"] if s.get("program_hours") is not None and c["hours_45_plus"] is not None else None
    c["ada_pct"] = s.get("ada_pct")
    c["dosage_bands"] = None
    return c


def rates(c):
    def pct(a, b):
        return round(100 * c[a] / c[b], 1) if c.get(a) is not None and c.get(b) else None
    return {
        "ada_pct": c.get("ada_pct"),
        "chronic_pct": pct("chronic", "chronic_eligible"),
        "hours_45_plus_pct": pct("hours_45_plus", "hours_reported"),
        "avg_hours": round(c["program_hours"] / c["hours_reported"], 1) if c.get("program_hours") is not None and c.get("hours_reported") else None,
        "on_track_pct": pct("on_track", "assessed"),
        "family_pct": pct("family_engaged", "enrolled"),
    }


def attendance_improvement(people, prior_people):
    """Of participants at or below 90% attendance last quarter, how many improved this quarter (21st CCLC-style)."""
    if prior_people is None:
        return None
    prior = {p["pid"]: p for p in prior_people if p["days_enrolled"]}
    base = improved = 0
    for p in people:
        q = prior.get(p["pid"])
        if not q or not p["days_enrolled"]:
            continue
        before = q["days_attended"] / q["days_enrolled"]
        if before <= 0.90:
            base += 1
            improved += p["days_attended"] / p["days_enrolled"] > before
    return {"base": base, "improved": improved}


def org_totals(site_rows):
    """Route A: add up the site rows."""
    included = [s for s in site_rows if s.get("counts")]
    t = {}
    for k in COUNT_KEYS:
        vals = [s["counts"][k] for s in included if s["counts"].get(k) is not None]
        t[k] = round(sum(vals), 1) if vals else None
    ada_sites = [s for s in included if s["counts"].get("ada_pct") is not None]
    weight = sum(s["counts"]["enrolled"] for s in ada_sites)
    t["ada_pct"] = round(sum(s["counts"]["ada_pct"] * s["counts"]["enrolled"] for s in ada_sites) / weight, 1) if weight else None
    t["ada_sites"] = len(ada_sites)
    bands = [s["counts"]["dosage_bands"] for s in included if s["counts"].get("dosage_bands")]
    t["dosage_bands"] = [sum(b[i] for b in bands) for i in range(len(DOSAGE_BANDS))] if bands else None
    imp = [s["improvement"] for s in included if s.get("improvement")]
    t["improvement"] = {"base": sum(i["base"] for i in imp), "improved": sum(i["improved"] for i in imp)} if imp else None
    return t


def org_totals_from_rows(sites):
    """Route B: recount from every participant row and summary form directly, without the site rows."""
    everyone = [p for s in sites.values() for p in s.get("participants", [])]
    t = site_counts_from_participants(everyone) if everyone else {k: 0 for k in COUNT_KEYS}
    for s in sites.values():
        if "summary" in s:
            c = site_counts_from_summary(s["summary"])
            for k in COUNT_KEYS:
                if c.get(k) is not None:
                    t[k] = round((t.get(k) or 0) + c[k], 1)
    return {k: t.get(k) for k in COUNT_KEYS}


def tie_out(site_rows, totals, sites):
    """Every count in the total row must equal the sum of the site rows and a recount from the raw rows."""
    recount = org_totals_from_rows(sites)
    results = []
    for k in COUNT_KEYS:
        site_sum = round(sum(s["counts"][k] for s in site_rows if s.get("counts") and s["counts"].get(k) is not None), 1)
        results.append({"measure": k, "total_row": totals[k], "sum_of_sites": site_sum, "recount": recount[k],
                        "ties": (totals[k] or 0) == site_sum == (recount[k] or 0)})
    return results
