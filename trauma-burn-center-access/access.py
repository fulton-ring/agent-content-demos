import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import hashlib
    import json
    import os
    import re
    import shutil
    import subprocess
    import time
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import httpx
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import valhalla
    from scipy.spatial import KDTree

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("ACCESS_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("ACCESS_OUT_DIR", HERE / "outputs"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    SEED = 148
    HAND_SAMPLE = {"adult": 30, "peds": 15, "burn": 20}
    EARTH_KM = 6371.0088
    KINDS = {
        "adult": "Level I/II adult trauma center",
        "peds": "Level I/II pediatric trauma center",
        "burn": "Burn center",
    }
    STATES = {
        "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
        "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
        "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
        "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
        "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
        "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
        "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
        "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
        "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
        "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    }  # fmt: skip
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # How far is each US community from a major trauma center and a burn center?

    **The question.** How long does it take to drive from each US block group to the nearest Level I or II adult
    trauma center, Level I or II pediatric trauma center, and burn center, and does that time fall unevenly by
    rurality, income, race and ethnicity, age and environmental-justice burden? We expected most people to live
    within an hour of a major trauma center, the people beyond it to be disproportionately rural, poorer and older,
    and burn-center access to be far more uneven than trauma access.

    **How.** Every block group is placed at its 2020 population-weighted centre. We measure straight-line distance to
    the nearest facility of each kind for the whole country, and road drive time on OpenStreetMap with the open
    [Valhalla](https://valhalla.github.io/valhalla/) router for two contrasting states, Maine (the most rural state
    by Census share) and New Jersey (one of the most urban). The two routed states calibrate a conversion from
    straight-line kilometres to drive minutes, which gives a national estimate, and they show how far the two
    methods disagree. Times are ground travel only, from the block group's centre to the hospital, with no traffic,
    dispatch or scene time and no helicopters.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The data

    Everything is downloaded at run time into `data/` and reused on later runs. Downloads retry four times with
    backoff, and a file with a published MD5 that doesn't match stops the run.

    - **Hospitals and trauma levels:** [HIFLD Next](https://hifld.publicenvirodata.org) `hospitals-3` v1.1.0,
      its `TRAUMA` field. Issued 2026-04-06; its source dates run to 2024-06.
    - **Burn centers:** [Wikipedia's list of burn centers in the United States
      ](https://en.wikipedia.org/wiki/List_of_burn_centers_in_the_United_States), revision 1379563112
      (2026-10-10), CC BY-SA 4.0.
    - **Where people live:** Census 2020 [population-weighted block-group centres
      ](https://www.census.gov/geographies/reference-files/time-series/geo/centers-population.html).
    - **Population, low income, age 65+, demographic index:** EPA EJScreen 2024 block groups (ACS 2018–2022),
      the [Harvard Dataverse copy](https://doi.org/10.7910/DVN/RLR5AX) that `ej-datasets-hifld-next/` rebuilds;
      its download is reused if that folder has run.
    - **Race and ethnicity, children under 18:** ACS 2018–2022 table-based summary file, tables B03002 and B01001.
    - **Rural and urban:** USDA ERS [RUCA codes](https://www.ers.usda.gov/data-products/rural-urban-commuting-area-codes)
      for 2020 tracts.
    - **Roads:** OpenStreetMap's US Northeast extract from
      [openstreetmap.fr](https://download.openstreetmap.fr/extracts/north-america/), the latest at run time.
    """)
    return


@app.cell
def _():
    def fetch(url: str, name: str, md5: str | None = None) -> Path:
        dest = DATA / name
        if not dest.exists():
            part = dest.with_name(name + ".part")
            for attempt in range(4):
                try:
                    with httpx.stream(
                        "GET",
                        url,
                        follow_redirects=True,
                        timeout=600,
                        headers={"User-Agent": "fulton-ring agent-content-demos (trauma-burn-center-access)"},
                    ) as response:
                        response.raise_for_status()
                        with part.open("wb") as out:
                            for chunk in response.iter_bytes(2**20):
                                out.write(chunk)
                    break
                except httpx.HTTPError:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** (attempt + 1))
            part.rename(dest)
        if md5:
            digest = hashlib.md5()
            with dest.open("rb") as f:
                for block in iter(lambda: f.read(2**22), b""):
                    digest.update(block)
            if digest.hexdigest() != md5:
                raise ValueError(f"{name}: MD5 {digest.hexdigest()} != published {md5}")
        return dest

    return (fetch,)


@app.cell
def _(fetch):
    _ej_copy = HERE.parent / "ej-datasets-hifld-next" / "data" / "EJSCREEN_2024_BG_with_AS_CNMI_GU_VI.csv"
    _acs = "https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/data/5YRData"
    _download_started = time.perf_counter()
    files = {
        "hospitals": fetch(
            "https://storage.googleapis.com/hifld-next-datasets-prod/hifld/hospitals-3/hospitals-3/v1.1.0/geoparquet/hospitals-3.parquet",
            "hospitals-3.parquet",
        ),
        "burn_wiki": fetch(
            "https://en.wikipedia.org/w/index.php?title=List_of_burn_centers_in_the_United_States&oldid=1379563112&action=raw",
            "wikipedia-burn-centers-1379563112.txt",
        ),
        "centres": fetch(
            "https://www2.census.gov/geo/docs/reference/cenpop2020/blkgrp/CenPop2020_Mean_BG.txt",
            "CenPop2020_Mean_BG.txt",
        ),
        "ejscreen": _ej_copy
        if _ej_copy.exists()
        else fetch(
            "https://dataverse.harvard.edu/api/access/datafile/10775972",
            "EJSCREEN_2024_BG.csv",
            md5="cd1e76219826c0110bc10c27059ddf93",
        ),
        "race": fetch(f"{_acs}/acsdt5y2022-b03002.dat", "acsdt5y2022-b03002.dat"),
        "age": fetch(f"{_acs}/acsdt5y2022-b01001.dat", "acsdt5y2022-b01001.dat"),
        "ruca": fetch(
            "https://www.ers.usda.gov/media/5443/2020-rural-urban-commuting-area-codes-census-tracts.csv",
            "ruca2020-tracts.csv",
        ),
    }
    download_seconds = time.perf_counter() - _download_started
    pd.DataFrame(
        {"file": [p.name for p in files.values()], "MB": [round(p.stat().st_size / 1e6, 1) for p in files.values()]}
    )
    return download_seconds, files


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Trauma centers

    HIFLD Next's hospital layer carries each hospital's trauma designation as free text in `TRAUMA`, compiled from
    state and federal sources (its `SOURCEDATE` runs to 2024). We keep open hospitals, drop psychiatric,
    rehabilitation, long-term-care and critical-access records (several copy the level of the general hospital they
    sit beside, and a few are plainly wrong, such as a critical-access hospital marked Level I), and read each
    comma- or slash-separated part of `TRAUMA`:

    - `LEVEL I` or `LEVEL II` is an adult level, unless the part says `PEDIATRIC` or the hospital is a children's
      hospital, in which case it is a pediatric level. A bare `PEDIATRIC` (three Florida children's hospitals) counts
      as a pediatric trauma center.
    - Montana's and Wyoming's `RTC` (regional trauma center, the top tier of their state systems) counts as Level II.
    - Rehab designations are ignored. Levels III to V don't count.

    We use HIFLD rather than the American College of Surgeons' verified-center search, because the ACS listing has
    no download and its terms forbid reusing its data in other applications. HIFLD also covers state-designated
    centers that ACS doesn't verify.
    """)
    return


@app.cell
def _(files):
    def trauma_levels(text: str, hospital_type: str) -> tuple[bool, bool]:
        """Whether a TRAUMA value makes the hospital a Level I/II adult and a Level I/II pediatric center."""
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

    _raw = gpd.read_parquet(files["hospitals"])
    hospitals = _raw[
        (_raw["STATUS"] == "OPEN")
        & ~_raw["TYPE"].isin(["PSYCHIATRIC", "REHABILITATION", "LONG TERM CARE", "CRITICAL ACCESS"])
    ].copy()
    _levels = [trauma_levels(t or "", ty) for t, ty in zip(hospitals["TRAUMA"], hospitals["TYPE"], strict=True)]
    hospitals["adult"] = [a for a, _ in _levels]
    hospitals["peds"] = [p for _, p in _levels]
    _dropped = _raw[(_raw["STATUS"] == "OPEN") & ~_raw.index.isin(hospitals.index)]
    _dropped_levels = [trauma_levels(t or "", ty) for t, ty in zip(_dropped["TRAUMA"], _dropped["TYPE"], strict=True)]
    trauma_counts = {
        "open hospitals": int((_raw["STATUS"] == "OPEN").sum()),
        "kept after dropping psychiatric, rehab, long-term and critical-access": len(hospitals),
        "Level I/II adult": int(hospitals["adult"].sum()),
        "Level I/II pediatric": int(hospitals["peds"].sum()),
        "dropped records that claimed Level I/II": sum(a or p for a, p in _dropped_levels),
        "latest SOURCEDATE": str(hospitals["SOURCEDATE"].max())[:10],
    }
    trauma_counts
    return hospitals, trauma_counts


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Burn centers

    The American Burn Association's [directory](https://ameriburn.org/resources/find-a-burn-center/) is the
    authoritative list of verified burn centers, but its [terms of use](https://ameriburn.org/terms-of-use/) forbid
    collecting its content with automated tools and copying or distributing its data without permission, so this
    notebook doesn't download it. We use Wikipedia's list instead, pinned to one revision and openly licensed. It
    lists every burn center the ABA knew of in 2016, verified or not, with later edits, so it measures access to *a*
    burn center, not to an ABA-verified one.

    Wikipedia names burn units, not hospitals, so a fuzzy match to HIFLD's hospital names went wrong too often (it
    sent UF Health Shands in Gainesville to a hospital in Tamarac, 400 km away). `burn_crosswalk.csv` is a hand
    match of each Wikipedia entry to a HIFLD hospital `source_ID`, with a reason for each entry left out (closed,
    outpatient or rehabilitation only, or not a hospital). Any entry the crosswalk doesn't cover stops the run.
    """)
    return


@app.cell
def _(files, hospitals):
    _text = files["burn_wiki"].read_text()
    _text = re.sub(r"<ref[^>]*/>", "", _text)
    _text = re.sub(r"<ref[^>]*>.*?</ref>", "", _text, flags=re.S)
    _text = re.sub(r"\{\{[^}]*\}\}", "", _text)
    _rows, _state = [], None
    for _line in _text.splitlines():
        _heading = re.match(r"^==\s*([^=]+?)\s*==\s*$", _line)
        if _heading:
            _state = STATES.get(_heading.group(1))
        elif _line.startswith("*") and _state:
            _name = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", _line.lstrip("* ")).replace("''", "").strip()
            _rows.append((_state, _name))
    burn_wiki = pd.DataFrame(_rows, columns=["state", "wiki_name"])
    _crosswalk = pd.read_csv(HERE / "burn_crosswalk.csv", dtype=str)
    _merged = burn_wiki.merge(_crosswalk, on=["state", "wiki_name"], how="left", indicator=True)
    _missing = _merged[_merged["_merge"] == "left_only"]
    if len(_missing):
        raise ValueError(
            f"burn_crosswalk.csv doesn't cover {len(_missing)} Wikipedia entries: {_missing.wiki_name.tolist()}"
        )
    _kept = _merged[_merged["source_ID"].notna()]
    _unknown = set(_kept["source_ID"]) - set(hospitals["source_ID"].astype(str))
    if _unknown:
        raise ValueError(f"burn_crosswalk.csv names source_IDs that aren't open HIFLD hospitals: {sorted(_unknown)}")
    burn_ids = set(_kept["source_ID"])
    burn_counts = {
        "Wikipedia entries": len(burn_wiki),
        "matched to a hospital": len(_kept),
        "distinct hospitals": len(burn_ids),
        **{f"left out: {k}": int(v) for k, v in _merged["excluded"].value_counts().items()},
    }
    burn_counts
    return burn_counts, burn_ids


@app.cell
def _(burn_ids, hospitals):
    hospitals["burn"] = hospitals["source_ID"].astype(str).isin(burn_ids)
    facilities = pd.concat(
        [
            hospitals.loc[
                hospitals[_kind], ["source_ID", "NAME", "CITY", "STATE", "TRAUMA", "LATITUDE", "LONGITUDE"]
            ].assign(kind=_kind)
            for _kind in KINDS
        ],
        ignore_index=True,
    )
    facilities["source_ID"] = facilities["source_ID"].astype(str)
    facilities.to_csv(OUT / "facilities.csv", index=False)
    facilities.groupby("kind").size().rename("facilities")
    return (facilities,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Hand check of the facility list

    A seeded sample of each kind was checked by hand against public listings: state trauma-system designation
    lists and hospital announcements for trauma levels, and for burn centers whether the hospital still runs an
    inpatient burn unit and whether the ABA's directory lists it. The verdicts are in `hand_check.csv`; this cell
    draws the same sample and joins them, so a changed facility list shows up as unchecked rows.
    """)
    return


@app.cell
def _(facilities):
    hand_sample = pd.concat(
        [facilities[facilities["kind"] == _kind].sample(n=_n, random_state=SEED) for _kind, _n in HAND_SAMPLE.items()],
        ignore_index=True,
    )
    hand_sample[["kind", "source_ID", "NAME", "CITY", "STATE", "TRAUMA"]].to_csv(
        OUT / "hand_check_sample.csv", index=False
    )
    _checked_path = HERE / "hand_check.csv"
    _checked = (
        pd.read_csv(_checked_path, dtype=str)
        if _checked_path.exists()
        else pd.DataFrame(columns=["kind", "source_ID", "correct"])
    )
    hand_check = hand_sample.merge(_checked[["kind", "source_ID", "correct"]], on=["kind", "source_ID"], how="left")
    hand_accuracy = (
        hand_check.assign(correct=hand_check["correct"].fillna("unchecked"))
        .groupby("kind")["correct"]
        .value_counts()
        .unstack(fill_value=0)
    )
    hand_accuracy
    return hand_accuracy, hand_check


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## People

    One row per 2020 block group in the 50 states and DC. Its location is the Census population-weighted centre; its
    people come from the ACS 2018–2022 estimates EPA used in EJScreen 2024: total population, people in households
    below twice the poverty line (EPA's "low income"), people 65 and over, and the national percentile of EPA's
    demographic index (the average of the low-income and people-of-color shares), which we cut into deciles. Race and
    ethnicity and children under 18 come from the same ACS release (tables B03002 and B01001). Rurality is the 2020
    RUCA code of the block group's tract: metropolitan (codes 1–3), micropolitan (4–6), small town (7–9) and
    rural (10).
    """)
    return


@app.cell
def _(files):
    _centres = pd.read_csv(files["centres"], dtype=str, encoding="utf-8-sig")
    _centres["geoid"] = _centres["STATEFP"] + _centres["COUNTYFP"] + _centres["TRACTCE"] + _centres["BLKGRPCE"]
    _centres[["lat", "lon"]] = _centres[["LATITUDE", "LONGITUDE"]].astype(float)
    _ej = pd.read_csv(
        files["ejscreen"],
        dtype={"ID": str},
        usecols=["ID", "ST_ABBREV", "ACSTOTPOP", "ACSIPOVBAS", "LOWINCOME", "OVER64", "P_DEMOGIDX_2"],
    ).rename(columns={"ID": "geoid", "ST_ABBREV": "state", "ACSTOTPOP": "pop", "ACSIPOVBAS": "poverty_base"})
    _race_columns = {
        "B03002_E003": "white",
        "B03002_E004": "black",
        "B03002_E005": "aian",
        "B03002_E006": "asian",
        "B03002_E007": "nhpi",
        "B03002_E012": "hispanic",
    }
    _race = pd.read_csv(files["race"], sep="|", usecols=["GEO_ID", "B03002_E001", *_race_columns]).rename(
        columns=_race_columns
    )
    _race["other_or_multiracial"] = _race["B03002_E001"] - _race[list(_race_columns.values())].sum(axis=1)
    _age_columns = [f"B01001_E{i:03d}" for i in (3, 4, 5, 6, 27, 28, 29, 30)]
    _age = pd.read_csv(files["age"], sep="|", usecols=["GEO_ID", *_age_columns])
    _age["children"] = _age[_age_columns].sum(axis=1)
    _acs = _race.merge(_age[["GEO_ID", "children"]], on="GEO_ID")
    _acs = _acs[_acs["GEO_ID"].str.startswith("1500000US")].assign(geoid=lambda d: d["GEO_ID"].str[9:])
    _ruca = pd.read_csv(files["ruca"], dtype={"TractFIPS20": str}, usecols=["TractFIPS20", "PrimaryRUCA"])
    _ruca = _ruca.drop_duplicates("TractFIPS20")
    _ruca["rurality"] = pd.cut(
        _ruca["PrimaryRUCA"], [0, 3, 6, 9, 10], labels=["Metropolitan", "Micropolitan", "Small town", "Rural"]
    )

    bg = (
        _ej[_ej["state"].isin(STATES.values())]
        .merge(_centres[["geoid", "lat", "lon"]], on="geoid", how="left")
        .merge(_acs.drop(columns=["GEO_ID", "B03002_E001"]), on="geoid", how="left")
        .assign(tract=lambda d: d["geoid"].str[:11])
        .merge(_ruca.rename(columns={"TractFIPS20": "tract"}), on="tract", how="left")
    )
    bg["low_income"] = bg["LOWINCOME"]
    bg["not_low_income"] = bg["poverty_base"] - bg["LOWINCOME"]
    bg["age_65_plus"] = bg["OVER64"]
    bg["under_65"] = bg["pop"] - bg["OVER64"]
    bg["ej_decile"] = np.minimum(bg["P_DEMOGIDX_2"] // 10 + 1, 10).astype("Int64")
    people_checks = {
        "block groups": len(bg),
        "people": int(bg["pop"].sum()),
        "block groups without a population centre": int(bg["lat"].isna().sum()),
        "people in them": int(bg.loc[bg["lat"].isna(), "pop"].sum()),
        "block groups without ACS race counts": int(bg["white"].isna().sum()),
        "block groups without a RUCA code": int(bg["rurality"].isna().sum()),
    }
    bg = bg[bg["lat"].notna()].reset_index(drop=True)
    people_checks
    return bg, people_checks


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Straight-line distance, nationally

    For every block group and each kind of facility, the great-circle distance to the nearest one, found with a k-d
    tree on points on the unit sphere. Facilities in other states count, since people cross state lines for care.
    """)
    return


@app.cell
def _():
    def unit_vectors(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        lat_r, lon_r = np.radians(lat), np.radians(lon)
        return np.column_stack([np.cos(lat_r) * np.cos(lon_r), np.cos(lat_r) * np.sin(lon_r), np.sin(lat_r)])

    def nearest(points: pd.DataFrame, targets: pd.DataFrame, k: int = 1) -> tuple[np.ndarray, np.ndarray]:
        """Great-circle km to, and row positions of, the k nearest targets for each point."""
        tree = KDTree(unit_vectors(targets["LATITUDE"].to_numpy(), targets["LONGITUDE"].to_numpy()))
        chord, index = tree.query(unit_vectors(points["lat"].to_numpy(), points["lon"].to_numpy()), k=k)
        return 2 * EARTH_KM * np.arcsin(np.clip(chord / 2, 0, 1)), index

    return (nearest,)


@app.cell
def _(bg, facilities, nearest):
    for _kind in KINDS:
        bg[f"{_kind}_km"] = nearest(bg, facilities[facilities["kind"] == _kind])[0]
    bg[[f"{k}_km" for k in KINDS]].describe(percentiles=[0.5, 0.9, 0.99]).round(1)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Road drive time in Maine and New Jersey

    Driving the whole country is too heavy for one run, so we route two contrasting states. The run downloads
    OpenStreetMap's US Northeast extract (about 2 GB), cuts a box around each state with
    [osmium](https://osmcode.org/osmium-tool/), wide enough to take in hospitals across the border (Boston for
    Maine, New York City and Philadelphia for New Jersey), and builds Valhalla routing tiles. Valhalla's
    many-to-many matrix then gives the car drive time from each block group's centre to the five nearest facilities
    of each kind by straight line, and we keep the shortest. Valhalla uses its default speeds by road class and posted
    limits, with no traffic.
    """)
    return


@app.cell
def _(fetch):
    routed_states = {"ME": (-72.0, 42.08, -66.9, 47.5), "NJ": (-76.3, 38.15, -73.15, 42.1)}
    if not shutil.which("osmium"):
        raise RuntimeError("osmium not found: install osmium-tool (apt install osmium-tool, brew install osmium-tool)")
    _routing_started = time.perf_counter()
    _northeast = fetch(
        "https://download.openstreetmap.fr/extracts/north-america/us-northeast-latest.osm.pbf",
        "us-northeast-latest.osm.pbf",
    )
    _info = subprocess.run(
        ["osmium", "fileinfo", "-g", "header.option.osmosis_replication_timestamp", str(_northeast)],
        capture_output=True,
        text=True,
        check=True,
    )
    osm_timestamp = _info.stdout.strip()
    tiles = {}
    for _state, _box in routed_states.items():
        _tile_dir = DATA / f"valhalla-{_state}"
        if not (_tile_dir / "done").exists():
            _pbf = DATA / f"osm-{_state}.osm.pbf"
            subprocess.run(
                ["osmium", "extract", "--overwrite", "-b", ",".join(map(str, _box)), str(_northeast), "-o", str(_pbf)],
                check=True,
            )
            shutil.rmtree(_tile_dir, ignore_errors=True)
            _tile_dir.mkdir()
            _config = valhalla.get_config(tile_extract="", tile_dir=_tile_dir)
            (_tile_dir / "config.json").write_text(json.dumps(_config))
            subprocess.run(
                ["valhalla_build_tiles", "-c", str(_tile_dir / "config.json"), str(_pbf)],
                check=True,
                capture_output=True,
            )
            (_tile_dir / "done").touch()
        tiles[_state] = _tile_dir
    tile_seconds = time.perf_counter() - _routing_started
    {"OSM data as of": osm_timestamp, "tiles": {k: str(v) for k, v in tiles.items()}}
    return osm_timestamp, routed_states, tile_seconds, tiles


@app.cell
def _(bg, facilities, nearest, routed_states, tiles):
    _matrix_started = time.perf_counter()
    _routed = []
    for _state, _box in routed_states.items():
        _config = valhalla.get_config(tile_extract="", tile_dir=tiles[_state])
        _config["service_limits"]["auto"]["max_matrix_location_pairs"] = 50_000
        _actor = valhalla.Actor(_config)
        _sources = bg[bg["state"] == _state].reset_index()
        _in_box = facilities[
            facilities["LONGITUDE"].between(_box[0], _box[2]) & facilities["LATITUDE"].between(_box[1], _box[3])
        ]
        _result = _sources[["index"]].copy()
        for _kind in KINDS:
            _targets = _in_box[_in_box["kind"] == _kind].reset_index(drop=True)
            _candidates = nearest(_sources, _targets, k=min(5, len(_targets)))[1].reshape(len(_sources), -1)
            _minutes = np.full(len(_sources), np.nan)
            for _start in range(0, len(_sources), 250):
                _batch = _sources.iloc[_start : _start + 250]
                _used = np.unique(_candidates[_start : _start + 250])
                _response = _actor.matrix(
                    {
                        "sources": [
                            {"lat": la, "lon": lo} for la, lo in zip(_batch["lat"], _batch["lon"], strict=True)
                        ],
                        "targets": [
                            {"lat": _targets.at[i, "LATITUDE"], "lon": _targets.at[i, "LONGITUDE"]} for i in _used
                        ],
                        "costing": "auto",
                    }
                )
                _times = np.array(
                    [
                        [np.nan if c.get("time") is None else c["time"] for c in row]
                        for row in _response["sources_to_targets"]
                    ]
                )
                _minutes[_start : _start + len(_batch)] = (
                    np.nanmin(np.where(np.isnan(_times), np.inf, _times), axis=1) / 60
                )
            _result[f"{_kind}_min_road"] = np.where(np.isinf(_minutes), np.nan, _minutes)
        _routed.append(_result)
    _routed = pd.concat(_routed).set_index("index")
    for _column in _routed:
        bg[_column] = _routed[_column]
    matrix_seconds = time.perf_counter() - _matrix_started
    routed_failures = {k: int(bg.loc[bg["state"].isin(routed_states), f"{k}_min_road"].isna().sum()) for k in KINDS}
    {"matrix seconds": round(matrix_seconds), "block groups with no route found": routed_failures}
    return matrix_seconds, routed_failures


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## From kilometres to minutes

    In the routed states, drive time is close to a straight line in straight-line distance, but the line differs by
    rurality: towns and cities have slower roads, and rural trips are longer but faster. We fit
    `minutes = a + b × km` by least squares for each rurality class, pooling Maine, New Jersey and all three
    kinds of facility, and use it to estimate drive time for every block group in the country. Where a class has
    fewer than 100 routed block groups we fall back to one pooled line.
    """)
    return


@app.cell
def _(bg, routed_states):
    _long = pd.concat(
        [
            bg.loc[bg["state"].isin(routed_states), ["state", "rurality", "pop"]].assign(
                kind=_kind, km=bg[f"{_kind}_km"], road=bg[f"{_kind}_min_road"]
            )
            for _kind in KINDS
        ]
    ).dropna(subset=["road", "rurality"])
    _pooled = np.polyfit(_long["km"], _long["road"], 1)
    fits = {}
    for _class, _group in _long.groupby("rurality", observed=True):
        fits[str(_class)] = np.polyfit(_group["km"], _group["road"], 1) if len(_group) >= 100 else _pooled
    fit_table = pd.DataFrame(
        {
            "routed block-group trips": _long.groupby("rurality", observed=True).size(),
            "minutes at 0 km (a)": {k: round(v[1], 1) for k, v in fits.items()},
            "minutes per km (b)": {k: round(v[0], 3) for k, v in fits.items()},
        }
    )
    for _kind in KINDS:
        _slope = bg["rurality"].astype(str).map({k: v[0] for k, v in fits.items()}).fillna(_pooled[0])
        _intercept = bg["rurality"].astype(str).map({k: v[1] for k, v in fits.items()}).fillna(_pooled[1])
        bg[f"{_kind}_min"] = _intercept + _slope * bg[f"{_kind}_km"]
    calibration = _long.assign(
        estimate=lambda d: d.apply(
            lambda r: fits[str(r["rurality"])][1] + fits[str(r["rurality"])][0] * r["km"], axis=1
        )
    )
    fit_table
    return calibration, fit_table


@app.cell
def _(calibration):
    def agreement(group: pd.DataFrame) -> pd.Series:
        error = group["estimate"] - group["road"]
        return pd.Series(
            {
                "block groups": len(group),
                "median road minutes": group["road"].median(),
                "median abs. error (min)": error.abs().median(),
                "90th pct abs. error (min)": error.abs().quantile(0.9),
                "same side of 30 min": ((group["estimate"] > 30) == (group["road"] > 30)).mean(),
                "same side of 60 min": ((group["estimate"] > 60) == (group["road"] > 60)).mean(),
                "people beyond 60 min, road": (group["pop"] * (group["road"] > 60)).sum() / group["pop"].sum(),
                "people beyond 60 min, estimate": (group["pop"] * (group["estimate"] > 60)).sum() / group["pop"].sum(),
            }
        )

    method_agreement = calibration.groupby(["state", "kind"]).apply(agreement).round(3)
    method_agreement
    return (method_agreement,)


@app.cell
def _(calibration):
    _fig, _axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    for _ax, (_state, _group) in zip(_axes, calibration.groupby("state"), strict=True):
        for _class, _sub in _group.groupby("rurality", observed=True):
            _ax.scatter(_sub["km"], _sub["road"], s=2, alpha=0.35, label=str(_class))
        _ax.set_title({"ME": "Maine", "NJ": "New Jersey"}[_state])
        _ax.set_xlabel("straight-line km to nearest facility")
        _ax.axhline(60, color="grey", lw=0.8, ls="--")
    _axes[0].set_ylabel("road minutes to nearest facility")
    _axes[0].legend(markerscale=5, fontsize=8)
    _fig.suptitle("Straight-line distance against Valhalla drive time, all three kinds of facility")
    _fig.tight_layout()
    _fig.savefig(OUT / "calibration.png", dpi=130)
    _fig
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Who is beyond 30 and 60 minutes

    Shares are of people, weighting each block group by its count of the group in question. For pediatric trauma
    centers the weight is children under 18; where a split needs children of a given race or income, we assume the
    block group's children split the way its whole population does. The national figures use the estimated drive
    time; the routed states also report road time directly.
    """)
    return


@app.cell
def _(bg):
    def beyond(minutes: pd.Series, weights: pd.Series) -> dict:
        valid = minutes.notna() & weights.notna()
        people = weights[valid].sum()
        return {
            "people": people,
            "beyond 30 min": weights[valid & (minutes > 30)].sum() / people,
            "beyond 60 min": weights[valid & (minutes > 60)].sum() / people,
            "people beyond 60 min": weights[valid & (minutes > 60)].sum(),
        }

    _groups = [("All", "Everyone", "pop", None)]
    _groups += [
        ("Rurality", c, "pop", bg["rurality"] == c) for c in ["Metropolitan", "Micropolitan", "Small town", "Rural"]
    ]
    _groups += [("Income", "Low income", "low_income", None), ("Income", "Not low income", "not_low_income", None)]
    _groups += [
        ("Race and ethnicity", label, column, None)
        for label, column in [
            ("Hispanic", "hispanic"),
            ("White", "white"),
            ("Black", "black"),
            ("American Indian and Alaska Native", "aian"),
            ("Asian", "asian"),
            ("Native Hawaiian and Pacific Islander", "nhpi"),
            ("Other or multiracial", "other_or_multiracial"),
        ]
    ]
    _groups += [("Age", "65 and over", "age_65_plus", None), ("Age", "Under 65", "under_65", None)]
    _groups += [
        ("EJ demographic index decile", f"Decile {d}", "pop", (bg["ej_decile"] == d).fillna(False))
        for d in range(1, 11)
    ]

    def split_table(frame: pd.DataFrame, suffix: str) -> pd.DataFrame:
        rows = []
        for kind, label in KINDS.items():
            child_share = (frame["children"] / frame["pop"]).where(frame["pop"] > 0)
            for dimension, group, column, mask in _groups:
                if kind == "peds" and dimension == "Age":
                    continue
                weights = frame[column] * (child_share if kind == "peds" else 1)
                if mask is not None:
                    weights = weights.where(mask.reindex(frame.index, fill_value=False), 0)
                rows.append(
                    {
                        "facility": label,
                        "dimension": dimension,
                        "group": group,
                        **beyond(frame[f"{kind}{suffix}"], weights),
                    }
                )
        return pd.DataFrame(rows)

    national = split_table(bg, "_min")
    national.to_csv(OUT / "national_by_group.csv", index=False)
    national.pivot_table(index=["dimension", "group"], columns="facility", values="beyond 60 min", sort=False).round(3)
    return beyond, national, split_table


@app.cell
def _(national):
    _rows = []
    for (_facility, _dimension), _g in national[national["dimension"] != "All"].groupby(
        ["facility", "dimension"], sort=False
    ):
        _top, _bottom = _g.loc[_g["beyond 60 min"].idxmax()], _g.loc[_g["beyond 60 min"].idxmin()]
        _rows.append(
            {
                "facility": _facility,
                "dimension": _dimension,
                "furthest group": _top["group"],
                "its share beyond 60 min": round(_top["beyond 60 min"], 3),
                "closest group": _bottom["group"],
                "its share beyond 60 min ": round(_bottom["beyond 60 min"], 3),
                "gap (points)": round(100 * (_top["beyond 60 min"] - _bottom["beyond 60 min"]), 1),
            }
        )
    gaps = pd.DataFrame(_rows)
    gaps.to_csv(OUT / "gaps.csv", index=False)
    gaps
    return (gaps,)


@app.cell
def _(bg, routed_states, split_table):
    routed = pd.concat(
        [split_table(bg[bg["state"] == s], "_min_road").assign(state=s, method="road") for s in routed_states]
        + [split_table(bg[bg["state"] == s], "_min").assign(state=s, method="estimate") for s in routed_states]
    )
    routed.to_csv(OUT / "routed_states_by_group.csv", index=False)
    routed[routed["dimension"].isin(["All", "Rurality"])].pivot_table(
        index=["state", "facility", "group"], columns="method", values="beyond 60 min", sort=False
    ).round(3)
    return (routed,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Against the published figures

    The published studies time a whole ambulance run, so they add dispatch and on-scene time (about 15 minutes in
    Branas et al., 17 in Choi et al.) to the drive, and most add helicopters. We put our drive-only share within
    60 minutes next to their ground-only figures, and also our share within 45 minutes of driving, which is closer to
    their 60-minute total.
    """)
    return


@app.cell
def _(bg):
    published = pd.DataFrame(
        [
            (
                "adult",
                "Branas et al. 2005, JAMA (2004 data)",
                "Level I/II, ground or air, 60 min incl. dispatch and scene",
                0.841,
            ),
            (
                "adult",
                "Branas et al. 2005, ground only (84.1% minus 27.7% helicopter only)",
                "Level I/II, ground, 60 min",
                0.564,
            ),
            (
                "adult",
                "Carr et al. 2017, Injury (2010 data)",
                "Level I/II, ground or air, share of block groups",
                0.883,
            ),
            ("adult", "Choi et al. 2022, JAMA (2019 data)", "ACS-verified Level I/II, ground or air, 60 min", 0.892),
            ("peds", "Nance et al. 2009 (children under 15)", "Verified pediatric centers, ground only, 60 min", 0.43),
            (
                "peds",
                "Melhado et al. 2025, JAMA Pediatrics (2020 data)",
                "Level I/II pediatric, ground only, 60 min",
                0.51,
            ),
            ("burn", "Klein et al. 2009, JAMA (2008 list)", "ABA-verified burn centers, ground only, 60 min", 0.251),
            (
                "burn",
                "Hur et al. 2024, JAMA Surgery (2019 data)",
                "ABA-verified burn centers, ground or air, 60 min",
                0.688,
            ),
        ],
        columns=["kind", "study", "measure", "share within"],
    )
    _ours = []
    for _kind, _label in KINDS.items():
        _weights = bg["children"] if _kind == "peds" else bg["pop"]
        _known = _weights[bg[f"{_kind}_min"].notna()].sum()
        for _limit in (60, 45):
            _ours.append(
                {
                    "kind": _kind,
                    "study": "This spike (estimated drive time)",
                    "measure": f"{_label}, drive only, {_limit} min",
                    "share within": _weights[bg[f"{_kind}_min"] <= _limit].sum() / _known,
                }
            )
    comparison = pd.concat([published, pd.DataFrame(_ours)]).sort_values("kind", kind="stable").round(3)
    comparison.to_csv(OUT / "comparison_with_published.csv", index=False)
    comparison
    return (comparison,)


@app.cell
def _(bg):
    _lower48 = bg[~bg["state"].isin(["AK", "HI"])]
    _bins = [0, 30, 60, 120, np.inf]
    _colors = ["#1a9850", "#fee08b", "#f46d43", "#a50026"]
    _fig, _axes = plt.subplots(3, 1, figsize=(10, 18))
    for _ax, (_kind, _label) in zip(_axes, KINDS.items(), strict=True):
        _band = pd.cut(_lower48[f"{_kind}_min"], _bins, labels=False)
        for _b, _color in enumerate(_colors):
            _sub = _lower48[_band == _b]
            _ax.scatter(
                _sub["lon"], _sub["lat"], s=0.3, color=_color, label=["under 30", "30–60", "60–120", "over 120"][_b]
            )
        _ax.set_title(f"Estimated drive time to the nearest {_label.lower()} (minutes)")
        _ax.set_aspect(1.25)
        _ax.axis("off")
        _ax.legend(markerscale=20, loc="lower left", fontsize=8)
    _fig.tight_layout()
    _fig.savefig(OUT / "map_drive_time.png", dpi=110)
    _fig
    return


@app.cell
def _(bg):
    _columns = [
        "geoid", "state", "lat", "lon", "pop", "children", "low_income", "age_65_plus", "hispanic", "white", "black",
        "aian", "asian", "nhpi", "other_or_multiracial", "rurality", "PrimaryRUCA", "P_DEMOGIDX_2", "ej_decile",
        *[f"{k}_{m}" for k in KINDS for m in ("km", "min", "min_road")],
    ]  # fmt: skip
    _out = gpd.GeoDataFrame(bg[_columns], geometry=gpd.points_from_xy(bg["lon"], bg["lat"]), crs="EPSG:4326")
    _out.to_parquet(OUT / "block_groups.parquet")
    _out.drop(columns="geometry").to_csv(OUT / "block_groups.csv.gz", index=False)
    _out[_out["state"].isin(["ME", "NJ"])].drop(columns="geometry").to_csv(OUT / "block_groups_me_nj.csv", index=False)
    {"block groups written": len(_out), "GeoParquet MB": round((OUT / "block_groups.parquet").stat().st_size / 1e6, 1)}
    return


@app.cell
def _(
    burn_counts,
    comparison,
    download_seconds,
    fit_table,
    gaps,
    hand_accuracy,
    matrix_seconds,
    method_agreement,
    national,
    osm_timestamp,
    people_checks,
    routed_failures,
    tile_seconds,
    trauma_counts,
):
    _all = national[national["dimension"] == "All"].set_index("facility")
    summary = {
        "national": {
            f: {
                "people": int(r["people"]),
                "beyond_30_min": round(r["beyond 30 min"], 4),
                "beyond_60_min": round(r["beyond 60 min"], 4),
                "people_beyond_60_min": int(r["people beyond 60 min"]),
            }
            for f, r in _all.iterrows()
        },
        "gaps_at_60_min": gaps.to_dict(orient="records"),
        "comparison": comparison.to_dict(orient="records"),
        "method_agreement": method_agreement.reset_index().to_dict(orient="records"),
        "fits": fit_table.reset_index().to_dict(orient="records"),
        "facilities": {"trauma": trauma_counts, "burn": burn_counts},
        "hand_check": hand_accuracy.to_dict(orient="index"),
        "people_checks": people_checks,
        "routing_failures": routed_failures,
        "osm_timestamp": osm_timestamp,
        "seconds": {
            "downloads": round(download_seconds),
            "osm_and_tiles": round(tile_seconds),
            "matrix": round(matrix_seconds),
            "total": round(time.perf_counter() - RUN_STARTED),
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    summary["national"]
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What didn't work, and what this can't show

    - **No national road routing.** Routing all 240,000 block groups needs the whole US road graph; we routed two
      states and estimated the rest from straight-line distance. Where roads are sparse or water is in the way
      (Alaska, island and coastal communities, mountain valleys) the estimate is too short.
    - **The ABA directory can't be used without permission**, so burn centers are Wikipedia's list of all burn
      centers, verified or not, matched to hospitals by hand. Access to an ABA-verified center would be lower.
    - **HIFLD's trauma levels are compiled from state sources and partly out of date** (see the hand check). The
      fuzzy text in `TRAUMA` also copies levels onto co-located specialty units, which we drop by hospital type.
    - **Ground ambulance only.** No helicopters, no traffic, no dispatch or on-scene time, and the trip starts at the
      block group's population centre rather than each home.
    - **Distance isn't the only barrier.** Capacity, insurance, transfers between hospitals and closures since 2024
      aren't in the data.
    """)
    return


if __name__ == "__main__":
    app.run()
