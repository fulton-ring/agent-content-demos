import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import logging
    import os
    import re
    import time
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import requests

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("psps")
    here = Path(mo.notebook_dir() or ".")
    cache = Path(os.environ.get("PSPS_CACHE", Path.home() / ".cache" / "pge-psps-hifld-facilities"))
    results = here / "results"
    for _d in (cache, results):
        _d.mkdir(parents=True, exist_ok=True)
    started = time.time()
    session = requests.Session()
    # PG&E's site refuses requests without a browser-like user agent.
    session.headers["User-Agent"] = "Mozilla/5.0 (research script)"

    def fetch(url: str, name: str) -> Path:
        """Download a file once into the cache, with a bounded number of retries."""
        path = cache / name
        if path.exists():
            return path
        for attempt in range(5):
            try:
                response = session.get(url, timeout=600)
                response.raise_for_status()
                path.write_bytes(response.content)
                log.info("downloaded %s (%d bytes)", url, len(response.content))
                return path
            except requests.RequestException as error:
                log.warning("%s attempt %d: %s", url, attempt + 1, error)
                time.sleep(2**attempt)
        raise RuntimeError(f"{url} failed 5 times")

    return fetch, gpd, json, mo, pd, plt, re, results, session, started, time


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # How many of PG&E's 1,864 shut-off critical facilities can HIFLD Next find?

    From October 14 to 17, 2026, PG&E cut power to 85,863 customers in a Public Safety Power
    Shutoff (PSPS). In its report to the CPUC it says 1,864 of those customers were **critical
    facilities and infrastructure (CFI)**. The utility holds that list. An emergency manager
    doesn't.

    So we try the obvious public method: take the polygons of de-energized areas that PG&E
    posts after each event, put HIFLD Next's facility layers inside them, and count, layer by
    layer. Then we set the result against PG&E's own numbers and against the 11 sites PG&E
    sent temporary generators to. We repeat it for two smaller 2026 shutoffs (July 15 and
    October 23) to see whether the gap holds.

    Issue [#278](https://github.com/fulton-ring/agent-content-demos/issues/278),
    [proposal card](https://app.notion.com/p/418cc69045cb8143bcd0fe547c462ee1).
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## PG&E's files

    PG&E posts three files per event on its
    [PSPS page](https://www.pge.com/en/outages-and-safety/safety/community-wildfire-safety-program/public-safety-power-shutoffs.html):
    the report PDF, an Excel workbook with every table and appendix, and a zipped file
    geodatabase (`<date>-pge-psps-event.gdb.zip`). The geodatabase has a
    `DeEnergizedAreas` layer, one polygon per "time and place" (a group of circuits shut off
    together), with customer counts. We download all three at run time.
    """)
    return


@app.cell
def _(fetch, gpd):
    pge_base = (
        "https://www.pge.com/assets/pge/docs/outages-and-safety/outage-preparedness-and-support"
    )
    events = {"2026-10-14": "10-14-2026", "2026-07-15": "07-15-2026", "2026-10-23": "10-23-2026"}
    workbooks = {
        e: fetch(f"{pge_base}/{d}-psps-post-event-report-tables.xlsx", f"{d}-tables.xlsx")
        for e, d in events.items()
    }
    footprints = {}
    for _event, _d in events.items():
        _gdb = fetch(f"{pge_base}/{_d}-pge-psps-event.gdb.zip", f"{_d}.gdb.zip")
        _layer = f"PSPS_{_d.replace('-', '')}DeEnergizedAreas"
        _areas = gpd.read_file(_gdb, layer=_layer).to_crs(3310)  # California Albers, metres
        _areas["geometry"] = _areas.make_valid()
        footprints[_event] = _areas
    oct14 = footprints["2026-10-14"]
    return events, footprints, oct14, workbooks


@app.cell
def _(footprints, mo, pd):
    _rows = [
        {
            "event": e,
            "polygons": len(a),
            "customers in polygons": int(a["Total_Customers"].sum()),
            "area km²": round(a.union_all().area / 1e6),
        }
        for e, a in footprints.items()
    ]
    mo.ui.table(pd.DataFrame(_rows), selection=None)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **PG&E's own counts.** Table 1 of each workbook gives the number of CFI customers
    de-energized. Table 15 of the October 14 workbook lists the CFI customers that got
    temporary generators. The report's Appendix F defines CFI with the CPUC's interim list of
    sectors (below). It gives only the total, not a count per sector, and neither does PG&E's
    2025 post-season data workbook, so we can compare by sector only against what each
    sector covers.
    """)
    return


@app.cell
def _(pd, workbooks):
    def table(event: str, sheet: str) -> pd.DataFrame:
        """A workbook table: after blank rows go, row 0 is the title and row 1 the header."""
        raw = pd.read_excel(workbooks[event], sheet_name=sheet, header=None).iloc[:, 1:]
        raw = raw.dropna(how="all")
        header = raw.index[1]  # row 0 is the table title
        frame = raw.loc[header + 1 :].copy()
        frame.columns = [str(c).replace("\n", " ").strip() for c in raw.loc[header]]
        return frame

    pge_cfi = {}
    for _event in workbooks:
        _t1 = table(_event, "Table 1")
        _col = next(c for c in _t1.columns if c.startswith("CFI"))
        _value = _t1[_col].iloc[0]
        assert str(_value).isdigit(), f"unexpected CFI cell {_value!r} for {_event}"
        pge_cfi[_event] = int(_value)

    _t15 = table("2026-10-14", "Table 15")
    _t15 = _t15[_t15["Site Type"].notna() & ~_t15["County"].astype(str).str.startswith("*")]
    generators = (
        _t15.assign(County=_t15["County"].str.rstrip("*").str.strip())
        .groupby(["County", "Site Type"], as_index=False)
        .agg(generators=("Site Type", "size"), reason=("Reason Deployed", "first"))
        .rename(columns={"County": "county", "Site Type": "site"})
    )
    generators["reason"] = generators["reason"].str.strip()
    assert len(generators) == 11, f"Table 15 should list 11 sites, found {len(generators)}"
    pge_cfi, generators
    return generators, pge_cfi


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## HIFLD Next's layers, by CFI sector

    The CPUC's interim CFI list (quoted in the report's Appendix F) names seven sectors. For
    each we take every HIFLD Next point layer that matches, found through the portal's API
    (dataset, then its newest version, then the GeoParquet file). We keep only records marked
    open or active where the layer has a status field, so closed hospitals, terminated
    wastewater permits and retired plants drop out.

    Two sectors have obvious holes. HIFLD Next has **no drinking-water layer** (no water
    systems, wells, pumps or tanks), and its **cellular towers** layer is the FCC's cellular
    licence locations only, about 24,000 nationally, not the carriers' full site list or their
    central offices and switches. Assisted living homes are kept apart from nursing homes
    because the CPUC list names skilled nursing and nursing homes only.
    """)
    return


@app.cell
def _(fetch, gpd, pd, re, session):
    api = "https://hifld.publicenvirodata.org/api/collections/hifld/datasets"
    # (HIFLD Next dataset, label, CPUC sector, rule for an open/active record)
    layers = [
        ("hospitals-3", "Hospitals", "Healthcare", lambda d: d["STATUS"] == "OPEN"),
        (
            "nursing-homes",
            "Nursing homes",
            "Healthcare",
            lambda d: (d["STATUS"] == "OPEN") & (d["TYPE"] == "NURSING HOME"),
        ),
        (
            "nursing-homes",
            "Assisted living (not on CPUC list)",
            "Not CFI",
            lambda d: (d["STATUS"] == "OPEN") & (d["TYPE"] != "NURSING HOME"),
        ),
        ("dialysis-centers", "Dialysis centers", "Healthcare", None),
        ("veterans-health-administration-medical-facilities", "VA facilities", "Healthcare", None),
        (
            "fire-and-emergency-medical-service-ems-stations",
            "Fire and EMS stations",
            "Emergency services",
            None,
        ),
        (
            "local-law-enforcement-locations",
            "Law enforcement",
            "Emergency services",
            lambda d: d["STATUS"] == "OPEN",
        ),
        ("local-emergency-operations-center-eoc", "Local EOCs", "Emergency services", None),
        ("state-emergency-operations-centers-eoc", "State EOCs", "Emergency services", None),
        # NCES status 1 open, 3 new, 4 added, 5 changed agency, 8 reopened.
        (
            "public-schools",
            "Public schools",
            "Government",
            lambda d: d["STATUS"].isin(["1", "3", "4", "5", "8"]),
        ),
        ("private-schools", "Private schools", "Government", None),
        ("colleges-and-universities", "Colleges", "Government", lambda d: d["STATUS"] == "A"),
        ("prison-boundaries-1", "Jails and prisons", "Government", lambda d: d["STATUS"] == "OPEN"),
        # PG&E's own plants are its assets, not CFI customers.
        (
            "power-plants-1",
            "Power plants (not PG&E's)",
            "Energy",
            lambda d: (d["STATUS"] == "OP") & ~d["OPERATOR"].str.startswith("PACIFIC GAS"),
        ),
        (
            "power-plants-1",
            "PG&E's own power plants",
            "Not CFI",
            lambda d: (d["STATUS"] == "OP") & d["OPERATOR"].str.startswith("PACIFIC GAS"),
        ),
        (
            "icis-wastewater-treatment-plants",
            "Wastewater plants",
            "Water and wastewater",
            lambda d: d["CWP_PERMIT_STATUS_CODE"].isin(["EFF", "ADC"]),
        ),
        ("cellular-towers", "Cellular towers", "Communications", None),
        (
            "epa-emergency-response-rmp-facilities",
            "EPA RMP chemical facilities",
            "Chemical",
            lambda d: d["ACTIVE_STATUS"] == "ACTIVE",
        ),
    ]

    def newest_parquet(dataset: str) -> tuple[str, str]:
        """Newest version and GeoParquet URL of a HIFLD Next dataset, through the portal API."""
        response = session.get(f"{api}/{dataset}", timeout=60)
        response.raise_for_status()
        child = next(link["href"] for link in response.json()["links"] if link["rel"] == "child")
        versions = session.get(child, timeout=60).json()["links"]
        hrefs = {link["href"] for link in versions if link["rel"] == "child"}
        assert hrefs, f"no versions for {dataset}"

        def version(href: str) -> tuple[int, ...]:
            found = re.search(r"/v(\d+)\.(\d+)\.(\d+)/", href)
            assert found, href
            return tuple(int(n) for n in found.groups())

        newest = max(hrefs, key=version)
        assets = session.get(newest, timeout=60).json()["assets"]
        url = next(a["href"] for k, a in assets.items() if k.startswith("geoparquet"))
        return "v" + ".".join(map(str, version(newest))), url

    _frames, _versions = [], []
    hospitals_all = None
    for _dataset, _label, _sector, _rule in layers:
        _v, _url = newest_parquet(_dataset)
        _g = gpd.read_parquet(fetch(_url, f"{_dataset}-{_v}.parquet")).to_crs(3310)
        if _dataset == "hospitals-3":
            hospitals_all = _g
        _kept = _g[_rule(_g)] if _rule else _g
        _name = next(
            c for c in ("NAME", "Name", "name", "CWP_NAME", "PRIMARY_NAME", "Licensee") if c in _g
        )
        _frames.append(
            gpd.GeoDataFrame(
                {
                    "layer": _label,
                    "sector": _sector,
                    "name": _kept[_name].astype(str).str.strip(),
                    "district_id": _kept.get("DISTRICTID"),
                },
                geometry=_kept.geometry,
                crs=3310,
            )
        )
        _versions.append(
            {
                "layer": _label,
                "dataset": _dataset,
                "version": _v,
                "records": len(_g),
                "kept": len(_kept),
            }
        )
    facilities = pd.concat(_frames, ignore_index=True)
    hifld_versions = pd.DataFrame(_versions)
    hifld_versions
    return facilities, hifld_versions, hospitals_all


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Count what falls inside the October 14 polygons

    A facility counts if its point (or, for jails and prisons, its outline) touches a
    de-energized polygon. We work in California Albers so distances are in metres.
    """)
    return


