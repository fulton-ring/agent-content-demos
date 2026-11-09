import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import logging
    import os
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import requests

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("cff")
    here = Path(mo.notebook_dir() or ".")
    cache = Path(
        os.environ.get("CFF_CACHE", Path.home() / ".cache" / "critical-facilities-flood-zones")
    )
    results = Path(os.environ.get("CFF_RESULTS", here / "results"))
    for _d in (cache / "nfhl", results):
        _d.mkdir(parents=True, exist_ok=True)
    started = time.time()

    def fetch(url: str, name: str) -> Path:
        """Download a file once into the cache, with a bounded number of retries."""
        path = cache / name
        if path.exists():
            return path
        for attempt in range(5):
            try:
                response = requests.get(url, timeout=600)
                response.raise_for_status()
                path.write_bytes(response.content)
                return path
            except requests.RequestException as error:
                log.warning("%s attempt %d: %s", url, attempt + 1, error)
                time.sleep(2**attempt)
        raise RuntimeError(f"{url} failed 5 times")

    _local = threading.local()

    def get_json(url: str, params: dict, attempts: int = 8) -> dict:
        """GET a JSON response with a bounded number of retries; ArcGIS errors count as failures.

        Each thread keeps its own session, so connections are reused instead of opening a new
        TLS connection per point (FEMA's service resets many of those).
        """
        if not hasattr(_local, "session"):
            _local.session = requests.Session()
        for attempt in range(attempts):
            try:
                response = _local.session.get(url, params=params, timeout=120)
                response.raise_for_status()
                payload = response.json()
                if "error" not in payload:
                    return payload
                log.warning("%s attempt %d: %s", url, attempt + 1, payload["error"])
            except (requests.RequestException, ValueError) as error:
                log.warning("%s attempt %d: %s", url, attempt + 1, error)
            time.sleep(min(2**attempt, 30))
        raise RuntimeError(f"{url} failed {attempts} times with {params}")

    return (
        ThreadPoolExecutor,
        cache,
        fetch,
        get_json,
        gpd,
        here,
        json,
        log,
        mo,
        pd,
        plt,
        results,
        started,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Which hospitals and substations sit in FEMA flood zones?

    HIFLD Open went offline in 2025. An analyst who wants to know which hospitals, substations and
    other critical facilities sit in a FEMA flood zone, or how they rank on FEMA's National Risk
    Index (NRI), now finds one utility's or one county's list, a 2019 mirror of HIFLD, or a paid
    tool. This notebook does it nationally from public data, step by step:

    1. **Facilities.** HIFLD Next's hospitals layer, and for substations the dataset our
       `us-substations-verified/` spike built and checked, because HIFLD Next has no substations
       layer.
    2. **Flood zones.** Each facility point against FEMA's National Flood Hazard Layer (NFHL):
       the 1%-a-year Special Flood Hazard Area (zone A and V families), the 0.2% zone, and
       whether there is any effective digital NFHL at that spot at all.
    3. **Risk ranking.** Each point joined to its NRI census tract and ranked on the tract's
       riverine (inland) and coastal flood risk scores.
    4. **Checks.** The vintage of every input, and a hand check of where a sample of points
       really sits on aerial imagery.

    Issue [#193](https://github.com/fulton-ring/agent-content-demos/issues/193). Run it with
    `./run.sh`; every number below comes from this run.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Facilities

    **Hospitals.** HIFLD Next `hospitals-3` v1.1.1 (a reprocessing of v1.1.0 with the same
    records). We keep the hospitals marked `OPEN`. The layer says when each record's source was
    dated (`SOURCEDATE`) and when its location was last checked (`VAL_DATE`, `VAL_METHOD`).

    **Substations.** DHS withdrew HIFLD's Electric Substations layer from public access in 2022,
    so HIFLD Next never had it (our `hifld-grid-gaps/` spike checked; HIFLD Next's 331 dataset
    folders still have no substation layer today). Instead we use `us-substations-verified/`:
    substations derived from the ends of HIFLD Next's transmission lines, merged with every
    OpenStreetMap substation (via Overture Maps) that the derivation missed. It is read from this
    repo at a pinned commit, so the input can't drift. We group substations by their highest known
    voltage, because a 345 kV switchyard and a neighbourhood distribution substation are different
    questions.
    """)
    return


@app.cell
def _(fetch, gpd, pd):
    _h = gpd.read_parquet(
        fetch(
            "https://storage.googleapis.com/hifld-next-datasets-prod/hifld/hospitals-3/"
            "hospitals-3/v1.1.1/geoparquet/hospitals-3.parquet",
            "hospitals-3-v1.1.1.parquet",
        )
    ).to_crs("EPSG:4326")
    _h = _h[_h.STATUS == "OPEN"]
    hospitals = gpd.GeoDataFrame(
        {
            "facility_id": "hospital-" + _h.source_ID.astype(str),
            "facility_type": "hospital",
            "subtype": _h.TYPE.astype(str),
            "name": _h.NAME.astype(str),
            "city": _h.CITY.astype(str),
            "state": _h.STATE.astype(str),
            "source_date": pd.to_datetime(_h.SOURCEDATE, errors="coerce"),
            "location_checked": pd.to_datetime(_h.VAL_DATE, errors="coerce"),
            "location_method": _h.VAL_METHOD.astype(str),
        },
        geometry=_h.geometry.values,
        crs="EPSG:4326",
    )

    _s = pd.read_parquet(
        fetch(
            "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/"
            "b48028fa402933bf55423ee552105f5d71d405ac/us-substations-verified/dataset/"
            "us_substations.parquet",
            "us_substations-b48028f.parquet",
        )
    )
    _s = gpd.GeoDataFrame(_s, geometry=gpd.GeoSeries.from_wkb(_s.geometry), crs="EPSG:4326")
    _kv = pd.to_numeric(_s.max_kv, errors="coerce")
    substations = gpd.GeoDataFrame(
        {
            "facility_id": _s["id"].astype(str),
            "facility_type": "substation",
            "subtype": pd.cut(
                _kv,
                [0, 100, 230, 10_000],
                right=False,
                labels=["under 100 kV", "100-229 kV", "230 kV+"],
            )
            .astype(str)
            .where(_kv.notna(), "voltage unknown"),
            "name": _s.name.fillna("").astype(str),
            "city": "",
            "state": _s.state.astype(str),
            "source": _s.source.astype(str),
        },
        geometry=_s.geometry.values,
        crs="EPSG:4326",
    )
    facilities = gpd.GeoDataFrame(pd.concat([hospitals, substations], ignore_index=True))
    assert facilities.facility_id.is_unique, "facility IDs must be unique"
    assert facilities.geometry.notna().all() and (facilities.geom_type == "Point").all()
    pd.crosstab(facilities.subtype, facilities.facility_type, margins=True)
    return facilities, hospitals, substations


@app.cell
def _(hospitals, pd, substations):
    pd.DataFrame(
        {
            "hospitals: source dated 2023 or later": [
                f"{(hospitals.source_date.dt.year >= 2023).mean():.0%}"
            ],
            "hospitals: location last checked, median year": [
                int(hospitals.location_checked.dt.year.median())
            ],
            "hospitals: location checked on imagery": [
                f"{hospitals.location_method.str.startswith('IMAGERY').mean():.0%}"
            ],
            "substations: derived and confirmed by OSM": [
                int((substations.source == "both").sum())
            ],
            "substations: derived only": [int((substations.source == "derived").sum())],
            "substations: OSM only": [int((substations.source == "osm").sum())],
        }
    ).T.rename(columns={0: "value"})
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Flood zones from the NFHL

    The full NFHL is tens of gigabytes as state downloads, so instead of downloading it we ask
    FEMA's public NFHL map service about each point. One `identify` call returns three things at
    that spot:

    - **NFHL Availability** (layer 0): is there an effective digital flood study here at all? A
      point outside it is in a community with paper maps only, or no map.
    - **FIRM Panels** (layer 3): the effective date of the map panel, our vintage for the
      flood zone.
    - **Flood Hazard Zones** (layer 28): the zone (`FLD_ZONE`), its subtype and whether it is
      in the SFHA.

    Each point gets one class; where zone polygons meet, the highest hazard wins: **SFHA, V**
    (coastal high hazard, V and VE), **SFHA, A** (A, AE, AH, AO, AR, A99), **0.2% zone** (zone X
    "0.2 PCT ANNUAL CHANCE", the 500-year floodplain), **other shaded X** (behind a levee, or 1%
    with less than a foot of depth), **minimal** (unshaded X), **D** (possible but undetermined
    hazard), **open water**, **study area, no zone** (inside a digital study but no zone polygon
    at the point) and **no NFHL** (outside every digital study). Answers are cached per point,
    and a point the service fails to answer 8 times is kept as "query failed" and counted.

    We first used one `query` call per layer, as `facility-climate-ranking/` did. `identify`
    answers all three layers at once, which cut the calls by two thirds.
    """)
    return


@app.cell
def _(ThreadPoolExecutor, cache, facilities, get_json, json, log, pd, time):
    _url = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/identify"
    _keep = {
        0: ["STUDY_ID"],
        3: ["DFIRM_ID", "FIRM_PAN", "EFF_DATE"],
        28: ["DFIRM_ID", "FLD_ZONE", "ZONE_SUBTY", "SFHA_TF"],
    }

    def identify(job: tuple[str, float, float]) -> dict:
        """Ask the NFHL service what is at one point, cached on disk."""
        facility_id, lon, lat = job
        path = cache / "nfhl" / f"{lon:.6f}_{lat:.6f}.json"
        if path.exists():
            return {"facility_id": facility_id, **json.loads(path.read_text())}
        try:
            payload = get_json(
                _url,
                {
                    "geometry": f"{lon:.6f},{lat:.6f}",
                    "geometryType": "esriGeometryPoint",
                    "sr": "4326",
                    "layers": "all:0,3,28",
                    "tolerance": "0",
                    "mapExtent": f"{lon - 0.001},{lat - 0.001},{lon + 0.001},{lat + 0.001}",
                    "imageDisplay": "400,400,96",
                    "returnGeometry": "false",
                    "f": "json",
                },
            )
        except RuntimeError:
            return {"facility_id": facility_id, "failed": True}
        found: dict[str, list] = {"0": [], "3": [], "28": []}
        for result in payload["results"]:
            layer = result["layerId"]
            values = [result["attributes"].get(k) for k in _keep[layer]]
            # identify writes empty fields as the string "Null"; query returns None.
            found[str(layer)].append([None if v == "Null" else v for v in values])
        path.write_text(json.dumps(found))
        return {"facility_id": facility_id, **found}

    _jobs = list(
        zip(facilities.facility_id, facilities.geometry.x, facilities.geometry.y, strict=True)
    )
    _t0 = time.time()
    with ThreadPoolExecutor(max_workers=12) as _pool:
        nfhl_raw = list(_pool.map(identify, _jobs))
    nfhl_seconds = time.time() - _t0
    log.info("%d points identified in NFHL in %.0f s", len(nfhl_raw), nfhl_seconds)
    pd.DataFrame(
        {
            "points": [len(nfhl_raw)],
            "query failed": [sum(1 for r in nfhl_raw if r.get("failed"))],
            "seconds": [round(nfhl_seconds)],
        }
    )
    return (nfhl_raw,)


@app.cell
def _(facilities, nfhl_raw, pd):
    _order = [
        "SFHA, V",
        "SFHA, A",
        "0.2% zone",
        "other shaded X",
        "minimal",
        "D",
        "open water",
        "study area, no zone",
        "no NFHL",
        "query failed",
    ]

    def zone_class(zone: str, subtype: str, sfha: str) -> str:
        if sfha == "T":
            return "SFHA, V" if zone.startswith("V") else "SFHA, A"
        if zone == "X" and subtype.startswith("0.2 PCT"):
            return "0.2% zone"
        if zone == "X" and subtype != "AREA OF MINIMAL FLOOD HAZARD":
            return "other shaded X"
        if zone in ("X", "C"):
            return "minimal"
        if zone == "B":
            return "other shaded X"
        if zone == "D":
            return "D"
        if zone == "OPEN WATER":
            return "open water"
        return "study area, no zone"

    _rows = []
    for _r in nfhl_raw:
        if _r.get("failed"):
            _rows.append({"facility_id": _r["facility_id"], "flood_class": "query failed"})
            continue
        _zones = [
            (zone_class((z or "").strip(), (s or "").strip(), (t or "").strip()), d, z)
            for d, z, s, t in _r["28"]
        ]
        if _zones:
            _cls, _dfirm, _zone = min(_zones, key=lambda x: _order.index(x[0]))
        else:
            _cls = "study area, no zone" if _r["0"] else "no NFHL"
            _dfirm, _zone = (_r["0"][0][0] if _r["0"] else None), None
        _panels = [p for p in _r["3"] if p[0] == _dfirm] or _r["3"]
        _rows.append(
            {
                "facility_id": _r["facility_id"],
                "flood_class": _cls,
                "fld_zone": _zone,
                "dfirm_id": _dfirm,
                "firm_panel": _panels[0][1] if _panels else None,
                "panel_effective": _panels[0][2] if _panels else None,
                "raw_zones": "|".join(sorted({(z or "").strip() for _, z, _, _ in _r["28"]})),
            }
        )
    nfhl = pd.DataFrame(_rows)
    _eff = pd.to_datetime(nfhl.panel_effective, format="%m/%d/%Y", errors="coerce")
    # Some panels carry a placeholder date (12/31/9999); a date in the future is no date.
    nfhl["panel_effective"] = _eff.where(_eff <= pd.Timestamp.now())
    nfhl["flood_class"] = pd.Categorical(nfhl.flood_class, categories=_order, ordered=True)
    flooded = facilities.merge(nfhl, on="facility_id", how="left", validate="one_to_one")
    assert flooded.flood_class.notna().all(), "every facility must get a flood class"
    pd.crosstab(flooded.flood_class, flooded.facility_type, margins=True)
    return (flooded,)


@app.cell
def _(mo):
    mo.md(r"""
    The raw zone codes behind those classes, so a reader can check the grouping. Zones B and C
    are pre-1986 labels some older digital studies still carry; we read B as shaded X and C as
    minimal.
    """)
    return


@app.cell
def _(flooded):
    flooded.raw_zones.str.split("|").explode().replace("", "(none)").value_counts()
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. The counts

    Share of each facility group in the SFHA (A and V together, then split), in the 0.2% zone,
    and with no digital NFHL at the point. "Mapped" excludes points with no NFHL, open water,
    a study area with no zone, or a failed query, so the SFHA share among mapped points is the
    fair comparison across states with and without maps.
    """)
    return


@app.cell
def _(flooded, pd):
    def summarize(frame: pd.DataFrame) -> pd.Series:
        n = len(frame)
        cls = frame.flood_class
        sfha = cls.isin(["SFHA, A", "SFHA, V"])
        mapped = cls.isin(["SFHA, A", "SFHA, V", "0.2% zone", "other shaded X", "minimal", "D"])
        return pd.Series(
            {
                "facilities": n,
                "SFHA": int(sfha.sum()),
                "SFHA %": round(100 * sfha.mean(), 1),
                "SFHA % of mapped": round(100 * sfha.sum() / max(mapped.sum(), 1), 1),
                "zone A": int((cls == "SFHA, A").sum()),
                "zone V": int((cls == "SFHA, V").sum()),
                "0.2% zone": int((cls == "0.2% zone").sum()),
                "0.2% %": round(100 * (cls == "0.2% zone").mean(), 1),
                "zone D": int((cls == "D").sum()),
                "no NFHL": int((cls == "no NFHL").sum()),
                "no NFHL %": round(100 * (cls == "no NFHL").mean(), 1),
                "query failed": int((cls == "query failed").sum()),
            }
        )

    _groups = [("hospitals, all", flooded[flooded.facility_type == "hospital"])]
    _groups += [
        (f"substations, {s}", flooded[flooded.subtype == s])
        for s in ["230 kV+", "100-229 kV", "under 100 kV", "voltage unknown"]
    ]
    _groups.append(("substations, all", flooded[flooded.facility_type == "substation"]))
    counts = pd.DataFrame({name: summarize(frame) for name, frame in _groups}).T
    counts
    return counts, summarize


@app.cell
def _(mo):
    mo.md(r"""
    **Hospitals by type.** Critical access hospitals are small rural hospitals, often the only
    one in reach, so a flooded one has no neighbour to take its patients.
    """)
    return


@app.cell
def _(flooded, pd, summarize):
    _h = flooded[flooded.facility_type == "hospital"]
    pd.DataFrame({t: summarize(g) for t, g in _h.groupby("subtype")}).T.sort_values(
        "facilities", ascending=False
    )[["facilities", "SFHA", "SFHA %", "0.2% zone", "no NFHL"]]
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Where the NFHL has no coverage

    A facility with "no NFHL" isn't safe; it's unknown. These are communities with only paper
    FIRMs, or none. The table lists the states with the most facilities in those gaps.
    """)
    return


