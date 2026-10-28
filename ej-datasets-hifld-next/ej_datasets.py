import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import hashlib
    import json
    import os
    import re
    import time
    import warnings
    import zipfile
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime
    from pathlib import Path

    import fsspec
    import geopandas as gpd
    import httpx
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import polars as pl
    import pyarrow.feather as feather
    import pyarrow.parquet as pq
    import pyogrio
    import pystac
    import rdata

    return (
        Path,
        ThreadPoolExecutor,
        datetime,
        feather,
        fsspec,
        gpd,
        hashlib,
        httpx,
        json,
        mo,
        np,
        os,
        pd,
        pl,
        plt,
        pq,
        pyogrio,
        pystac,
        rdata,
        re,
        time,
        warnings,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can the environmental-justice screening data be rebuilt as files HIFLD Next can host?

    EPA took EJScreen offline in February 2025 and the White House took down CEJST a month
    earlier. Copies survive in public archives, and Public Environmental Data Partners (PEDP)
    now maintains EJAM, EPA's multisite tool, with its own yearly pipeline that rebuilds
    EJScreen's block-group indicators from newer Census data.

    This notebook asks whether those copies can be turned into datasets shaped like a
    [HIFLD Next](https://hifld.publicenvirodata.org) entry, with a pipeline anyone can
    rerun: one GeoParquet file per dataset, a STAC record describing it, and checks that
    the files say what the sources say. It builds three datasets:

    1. **EPA EJScreen 2.3 (2024) block groups**, EPA's last official release (ACS 2018–2022).
    2. **PEDP EJAM v3.2024.0 block groups**, the newest public rebuild (ACS 2020–2024).
    3. **CEJST v2.0 census tracts**, the last release of the Climate and Economic Justice
       Screening Tool.

    Then it compares PEDP's rebuild with EPA's release, to show what changed.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The sources

    Every file is fetched when the notebook runs; nothing from a source is committed. Where
    the archive publishes an MD5 the download is checked against it. Every file gets a
    SHA-256 hash, which goes in the STAC record so a host can tell whether a source changed.

    - EPA's 2024 CSV comes from the **Harvard Dataverse** copy (CC0), because it holds the
      CSV as a single file. The Zenodo archive only has 5 GB zips of whole years, and EPA's own
      `gaftp.epa.gov` now returns 404.
    - EJAM's data is pinned to the **`v3.2024.0` release tag**. The block-group table
      `blockgroupstats` is an R `.rda` file in the EJAM repository, and the EJ indexes
      (`bgej.arrow`) are a release asset of the `ejamdata` repository. The same files at
      `v3.2022.3`, PEDP's rebuild of EPA's own ACS 2018–2022 vintage, are fetched for the
      comparison at the end.
    - CEJST v2.0 comes from the **EDGI copy on Zenodo**, which publishes MD5s and
      the tool's codebook. (The Harvard Dataverse copy has the same CSV but no checksums.)
    - Geometry comes from Census **cartographic boundary files** of the matching vintage for
      block groups (2022 for EPA, 2024 for EJAM). The four island territories aren't
      divided into block groups: EPA used 2022 Census places for American Samoa, Guam
      and the Northern Mariana Islands, and estates for the Virgin Islands, which only
      TIGER/Line publishes. CEJST uses 2010 tracts, which come from **TIGER/Line 2010**.
      The cartographic files leave out block groups that are all water.
    """)
    return


@app.cell
def _(Path, os, time):
    t_start = time.perf_counter()
    DATA_DIR = Path(os.environ.get("EJ_DATA_DIR", "data"))
    OUT_DIR = Path(os.environ.get("EJ_OUT_DIR", "outputs"))
    # Vector tiles take about six minutes per block-group dataset, so they are opt-in.
    MAKE_PMTILES = os.environ.get("EJ_PMTILES") == "1"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    EJAM_RAW = "https://raw.githubusercontent.com/Public-Environmental-Data-Partners/EJAM"
    EJAMDATA = "https://github.com/Public-Environmental-Data-Partners/ejamdata/releases/download"
    DATAVERSE = "https://dataverse.harvard.edu/api/access/datafile"
    ZENODO_CEJST = "https://zenodo.org/api/records/14675929/files"
    GENZ = "https://www2.census.gov/geo/tiger"
    TIGER2010 = "https://www2.census.gov/geo/tiger/TIGER2010/TRACT/2010"
    # The 50 states, DC, Puerto Rico and the four island territories CEJST covers.
    TRACT_STATES = sorted(
        {f"{n:02d}" for n in range(1, 57)} - {"03", "07", "14", "43", "52"}
        | {"60", "66", "69", "72", "78"}
    )

    sources = [
        {
            "key": "epa_2024_bg",
            "url": f"{DATAVERSE}/10775972",
            "file": "EJSCREEN_2024_BG_with_AS_CNMI_GU_VI.csv",
            "md5": "cd1e76219826c0110bc10c27059ddf93",
        },
        {
            "key": "epa_2024_columns",
            "url": f"{DATAVERSE}/10775980",
            "file": "EJScreen_2024_BG_Percentiles_Columns.xlsx",
            "md5": "33272c09b453036cb0f2d4965b93c271",
        },
        {
            "key": "epa_2024_bg_statepct",
            "url": f"{DATAVERSE}/10775971",
            "file": "EJSCREEN_2024_BG_StatePct_with_AS_CNMI_GU_VI.csv",
            "md5": "151e738e639cdc864a2d9c131004daef",
        },
        {
            "key": "cejst_v2",
            "url": f"{ZENODO_CEJST}/2.0-communities.csv/content",
            "file": "cejst_2.0-communities.csv",
            "md5": "d08e08e5e5aa08f1928f1a68cb602a2f",
        },
    ]
    for _tag in ["v3.2024.0", "v3.2022.3"]:
        sources += [
            {
                "key": f"ejam_{_tag}_bgs",
                "url": f"{EJAM_RAW}/{_tag}/data/blockgroupstats.rda",
                "file": f"ejam_{_tag}_blockgroupstats.rda",
            },
            {
                "key": f"ejam_{_tag}_bgej",
                "url": f"{EJAMDATA}/{_tag}/bgej.arrow",
                "file": f"ejam_{_tag}_bgej.arrow",
            },
        ]
        # The lookup tables EJAM turns raw values into national and state percentiles with.
        for _lookup in ["usastats", "statestats"]:
            sources.append(
                {
                    "key": f"ejam_{_tag}_{_lookup}",
                    "url": f"{EJAM_RAW}/{_tag}/data/{_lookup}.rda",
                    "file": f"ejam_{_tag}_{_lookup}.rda",
                }
            )
    sources.append(
        {
            "key": "ejam_v3.2024.0_headers",
            "url": f"{EJAM_RAW}/v3.2024.0/data/map_headernames.rda",
            "file": "ejam_v3.2024.0_map_headernames.rda",
        }
    )
    for _year in ["2022", "2024"]:
        sources.append(
            {
                "key": f"cb_{_year}_bg",
                "url": f"{GENZ}/GENZ{_year}/shp/cb_{_year}_us_bg_500k.zip",
                "file": f"cb_{_year}_us_bg_500k.zip",
            }
        )
    for _layer in ["60_place", "66_place", "69_place"]:
        sources.append(
            {
                "key": f"cb_2022_{_layer}",
                "url": f"{GENZ}/GENZ2022/shp/cb_2022_{_layer}_500k.zip",
                "file": f"cb_2022_{_layer}_500k.zip",
            }
        )
    # The Virgin Islands' 416 estates have no cartographic file, only TIGER/Line.
    sources.append(
        {
            "key": "tl_2022_78_estate",
            "url": f"{GENZ}/TIGER2022/ESTATE/tl_2022_78_estate.zip",
            "file": "tl_2022_78_estate.zip",
        }
    )
    for _st in TRACT_STATES:
        sources.append(
            {
                "key": f"tl_2010_{_st}_tract10",
                "url": f"{TIGER2010}/tl_2010_{_st}_tract10.zip",
                "file": f"tl_2010_{_st}_tract10.zip",
            }
        )
    return DATA_DIR, MAKE_PMTILES, OUT_DIR, ZENODO_CEJST, sources, t_start


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Download and verify

    Each file is streamed to disk once and reused on later runs. Downloads retry up to four
    times with backoff, and a file whose MD5 doesn't match the archive's stops the run.
    """)
    return


@app.cell
def _(DATA_DIR, Path, hashlib, httpx, time):
    def fetch(source: dict) -> dict:
        dest: Path = DATA_DIR / source["file"]
        if not dest.exists():
            part = dest.with_name(dest.name + ".part")
            for attempt in range(4):
                try:
                    with httpx.stream(
                        "GET", source["url"], follow_redirects=True, timeout=300
                    ) as response:
                        response.raise_for_status()
                        with part.open("wb") as out:
                            for chunk in response.iter_bytes(2**20):
                                out.write(chunk)
                    break
                except httpx.HTTPError:
                    if attempt == 3:
                        raise
                    time.sleep(2**attempt)
            part.rename(dest)
        sha256, md5 = hashlib.sha256(), hashlib.md5()
        with dest.open("rb") as f:
            for block in iter(lambda: f.read(2**22), b""):
                sha256.update(block)
                md5.update(block)
        expected = source.get("md5")
        if expected and md5.hexdigest() != expected:
            raise ValueError(f"{dest.name}: MD5 {md5.hexdigest()} != published {expected}")
        return {
            **source,
            "path": str(dest),
            "bytes": dest.stat().st_size,
            "sha256": sha256.hexdigest(),
            "md5_checked": bool(expected),
        }

    return (fetch,)


@app.cell
def _(ThreadPoolExecutor, fetch, pl, sources, time):
    _t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as _pool:
        manifest = {row["key"]: row for row in _pool.map(fetch, sources)}
    t_download = time.perf_counter() - _t
    manifest_table = pl.DataFrame(
        [{k: v for k, v in row.items() if k != "path"} for row in manifest.values()]
    )
    print(
        f"{len(manifest)} files, {manifest_table['bytes'].sum() / 1e9:.2f} GB, "
        f"{manifest_table['md5_checked'].sum()} checked against a published MD5, "
        f"{t_download:.0f} s"
    )
    manifest_table.select("key", "bytes", "md5_checked", "sha256").head(12)
    return manifest, t_download


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Read the sources

    EPA's CSV and CEJST's CSV are read with every row used for type inference, with the
    IDs kept as text so leading zeros survive. EJAM's block-group table is an R data file;
    [`rdata`](https://rdata.readthedocs.io) reads it without R but takes about five minutes
    per vintage, so the result is cached as Parquet next to the download, keyed by its hash.
    """)
    return


@app.cell
def _(manifest, pl):
    epa_raw = pl.read_csv(
        manifest["epa_2024_bg"]["path"], infer_schema_length=None, schema_overrides={"ID": pl.Utf8}
    )
    cejst_raw = pl.read_csv(
        manifest["cejst_v2"]["path"],
        infer_schema_length=None,
        schema_overrides={"Census tract 2010 ID": pl.Utf8},
    )
    print(f"EPA 2024: {epa_raw.shape}; CEJST v2.0: {cejst_raw.shape}")
    return cejst_raw, epa_raw


@app.cell
def _(Path, feather, manifest, pl, rdata, warnings):
    def read_rda_table(key: str, name: str) -> pl.DataFrame:
        source = manifest[key]
        cache = Path(source["path"]).with_suffix(f".{source['sha256'][:12]}.parquet")
        if not cache.exists():
            with warnings.catch_warnings():
                # rdata has no data.table constructor and falls back to data.frame.
                warnings.simplefilter("ignore", UserWarning)
                frame = rdata.read_rda(source["path"], default_encoding="utf8")[name]
            pl.from_pandas(frame).write_parquet(cache)
        return pl.read_parquet(cache)

    def read_ejam(tag: str) -> pl.DataFrame:
        bgs = read_rda_table(f"ejam_{tag}_bgs", "blockgroupstats")
        bgej = pl.from_arrow(feather.read_table(manifest[f"ejam_{tag}_bgej"]["path"]))
        assert isinstance(bgej, pl.DataFrame)
        assert bgej.height == bgs.height, f"{tag}: bgej has {bgej.height} rows, bgs {bgs.height}"
        return bgs.join(bgej.drop("bgid", "ST", "pop"), on="bgfips", how="left", validate="1:1")

    return read_ejam, read_rda_table


@app.cell
def _(pl, read_ejam, read_rda_table):
    ejam_raw = read_ejam("v3.2024.0")
    ejam_2022_raw = read_ejam("v3.2022.3")
    headers = read_rda_table("ejam_v3.2024.0_headers", "map_headernames")
    lookups = {
        (tag, name): read_rda_table(f"ejam_{tag}_{name}", name)
        for tag in ["v3.2024.0", "v3.2022.3"]
        for name in ["usastats", "statestats"]
    }
    ejam_all_null = [c for c in ejam_raw.columns if ejam_raw[c].null_count() == ejam_raw.height]
    print(
        f"EJAM v3.2024.0: {ejam_raw.shape}, of which {len(ejam_all_null)} columns are empty; "
        f"EJAM v3.2022.3: {ejam_2022_raw.shape}"
    )
    pl.DataFrame({"empty EJAM v3.2024.0 columns": ejam_all_null}).head(8)
    return ejam_2022_raw, ejam_all_null, ejam_raw, headers, lookups


@app.cell
def _(mo):
    mo.md(r"""
    `blockgroupstats` in v3.2024.0 still carries EPA-named columns (`ID`, `PM25`, `P_PM25`
    and so on) that are empty in every row: they were filled in the v3.2022 releases from
    EPA's file and are blank once the table is rebuilt from new Census data. They are dropped
    from the output, and the comparison below uses EJAM's own column names instead.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Normalise

    Every dataset gets the same shape: a text `geoid` first, then the source's columns
    renamed to lower snake case, then geometry. Block-group IDs are 12 digits; EPA's CSV
    stored them as numbers, so 11-digit ones get their leading zero back. The four island
    territories use Census place (7-digit) and estate (10-digit) IDs instead,
    which EPA and EJAM both keep as they are. CEJST tract IDs are 11 digits.

    The column descriptions and units for the STAC record come from each source's own
    documentation: EPA's column list, EJAM's `map_headernames` table and CEJST's codebook.
    """)
    return


@app.cell
def _(pl, re):
    def snake(name: str) -> str:
        return re.sub(r"[^0-9a-z]+", "_", name.lower()).strip("_")

    def renamed(columns: list[str], id_column: str) -> dict[str, str]:
        mapping = {c: "geoid" if c == id_column else snake(c) for c in columns}
        assert len(set(mapping.values())) == len(mapping), "two columns normalise to one name"
        return mapping

    def pad_bg(column: str) -> pl.Expr:
        ids = pl.col(column)
        return pl.when(ids.str.len_chars() == 11).then(ids.str.zfill(12)).otherwise(ids)

    return pad_bg, renamed


@app.cell
def _(ZENODO_CEJST, fsspec, manifest, pd, pl, zipfile):
    epa_docs = pd.read_excel(manifest["epa_2024_columns"]["path"], header=1)
    epa_descriptions = dict(zip(epa_docs["Column Names"], epa_docs["Description"], strict=True))

    # The codebook ships only inside CEJST's 374 MB shapefile zip; reading the zip over HTTP
    # range requests fetches just the 42 kB codebook.
    _url = f"{ZENODO_CEJST}/2.0-shapefile-codebook.zip/content"
    with fsspec.open(_url) as _remote, zipfile.ZipFile(_remote) as _zip:
        cejst_codebook = pl.read_csv(_zip.read("2.0-codebook.csv"), infer_schema_length=0)
    cejst_codebook = cejst_codebook.filter(pl.col("csv_label").is_not_null())
    print(f"EPA column docs: {len(epa_descriptions)}; CEJST codebook rows: {cejst_codebook.height}")
    return cejst_codebook, epa_descriptions


@app.cell
def _(
    cejst_codebook,
    cejst_raw,
    ejam_all_null,
    ejam_raw,
    epa_descriptions,
    epa_raw,
    headers,
    pad_bg,
    pl,
    renamed,
):
    by_csvname = {row["csvname"]: row for row in headers.iter_rows(named=True) if row["csvname"]}
    by_rname = {row["rname"]: row for row in headers.iter_rows(named=True) if row["rname"]}
    by_csv_label = {row["csv_label"]: row for row in cejst_codebook.iter_rows(named=True)}

    epa_names = renamed(epa_raw.columns, "ID")
    epa = epa_raw.with_columns(pad_bg("ID")).rename(epa_names)
    epa_docs_by_out = {
        out: {
            "description": epa_descriptions.get(src) or by_csvname.get(src, {}).get("longname"),
            "unit": by_csvname.get(src, {}).get("units") or None,
            "source_name": src,
        }
        for src, out in epa_names.items()
    }

    ejam_keep = [c for c in ejam_raw.columns if c not in ejam_all_null]
    ejam_names = renamed(ejam_keep, "bgfips")
    ejam = ejam_raw.select(ejam_keep).rename(ejam_names).select("geoid", pl.exclude("geoid"))
    ejam_docs_by_out = {
        out: {
            "description": by_rname.get(src, {}).get("longname"),
            "unit": by_rname.get(src, {}).get("units") or None,
            "source_name": src,
        }
        for src, out in ejam_names.items()
    }

    cejst_names = renamed(cejst_raw.columns, "Census tract 2010 ID")
    cejst = cejst_raw.rename(cejst_names)
    cejst_docs_by_out = {
        out: {
            "description": by_csv_label.get(src, {}).get("Description") or src,
            "unit": by_csv_label.get(src, {}).get("csv_field_type"),
            "source_name": src,
        }
        for src, out in cejst_names.items()
    }
    return (
        cejst,
        cejst_docs_by_out,
        cejst_names,
        ejam,
        ejam_docs_by_out,
        ejam_names,
        epa,
        epa_docs_by_out,
        epa_names,
    )


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Add EJScreen's percentiles

    EJScreen's maps colour each block group by its percentile, nationally or within its
    state, but EJAM's tables hold only raw values: EJAM ranks a value when it runs a report,
    by looking it up in `usastats` and `statestats`. Each holds, for every indicator, the
    value at percentiles 0 to 100, for the whole country and for each state.

    This section adds EPA's 50 percentile columns to the v3.2024.0 file the way EJAM's own
    export (`calc_ejscreen_export()`) builds them, ported from its R code:

    - **The lookup rule** is `pctile_from_raw_lookup()`. A value gets the highest
      percentile whose cutoff it reaches; a value exactly equal to a cutoff shared by
      several percentiles gets the lowest of them; zero or below is the 0th percentile.
    - **State percentiles** look up the value in the block group's state. The demographic
      indexes and EJ indexes use their state versions, which EJAM computes from state
      averages; the other indicators use the same value as nationally.
    - **Two export adjustments.** Unemployment counts as 0% (not missing) where nobody is
      in the labour force, and its cutoffs are recomputed from those adjusted values.
      Disability is rounded to 12 significant digits before the lookup.
    - **Map bins and text** (`B_`, `T_`) come from the national percentile with EJScreen's
      cutpoints: bins 1 to 9 by tens, 10 for the 90–94th and 11 for the 95th and above.

    EJAM's export writes national and state percentiles to two separate files under the
    same names, as EPA did. Here both go in one file: `p_` is national and `s_p_` state.
    """)
    return


@app.cell
def _(headers, np, pl):
    # EPA's 50 percentile columns and the EJAM column each one ranks, from map_headernames.
    pctile_fields = (
        headers.filter(
            pl.col("rname").str.starts_with("pctile.")
            & pl.col("ejscreen_indicator").str.starts_with("P_")
        )
        .select(raw=pl.col("rname").str.strip_prefix("pctile."), field="ejscreen_indicator")
        .unique(maintain_order=True)
    )
    STATE_VERSION = {
        "Demog.Index": "Demog.Index.State",
        "Demog.Index.Supp": "Demog.Index.Supp.State",
    }

    def lookup_pctile(values: np.ndarray, cutoffs: np.ndarray) -> np.ndarray:
        # Python version of EJAM's pctile_from_raw_lookup() for one zone. cutoffs[i] is the
        # value at percentile i, so the count of cutoffs at or below a value, minus one, is
        # the highest percentile it reaches; an exact tie takes the first tied percentile.
        assert len(cutoffs) == 101 and np.all(np.diff(cutoffs) >= 0)
        if np.isnan(cutoffs).any():
            return np.full(len(values), np.nan)
        first = np.searchsorted(cutoffs, values, "left")
        reached = np.searchsorted(cutoffs, values, "right")
        pctile = np.where(first < reached, first, reached - 1).clip(0).astype(float)
        pctile[values <= 0] = 0
        pctile[np.isnan(values)] = np.nan
        return pctile

    def signif(values: np.ndarray, digits: int) -> np.ndarray:
        # R's signif(): round to a number of significant digits.
        with np.errstate(divide="ignore", invalid="ignore"):
            scale = 10.0 ** (digits - 1 - np.floor(np.log10(np.abs(values))))
        return np.where(np.isfinite(scale), np.round(values * scale) / scale, values)

    def ejscreen_percentiles(
        bg: pl.DataFrame, usastats: pl.DataFrame, statestats: pl.DataFrame
    ) -> pl.DataFrame:
        bg = bg.with_columns(
            pctunemployed=pl.when(
                pl.col("pctunemployed").is_null()
                & (pl.col("laborforce_universe") == 0)
                & (pl.col("unemployedbase") == 0)
            )
            .then(0.0)
            .otherwise(pl.col("pctunemployed"))
        )
        states = bg["ST"].to_numpy()
        tables = {
            region: frame.filter(pl.col("PCTILE") != "mean")
            for (region,), frame in pl.concat([usastats, statestats], how="diagonal")
            .select(pl.exclude("OBJECTID"))
            .partition_by("REGION", as_dict=True)
            .items()
        }
        assert all(t["PCTILE"].to_list() == [str(i) for i in range(101)] for t in tables.values())

        def values_of(column: str) -> np.ndarray:
            return bg[column].cast(pl.Float64).fill_nan(None).to_numpy().astype(float)

        def cutoffs(region: str, column: str, values: np.ndarray) -> np.ndarray:
            if column == "pctunemployed":
                # EJAM recomputes these cutoffs from the adjusted values, by R's default
                # (type 7) quantile, which is numpy's default too.
                return np.nanquantile(values, np.arange(101) / 100)
            return tables[region][column].cast(pl.Float64).fill_nan(None).to_numpy().astype(float)

        def ranked(values: np.ndarray, cut: np.ndarray, raw: str) -> np.ndarray:
            if raw == "pctdisability":
                return lookup_pctile(signif(values, 12), signif(cut, 12))
            return lookup_pctile(values, cut)

        out = {"bgfips": bg["bgfips"]}
        for raw, field in pctile_fields.iter_rows():
            values = values_of(raw)
            out[field] = ranked(values, cutoffs("USA", raw, values), raw)
            state_raw = STATE_VERSION.get(raw, f"state.{raw}" if raw.startswith("EJ.") else raw)
            state_values = values_of(state_raw)
            by_state = np.full(len(state_values), np.nan)
            for state in np.unique(states[states != None]):  # noqa: E711
                rows = states == state
                if state in tables and not np.isnan(state_values[rows]).all():
                    cut = cutoffs(state, state_raw, state_values[rows])
                    by_state[rows] = ranked(state_values[rows], cut, raw)
            out[f"S_{field}"] = by_state
        frame = pl.DataFrame(out).with_columns(pl.exclude("bgfips").cast(pl.Int32))
        # Bins 1-9 by tens, 10 for the 90-94th percentile and 11 for the 95th and above.
        bins = {
            f"B_{f.removeprefix('P_')}": (pl.col(f) // 10 + 1).clip(upper_bound=10)
            + (pl.col(f) >= 95).cast(pl.Int32)
            for f in pctile_fields["field"]
        }
        texts = {
            f"T_{f.removeprefix('P_')}": pl.col(f).cast(pl.Utf8) + " %ile"
            for f in pctile_fields["field"]
        }
        return frame.with_columns(**bins, **texts)

    print(f"{pctile_fields.height} percentile columns")
    pctile_fields.head(5)
    return ejscreen_percentiles, pctile_fields


@app.cell
def _(mo):
    mo.md(r"""
    **The check.** EJAM's v3.2022.3 is PEDP's rebuild of EPA's own ACS 2018–2022 vintage,
    and section 8 shows its raw values match EPA's. So the same code run on v3.2022.3 and
    its lookup tables should reproduce EPA 2024's `P_` columns, nationally from EPA's main
    file and by state from EPA's `StatePct` file. A percentile is an integer, so a match
    means exactly equal, or missing in both.
    """)
    return


@app.cell
def _(
    OUT_DIR, ejam_2022_raw, ejscreen_percentiles, lookups, manifest, pad_bg, pctile_fields, pl, time
):
    def epa_columns(key: str) -> pl.DataFrame:
        frame = pl.read_csv(
            manifest[key]["path"],
            columns=["ID", *pctile_fields["field"], "B_PM25"],
            infer_schema_length=None,
            schema_overrides={"ID": pl.Utf8},
        )
        return frame.with_columns(pad_bg("ID"))

    def check(ours: pl.DataFrame, epa: pl.DataFrame, prefix: str, label: str) -> pl.DataFrame:
        joined = epa.join(ours, left_on="ID", right_on="bgfips", how="inner", suffix="__ours")
        rows = []
        for field in pctile_fields["field"]:
            theirs = joined[field]
            mine = joined[f"{prefix}{field}" + ("__ours" if not prefix else "")]
            same = theirs.eq_missing(mine)
            rows.append(
                {
                    "check": label,
                    "field": field,
                    "rows": joined.height,
                    "share_exact": float(same.mean() or 0.0),
                    "mismatches": int((~same).sum()),
                    "max_abs_diff": int((theirs - mine).abs().max() or 0),
                    "missing_in_epa_only": int((theirs.is_null() & mine.is_not_null()).sum()),
                    "missing_in_ours_only": int((mine.is_null() & theirs.is_not_null()).sum()),
                }
            )
        return pl.DataFrame(rows)

    _t = time.perf_counter()
    pctiles_2022 = ejscreen_percentiles(
        ejam_2022_raw, lookups[("v3.2022.3", "usastats")], lookups[("v3.2022.3", "statestats")]
    )
    pctile_seconds = time.perf_counter() - _t
    _epa_national = epa_columns("epa_2024_bg")
    pctile_check = pl.concat(
        [
            check(pctiles_2022, _epa_national, "", "national (P_)"),
            check(pctiles_2022, epa_columns("epa_2024_bg_statepct"), "S_", "state (StatePct P_)"),
        ]
    )
    pctile_check.write_csv(OUT_DIR / "percentile_check.csv")
    _bins = _epa_national.join(pctiles_2022, left_on="ID", right_on="bgfips", suffix="__ours")
    bins_match = float(_bins["B_PM25"].eq_missing(_bins["B_PM25__ours"]).mean() or 0.0)
    print(f"percentiles for one vintage in {pctile_seconds:.0f} s; B_PM25 matches {bins_match:.4%}")
    pctile_check.group_by("check").agg(
        pl.len().alias("fields"),
        (pl.col("share_exact") == 1).sum().alias("fields_all_exact"),
        pl.col("share_exact").min().alias("lowest_share_exact"),
        pl.col("mismatches").sum(),
        pl.col("max_abs_diff").max(),
    ).sort("check")
    return bins_match, pctile_check, pctile_seconds


@app.cell
def _(mo):
    mo.md(r"""
    The same code then ranks v3.2024.0's values against v3.2024.0's own lookup tables, and
    the 200 new columns join the file by block-group ID. Each gets a description in the STAC
    record naming the EJAM column it ranks and the lookup it came from.
    """)
    return


@app.cell
def _(ejam, ejam_raw, ejscreen_percentiles, lookups, pctile_fields, pl):
    _pctiles = ejscreen_percentiles(
        ejam_raw, lookups[("v3.2024.0", "usastats")], lookups[("v3.2024.0", "statestats")]
    )
    _pctiles = _pctiles.rename({c: c.lower() for c in _pctiles.columns}).rename({"bgfips": "geoid"})
    ejam_with_pctiles = ejam.join(_pctiles, on="geoid", how="left", validate="1:1")
    pctile_docs = {}
    for _raw, _field in pctile_fields.iter_rows():
        _code = _field.removeprefix("P_")
        _what = f"EJAM `{_raw}`"
        pctile_docs |= {
            _field.lower(): {
                "description": f"National percentile of {_what}, from EJAM's usastats",
                "unit": "percentile",
                "source_name": f"pctile.{_raw}",
            },
            f"s_{_field.lower()}": {
                "description": f"State percentile of {_what} (state version for indexes), "
                "from EJAM's statestats",
                "unit": "percentile",
                "source_name": f"state.pctile.{_raw}",
            },
            f"b_{_code.lower()}": {
                "description": f"EJScreen map bin (1-11) of the national percentile of {_what}",
                "unit": None,
                "source_name": f"B_{_code}",
            },
            f"t_{_code.lower()}": {
                "description": f"EJScreen map text of the national percentile of {_what}",
                "unit": None,
                "source_name": f"T_{_code}",
            },
        }
    assert set(pctile_docs) == set(_pctiles.columns) - {"geoid"}
    print(f"v3.2024.0 gains {len(pctile_docs)} columns: {ejam_with_pctiles.shape}")
    ejam_with_pctiles.select("geoid", "st", "pm", "p_pm25", "s_p_pm25", "b_pm25", "t_pm25").head()
    return ejam_with_pctiles, pctile_docs


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Join geometry

    The block-group tables carry no shapes, so geometry is joined from Census boundary files
    by ID and reprojected from NAD83 to WGS 84 (EPSG:4326). Rows are kept even when no
    shape matches, so the row count always equals the source's, and the unmatched rows are
    counted. Census land area (`ALAND`) is carried along to check that each shape landed
    on the right row.
    """)
    return


@app.cell
def _(gpd, manifest, pd):
    def read_shapes(keys: list[str], id_column: str, area_column: str) -> gpd.GeoDataFrame:
        frames = [gpd.read_file(manifest[k]["path"]).to_crs(4326) for k in keys]
        shapes = pd.concat(frames, ignore_index=True)
        shapes = shapes.rename(columns={id_column: "geoid", area_column: "census_aland"})
        shapes = gpd.GeoDataFrame(
            shapes[["geoid", "census_aland", "geometry"]], geometry="geometry", crs=4326
        )
        assert shapes["geoid"].is_unique, "duplicate IDs in the boundary files"
        return shapes

    territories = ["cb_2022_60_place", "cb_2022_66_place", "cb_2022_69_place", "tl_2022_78_estate"]
    bg_2022 = read_shapes(["cb_2022_bg", *territories], "GEOID", "ALAND")
    bg_2024 = read_shapes(["cb_2024_bg", *territories], "GEOID", "ALAND")
    tracts_2010 = read_shapes(
        [k for k in manifest if k.startswith("tl_2010_")], "GEOID10", "ALAND10"
    )
    print(f"shapes: {len(bg_2022)} BG 2022, {len(bg_2024)} BG 2024, {len(tracts_2010)} tracts 2010")
    return bg_2022, bg_2024, tracts_2010


@app.cell
def _(gpd, pl):
    def attach(table: pl.DataFrame, shapes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        frame = table.to_pandas(use_pyarrow_extension_array=True)
        frame["geoid"] = frame["geoid"].astype(str)
        merged = frame.merge(shapes, on="geoid", how="left", validate="1:1")
        assert len(merged) == table.height
        return gpd.GeoDataFrame(merged, geometry="geometry", crs=4326)

    def coverage(gdf: gpd.GeoDataFrame, state_column: str) -> pl.DataFrame:
        missing = gdf[gdf.geometry.isna()]
        return (
            pl.from_pandas(missing[[state_column]].astype(str))
            .group_by(state_column)
            .len("rows_without_shape")
            .sort("rows_without_shape", descending=True)
        )

    return attach, coverage


@app.cell
def _(attach, bg_2022, bg_2024, cejst, coverage, ejam_with_pctiles, epa, tracts_2010):
    epa_gdf = attach(epa, bg_2022)
    ejam_gdf = attach(ejam_with_pctiles, bg_2024)
    cejst_gdf = attach(cejst, tracts_2010)
    unmatched = {
        "epa": coverage(epa_gdf, "st_abbrev"),
        "ejam": coverage(ejam_gdf, "st"),
        "cejst": coverage(cejst_gdf, "state_territory"),
    }
    for _name, _table in unmatched.items():
        print(_name, "rows without a shape:", _table["rows_without_shape"].sum())
    unmatched["epa"].head(10)
    return cejst_gdf, ejam_gdf, epa_gdf, unmatched


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Write GeoParquet and a STAC record

    Each dataset is written as one GeoParquet file (zstd, with a bounding-box column so
    readers can skip row groups), optionally (`EJ_PMTILES=1`) a PMTiles vector-tile file of
    a few headline columns for maps, and a STAC 1.1 Collection shaped like a HIFLD Next
    dataset version: title, description, providers, licence, extent, a version, every column
    with type, description, unit and null count (STAC's table extension), and assets with
    size and SHA-256 (the file extension). The source files are linked as `derived_from`
    with their own hashes.
    """)
    return


@app.cell
def _(MAKE_PMTILES, OUT_DIR, hashlib, json, pq, pyogrio, pystac, time):
    def sha256_of(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(2**22), b""):
                digest.update(block)
        return digest.hexdigest()

    def file_fields(path: str) -> dict:
        # file:checksum is a multihash: 0x12 (SHA-256), 0x20 (32 bytes), then the digest.
        size = OUT_DIR.joinpath(path).stat().st_size
        return {"file:size": size, "file:checksum": "1220" + sha256_of(str(OUT_DIR / path))}

    def write_dataset(gdf, spec: dict, docs: dict, sources: list[dict]) -> dict:
        slug = spec["slug"]
        parquet_name, tiles_name = f"{slug}.parquet", f"{slug}.pmtiles"
        gdf.to_parquet(OUT_DIR / parquet_name, compression="zstd", write_covering_bbox=True)
        tiles_seconds = None
        if MAKE_PMTILES:
            started = time.perf_counter()
            tiles = gdf[[*spec["tile_columns"], "geometry"]]
            numeric = {c: "float64" for c in spec["tile_columns"][1:]}
            tiles = tiles[tiles.geometry.notna()].astype(numeric)
            pyogrio.write_dataframe(
                tiles,
                OUT_DIR / tiles_name,
                driver="PMTiles",
                layer=slug,
                dataset_options={"MINZOOM": 2, "MAXZOOM": 10},
            )
            tiles_seconds = round(time.perf_counter() - started)
        columns = [
            {
                "name": field.name,
                "type": "geometry" if field.name == "geometry" else str(field.type),
                "description": docs.get(field.name, {}).get("description") or field.name,
                "unit": docs.get(field.name, {}).get("unit"),
                "source_name": docs.get(field.name, {}).get("source_name"),
                "null_count": int(gdf[field.name].isna().sum()),
            }
            for field in pq.read_schema(OUT_DIR / parquet_name)
            if field.name in gdf.columns
        ]
        collection = pystac.Collection(
            id=f"ej-screening/{slug}/{spec['version']}",
            title=spec["title"],
            description=spec["description"],
            license=spec["license"],
            keywords=["Environmental Justice", "Public Health", "Demographics"],
            providers=[
                pystac.Provider(name=spec["producer"], roles=["producer", "licensor"]),
                pystac.Provider(name=spec["archive"], roles=["host"], url=spec["archive_url"]),
                pystac.Provider(
                    name="HIFLD Next", roles=["host"], url="https://hifld.publicenvirodata.org"
                ),
            ],
            extent=pystac.Extent(
                pystac.SpatialExtent([list(gdf.total_bounds)]),
                pystac.TemporalExtent([[spec["start"], spec["end"]]]),
            ),
            stac_extensions=[
                "https://stac-extensions.github.io/file/v2.1.0/schema.json",
                "https://stac-extensions.github.io/version/v1.2.0/schema.json",
                "https://stac-extensions.github.io/table/v1.2.0/schema.json",
            ],
            extra_fields={
                "version": spec["version"],
                "table:columns": columns,
                "table:row_count": len(gdf),
                "table:primary_geometry": "geometry",
                "hifld:agency": spec["producer"],
                "hifld:feature_count": len(gdf),
                "hifld:feature_id_column": "geoid",
                "hifld:geometry_column": "geometry",
                "hifld:geometry_type": "/".join(sorted(gdf.geometry.dropna().geom_type.unique())),
                "hifld:spatial_status": "spatial",
                "hifld:quality": {
                    "null_geometry_count": int(gdf.geometry.isna().sum()),
                    "invalid_geometry_count": int((~gdf.geometry.dropna().is_valid).sum()),
                },
            },
        )
        collection.add_asset(
            "geoparquet",
            pystac.Asset(
                href=f"./{parquet_name}",
                media_type="application/vnd.apache.parquet",
                roles=["data"],
                title=parquet_name,
                extra_fields=file_fields(parquet_name),
            ),
        )
        if MAKE_PMTILES:
            collection.add_asset(
                "pmtiles",
                pystac.Asset(
                    href=f"./{tiles_name}",
                    media_type="application/vnd.pmtiles",
                    roles=["visual"],
                    title=f"{tiles_name} ({', '.join(spec['tile_columns'][1:])})",
                    extra_fields=file_fields(tiles_name),
                ),
            )
        for source in sources:
            collection.add_link(
                pystac.Link(
                    rel="derived_from",
                    target=source["url"],
                    title=source["file"],
                    extra_fields={
                        "file:size": source["bytes"],
                        "file:checksum": "1220" + source["sha256"],
                    },
                )
            )
        collection.validate()
        stac_path = OUT_DIR / f"{slug}.collection.json"
        stac_path.write_text(json.dumps(collection.to_dict(include_self_link=False), indent=1))
        return {
            "dataset": slug,
            "rows": len(gdf),
            "columns": gdf.shape[1],
            "geoparquet_mb": round((OUT_DIR / parquet_name).stat().st_size / 1e6, 1),
            "pmtiles_mb": round((OUT_DIR / tiles_name).stat().st_size / 1e6, 1)
            if MAKE_PMTILES
            else None,
            "pmtiles_seconds": tiles_seconds,
            "stac": str(stac_path),
        }

    return (write_dataset,)


@app.cell
def _(
    cejst_docs_by_out,
    cejst_gdf,
    datetime,
    ejam_docs_by_out,
    ejam_gdf,
    epa_docs_by_out,
    epa_gdf,
    manifest,
    pctile_docs,
    pl,
    time,
    write_dataset,
):
    _t = time.perf_counter()
    _bg_shapes = [manifest[k] for k in manifest if k.startswith(("cb_2022_", "tl_2022_"))]
    _specs = [
        (
            epa_gdf,
            {
                "slug": "epa-ejscreen-2024-block-groups",
                "version": "2.3",
                "title": "EJScreen 2.3 (2024) block groups, EPA",
                "description": "EPA's last official EJScreen release: environmental, "
                "demographic and EJ index values with national percentiles for every block "
                "group (ACS 2018-2022, 2022 Census geography) and the four island territories.",
                "license": "CC0-1.0",
                "producer": "Environmental Protection Agency",
                "archive": "Harvard Dataverse (doi:10.7910/DVN/RLR5AX)",
                "archive_url": "https://doi.org/10.7910/DVN/RLR5AX",
                "start": datetime(2018, 1, 1),
                "end": datetime(2022, 12, 31),
                "tile_columns": ["geoid", "pm25", "p_d2_pm25", "demogidx_2"],
            },
            epa_docs_by_out,
            [manifest["epa_2024_bg"], manifest["epa_2024_columns"], *_bg_shapes],
        ),
        (
            ejam_gdf,
            {
                "slug": "pedp-ejam-acs2024-block-groups",
                "version": "v3.2024.0",
                "title": "EJScreen-style block groups, ACS 2020-2024 (PEDP EJAM v3.2024.0)",
                "description": "PEDP's rebuild of EJScreen's block-group indicators and EJ "
                "indexes from ACS 2020-2024, from EJAM's blockgroupstats and bgej datasets.",
                "license": "MIT",
                "producer": "Public Environmental Data Partners (EJAM)",
                "archive": "EJAM and ejamdata on GitHub",
                "archive_url": "https://github.com/Public-Environmental-Data-Partners/ejamdata",
                "start": datetime(2020, 1, 1),
                "end": datetime(2024, 12, 31),
                "tile_columns": ["geoid", "pm", "ej_disparity_pm_eo", "p_d2_pm25", "demog_index"],
            },
            ejam_docs_by_out | pctile_docs,
            [
                manifest["ejam_v3.2024.0_bgs"],
                manifest["ejam_v3.2024.0_bgej"],
                manifest["ejam_v3.2024.0_headers"],
                manifest["ejam_v3.2024.0_usastats"],
                manifest["ejam_v3.2024.0_statestats"],
                manifest["cb_2024_bg"],
                *_bg_shapes[1:],
            ],
        ),
        (
            cejst_gdf,
            {
                "slug": "cejst-v2-census-tracts",
                "version": "2.0",
                "title": "Climate and Economic Justice Screening Tool v2.0 census tracts",
                "description": "CEJST v2.0 (December 2024): burden indicators, thresholds and "
                "disadvantaged status for every 2010 census tract.",
                "license": "other",
                "producer": "Council on Environmental Quality",
                "archive": "EDGI on Zenodo (doi:10.5281/zenodo.14675929)",
                "archive_url": "https://doi.org/10.5281/zenodo.14675929",
                "start": datetime(2015, 1, 1),
                "end": datetime(2019, 12, 31),
                "tile_columns": [
                    "geoid",
                    "total_threshold_criteria_exceeded",
                    "total_population",
                ],
            },
            cejst_docs_by_out,
            [manifest["cejst_v2"], *[manifest[k] for k in manifest if k.startswith("tl_2010_")]],
        ),
    ]
    outputs = pl.DataFrame([write_dataset(*_spec) for _spec in _specs])
    t_write = time.perf_counter() - _t
    outputs
    return outputs, t_write


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Validate against the sources

    The written files are read back and checked against the source tables as first read:
    row counts, unique IDs, null counts column by column, and every value in 2,000 random
    rows. For block groups, the Census land area of the joined shape is compared with the
    land area the source itself reports, which catches a shape joined to the wrong row.
    """)
    return


@app.cell
def _(OUT_DIR, pl):
    def validate(slug: str, source: pl.DataFrame, names: dict[str, str], area: str | None) -> dict:
        out = pl.read_parquet(OUT_DIR / f"{slug}.parquet")
        src = source.rename(names)
        src = src.select(c for c in out.columns if c in src.columns)
        null_mismatch = [c for c in src.columns if src[c].null_count() != out[c].null_count()]
        sample = src.sample(2000, seed=1)
        joined = sample.join(out, on="geoid", how="left", suffix="__out")
        value_mismatch = [
            c
            for c in src.columns
            if c != "geoid" and not joined[c].eq_missing(joined[f"{c}__out"]).all()
        ]
        result = {
            "dataset": slug,
            "source_rows": source.height,
            "output_rows": out.height,
            "geoid_unique": out["geoid"].is_unique().all(),
            "columns_checked": src.width,
            "null_count_mismatches": len(null_mismatch),
            "sampled_value_mismatches": len(value_mismatch),
            "columns_with_nulls": sum(out[c].null_count() > 0 for c in src.columns),
            "columns_all_null": sum(out[c].null_count() == out.height for c in src.columns),
        }
        if area:
            matched = out.filter(pl.col("census_aland").is_not_null() & pl.col(area).is_not_null())
            same = (matched["census_aland"] - matched[area]).abs() < 1
            result["shape_area_matches_source"] = f"{same.sum()} of {matched.height}"
        nulls = pl.DataFrame(
            {"column": src.columns, "nulls": [out[c].null_count() for c in src.columns]}
        )
        nulls.write_csv(OUT_DIR / f"{slug}.nulls.csv")
        return result

    return (validate,)


@app.cell
def _(
    OUT_DIR, cejst_names, cejst_raw, ejam_names, ejam_raw, epa_names, epa_raw, pad_bg, pl, validate
):
    epa_raw_ids = epa_raw.with_columns(pad_bg("ID"))
    validation = pl.DataFrame(
        [
            validate("epa-ejscreen-2024-block-groups", epa_raw_ids, epa_names, "arealand"),
            validate(
                "pedp-ejam-acs2024-block-groups",
                ejam_raw.select(list(ejam_names)),
                ejam_names,
                "arealand",
            ),
            validate("cejst-v2-census-tracts", cejst_raw, cejst_names, None),
        ]
    )
    validation.write_csv(OUT_DIR / "validation.csv")
    validation.transpose(include_header=True, header_name="check", column_names="dataset")
    return (validation,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. What PEDP's rebuild changes from EPA's last release

    EJAM's `map_headernames` table pairs each of its column names with EPA's. Two comparisons
    use those pairs, joined on block-group ID:

    - **v3.2022.3 against EPA 2024.** Same Census vintage, so this measures how faithfully
      PEDP reproduces EPA's numbers.
    - **v3.2024.0 against EPA 2024.** New Census vintage, so this shows which columns were
      actually updated and which were carried over from EPA unchanged.

    Two values count as equal when they differ by less than one part in a million.
    """)
    return