@app.cell
def _(facilities, footprints, gpd, pd):
    def inside(event: str) -> gpd.GeoDataFrame:
        """HIFLD Next facilities that touch one event's de-energized polygons."""
        areas = footprints[event][["Time_Place", "geometry"]]
        hits = gpd.sjoin(facilities, areas, predicate="intersects", how="inner")
        return hits[~hits.index.duplicated()].drop(columns="index_right")

    inside_oct14 = inside("2026-10-14")
    by_layer = (
        inside_oct14.groupby(["sector", "layer"], sort=False).size().rename("inside").reset_index()
    )
    by_layer = (
        facilities[["sector", "layer"]]
        .drop_duplicates()
        .merge(by_layer, how="left", on=["sector", "layer"])
        .fillna({"inside": 0})
        .astype({"inside": int})
    )
    pd.DataFrame(by_layer)
    return by_layer, inside, inside_oct14


@app.cell
def _(by_layer, mo, pd, pge_cfi):
    _cfi = by_layer[by_layer["sector"] != "Not CFI"]
    hifld_total_oct14 = int(_cfi["inside"].sum())
    _sectors = _cfi.groupby("sector", sort=False)["inside"].sum()
    _missing = {
        "Healthcare": "blood banks, clinics, hospice, public health departments",
        "Emergency services": "fire stations missing from the national layer, dispatch centres",
        "Government": "school district offices and support sites",
        "Energy": "other utilities' substations, pumping and gas facilities",
        "Water and wastewater": "every drinking-water site: wells, pumps, tanks, treatment",
        "Communications": "most cell sites, central offices, head ends, remote terminals",
        "Chemical": "chemical sites not under EPA's Risk Management Program",
    }
    sector_table = pd.DataFrame(
        {"HIFLD Next inside": _sectors, "Not in any HIFLD Next layer": pd.Series(_missing)}
    ).rename_axis("CPUC CFI sector")
    mo.vstack(
        [
            mo.md(
                f"**HIFLD Next finds {hifld_total_oct14} CFI-type facilities inside the October "
                f"14 polygons, against PG&E's {pge_cfi['2026-10-14']:,} CFI customers: "
                f"{hifld_total_oct14 / pge_cfi['2026-10-14']:.0%}.** PG&E counts accounts "
                "(service points), so one site with several meters counts more than once on its "
                "side; we count points."
            ),
            mo.ui.table(sector_table.reset_index(), selection=None),
        ]
    )
    return hifld_total_oct14, sector_table