@app.cell
def _(flooded, pd):
    _gap = flooded[flooded.flood_class == "no NFHL"]
    nfhl_gaps = (
        pd.crosstab(_gap.state, _gap.facility_type)
        .assign(total=lambda t: t.sum(axis=1))
        .join(
            flooded.groupby("state").size().rename("all facilities in state"),
        )
        .assign(share=lambda t: (100 * t.total / t["all facilities in state"]).round(1))
        .sort_values("total", ascending=False)
    )
    nfhl_gaps.head(15)
    return (nfhl_gaps,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Ranking by the National Risk Index

    NRI v1.20 (December 2025) scores 2020 census tracts. FEMA's tract service gives scores without
    shapes, so we take shapes from the Census Bureau's 2020 cartographic tract file and join each
    point to the tract it falls in. We keep the overall risk score and the **inland flooding**
    (riverine) and **coastal flooding** risk scores and ratings. A score is a percentile among all
    tracts, 0 to 100. This step follows `facility-climate-ranking/`.
    """)
    return


@app.cell
def _(fetch, get_json, gpd, pd):
    _fields = [
        "TRACTFIPS",
        "STATEABBRV",
        "COUNTY",
        "NRI_VER",
        "RISK_SCORE",
        "RISK_RATNG",
        "IFLD_RISKS",
        "IFLD_RISKR",
        "CFLD_RISKS",
        "CFLD_RISKR",
    ]
    _url = (
        "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
        "National_Risk_Index_Census_Tracts/FeatureServer/0/query"
    )
    _rows: list[dict] = []
    for _page in range(60):
        _payload = get_json(
            _url,
            {
                "where": "1=1",
                "outFields": ",".join(_fields),
                "returnGeometry": "false",
                "orderByFields": "OBJECTID",
                "resultOffset": len(_rows),
                "resultRecordCount": 2000,
                "f": "json",
            },
        )
        _rows += [f["attributes"] for f in _payload["features"]]
        if not _payload.get("exceededTransferLimit"):
            break
    else:
        raise RuntimeError("NRI tract table still paging after 60 pages")
    nri = pd.DataFrame(_rows)
    assert nri.TRACTFIPS.is_unique and len(nri) > 80_000, "NRI tract table looks wrong"
    tracts = gpd.read_file(
        fetch(
            "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_tract_500k.zip",
            "cb_2020_us_tract_500k.zip",
        ),
        columns=["GEOID"],
    ).to_crs("EPSG:4326")
    pd.DataFrame(
        {
            "NRI tracts": [len(nri)],
            "NRI version": [", ".join(sorted(nri.NRI_VER.dropna().unique()))],
            "tract shapes": [len(tracts)],
        }
    )
    return nri, tracts


@app.cell
def _(flooded, gpd, nri, pd, tracts):
    _joined = gpd.sjoin(flooded, tracts, how="left", predicate="within").drop(columns="index_right")
    _joined = _joined[~_joined.facility_id.duplicated()]
    ranked = _joined.merge(
        nri, left_on="GEOID", right_on="TRACTFIPS", how="left", validate="many_to_one"
    )
    assert len(ranked) == len(flooded)
    _status = pd.Series("joined", index=ranked.index)
    _status[ranked.GEOID.isna()] = "outside every tract"
    _status[ranked.GEOID.notna() & ranked.TRACTFIPS.isna()] = "tract not in NRI"
    _status[ranked.GEOID.notna() & ranked.TRACTFIPS.notna() & ranked.IFLD_RISKS.isna()] = (
        "tract has no flood score"
    )
    ranked["nri_join"] = _status
    pd.crosstab(ranked.nri_join, ranked.facility_type)
    return (ranked,)


@app.cell
def _(mo):
    mo.md(r"""
    **Top facilities by NRI flood risk.** Many facilities share a tract, so the top of each list
    is a handful of tracts; ties are broken by name. Substations here are 100 kV and up, because
    small distribution substations crowd the list otherwise (the full ranking of every facility is
    in `results/facilities.csv`). The NRI ranks the tract, not the building: see the next table.
    """)
    return


@app.cell
def _(pd, ranked):
    _cols = [
        "facility_type",
        "name",
        "city",
        "state",
        "TRACTFIPS",
        "flood_class",
    ]
    _big = ranked[
        (ranked.facility_type == "hospital") | ranked.subtype.isin(["230 kV+", "100-229 kV"])
    ]
    _tops = []
    for _hazard, _score, _rating in [
        ("inland (riverine) flood", "IFLD_RISKS", "IFLD_RISKR"),
        ("coastal flood", "CFLD_RISKS", "CFLD_RISKR"),
    ]:
        for _type in ["hospital", "substation"]:
            _top = (
                _big[(_big.facility_type == _type) & _big[_score].notna()]
                .sort_values([_score, "name"], ascending=[False, True])
                .head(10)
            )
            _tops.append(
                _top[_cols + [_score, _rating]]
                .rename(columns={_score: "score", _rating: "rating"})
                .assign(hazard=_hazard, rank=range(1, len(_top) + 1))
            )
    top_facilities = pd.concat(_tops, ignore_index=True)
    top_facilities
    return (top_facilities,)


@app.cell
def _(mo):
    mo.md(r"""
    **Tract rating against the flood zone at the point.** For each facility we take the higher
    of its tract's inland and coastal flood ratings and ask what share of facilities in each
    rating are actually in the SFHA. If the NRI told you about the building, the "Very High" row
    would be mostly SFHA.
    """)
    return


@app.cell
def _(pd, plt, ranked, results):
    _levels = [
        "Very Low",
        "Relatively Low",
        "Relatively Moderate",
        "Relatively High",
        "Very High",
    ]
    _rank = {r: i for i, r in enumerate(_levels)}
    _mapped = ranked[
        ranked.flood_class.isin(
            ["SFHA, A", "SFHA, V", "0.2% zone", "other shaded X", "minimal", "D"]
        )
        & ranked.nri_join.eq("joined")
    ].copy()
    _i = _mapped.IFLD_RISKR.map(_rank)
    _c = _mapped.CFLD_RISKR.map(_rank)
    _mapped["tract_flood_rating"] = (
        pd.concat([_i, _c], axis=1).max(axis=1).map(dict(enumerate(_levels)))
    )
    _mapped = _mapped[_mapped.tract_flood_rating.notna()]
    _mapped["in_sfha"] = _mapped.flood_class.isin(["SFHA, A", "SFHA, V"])
    rating_vs_zone = (
        _mapped.groupby(["facility_type", "tract_flood_rating"])
        .agg(facilities=("in_sfha", "size"), in_sfha=("in_sfha", "sum"))
        .assign(sfha_pct=lambda t: (100 * t.in_sfha / t.facilities).round(1))
        .reset_index()
    )
    rating_vs_zone["tract_flood_rating"] = pd.Categorical(
        rating_vs_zone.tract_flood_rating, _levels, ordered=True
    )
    rating_vs_zone = rating_vs_zone.sort_values(["facility_type", "tract_flood_rating"])

    _fig, _ax = plt.subplots(figsize=(8, 4))
    for _type, _g in rating_vs_zone.groupby("facility_type"):
        _ax.plot(_g.tract_flood_rating.astype(str), _g.sfha_pct, marker="o", label=_type)
    _ax.set_ylabel("% of mapped facilities in the SFHA")
    _ax.set_xlabel("Tract's NRI flood rating (higher of inland and coastal)")
    _ax.set_title("NRI tract flood rating against the flood zone at the facility")
    _ax.legend()
    _ax.tick_params(axis="x", labelsize=8)
    _fig.tight_layout()
    _fig.savefig(results / "sfha_by_tract_rating.png", dpi=150)
    rating_vs_zone
    return (rating_vs_zone,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Vintage of each input

    The flood zone at a point is as old as its FIRM panel. Here are the panel effective dates
    for facilities with a panel, and the other inputs' dates.
    """)
    return


