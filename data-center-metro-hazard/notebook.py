import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import logging
    import math
    import os
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import requests
    from shapely import wkt
    from sklearn.cluster import DBSCAN

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("dch")
    here = Path(mo.notebook_dir() or ".")
    cache = Path(os.environ.get("DCH_CACHE", Path.home() / ".cache" / "data-center-metro-hazard"))
    results = Path(os.environ.get("DCH_RESULTS", here / "results"))
    fri_dir = Path(os.environ.get("DCH_FRI_DATA", here.parent / "fri-datasets-map" / "data"))
    for _d in (cache / "nfhl", cache / "nri", results):
        _d.mkdir(parents=True, exist_ok=True)
    started = time.time()

    def get_json(url: str, params: dict, cache_file: Path, attempts: int = 5) -> dict:
        """GET a JSON response, cached on disk, with a bounded number of retries."""
        if cache_file.exists():
            return json.loads(cache_file.read_text())
        for attempt in range(attempts):
            try:
                response = requests.get(url, params=params, timeout=120)
                response.raise_for_status()
                payload = response.json()
                if "error" not in payload:
                    cache_file.write_text(json.dumps(payload))
                    return payload
                log.warning("%s attempt %d: %s", url, attempt + 1, payload["error"])
            except (requests.RequestException, ValueError) as error:
                log.warning("%s attempt %d: %s", url, attempt + 1, error)
            time.sleep(2**attempt)
        raise RuntimeError(f"{url} failed {attempts} times with {params}")

    return (
        DBSCAN,
        Path,
        ThreadPoolExecutor,
        cache,
        fri_dir,
        get_json,
        gpd,
        log,
        math,
        mo,
        np,
        pd,
        plt,
        requests,
        results,
        started,
        time,
        wkt,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Do data centers in the same metro share the same flood zones and risk scores?

    Cloud redundancy plans assume that when one building fails the next one keeps running. If the
    data centers in a metro all sit in the same FEMA flood zone and score alike on FEMA's National
    Risk Index (NRI) and the Future Risk Index (FRI), a single flood or storm could hit them
    together. This notebook tests that.

    **The claim is wrong** if sites in a metro are spread across flood zones with varied scores.

    Steps: (1) get an open list of reported US data-center sites, (2) group them by metro (Census
    CBSA), (3) score each site against the NFHL flood zone, the NRI (tract and county) and our FRI
    rebuild, (4) compare how alike the scores are within a metro and across metros, against a
    chance baseline, and (5) move every site 250 m to see how much the answer depends on where the
    point sits.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The site list: OpenStreetMap `telecom=data_center`

    HIFLD Next has no data-center layer, so we need an outside list. Two open ones exist:

    - **OpenStreetMap** features tagged `telecom=data_center`, licensed ODbL. Locations are
      crowd-mapped: mostly building or campus outlines traced from imagery, some single points.
    - **PNNL's IM3 Open Source Data Center Atlas** (DOI 10.57931/3017294, ODbL). It is built from
      the same OSM tag, adding square footage and county. Its files on MSD-LIVE were not
      downloadable from our run environment (the record lists only a placeholder file and the
      access endpoint returns 403), so we go to OSM directly. The atlas would add no locations OSM
      lacks.

    We query OSM through the University of Freiburg's public QLever SPARQL endpoint, which serves
    a full planet file and knows which features intersect the United States (OSM relation
    148838). Ways and relations are reduced to their centroid. The public Overpass servers
    refused or timed out from our environment.
    """)
    return


@app.cell
def _(cache, get_json, log, pd, requests, wkt):
    qlever = "https://qlever.dev/api/osm-planet"
    query = """
    PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
    PREFIX geo: <http://www.opengis.net/ont/geosparql#>
    PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
    PREFIX ogc: <http://www.opengis.net/rdf#>
    PREFIX osmrel: <https://www.openstreetmap.org/relation/>
    PREFIX osm2rdf: <https://osm2rdf.cs.uni-freiburg.de/rdf#>
    PREFIX osmmeta: <https://www.openstreetmap.org/meta/>
    SELECT ?osm ?name ?operator ?building ?area ?edited (geof:centroid(?geom) AS ?centroid)
    WHERE {
      ?osm osmkey:telecom "data_center" .
      ?osm ogc:sfIntersects osmrel:148838 .
      ?osm geo:hasGeometry/geo:asWKT ?geom .
      ?osm osmmeta:timestamp ?edited .
      OPTIONAL { ?osm osmkey:name ?name }
      OPTIONAL { ?osm osmkey:operator ?operator }
      OPTIONAL { ?osm osmkey:building ?building }
      OPTIONAL { ?osm osm2rdf:area ?area }
    }
    """
    _csv = cache / "osm_data_centers.csv"
    if not _csv.exists():
        _response = requests.get(
            qlever, params={"query": query}, headers={"Accept": "text/csv"}, timeout=300
        )
        _response.raise_for_status()
        assert _response.text.startswith("osm,"), _response.text[:300]
        _csv.write_text(_response.text)
    osm = pd.read_csv(_csv)
    assert osm.osm.is_unique, "one row per OSM feature expected"
    _points = osm.centroid.map(wkt.loads)
    osm["lon"] = [p.x for p in _points]
    osm["lat"] = [p.y for p in _points]
    osm["osm_type"] = osm.osm.str.split("/").str[3]
    planet = get_json(f"{qlever}?cmd=stats", {}, cache / "qlever_stats.json")["name-index"]
    log.info("%d OSM features; index: %s", len(osm), planet)
    osm_summary = pd.DataFrame(
        {
            "OSM features in the US": [len(osm)],
            "ways / nodes / relations": [
                "/".join(str((osm.osm_type == t).sum()) for t in ("way", "node", "relation"))
            ],
            "planet file": [planet.split("/pbf/")[1].split(",")[0]],
            "latest edit in list": [osm.edited.max()],
        }
    )
    osm_summary
    return (osm,)


@app.cell
def _(mo):
    mo.md(r"""
    OSM often maps a campus and each building inside it, so one facility can appear several
    times. We merge features whose centroids lie within 150 m of each other (DBSCAN on great-circle
    distance) and keep the largest footprint. Separate buildings further apart on one campus stay
    separate sites; later we check the result holds when partners within 1 km don't count.
    """)
    return


@app.cell
def _(DBSCAN, np, osm, pd):
    _earth_m = 6_371_000
    _labels = DBSCAN(eps=150 / _earth_m, min_samples=1, metric="haversine").fit_predict(
        np.radians(osm[["lat", "lon"]].to_numpy())
    )
    _ranked = osm.assign(group=_labels, area_rank=osm.area.fillna(-1)).sort_values(
        "area_rank", ascending=False
    )
    sites = (
        _ranked.groupby("group", sort=False)
        .agg(
            osm=("osm", "first"),
            name=("name", "first"),
            operator=("operator", "first"),
            lat=("lat", "first"),
            lon=("lon", "first"),
            area_m2=("area", "first"),
            osm_features=("osm", "size"),
        )
        .reset_index(drop=True)
    )
    sites["site_id"] = sites.osm.str.replace("https://www.openstreetmap.org/", "", regex=False)
    pd.DataFrame({"OSM features": [len(osm)], "sites after 150 m merge": [len(sites)]})
    return (sites,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Group sites by metro

    Each site is placed in its Core Based Statistical Area with the Census Bureau's 2024 TIGER
    CBSA boundaries. CBSAs are metropolitan (M1) or micropolitan (M2) areas; we keep both and call
    them metros. Sites outside any CBSA keep a blank metro and drop out of the metro comparison.
    """)
    return