@app.cell
def _(gpd, inside_oct14, mo):
    _cfi = inside_oct14[inside_oct14["sector"] != "Not CFI"]
    _blobs = gpd.GeoSeries([_cfi.buffer(50).union_all()], crs=3310).explode(index_parts=False)
    sites_oct14 = len(_blobs)
    _plants = _cfi[_cfi["layer"] == "Power plants (not PG&E's)"]
    mo.md(
        f"Points are not sites either. Merging every CFI-type point within 100 m of another "
        f"into one site leaves **{sites_oct14} sites** from {len(_cfi)} points: some fire stations "
        "appear twice under two agencies' names, and some schools share a campus. Of the "
        f"{len(_plants)} power plants, "
        f"{int(_plants['name'].str.contains('solar', case=False).sum())} have 'solar' in the name."
    )
    return (sites_oct14,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Hospitals

    The card expected the public layers to find most hospitals. Here is every HIFLD Next
    hospital record, open or closed, inside the polygons.
    """)
    return


@app.cell
def _(gpd, hospitals_all, oct14):
    hospitals_oct14 = gpd.sjoin(
        hospitals_all, oct14[["Time_Place", "geometry"]], predicate="intersects"
    )[["NAME", "CITY", "COUNTY", "STATUS", "TYPE", "BEDS", "SOURCEDATE", "Time_Place"]]
    hospitals_oct14
    return (hospitals_oct14,)


@app.cell(hide_code=True)
def _(hospitals_oct14, mo):
    _open = hospitals_oct14[hospitals_oct14["STATUS"] == "OPEN"]
    _closed = hospitals_oct14[hospitals_oct14["STATUS"] != "OPEN"]
    mo.md(
        f"{len(hospitals_oct14)} hospital records fall inside: {len(_open)} open "
        f"({', '.join(_open['NAME'].str.title())}) and {len(_closed)} marked closed "
        f"({', '.join(_closed['NAME'].str.title()) or 'none'}). The PG&E report doesn't say "
        "how many hospitals it shut off, so we can't give a share. What it does show is that "
        "the footprint held very few hospitals: most of the 1,864 are something else."
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## The 11 sites that got generators (Table 15)

    These are the CFI PG&E judged most at risk, so they are the fairest test. Table 15 names a
    site type, not an address. For a school district we count it found if HIFLD Next has at
    least one open public school of that district inside the polygons (matched on the NCES
    district ID through HIFLD Next's school district layers). For a named school we look for
    the name among HIFLD Next schools, and for a water system in every layer. Where nothing
    matches inside, we say how far outside the polygons the nearest match is.
    """)
    return


