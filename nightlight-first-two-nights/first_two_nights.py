import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import io
    import json
    import os
    import re
    import time
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date, datetime, timedelta, timezone
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import httpx
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import polars as pl
    from PIL import Image
    from pypdf import PdfReader
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds

    started = time.time()
    outputs = Path(__file__).parent / "outputs"
    outputs.mkdir(exist_ok=True)
    data_dir = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return (
        Image,
        PdfReader,
        ThreadPoolExecutor,
        data_dir,
        date,
        datetime,
        duckdb,
        from_bounds,
        gpd,
        httpx,
        io,
        json,
        mo,
        np,
        outputs,
        pl,
        plt,
        rasterize,
        re,
        started,
        time,
        timedelta,
        timezone,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can night light show which places are still dark in the first two days after a summer storm?

    Our earlier spike (`nightlight-storm-restoration/`, PR #252) found that after DTE's
    July 3, 2026 storm in Southeast Michigan, NASA's Black Marble night light had no clear view
    of any of DTE's 466 census tracts for the first two nights, and that across 611 storms in
    Heimdall Research's Storm Blackout tables only 28% of county nights in the first two nights
    had a clear reading. This notebook checks three things that spike left open:

    1. **Is the blindness cloud, or one satellite's sensor?** VIIRS flies on two satellites,
       Suomi NPP (Black Marble product VNP46, from 2012) and NOAA-20 (VJ146, from 2018). S-NPP
       stopped delivering data on November 2, 2026, so NOAA-20 is what anyone has to use now.
       We count clear first-two-night readings on both, with the same method, for every storm
       both cover. Heimdall's 28% mixes the two: each storm uses one product or the other.
    2. **DTE's July 2026 storm on both satellites,** including whether the last two nights of
       the earlier run were missing data or cloud.
    3. **How well night light tracks outages storm by storm,** not just pooled.

    Everything is public and downloaded at run time: NASA GIBS images, Heimdall's tables
    (Zenodo, CC BY 4.0), DOE EAGLE-I (figshare, CC BY 4.0), HIFLD Next and Census boundaries,
    and DTE's filing to the Michigan PSC.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Reading night light and cloud from NASA GIBS

    Black Marble's HDF5 files need an Earthdata login. NASA GIBS serves the same products as
    public PNG images with published color maps, so we turn colors back into values: the
    gap-filled radiance (180 bins up to 38.2 nW/cm²/sr) and the VIIRS cloud mask's clear-sky
    confidence (0 to 1). A pixel counts as clear at 95% confidence or more, as in the earlier
    spike. A transparent pixel is GIBS's "no data", which lets us tell missing data from cloud.
    These helpers are the earlier spike's `nightlight.py`, trimmed and copied so that folder
    stays untouched.
    """)
    return


@app.cell
def _(Image, data_dir, date, from_bounds, httpx, io, np, rasterize, re, time):
    from dataclasses import dataclass

    WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
    COLORMAPS = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/"
    CLEAR_CONFIDENCE = 0.95

    @dataclass(frozen=True)
    class Grid:
        """A lon/lat box sampled at a fixed number of pixels per degree."""

        west: float
        south: float
        east: float
        north: float
        per_degree: int

        @property
        def shape(self) -> tuple[int, int]:
            return (
                round((self.north - self.south) * self.per_degree),
                round((self.east - self.west) * self.per_degree),
            )

    def grid_around(bounds: np.ndarray, per_degree: int) -> Grid:
        """The smallest grid of this resolution covering (west, south, east, north)."""
        step = 1 / per_degree
        west, south, east, north = (float(b) for b in bounds)
        return Grid(
            round(west // step * step, 6),
            round(south // step * step, 6),
            round(-(-east // step) * step, 6),
            round(-(-north // step) * step, 6),
            per_degree,
        )

    def download(url: str, path, params: dict[str, str] | None = None):
        """Download url to path once, with up to four tries. Returns the cached path."""
        if path.exists() and path.stat().st_size > 0:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(4):
            try:
                with httpx.stream(
                    "GET", url, params=params, timeout=600, follow_redirects=True
                ) as response:
                    response.raise_for_status()
                    tmp = path.with_suffix(path.suffix + ".part")
                    with open(tmp, "wb") as f:
                        f.writelines(response.iter_bytes(1 << 20))
                tmp.rename(path)
                return path
            except httpx.HTTPError:
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))
        raise AssertionError("unreachable")

    def load_colormap(name: str) -> tuple[np.ndarray, np.ndarray]:
        """Sorted RGB keys and the lower bound of each data bin of a GIBS color map."""
        text = download(COLORMAPS + name, data_dir / "colormaps" / name).read_text()
        entries = re.findall(
            r'<ColorMapEntry rgb="(\d+),(\d+),(\d+)"[^>]*? value="[\[(]([^"]*)[)\]]"', text
        )
        bins: dict[int, float] = {}
        for r, g, b, bounds in entries:
            low = float(bounds.split(",")[0])
            if low >= 0:
                bins.setdefault((int(r) << 16) | (int(g) << 8) | int(b), low)
        assert len(bins) > 50, f"color map {name} parsed to only {len(bins)} entries"
        keys = np.array(sorted(bins))
        return keys, np.array([bins[k] for k in keys])

    def fetch_png(layer: str, night: date, grid: Grid) -> np.ndarray:
        """One GIBS WMS image of the grid as an RGBA array, cached on disk."""
        height, width = grid.shape
        name = f"{night.isoformat()}_{grid.west}_{grid.south}_{grid.per_degree}.png"
        params = {
            "SERVICE": "WMS",
            "REQUEST": "GetMap",
            "VERSION": "1.3.0",
            "LAYERS": layer,
            "CRS": "EPSG:4326",
            "BBOX": f"{grid.south},{grid.west},{grid.north},{grid.east}",
            "WIDTH": str(width),
            "HEIGHT": str(height),
            "FORMAT": "image/png",
            "TRANSPARENT": "TRUE",
            "TIME": night.isoformat(),
        }
        path = data_dir / "gibs" / layer / name
        for _attempt in range(3):  # GIBS sometimes answers with an XML error instead
            download(WMS, path, params)
            if path.read_bytes()[:4] == b"\x89PNG":
                break
            path.unlink()
        else:
            print(f"GIBS gave no image for {layer} {night}; counted as no data")
            return np.zeros((height, width, 4), dtype=np.uint8)
        rgba = np.array(Image.open(io.BytesIO(path.read_bytes())).convert("RGBA"))
        assert rgba.shape[:2] == (height, width), f"{path} has shape {rgba.shape}"
        return rgba

    def decode(rgba: np.ndarray, colormap: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
        """Each pixel's bin value; NaN where GIBS has no data or the color is unknown."""
        keys, lows = colormap
        rgb = rgba[..., :3].astype(np.int64)
        flat = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
        index = np.clip(np.searchsorted(keys, flat), 0, len(keys) - 1)
        found = (keys[index] == flat) & (rgba[..., 3] > 0)
        return np.where(found, lows[index], np.nan)

    radiance_map = load_colormap("VIIRS_DayNightBand_At_Sensor_Radiance.xml")
    clear_map = load_colormap("VIIRS_Clear_Sky_Confidence.xml")

    def clear_confidence(satellite: str, night: date, grid: Grid) -> np.ndarray:
        """VIIRS night clear-sky confidence, 0 to 1, NaN where GIBS has no data."""
        return decode(
            fetch_png(f"VIIRS_{satellite}_Clear_Sky_Confidence_Night", night, grid), clear_map
        )

    def radiance(satellite: str, night: date, grid: Grid) -> np.ndarray:
        """Black Marble gap-filled radiance (nW/cm²/sr, lower bin edge)."""
        layer = f"VIIRS_{satellite}_GapFilled_BRDF_Corrected_DayNightBand_Radiance"
        return decode(fetch_png(layer, night, grid), radiance_map)

    def zone_index(zones, grid: Grid) -> np.ndarray:
        """Rasterize zones onto the grid: each pixel holds its zone's row number, or -1."""
        height, width = grid.shape
        transform = from_bounds(grid.west, grid.south, grid.east, grid.north, width, height)
        shapes = ((geom, i) for i, geom in enumerate(zones.geometry))
        return rasterize(shapes, out_shape=(height, width), transform=transform, fill=-1)

    return (
        CLEAR_CONFIDENCE,
        clear_confidence,
        download,
        fetch_png,
        grid_around,
        radiance,
        radiance_map,
        decode,
        zone_index,
    )


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. DTE's July 3, 2026 storm on both satellites

    DTE's filing (MPSC Case U-22156) gives the restoration curve: 44% of affected customers
    back within 24 hours, 70% within 48, 88% within 72, 99% after 4.6 days, and meter
    reporting down to about 45% at the peak. We read it from the PDF so every number traces
    back to the filing.
    """)
    return


@app.cell
def _(PdfReader, data_dir, download, re):
    filing_path = download(
        "https://mi-psc.my.site.com/sfc/servlet.shepherd/version/download/068cs00002PhWOeAAN",
        data_dir / "dte_storm_report_u22156.pdf",
    )
    filing_text = re.sub(
        r"\s+", " ", " ".join(page.extract_text() or "" for page in PdfReader(filing_path).pages)
    )
    restoration_sentence = re.search(
        r"Of the total affected customer population,.*?July 9\.", filing_text
    )
    assert restoration_sentence, "restoration sentence not found in the filing"
    shares = [
        int(s)
        for s in re.findall(r"(\d+)% (?:were restored )?(?:within|after)", restoration_sentence[0])
    ]
    assert shares == [44, 70, 88, 99], f"unexpected restoration shares {shares}"
    affected_match = re.search(r"nearly ([\d,]+) customers impacted", filing_text)
    served_match = re.search(r"~([\d.]+) million electric customers", filing_text)
    meters_match = re.search(r"[Mm]eter reporting fell to about (\d+)%", filing_text)
    assert affected_match and served_match and meters_match, "filing figures not found"
    customers_affected = int(affected_match[1].replace(",", ""))
    customers_served = float(served_match[1]) * 1e6
    meter_reporting = int(meters_match[1])
    # Hours after 16:00 EDT on July 3, the filing's own clock (99% at 07:00 July 8, the last
    # customers "in the early morning on July 9", taken as 04:00).
    dte_hours = [0, 24, 48, 72, 111, 132]
    dte_restored = [0.0, 0.44, 0.70, 0.88, 0.99, 1.0]
    print(restoration_sentence[0])
    return customers_affected, customers_served, dte_hours, dte_restored, meter_reporting


@app.cell
def _(mo):
    mo.md(r"""
    DTE's territory is the piece of HIFLD Next's DTE Electric polygon that contains Detroit
    (the whole polygon is about 3.5 times DTE's real territory; see the earlier spike). A
    census tract counts if at least half of it is inside. A pixel is "lit" if its usual
    NOAA-20 brightness on clear nights in the month before the storm is at least
    5 nW/cm²/sr. Both satellites are scored on the same lit pixels, and a tract or the
    territory has a clear reading when at least half its lit pixels are clear.
    """)
    return


@app.cell
def _(data_dir, download, gpd):
    from shapely.geometry import Point

    territories = gpd.read_parquet(
        download(
            "https://hifld.publicenvirodata.org/storage/hifld/electric-retail-service-territories/"
            "electric-retail-service-territories/v1.0.0/geoparquet/"
            "electric-retail-service-territories.parquet",
            data_dir / "territories.parquet",
        )
    )
    dte = territories[territories["NAME"] == "DTE ELECTRIC COMPANY"].to_crs(4326)
    assert len(dte) == 1, "expected one DTE polygon"
    dte_parts = dte.explode(index_parts=False).reset_index(drop=True)
    territory = dte_parts[dte_parts.contains(Point(-83.05, 42.33))].reset_index(drop=True)
    assert len(territory) == 1, "no DTE piece contains Detroit"

    census = "https://www2.census.gov/geo/tiger/GENZ2024/shp/"
    tracts = gpd.read_file(
        download(census + "cb_2024_26_tract_500k.zip", data_dir / "cb_2024_26_tract_500k.zip")
    ).to_crs(4326)
    tract_area = tracts.to_crs(5070).area
    tracts["geometry"] = tracts.intersection(territory.geometry.iloc[0])
    tracts = tracts[tracts.to_crs(5070).area / tract_area >= 0.5].reset_index(drop=True)
    print(f"{len(tracts)} tracts in DTE's territory")
    return census, territory, tracts


@app.cell
def _(
    ThreadPoolExecutor,
    clear_confidence,
    date,
    grid_around,
    np,
    radiance,
    territory,
    timedelta,
    tracts,
    zone_index,
):
    dte_grid = grid_around(territory.total_bounds, 240)  # Black Marble's 15 arc-second grid
    storm_night = date(2026, 7, 4)  # first overpass after the 16:00 EDT July 3 storm
    dte_nights = [storm_night + timedelta(days=d) for d in range(-31, 30)]
    pre_nights = [n for n in dte_nights if n < storm_night]
    with ThreadPoolExecutor(max_workers=8) as dte_pool:
        dte_conf = {
            sat: np.stack(
                list(dte_pool.map(lambda n, s=sat: clear_confidence(s, n, dte_grid), dte_nights))
            )
            for sat in ("NOAA20", "SNPP")
        }
        pre_radiance = np.stack(
            list(dte_pool.map(lambda n: radiance("NOAA20", n, dte_grid), pre_nights))
        )
    pre_clear = dte_conf["NOAA20"][: len(pre_nights)] >= 0.95
    with np.errstate(all="ignore"):
        usual = np.nanmedian(np.where(pre_clear, pre_radiance, np.nan), axis=0)
    lit = (zone_index(territory, dte_grid) == 0) & (pre_clear.sum(axis=0) >= 3) & (usual >= 5.0)
    tract_index = np.where(lit, zone_index(tracts, dte_grid), -1)
    tract_lit = np.bincount(tract_index[tract_index >= 0], minlength=len(tracts))
    print(f"{lit.sum():,} lit pixels; {(tract_lit >= 20).sum()} tracts with 20+ lit pixels")
    return dte_conf, dte_grid, dte_nights, lit, tract_index, tract_lit


@app.cell
def _(
    customers_affected,
    customers_served,
    datetime,
    dte_conf,
    dte_hours,
    dte_nights,
    dte_restored,
    lit,
    np,
    outputs,
    pl,
    timezone,
    tract_index,
    tract_lit,
):
    storm_time = datetime(2026, 7, 3, 20, 0, tzinfo=timezone.utc)  # 16:00 EDT
    hours_after = [
        (datetime(n.year, n.month, n.day, 7, tzinfo=timezone.utc) - storm_time).total_seconds()
        / 3600
        for n in dte_nights
    ]  # both satellites cross Detroit around 07:00 UTC, 03:00 EDT
    dte_out = [
        (1 - float(np.interp(h, dte_hours, dte_restored))) * customers_affected / customers_served
        if h >= 0
        else 0.0
        for h in hours_after
    ]
    readable_tracts = tract_lit >= 20
    dte_rows = []
    for sat, conf in dte_conf.items():
        for i, night in enumerate(dte_nights):
            clear_px = (conf[i] >= 0.95) & lit
            tract_clear = np.bincount(
                tract_index[clear_px & (tract_index >= 0)], minlength=len(tract_lit)
            )
            with np.errstate(all="ignore"):
                tract_share = tract_clear / tract_lit
            dte_rows.append(
                {
                    "satellite": sat,
                    "night": night,
                    "hours_after_storm": round(hours_after[i], 1),
                    "clear_share": float(clear_px.sum() / lit.sum()),
                    "no_data_share": float(np.isnan(conf[i][lit]).mean()),
                    "tracts_clear": int(((tract_share >= 0.5) & readable_tracts).sum()),
                    "dte_out_share": dte_out[i],
                }
            )
    dte_table = pl.DataFrame(dte_rows)
    dte_table.write_csv(outputs / "dte_nights.csv")
    dte_table.filter(pl.col("hours_after_storm").is_between(0, 100)).sort("night", "satellite")
    return (dte_table,)


@app.cell
def _(mo):
    mo.md(r"""
    For each satellite: tracts with a clear reading in the first 48 hours (the nights of
    July 4 and 5, UTC), the first night with at least half the lit territory clear, and DTE's
    implied share of all its customers still out at that overpass (share of affected customers
    still out × 450,000 / 2.3 million). Then every post-storm night where the territory had
    no clear reading, split into nights GIBS has no data for and nights the cloud mask rated
    cloudy.
    """)
    return


@app.cell
def _(dte_table, pl, tract_lit):
    after_storm = dte_table.filter(pl.col("hours_after_storm") > 0)
    dte_results = {}
    for sat_r in ("NOAA20", "SNPP"):
        rows_r = after_storm.filter(pl.col("satellite") == sat_r).sort("night")
        first_48h = rows_r.filter(pl.col("hours_after_storm") <= 48)
        first_clear = rows_r.filter(pl.col("clear_share") >= 0.5).row(0, named=True)
        dark_nights = rows_r.filter(pl.col("clear_share") < 0.5)
        dte_results[sat_r] = {
            "tracts": int((tract_lit >= 20).sum()),
            "tracts_clear_first_48h": int(first_48h["tracts_clear"].max()),
            "best_clear_share_first_48h": round(float(first_48h["clear_share"].max()), 4),
            "first_clear_night": str(first_clear["night"]),
            "first_clear_hours": first_clear["hours_after_storm"],
            "dte_out_share_then": round(first_clear["dte_out_share"], 4),
            "post_storm_nights": rows_r.height,
            "nights_without_clear_reading": dark_nights.height,
            "of_which_no_data": int((dark_nights["no_data_share"] >= 0.5).sum()),
            "of_which_cloud": int((dark_nights["no_data_share"] < 0.5).sum()),
            "last_two_nights": rows_r.tail(2)
            .select("night", "clear_share", "no_data_share")
            .with_columns(pl.col("night").cast(pl.String))
            .to_dicts(),
        }
    for sat_p, res in dte_results.items():
        print(sat_p, {k: v for k, v in res.items() if k != "last_two_nights"})
        print("  last two nights:", res["last_two_nights"])
    return (dte_results,)


@app.cell
def _(mo):
    mo.md(r"""
    The earlier spike asked whether its last two nights (August 1 and 2) were missing GIBS
    data rather than cloud. The table above says cloud: GIBS has a cloud-mask value for every
    lit pixel on both nights, and none is clear. The raw picture agrees. Below,
    NOAA-20's uncorrected day/night band on a clear night (July 30) and on August 1 and 2:
    sharp city lights on the clear night; on the other two, cloud texture covers the
    territory and the cities show only as a diffuse glow.
    """)
    return


@app.cell
def _(date, decode, dte_conf, dte_grid, dte_nights, fetch_png, np, outputs, plt, radiance_map):
    raw_grid = dte_grid
    fig_raw, axes_raw = plt.subplots(1, 3, figsize=(12, 4.6))
    for ax_raw, night_raw in zip(
        axes_raw, [date(2026, 7, 30), date(2026, 8, 1), date(2026, 8, 2)], strict=True
    ):
        raw = decode(
            fetch_png("VIIRS_NOAA20_DayNightBand_At_Sensor_Radiance", night_raw, raw_grid),
            radiance_map,
        )
        conf_raw = dte_conf["NOAA20"][dte_nights.index(night_raw)]
        ax_raw.imshow(np.log1p(raw), cmap="gray", vmin=0, vmax=np.log1p(38.2))
        ax_raw.set_title(f"{night_raw:%b %-d}: {np.mean(conf_raw >= 0.95):.0%} of box clear")
        ax_raw.axis("off")
    fig_raw.suptitle("NOAA-20 day/night band over DTE's territory (log scale)")
    fig_raw.tight_layout()
    fig_raw.savefig(outputs / "dte_last_nights.png", dpi=100)
    fig_raw
    return


@app.cell
def _(dte_table, outputs, pl, plt):
    fig_dte, ax_dte = plt.subplots(figsize=(10, 4.2))
    window_dte = dte_table.filter(pl.col("hours_after_storm").is_between(-24 * 5, 24 * 30))
    for sat_plot, color_c in (("NOAA20", "tab:blue"), ("SNPP", "tab:orange")):
        rows_c = window_dte.filter(pl.col("satellite") == sat_plot)
        ax_dte.plot(
            rows_c["hours_after_storm"] / 24,
            rows_c["clear_share"] * 100,
            marker="o",
            color=color_c,
            label=f"{sat_plot}: lit territory clear, %",
        )
        missing = rows_c.filter(pl.col("no_data_share") >= 0.5)
        ax_dte.scatter(
            missing["hours_after_storm"] / 24,
            [-4] * missing.height,
            marker="x",
            color=color_c,
            label=f"{sat_plot}: no GIBS data",
        )
    sat_curve = window_dte.filter(pl.col("satellite") == "NOAA20")
    ax_dte.plot(
        sat_curve["hours_after_storm"] / 24,
        sat_curve["dte_out_share"] * 100 * 5,
        color="black",
        linestyle="--",
        label="DTE customers still out, % × 5",
    )
    ax_dte.axvspan(0, 2, color="grey", alpha=0.15)
    ax_dte.set_xlabel("days after the storm (16:00 EDT July 3, 2026); shaded: first 48 hours")
    ax_dte.set_ylabel("%")
    ax_dte.legend(fontsize=8, ncol=2)
    ax_dte.set_title("DTE territory: how much of it each satellite could see, night by night")
    fig_dte.tight_layout()
    fig_dte.savefig(outputs / "dte_clear_nights.png", dpi=110)
    fig_dte
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. First two nights after every storm, NOAA-20 vs S-NPP

    Heimdall's tables list 611 storms with FEMA-declared counties, each county with the date
    the storm reached it. For every declared county we take the first and second night after
    that date, as the earlier spike did, and keep the county nights that both satellites'
    GIBS cloud masks cover: from February 2018, when NOAA-20 starts, to November 2, 2026,
    minus gaps GIBS lists in its capabilities (the largest is October 1 to December 4, 2023,
    for both satellites). Alaska is left out: its counties cross the antimeridian.

    For each storm we fetch one image per night and satellite covering its declared counties,
    at 60 pixels per degree (about 1.8 km; county shares don't need Black Marble's 500 m), and
    count a county night as clear when at least half the county's pixels are clear. That is
    the same rule the earlier spike applied to Heimdall's valid-pixel share, so Heimdall's
    own number on these county nights is a check on our method.
    """)
    return


@app.cell
def _(data_dir, download, pl):
    zenodo = "https://zenodo.org/api/records/23010005/files/"
    heimdall_daily = download(
        zenodo + "data__county_daily.parquet/content", data_dir / "heimdall_county_daily.parquet"
    )
    heimdall_summary = pl.read_csv(
        download(
            zenodo + "data__county_summary.csv/content", data_dir / "heimdall_county_summary.csv"
        ),
        infer_schema_length=0,
    )
    declared = heimdall_summary.filter(pl.col("declared") == "True").select(
        "event_id", "geoid", "state", "product", impact=pl.col("impact_date").str.to_date()
    )
    print(f"{declared['event_id'].n_unique()} storms, {declared.height:,} declared counties")
    return declared, heimdall_daily


@app.cell
def _(data_dir, date, download, re):
    capabilities = download(
        "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/1.0.0/WMTSCapabilities.xml",
        data_dir / "gibs_capabilities.xml",
    ).read_text()

    def layer_ranges(layer: str) -> list[tuple[date, date]]:
        """Date ranges GIBS lists for a layer, from its WMTS capabilities."""
        block = re.search(
            rf"<ows:Identifier>{layer}</ows:Identifier>.*?</Layer>", capabilities, re.S
        )
        assert block, f"{layer} not in GIBS capabilities"
        spans = re.findall(r"<Value>(\d{4}-\d\d-\d\d)/(\d{4}-\d\d-\d\d)/P1D</Value>", block[0])
        assert spans, f"no date ranges for {layer}"
        return [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in spans]

    cloud_ranges = {
        sat: layer_ranges(f"VIIRS_{sat}_Clear_Sky_Confidence_Night") for sat in ("NOAA20", "SNPP")
    }
    for sat_g, spans_g in cloud_ranges.items():
        print(sat_g, [f"{a}..{b}" for a, b in spans_g])
    return (cloud_ranges,)


@app.cell
def _(census, cloud_ranges, data_dir, declared, download, gpd, pl):
    def covered(night) -> bool:
        return all(any(a <= night <= b for a, b in spans) for spans in cloud_ranges.values())

    all_county_nights = declared.join(pl.DataFrame({"k": [1, 2]}), how="cross").with_columns(
        night=pl.col("impact") + pl.duration(days=pl.col("k"))
    )
    county_shapes = gpd.read_file(
        download(census + "cb_2024_us_county_500k.zip", data_dir / "cb_2024_us_county_500k.zip")
    ).to_crs(4326)[["GEOID", "geometry"]]
    sample = all_county_nights.filter(
        pl.col("night").map_elements(covered, return_dtype=pl.Boolean)
        & (pl.col("state") != "AK")
        & pl.col("geoid").is_in(county_shapes["GEOID"].to_list())
    )
    print(
        f"all storms: {all_county_nights.height:,} county nights; both satellites covered: "
        f"{sample.height:,} county nights, {sample['event_id'].n_unique()} storms, "
        f"{sample.select('event_id', 'night').unique().height} storm nights"
    )
    return county_shapes, sample


@app.cell
def _(
    CLEAR_CONFIDENCE,
    ThreadPoolExecutor,
    clear_confidence,
    county_shapes,
    grid_around,
    np,
    pl,
    sample,
    time,
    zone_index,
):
    fetch_started = time.time()
    storm_grids = {}
    for event_g in sample["event_id"].unique().sort():
        geoids_g = sample.filter(pl.col("event_id") == event_g)["geoid"].unique().to_list()
        shapes_g = county_shapes[county_shapes["GEOID"].isin(geoids_g)].reset_index(drop=True)
        grid_g = grid_around(shapes_g.total_bounds, 60)
        assert max(grid_g.shape) <= 4000, f"{event_g} box is too large: {grid_g.shape}"
        storm_grids[event_g] = (shapes_g, grid_g)
    jobs = [
        (row["event_id"], row["night"], sat)
        for row in sample.select("event_id", "night").unique().iter_rows(named=True)
        for sat in ("NOAA20", "SNPP")
    ]
    with ThreadPoolExecutor(max_workers=8) as storm_pool:
        list(storm_pool.map(lambda j: clear_confidence(j[2], j[1], storm_grids[j[0]][1]), jobs))
    print(f"{len(jobs):,} GIBS images in {time.time() - fetch_started:.0f} s")

    county_rows = []
    for event_c, (shapes_c, grid_c) in storm_grids.items():
        zones_c = zone_index(shapes_c, grid_c)
        inside_c = zones_c >= 0
        ids_c = zones_c[inside_c]
        pixels_c = np.bincount(ids_c, minlength=len(shapes_c))
        nights_c = sample.filter(pl.col("event_id") == event_c)["night"].unique().to_list()
        for night_c in nights_c:
            for sat_c in ("NOAA20", "SNPP"):
                conf_c = clear_confidence(sat_c, night_c, grid_c)[inside_c]
                clear_c = np.bincount(ids_c, conf_c >= CLEAR_CONFIDENCE, len(shapes_c))
                empty_c = np.bincount(ids_c, np.isnan(conf_c), len(shapes_c))
                with np.errstate(all="ignore"):
                    county_rows.append(
                        pl.DataFrame(
                            {
                                "event_id": event_c,
                                "geoid": shapes_c["GEOID"],
                                "night": night_c,
                                "satellite": sat_c,
                                "clear_share": clear_c / pixels_c,
                                "no_data_share": empty_c / pixels_c,
                            }
                        )
                    )
    gibs_county = pl.concat(county_rows).pivot(
        on="satellite",
        index=["event_id", "geoid", "night"],
        values=["clear_share", "no_data_share"],
    )
    fetch_seconds = round(time.time() - fetch_started)
    gibs_county.head()
    return fetch_seconds, gibs_county, jobs


@app.cell
def _(duckdb, gibs_county, heimdall_daily, pl, sample):
    wanted = sample.select("event_id", "geoid", "night")  # noqa: F841 (read by duckdb)
    heimdall_valid = duckdb.sql(f"""
        SELECT d.event_id, d.geoid, CAST(d.date AS DATE) AS night, d.valid_pixel_share
        FROM read_parquet('{heimdall_daily}') d
        JOIN wanted w
          ON d.event_id = w.event_id AND d.geoid = w.geoid AND CAST(d.date AS DATE) = w.night
    """).pl()
    assert heimdall_valid.select("event_id", "geoid", "night").is_unique().all()
    first_two = (
        sample.join(gibs_county, on=["event_id", "geoid", "night"], how="left")
        .join(heimdall_valid, on=["event_id", "geoid", "night"], how="left")
        .with_columns(
            noaa20_clear=pl.col("clear_share_NOAA20") >= 0.5,
            snpp_clear=pl.col("clear_share_SNPP") >= 0.5,
            heimdall_clear=pl.col("valid_pixel_share").fill_null(0) >= 0.5,
            summer=pl.col("impact").dt.month().is_between(5, 9),
        )
    )
    assert first_two["clear_share_NOAA20"].null_count() == 0, "a county night was not measured"
    first_two.select("noaa20_clear", "snpp_clear", "heimdall_clear").mean()
    return (first_two,)


@app.cell
def _(mo):
    mo.md(r"""
    The headline: on the same county nights, how often each satellite had a clear reading.
    If the blindness were one sensor's fault, the two would disagree. If it's cloud, they
    agree, because the two fly the same orbit and pass within an hour of each other (50
    minutes apart until NOAA-21 joined, about 25 minutes since), through the same weather.
    """)
    return


@app.cell
def _(first_two, pl):
    def clear_rates(rows: pl.DataFrame) -> dict:
        return {
            "county_nights": rows.height,
            "storms": rows["event_id"].n_unique(),
            "noaa20_clear": round(float(rows["noaa20_clear"].mean()), 4),
            "snpp_clear": round(float(rows["snpp_clear"].mean()), 4),
            "heimdall_clear": round(float(rows["heimdall_clear"].mean()), 4),
            "both_clear": round(float((rows["noaa20_clear"] & rows["snpp_clear"]).mean()), 4),
            "neither_clear": round(float((~rows["noaa20_clear"] & ~rows["snpp_clear"]).mean()), 4),
            "noaa20_no_data": round(float((rows["no_data_share_NOAA20"] >= 0.5).mean()), 4),
            "snpp_no_data": round(float((rows["no_data_share_SNPP"] >= 0.5).mean()), 4),
            "snpp_clear_where_it_has_data": round(
                float(rows.filter(pl.col("no_data_share_SNPP") < 0.5)["snpp_clear"].mean()), 4
            ),
        }

    visibility = {
        "all": clear_rates(first_two),
        "summer_may_sep": clear_rates(first_two.filter(pl.col("summer"))),
        "heimdall_used_vnp46a2": clear_rates(first_two.filter(pl.col("product") == "VNP46A2")),
        "heimdall_used_vj146a2": clear_rates(first_two.filter(pl.col("product") == "VJ146A2")),
    }
    pl.DataFrame([{"subset": k, **v} for k, v in visibility.items()])
    return (visibility,)


@app.cell
def _(mo):
    mo.md(r"""
    Check against Heimdall: on storms where Heimdall used S-NPP, our GIBS S-NPP rate should
    be close to Heimdall's, and likewise for NOAA-20. Heimdall's valid pixels also exclude
    snow and bad-quality pixels, and its cloud mask is the one inside the Black Marble files,
    so some gap is expected. The agreement rate below is county night by county night.
    """)
    return


@app.cell
def _(first_two, pl):
    method_check = (
        first_two.with_columns(
            gibs_same_satellite=pl.when(pl.col("product") == "VNP46A2")
            .then(pl.col("snpp_clear"))
            .otherwise(pl.col("noaa20_clear"))
        )
        .group_by("product")
        .agg(
            county_nights=pl.len(),
            gibs_clear=pl.col("gibs_same_satellite").mean(),
            heimdall_clear=pl.col("heimdall_clear").mean(),
            agree=(pl.col("gibs_same_satellite") == pl.col("heimdall_clear")).mean(),
        )
        .sort("product")
    )
    method_check
    return (method_check,)


@app.cell
def _(first_two, outputs, pl, plt):
    per_storm = (
        first_two.group_by("event_id")
        .agg(
            impact=pl.col("impact").min(),
            states=pl.col("state").unique().sort().str.join(" "),
            county_nights=pl.len(),
            noaa20_clear=pl.col("noaa20_clear").mean(),
            snpp_clear=pl.col("snpp_clear").mean(),
            heimdall_clear=pl.col("heimdall_clear").mean(),
            heimdall_product=pl.col("product").first(),
        )
        .sort("impact", "event_id")
    )
    per_storm.write_csv(outputs / "storms_first_two_nights.csv")
    fig_storms, ax_storms = plt.subplots(figsize=(5.8, 5.4))
    ax_storms.scatter(
        per_storm["snpp_clear"] * 100,
        per_storm["noaa20_clear"] * 100,
        s=per_storm["county_nights"].clip(upper_bound=200) / 2 + 4,
        alpha=0.5,
    )
    ax_storms.plot([0, 100], [0, 100], color="grey", linestyle="--")
    ax_storms.set_xlabel("S-NPP: county nights clear, %")
    ax_storms.set_ylabel("NOAA-20: county nights clear, %")
    ax_storms.set_title("First two nights after each storm (dot size: county nights)")
    fig_storms.tight_layout()
    fig_storms.savefig(outputs / "storms_noaa20_vs_snpp.png", dpi=110)
    corr_storms = per_storm.select(pl.corr("snpp_clear", "noaa20_clear")).item()
    print(f"{per_storm.height} storms; correlation of per-storm clear shares {corr_storms:.2f}")
    fig_storms
    return corr_storms, per_storm


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Where night light can see, does it track outages? Storm by storm

    The earlier spike compared Heimdall's night-light deficit (1 − the county's light ratio
    to its usual brightness) with DOE EAGLE-I's share of customers out at the satellite's
    overpass, on county nights 1 to 7 after impact with at least half the county clear, for
    five summer storms. Pooled, the Spearman correlation was 0.04. Here we rebuild that table
    and report it per storm, with the number of clear county nights behind each.

    EAGLE-I gives customers out per county every 15 minutes. NOAA-20 and S-NPP cross at about
    01:30 local solar time, so a county's overpass is 1.5 h − longitude/15 in UTC; we average
    EAGLE-I within 30 minutes of it and divide by EAGLE-I's modeled customers per county.
    EAGLE-I is scraped from utility outage maps, so it is the utilities' own count.
    """)
    return


@app.cell
def _(county_shapes, data_dir, download, duckdb, pl):
    figshare = "https://ndownloader.figshare.com/files/"
    eaglei_files = {2023: "44574907", 2024: "53581661"}
    mcc = pl.read_csv(
        download(figshare + "42547708", data_dir / "eaglei_MCC.csv"), infer_schema_length=0
    )
    mcc = mcc.rename({mcc.columns[0]: "County_FIPS"}).select(  # the file starts with a BOM
        geoid=pl.col("County_FIPS").str.zfill(5), customers=pl.col("Customers").cast(pl.Float64)
    )
    overpass = pl.DataFrame(
        {
            "geoid": county_shapes["GEOID"],
            "overpass_utc": 1.5
            - county_shapes.to_crs(5070).centroid.to_crs(4326).x.to_numpy() / 15,
        }
    )

    def eaglei_at_overpass(geoids: list[str], nights: list) -> pl.DataFrame:
        """Share of customers out per county and night, at that county's overpass."""
        years = {n.year for n in nights}
        assert len(years) == 1 and years <= set(eaglei_files), f"no EAGLE-I file for {years}"
        year = years.pop()
        path = download(figshare + eaglei_files[year], data_dir / f"eaglei_outages_{year}.csv")
        header = path.open().readline().strip().split(",")
        count_column = "sum" if "sum" in header else "customers_out"  # renamed in 2024
        rows = duckdb.sql(f"""
            SELECT lpad(fips_code, 5, '0') AS geoid, run_start_time AS t, "{count_column}" AS out
            FROM read_csv('{path}', types={{'fips_code': 'VARCHAR', 'run_start_time': 'TIMESTAMP'}})
            WHERE lpad(fips_code, 5, '0') IN ({",".join(f"'{g}'" for g in geoids)})
              AND run_start_time >= DATE '{min(nights)}'
              AND run_start_time < DATE '{max(nights)}' + INTERVAL 1 DAY
        """).pl()
        grid = pl.DataFrame({"geoid": geoids}).join(pl.DataFrame({"night": nights}), how="cross")
        matched = (
            grid.join(overpass, on="geoid", how="left")
            .join(
                rows.with_columns(
                    night=pl.col("t").dt.date(),
                    hour=pl.col("t").dt.hour() + pl.col("t").dt.minute() / 60,
                ),
                on=["geoid", "night"],
                how="left",
            )
            .filter((pl.col("hour") - pl.col("overpass_utc")).abs() <= 0.5)
            .group_by("geoid", "night")
            .agg(customers_out=pl.col("out").mean())
        )
        return (
            grid.join(matched, on=["geoid", "night"], how="left")
            .join(mcc, on="geoid", how="left")
            .with_columns(pl.col("customers_out").fill_null(0.0))
            .with_columns(out_share=(pl.col("customers_out") / pl.col("customers")).clip(0, 1))
        )

    return (eaglei_at_overpass,)


@app.cell
def _(declared, duckdb, eaglei_at_overpass, heimdall_daily, pl, timedelta):
    comparison_storms = ["DR-4757", "DR-4721", "DR-4728", "AL022024", "DR-4804"]
    storm_pairs = []
    for event_s in comparison_storms:
        counties_s = declared.filter(pl.col("event_id") == event_s)
        nights_s = [counties_s["impact"].min() + timedelta(days=d) for d in range(1, 8)]
        light_s = duckdb.sql(f"""
            SELECT geoid, CAST(date AS DATE) AS night, light_ratio, valid_pixel_share
            FROM read_parquet('{heimdall_daily}')
            WHERE event_id = '{event_s}' AND declared
        """).pl()
        storm_pairs.append(
            light_s.join(counties_s.select("geoid", "impact"), on="geoid")
            .with_columns(days_after=(pl.col("night") - pl.col("impact")).dt.total_days())
            .filter(pl.col("days_after").is_between(1, 7) & (pl.col("valid_pixel_share") >= 0.5))
            .join(
                eaglei_at_overpass(counties_s["geoid"].to_list(), nights_s), on=["geoid", "night"]
            )
            .with_columns(deficit=(1 - pl.col("light_ratio")).clip(0, 1), event_id=pl.lit(event_s))
        )
    pairs = pl.concat(storm_pairs)
    storm_names = {
        "DR-4757": "DTE / SE Michigan, Aug 2023",
        "DR-4721": "Oklahoma, June 2023",
        "DR-4728": "Illinois, June 2023",
        "AL022024": "Hurricane Beryl, Texas, July 2024",
        "DR-4804": "Kentucky, May 2024",
    }
    per_storm_spearman = (
        pairs.group_by("event_id")
        .agg(
            clear_county_nights=pl.len(),
            spearman=pl.corr("deficit", "out_share", method="spearman"),
            mean_out_share=pl.col("out_share").mean(),
            mean_deficit=pl.col("deficit").mean(),
            deficit_where_under_1pct_out=pl.col("deficit")
            .filter(pl.col("out_share") < 0.01)
            .mean(),
            county_nights_under_1pct_out=(pl.col("out_share") < 0.01).sum(),
        )
        .with_columns(storm=pl.col("event_id").replace_strict(storm_names))
        .sort("spearman", descending=True)
    )
    per_storm_spearman
    return pairs, per_storm_spearman


@app.cell
def _(mo):
    mo.md(r"""
    Why the pooled number is near zero: each storm sits at its own level. On two storms
    (Illinois and Kentucky) Heimdall's counties read about half their usual brightness for
    the week after, even on county nights where EAGLE-I shows under 1% of customers out, while
    on Oklahoma they read near normal. Pooling stacks those offsets on top of each other, so
    the pooled rank correlation mostly measures which storm a county night came from. Centering
    each storm first (subtracting each storm's mean deficit and mean share out) and then ranking
    removes most of the offsets; the per-storm values, and their average weighted by clear
    county nights, are the honest summary.
    """)
    return


@app.cell
def _(outputs, pairs, per_storm_spearman, pl, plt):
    pooled_raw = pairs.select(pl.corr("deficit", "out_share", method="spearman")).item()
    centered = pairs.with_columns(
        deficit_c=pl.col("deficit") - pl.col("deficit").mean().over("event_id"),
        out_c=pl.col("out_share") - pl.col("out_share").mean().over("event_id"),
    )
    pooled_within = centered.select(pl.corr("deficit_c", "out_c", method="spearman")).item()
    weighted_mean = float(
        (per_storm_spearman["spearman"] * per_storm_spearman["clear_county_nights"]).sum()
        / per_storm_spearman["clear_county_nights"].sum()
    )
    print(
        f"pooled Spearman {pooled_raw:.3f} over {pairs.height} clear county nights; "
        f"within-storm pooled {pooled_within:.3f}; weighted mean of per-storm {weighted_mean:.3f}"
    )
    fig_sp, ax_sp = plt.subplots(figsize=(7, 5.2))
    for event_p in per_storm_spearman["event_id"]:
        sub = pairs.filter(pl.col("event_id") == event_p)
        rho = per_storm_spearman.filter(pl.col("event_id") == event_p)["spearman"].item()
        ax_sp.scatter(
            sub["out_share"] * 100,
            sub["deficit"] * 100,
            s=10,
            alpha=0.6,
            label=f"{event_p}: ρ = {rho:.2f}, n = {sub.height}",
        )
    ax_sp.set_xlabel("EAGLE-I customers out at overpass, % of county")
    ax_sp.set_ylabel("Night-light deficit (1 − light ratio), %")
    ax_sp.set_title(f"Clear county nights 1–7 after impact (pooled ρ = {pooled_raw:.2f})")
    ax_sp.legend(fontsize=8)
    fig_sp.tight_layout()
    fig_sp.savefig(outputs / "per_storm_spearman.png", dpi=110)
    per_storm_spearman.write_csv(outputs / "per_storm_spearman.csv")
    fig_sp
    return pooled_raw, pooled_within, weighted_mean


@app.cell
def _(
    corr_storms,
    data_dir,
    dte_results,
    fetch_seconds,
    jobs,
    json,
    meter_reporting,
    method_check,
    outputs,
    per_storm,
    per_storm_spearman,
    pooled_raw,
    pooled_within,
    started,
    time,
    visibility,
    weighted_mean,
):
    summary = {
        "dte_meter_reporting_at_peak_pct": meter_reporting,
        "dte_july_2026": dte_results,
        "first_two_nights": visibility,
        "per_storm_clear_share_correlation": round(corr_storms, 3),
        "storms_measured": per_storm.height,
        "method_check_vs_heimdall": method_check.to_dicts(),
        "per_storm_spearman": per_storm_spearman.to_dicts(),
        "pooled_spearman": round(pooled_raw, 3),
        "pooled_spearman_within_storm": round(pooled_within, 3),
        "weighted_mean_per_storm_spearman": round(weighted_mean, 3),
        "gibs_images_for_storms": len(jobs),
        "storm_fetch_seconds": fetch_seconds,
        "data_cache_megabytes": round(
            sum(p.stat().st_size for p in data_dir.rglob("*") if p.is_file()) / 1e6
        ),
        "run_seconds": round(time.time() - started),
        "cost_usd": 0,
    }
    (outputs / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return


@app.cell
def _(dte_results, mo, per_storm_spearman, pooled_raw, visibility, weighted_mean):
    _all = visibility["all"]
    _summer = visibility["summer_may_sep"]
    _n20 = dte_results["NOAA20"]
    _rhos = ", ".join(
        f"{r['storm']} {r['spearman']:.2f} (n = {r['clear_county_nights']})"
        for r in per_storm_spearman.iter_rows(named=True)
    )
    mo.md(f"""
    ## Result

    - **It's cloud, not the sensor.** On the same {_all["county_nights"]:,} first-two-night
      county nights after {_all["storms"]} storms, NOAA-20 had a clear reading on
      {_all["noaa20_clear"]:.1%} and S-NPP on {_all["snpp_clear"]:.1%}
      ({_all["snpp_clear_where_it_has_data"]:.1%} where S-NPP has data). The two agree on
      {_all["both_clear"] + _all["neither_clear"]:.0%} of county nights. In summer storms
      (May to September) it is {_summer["noaa20_clear"]:.1%} on NOAA-20.
    - **DTE, July 2026:** {_n20["tracts_clear_first_48h"]} of {_n20["tracts"]} tracts had a
      clear reading in the first 48 hours on either satellite. The first clear night was
      {_n20["first_clear_night"]}, {_n20["first_clear_hours"]:.0f} hours after the storm, when
      DTE's curve implies {_n20["dte_out_share_then"]:.1%} of its customers were still out.
    - **Where it can see:** {_rhos}. Pooled, {pooled_raw:.2f}; the weighted mean of the
      per-storm values is {weighted_mean:.2f}.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - **GIBS images aren't the HDF5 files.** Our cloud mask is the one GIBS publishes for each
      satellite; Heimdall used the quality flags inside Black Marble's own files. The method
      check above shows how far apart the two are.
    - **A clear county isn't a correct county.** Section 3 is about what night light says when
      it can see; sections 1 and 2 are only about whether it can see.
    - **Two nights is a fixed window.** A storm that reached a county late in the evening
      gets its first overpass a few hours later; one that arrived at dawn gets it almost a day
      later. Hours after impact vary by county.
    - **Section 3 rests on five storms** and Heimdall's S-NPP or NOAA-20 product per storm;
      it is not a rerun on NOAA-20 alone.
    """)
    return


if __name__ == "__main__":
    app.run()