@app.cell
def _(hospitals, nri, pd, ranked):
    _p = ranked.panel_effective.dropna()
    vintage = pd.DataFrame(
        [
            [
                "HIFLD Next hospitals-3",
                "v1.1.1 (records of v1.1.0)",
                f"source dates: {(hospitals.source_date.dt.year >= 2024).mean():.0%} from 2024; "
                f"locations checked: median {int(hospitals.location_checked.dt.year.median())}",
            ],
            [
                "Substations (us-substations-verified)",
                "commit b48028f",
                "HIFLD Next Transmission Lines v1.0.0 + Overture Maps 2026-09-23.0 (OSM)",
            ],
            [
                "FEMA NFHL",
                "live service, queried this run",
                f"FIRM panel effective dates: median {int(_p.dt.year.median())}, "
                f"{(_p.dt.year < 2000).mean():.1%} before 2000, "
                f"{(_p.dt.year >= 2020).mean():.0%} 2020 or later",
            ],
            [
                "FEMA NRI",
                ", ".join(sorted(nri.NRI_VER.dropna().unique())),
                "tract table from FEMA's ArcGIS Online service",
            ],
            ["Census tracts", "2020 cartographic boundary, 1:500k", ""],
        ],
        columns=["input", "version", "dates"],
    )
    vintage
    return (vintage,)