@app.cell
def _(facilities, fetch, generators, oct14, pd, re):
    _base = "https://hifld.publicenvirodata.org/storage/hifld/{0}/{0}/v1.0.0/geoparquet/{0}.parquet"
    _districts = pd.concat(
        [
            pd.read_parquet(
                fetch(_base.format(k), f"{k}-v1.0.0.parquet"), columns=["NAME", "GEOID"]
            )
            for k in ("unified-school-districts", "elementary-school-districts")
        ]
    )
    _districts = _districts[_districts["GEOID"].str.startswith("06")]  # California
    _footprint = oct14.union_all()
    _x0, _y0, _x1, _y1 = oct14.total_bounds
    _nearby = facilities.cx[_x0 - 50_000 : _x1 + 50_000, _y0 - 50_000 : _y1 + 50_000].copy()
    _nearby["metres_outside"] = _nearby.distance(_footprint).round()

    def words(text: str) -> set[str]:
        """Lower-case name words without filler, for loose name matching."""
        filler = {"school", "district", "unified", "union", "co", "the", "of", "county", "st"}
        return set(re.findall(r"[a-z]+", text.lower())) - filler

    _rows = []
    for _site in generators.itertuples():
        _type = str(_site.site)
        _key = words(_type)
        _is_school = "school" in _type.lower() or "unified" in _type.lower()
        _pool = (
            _nearby[_nearby["layer"].isin(["Public schools", "Private schools"])]
            if _is_school
            else _nearby
        )
        _ids = _districts[_districts["NAME"].map(lambda n, k=_key: k <= words(n))]["GEOID"]
        if _is_school and ("district" in _type.lower() or "unified" in _type.lower()):
            _candidates = _pool[_pool["district_id"].isin(_ids)]
            _how = f"NCES district {', '.join(_ids)}"
        else:
            _candidates = _pool[_pool["name"].map(lambda n, k=_key: k <= words(n))]
            _how = "name"
        _in = _candidates[_candidates["metres_outside"] == 0]
        _rows.append(
            {
                "county": _site.county,
                "site": _type,
                "reason": _site.reason,
                "matched by": _how,
                "HIFLD Next record inside": "; ".join(_in["name"].str.title()) or "none",
                "nearest candidate outside (m)": _candidates["metres_outside"].min()
                if len(_in) == 0 and len(_candidates)
                else None,
            }
        )
    generator_match = pd.DataFrame(_rows)
    generator_match
    return (generator_match,)