@app.cell
def _(cache, gpd, log, requests, sites):
    _zip = cache / "tl_2024_us_cbsa.zip"
    if not _zip.exists():
        _response = requests.get(
            "https://www2.census.gov/geo/tiger/TIGER2024/CBSA/tl_2024_us_cbsa.zip", timeout=600
        )
        _response.raise_for_status()
        _zip.write_bytes(_response.content)
    _cbsa = gpd.read_file(_zip, columns=["CBSAFP", "NAME", "LSAD"])
    _points = gpd.GeoDataFrame(
        sites, geometry=gpd.points_from_xy(sites.lon, sites.lat), crs="EPSG:4326"
    ).to_crs(_cbsa.crs)
    _joined = _points.sjoin(_cbsa, how="left", predicate="within").drop_duplicates("site_id")
    sites_metro = sites.assign(
        cbsa=_joined.CBSAFP.to_numpy(),
        metro=_joined.NAME.to_numpy(),
        metro_type=_joined.LSAD.map({"M1": "metro", "M2": "micro"}).to_numpy(),
    )
    log.info(
        "%d of %d sites in a CBSA, %d CBSAs",
        sites_metro.cbsa.notna().sum(),
        len(sites_metro),
        sites_metro.cbsa.nunique(),
    )
    return (sites_metro,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Score each site

    **Flood zone.** We ask FEMA's live National Flood Hazard Layer service (layer 28, Flood Hazard
    Zones) which zone polygon contains the site, and the same for four points 250 m north, east,
    south and west of it. Zones are grouped by hazard: **SFHA** (zones A and V, the 1%-a-year
    floodplain), **shaded X** (moderate hazard: mostly the 0.2%-a-year floodplain, plus areas behind
    levees and 1% areas under a foot deep or draining under a square mile), **minimal** (unshaded
    X), **D**
    (undetermined), **open water**, and **not mapped** where the NFHL has no digital map. Where a
    point touches two polygons, the higher hazard wins.

    **NRI.** FEMA's v1.20 NRI tract layer gives each point its census tract and composite risk
    rating and score, and we join the county rating and score from the county layer.
    """)
    return


@app.cell
def _(ThreadPoolExecutor, cache, get_json, log, math, pd, sites_metro, time):
    nfhl_url = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
    nri_url = (
        "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
        "National_Risk_Index_Census_Tracts/FeatureServer/0/query"
    )
    nri_tract_fields = "TRACTFIPS,STCOFIPS,RISK_RATNG,RISK_SCORE,NRI_VER"
    hazard_order = ["SFHA", "shaded X", "minimal", "D", "open water", "not mapped"]
    offsets = {"here": (0, 0), "N": (250, 0), "E": (0, 250), "S": (-250, 0), "W": (0, -250)}

    def flood_class(features: list[dict]) -> tuple[str, str]:
        """Group NFHL zone polygons at a point into a hazard class; the highest hazard wins."""
        found = []
        for feature in features:
            zone = (feature["attributes"]["FLD_ZONE"] or "").strip()
            subtype = feature["attributes"]["ZONE_SUBTY"] or ""
            if feature["attributes"]["SFHA_TF"] == "T":
                found.append(("SFHA", zone))
            elif zone == "X" and subtype != "AREA OF MINIMAL FLOOD HAZARD":
                found.append(("shaded X", zone))
            elif zone == "X":
                found.append(("minimal", zone))
            elif zone == "D":
                found.append(("D", zone))
            elif zone == "OPEN WATER":
                found.append(("open water", zone))
        if not found:
            return "not mapped", ""
        return min(found, key=lambda pair: hazard_order.index(pair[0]))

    def score_point(job: tuple[str, str, float, float]) -> dict:
        """Flood class and NRI tract for one (site, offset) point."""
        site_id, offset, lat, lon = job
        key = f"{lat:.6f}_{lon:.6f}"
        geometry = {
            "geometry": f"{lon:.6f},{lat:.6f}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": "false",
            "f": "json",
        }
        nfhl = get_json(
            nfhl_url,
            {**geometry, "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF"},
            cache / "nfhl" / f"{key}.json",
        )
        nri = get_json(
            nri_url, {**geometry, "outFields": nri_tract_fields}, cache / "nri" / f"{key}.json"
        )
        flood, zone = flood_class(nfhl["features"])
        tract = nri["features"][0]["attributes"] if nri["features"] else {}
        return {
            "site_id": site_id,
            "offset": offset,
            "flood_class": flood,
            "flood_zone": zone,
            "tract": tract.get("TRACTFIPS"),
            "county_fips": tract.get("STCOFIPS"),
            "nri_tract_rating": tract.get("RISK_RATNG"),
            "nri_tract_score": tract.get("RISK_SCORE"),
            "nri_version": tract.get("NRI_VER"),
        }

    _jobs = []
    for _site in sites_metro.itertuples():
        _metres_per_deg_lon = 111_320 * math.cos(math.radians(_site.lat))
        for _name, (_north, _east) in offsets.items():
            _jobs.append(
                (
                    _site.site_id,
                    _name,
                    _site.lat + _north / 111_320,
                    _site.lon + _east / _metres_per_deg_lon,
                )
            )
    _t0 = time.time()
    with ThreadPoolExecutor(max_workers=12) as _pool:
        point_scores = pd.DataFrame(list(_pool.map(score_point, _jobs)))
    log.info("%d points scored in %.0f s", len(point_scores), time.time() - _t0)
    return hazard_order, point_scores


@app.cell
def _(cache, fri_dir, get_json, pd):
    _url = (
        "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
        "National_Risk_Index_Counties/FeatureServer/0/query"
    )
    _rows = []
    for _page in range(5):
        _payload = get_json(
            _url,
            {
                "where": "1=1",
                "outFields": "STCOFIPS,RISK_RATNG,RISK_SCORE",
                "returnGeometry": "false",
                "orderByFields": "OBJECTID",
                "resultOffset": len(_rows),
                "resultRecordCount": 2000,
                "f": "json",
            },
            cache / f"nri_counties_{_page}.json",
        )
        _rows += [f["attributes"] for f in _payload["features"]]
        if not _payload.get("exceededTransferLimit"):
            break
    nri_counties = pd.DataFrame(_rows).rename(
        columns={
            "STCOFIPS": "county_fips",
            "RISK_RATNG": "nri_county_rating",
            "RISK_SCORE": "nri_county_score",
        }
    )
    assert nri_counties.county_fips.is_unique

    # Our FRI rebuild: late century, higher warming, one multiplier per county and hazard.
    _scenario = "LATE_HIGHER"
    _mult = pd.read_csv(fri_dir / "multipliers_by_county.csv", dtype={"fips": str})
    _mult = _mult[(_mult.scenario == _scenario) & _mult.hazard.isin(["CFLD", "EXHT_L95"])]
    fri = _mult.pivot(index="fips", columns="hazard", values="rebuilt_hm").rename(
        columns={"CFLD": "fri_coastal_flood", "EXHT_L95": "fri_extreme_heat"}
    )
    _hrcn = pd.read_csv(fri_dir / "hurricane_by_county.csv", dtype={"fips": str})
    fri["fri_hurricane"] = _hrcn[_hrcn.scenario == _scenario].set_index("fips").our_hm
    fri = fri.reset_index().rename(columns={"fips": "county_fips"})
    return fri, nri_counties


@app.cell
def _(mo):
    mo.md(r"""
    **FRI.** From our rebuild (`fri-datasets-map/data/`), each site's county gets the late-century,
    higher-warming multiplier for the three hazards that threaten a data center's building or
    cooling: coastal flooding, hurricane and extreme heat (LOCA2, 95th percentile). Inland
    flooding was never part of FEMA's FRI. Like the county NRI, these are county values: two
    sites in one county always match.

    One row per site goes to `results/sites.csv`.
    """)
    return


@app.cell
def _(fri, nri_counties, point_scores, results, sites_metro):
    _here = point_scores[point_scores.offset == "here"].drop(columns="offset")
    site_scores = (
        sites_metro.merge(_here, on="site_id", how="left")
        .merge(nri_counties, on="county_fips", how="left")
        .merge(fri, on="county_fips", how="left")
    )
    site_scores.insert(1, "source", "OpenStreetMap telecom=data_center (ODbL) via QLever")
    site_scores.drop(columns=["osm"]).to_csv(results / "sites.csv", index=False)
    site_scores[["metro", "flood_class", "nri_tract_rating", "nri_county_rating"]].describe()
    return (site_scores,)


@app.cell
def _(hazard_order, pd, site_scores):
    _in_metro = site_scores.cbsa.notna()
    coverage = pd.DataFrame(
        {
            "sites": [len(site_scores)],
            "in a CBSA": [int(_in_metro.sum())],
            "CBSAs": [site_scores.cbsa.nunique()],
            "CBSAs with 2+ sites": [int((site_scores.cbsa.value_counts() >= 2).sum())],
            "with NRI tract": [int(site_scores.nri_tract_rating.notna().sum())],
            "with FRI values": [int(site_scores.fri_extreme_heat.notna().sum())],
        }
    )
    flood_counts = (
        site_scores.flood_class.value_counts().reindex(hazard_order, fill_value=0).rename("sites")
    )
    coverage, flood_counts.to_frame().T
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Do sites in a metro share the same scores?

    From here on we use only sites in a CBSA with at least two sites (the clusters a redundancy
    plan might span). **Share sharing** is the share of these sites with at least one other site
    in the same metro that has the same flood class *and* the same NRI rating.

    A high share alone proves little: if nearly every data center is in zone X, any two sites
    match. So we compare it with a **chance baseline**: shuffle the metro labels across the same
    sites 200 times (keeping each metro's size) and recompute. If metro clustering matters, the
    real share should be well above the shuffled one.
    """)
    return


