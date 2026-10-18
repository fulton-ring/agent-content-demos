import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import time
    import urllib.request
    import zipfile
    from datetime import UTC, datetime
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import shapely

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("GRID_GAPS_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("GRID_GAPS_OUTPUT_DIR", HERE / "output"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    # Distances are measured in CONUS Albers (metres), so the connectivity and hazard checks cover the lower 48.
    ALBERS = "EPSG:5070"
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # What do the HIFLD power plant, substation and transmission line layers leave out?

    **The question.** People treat the public HIFLD electric layers, now preserved in
    [HIFLD Next](https://hifld.publicenvirodata.org), as the map of the US grid. We expected one pass over them to
    find three kinds of gap:

    1. **Storage:** battery storage that EIA-860 lists but the Power Plants and Generating Units layers don't.
    2. **Connectivity:** transmission line ends that meet no substation.
    3. **Geomagnetic hazard:** a count of substations in USGS high geoelectric-hazard areas, and a total that differs
       from the 66,935 substations in Microsoft Research's space-weather model.

    If the storage gap is small, line ends almost all meet substations and the substation counts agree, the map
    holds up.

    **The first finding comes before any analysis.** HIFLD Next has no Electric Substations layer. DHS withdrew the
    HIFLD substation layer from public access in 2022 (data.gov lists it as "restricted public"), so it was not on
    HIFLD Open when the layers were preserved. Sections 2 and 3 therefore use OpenStreetMap's substations, as
    published in the Overture Maps infrastructure layer, as the stand-in public substation map.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The data

    Everything is downloaded on the first run into `data/` (not committed) and reused after that.
    The download date reported for each file is when that copy was fetched.

    | Source | What we use | Version |
    |---|---|---|
    | HIFLD Next | Power Plants, Generating Units, Transmission Lines | release `1704edb3`, layer v1.0.0 |
    | EIA-860 | Plant schedule (coordinates), Energy Storage schedule | 2025 annual, released September 2026 |
    | Overture Maps | `base/infrastructure`, `class = substation` (from OpenStreetMap) | release 2026-09-23.0 |
    | USGS (Lucas et al. 2020) | 100-year geoelectric field at 1,079 survey sites | the paper's published CSV |
    | US Census | state boundaries, 1:20m | 2024 cartographic boundary file |
    """)
    return


@app.cell
def _():
    def fetch(url: str, name: str) -> Path:
        """Download url into DATA/name once; later runs reuse the copy."""
        path = DATA / name
        if path.exists():
            return path
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (hifld-grid-gaps spike)"})
        with urllib.request.urlopen(request, timeout=600) as response:
            if response.status != 200:
                raise RuntimeError(f"{url} returned HTTP {response.status}")
            path.write_bytes(response.read())
        return path

    return (fetch,)


@app.cell
def _(fetch):
    _hifld = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    sources = {
        "HIFLD Next Power Plants": (
            f"{_hifld}/power-plants-1/power-plants-1/v1.0.0/geoparquet/power-plants-1.parquet",
            "power-plants.parquet",
        ),
        "HIFLD Next Generating Units": (
            f"{_hifld}/generating-units-1/generating-units-1/v1.0.0/geopackage/generating-units-1-geopackage.gpkg",
            "generating-units.gpkg",
        ),
        "HIFLD Next Transmission Lines": (
            f"{_hifld}/transmission-lines-1/transmission-lines-1/v1.0.0/geoparquet/transmission-lines-1.parquet",
            "transmission-lines.parquet",
        ),
        "EIA-860 2025": (
            "https://www.eia.gov/electricity/data/eia860/xls/eia8602025.zip",
            "eia8602025.zip",
        ),
        "USGS 100-year geoelectric field (Lucas et al. 2020)": (
            "https://raw.githubusercontent.com/greglucas/GeoelectricHazardPaper2019/"
            "856374c4aa0a96f149915712d5b7cc3e017d1507/code/geoelectric_100year.csv",
            "geoelectric_100year.csv",
        ),
        "Census states 2024": (
            "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_20m.zip",
            "cb_2024_us_state_20m.zip",
        ),
    }
    paths = {label: fetch(url, name) for label, (url, name) in sources.items()}
    return paths, sources


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Overture publishes its layers as GeoParquet on a public S3 bucket. DuckDB reads only the row groups whose
    bounding boxes fall in the lower 48, which still takes a few minutes the first time.
    """)
    return


@app.cell
def _():
    overture_release = "2026-09-23.0"
    overture_path = DATA / f"overture-substations-{overture_release}.parquet"
    if not overture_path.exists():
        _con = duckdb.connect()
        _con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        # An empty key makes DuckDB read the public bucket anonymously instead of using any AWS credentials around.
        _con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
        _con.sql(f"""
            COPY (
                SELECT id, names.primary AS name, ST_AsWKB(geometry) AS wkb
                FROM read_parquet(
                    's3://overturemaps-us-west-2/release/{overture_release}/theme=base/type=infrastructure/*')
                WHERE subtype = 'power' AND class = 'substation'
                  AND bbox.xmin > -125.5 AND bbox.xmax < -66.0 AND bbox.ymin > 24.0 AND bbox.ymax < 49.5
            ) TO '{overture_path}' (FORMAT parquet)
        """)
    return overture_path, overture_release


@app.cell
def _(overture_path, paths):
    def to_albers(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        return frame.to_crs(ALBERS)

    states = gpd.read_file(f"zip://{paths['Census states 2024']}")
    lower48 = to_albers(states[~states["STUSPS"].isin(["AK", "HI", "PR", "VI", "GU", "MP", "AS"])])[
        ["STUSPS", "geometry"]
    ]
    plants = to_albers(gpd.read_parquet(paths["HIFLD Next Power Plants"]))
    units = gpd.read_file(paths["HIFLD Next Generating Units"])
    lines = to_albers(gpd.read_parquet(paths["HIFLD Next Transmission Lines"]))
    _ov = pd.read_parquet(overture_path)
    _ov_all = to_albers(gpd.GeoDataFrame(_ov[["id", "name"]], geometry=gpd.GeoSeries.from_wkb(_ov["wkb"]), crs=4326))
    # Keep the Overture substations inside a lower-48 state; the query box also catches some in Canada and Mexico.
    substations = gpd.sjoin(_ov_all, lower48, predicate="intersects", how="inner")
    substations = substations[~substations.index.duplicated()].drop(columns="index_right")
    overture_in_box = len(_ov_all)
    return lines, lower48, overture_in_box, plants, states, substations, units


@app.cell
def _(overture_path, overture_release, paths, sources):
    _rows = []
    for _label, (_url, _) in sources.items():
        _path = paths[_label]
        _rows.append((_label, _url, _path.stat().st_size // 1_000_000, _path.stat().st_mtime))
    _rows.append(
        (
            f"Overture substations {overture_release}",
            "s3://overturemaps-us-west-2 (query above)",
            overture_path.stat().st_size // 1_000_000,
            overture_path.stat().st_mtime,
        )
    )
    provenance = pd.DataFrame(_rows, columns=["source", "url", "MB", "mtime"])
    provenance["downloaded (UTC)"] = pd.to_datetime(provenance.pop("mtime"), unit="s").dt.strftime("%Y-%m-%d %H:%M")
    provenance.to_csv(OUT / "provenance.csv", index=False)
    mo.ui.table(provenance, selection=None)
    return (provenance,)


@app.cell(hide_code=True)
def _(lines, plants, units):
    mo.md(f"""
    **How current are the HIFLD layers?** Each record carries a `SOURCEDATE`. Every Generating Units record is dated
    **{units["SOURCEDATE"].astype(str).str[:10].max()}**. The newest Power Plants record is dated
    **{plants["SOURCEDATE"].astype(str).str[:10].max()}**, and the newest Transmission Lines record
    **{lines["SOURCEDATE"].astype(str).str[:10].max()}**. HIFLD Next preserved what HIFLD Open last published, and
    nothing has refreshed these three layers since. Part of every gap below is age, and the storage section separates
    age from omission.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. Storage: batteries EIA-860 lists that the generation layers don't

    **Ground truth.** The Energy Storage schedule of EIA-860 2025 lists every operable battery generator at plants
    of at least 1 MW combined nameplate capacity. That threshold is by plant, so a battery unit below 1 MW can appear
    when it sits at a larger plant, and storage at sites under 1 MW (home and most commercial batteries) is in
    neither source by design. We don't count it.

    **Matching, in order.** For each battery generator we ask:

    1. Is the **unit** in Generating Units? HIFLD's unit `ID` is `<plant code>-<generator id>`.
    2. If not, is its **plant** in Power Plants by EIA plant code?
    3. If not, is there **any HIFLD power plant within 1 km** of EIA's coordinates for the plant (a location match)?

    A battery that fails all three is missing from the map. One that passes only 2 or 3 has a plant on the map,
    but the battery itself is not listed.
    """)
    return


@app.cell
def _(paths, plants, units):
    _zip = zipfile.ZipFile(paths["EIA-860 2025"])
    _storage = pd.read_excel(_zip.open("3_4_Energy_Storage_Y2025.xlsx"), sheet_name="Operable", header=1)
    _eia_plants = pd.read_excel(_zip.open("2___Plant_Y2025.xlsx"), header=1)
    batteries = _storage[_storage["Prime Mover"] == "BA"].copy()
    batteries["Plant Code"] = batteries["Plant Code"].astype(int)
    batteries["mw"] = batteries["Nameplate Capacity (MW)"].astype(float)
    batteries = batteries.merge(
        _eia_plants[["Plant Code", "Latitude", "Longitude"]].dropna().astype({"Plant Code": int}),
        on="Plant Code",
        how="left",
    )
    assert batteries["Latitude"].notna().all(), "every battery plant should have EIA coordinates"

    _unit_ids = set(units["ID"].astype(str).str.upper().str.strip())
    batteries["unit_key"] = (
        batteries["Plant Code"].astype(str) + "-" + batteries["Generator ID"].astype(str).str.upper()
    )
    batteries["unit_listed"] = batteries["unit_key"].isin(_unit_ids)
    # A few HIFLD plant codes are not numbers (for example "NA919"), so compare codes as text.
    batteries["plant_code_listed"] = batteries["Plant Code"].astype(str).isin(set(plants["PLANT_CODE"].astype(str)))

    _points = gpd.GeoDataFrame(
        batteries[["unit_key"]],
        geometry=gpd.points_from_xy(batteries["Longitude"], batteries["Latitude"]),
        crs=4326,
    ).to_crs(ALBERS)
    _near = gpd.sjoin_nearest(_points, plants[["geometry"]], distance_col="m_to_plant")
    batteries["m_to_hifld_plant"] = _near.groupby(level=0)["m_to_plant"].min()
    batteries["near_hifld_plant"] = batteries["m_to_hifld_plant"] <= 1000

    batteries["match"] = np.select(
        [
            batteries["unit_listed"],
            batteries["plant_code_listed"],
            batteries["near_hifld_plant"],
        ],
        [
            "1 unit in Generating Units",
            "2 plant code in Power Plants",
            "3 HIFLD plant within 1 km",
        ],
        default="4 missing from the map",
    )
    # Generating Units is dated 2023-09-01: a battery started after August 2023 can only be in it as a planned unit.
    _started = batteries["Operating Year"] * 12 + batteries["Operating Month"]
    batteries["built"] = np.where(_started >= 2023 * 12 + 9, "after Aug 2023", "by Aug 2023")
    _unit_status = units.assign(key=units["ID"].astype(str).str.upper().str.strip()).set_index("key")["STATUS"]
    batteries["status_in_units"] = batteries["unit_key"].map(_unit_status[~_unit_status.index.duplicated()])
    return (batteries,)


@app.cell
def _(batteries):
    storage_by_match = (
        batteries.groupby("match")
        .agg(generators=("mw", "size"), MW=("mw", "sum"))
        .round(1)
        .assign(share_of_MW=lambda t: (t["MW"] / t["MW"].sum()).round(3))
    )
    storage_by_age = batteries.pivot_table(index="match", columns="built", values="mw", aggfunc=["size", "sum"])
    storage_by_age.columns = [f"{'generators' if a == 'size' else 'MW'}, {b}" for a, b in storage_by_age.columns]
    storage_by_age = storage_by_age.fillna(0).round(0).astype(int)
    storage_by_match.to_csv(OUT / "storage_by_match.csv")
    storage_by_age.to_csv(OUT / "storage_by_age.csv")
    mo.vstack([storage_by_match, storage_by_age])
    return storage_by_age, storage_by_match


@app.cell(hide_code=True)
def _(batteries):
    _old = batteries[batteries["built"] == "by Aug 2023"]
    _old_unlisted = _old[~_old["unit_listed"]]
    _new = batteries[batteries["built"] == "after Aug 2023"]
    _new_listed = _new[_new["unit_listed"]]
    mo.md(f"""
    EIA-860 2025 lists **{len(batteries):,} operable battery generators, {batteries["mw"].sum():,.0f} MW**.
    Generating Units lists **{batteries["unit_listed"].sum():,}** of them
    ({batteries.loc[batteries["unit_listed"], "mw"].sum() / batteries["mw"].sum():.0%} of the MW).

    Most of the gap is age. **{len(_new):,} generators ({_new["mw"].sum():,.0f} MW)** started operating after August
    2023, the layer's source date. {len(_new_listed):,} of those are in Generating Units anyway, but as planned units
    (status {", ".join(sorted(_new_listed["status_in_units"].dropna().unique()))}), not operating ones. Of the
    **{len(_old):,}** generators operating by August 2023, **{len(_old_unlisted):,}
    ({_old_unlisted["mw"].sum():,.0f} MW)** are not in Generating Units. Those are omissions that age does not explain.
    """)
    return


@app.cell
def _(batteries):
    _bands = pd.cut(
        batteries["mw"],
        [0, 5, 20, 100, 10_000],
        labels=["<5 MW", "5-20 MW", "20-100 MW", "100+ MW"],
    )
    _flagged = batteries.assign(
        size_band=_bands,
        unlisted=~batteries["unit_listed"],
        unlisted_mw=np.where(batteries["unit_listed"], 0.0, batteries["mw"]),
    )
    storage_by_size = (
        _flagged.groupby("size_band", observed=True)
        .agg(
            generators=("mw", "size"),
            unlisted=("unlisted", "sum"),
            MW=("mw", "sum"),
            MW_unlisted=("unlisted_mw", "sum"),
        )
        .round(0)
        .assign(share_unlisted=lambda t: (t["unlisted"] / t["generators"]).round(2))
    )
    storage_by_state = (
        _flagged.assign(missing=_flagged["match"] == "4 missing from the map")
        .groupby("State")
        .agg(
            generators=("mw", "size"),
            unlisted=("unlisted", "sum"),
            MW=("mw", "sum"),
            MW_unlisted=("unlisted_mw", "sum"),
            missing_from_map=("missing", "sum"),
        )
        .sort_values("MW_unlisted", ascending=False)
        .round(0)
    )
    storage_by_size.to_csv(OUT / "storage_by_size.csv")
    storage_by_state.to_csv(OUT / "storage_by_state.csv")
    mo.vstack([storage_by_size, storage_by_state.head(15)])
    return storage_by_size, storage_by_state


@app.cell
def _(batteries, lower48):
    _pts = gpd.GeoDataFrame(
        batteries,
        geometry=gpd.points_from_xy(batteries["Longitude"], batteries["Latitude"]),
        crs=4326,
    ).to_crs(ALBERS)
    _pts = _pts[_pts.within(lower48.union_all())]
    _fig, _ax = plt.subplots(figsize=(11, 6.5))
    lower48.plot(ax=_ax, color="#f2f2f2", edgecolor="#bbbbbb", linewidth=0.5)
    for _label, _color in [("listed", "#9aa5b1"), ("unlisted", "#d1495b")]:
        _sel = _pts[_pts["unit_listed"] == (_label == "listed")]
        _sel.plot(
            ax=_ax,
            markersize=_sel["mw"].clip(2, 400) / 3,
            color=_color,
            alpha=0.6,
            label=f"battery {_label}",
        )
    _ax.set_axis_off()
    _ax.legend(loc="lower left", frameon=False)
    _ax.set_title("EIA-860 2025 battery generators: listed (grey) and not listed (red) in HIFLD Generating Units")
    _fig.tight_layout()
    _fig.savefig(OUT / "map_storage.png", dpi=110)
    mo.as_html(_fig)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. Connectivity: transmission line ends that meet no substation

    We take the two ends of every lower-48 line in the Transmission Lines layer and measure how far each is from the
    nearest substation, at 50 m, 250 m and 1 km, so the threshold's effect is visible.

    A line end far from a substation is not automatically an error. HIFLD splits lines where they branch, so many ends
    sit on another line (a tap); others end at a power plant's switchyard. For each end we also record whether it
    touches another line within 25 m and how far it is from the nearest HIFLD power plant. Then we hand-check a
    random sample of 50 ends that are more than 1 km from any substation against aerial imagery.
    """)
    return


@app.cell
def _(lines, lower48, plants, substations):
    _conus = lines[lines.intersects(lower48.union_all())].reset_index(drop=True)
    _first = shapely.get_point(shapely.get_geometry(_conus.geometry.values, 0), 0)
    _last = shapely.get_point(shapely.get_geometry(_conus.geometry.values, -1), -1)
    ends = gpd.GeoDataFrame(
        {
            "line": np.r_[_conus.index, _conus.index],
            "end": np.r_[np.full(len(_conus), 1), np.full(len(_conus), 2)],
            "line_id": np.r_[_conus["source_ID"], _conus["source_ID"]],
            "voltage": np.r_[_conus["VOLTAGE"], _conus["VOLTAGE"]],
            "sub_attr": np.r_[_conus["SUB_1"], _conus["SUB_2"]],
            "inferred": np.r_[_conus["INFERRED"], _conus["INFERRED"]],
        },
        geometry=np.r_[_first, _last],
        crs=ALBERS,
    )

    def nearest_m(points: gpd.GeoDataFrame, targets: gpd.GeoDataFrame) -> pd.Series:
        joined = gpd.sjoin_nearest(points[["geometry"]], targets[["geometry"]], distance_col="m")
        return joined.groupby(level=0)["m"].min()

    ends["m_to_substation"] = nearest_m(ends, substations)
    ends["m_to_plant"] = nearest_m(ends, plants)
    _touch = gpd.sjoin(
        gpd.GeoDataFrame(ends[["line"]], geometry=ends.buffer(25), crs=ALBERS),
        _conus[["geometry"]],
        predicate="intersects",
    )
    _other = _touch[_touch["line"] != _touch["index_right"]]
    ends["touches_other_line"] = ends.index.isin(_other.index)
    _attr = ends["sub_attr"].astype(str).str.upper()
    ends["attr_says"] = np.select(
        [
            _attr.str.startswith("TAP"),
            _attr.str.startswith("UNKNOWN"),
            _attr == "NOT AVAILABLE",
        ],
        ["TAP", "UNKNOWN", "NOT AVAILABLE"],
        default="named",
    )
    conus_line_count = len(_conus)
    return conus_line_count, ends


@app.cell
def _(conus_line_count, ends):
    _rows = []
    for _m in [50, 250, 1000]:
        _far = ends["m_to_substation"] > _m
        _far_plant = _far & (ends["m_to_plant"] > _m)
        _dead = _far_plant & ~ends["touches_other_line"]
        _rows.append(
            {
                "threshold": f"{_m:,} m",
                "ends farther than this from a substation": int(_far.sum()),
                "share of all ends": round(_far.mean(), 3),
                "... and from any HIFLD plant": int(_far_plant.sum()),
                "... and touching no other line": int(_dead.sum()),
                "share dead ends": round(_dead.mean(), 3),
            }
        )
    connectivity = pd.DataFrame(_rows).set_index("threshold")
    connectivity.to_csv(OUT / "connectivity_thresholds.csv")
    mo.vstack(
        [
            mo.md(f"**{conus_line_count:,} lower-48 lines, {len(ends):,} line ends.**"),
            connectivity,
        ]
    )
    return (connectivity,)


@app.cell
def _(ends):
    _far = ends[ends["m_to_substation"] > 1000]
    attr_split = pd.crosstab(
        _far["attr_says"],
        _far["touches_other_line"].map({True: "touches another line", False: "touches none"}),
    )
    attr_split.to_csv(OUT / "connectivity_attributes.csv")
    mo.vstack(
        [
            mo.md("What the line's own `SUB_1`/`SUB_2` attribute says, for ends more than 1 km out:"),
            attr_split,
        ]
    )
    return (attr_split,)


@app.cell
def _(ends, lower48):
    _far = ends[(ends["m_to_substation"] > 1000) & (ends["m_to_plant"] > 1000)]
    _fig, _ax = plt.subplots(figsize=(11, 6.5))
    lower48.plot(ax=_ax, color="#f2f2f2", edgecolor="#bbbbbb", linewidth=0.5)
    _far[_far["touches_other_line"]].plot(ax=_ax, markersize=1, color="#9aa5b1", label="touches another line")
    _far[~_far["touches_other_line"]].plot(ax=_ax, markersize=1.5, color="#d1495b", label="touches no other line")
    _ax.set_axis_off()
    _ax.legend(loc="lower left", frameon=False, markerscale=6)
    _ax.set_title("HIFLD transmission line ends more than 1 km from any substation or power plant")
    _fig.tight_layout()
    _fig.savefig(OUT / "map_connectivity.png", dpi=110)
    mo.as_html(_fig)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **The hand-checked sample.** We drew 50 ends at random (seed 50) from those more than 1 km from any
    substation, looked at each on Esri World Imagery with the line and nearby OpenStreetMap substations drawn on top,
    and labelled it: **data error** (the line stops short of, or runs past, a visible substation, or no line is
    visible), **tap or interconnection** (it ends on another line, or at a customer's or a utility's switch or
    station that no substation map shows), **end at a plant** (a generating plant's yard), or **unclear**. The labels
    are in `hand_check.csv`; `hand_check_chips.py` redraws the images we looked at.
    """)
    return


@app.cell
def _(ends):
    _pool = ends[ends["m_to_substation"] > 1000]
    sample = _pool.sample(50, random_state=50).to_crs(4326)
    sample_frame = pd.DataFrame(
        {
            "end_index": sample.index,
            "line_id": sample["line_id"],
            "end": sample["end"],
            "lon": sample.geometry.x.round(6),
            "lat": sample.geometry.y.round(6),
            "voltage": sample["voltage"],
            "sub_attr": sample["sub_attr"],
            "m_to_substation": sample["m_to_substation"].round(0),
            "m_to_plant": sample["m_to_plant"].round(0),
            "touches_other_line": sample["touches_other_line"],
        }
    )
    sample_frame.to_csv(OUT / "hand_check_sample.csv", index=False)
    _labels_path = HERE / "hand_check.csv"
    hand_labels = pd.read_csv(_labels_path) if _labels_path.exists() else pd.DataFrame()
    if len(hand_labels):
        # The labels were made on this exact sample; stop if the sample moved (for example, new data).
        assert sorted(hand_labels["end_index"]) == sorted(sample_frame["end_index"]), "hand_check.csv is stale"
        hand_split = hand_labels["label"].value_counts().rename("ends").to_frame()
        hand_split["share"] = (hand_split["ends"] / len(hand_labels)).round(2)
    else:
        hand_split = pd.DataFrame()
    mo.vstack([hand_split, hand_labels[hand_labels["label"] != "tap or interconnection"]] if len(hand_labels) else [])
    return hand_labels, hand_split, sample_frame


@app.cell(hide_code=True)
def _(connectivity, ends, hand_split):
    _km = connectivity.loc["1,000 m"]
    _placeholder = (ends.loc[ends["m_to_substation"] > 1000, "attr_says"] != "named").mean()
    _taps = int(hand_split.loc["tap or interconnection", "ends"]) if len(hand_split) else 0
    mo.md(f"""
    **What it shows.** {_km["ends farther than this from a substation"]:,} of {len(ends):,} line ends
    ({_km["share of all ends"]:.0%}) are more than 1 km from any OpenStreetMap substation. That looks like a broken
    map until you look at where they are: only **{_km["... and touching no other line"]:,}**
    ({_km["share dead ends"]:.1%} of all ends) are also more than 1 km from a HIFLD power plant and touch no other
    line. In the hand-checked sample, **{_taps} of 50** ends were taps or joins onto another line. HIFLD Transmission
    Lines is not a network you can trace from substation to substation: it is drawn as segments that break wherever a
    line branches, and for {_placeholder:.0%} of the far ends the substation named in `SUB_1`/`SUB_2` is a placeholder (`TAP...`,
    `UNKNOWN...` or `NOT AVAILABLE`).
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. Geomagnetic hazard: substations in USGS high-hazard areas

    USGS (Lucas et al. 2020, *Space Weather*) estimated the once-per-century geoelectric field at 1,079
    magnetotelluric survey sites, covering about two-thirds of the lower 48 (the Southeast, Texas and parts of the
    Plains have no survey yet). The paper maps these site values; we give each substation the value of its nearest
    survey site within 100 km, about one and a half times the survey's 70 km grid spacing, and leave it unrated if no
    site is that close.

    We band the 100-year field at 1, 3 and 10 V/km and call **3 V/km or more** the high bands. A field of a few
    volts per kilometre is where the paper finds transmission line voltages in the hundreds of volts.
    """)
    return


@app.cell
def _(paths, substations):
    _sites = pd.read_csv(paths["USGS 100-year geoelectric field (Lucas et al. 2020)"])
    sites = gpd.GeoDataFrame(
        _sites[["Site", "E 100-year"]],
        geometry=gpd.points_from_xy(_sites["longitude"], _sites["latitude"]),
        crs=4326,
    ).to_crs(ALBERS)
    _centroids = gpd.GeoDataFrame(substations[["STUSPS"]], geometry=substations.geometry.centroid, crs=ALBERS)
    _near = gpd.sjoin_nearest(_centroids, sites, max_distance=100_000, how="left", distance_col="m_to_site")
    _near = _near[~_near.index.duplicated()]
    rated = substations.assign(e100=_near["E 100-year"], m_to_site=_near["m_to_site"])
    rated["band"] = pd.cut(
        rated["e100"],
        [0, 1, 3, 10, 1_000],
        labels=["<1 V/km", "1-3 V/km", "3-10 V/km", "10+ V/km"],
        right=False,
    )
    rated["band"] = (
        rated["band"].cat.add_categories("no survey site within 100 km").fillna("no survey site within 100 km")
    )
    return rated, sites


@app.cell
def _(overture_in_box, rated):
    hazard_bands = rated["band"].value_counts().sort_index().rename("substations").to_frame()
    hazard_bands["share"] = (hazard_bands["substations"] / len(rated)).round(3)
    _high = rated[rated["band"].isin(["3-10 V/km", "10+ V/km"])]
    hazard_by_state = (
        _high.groupby(["STUSPS", "band"], observed=True)
        .size()
        .unstack(fill_value=0)
        .assign(total=lambda t: t.sum(axis=1))
    )
    hazard_by_state = hazard_by_state.sort_values("total", ascending=False)
    hazard_bands.to_csv(OUT / "hazard_bands.csv")
    hazard_by_state.to_csv(OUT / "hazard_by_state.csv")
    substation_counts = pd.DataFrame(
        {
            "substations": [len(rated), overture_in_box, 66_935, 0],
        },
        index=[
            "Overture/OSM, inside a lower-48 state",
            "Overture/OSM, whole query box (incl. border areas of Canada and Mexico)",
            "Microsoft Research space-weather model (GridSFM-derived grid data)",
            "HIFLD Next (no substation layer)",
        ],
    )
    substation_counts.to_csv(OUT / "substation_counts.csv")
    mo.vstack([substation_counts, hazard_bands, hazard_by_state.head(15)])
    return hazard_bands, hazard_by_state, substation_counts


@app.cell(hide_code=True)
def _(hazard_bands, hazard_by_state, rated):
    _high = int(hazard_bands.loc[["3-10 V/km", "10+ V/km"], "substations"].sum())
    _rated = len(rated) - int(hazard_bands.loc["no survey site within 100 km", "substations"])
    _top = ", ".join(f"{s} ({n:,})" for s, n in hazard_by_state["total"].head(5).items())
    mo.md(f"""
    **What it shows.** OpenStreetMap has **{len(rated):,}** substations in the lower 48, about
    {len(rated) - 66_935:,} more than Microsoft's 66,935. HIFLD Next has none to compare. Of the {_rated:,} substations
    near a USGS survey site, **{_high:,}** ({_high / _rated:.0%}) sit where the once-per-century geoelectric field is
    3 V/km or more. The states with the most are {_top}.

    The two totals are close but not built the same way. OSM counts any mapped `power=substation`, including small
    distribution and industrial yards, and is only as complete as its volunteers. Microsoft's count comes from
    "GridSFM-derived grid data", which its blog describes as realistic US transmission models; its substation list
    is not published with the post, so we can't say which yards differ. Neither is a utility's asset list.
    """)
    return


@app.cell
def _(lower48, rated, sites):
    _fig, _ax = plt.subplots(figsize=(11, 6.5))
    lower48.plot(ax=_ax, color="#f2f2f2", edgecolor="#bbbbbb", linewidth=0.5)
    _colors = {
        "no survey site within 100 km": "#dddddd",
        "<1 V/km": "#c6dbef",
        "1-3 V/km": "#6baed6",
        "3-10 V/km": "#f28e2b",
        "10+ V/km": "#d1495b",
    }
    _pts = rated.geometry.centroid
    for _band, _color in _colors.items():
        _sel = rated["band"] == _band
        _ax.scatter(
            _pts[_sel].x,
            _pts[_sel].y,
            s=0.6,
            color=_color,
            label=f"{_band} ({_sel.sum():,})",
        )
    sites.plot(ax=_ax, markersize=2, color="black", marker="x", linewidth=0.4)
    _ax.set_axis_off()
    _ax.legend(loc="lower left", frameon=False, markerscale=10, fontsize=8)
    _ax.set_title("Substations (OpenStreetMap via Overture) by once-per-century geoelectric field, USGS 2020 sites (x)")
    _fig.tight_layout()
    _fig.savefig(OUT / "map_hazard.png", dpi=110)
    mo.as_html(_fig)
    return


@app.cell
def _(
    batteries,
    connectivity,
    conus_line_count,
    ends,
    hand_split,
    hazard_bands,
    overture_release,
    provenance,
    rated,
):
    _old = batteries[batteries["built"] == "by Aug 2023"]
    _high = rated["band"].isin(["3-10 V/km", "10+ V/km"])
    headline = {
        "run_at_utc": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "run_seconds": round(time.perf_counter() - RUN_STARTED),
        "storage": {
            "eia_battery_generators": len(batteries),
            "eia_battery_mw": round(batteries["mw"].sum()),
            "unit_in_generating_units": int(batteries["unit_listed"].sum()),
            "mw_in_generating_units": round(batteries.loc[batteries["unit_listed"], "mw"].sum()),
            "by_match": batteries["match"].value_counts().sort_index().to_dict(),
            "started_after_aug_2023": int((batteries["built"] == "after Aug 2023").sum()),
            "mw_started_after_aug_2023": round(batteries.loc[batteries["built"] == "after Aug 2023", "mw"].sum()),
            "operating_by_aug_2023_not_in_units": int((~_old["unit_listed"]).sum()),
            "mw_operating_by_aug_2023_not_in_units": round(_old.loc[~_old["unit_listed"], "mw"].sum()),
        },
        "connectivity": {
            "lower48_lines": conus_line_count,
            "line_ends": len(ends),
            "thresholds": connectivity.reset_index().to_dict(orient="records"),
            "hand_check": hand_split["ends"].to_dict() if len(hand_split) else "not labelled",
        },
        "hazard": {
            "overture_release": overture_release,
            "substations_lower48": len(rated),
            "microsoft_count": 66_935,
            "bands": hazard_bands["substations"].to_dict(),
            "high_band_substations": int(_high.sum()),
        },
        "sources": provenance.to_dict(orient="records"),
    }
    (OUT / "headline.json").write_text(json.dumps(headline, indent=2, default=str))
    mo.md(f"```json\n{json.dumps(headline, indent=2, default=str)}\n```")
    return (headline,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **There is no HIFLD substation layer to test.** The question assumed one. Sections 2 and 3 use OpenStreetMap's
      substations (via Overture), so they test HIFLD's lines against a volunteer map, not against HIFLD's own
      substations. A line end that OSM is missing a substation for counts as floating here.
    - **Overpass failed.** We first tried pulling OSM substations from the Overpass API; the main server reset the
      connection and two mirrors timed out. Overture's GeoParquet on S3 worked and is versioned, so it is the
      reproducible choice.
    - **The hazard rating is by nearest survey site.** USGS publishes site values, not a gridded raster, and the paper's
      maps colour Voronoi-style cells around sites. Our nearest-site-within-100-km rule is close to that but not the
      same, and it leaves the unsurveyed third of the lower 48 unrated.
    - **Generating Units has no coordinates.** The layer is a table keyed to plants, so its location match has to go
      through the Power Plants layer or EIA's own coordinates.
    - **Line ends are taken as each line's first and last vertex.** For a multi-part line we take the first part's
      start and the last part's end; ends between parts are not tested.
    """)
    return


if __name__ == "__main__":
    app.run()