@app.cell
def _(epa, epa_names, headers, pl):
    numeric = {src for src, out in epa_names.items() if epa.schema[out].is_numeric()}

    def compare(ejam_frame: pl.DataFrame, label: str) -> pl.DataFrame:
        pairs = [
            (r["rname"], r["csvname"])
            for r in headers.iter_rows(named=True)
            if r["rname"] in ejam_frame.columns
            and r["csvname"] in numeric
            and ejam_frame.schema[r["rname"]].is_numeric()
            and ejam_frame[r["rname"]].null_count() < ejam_frame.height
        ]
        joined = ejam_frame.select(
            pl.col("bgfips").alias("geoid"), *[pl.col(e).alias(f"ejam:{e}") for e, _ in pairs]
        ).join(epa, on="geoid", how="inner")
        rows = []
        for ejam_col, epa_col in pairs:
            a = joined[f"ejam:{ejam_col}"].cast(pl.Float64)
            b = joined[epa_names[epa_col]].cast(pl.Float64)
            both = a.is_not_null() & b.is_not_null()
            diff = (a - b).abs().filter(both)
            scale = b.abs().filter(both).clip(lower_bound=1.0)
            rows.append(
                {
                    "comparison": label,
                    "ejam_column": ejam_col,
                    "epa_column": epa_col,
                    "rows_compared": int(both.sum()),
                    "share_equal": float((diff <= 1e-6 * scale).mean() or 0.0),
                    "median_abs_diff": float(diff.median() or 0.0),
                    "epa_only_values": int((b.is_not_null() & a.is_null()).sum()),
                }
            )
        return pl.DataFrame(rows)

    return (compare,)