@app.cell
def _(np, pd, site_scores):
    clustered = site_scores[
        site_scores.cbsa.notna() & site_scores.cbsa.map(site_scores.cbsa.value_counts()).ge(2)
    ].reset_index(drop=True)
    assert len(clustered) < 5000, "pairwise matrices below assume a few thousand sites"
    _rng = np.random.default_rng(174)
    _lat = np.radians(clustered.lat.to_numpy())
    _lon = np.radians(clustered.lon.to_numpy())
    _dlat = _lat[:, None] - _lat[None, :]
    _dlon = _lon[:, None] - _lon[None, :]
    _hav = (
        np.sin(_dlat / 2) ** 2
        + np.cos(_lat[:, None]) * np.cos(_lat[None, :]) * np.sin(_dlon / 2) ** 2
    )
    distance_km = 2 * 6371 * np.arcsin(np.sqrt(_hav))

    def shares_with_metro_mate(metro: np.ndarray, keys: list[str], min_km: float) -> np.ndarray:
        """Per site: does another site in the same metro, min_km or more away, match on keys?"""
        same = metro[:, None] == metro[None, :]
        for key in keys:
            values = clustered[key].fillna("missing").to_numpy()
            same &= values[:, None] == values[None, :]
        same &= distance_km >= min_km
        np.fill_diagonal(same, False)
        return same.any(axis=1)

    _metro = clustered.cbsa.to_numpy()
    _shuffles = [_rng.permutation(_metro) for _ in range(200)]
    _all = np.ones(len(clustered), bool)
    _county_key = ["flood_class", "nri_county_rating"]
    _tract_key = ["flood_class", "nri_tract_rating"]
    _floodplain = clustered.flood_class.isin(["SFHA", "shaded X"]).to_numpy()
    _not_dc = (clustered.cbsa != "47900").to_numpy()  # Washington, DC metro (Ashburn)
    _tests = {
        "flood class + NRI county rating": (_county_key, 0.0, _all),
        "flood class + NRI tract rating": (_tract_key, 0.0, _all),
        "flood class + NRI county rating, partner 1 km+ away": (_county_key, 1.0, _all),
        "flood class + NRI tract rating, partner 1 km+ away": (_tract_key, 1.0, _all),
        "flood class + NRI tract rating, without the DC metro": (_tract_key, 0.0, _not_dc),
        "SFHA or shaded X sites, partner in the same class": (["flood_class"], 0.0, _floodplain),
        "SFHA sites, partner also SFHA": (
            ["flood_class"],
            0.0,
            (clustered.flood_class == "SFHA").to_numpy(),
        ),
    }
    _rows = []
    for _label, (_keys, _min_km, _mask) in _tests.items():
        _real = shares_with_metro_mate(_metro, _keys, _min_km)[_mask].mean()
        _null = [shares_with_metro_mate(m, _keys, _min_km)[_mask].mean() for m in _shuffles]
        _rows.append(
            {
                "test": _label,
                "sites": int(_mask.sum()),
                "share sharing": round(float(_real), 3),
                "chance (shuffled metros)": round(float(np.mean(_null)), 3),
                "chance 95th pct": round(float(np.percentile(_null, 95)), 3),
            }
        )
    sharing = pd.DataFrame(_rows)
    sharing
    return clustered, distance_km, sharing


