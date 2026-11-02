import marimo

__generated_with = "0.17.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import subprocess
    import tempfile
    import zipfile
    from pathlib import Path

    import geopandas as gpd
    import httpx
    import marimo as mo
    import pandas as pd

    return Path, gpd, httpx, json, mo, os, pd, subprocess, tempfile, zipfile


@app.cell
def _(mo):
    mo.md(r"""
    # Part 1: ten flood-exposure questions and their answer key

    We ask an agent ten questions about which public facilities sit in FEMA's flood zones. Before any
    agent sees them, we answer them ourselves from the same public data, here, with GeoPandas, and
    cross-check the counts with QGIS. This notebook and `questions.json` were committed before the
    first agent run.

    Four places: **Harris County, TX**, **Orleans Parish, LA**, **Miami-Dade County, FL** and
    **Charleston County, SC**.
    """)
    return


@app.cell
def _(Path, json, os):
    HERE = Path(__file__).parent
    CACHE = Path(os.environ.get("HQAE_CACHE", Path.home() / ".cache" / "hifld-qgis-agent-errors"))
    CACHE.mkdir(parents=True, exist_ok=True)
    QUESTIONS = json.loads((HERE / "questions.json").read_text())
    COUNTIES = {
        "48201": {"name": "Harris County, TX", "utm": 32615},
        "22071": {"name": "Orleans Parish, LA", "utm": 32615},
        "12086": {"name": "Miami-Dade County, FL", "utm": 32617},
        "45019": {"name": "Charleston County, SC", "utm": 32617},
    }
    return CACHE, COUNTIES, HERE, QUESTIONS


@app.cell
def _(mo):
    mo.md(r"""
    ## The data

    **HIFLD Next facility layers.** The GeoParquet files HIFLD Next publishes, the same files its MCP
    server queries. Versions are pinned in the paths. Several layers are stored in Web Mercator
    (EPSG:3857), the rest in WGS 84; the county boundaries are NAD83.

    **FEMA NFHL.** Each county's current NFHL extract from FEMA's Map Service Center, the way
    `open-flood-layer-vs-nfhl/` reads it. We use the flood hazard zones, `S_FLD_HAZ_AR`. The Special
    Flood Hazard Area (SFHA) is every zone with `SFHA_TF = 'T'` (A, AE, AH, AO, VE and so on). The
    0.2%-annual-chance area is zone X with `ZONE_SUBTY = '0.2 PCT ANNUAL CHANCE FLOOD HAZARD'`. The
    Map Service Center serves only the latest extract, so the file names (which carry its date) are
    recorded in `answer_key.json`; a later run may download a newer map.

    HIFLD Next also has a dataset called *NFHL*. Its "Flood Hazard Zones" file holds 720 high water
    marks, not flood zones, so it can't answer these questions. We leave it in the catalog the agent
    sees, since an agent that uses it has picked the wrong layer.
    """)
    return


@app.cell
def _(CACHE, httpx):
    HIFLD = "https://hifld.publicenvirodata.org/storage/hifld"
    LAYERS = {
        "hospitals": "hospitals-3/hospitals-3/v1.1.0/geoparquet/hospitals-3.parquet",
        "nursing": "nursing-homes/nursing-homes/v1.0.0/geoparquet/nursing-homes.parquet",
        "schools": "public-schools/public-schools/v1.0.0/geoparquet/public-schools.parquet",
        "fire": "fire-and-emergency-medical-service-ems-stations/fire-and-emergency-medical-service-ems-stations/v1.0.0/geoparquet/fire-and-emergency-medical-service-ems-stations.parquet",
        "plants": "power-plants-1/power-plants-1/v1.0.0/geoparquet/power-plants-1.parquet",
        "lines": "transmission-lines-1/transmission-lines-1/v1.0.0/geoparquet/transmission-lines-1.parquet",
        "dialysis": "dialysis-centers/dialysis-centers/v1.0.0/geoparquet/dialysis-centers.parquet",
        "counties": "us-county-boundaries-1/us-county-boundaries-1/v1.0.0/geoparquet/us-county-boundaries-1.parquet",
    }
    for _name, _path in LAYERS.items():
        _file = CACHE / f"{_name}.parquet"
        if _file.exists():
            continue
        with httpx.stream("GET", f"{HIFLD}/{_path}", timeout=600, follow_redirects=True) as _r:
            _r.raise_for_status()
            _file.write_bytes(_r.read())
    return HIFLD, LAYERS