@app.cell
def _(pd, ranked):
    _p = ranked.dropna(subset=["panel_effective"])
    pd.crosstab(
        pd.cut(
            _p.panel_effective.dt.year,
            [1970, 1990, 2000, 2010, 2015, 2020, 2030],
            right=False,
            labels=["1970s-80s", "1990s", "2000s", "2010-14", "2015-19", "2020+"],
        ),
        _p.facility_type,
        margins=True,
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Spot check: are the points on the facilities?

    A flood zone answer is only as good as the point. We drew a random sample (seed 193) of 25
    hospitals and 25 substations of 100 kV and up from those the NFHL puts in the SFHA, where a
    misplaced point matters most, and looked at each on Esri World Imagery with the NFHL zones
    drawn over it (`chips.py` makes the images; they aren't committed because the imagery is
    Esri's). For each we recorded whether the point sits **on** the facility, **near** it (within
    about 150 m, for example on its parking lot or street), or **off** (somewhere else), and
    whether the facility's footprint is **all**, **part** or **none** inside the SFHA.
    """)
    return


@app.cell
def _(here, pd, ranked, results):
    _pool = ranked[
        ranked.flood_class.isin(["SFHA, A", "SFHA, V"])
        & ((ranked.facility_type == "hospital") | ranked.subtype.isin(["230 kV+", "100-229 kV"]))
    ]
    spot_sample = pd.concat(
        [g.sample(min(25, len(g)), random_state=193) for _, g in _pool.groupby("facility_type")]
    )[["facility_id", "facility_type", "source", "name", "city", "state", "fld_zone"]].assign(
        lon=lambda t: ranked.loc[t.index].geometry.x.round(6),
        lat=lambda t: ranked.loc[t.index].geometry.y.round(6),
    )
    spot_sample.to_csv(results / "spot_check_sample.csv", index=False)
    _labels_path = here / "hand_check.csv"
    if _labels_path.exists():
        _labels = pd.read_csv(_labels_path)
        spot_check = spot_sample.merge(_labels, on="facility_id", how="left")
        spot_summary = pd.concat(
            [
                pd.crosstab(spot_check.facility_type, spot_check.location, margins=True),
                pd.crosstab(spot_check.facility_type, spot_check.footprint_in_sfha, margins=True),
            ],
            axis=1,
            keys=["point location", "footprint in SFHA"],
        )
    else:
        spot_check = spot_sample
        spot_summary = pd.DataFrame({"note": ["hand_check.csv not found"]})
    spot_summary
    return spot_check, spot_summary


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. What didn't work, and what this doesn't show

    - **No HIFLD substation layer.** The substation counts rest on our derived-plus-OSM dataset,
      not an official one. A derived point is where transmission lines end, which is inside the
      fence for most substations but can be a tap or a plant (see `us-substations-verified/`).
    - **A point is not a footprint.** A hospital campus can straddle a zone boundary; we classify
      the point. The spot check measures how often that changes the answer.
    - **The NFHL is not the whole flood picture.** It maps the 1% and 0.2% floodplains from
      studies that are often decades old, leaves out pluvial (rainfall) flooding, and has no
      digital coverage in some counties. Zone D and "no NFHL" mean unknown, not safe.
    - **The NRI ranks tracts, not buildings.** FEMA says the NRI does not replace local
      assessment, and the rating-against-zone table shows why.
    - **Downloading the NFHL** state by state was too big for one run (several GB per state), so
      we query FEMA's live service point by point. That makes the result depend on the service
      being up; answers are cached so a rerun only asks for what's missing.
    """)
    return


