import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import time
    from datetime import UTC, date, datetime
    from pathlib import Path

    import duckdb
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import requests

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("LAYERS_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("LAYERS_OUTPUT_DIR", HERE / "output"))
    INVENTORY = HERE / "inventory"
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    # Regrid's public "Coverage Report" Google Sheet, one tab per product (tab ids from its htmlview page).
    REGRID_SHEET = "https://docs.google.com/spreadsheets/d/1rvRYv6_ppZlwbmyi2kbzemot6FOEm2EEPdHPyENTQPE"
    REGRID_TABS = {"parcels": 1284673582, "buildings": 990012686, "addresses": 395432099, "zoning": 1140654165}
    MIREYE_FETCH_FIELDS = "https://api.mireye.com/v1/meta/fields"
    MIREYE_ENRICH_FIELDS = "https://api.mireye.com/v1/enrich/fields"
    TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Census2020/MapServer"
    OVERTURE_RELEASE = "2026-10-21.0"
    OVERTURE = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
    COUNTIES = {"Wake NC": "37183", "Fergus MT": "30027", "Gordon GA": "13129"}
    RATINGS = ["public and easy", "public but scattered", "proprietary"]
    TODAY = date.today()
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Can we rebuild Regrid's and Mireye's layers from public sources?

    **The question.** Commercial parcel platforms sell many layers on top of the parcel map: owners, values, sales,
    zoning, buildings, addresses, flood zones and more. How many of those layers could an open rebuild cover from
    sources anyone can reach? Which are genuinely proprietary? And where is an advertised layer thinner or older than
    the marketing says?

    **The two vendors.**

    - [Regrid](https://regrid.com) sells US parcel data (160 million parcels) with add-ons for buildings, addresses,
      zoning and ownership.
    - [Mireye](https://www.mireye.com) is a Y Combinator (Summer 2026) start-up selling "physical world context for
      AI agents". It is one API and an MCP server that answers questions about a place with cited fields. It
      launched on [Hacker News](https://news.ycombinator.com/item?id=49552616) on 2026-09-03. Its field catalog is
      public JSON, so we can rate every field it sells.

    **The method.**

    1. List every layer each vendor advertises, from its public docs.
    2. Rate each layer **public and easy** (one national or statewide source), **public but scattered** (public
       record, but it takes county-by-county work) or **proprietary** (licensed, bought or derived by the vendor).
    3. Read Regrid's own published coverage report to see where its layers are thin or stale.
    4. Count what public sources hold in three counties of different kinds, against what Regrid says it has there.

    Everything is read from public pages and public endpoints at run time. We used no logins, vendor accounts or
    paid services. We record no owner names: owner fields are only counted.
    """)
    return


@app.cell
def _():
    def get(url: str, params: dict | None = None, timeout: int = 120) -> requests.Response:
        """GET with three tries; raises on a final HTTP error."""
        for attempt in range(3):
            try:
                response = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "fr-spike"})
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        raise AssertionError("unreachable")

    def download(url: str, name: str) -> Path:
        """Download url into DATA/name once; later runs reuse the copy."""
        path = DATA / name
        if not path.exists():
            path.write_bytes(get(url, timeout=600).content)
        return path

    return download, get


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. What Regrid advertises

    `inventory/regrid_layers.csv` lists the 40 layers and field groups Regrid documents on
    [support.regrid.com](https://support.regrid.com/llms.txt). Each row has a short quote from the doc page, the
    rating and the public source that would replace it. The rating is our judgement; the `why` column gives the
    reason.

    Regrid publishes a [coverage report](https://docs.google.com/spreadsheets/d/1rvRYv6_ppZlwbmyi2kbzemot6FOEm2EEPdHPyENTQPE/htmlview)
    with the share of parcels that have each field filled, county by county. Its first row is the nationwide fill
    rate. We download it and put that rate next to each layer.
    """)
    return


@app.cell
def _(download):
    regrid_tabs = {
        _name: pd.read_csv(download(f"{REGRID_SHEET}/export?format=csv&gid={_gid}", f"regrid_{_name}.csv"), dtype=str)
        for _name, _gid in REGRID_TABS.items()
    }
    regrid_parcels_tab = regrid_tabs["parcels"]
    nationwide = regrid_parcels_tab.iloc[0]
    assert str(nationwide["county"]).startswith("Nationwide"), "the report's first row should be the nationwide one"

    regrid_layers = pd.read_csv(INVENTORY / "regrid_layers.csv", dtype=str).fillna("")
    assert set(regrid_layers["rating"]) <= set(RATINGS)

    def national_fill(fields: str) -> str:
        return ", ".join(f"{_f} {nationwide[_f + '_pct']}%" for _f in fields.split(";") if _f)

    regrid_layers["national fill"] = regrid_layers["fill_fields"].map(national_fill)
    regrid_counts = regrid_layers["rating"].value_counts().reindex(RATINGS, fill_value=0)
    regrid_layers[["layer", "rating", "national fill", "public_source", "why"]].to_csv(
        OUT / "regrid_layers_rated.csv", index=False
    )
    mo.vstack(
        [
            mo.md(
                f"**{len(regrid_layers)} Regrid layers:** "
                + ", ".join(f"{_n} {_r}" for _r, _n in regrid_counts.items())
            ),
            mo.ui.table(
                regrid_layers[["layer", "rating", "national fill", "public_source", "advertised_refresh"]],
                selection=None,
                page_size=40,
            ),
        ]
    )
    return nationwide, regrid_counts, regrid_layers, regrid_parcels_tab, regrid_tabs


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. What Mireye advertises

    Mireye's catalog is machine-readable without a key: `GET /v1/meta/fields` lists the free point-lookup ("Fetch")
    fields and `GET /v1/enrich/fields` lists everything its paid parcel "Enrich" call returns. Each field names its
    source with a label such as `FEMA_NFHL` or `USDA_SSURGO`. We rate each of those source labels once, in
    `inventory/mireye_sources.csv`, and count fields.
    """)
    return


@app.cell
def _(get):
    _fetch = pd.DataFrame(get(MIREYE_FETCH_FIELDS).json()["fields"])
    _enrich = pd.DataFrame(get(MIREYE_ENRICH_FIELDS).json()["fields"])
    _fetch["endpoint"] = "fetch"
    _enrich["endpoint"] = "enrich"
    # A field in both lists is one field; keep the Fetch copy, which has the layer and source URL.
    mireye_fields = pd.concat([_fetch, _enrich[~_enrich["name"].isin(_fetch["name"])]], ignore_index=True)
    _sources = pd.read_csv(INVENTORY / "mireye_sources.csv")
    _unrated = set(mireye_fields["source"]) - set(_sources["source"])
    assert not _unrated, f"new Mireye source labels to rate in inventory/mireye_sources.csv: {sorted(_unrated)}"
    mireye_fields = mireye_fields.merge(_sources, on="source", how="left")

    mireye_counts = pd.DataFrame(
        {
            "fields": mireye_fields["rating"].value_counts(),
            "source labels": mireye_fields.drop_duplicates("source")["rating"].value_counts(),
        }
    ).reindex(RATINGS, fill_value=0)
    mireye_by_source = (
        mireye_fields.groupby(["source", "rating"], as_index=False)
        .agg(fields=("name", "size"), example=("name", "first"))
        .sort_values("fields", ascending=False)
    )
    mireye_by_source.to_csv(OUT / "mireye_sources_rated.csv", index=False)
    mo.vstack(
        [
            mo.md(
                f"**{len(mireye_fields)} Mireye fields** ({len(_fetch)} Fetch, "
                f"{len(mireye_fields) - len(_fetch)} Enrich-only) from **{mireye_fields['source'].nunique()} source "
                "labels**:"
            ),
            mo.ui.table(mireye_counts.reset_index(names="rating"), selection=None),
            mo.ui.table(mireye_by_source, selection=None, page_size=15),
        ]
    )
    return mireye_counts, mireye_fields


@app.cell
def _(mireye_counts, regrid_counts):
    _fig, _ax = plt.subplots(figsize=(8, 2.6))
    _shares = pd.DataFrame(
        {
            f"Regrid ({regrid_counts.sum()} layers)": regrid_counts / regrid_counts.sum(),
            f"Mireye ({mireye_counts['fields'].sum()} fields)": mireye_counts["fields"] / mireye_counts["fields"].sum(),
        }
    ).T
    _shares.plot.barh(stacked=True, ax=_ax, color=["#55a868", "#dd8452", "#c44e52"], width=0.6)
    _ax.set_xlim(0, 1)
    _ax.set_xlabel("share of advertised layers (Regrid) or fields (Mireye)")
    _ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.35), ncol=3, frameon=False)
    _fig.tight_layout()
    _fig.savefig(OUT / "ratings.png", dpi=120)
    mo.as_html(_fig)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Mireye never names its parcel vendor: the parcel fields are labelled `PARCEL_VENDOR`, and its
    [terms](https://www.mireye.com/terms) forbid using them to "reconstruct a substantial portion of an underlying
    licensed dataset". The field names give it away. We compare them with the column names in Regrid's coverage
    report, where Mireye's `pvd_` prefix ("parcel vendor data") stands for Regrid's own `ll_`.
    """)
    return


@app.cell
def _(mireye_fields, regrid_parcels_tab):
    _regrid_columns = {_c.removesuffix("_pct") for _c in regrid_parcels_tab.columns}
    _vendor = mireye_fields.loc[mireye_fields["source"] == "PARCEL_VENDOR", "name"]
    _as_regrid = _vendor.str.replace(r"^pvd_", "ll_", regex=True)
    vendor_match = _as_regrid.isin(_regrid_columns)
    _unmatched = sorted(_vendor[~vendor_match.to_numpy()])
    mo.md(
        f"**{vendor_match.sum()} of {len(_vendor)}** Mireye `PARCEL_VENDOR` fields have a column of the same name "
        f"in Regrid's coverage report. Not matched: {', '.join(f'`{_n}`' for _n in _unmatched)}. "
        "The rest of Mireye's catalog is federal and open data: its parcel layer is Regrid's, resold."
    )
    return (vendor_match,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Mireye's own field descriptions say where a field is narrower than "any US location". We count the fields whose
    description admits a limit.
    """)
    return


@app.cell
def _(mireye_fields):
    _limits = {
        "lower 48 only (CONUS)": r"\bCONUS\b(?:[- ]only| \(|\.|,)|lower[- ]48",
        "California only": r"California[- ]only",
        "one value per county": r"(?:containing|the) county\b|county[- ](?:level|FIPS)",
        "one value per state": r"state[- ](?:level|average|wide)|containing state",
        "one value per tract": r"(?:containing )?Census tract\b(?! GEOID)",
        "from the nearest monitor or gage": r"nearest (?:AQS )?monitor|nearest USGS gage",
    }
    _description = mireye_fields["description"].fillna("")
    mireye_limits = pd.DataFrame(
        {
            "limit": list(_limits),
            "fields": [int(_description.str.contains(_p, case=False, regex=True).sum()) for _p in _limits.values()],
            "example": [
                next(iter(mireye_fields.loc[_description.str.contains(_p, case=False, regex=True), "name"]), "")
                for _p in _limits.values()
            ],
        }
    )
    mireye_limits.to_csv(OUT / "mireye_limits.csv", index=False)
    mo.ui.table(mireye_limits, selection=None)
    return (mireye_limits,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. Regrid's coverage report against Regrid's claims

    The coverage report gives every county's last refresh date and fill rates. We check them against three claims
    from Regrid's docs:

    - "We target updating over 3,000 counties (92%) on an at least annual basis"
      ([data dictionary](https://support.regrid.com/docs/data-dictionary));
    - "On average 94% of our parcels have been refreshed in the last 12 months"
      ([onboarding FAQ](https://support.regrid.com/docs/parcel-data-onboarding-faq));
    - "100% US coverage" of parcels ([parcel schemas](https://support.regrid.com/docs/regrid-parcel-schemas)).

    Ages are measured from the day this notebook runs. To test "100%", we compare each county's parcel count with
    its 2020 Census housing units (from TIGERweb). Cities with large apartment buildings have far more homes than
    parcels, so we only flag counties under 100,000 housing units with fewer than half as many parcels.
    """)
    return


@app.cell
def _(get, regrid_parcels_tab):
    _rows = regrid_parcels_tab.iloc[1:].dropna(subset=["geoid"]).copy()
    _rows["parcels"] = _rows["parcel_count"].str.replace(",", "").astype(float)
    _rows["last_refresh"] = pd.to_datetime(_rows["last_refresh"])
    # A few counties are split into city rows; one row per county.
    regrid_counties = _rows.groupby("geoid", as_index=False).agg(
        state=("state", "first"),
        county=("county", "first"),
        parcels=("parcels", "sum"),
        last_refresh=("last_refresh", "min"),
    )
    regrid_counties["age_days"] = (pd.Timestamp(TODAY) - regrid_counties["last_refresh"]).dt.days

    _housing = get(
        f"{TIGER}/82/query",
        {"where": "1=1", "outFields": "GEOID,HU100", "returnGeometry": "false", "f": "json"},
    ).json()["features"]
    _housing = pd.DataFrame([_f["attributes"] for _f in _housing]).rename(columns={"GEOID": "geoid"})
    assert len(_housing) > 3000, "TIGERweb should return every county"
    regrid_counties = regrid_counties.merge(_housing, on="geoid", how="left")

    _in_year = regrid_counties["age_days"] <= 365
    freshness = {
        "counties in the report": len(regrid_counties),
        "counties refreshed in the last 365 days, %": round(100 * _in_year.mean(), 1),
        "parcels refreshed in the last 365 days, %": round(
            100 * regrid_counties.loc[_in_year, "parcels"].sum() / regrid_counties["parcels"].sum(), 1
        ),
        "median days since a county's refresh": int(regrid_counties["age_days"].median()),
        "counties not refreshed in 2 years": int((regrid_counties["age_days"] > 730).sum()),
        "oldest refresh": regrid_counties["last_refresh"].min().date().isoformat(),
    }
    partial_counties = regrid_counties[
        (regrid_counties["HU100"] < 100_000) & (regrid_counties["parcels"] < 0.5 * regrid_counties["HU100"])
    ].assign(parcels_per_home=lambda _d: (_d["parcels"] / _d["HU100"]).round(2))
    _no_census = sorted(set(_housing["geoid"]) - set(regrid_counties["geoid"]))
    mo.vstack(
        [
            mo.ui.table(pd.Series(freshness).reset_index(names="measure"), selection=None),
            mo.md(f"**Counties with fewer than half as many parcels as homes** ({len(partial_counties)}):"),
            mo.ui.table(
                partial_counties[["state", "county", "parcels", "HU100", "parcels_per_home", "last_refresh"]],
                selection=None,
            ),
            mo.md(
                f"Census counties and county-equivalents with no row in the report: {len(_no_census)} "
                f"({', '.join(_no_census)}). Connecticut's 8 old counties are expected: Regrid uses its 9 new "
                "planning regions instead. The 60xxx and 69xxx codes are American Samoa and the Northern Mariana Islands."
            ),
        ]
    )
    return freshness, partial_counties, regrid_counties


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Advertised fields that are thin.** An advertised field can still be empty in most counties. For the fields
    behind the layers above, we count the counties where Regrid's own report says the field is 0% filled.
    """)
    return


@app.cell
def _(nationwide, regrid_parcels_tab):
    _fields = [
        "usecode", "zoning", "yearbuilt", "saleprice", "taxamt", "homestead_exemption", "fema_flood_zone",
        "usps_vacancy", "lbcs_activity", "cdl_majority_category", "padus_public_access",
    ]  # fmt: skip
    _counties = regrid_parcels_tab.iloc[1:].dropna(subset=["geoid"])
    thin_fields = pd.DataFrame(
        {
            "field": _fields,
            "nationwide fill %": [int(nationwide[_f + "_pct"]) for _f in _fields],
            "counties at 0%": [int((_counties[_f + "_pct"].astype(int) == 0).sum()) for _f in _fields],
        }
    ).sort_values("nationwide fill %")
    thin_fields.to_csv(OUT / "regrid_thin_fields.csv", index=False)
    mo.ui.table(thin_fields, selection=None)
    return (thin_fields,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Marketing numbers against the report.** The add-on tabs of the same sheet give totals we can set against the
    numbers on Regrid's product pages.
    """)
    return


@app.cell
def _(regrid_tabs):
    def total(tab: str, column: str) -> int:
        return int(str(regrid_tabs[tab].iloc[0][column]).replace(",", ""))

    _zoning = regrid_tabs["zoning"].iloc[1:]
    _zoned_counties = int((_zoning["parcels_in_zone"].str.replace(",", "").astype(float) > 0).sum())
    claims = pd.DataFrame(
        [
            ("buildings", "Matched Building Footprints", "156+ million (onboarding FAQ)", total("buildings", "buildings")),
            ("addresses", "regrid.com/api", "more than 73 million", total("addresses", "address_count")),
            ("addresses", "regrid.com/validated-us-addresses", "more than 180 million", total("addresses", "address_count")),
            ("zoning", "support.regrid.com/docs/standardized-zoning", "more than 2,500 counties", _zoned_counties),
            ("zoning", "support.regrid.com/docs/standardized-zoning", "nearly 14,000 municipalities", total("zoning", "distinct_municipalities")),
            ("zoning", "support.regrid.com/docs/standardized-zoning", "127.9 million parcels", total("zoning", "parcels_in_zone")),
        ],
        columns=["layer", "page", "claim", "coverage report"],
    )  # fmt: skip
    claims.to_csv(OUT / "regrid_claims.csv", index=False)
    mo.ui.table(claims, selection=None)
    return (claims,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Most of these differences are stale pages, not overclaims: the report is newer and bigger than the marketing.
    The address pages disagree with each other by more than 100 million. That is a ready-to-use problem for a buyer,
    not a coverage problem.

    ## 4. Three counties

    Three kinds of county:

    - **Wake County, NC** is urban, and both the county and the state (NC OneMap) publish parcels.
    - **Fergus County, MT** is rural, and covered by Montana's free statewide cadastral program.
    - **Gordon County, GA** has no open parcel portal. The county sends people to a view-only qPublic site, whose
      terms forbid scraping, and sells its GIS file at $300 a layer. Georgia has no statewide parcel layer.

    `inventory/county_sources.csv` lists the public endpoint for each layer, found by hand and checked with curl.
    We count each one live. "Latest date" is the newest date in the layer's date field. That's the best freshness
    signal these services give, because none of them report an edit date.
    """)
    return


@app.cell
def _(get):
    def arcgis_count(url: str, where: str, layers: str, box: tuple[float, float, float, float]) -> int:
        if layers:
            _defs = json.dumps({_l: "1=1" for _l in layers.split(";")})
            _layers = get(f"{url}/query", {"layerDefs": _defs, "returnCountOnly": "true", "f": "json"}).json()
            return sum(_l["count"] for _l in _layers["layers"])
        _params = {"where": where, "returnCountOnly": "true", "f": "json"}
        if where == "envelope":
            _params |= {
                "where": "1=1",
                "geometry": ",".join(map(str, box)),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            }
        _reply = get(f"{url}/query", _params).json()
        if "count" not in _reply:
            raise RuntimeError(f"{url}: {_reply}")
        return int(_reply["count"])

    def arcgis_max_date(url: str, where: str, field: str) -> str:
        """Newest date in field, ignoring the 9999-12-31 placeholders some counties use."""
        _stats = json.dumps([{"statisticType": "max", "onStatisticField": field, "outStatisticFieldName": "m"}])
        _where = f"({where}) AND {field} < DATE '2100-01-01'"
        _reply = get(f"{url}/query", {"where": _where, "outStatistics": _stats, "f": "json"}).json()
        _value = _reply["features"][0]["attributes"]["m"]
        return datetime.fromtimestamp(_value / 1000, UTC).date().isoformat() if _value else ""

    return arcgis_count, arcgis_max_date


@app.cell
def _(get):
    county_shapes = {}
    for _name, _geoid in COUNTIES.items():
        _reply = get(
            f"{TIGER}/82/query",
            {"where": f"GEOID='{_geoid}'", "outFields": "GEOID,HU100", "outSR": "4326", "f": "geojson"},
        ).json()
        assert len(_reply["features"]) == 1, f"TIGERweb should return one county for {_geoid}"
        _feature = _reply["features"][0]
        _rings = [_p for _ring in _feature["geometry"]["coordinates"] for _p in _ring]
        _points = _rings if isinstance(_rings[0][0], float) else [_p for _ring in _rings for _p in _ring]
        _xs, _ys = [_p[0] for _p in _points], [_p[1] for _p in _points]
        county_shapes[_name] = {
            "geoid": _geoid,
            "housing_units": _feature["properties"]["HU100"],
            "geometry": json.dumps(_feature["geometry"]),
            "box": (min(_xs), min(_ys), max(_xs), max(_ys)),
        }
    return (county_shapes,)


@app.cell
def _(arcgis_count, arcgis_max_date, county_shapes):
    _sources = pd.read_csv(INVENTORY / "county_sources.csv", dtype=str).fillna("")
    _results = []
    for _row in _sources.itertuples():
        _started = time.perf_counter()
        _count, _latest, _error = None, "", ""
        if _row.url:
            try:
                _count = arcgis_count(_row.url, _row.where, _row.layers, county_shapes[_row.county]["box"])
                if _row.date_field:
                    _latest = arcgis_max_date(_row.url, _row.where, _row.date_field)
            except (requests.RequestException, RuntimeError, KeyError) as _e:
                _error = f"failed: {type(_e).__name__}"
        _results.append(
            {
                "county": _row.county,
                "layer": _row.layer,
                "source": _row.source,
                "public count": _count,
                "latest date": _latest,
                "seconds": round(time.perf_counter() - _started, 1),
                "note": _error or _row.note,
            }
        )
    public_counts = pd.DataFrame(_results)
    public_counts.to_csv(OUT / "county_public_counts.csv", index=False)
    mo.ui.table(public_counts, selection=None, page_size=30)
    return (public_counts,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Buildings and addresses from Overture.** The open building layer for any county is
    [Overture Maps](https://docs.overturemaps.org/), which merges OpenStreetMap, Microsoft and Google footprints and
    others. Its address theme merges county and state address points, including the USDOT National Address
    Database. We count the features inside each county outline, split by the dataset each came from. This reads
    Overture's GeoParquet on S3 with DuckDB, a few minutes per county, and caches the counts in `data/`.
    """)
    return


@app.cell
def _(county_shapes):
    _cache = DATA / f"overture_counts_{OVERTURE_RELEASE}.csv"
    if _cache.exists():
        overture_counts = pd.read_csv(_cache, dtype={"dataset": str})
    else:
        _con = duckdb.connect()
        _con.sql("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
        # An empty key makes DuckDB read the public bucket anonymously instead of using any AWS credentials around.
        _con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
        _frames = []
        for _name, _shape in county_shapes.items():
            _xmin, _ymin, _xmax, _ymax = _shape["box"]
            for _theme, _type in [("buildings", "building"), ("addresses", "address")]:
                _started = time.perf_counter()
                _frame = _con.sql(
                    f"""
                    SELECT sources[1].dataset AS dataset, count(*) AS features
                    FROM read_parquet('{OVERTURE}/theme={_theme}/type={_type}/*', hive_partitioning = 1)
                    WHERE bbox.xmin >= {_xmin} AND bbox.xmax <= {_xmax}
                      AND bbox.ymin >= {_ymin} AND bbox.ymax <= {_ymax}
                      AND ST_Intersects(geometry, ST_GeomFromGeoJSON($shape))
                    GROUP BY 1
                    """,
                    params={"shape": _shape["geometry"]},
                ).df()
                _frame["county"], _frame["layer"] = _name, _theme
                _frames.append(_frame)
                print(
                    f"overture {_theme} {_name}: {_frame['features'].sum():,} in {time.perf_counter() - _started:.0f} s"
                )
        overture_counts = pd.concat(_frames, ignore_index=True)
        overture_counts.to_csv(_cache, index=False)
    mo.ui.table(
        overture_counts.pivot_table(index=["county", "layer"], columns="dataset", values="features", fill_value=0),
        selection=None,
    )
    return (overture_counts,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Side by side.** For each county and layer, the largest public count against what Regrid's coverage report says
    it has there. Regrid's figures are parcels, matched buildings, matched addresses and parcels inside a standardized
    zone. Public zoning counts zoning polygons (Wake) or city-zoned parcels (Gordon), so it shows whether a public
    source exists, not a like-for-like total.
    """)
    return


@app.cell
def _(county_shapes, overture_counts, public_counts, regrid_tabs):
    def regrid_value(tab: str, geoid_column: str, geoid: str, column: str) -> str:
        _rows = regrid_tabs[tab][regrid_tabs[tab][geoid_column] == geoid]
        return ", ".join(sorted(set(_rows[column].dropna().astype(str)))) or "none"

    _overture = overture_counts.groupby(["county", "layer"])["features"].sum()
    _rows = []
    for _name, _shape in county_shapes.items():
        _geoid = _shape["geoid"]
        _public = public_counts[public_counts["county"] == _name].groupby("layer")["public count"].max()
        _rows += [
            (_name, "parcels", _public.get("parcels"), regrid_value("parcels", "geoid", _geoid, "parcel_count"),
             "refreshed " + regrid_value("parcels", "geoid", _geoid, "last_refresh")),
            (_name, "buildings", _overture.get((_name, "buildings")), regrid_value("buildings", "ed_geoid", _geoid, "buildings"),
             "public = Overture"),
            (_name, "addresses", max(_public.get("addresses") or 0, _overture.get((_name, "addresses"), 0)),
             regrid_value("addresses", "geoid", _geoid, "address_count"), "public = larger of state/county and Overture"),
            (_name, "zoning", _public.get("zoning"), regrid_value("zoning", "geoid", _geoid, "parcels_in_zone"),
             "Regrid zoning data date " + regrid_value("zoning", "geoid", _geoid, "last_date_modified")),
            (_name, "flood zones", _public.get("flood zones"), regrid_value("parcels", "geoid", _geoid, "fema_flood_zone_pct") + "% of parcels",
             "FIRM latest effective " + str(public_counts.query("county == @_name and layer == 'FIRM panels'")["latest date"].max())),
            (_name, "housing units (2020)", _shape["housing_units"], "", "Census, for scale"),
        ]  # fmt: skip
    side_by_side = pd.DataFrame(_rows, columns=["county", "layer", "public", "Regrid", "note"])
    side_by_side.to_csv(OUT / "county_side_by_side.csv", index=False)
    mo.ui.table(side_by_side, selection=None, page_size=20)
    return (side_by_side,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Which parcel fields the public layers carry.** For each public parcel layer we count the parcels where a field
    is filled (non-empty text, a number above 0, a real date). We set that against Regrid's fill rate for the same
    field in the same county. Owner fields are counted, never read.
    """)
    return


@app.cell
def _(get, regrid_tabs):
    _regrid_field = {
        "owner": "owner", "address": "address", "value": "parval", "sale_price": "saleprice",
        "sale_date": "saledate", "land_use": "usecode", "year_built": "yearbuilt",
    }  # fmt: skip
    _sources = pd.read_csv(INVENTORY / "county_sources.csv", dtype=str).fillna("")
    _sources = _sources[(_sources["layer"] == "parcels") & (_sources["url"] != "")]
    _rows = []
    for _row in _sources.itertuples():
        _types = {_f["name"]: _f["type"] for _f in get(_row.url, {"f": "json"}).json()["fields"]}
        _total = get(f"{_row.url}/query", {"where": _row.where, "returnCountOnly": "true", "f": "json"}).json()["count"]
        _mapping = dict(_pair.split(":") for _pair in _row.fields.split(";"))
        _regrid = regrid_tabs["parcels"][regrid_tabs["parcels"]["geoid"] == COUNTIES[_row.county]].iloc[0]
        for _group, _column in _regrid_field.items():
            _field = _mapping.get(_group, "")
            _filled = None
            if _field:
                _kind = _types[_field]
                _test = (
                    f"{_field} > 0" if _kind in ("esriFieldTypeDouble", "esriFieldTypeInteger", "esriFieldTypeSmallInteger")
                    else f"{_field} < DATE '2100-01-01'" if _kind == "esriFieldTypeDate"
                    else f"{_field} <> ''"
                )  # fmt: skip
                _reply = get(
                    f"{_row.url}/query",
                    {
                        "where": f"({_row.where}) AND {_field} IS NOT NULL AND {_test}",
                        "returnCountOnly": "true",
                        "f": "json",
                    },
                ).json()
                _filled = round(100 * _reply["count"] / _total)
            _rows.append(
                {"county": _row.county, "source": _row.source, "field group": _group,
                 "public fill %": _filled, "Regrid fill %": int(_regrid[_column + "_pct"])}
            )  # fmt: skip
    field_fill = pd.DataFrame(_rows)
    field_fill.to_csv(OUT / "county_field_fill.csv", index=False)
    mo.ui.table(
        field_fill.pivot_table(
            index="field group", columns=["county", "source"], values=["public fill %"], aggfunc="first"
        )
        .join(
            field_fill.drop_duplicates(["county", "field group"])
            .pivot(index="field group", columns="county", values="Regrid fill %")
            .add_prefix("Regrid ")
        )
        .reset_index(),
        selection=None,
    )
    return (field_fill,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. What it adds up to
    """)
    return


@app.cell
def _(
    freshness,
    mireye_counts,
    mireye_fields,
    partial_counties,
    public_counts,
    regrid_counts,
    regrid_layers,
    side_by_side,
    thin_fields,
    vendor_match,
):
    _vendor_fields = int((mireye_fields["source"] == "PARCEL_VENDOR").sum())
    _gordon = side_by_side[side_by_side["county"] == "Gordon GA"].set_index("layer")
    _fergus_zoning = side_by_side.query("county == 'Fergus MT' and layer == 'zoning'").iloc[0]
    _firms = public_counts[public_counts["layer"] == "FIRM panels"].set_index("county")["latest date"]
    _thin = thin_fields.set_index("field")
    summary = {
        "Regrid layers": len(regrid_layers),
        **{f"Regrid {_r}": int(_n) for _r, _n in regrid_counts.items()},
        "Mireye fields": len(mireye_fields),
        **{f"Mireye fields {_r}": int(_n) for _r, _n in mireye_counts["fields"].items()},
        "Mireye PARCEL_VENDOR fields with a Regrid column name": f"{int(vendor_match.sum())} of {_vendor_fields}",
        **freshness,
        "small counties with < half as many parcels as homes": len(partial_counties),
    }
    pd.Series(summary).to_csv(OUT / "summary.csv", header=["value"])
    _fergus_regrid_zoning = _fergus_zoning["Regrid"]
    mo.md(
        f"""
    **The catalog.** Of Regrid's {len(regrid_layers)} layers, {regrid_counts["public and easy"]} are public and easy,
    {regrid_counts["public but scattered"]} are public but scattered and {regrid_counts["proprietary"]} are
    proprietary. The scattered ones are the county record itself: boundaries, owners, values, sales, land use,
    building attributes. They are public, but only county by county. The proprietary ones are bought from partners
    (ATTOM deeds, Zoneomics zoning, EarthDefine buildings, Ageon addresses, USPS validation, Esri demographics,
    NatureServe) or are Regrid's own keys and crosswalks.

    Of Mireye's {len(mireye_fields)} fields, {mireye_counts.loc["public and easy", "fields"]} come from public
    national datasets, {mireye_counts.loc["public but scattered", "fields"]} clip public layers to a parcel, and
    {mireye_counts.loc["proprietary", "fields"]} are licensed parcel fields. {int(vendor_match.sum())} of those
    {_vendor_fields} parcel fields carry Regrid's column names.

    **Regrid's freshness.** {freshness["counties refreshed in the last 365 days, %"]}% of counties and
    {freshness["parcels refreshed in the last 365 days, %"]}% of parcels were refreshed in the last year, against a
    92% county target and a 94% parcel claim. {freshness["counties not refreshed in 2 years"]} counties are over two
    years old. Some advertised fields are close to empty: tax amount is {_thin.loc["taxamt", "nationwide fill %"]}%
    filled nationwide and 0% in {_thin.loc["taxamt", "counties at 0%"]} counties; FEMA flood zone is 0% in
    {_thin.loc["fema_flood_zone", "counties at 0%"]} counties, though the layer is free.

    **The counties.** Wake County publishes everything Regrid sells there except the licensed add-ons. Fergus
    County's parcels and addresses are public through Montana, but we found no machine-readable zoning; Regrid
    reports {_fergus_regrid_zoning} parcels in a standardized zone there. Gordon County has no open parcels or
    addresses: Regrid has {_gordon.loc["parcels", "Regrid"]} parcels and
    {_gordon.loc["addresses", "Regrid"]} addresses there, which an open rebuild can't match. The FEMA maps are old in
    two of the three: the latest FIRM panel dates are {", ".join(f"{_c} {_d}" for _c, _d in _firms.items())}.
    """
    )
    return (summary,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this doesn't show, and what didn't work

    - **Ratings are judgement.** The line between "public and easy" and "scattered" is how much work it takes, and
      each row says why. A statewide parcel program (North Carolina, Montana) turns a scattered layer into an easy
      one for that state only.
    - **Three counties are three examples, not a sample.** The national figures come from Regrid's own report.
    - **Counts aren't quality.** We didn't check that a public parcel matches Regrid's boundary or that a value is
      the same. Regrid's fill rates and ours count slightly different things ("filled" vs "valid").
    - **Freshness is a proxy.** No service reports an edit date, so we use the newest date field (sale date, update
      date). Montana's cadastral has no date field at all; its metadata says it's published monthly.
    - **What failed.** `api.census.gov` now needs a key, so housing units come from TIGERweb. The National Address
      Database times out on any attribute filter, so we query it by bounding box, which also counts neighbours.
      Wake's own address service has no date field. Old Montana `gisservicemt.gov` URLs return an HTML "moved" page.
    - **Not tested:** Mireye's values. Its Fetch call needs a key from a sign-up, so we rated its catalog without
      calling it. Regrid's sample files are behind a store page; we used only its public coverage report.
    - **The Gordon County parcel layer** on a City of Calhoun utility server is public but unlicensed and has
      geometry and street names only. We count it as a finding, not as a source.
    """)
    return


@app.cell
def _():
    run_seconds = time.perf_counter() - RUN_STARTED
    print(f"run time: {run_seconds:.0f} s")
    return (run_seconds,)


if __name__ == "__main__":
    app.run()