@app.cell
def _(CACHE, COUNTIES, httpx, zipfile):
    # The Map Service Center redirects to the county's latest NFHL extract (<FIPS>C_<date>.zip).
    # FEMA's server drops connections now and then, so each download gets up to four tries.
    # We record the date stamped on the zone file inside each extract.
    nfhl_files = {}
    for _fips in COUNTIES:
        _zip = CACHE / f"nfhl_{_fips}C.zip"
        for _attempt in range(4):
            if _zip.exists():
                break
            try:
                with httpx.stream(
                    "GET",
                    "https://msc.fema.gov/portal/downloadProduct",
                    params={
                        "productTypeID": "NFHL",
                        "productSubTypeID": "NFHL_COUNTY_DATA",
                        "productID": f"NFHL_{_fips}C",
                    },
                    timeout=900,
                    follow_redirects=True,
                ) as _r:
                    _r.raise_for_status()
                    _zip.write_bytes(_r.read())
            except httpx.HTTPError as _e:
                print(f"NFHL {_fips}: attempt {_attempt + 1} failed: {_e}")
        assert _zip.exists(), f"could not download the NFHL extract for {_fips}"
        _dir = CACHE / "nfhl" / f"{_fips}C"
        with zipfile.ZipFile(_zip) as _z:
            _y, _m, _d = _z.getinfo("S_FLD_HAZ_AR.shp").date_time[:3]
            if not (_dir / "S_FLD_HAZ_AR.shp").exists():
                _z.extractall(_dir)
        nfhl_files[_fips] = f"{_fips}C extract dated {_y}-{_m:02d}-{_d:02d}"
    nfhl_files
    return (nfhl_files,)


@app.cell
def _(CACHE, COUNTIES, gpd):
    # Load everything once, reprojected per county into its UTM zone so distances and lengths are meters.
    counties = gpd.read_parquet(CACHE / "counties.parquet")
    facilities = {
        k: gpd.read_parquet(CACHE / f"{k}.parquet")
        for k in ["hospitals", "nursing", "schools", "fire", "plants", "dialysis"]
    }
    lines = gpd.read_parquet(CACHE / "lines.parquet")
    zones = {}
    county_shape = {}
    for _fips, _c in COUNTIES.items():
        zones[_fips] = gpd.read_file(
            CACHE / "nfhl" / f"{_fips}C" / "S_FLD_HAZ_AR.shp", columns=["FLD_ZONE", "ZONE_SUBTY", "SFHA_TF"]
        ).to_crs(_c["utm"])
        county_shape[_fips] = counties[counties.GEOID == _fips].to_crs(_c["utm"]).geometry.iloc[0]
    {k: f"{len(v):,} zones" for k, v in zones.items()}
    return county_shape, facilities, lines, zones


@app.cell
def _(mo):
    mo.md(r"""
    ## How we answer

    "In Harris County" means inside the county boundary. Where a layer also has a `COUNTYFIPS` field,
    we count that way too. "Inside the SFHA" means the point falls within an SFHA polygon; we also
    count points that only touch one. When these choices give different numbers, the key accepts each
    of them, so an agent isn't marked wrong for a defensible choice. The table at the end shows where
    that happened.

    `in_county` and `flood_join` are the two steps every question shares, so they're functions.
    """)
    return