@app.cell
def _(
    counts,
    json,
    log,
    nfhl_gaps,
    rating_vs_zone,
    ranked,
    results,
    spot_check,
    spot_summary,
    started,
    time,
    top_facilities,
    vintage,
):
    _out = ranked.assign(lon=ranked.geometry.x.round(6), lat=ranked.geometry.y.round(6))
    _cols = [
        "facility_id",
        "facility_type",
        "subtype",
        "name",
        "city",
        "state",
        "lon",
        "lat",
        "flood_class",
        "fld_zone",
        "dfirm_id",
        "firm_panel",
        "panel_effective",
        "TRACTFIPS",
        "RISK_SCORE",
        "RISK_RATNG",
        "IFLD_RISKS",
        "IFLD_RISKR",
        "CFLD_RISKS",
        "CFLD_RISKR",
        "nri_join",
    ]
    _out[_cols].to_csv(results / "facilities.csv", index=False)
    counts.to_csv(results / "counts.csv")
    nfhl_gaps.to_csv(results / "nfhl_gaps_by_state.csv")
    top_facilities.to_csv(results / "top_facilities.csv", index=False)
    rating_vs_zone.to_csv(results / "sfha_by_tract_rating.csv", index=False)
    vintage.to_csv(results / "vintage.csv", index=False)
    spot_check.to_csv(results / "spot_check.csv", index=False)
    spot_summary.to_csv(results / "spot_check_summary.csv")
    _headline = {
        "facilities": counts["facilities"].to_dict(),
        "sfha": counts["SFHA"].to_dict(),
        "sfha_pct": counts["SFHA %"].to_dict(),
        "zone_02_pct": counts["0.2% %"].to_dict(),
        "no_nfhl_pct": counts["no NFHL %"].to_dict(),
        "query_failed": counts["query failed"].to_dict(),
        "run_minutes": round((time.time() - started) / 60, 1),
    }
    (results / "headline.json").write_text(json.dumps(_headline, indent=2, default=int))
    log.info("done in %.1f minutes", (time.time() - started) / 60)
    _headline
    return


if __name__ == "__main__":
    app.run()