@app.cell
def _(mo):
    mo.md(r"""
    **Within against between.** For every pair of clustered sites we ask whether the two match
    (categories) or how far apart their scores are (numbers), and compare pairs in the same metro
    with pairs in different metros. County-level values (county NRI, FRI) match by construction
    for two sites in one county, so we also show same-metro pairs in *different* counties. The
    last column is the share of score variance explained by the metro (η²), with how often 200
    shuffles of the metro labels reach it.
    """)
    return


@app.cell
def _(clustered, distance_km, np, pd, results):
    _metro = clustered.cbsa.to_numpy()
    _county = clustered.county_fips.fillna("?").to_numpy()
    _upper = np.triu(np.ones((len(clustered), len(clustered)), bool), k=1)
    _same_metro = (_metro[:, None] == _metro[None, :]) & _upper
    _between = (_metro[:, None] != _metro[None, :]) & _upper
    _diff_county = _same_metro & (_county[:, None] != _county[None, :])
    _rng = np.random.default_rng(174)

    def _eta2(values: np.ndarray, labels: np.ndarray) -> float:
        frame = pd.DataFrame({"v": values, "g": labels}).dropna()
        group_mean = frame.groupby("g").v.transform("mean")
        total = ((frame.v - frame.v.mean()) ** 2).sum()
        return float(((group_mean - frame.v.mean()) ** 2).sum() / total)

    _rows = []
    for _col in ["flood_class", "nri_tract_rating", "nri_county_rating"]:
        _v = clustered[_col].fillna("missing").to_numpy()
        _match = _v[:, None] == _v[None, :]
        _rows.append(
            {
                "measure": _col,
                "kind": "share of pairs that match",
                "same metro": _match[_same_metro].mean(),
                "same metro, different county": _match[_diff_county].mean(),
                "different metros": _match[_between].mean(),
            }
        )
    for _col in [
        "nri_tract_score",
        "nri_county_score",
        "fri_coastal_flood",
        "fri_hurricane",
        "fri_extreme_heat",
    ]:
        _v = clustered[_col].to_numpy(float)
        _gap = np.abs(_v[:, None] - _v[None, :])
        _real = _eta2(_v, _metro)
        _null = [_eta2(_v, _rng.permutation(_metro)) for _ in range(200)]
        _rows.append(
            {
                "measure": _col,
                "kind": "mean absolute gap",
                "same metro": np.nanmean(_gap[_same_metro]),
                "same metro, different county": np.nanmean(_gap[_diff_county]),
                "different metros": np.nanmean(_gap[_between]),
                "variance explained by metro (eta2)": _real,
                "eta2 by chance (mean of shuffles)": float(np.mean(_null)),
                "shuffles reaching it": int(np.sum(np.array(_null) >= _real)),
            }
        )
    within_between = pd.DataFrame(_rows).round(3)
    within_between.to_csv(results / "within_between.csv", index=False)
    pair_counts = {
        "same-metro pairs": int(_same_metro.sum()),
        "of which different county": int(_diff_county.sum()),
        "different-metro pairs": int(_between.sum()),
        "median same-metro distance km": float(np.median(distance_km[_same_metro])),
    }
    within_between, pair_counts
    return (within_between,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Which metros carry the most hazard?

    Per metro: how many sites, in how many counties, how many sit in the SFHA or shaded X,
    and how many are in a tract the NRI rates Very High or Relatively High. Written to
    `results/metros.csv`.
    """)
    return


@app.cell
def _(pd, results, site_scores):
    _high = ["Very High", "Relatively High"]
    _m = site_scores[site_scores.cbsa.notna()]
    metros = (
        _m.groupby(["cbsa", "metro"])
        .agg(
            sites=("site_id", "size"),
            counties=("county_fips", "nunique"),
            flood_classes=("flood_class", "nunique"),
            sfha=("flood_class", lambda s: int((s == "SFHA").sum())),
            sfha_or_shaded=("flood_class", lambda s: int(s.isin(["SFHA", "shaded X"]).sum())),
            nri_tract_high=("nri_tract_rating", lambda s: int(s.isin(_high).sum())),
            nri_tract_ratings=("nri_tract_rating", "nunique"),
            nri_county_high=("nri_county_rating", lambda s: int(s.isin(_high).sum())),
            fri_hurricane=("fri_hurricane", "median"),
            fri_coastal_flood=("fri_coastal_flood", "median"),
        )
        .reset_index()
        .sort_values("sites", ascending=False)
    )
    metros.to_csv(results / "metros.csv", index=False)
    top_flood = metros.sort_values(["sfha_or_shaded", "sites"], ascending=False).head(10)
    top_nri = metros.sort_values(["nri_tract_high", "sites"], ascending=False).head(10)
    pd.concat({"by sites in SFHA or shaded X": top_flood, "by sites in high-NRI tracts": top_nri})
    return (metros,)


@app.cell
def _(metros, plt, results):
    _top = metros.head(20).iloc[::-1].reset_index(drop=True)
    _fig, _ax = plt.subplots(figsize=(8, 9))
    _bars = [
        ("sites", "#cfd8e3", "all sites"),
        ("nri_tract_high", "#d9822b", "in a Very or Relatively High NRI tract"),
        ("sfha_or_shaded", "#2b6cb0", "in SFHA or shaded X"),
    ]
    for _i, (_col, _color, _label) in enumerate(_bars):
        _ax.barh(_top.index + (_i - 1) * 0.27, _top[_col], height=0.27, color=_color, label=_label)
    _ax.set_yticks(_top.index, _top.metro)
    _ax.set_xlabel("OSM data-center sites")
    _ax.set_title("The 20 metros with the most reported data-center sites")
    _ax.legend(loc="lower right")
    _fig.tight_layout()
    _fig.savefig(results / "metros.png", dpi=150)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. How much does a 250 m location error matter?

    OSM centroids can be off by a building or more, and a campus centroid may sit in a car park.
    We moved every site 250 m in each of four directions and count how many change flood class or
    NRI tract rating at one or more of the four moves.
    """)
    return