@app.cell(hide_code=True)
def _(generator_match, mo):
    _found = int((generator_match["HIFLD Next record inside"] != "none").sum())
    mo.md(
        f"**HIFLD Next has a record inside the polygons for {_found} of the 11 generator sites.** "
        "Read the school district rows loosely: a district with a school inside is not proof the "
        "generator went to that school. The water systems have no HIFLD Next layer to be in."
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## How much rides on the polygon edges?

    PG&E's polygons approximate the area each circuit serves, so a facility a few metres
    inside an edge may be on a circuit that stayed on, and one just outside may have gone
    dark. We count CFI-type facilities within 100 m and 500 m of an edge, on either side.
    """)
    return


@app.cell
def _(facilities, gpd, oct14, pd):
    _edges = gpd.GeoDataFrame(geometry=oct14.boundary.explode(index_parts=False), crs=3310)
    _cfi = facilities[facilities["sector"] != "Not CFI"]
    _near = gpd.sjoin_nearest(_cfi, _edges, max_distance=500, distance_col="edge_m")
    _near = _near[~_near.index.duplicated()]
    _inside = _near.intersects(oct14.union_all())
    edge = pd.DataFrame(
        [
            {
                "within": f"{m} m of an edge",
                "inside, near edge": int(((_near["edge_m"] <= m) & _inside).sum()),
                "outside, near edge": int(((_near["edge_m"] <= m) & ~_inside).sum()),
            }
            for m in (100, 500)
        ]
    )
    edge
    return (edge,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Two smaller shutoffs

    The same count for July 15, 2026 (5,186 customers) and October 23, 2026 (364 customers).
    """)
    return