@app.cell
def _(OUT_DIR, compare, ejam_2022_raw, ejam_raw, epa, pl):
    diffs = pl.concat(
        [
            compare(ejam_2022_raw, "v3.2022.3 vs EPA 2024"),
            compare(ejam_raw, "v3.2024.0 vs EPA 2024"),
        ]
    )
    diffs.write_csv(OUT_DIR / "diff_vs_epa_2024.csv")
    diff_summary = (
        diffs.with_columns(
            pl.when(pl.col("share_equal") >= 0.999)
            .then(pl.lit("identical (>=99.9% equal)"))
            .when(pl.col("share_equal") >= 0.5)
            .then(pl.lit("mostly equal"))
            .otherwise(pl.lit("changed (<50% equal)"))
            .alias("verdict")
        )
        .group_by("comparison", "verdict")
        .agg(pl.len().alias("columns"), pl.col("ejam_column").head(6).alias("examples"))
        .sort("comparison", "verdict")
    )
    universe = {
        tag: {
            "ejam_rows": frame.height,
            "only_in_ejam": frame.join(epa, left_on="bgfips", right_on="geoid", how="anti").height,
            "only_in_epa": epa.join(frame, left_on="geoid", right_on="bgfips", how="anti")
            .group_by("st_abbrev", "cnty_name")
            .agg(pl.len().alias("block_groups"), pl.col("acstotpop").sum().alias("people"))
            .to_dicts(),
        }
        for tag, frame in {"v3.2022.3": ejam_2022_raw, "v3.2024.0": ejam_raw}.items()
    }
    print(universe)
    diff_summary
    return diff_summary, diffs, universe