@app.cell
def _(pd, point_scores, results):
    _wide = point_scores.pivot(index="site_id", columns="offset")
    _rows = []
    for _col in ["flood_class", "nri_tract_rating", "tract"]:
        _base = _wide[(_col, "here")]
        _moved = pd.concat([_wide[(_col, o)] != _base for o in ["N", "E", "S", "W"]], axis=1)
        _rows.append(
            {
                "measure": _col,
                "sites changing at 1+ of 4 moves": int(_moved.any(axis=1).sum()),
                "share": round(float(_moved.any(axis=1).mean()), 3),
                "share of single moves that change": round(float(_moved.to_numpy().mean()), 3),
            }
        )
    _sfha_here = _wide[("flood_class", "here")] == "SFHA"
    _sfha_any = pd.concat(
        [_wide[("flood_class", o)] == "SFHA" for o in ["N", "E", "S", "W"]], axis=1
    ).any(axis=1)
    _rows.append(
        {
            "measure": "not SFHA at the point, SFHA at 1+ moves",
            "sites changing at 1+ of 4 moves": int((_sfha_here != _sfha_any).sum()),
            "share": round(float((_sfha_here != _sfha_any).mean()), 3),
        }
    )
    sensitivity = pd.DataFrame(_rows)
    sensitivity.to_csv(results / "location_sensitivity.csv", index=False)
    sensitivity
    return (sensitivity,)