@app.cell
def _(footprints, inside, pd, pge_cfi):
    _rows = []
    for _event, _areas in footprints.items():
        _hits = inside(_event)
        _cfi = _hits[_hits["sector"] != "Not CFI"]
        _row = {
            "event": _event,
            "customers": int(_areas["Total_Customers"].sum()),
            "PG&E CFI": pge_cfi[_event],
            "HIFLD Next CFI-type": len(_cfi),
            "share": round(len(_cfi) / pge_cfi[_event], 3),
        }
        _row.update(_cfi["sector"].value_counts().to_dict())
        _rows.append(_row)
    event_table = pd.DataFrame(_rows).fillna(0)
    event_table
    return (event_table,)


@app.cell
def _(facilities, oct14, plt, results):
    _fig, _ax = plt.subplots(figsize=(8, 8))
    oct14.plot(ax=_ax, color="#f2c14e", edgecolor="#9a7b1c", linewidth=0.3)
    _xmin, _ymin, _xmax, _ymax = oct14.total_bounds
    _shown = facilities.cx[_xmin:_xmax, _ymin:_ymax]
    _shown = _shown[_shown.intersects(oct14.union_all()) & (_shown["sector"] != "Not CFI")]
    _shown = _shown.set_geometry(_shown.representative_point())  # jails are outlines
    for _sector, _g in _shown.groupby("sector"):
        _g.plot(ax=_ax, markersize=6, label=f"{_sector} ({len(_g)})")
    _ax.legend(loc="upper right", fontsize=8)
    _ax.set_axis_off()
    _ax.set_title("HIFLD Next facilities inside PG&E's October 14, 2026 de-energized areas")
    _fig.savefig(results / "map_oct14.png", dpi=150, bbox_inches="tight")
    _ax
    return


@app.cell
def _(
    by_layer,
    edge,
    event_table,
    generator_match,
    hifld_total_oct14,
    hifld_versions,
    hospitals_oct14,
    inside_oct14,
    json,
    pge_cfi,
    results,
    sector_table,
    sites_oct14,
    started,
    time,
):
    by_layer.to_csv(results / "counts_by_layer_oct14.csv", index=False)
    sector_table.to_csv(results / "counts_by_sector_oct14.csv")
    inside_oct14.drop(columns="geometry").to_csv(
        results / "facilities_inside_oct14.csv", index=False
    )
    hospitals_oct14.to_csv(results / "hospitals_oct14.csv", index=False)
    generator_match.to_csv(results / "generator_sites_oct14.csv", index=False)
    edge.to_csv(results / "edge_sensitivity_oct14.csv", index=False)
    event_table.to_csv(results / "events.csv", index=False)
    hifld_versions.to_csv(results / "hifld_versions.csv", index=False)
    _open = hospitals_oct14[hospitals_oct14["STATUS"] == "OPEN"]
    headline = {
        "pge_cfi_oct14": pge_cfi["2026-10-14"],
        "hifld_cfi_type_inside_oct14": hifld_total_oct14,
        "share": round(hifld_total_oct14 / pge_cfi["2026-10-14"], 3),
        "hifld_sites_inside_oct14": sites_oct14,
        "hospital_records_inside": len(hospitals_oct14),
        "open_hospitals_inside": len(_open),
        "generator_sites_found": int((generator_match["HIFLD Next record inside"] != "none").sum()),
        "generator_sites": len(generator_match),
        "run_seconds": round(time.time() - started),
    }
    (results / "headline.json").write_text(json.dumps(headline, indent=2) + "\n")
    headline
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **No per-sector count from PG&E.** The report and workbook give only the CFI total. We
      can say which sectors HIFLD Next can't see at all, but not how many of PG&E's 1,864 sit
      in each, so "misses mainly water and communications" rests on what the layers lack, not
      on PG&E's breakdown.
    - **Accounts against points.** PG&E counts service points. A school or water district
      with several meters counts several times on PG&E's side and once, or not at all, on ours.
      The gap is partly a unit mismatch, and public data can't size that part.
    - **Status fields are old.** HIFLD Next's facility layers were last validated between
      2008 and 2024, depending on the layer. Fire stations, dialysis centres, EOCs and cellular towers have no usable
      status field, so closed sites can still count.
    - **Generator matching is loose.** Table 15 names a district or a site type, not an
      address.
    - **Polygons are approximate.** See the edge counts above.
    - **Our first power plant count was wrong.** It counted PG&E's own hydro plants (Pit,
      Balch, Drum, Caribou and others) as CFI. They are PG&E's assets, not customers, so they
      now sit in a separate row outside the total.
    """)
    return


if __name__ == "__main__":
    app.run()