@app.cell
def _(diffs, mo, pl):
    _same = diffs.filter(
        (pl.col("comparison") == "v3.2024.0 vs EPA 2024") & (pl.col("share_equal") >= 0.999)
    )["ejam_column"].to_list()
    _replica = diffs.filter(pl.col("comparison") == "v3.2022.3 vs EPA 2024")
    mo.md(f"""
    At the same Census vintage, {(_replica["share_equal"] >= 0.999).sum()} of
    {_replica.height} paired columns match EPA's in at least 99.9% of block groups, and the
    lowest match is {_replica["share_equal"].min():.4%}. In v3.2024.0 these
    {len(_same)} columns are still identical to EPA's: {", ".join(_same)}.

    So the new release updates the Census demographics, and the demographic and EJ indexes
    built from them, but the environmental indicators and life expectancy are EPA's 2024
    values. The counts of EJ indexes at or above the 80th percentile (`count.ej.80up`) are
    unchanged too, although most EJ index values moved, which suggests they were carried
    over rather than recomputed. The full table is in `outputs/diff_vs_epa_2024.csv`.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    The map shows what the new Census vintage does to one input of the indexes: the share
    of people with low income, in percentage points, from EPA's 2024 release (ACS 2018-2022)
    to PEDP's v3.2024.0 (ACS 2020-2024), for Louisiana's block groups. Block-group ACS
    estimates have wide margins of error, so much of the speckle is sampling noise rather
    than change on the ground. (The demographic index itself is an average of z-scores
    shifted to be non-negative, so its raw values don't compare across vintages.)
    """)
    return