@app.cell
def _(
    clustered,
    json,
    log,
    metros,
    results,
    sensitivity,
    sharing,
    site_scores,
    started,
    time,
    within_between,
):
    headline = {
        "sites": len(site_scores),
        "sites_in_cbsa": int(site_scores.cbsa.notna().sum()),
        "cbsas": int(site_scores.cbsa.nunique()),
        "clustered_sites": len(clustered),
        "clustered_cbsas": int(clustered.cbsa.nunique()),
        "sharing": sharing.to_dict("records"),
        "within_between": within_between.to_dict("records"),
        "top_metros_by_sites": metros.head(10)[["metro", "sites", "sfha_or_shaded"]].to_dict(
            "records"
        ),
        "location_sensitivity": sensitivity.to_dict("records"),
        "run_seconds": round(time.time() - started),
        "cost_usd": 0,
    }
    (results / "headline.json").write_text(json.dumps(headline, indent=2, default=str))
    log.info("done in %d s", headline["run_seconds"])
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - **The list is what OSM mappers drew.** It misses unmapped sites and includes some small
      server rooms tagged as data centers. It has no operator-confirmed coordinates.
    - **A shared flood class is not a shared outage.** Most sites are outside mapped floodplains,
      and operators raise floors and site equipment above flood elevation. The NFHL is today's
      map and is not a forecast of the next storm.
    - **County indices can't separate sites in one county.** The county NRI and the FRI give every
      site in a county the same value, so their within-metro agreement is mostly the county.
    - **No conflict or geopolitical scoring**, by design.
    """)
    return


if __name__ == "__main__":
    app.run()