@app.cell
def _(COUNTIES, county_shape, facilities, gpd, zones):
    def in_county(layer: str, fips: str, by: str) -> gpd.GeoDataFrame:
        """Facilities of one layer in one county, by boundary ('polygon') or by the COUNTYFIPS field ('field')."""
        gdf = facilities[layer].to_crs(COUNTIES[fips]["utm"])
        if by == "field":
            assert "COUNTYFIPS" in gdf, f"{layer} has no COUNTYFIPS field"
            return gdf[gdf.COUNTYFIPS.astype(str).str.zfill(5) == fips]
        return gdf[gdf.within(county_shape[fips])]

    def flood_join(points: gpd.GeoDataFrame, fips: str, predicate: str) -> gpd.GeoDataFrame:
        """Each point with the flood zone it falls in; a point on two zones keeps the SFHA one."""
        z = zones[fips]
        joined = gpd.sjoin(points, z, predicate=predicate, how="left")
        joined = joined.sort_values("SFHA_TF", ascending=False, na_position="last")
        return joined[~joined.index.duplicated(keep="first")].sort_index()

    def variants(layer: str, fips: str) -> list[tuple[str, str]]:
        ways = ["polygon", "field"] if "COUNTYFIPS" in facilities[layer] else ["polygon"]
        return [(by, pred) for by in ways for pred in ["within", "intersects"]]

    return flood_join, in_county, variants


@app.cell
def _(flood_join, in_county, variants):
    # Q1-Q5, Q8, Q10 are counts, names or sums over facilities in the SFHA (or the 0.2% zone),
    # computed under every county and predicate choice.
    def sfha_rows(layer: str, fips: str, by: str, pred: str):
        j = flood_join(in_county(layer, fips, by), fips, pred)
        return j, j[j.SFHA_TF == "T"]

    answers = {}

    _rows = {v: sfha_rows("hospitals", "48201", *v)[1] for v in variants("hospitals", "48201")}
    answers["Q1"] = {"accepted": sorted({len(r) for r in _rows.values()})}

    _rows = {v: sfha_rows("nursing", "22071", *v)[1] for v in variants("nursing", "22071")}
    answers["Q2"] = {"accepted_sets": sorted({tuple(sorted(r.NAME)) for r in _rows.values()})}

    _rows = {v: sfha_rows("schools", "12086", *v)[1] for v in variants("schools", "12086")}
    answers["Q3"] = {"accepted": sorted({len(r) for r in _rows.values()})}

    _counts = set()
    for _v in variants("nursing", "45019"):
        _j, _ = sfha_rows("nursing", "45019", *_v)
        _counts.add(int(((_j.SFHA_TF != "T") & _j.ZONE_SUBTY.fillna("").str.startswith("0.2 PCT")).sum()))
    answers["Q4"] = {"accepted": sorted(_counts)}

    _rows = {v: sfha_rows("fire", "12086", *v)[1] for v in variants("fire", "12086")}
    answers["Q5"] = {"accepted": sorted({len(r) for r in _rows.values()})}

    _sums = set()
    for _v in variants("hospitals", "12086"):
        _r = sfha_rows("hospitals", "12086", *_v)[1]
        _r = _r[(_r.STATUS == "OPEN") & (_r.BEDS > 0)]
        _sums.add(int(_r.BEDS.sum()))
    answers["Q8"] = {"accepted": sorted(_sums), "unit": "beds"}

    _pcts = set()
    for _v in variants("dialysis", "48201"):
        _j, _r = sfha_rows("dialysis", "48201", *_v)
        _pcts.add(round(100 * len(_r) / len(_j), 2))
    answers["Q10"] = {"accepted": sorted(_pcts), "tolerance": 0.5, "unit": "%"}
    return (answers,)


@app.cell
def _(mo):
    mo.md(r"""
    **Q6** needs a distance. We measure it in UTM zone 15N, in meters, from each plant to the nearest
    SFHA polygon. "Operating" is `STATUS = 'OP'`; `OPER_CAP` is in MW and uses -999999 for missing.
    For contrast we also measure in Web Mercator, the CRS the power plants layer is stored in, where
    a "meter" near Houston is about 0.87 real meters.
    """)
    return