@app.cell
def _(OUT_DIR, ejam_gdf, epa, gpd, pl, plt):
    _la = ejam_gdf[ejam_gdf["st"] == "LA"][["geoid", "pctlowinc", "geometry"]]
    _before = epa.select("geoid", pl.col("lowincpct").alias("epa_2024")).to_pandas()
    _la = gpd.GeoDataFrame(_la.merge(_before, on="geoid"), geometry="geometry", crs=4326)
    _la["change"] = 100 * (_la["pctlowinc"].astype(float) - _la["epa_2024"])
    _fig, _ax = plt.subplots(figsize=(8, 6))
    _la.to_crs(3452).plot(
        column="change", cmap="RdBu_r", vmin=-20, vmax=20, legend=True, ax=_ax, linewidth=0
    )
    _ax.set_axis_off()
    _ax.set_title("% low income, ACS 2020-24 minus ACS 2018-22, points (Louisiana)")
    _fig.savefig(OUT_DIR / "map_lowinc_change_la.png", dpi=120, bbox_inches="tight")
    _fig
    return


@app.cell
def _(OUT_DIR, gpd, outputs):
    # Washington, DC alone, small enough to commit as a sample of each file.
    (OUT_DIR / "samples").mkdir(exist_ok=True)
    for _slug in outputs["dataset"]:
        _gdf = gpd.read_parquet(OUT_DIR / f"{_slug}.parquet")
        _gdf[_gdf["geoid"].str.startswith("11")].to_parquet(
            OUT_DIR / "samples" / f"{_slug}.dc.parquet", compression="zstd"
        )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 9. What the public copies leave out
    """)
    return


@app.cell
def _(ejam_raw, epa_raw, headers, pl):
    _rname_of = {r["csvname"]: r["rname"] for r in headers.iter_rows(named=True) if r["csvname"]}
    _filled = {c for c in ejam_raw.columns if ejam_raw[c].null_count() < ejam_raw.height}
    missing_from_ejam = [
        c for c in epa_raw.columns if c != "ID" and _rname_of.get(c) not in _filled
    ]
    _groups = {
        "national percentiles (P_)": [c for c in missing_from_ejam if c.startswith("P_")],
        "map bins (B_)": [c for c in missing_from_ejam if c.startswith("B_")],
        "map text (T_)": [c for c in missing_from_ejam if c.startswith("T_")],
    }
    _grouped = {c for cols in _groups.values() for c in cols}
    _groups["other"] = [c for c in missing_from_ejam if c not in _grouped]
    missing_table = pl.DataFrame(
        {
            "EPA 2024 columns with no EJAM v3.2024.0 counterpart": list(_groups),
            "count": [len(v) for v in _groups.values()],
            "examples": [", ".join(v[:6]) for v in _groups.values()],
        }
    )
    missing_table
    return missing_from_ejam, missing_table


@app.cell
def _(
    OUT_DIR,
    diff_summary,
    json,
    manifest,
    missing_from_ejam,
    outputs,
    t_download,
    t_start,
    t_write,
    time,
    universe,
    unmatched,
    validation,
):
    t_total = time.perf_counter() - t_start
    summary = {
        "run_seconds": round(t_total),
        "download_seconds": round(t_download),
        "write_seconds": round(t_write),
        "source_files": len(manifest),
        "source_gb": round(sum(m["bytes"] for m in manifest.values()) / 1e9, 2),
        "outputs": outputs.to_dicts(),
        "validation": validation.to_dicts(),
        "rows_without_shape": {k: v.to_dicts() for k, v in unmatched.items()},
        "row_universe_vs_epa": universe,
        "diff_summary": diff_summary.with_columns(
            diff_summary["examples"].list.join(", ")
        ).to_dicts(),
        "epa_columns_missing_from_ejam": missing_from_ejam,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(f"total run time {t_total / 60:.1f} min")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **R data without R is slow.** `rdata` takes about five minutes to parse each EJAM
      `blockgroupstats.rda`; `pyreadr` (librdata) reads the file but returns a single empty
      column for this data.table. The parsed table is cached, so only a first run pays.
    - **EJAM v3.2024.0 has no per-block-group percentiles.** EJAM computes them when it runs
      a report from its national and state lookup tables, so the hosted file has raw values
      and EJ indexes but not EPA's `P_`, `B_` and `T_` columns (see section 8).
    - **Water-only block groups have no shape.** The cartographic boundary files leave out
      block groups that are all water, so about 440 rows per block-group file, with no
      population, have empty geometry. TIGER/Line block groups would fill them at the cost
      of a 1 GB download and much larger files.
    - **EJAM v3.2024.0 drops 39 block groups.** They are in Suffolk County, New York, and
      are missing from Census's ACS 2020-2024 tables, which EJAM's pipeline documentation
      describes; EPA's 2024 file had people in them.
    - **No uploads.** Uploading to HIFLD Next is left to the founders; the STAC records are
      shaped after the catalog's published collections but have not been through its
      ingest.
    - **The comparison is column by column.** It doesn't check whether EJAM's formulas are
      right where its numbers differ from EPA's, only how much and where they differ.
    """)
    return


if __name__ == "__main__":
    app.run()
