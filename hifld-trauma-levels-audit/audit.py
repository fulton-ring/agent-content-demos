import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import hashlib
    import json
    import os
    import re
    import shutil
    import time
    import urllib.error
    import urllib.request
    from pathlib import Path

    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from scipy.spatial import KDTree

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("AUDIT_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("AUDIT_OUT_DIR", HERE / "outputs"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    USER_AGENT = "fulton-ring-agent-content-demos/0.1 (https://github.com/fulton-ring/agent-content-demos)"
    SEED = 204
    EARTH_KM = 6371.0088
    LEVELS = ["I", "II", "III", "IV", "V"]
    KINDS = {"adult": "adult", "peds": "pediatric"}
    STATES = (
        "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
        "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY"
    ).split()
    # The trauma-access spike's straight-line-to-minutes lines (trauma-burn-center-access/outputs/summary.json,
    # "fits"), fitted on Valhalla drive times in Maine and New Jersey: minutes = a + b * km, by RUCA class.
    FITS = {
        "Metropolitan": (11.5, 0.703),
        "Micropolitan": (15.7, 0.614),
        "Small town": (28.9, 0.633),
        "Rural": (23.3, 0.711),
    }
    EXTRACTION_SAMPLE = 60
    # HIFLD's trauma levels date from 2023-2024; a list older than this can't judge them.
    OLDEST_LIST = "2022-01-01"
    # State tiers that aren't numbered, mapped to the nearest ACS level (see state_sources.csv notes).
    TIERS = {
        "RTC": "II", "RTH": "II", "ATH": "III", "CTH": "IV", "TRF": "V", "TRH": "V",  # Montana, Wyoming, South Dakota
        "PARC": "I",  # Maryland's Primary Adult Resource Center (Shock Trauma)
        # Mississippi's pediatric tiers: a Secondary center may be a Level III adult center and keeps children only
        # for orthopedic injuries (15 Miss. Code R. 3-1-7.2.1), so it maps to III, not II.
        "TERTIARY": "I", "SECONDARY": "III",
        "PTC": "unspecified",  # Florida designates Pediatric Trauma Centers with no level
    }  # fmt: skip
    # Tiers that mean a hospital takes part in the state system, not that it is a trauma center: Maine's Trauma
    # System Hospitals, and Mississippi's Primary Pediatric tier, which every designated hospital holds.
    # Tennessee's Comprehensive Regional Pediatric Center is a pediatric emergency-care tier, not a trauma level.
    NOT_TRAUMA = {"TSH", "PRIMARY", "CRPC"}
    # States whose list leaves out pediatric centers that other official documents designate (the pediatric check
    # found Los Angeles and Riverside county pediatric centers missing from California's list, and UK Kentucky
    # Children's Level I missing from Kentucky's map), so their pediatric levels count as unchecked.
    PEDS_LIST_INCOMPLETE = {"CA", "KY"}
    RUN_STARTED = time.perf_counter()

    def rank(level: str) -> int:
        """Position of a level, I highest; unnumbered and unknown levels sort last."""
        return LEVELS.index(level) if level in LEVELS else len(LEVELS)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # How complete are the trauma levels in HIFLD's hospital layer, and can we fix them?

    **The question.** The HIFLD hospital layer is the one national public file that carries a trauma level for
    every hospital, and most people who map access to trauma care reach for it. How far can you trust its
    `TRAUMA` field? The trauma-access spike (`trauma-burn-center-access/`, issue #148) found 102 Level I/II
    pediatric records in it against 148 real centers, and New Jersey with 1 of its 5. We expected adult levels to be
    mostly right, pediatric levels to be badly incomplete, and a corrected field to change who looks far from care.

    **How.** Each state designates its own trauma centers and most publish the list. We took each state's official
    list (the American College of Surgeons' verified-center search can't be used: it has no download and its terms
    forbid reuse in other applications), copied its rows into `state_designations.csv`, and matched each row by
    hand to a HIFLD record. This notebook compares the two, counts the errors by state, writes a corrected field,
    and reruns the spike's distance shares on it.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The data

    Downloaded at run time into `data/` and reused on later runs:

    - **Hospitals:** [HIFLD Next](https://hifld.publicenvirodata.org) `hospitals-3` v1.1.0 (issued 2026-04-06),
      its `TRAUMA`, `TYPE` and `STATUS` fields.
    - **Where people live:** Census 2020 population-weighted block-group centres.
    - **People and children under 18:** ACS 2018–2022 table-based summary file, table B01001, by block group.
    - **Rurality:** USDA ERS RUCA codes for 2020 tracts.

    Committed with the notebook, because they are our work rather than a download:

    - `state_sources.csv`: for each of the 50 states and DC, the official list we used, its date, its terms and
      whether it designates pediatric centers.
    - `state_designations.csv`: every row of those lists, one per hospital per kind (adult or pediatric), with the
      HIFLD `source_ID` we matched it to. The state documents themselves aren't committed.
    - `extraction_check.csv`: a seeded sample of those rows checked again against the source documents.
    - `added_locations.csv`: coordinates for Level I/II centers that have no HIFLD record, so the distance rerun
      can place them.
    """)
    return


@app.cell
def _():
    def fetch(url: str, name: str) -> Path:
        dest = DATA / name
        if dest.exists():
            return dest
        part = dest.with_name(name + ".part")
        for attempt in range(4):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=600) as response, part.open("wb") as out:
                    shutil.copyfileobj(response, out, 2**20)
                break
            except (urllib.error.URLError, TimeoutError):
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))
        part.rename(dest)
        return dest

    _acs = "https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/data/5YRData"
    files = {
        "hospitals": fetch(
            "https://storage.googleapis.com/hifld-next-datasets-prod/hifld/hospitals-3/hospitals-3/v1.1.0/geoparquet/hospitals-3.parquet",
            "hospitals-3.parquet",
        ),
        "centres": fetch(
            "https://www2.census.gov/geo/docs/reference/cenpop2020/blkgrp/CenPop2020_Mean_BG.txt",
            "CenPop2020_Mean_BG.txt",
        ),
        "age": fetch(f"{_acs}/acsdt5y2022-b01001.dat", "acsdt5y2022-b01001.dat"),
        "ruca": fetch(
            "https://www.ers.usda.gov/media/5443/2020-rural-urban-commuting-area-codes-census-tracts.csv",
            "ruca2020-tracts.csv",
        ),
    }
    pd.DataFrame(
        {"file": [p.name for p in files.values()], "MB": [round(p.stat().st_size / 1e6, 1) for p in files.values()]}
    )
    return (files,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The sources and their terms

    For each state we looked for the health department's or EMS office's own list of designated trauma centers,
    and recorded its date, its terms of use and whether it designates pediatric centers separately. A list is
    *reusable* when it is an official public list and nothing in the site's terms forbids reuse; *unclear* when
    the site claims copyright or limits reuse without addressing facts like these (lists of facts aren't
    copyrightable in the US, but we flag them). We use reusable and unclear lists dated 2022 or later (HIFLD's
    levels date from 2023–2024), and undated lists still posted as current. States with no official list, with
    terms that forbid reuse, or with only an older list keep HIFLD's values and are counted as unchecked.
    """)
    return


@app.cell
def _():
    sources = pd.read_csv(HERE / "state_sources.csv", dtype=str).fillna("")
    _extracted = pd.read_csv(HERE / "state_designations.csv", dtype=str).fillna("")
    # "Seeking provisional status" (Ohio) is an application, not a designation.
    designations = _extracted[~_extracted["level"].isin(NOT_TRAUMA) & (_extracted["status"] != "seeking")].reset_index(
        drop=True
    )
    assert set(sources["state"]) == set(STATES), (
        f"state_sources.csv must cover 51 states: {set(STATES) ^ set(sources['state'])}"
    )
    _by_state = sources.groupby("state").agg(
        reusable=("reusable", lambda s: "yes" if (s == "yes").all() else ("no" if (s == "no").all() else "unclear")),
        covers_peds=("covers_peds", lambda s: "yes" if (s == "yes").any() else "no"),
        list_date=("list_date", "max"),
    )
    _rows = designations.groupby("state").size()
    state_status = _by_state.assign(rows=_rows.reindex(_by_state.index, fill_value=0))
    state_status["current"] = (state_status["list_date"] == "") | (state_status["list_date"] >= OLDEST_LIST)
    state_status["checked_adult"] = (
        state_status["reusable"].isin(["yes", "unclear"]) & (state_status["rows"] > 0) & state_status["current"]
    )
    _peds_rows = designations[designations["kind"] == "peds"].groupby("state").size()
    state_status["checked_peds"] = (
        state_status["checked_adult"]
        & (state_status["covers_peds"] == "yes")
        & (_peds_rows.reindex(state_status.index, fill_value=0) > 0)
        & ~state_status.index.isin(PEDS_LIST_INCOMPLETE)
    )
    _dated = sources.loc[sources["state"].isin(state_status.index[state_status["checked_adult"]]), "list_date"]
    _dated = _dated[_dated != ""]
    source_counts = {
        "states and DC": len(state_status),
        "reusable official list": int((state_status["reusable"] == "yes").sum()),
        "official list, terms unclear": int((state_status["reusable"] == "unclear").sum()),
        "official list, but older than 2022": int((~state_status["current"] & (state_status["rows"] > 0)).sum()),
        "no usable list": int((~state_status["checked_adult"]).sum()),
        "checked for adult levels": int(state_status["checked_adult"].sum()),
        "checked for pediatric levels": int(state_status["checked_peds"].sum()),
        "list dates from": _dated.min(),
        "list dates to": _dated.max(),
        "checked lists with no stated date": int(
            ((sources["list_date"] == "") & sources["state"].map(state_status["checked_adult"])).sum()
        ),
    }
    source_counts
    return designations, source_counts, sources, state_status


@app.cell
def _(state_status):
    state_status
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## How good is the extraction?

    The rows were copied from the state documents by Claude agents, one per region, which also matched each row to
    a HIFLD record. A different pass re-read a seeded sample of rows against the source documents and checked the
    name, level, kind and HIFLD match. `extraction_check.csv` holds its verdicts; this cell draws the same sample,
    so a changed extraction shows up as unchecked rows.
    """)
    return


@app.cell
def _(designations):
    _key = designations["state"] + "|" + designations["list_name"] + "|" + designations["kind"]
    _rank = _key.map(lambda k: hashlib.sha256(f"{SEED}-{k}".encode()).hexdigest())
    check_sample = designations.loc[_rank.sort_values().index[:EXTRACTION_SAMPLE]]
    _checked_path = HERE / "extraction_check.csv"
    _checked = (
        pd.read_csv(_checked_path, dtype=str).fillna("")
        if _checked_path.exists()
        else pd.DataFrame(columns=["state", "list_name", "kind", "row_correct", "match_correct", "note"])
    )
    extraction_check = check_sample.merge(
        _checked[["state", "list_name", "kind", "row_correct", "match_correct", "note"]],
        on=["state", "list_name", "kind"],
        how="left",
    ).fillna({"row_correct": "unchecked", "match_correct": "unchecked"})
    extraction_accuracy = {
        "rows checked": int((extraction_check["row_correct"] != "unchecked").sum()),
        "row copied correctly (name, kind, level)": int((extraction_check["row_correct"] == "yes").sum()),
        "HIFLD match correct": int((extraction_check["match_correct"] == "yes").sum()),
    }
    extraction_accuracy
    return extraction_accuracy, extraction_check


@app.cell
def _(extraction_check):
    extraction_check[extraction_check["row_correct"].ne("yes") | extraction_check["match_correct"].ne("yes")]
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Reading HIFLD's trauma field

    `TRAUMA` is free text. We split it on commas and slashes and read each part: `LEVEL I` to `LEVEL V` is an
    adult level unless the part says `PEDIATRIC` or the hospital's `TYPE` is `CHILDREN` (and the part doesn't say
    `ADULT`), in which case it is pediatric. A bare `PEDIATRIC` (three Florida children's hospitals) is a pediatric
    designation with no level. Rehab designations are ignored. Montana, Wyoming and South Dakota use their own
    tiers, which both sides map to numbers the same way (table below). When a hospital has two parts of one kind,
    the higher level wins.
    """)
    return


@app.cell
def _(files):
    def parse_trauma(text: str, hospital_type: str) -> tuple[str, str]:
        """Adult and pediatric level ('' if none) in a HIFLD TRAUMA value."""
        found = {"adult": "", "peds": ""}
        for part in re.split(r"[,/]", (text or "").upper()):
            part = part.strip()
            if not part or "REHAB" in part or part == "NOT AVAILABLE":
                continue
            numbered = re.search(r"\bLEVEL (IV|V|I{1,3})\b", part)
            level = numbered.group(1) if numbered else TIERS.get(part, "unspecified" if part == "PEDIATRIC" else "")
            if not level:
                continue
            pediatric = "PEDIATRIC" in part or (hospital_type == "CHILDREN" and "ADULT" not in part)
            kind = "peds" if pediatric else "adult"
            if not found[kind] or rank(level) < rank(found[kind]):
                found[kind] = level
        return found["adult"], found["peds"]

    hifld = pd.read_parquet(files["hospitals"]).drop(columns=["geometry", "bbox"])
    hifld["source_ID"] = hifld["source_ID"].astype(str)
    _parsed = [parse_trauma(t, ty) for t, ty in zip(hifld["TRAUMA"], hifld["TYPE"], strict=True)]
    hifld["adult_hifld"] = [a for a, _ in _parsed]
    hifld["peds_hifld"] = [p for _, p in _parsed]
    # The trauma-access spike's own Level I/II reading, kept for the distance rerun's "before" list.

    def spike_levels(text: str, hospital_type: str) -> tuple[bool, bool]:
        """The trauma-access spike's reading (trauma-burn-center-access/access.py), copied unchanged."""
        adult = peds = False
        for part in re.split(r"[,/]", text.upper()):
            if "REHAB" in part:
                continue
            top_level = bool(re.search(r"\bLEVEL II?\b", part)) or part.strip() == "RTC"
            if part.strip() == "PEDIATRIC" or ("PEDIATRIC" in part and top_level):
                peds = True
            elif top_level and hospital_type == "CHILDREN":
                peds = True
            elif top_level:
                adult = True
        return adult, peds

    _kept = (hifld["STATUS"] == "OPEN") & ~hifld["TYPE"].isin(["PSYCHIATRIC", "REHABILITATION", "CRITICAL ACCESS"])
    _spike = [spike_levels(t or "", ty) for t, ty in zip(hifld["TRAUMA"], hifld["TYPE"], strict=True)]
    hifld["adult_spike"] = _kept & np.array([a for a, _ in _spike])
    hifld["peds_spike"] = _kept & np.array([p for _, p in _spike])
    _with_level = hifld[(hifld["adult_hifld"] != "") | (hifld["peds_hifld"] != "")]
    pd.crosstab(_with_level["adult_hifld"].replace("", "none"), _with_level["peds_hifld"].replace("", "none"))
    return (hifld,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Matching HIFLD against the state lists

    For every state whose list we could use, and for adult and pediatric levels separately (pediatric only where
    the state designates pediatric centers), we line up each HIFLD record that claims a level with each list row,
    by the `source_ID` the row was matched to. Every pair falls in one bucket:

    - **correct:** both give the same level.
    - **wrong level:** both say it's a trauma center, at different levels.
    - **missing, blank:** the state designates it, the hospital is in HIFLD, but its `TRAUMA` has no level of
      this kind.
    - **missing, absent:** the state designates it and HIFLD has no record of the hospital at all.
    - **stale:** HIFLD gives a level but the state's list doesn't have the hospital (dropped, closed, or never
      designated).
    - **stale, duplicate record:** a stale record within 500 m of a record the state does designate: HIFLD has the
      same campus twice and gives both the level.

    A provisional designation counts as designated, and a pediatric designation with no level (Florida's, and
    HIFLD's bare `PEDIATRIC`) matches a Level I or II. Separately, a designated hospital is **mistyped** when its
    HIFLD record is marked closed, or typed long-term care, psychiatric or rehabilitation, or (for Level I/II)
    critical access: any of these drops it from a trauma analysis that filters on `TYPE` and `STATUS`, as the
    trauma-access spike did.
    """)
    return


@app.cell
def _(designations, hifld, state_status):
    _ids = set(hifld["source_ID"])
    _unknown = designations[(designations["source_ID"] != "") & ~designations["source_ID"].isin(_ids)]
    assert _unknown.empty, f"state_designations.csv names unknown source_IDs: {_unknown['source_ID'].tolist()}"
    _bad_level = designations[~designations["level"].isin(LEVELS + list(TIERS))]
    assert _bad_level.empty, f"unexpected levels: {_bad_level[['state', 'list_name', 'level']].values.tolist()}"

    # A row a state lists for a hospital across its border is judged by the home state's own list instead.
    _record_state = designations["source_ID"].map(hifld.set_index("source_ID")["STATE"])
    _home = (designations["source_ID"] == "") | (_record_state == designations["state"])
    out_of_state_rows = designations[~_home]
    _list = designations[_home].assign(level=designations["level"].replace(TIERS))
    _list = _list.assign(_rank=_list["level"].map(rank)).sort_values("_rank")
    # A row with no HIFLD match gets its own key; two rows matched to one record keep the higher level.
    _list["key"] = np.where(
        _list["source_ID"] != "", _list["source_ID"], "list:" + _list["state"] + ":" + _list["list_name"]
    )
    _list = _list.drop_duplicates(["key", "kind"])

    _pairs = []
    for _kind in KINDS:
        _checked = state_status.index[state_status[f"checked_{_kind}"]]
        _h = hifld[(hifld[f"{_kind}_hifld"] != "") & hifld["STATE"].isin(_checked)]
        _h = _h[["source_ID", "STATE", f"{_kind}_hifld"]].rename(
            columns={"source_ID": "key", "STATE": "state", f"{_kind}_hifld": "hifld_level"}
        )
        _l = _list[(_list["kind"] == _kind) & _list["state"].isin(_checked)][["key", "state", "level", "list_name"]]
        _l = _l.rename(columns={"level": "state_level", "state": "list_state"})
        _m = _h.merge(_l, on="key", how="outer")
        _m["state"] = _m["state"].fillna(_m["list_state"])
        _m["kind"] = _kind
        _pairs.append(_m.drop(columns="list_state"))
    pairs = pd.concat(_pairs, ignore_index=True).fillna({"hifld_level": "", "state_level": "", "list_name": ""})
    pairs["in_hifld"] = ~pairs["key"].str.startswith("list:")
    pairs["bucket"] = np.select(
        [
            (pairs["hifld_level"] != "")
            & (
                (pairs["hifld_level"] == pairs["state_level"])
                # A pediatric designation with no level matches a Level I or II on the other side.
                | (pairs["hifld_level"].isin(["I", "II"]) & (pairs["state_level"] == "unspecified"))
                | ((pairs["hifld_level"] == "unspecified") & pairs["state_level"].isin(["I", "II"]))
            ),
            (pairs["hifld_level"] != "") & (pairs["state_level"] != ""),
            (pairs["state_level"] != "") & pairs["in_hifld"],
            pairs["state_level"] != "",
        ],
        ["correct", "wrong level", "missing, blank", "missing, absent"],
        default="stale",
    )
    # A stale record sitting on the same campus as a designated one (within 500 m) is a duplicate record.
    _xy = hifld.set_index("source_ID")[["LATITUDE", "LONGITUDE"]]
    for _kind in KINDS:
        _on_list = pairs[(pairs["kind"] == _kind) & (pairs["state_level"] != "") & pairs["in_hifld"]]
        _stale = pairs[(pairs["kind"] == _kind) & (pairs["bucket"] == "stale")]
        _a = np.radians(_xy.loc[_on_list["key"]].to_numpy(float))
        _b = np.radians(_xy.loc[_stale["key"]].to_numpy(float))
        _cos = np.sin(_b[:, :1]) * np.sin(_a[:, 0]) + np.cos(_b[:, :1]) * np.cos(_a[:, 0]) * np.cos(
            _b[:, 1:] - _a[:, 1]
        )
        _km = EARTH_KM * np.arccos(np.clip(_cos, -1, 1)).min(axis=1)
        pairs.loc[_stale.index[_km < 0.5], "bucket"] = "stale, duplicate record"

    _meta = hifld.set_index("source_ID")[["TYPE", "STATUS"]]
    _designated = pairs[(pairs["state_level"] != "") & pairs["in_hifld"]].join(_meta, on="key")
    _top = _designated["state_level"].isin(["I", "II"])
    _designated["mistyped"] = (
        (_designated["STATUS"] != "OPEN")
        | _designated["TYPE"].isin(["LONG TERM CARE", "PSYCHIATRIC", "REHABILITATION", "NOT AVAILABLE"])
        | (_top & (_designated["TYPE"] == "CRITICAL ACCESS"))
    )
    mistyped = _designated[_designated["mistyped"]]
    BUCKETS = ["correct", "wrong level", "missing, blank", "missing, absent", "stale", "stale, duplicate record"]
    national = pairs.groupby(["kind", "bucket"]).size().unstack(fill_value=0).reindex(columns=BUCKETS, fill_value=0)
    national["mistyped"] = mistyped.groupby("kind").size().reindex(national.index, fill_value=0)
    mo.vstack(
        [
            national,
            mo.md(f"{len(out_of_state_rows)} list rows name a hospital in another state and are left to that state."),
        ]
    )
    return BUCKETS, mistyped, national, out_of_state_rows, pairs


@app.cell
def _(BUCKETS, mistyped, pairs):
    by_state = (
        pairs.groupby(["state", "kind", "bucket"]).size().unstack(fill_value=0).reindex(columns=BUCKETS, fill_value=0)
    )
    by_state["mistyped"] = mistyped.groupby(["state", "kind"]).size().reindex(by_state.index, fill_value=0)
    by_state["share correct"] = (by_state["correct"] / by_state[BUCKETS].sum(axis=1)).round(3)
    by_state.to_csv(OUT / "errors_by_state.csv")
    pairs.to_csv(OUT / "pairs.csv", index=False)
    by_state
    return (by_state,)


@app.cell
def _(pairs):
    # The same buckets for Level I/II only: what a trauma-access analysis uses.
    _top = pairs[pairs["hifld_level"].isin(["I", "II", "unspecified"]) | pairs["state_level"].isin(["I", "II"])].copy()
    _top["hifld_top"] = _top["hifld_level"].isin(["I", "II", "unspecified"])
    _top["state_top"] = _top["state_level"].isin(["I", "II"])
    _top["bucket_top"] = np.select(
        [_top["hifld_top"] & _top["state_top"], _top["state_top"]],
        ["Level I/II in both", "Level I/II on state list only"],
        default="Level I/II in HIFLD only",
    )
    top_levels = _top.groupby(["kind", "bucket_top"]).size().unstack(fill_value=0)
    top_levels
    return (top_levels,)


@app.cell
def _(mistyped):
    mistyped[["state", "kind", "key", "list_name", "state_level", "TYPE", "STATUS"]]
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The corrected trauma field

    One row per HIFLD record that has a level on either side, plus one per list row with no HIFLD record. Where a
    state's list was checked, the corrected level is the list's level (blank if the list doesn't have the
    hospital); elsewhere HIFLD's value stands. `TRAUMA_corrected` writes the result in HIFLD's own style, and
    `change` says what happened. `corrected_trauma.csv` has every row; `diff_vs_v1.1.0.csv` only the changed ones.
    """)
    return


@app.cell
def _(designations, hifld, pairs, sources, state_status):
    _wide = pairs.pivot_table(index="key", columns="kind", values="state_level", aggfunc="first")
    _wide = _wide.reindex(columns=list(KINDS)).fillna("")
    _names = pairs.drop_duplicates("key").set_index("key")[["state", "list_name"]]
    # In a state with a current list but no pediatric list, a children's hospital it designates at Level I/II is
    # still added (nothing is removed there).
    _state_of = hifld.set_index("source_ID")["STATE"]
    _adds = designations[
        (designations["kind"] == "peds")
        & designations["level"].replace(TIERS).isin(["I", "II", "unspecified"])
        & designations["state"].map(state_status["checked_adult"])
        & ~designations["state"].map(state_status["checked_peds"])
    ]
    _adds = _adds[(_adds["source_ID"] == "") | (_adds["source_ID"].map(_state_of) == _adds["state"])]
    _adds = _adds.assign(
        key=np.where(_adds["source_ID"] != "", _adds["source_ID"], "list:" + _adds["state"] + ":" + _adds["list_name"]),
        level=_adds["level"].replace(TIERS),
    )
    _adds = _adds.assign(_rank=_adds["level"].map(rank)).sort_values("_rank").drop_duplicates("key").set_index("key")
    _names = pd.concat([_names, _adds[["state", "list_name"]]])
    _names = _names[~_names.index.duplicated()]
    _keys = set(hifld.loc[(hifld["adult_hifld"] != "") | (hifld["peds_hifld"] != ""), "source_ID"])
    _keys |= set(_wide.index) | set(_adds.index)
    corrected = pd.DataFrame(index=sorted(_keys))
    corrected = corrected.join(
        hifld.set_index("source_ID")[["NAME", "CITY", "STATE", "TYPE", "STATUS", "TRAUMA", "adult_hifld", "peds_hifld"]]
    )
    corrected["STATE"] = corrected["STATE"].fillna(_names["state"].reindex(corrected.index))
    corrected["NAME"] = corrected["NAME"].fillna(_names["list_name"].reindex(corrected.index))
    corrected = corrected.fillna({"adult_hifld": "", "peds_hifld": "", "TRAUMA": ""})
    for _kind in KINDS:
        _checked = corrected["STATE"].map(state_status[f"checked_{_kind}"]).fillna(False).astype(bool)
        _state_value = _wide[_kind].reindex(corrected.index).fillna("")
        corrected[f"{_kind}_corrected"] = np.where(_checked, _state_value, corrected[f"{_kind}_hifld"])
    _added = _adds["level"].reindex(corrected.index).fillna("")
    _fill = (corrected["peds_corrected"] == "") & (_added != "")
    corrected.loc[_fill, "peds_corrected"] = _added[_fill]

    def trauma_text(adult: str, peds: str) -> str:
        parts = [
            f"LEVEL {adult} ADULT" if adult in LEVELS else adult,
            f"LEVEL {peds} PEDIATRIC" if peds in LEVELS else peds,
        ]
        return ", ".join(p for p in parts if p)

    corrected["TRAUMA_corrected"] = [
        trauma_text(a, p) for a, p in zip(corrected["adult_corrected"], corrected["peds_corrected"], strict=True)
    ]
    _before = corrected["adult_hifld"] + "|" + corrected["peds_hifld"]
    _after = corrected["adult_corrected"] + "|" + corrected["peds_corrected"]
    _had = (corrected["adult_hifld"] != "") | (corrected["peds_hifld"] != "")
    _has = (corrected["adult_corrected"] != "") | (corrected["peds_corrected"] != "")
    corrected["change"] = np.select(
        [_before == _after, ~corrected.index.str.startswith("list:") & ~_had, ~_had, ~_has],
        ["unchanged", "added", "added (no HIFLD record)", "removed"],
        default="level changed",
    )
    _urls = sources.groupby("state")["source_url"].agg(" ; ".join)
    _checked_any = corrected["STATE"].map(state_status["checked_adult"]).fillna(False).astype(bool)
    corrected["checked_against"] = np.where(_checked_any, corrected["STATE"].map(_urls).fillna(""), "")
    corrected.index.name = "source_ID"
    corrected.to_csv(OUT / "corrected_trauma.csv")
    corrected[corrected["change"] != "unchanged"].to_csv(OUT / "diff_vs_v1.1.0.csv")
    corrected["change"].value_counts()
    return (corrected,)


@app.cell
def _(corrected, designations, hifld, state_status):
    # Pediatric Level I/II centers before (HIFLD, read the trauma-access spike's way) and after the correction.
    _peds_before = hifld[hifld["peds_spike"]]
    _peds_list = designations[(designations["kind"] == "peds") & designations["level"].replace(TIERS).isin(["I", "II"])]
    _peds_checked = _peds_list[_peds_list["state"].map(state_status["checked_peds"])]
    pediatric_counts = {
        "HIFLD pediatric Level I/II records (spike's filter)": len(_peds_before),
        "states that designate pediatric centers (checked)": int(state_status["checked_peds"].sum()),
        "pediatric Level I/II centers on those states' lists": len(_peds_checked),
        "HIFLD pediatric Level I/II records in those states": int(
            _peds_before["STATE"].map(state_status["checked_peds"]).fillna(False).sum()
        ),
        "of which on the state list at Level I/II": int(
            _peds_before["source_ID"].isin(set(_peds_checked["source_ID"])).sum()
        ),
        "pediatric Level I/II in the corrected field, nationally": int(
            corrected["peds_corrected"].isin(["I", "II", "unspecified"]).sum()
        ),
    }
    pediatric_counts
    return (pediatric_counts,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Because the pediatric disagreements drive the distance result, a separate pass checked every one of them
    (each hospital where HIFLD and the state list disagree on a pediatric Level I/II designation) against the state
    list, the hospital's own announcements and, for reading only, the ACS listing. Its verdicts are in
    `peds_check.csv`.
    """)
    return


@app.cell
def _():
    peds_check = pd.read_csv(HERE / "peds_check.csv", dtype=str).fillna("")
    peds_check_counts = {
        "pediatric disagreements checked": len(peds_check),
        "our reading of the state list right": int((peds_check["our_extraction_right"] == "yes").sum()),
        "HIFLD match right (or no record needed)": int(peds_check["match_right"].isin(["yes", "na"]).sum()),
        "hospital is a pediatric Level I/II center": int((peds_check["is_peds_I_II"] == "yes").sum()),
    }
    peds_check_counts
    return (peds_check_counts,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Does the fix change who looks far from care?

    The trauma-access spike put 12.8% of people beyond an hour's drive of a Level I/II adult trauma center and
    45.2% of children beyond an hour of a Level I/II pediatric one. We rebuild its national estimate exactly: each
    block group at its population-weighted centre, great-circle distance to the nearest center, converted to
    minutes with the spike's fitted lines by rurality (listed in the setup cell), weighted by people or by children
    under 18 (ACS 2018–2022). The *before* list reads HIFLD the spike's way, dropping closed, psychiatric,
    rehabilitation and critical-access records. The *after* list is the corrected field at Level I/II, taking a
    state-designated hospital whatever its HIFLD type, plus designated centers with no HIFLD record at the
    coordinates in `added_locations.csv`. In states whose list doesn't designate pediatric centers, the after list
    keeps HIFLD's pediatric records and adds any children's hospital the state designates at Level I/II.

    The spike falls back to a pooled line for the 315 block groups with no RUCA code; we leave them out, which
    reproduces its shares to the tenth of a point.
    """)
    return


@app.cell
def _(files):
    _centres = pd.read_csv(files["centres"], dtype=str, encoding="utf-8-sig")
    _centres[["lat", "lon"]] = _centres[["LATITUDE", "LONGITUDE"]].astype(float)
    _age_columns = [f"B01001_E{i:03d}" for i in (3, 4, 5, 6, 27, 28, 29, 30)]
    _age = pd.read_csv(files["age"], sep="|", usecols=["GEO_ID", "B01001_E001", *_age_columns])
    _age = _age[_age["GEO_ID"].str.startswith("1500000US")]
    _age = _age.assign(geoid=_age["GEO_ID"].str[9:], pop=_age["B01001_E001"], children=_age[_age_columns].sum(axis=1))
    _ruca = pd.read_csv(
        files["ruca"],
        dtype={"TractFIPS20": str, "TractFIPS23": str},
        usecols=["TractFIPS20", "TractFIPS23", "PrimaryRUCA"],
    )
    # The 2022 ACS moved Connecticut's tracts to planning regions; RUCA maps the 2020 codes to the new ones.
    _tract_2020 = _centres["STATEFP"] + _centres["COUNTYFP"] + _centres["TRACTCE"]
    _centres["geoid"] = (
        _tract_2020.map(dict(zip(_ruca["TractFIPS20"], _ruca["TractFIPS23"], strict=True))).fillna(_tract_2020)
        + _centres["BLKGRPCE"]
    )
    _ruca = _ruca.drop_duplicates("TractFIPS23")
    _ruca["rurality"] = pd.cut(
        _ruca["PrimaryRUCA"], [0, 3, 6, 9, 10], labels=["Metropolitan", "Micropolitan", "Small town", "Rural"]
    ).astype(str)
    bg = _age[_age["geoid"].str[:2] != "72"][["geoid", "pop", "children"]]
    bg = bg.merge(_centres[["geoid", "STATEFP", "lat", "lon"]], on="geoid", how="left")
    bg = bg.assign(tract=bg["geoid"].str[:11]).merge(
        _ruca[["TractFIPS23", "rurality"]].rename(columns={"TractFIPS23": "tract"}), on="tract", how="left"
    )
    people_checks = {
        "block groups": len(bg),
        "people": int(bg["pop"].sum()),
        "children under 18": int(bg["children"].sum()),
        "block groups without a centre or RUCA code (left out)": int((bg["lat"].isna() | bg["rurality"].isna()).sum()),
    }
    bg = bg[bg["lat"].notna() & bg["rurality"].notna()].reset_index(drop=True)
    people_checks
    return bg, people_checks


@app.cell
def _(bg, corrected, hifld, state_status):
    def unit_vectors(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        lat_r, lon_r = np.radians(lat), np.radians(lon)
        return np.column_stack([np.cos(lat_r) * np.cos(lon_r), np.cos(lat_r) * np.sin(lon_r), np.sin(lat_r)])

    def minutes_to_nearest(centers: pd.DataFrame) -> np.ndarray:
        tree = KDTree(unit_vectors(centers["LATITUDE"].to_numpy(float), centers["LONGITUDE"].to_numpy(float)))
        chord, _ = tree.query(unit_vectors(bg["lat"].to_numpy(), bg["lon"].to_numpy()))
        km = 2 * EARTH_KM * np.arcsin(np.clip(chord / 2, 0, 1))
        a = bg["rurality"].map({k: v[0] for k, v in FITS.items()})
        b = bg["rurality"].map({k: v[1] for k, v in FITS.items()})
        return (a + b * km).to_numpy()

    _top = ["I", "II", "unspecified"]
    _coords = hifld.set_index("source_ID")[["LATITUDE", "LONGITUDE", "STATE"]]
    _added = pd.read_csv(HERE / "added_locations.csv", dtype={"key": str})
    _added = _added.set_index("key")[["LATITUDE", "LONGITUDE", "state"]].rename(columns={"state": "STATE"})
    _coords = pd.concat([_coords, _added])
    center_sets = {}
    for _kind in KINDS:
        _before = hifld.loc[hifld[f"{_kind}_spike"], "source_ID"]
        _top_after = corrected[f"{_kind}_corrected"].isin(_top)
        # Where HIFLD's value stands unchecked, keep the spike's filter on type and status.
        _unchanged = corrected[f"{_kind}_corrected"] == corrected[f"{_kind}_hifld"]
        _checked = corrected["STATE"].map(state_status[f"checked_{_kind}"]).fillna(False).astype(bool)
        _dropped = ~_checked & _unchanged & ~corrected.index.isin(set(_before))
        _after = set(corrected.index[_top_after & ~_dropped])
        _missing = sorted(_after - set(_coords.index))
        assert not _missing, f"no coordinates for {_missing}; add them to added_locations.csv"
        center_sets[_kind] = {"before": sorted(_before), "after": sorted(_after)}

    shares = {}
    for _kind, _weight in (("adult", "pop"), ("peds", "children")):
        for _when in ("before", "after"):
            bg[f"{_kind}_{_when}_min"] = minutes_to_nearest(_coords.loc[center_sets[_kind][_when]])
            _beyond = bg[f"{_kind}_{_when}_min"] > 60
            shares[(_kind, _when)] = {
                "centers": len(center_sets[_kind][_when]),
                "share beyond 60 min": round(float(bg.loc[_beyond, _weight].sum() / bg[_weight].sum()), 4),
                "people beyond 60 min": int(bg.loc[_beyond, _weight].sum()),
            }
    distance_shares = pd.DataFrame(shares).T
    distance_shares
    return center_sets, distance_shares


@app.cell
def _(bg, hifld):
    # Where the corrected list moves children and adults most, by state.
    _abbrev = dict(zip(hifld["ST_FIPS"].astype(str).str.zfill(2), hifld["STATE"], strict=False))
    _rows = []
    for _fips, _g in bg.groupby("STATEFP"):
        _row = {"state": _abbrev.get(_fips, _fips)}
        for _kind, _weight in (("adult", "pop"), ("peds", "children")):
            for _when in ("before", "after"):
                _row[f"{_kind} beyond 60, {_when}"] = round(
                    float(_g.loc[_g[f"{_kind}_{_when}_min"] > 60, _weight].sum() / _g[_weight].sum()), 3
                )
        _rows.append(_row)
    shift_by_state = pd.DataFrame(_rows)
    shift_by_state["peds change (points)"] = (
        100 * (shift_by_state["peds beyond 60, after"] - shift_by_state["peds beyond 60, before"])
    ).round(1)
    shift_by_state["adult change (points)"] = (
        100 * (shift_by_state["adult beyond 60, after"] - shift_by_state["adult beyond 60, before"])
    ).round(1)
    shift_by_state.to_csv(OUT / "distance_shift_by_state.csv", index=False)
    shift_by_state.sort_values("peds change (points)")
    return (shift_by_state,)


@app.cell
def _(BUCKETS, by_state):
    # Each state's records by bucket, adult and pediatric side by side.
    _colors = ["#4c78a8", "#f2a541", "#e45756", "#9d2a2a", "#b0b0b0", "#dcdcdc"]
    _fig, _axes = plt.subplots(1, 2, figsize=(11, 9), gridspec_kw={"width_ratios": [3, 1]})
    for _ax, _kind in zip(_axes, KINDS, strict=True):
        _t = by_state.xs(_kind, level="kind")[BUCKETS]
        _t = _t.loc[(_t["correct"] / _t.sum(axis=1)).sort_values(ascending=False).index]
        _left = np.zeros(len(_t))
        for _bucket, _color in zip(BUCKETS, _colors, strict=True):
            _ax.barh(_t.index, _t[_bucket], left=_left, color=_color, label=_bucket)
            _left += _t[_bucket].to_numpy()
        _ax.invert_yaxis()
        _ax.tick_params(axis="y", labelsize=7)
        _ax.set_title(f"{KINDS[_kind]} levels ({len(_t)} states)")
        _ax.set_xlabel("records")
    _axes[0].legend(fontsize=8, loc="lower right")
    _fig.suptitle("HIFLD hospitals-3 v1.1.0 trauma levels against each state's list, states ordered by share correct")
    _fig.tight_layout()
    _fig.savefig(OUT / "buckets_by_state.png", dpi=130)
    _fig
    return


@app.cell
def _(
    distance_shares,
    extraction_accuracy,
    national,
    pediatric_counts,
    peds_check_counts,
    people_checks,
    source_counts,
    top_levels,
):
    summary = {
        "sources": source_counts,
        "extraction_check": extraction_accuracy,
        "pediatric_disagreement_check": peds_check_counts,
        "records_by_bucket": {k: {c: int(v) for c, v in row.items()} for k, row in national.iterrows()},
        "level_I_II": {k: {c: int(v) for c, v in row.items()} for k, row in top_levels.iterrows()},
        "pediatric": pediatric_counts,
        "distance": {
            f"{kind} {when}": {c: (float(v) if isinstance(v, float) else int(v)) for c, v in row.items()}
            for (kind, when), row in distance_shares.iterrows()
        },
        "people": people_checks,
        "seconds": round(time.perf_counter() - RUN_STARTED),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    summary
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **Four states have no list to check against.** Connecticut, Rhode Island and Vermont designate by American
      College of Surgeons verification and publish no list of their own; Oklahoma's hospitals report their own
      level on a licensing form and the state doesn't publish the results. New Mexico's only official list is an
      archived 2013 map and North Dakota's a 2020 map that shows levels by marker colour; both are too old. These
      six keep HIFLD's values.
    - **Sixteen checked states have no usable pediatric list.** Fourteen don't designate pediatric centers
      separately (New Jersey and Tennessee among them). In California and Kentucky the pediatric check found
      designated centers missing from the state's list. Their pediatric records stay unchecked: the corrected
      list keeps HIFLD's records and adds children's hospitals the state designates at Level I or II. A state list
      can't confirm New Jersey's 1-of-5 gap from the trauma-access spike for this reason.
    - **Some sources aren't the state's own document.** Pennsylvania's list is the press release of the
      nonprofit the state law names as its accreditor; Colorado's, Kansas's, Missouri's and Wisconsin's come from
      the state's own map services because their pages blocked us or only show a map; Mississippi's PDF was taken
      down in a site redesign and was read from a cached copy. `state_sources.csv` says which.
    - **Several lists are undated or a few years old** (West Virginia 2022, New Jersey 2024). A hospital dropped
      since then shows as correct; one added since shows as stale.
    - **Tiers don't line up perfectly.** Montana, Wyoming and South Dakota map their tiers to levels; Mississippi's
      Secondary pediatric tier sits between Levels II and III and we called it III; Maine's "Trauma System
      Hospital" and Mississippi's "Primary Pediatric" mean taking part in the system, not a trauma level, and are
      dropped. Changing any of these moves a handful of records.
    - **Matching is by hand and campus-level.** A children's hospital with no HIFLD record of its own is matched
      to the adult campus it shares; where HIFLD has two records for one campus, the one the list row matches is
      judged and the other shows as a duplicate.
    - **The distance rerun reuses the trauma-access spike's straight-line-to-minutes lines**, fitted on two
      northeastern states; its ±5-point caveat on national shares applies here too. It moves only the facility
      list, not the method.
    """)
    return


if __name__ == "__main__":
    app.run()