@app.cell
def _(COUNTIES, answers, county_shape, facilities, zones):
    _plants = facilities["plants"].to_crs(COUNTIES["48201"]["utm"])
    _plants = _plants[_plants.within(county_shape["48201"])]
    _big = _plants[(_plants.STATUS == "OP") & (_plants.OPER_CAP >= 100)]
    _sfha = zones["48201"][zones["48201"].SFHA_TF == "T"].union_all()
    _dist = _big.distance(_sfha)
    q6 = _big.assign(meters=_dist.round(0))[_dist <= 500][["NAME", "OPER_CAP", "meters"]]

    _big_wm = _big.to_crs(3857)
    _dist_wm = _big_wm.distance(zones["48201"][zones["48201"].SFHA_TF == "T"].to_crs(3857).union_all())
    q6_web_mercator = sorted(_big_wm[_dist_wm <= 500].NAME)

    answers["Q6"] = {"accepted_sets": [tuple(sorted(q6.NAME))], "web_mercator_answer": q6_web_mercator}
    q6
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Q7** clips lines with `VOLTAGE >= 345` (kV; -999999 means missing) to the county, then to the
    SFHA, and sums their length in UTM 15N. The key accepts ±3% because a clip done another way
    (dissolved or not, another projected CRS) moves the total by a little.
    """)
    return


@app.cell
def _(COUNTIES, answers, county_shape, lines, zones):
    _hv = lines[lines.VOLTAGE >= 345].to_crs(COUNTIES["48201"]["utm"])
    _in_county = _hv.clip(county_shape["48201"])
    _in_sfha = _in_county.clip(zones["48201"][zones["48201"].SFHA_TF == "T"].union_all())
    q7_km = round(_in_sfha.length.sum() / 1000, 1)
    answers["Q7"] = {
        "accepted": [q7_km],
        "tolerance_pct": 3,
        "unit": "km",
        "context": {"km_345kv_plus_in_county": round(_in_county.length.sum() / 1000, 1)},
    }
    answers["Q9"] = {"accepted": ["unavailable"], "why": "HIFLD Next has no electric substations layer"}
    answers["Q7"]
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Check: the same counts in QGIS

    An independent engine for the count questions: QGIS's own *Extract by location* run through
    `qgis_process`, on the county's facilities and SFHA polygons written to GeoPackages. If a count
    isn't one the key already accepts, the notebook stops.
    """)
    return


@app.cell
def _(answers, gpd, in_county, json, subprocess, tempfile, zones):
    def qgis_count(layer: str, fips: str, by: str) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            pts, sfha = f"{tmp}/pts.gpkg", f"{tmp}/sfha.gpkg"
            in_county(layer, fips, by)[["geometry"]].to_file(pts)
            zones[fips][zones[fips].SFHA_TF == "T"][["geometry"]].to_file(sfha)
            params = {"inputs": {"INPUT": pts, "INTERSECT": sfha, "PREDICATE": [0], "OUTPUT": f"{tmp}/out.gpkg"}}
            proc = subprocess.run(
                ["qgis_process", "--json", "run", "native:extractbylocation", "-"],
                input=json.dumps(params),
                capture_output=True,
                text=True,
                timeout=600,
                env={"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin:/bin"},
            )
            assert proc.returncode == 0, proc.stderr[-2000:]
            return len(gpd.read_file(f"{tmp}/out.gpkg"))

    qgis_check = {
        "Q1": qgis_count("hospitals", "48201", "polygon"),
        "Q3": qgis_count("schools", "12086", "polygon"),
        "Q5": qgis_count("fire", "12086", "polygon"),
    }
    for _q, _n in qgis_check.items():
        assert _n in answers[_q]["accepted"], f"{_q}: QGIS counts {_n}, key accepts {answers[_q]['accepted']}"
    qgis_check
    return (qgis_check,)


@app.cell
def _(HERE, QUESTIONS, answers, json, mo, nfhl_files, pd, qgis_check):
    key = {
        "questions": {q["id"]: {**q, **answers[q["id"]]} for q in QUESTIONS},
        "nfhl_extracts": nfhl_files,
        "qgis_check": qgis_check,
    }
    (HERE / "answer_key.json").write_text(json.dumps(key, indent=2, default=list))

    def _show(a: dict) -> str:
        if "accepted_sets" in a:
            return " | ".join("; ".join(s) for s in a["accepted_sets"])
        unit = a.get("unit", "")
        return " or ".join(f"{v}{(' ' + unit) if unit and unit != '%' else unit}" for v in a["accepted"])

    mo.vstack(
        [
            mo.md("## The answer key"),
            mo.ui.table(
                pd.DataFrame(
                    [
                        {
                            "id": q["id"],
                            "level": q["level"],
                            "question": q["question"],
                            "answer": _show(answers[q["id"]]),
                        }
                        for q in QUESTIONS
                    ]
                ),
                selection=None,
                page_size=10,
            ),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
