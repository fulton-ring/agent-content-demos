import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # What data is inside EPA's legacy web archive, and can we get it out of the crawl?

        EPA says it retires `archive.epa.gov` on December 31, 2026. Anything But Binary crawled
        the site into the Internet Archive item
        [`epa-archive-harvest-2026`](https://archive.org/details/epa-archive-harvest-2026):
        WARC files plus a CDX index that says, for every captured address, its MIME type,
        HTTP status, size and where its record sits inside which WARC.

        A crawl keeps the bytes but not the meaning. This notebook asks four things:

        1. How much of the crawl is **data** (spreadsheets, CSVs, databases, statistical files),
           as opposed to web pages, PDFs and images?
        2. Do the crawl's own numbers (79,352 sitemap pages and files, about 24,000 extra
           addresses, 81.3 GB, 3,400+ damaged or missing files) hold up against the CDX?
        3. For a seeded sample of data files, is there a live copy anywhere else: on
           www.epa.gov, in EPA's three snapshot sites, or in the data.gov catalog?
        4. Can a handful of datasets be pulled out of the WARCs, by byte range, into Parquet
           with a catalog entry that says where each came from?

        Everything is read from public sources at run time. Nothing from the crawl is committed
        except the tables this notebook writes to `outputs/`.
        """
    )
    return (mo,)


@app.cell
def _():
    import base64
    import datetime as dt
    import gzip
    import hashlib
    import io
    import json
    import os
    import random
    import re
    import time
    import zipfile
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from urllib.parse import quote, unquote, urlencode, urlsplit

    import pandas as pd
    import requests
    from access_parser import AccessParser
    from warcio.archiveiterator import ArchiveIterator

    HERE = Path(__file__).parent
    CACHE = Path(os.environ.get("EPA_CACHE_DIR", HERE / "cache"))
    OUT = Path(os.environ.get("EPA_OUT_DIR", HERE / "outputs"))
    SAMPLE_SIZE = int(os.environ.get("EPA_SAMPLE_SIZE", "100"))
    SEED = int(os.environ.get("EPA_SEED", "217"))
    ITEM = "epa-archive-harvest-2026"
    DOWNLOAD = f"https://archive.org/download/{ITEM}"
    CACHE.mkdir(parents=True, exist_ok=True)
    (OUT / "parquet").mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "fulton-ring-epa-archive-datasets/0.1 (research spike)"
    RUN_STARTED = time.perf_counter()
    return (
        AccessParser,
        ArchiveIterator,
        base64,
        CACHE,
        DOWNLOAD,
        ITEM,
        OUT,
        RUN_STARTED,
        SAMPLE_SIZE,
        SEED,
        ThreadPoolExecutor,
        dt,
        gzip,
        hashlib,
        io,
        json,
        pd,
        quote,
        random,
        re,
        requests,
        session,
        time,
        unquote,
        urlencode,
        urlsplit,
        zipfile,
    )


@app.cell
def _(CACHE, requests, session, time):
    def get(url: str, *, headers: dict[str, str] | None = None, timeout: int = 120) -> bytes:
        """GET with three tries and backoff; raises on a final non-2xx."""
        last_error = ""
        for attempt in range(3):
            try:
                response = session.get(url, headers=headers or {}, timeout=timeout)
                if response.status_code in (200, 206):
                    return response.content
                last_error = f"HTTP {response.status_code}"
            except requests.RequestException as error:
                last_error = repr(error)
            time.sleep(2**attempt)
        raise RuntimeError(f"GET {url} failed: {last_error}")

    def cached(url: str, name: str) -> bytes:
        """Download once into the cache directory, then reuse."""
        path = CACHE / name
        if not path.exists():
            path.write_bytes(get(url))
        return path.read_bytes()

    return cached, get


@app.cell
def _(mo):
    mo.md(
        """
        ## The data

        Three files from the Internet Archive item, about 9 MB together:

        - `epa-archive-harvest-2026.cdx.gz`, the item's merged CDX index (one line per capture).
        - `baseline-2026-10-23.zip`, the crawlers' copy of the 79,352 URLs in EPA's sitemaps.
        - The item's metadata, which lists every WARC file and its size.

        The CDX `S` column is the size of the gzipped WARC record, not the original file, so
        all byte figures below are **compressed bytes in the WARCs**.
        """
    )
    return


@app.cell
def _(DOWNLOAD, ITEM, cached, gzip, io, json, pd, unquote, urlsplit):
    cdx_columns = [
        "urlkey",
        "timestamp",
        "url",
        "mime",
        "status",
        "digest",
        "redirect",
        "meta",
        "size",
        "offset",
        "warc",
    ]
    cdx_lines = gzip.decompress(cached(f"{DOWNLOAD}/{ITEM}.cdx.gz", f"{ITEM}.cdx.gz"))
    cdx = pd.read_csv(
        io.BytesIO(cdx_lines),
        sep=" ",
        names=cdx_columns,
        skiprows=1,
        dtype=str,
        keep_default_na=False,
        quoting=3,
    )
    assert (cdx["warc"].str.startswith(f"{ITEM}/")).all(), "every record should point into the item"
    cdx["size"] = cdx["size"].astype(int)
    cdx["offset"] = cdx["offset"].astype(int)

    def normalize(url: str) -> str:
        """One spelling per address: the crawl reached some files through www.epa.gov/archive/."""
        parts = urlsplit(unquote(url.strip()))
        path = parts.path
        if parts.netloc == "www.epa.gov" and path.startswith("/archive/"):
            path = path[len("/archive") :]
        return "archive.epa.gov" + path + (f"?{parts.query}" if parts.query else "")

    cdx["address"] = cdx["url"].map(normalize)
    cdx["ext"] = (
        cdx["address"].str.lower().str.extract(r"\.([a-z0-9]{1,5})(?:\?.*)?$")[0].fillna("")
    )

    metadata = json.loads(cached(f"https://archive.org/metadata/{ITEM}", f"{ITEM}-metadata.json"))
    warc_files = pd.DataFrame(
        [
            {"name": f["name"], "bytes": int(f["size"])}
            for f in metadata["files"]
            if f["name"].endswith(".warc.gz") and ".cdx." not in f["name"]
        ]
    )
    cdx.head(3)
    return cdx, normalize, warc_files


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 1: what kind of file is each address?

        The file extension is a better guide than the MIME type here: the server labels some
        HTML news releases `application/xml` and every SAS, Lotus and Access file `unk`.
        We group extensions into kinds. **Data** means tabular files and databases a researcher
        would load as a table. Archives (zip, tar.gz) often hold data too, but we can't tell
        without opening each one, so they are counted separately. XML, RDF and JSON are kept
        apart because, on inspection, they are RSS feeds, slide metadata and page labels.
        """
    )
    return


@app.cell
def _(OUT, cdx, pd):
    kinds = {
        "data: spreadsheet or table": ["xls", "xlsx", "xlsm", "csv", "wk4", "tsv", "dbf"],
        "data: database": ["mdb", "accdb"],
        "data: statistical file": ["xpt", "sav", "dta"],
        "data: GIS": ["shp", "kml", "kmz", "gdb", "e00", "geojson"],
        "archive (zip, tar.gz)": ["zip", "gz", "tar", "tgz"],
        "xml, rdf, json": ["xml", "rdf", "json"],
        "code (R, SAS, Fortran)": ["r", "sas", "for", "f90"],
        "plain text": ["txt"],
        "pdf": ["pdf"],
        "office document": ["doc", "docx", "ppt", "pptx", "wpd"],
        "web page": ["html", "htm", "", "shtml", "asp", "cfm"],
        "image": ["jpg", "jpeg", "gif", "png", "bmp", "svg", "ico", "wmf", "emz", "wmz"],
        "audio, video, flash": ["mp3", "wav", "wmv", "mp4", "avi", "qt", "mpg", "flv", "rm", "swf"],
        "page asset (css, js)": ["css", "js", "lbi", "dwt"],
        "software": ["exe", "msi", "jar"],
    }
    kind_of_ext = {ext: kind for kind, exts in kinds.items() for ext in exts}
    cdx["kind"] = cdx["ext"].map(kind_of_ext).fillna("other")
    cdx["is_data"] = cdx["kind"].str.startswith("data:")
    # Files EPA moved here from www.epa.gov keep that site's upload path.
    cdx["origin"] = (
        cdx["address"]
        .str.startswith("archive.epa.gov/epa/sites/production/files/")
        .map({True: "moved from www.epa.gov", False: "legacy program site"})
    )

    ok_captures = cdx[cdx["status"].isin(["200", "206"])].drop_duplicates("address", keep="last")
    by_kind = (
        ok_captures.groupby("kind")
        .agg(addresses=("address", "size"), warc_bytes=("size", "sum"))
        .sort_values("addresses", ascending=False)
    )
    by_kind["share_of_addresses"] = (by_kind["addresses"] / by_kind["addresses"].sum()).round(4)
    by_kind["share_of_bytes"] = (by_kind["warc_bytes"] / by_kind["warc_bytes"].sum()).round(4)
    by_kind.to_csv(OUT / "inventory_by_kind.csv")

    is_archive = ok_captures["kind"] == "archive (zip, tar.gz)"
    data_like = ok_captures[ok_captures["is_data"] | is_archive]
    by_ext = (
        data_like.groupby(["kind", "ext"])
        .agg(addresses=("address", "size"), warc_bytes=("size", "sum"))
        .sort_values("addresses", ascending=False)
    )
    by_ext.to_csv(OUT / "inventory_data_by_extension.csv")
    listing = [
        "address",
        "url",
        "kind",
        "ext",
        "origin",
        "timestamp",
        "size",
        "digest",
        "warc",
        "offset",
    ]
    data_like[listing].sort_values("address").to_csv(OUT / "data_files.csv", index=False)

    data_files = ok_captures[ok_captures["is_data"]]
    data_share = len(data_files) / len(ok_captures)
    data_or_archive_share = len(data_like) / len(ok_captures)
    by_origin = pd.crosstab(
        data_like["kind"], data_like["origin"], margins=True, margins_name="total"
    )
    by_kind
    return by_ext, by_kind, by_origin, data_files, data_or_archive_share, data_share, ok_captures


@app.cell
def _(by_ext, by_origin, data_files, data_or_archive_share, data_share, mo, ok_captures):
    mo.vstack(
        [
            mo.md(
                f"""
            **{len(ok_captures):,} distinct addresses were captured with HTTP 200.**
            {len(data_files):,} of them ({data_share:.1%}) are data files;
            counting archives too, {data_or_archive_share:.1%}.
            The data files take {data_files["size"].sum() / 1e9:.2f} GB of WARC records.
            The full list is in `outputs/data_files.csv`, with the WARC and offset of each
            record. Files under `/epa/sites/production/files/` were moved here from www.epa.gov;
            everything else comes from the older program sites (EMAP, air quality, air toxics,
            regions and so on), which matters in step 4.
            """
            ),
            mo.hstack([by_ext.head(12), by_origin]),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 2: do the crawl's own numbers hold up?

        The crawlers said they captured "all 79,352 sitemap pages and files, plus nearly
        24,000 linked addresses no sitemap lists", 81.3 GB. We match the sitemap list against
        the CDX, address by address, and add up the WARC files the item lists today.
        """
    )
    return


@app.cell
def _(DOWNLOAD, OUT, cached, cdx, io, mo, normalize, ok_captures, pd, warc_files, zipfile):
    baseline_zip = zipfile.ZipFile(
        io.BytesIO(cached(f"{DOWNLOAD}/baseline-2026-10-23.zip", "baseline-2026-10-23.zip"))
    )
    sitemap_urls = baseline_zip.read("baseline/urls-2026-10-23.txt").decode().split("\n")
    sitemap = {normalize(u) for u in sitemap_urls if u.strip()}
    captured_ok = set(ok_captures["address"])
    captured_any = set(cdx["address"])
    indexed_warcs = set(cdx["warc"].str.split("/").str[-1])
    unindexed = warc_files[~warc_files["name"].isin(indexed_warcs)]
    extras = ok_captures[~ok_captures["address"].isin(sitemap)]
    checks = {
        "sitemap URLs (claimed 79,352)": len(sitemap_urls) - sitemap_urls.count(""),
        "distinct sitemap addresses after normalizing": len(sitemap),
        "sitemap addresses captured with HTTP 200": len(sitemap & captured_ok),
        "sitemap addresses captured, never with 200": len((sitemap & captured_any) - captured_ok),
        "sitemap addresses not in the CDX at all": len(sitemap - captured_any),
        "extra addresses with 200, in no sitemap (claimed ~24,000)": len(extras),
        "  of which images, css and js": int(
            extras["kind"].isin(["image", "page asset (css, js)"]).sum()
        ),
        "  of which everything else": int(
            (~extras["kind"].isin(["image", "page asset (css, js)"])).sum()
        ),
        "CDX lines (captures)": len(cdx),
        "WARC GB indexed by the merged CDX (claimed 81.3)": round(cdx["size"].sum() / 1e9, 1),
        "WARC files in the item today": len(warc_files),
        "WARC GB in the item today": round(warc_files["bytes"].sum() / 1e9, 1),
        "WARC files the merged CDX doesn't cover yet": len(unindexed),
        "WARC GB the merged CDX doesn't cover yet": round(unindexed["bytes"].sum() / 1e9, 1),
    }
    crawl_check = pd.DataFrame(
        {"check": list(checks), "value": list(checks.values())}, dtype=object
    )
    crawl_check.to_csv(OUT / "crawl_check.csv", index=False)
    extras_by_kind = extras["kind"].value_counts().rename("extra addresses")
    mo.hstack([crawl_check, extras_by_kind])
    return checks, crawl_check, sitemap, unindexed


@app.cell
def _(mo, unindexed):
    mo.md(
        f"""
        The merged CDX matches the crawl as it stood when the 81.3 GB figure was published.
        The crawl kept going: {len(unindexed)} later WARC files are in the item but not in the
        merged index yet (most are named `retired_main`, `round25` and `guess_*`). Everything
        below describes the indexed part only; reading the rest would mean downloading
        {unindexed["bytes"].sum() / 1e9:.0f} GB, which this spike doesn't do.
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 3: the damaged and missing files

        An address counts as **failed** when the crawl never got an HTTP 200 for it, under
        either spelling (`archive.epa.gov/...` or `www.epa.gov/archive/...`). We group failures
        by the status the server gave and by the kind of file. The CDX can't show a file that
        returned 200 but is truncated or corrupt; that would need every record opened.
        """
    )
    return


@app.cell
def _(OUT, cdx, ok_captures, pd, sitemap):
    last_capture = cdx.sort_values("timestamp").drop_duplicates("address", keep="last")
    failed = last_capture[~last_capture["address"].isin(set(ok_captures["address"]))].copy()
    failed["in_sitemap"] = failed["address"].isin(sitemap)
    failed_by_kind = pd.crosstab(
        failed["kind"], failed["status"], margins=True, margins_name="total"
    )
    failed_by_kind = failed_by_kind.sort_values("total", ascending=False)
    failed_by_kind.to_csv(OUT / "failed_by_kind.csv")
    failed[["address", "url", "kind", "ext", "status", "timestamp", "in_sitemap"]].sort_values(
        "address"
    ).to_csv(OUT / "failed_addresses.csv", index=False)
    failed_hard = failed[failed["status"].isin(["403", "404"])]
    failed_data = failed_hard[failed_hard["kind"].str.startswith("data:")]
    failed_by_kind
    return failed, failed_data, failed_hard


@app.cell
def _(failed, failed_data, failed_hard, mo):
    mo.md(
        f"""
        **{len(failed):,} addresses never returned HTTP 200.** {len(failed_hard):,} of them
        ended in 404 (gone) or 403 (refused); the other {len(failed) - len(failed_hard):,} only
        ever answered with a redirect the crawl didn't follow to a 200.
        {failed_hard["in_sitemap"].sum():,} of the 404s and 403s are addresses EPA's own sitemaps
        still list. {len(failed_data):,} of them are data files.
        The list is in `outputs/failed_addresses.csv`.
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 4: is there a live copy anywhere else?

        We draw a seeded random sample of data files captured with HTTP 200 and look for each
        one in three places:

        - **www.epa.gov.** Files under `archive.epa.gov/epa/sites/production/files/` were moved
          from www.epa.gov, so we try `www.epa.gov/sites/default/files/<same path>`. For other
          files we try `www.epa.gov/<same path>`.
        - **EPA's snapshot collections**, the three sites EPA's retirement banner points to
          (`19january2017snapshot`, `19january2021snapshot`, `19january2025snapshot`), at the
          same paths.
        - **data.gov**, by searching the catalog for the file name and accepting a hit only if a
          listed download URL ends in the same file name.

        A copy counts only on HTTP 200. Matching is by file name, so a dataset republished
        under a new name is missed: the "no live copy" share is an upper bound.
        """
    )
    return


@app.cell
def _(
    SAMPLE_SIZE,
    SEED,
    ThreadPoolExecutor,
    data_files,
    json,
    quote,
    random,
    session,
    time,
    unquote,
    urlencode,
):
    snapshot_hosts = [
        "19january2017snapshot.epa.gov",
        "19january2021snapshot.epa.gov",
        "19january2025snapshot.epa.gov",
    ]
    moved_prefix = "/epa/sites/production/files/"

    def candidate_urls(address: str) -> dict[str, list[str]]:
        path = address.removeprefix("archive.epa.gov")
        www_path = path
        snapshot_path = path
        if path.startswith(moved_prefix):
            rest = path.removeprefix(moved_prefix)
            www_path = "/sites/default/files/" + rest
            snapshot_path = "/sites/production/files/" + rest
        return {
            "www.epa.gov": [f"https://www.epa.gov{quote(www_path)}"],
            "EPA snapshots": [f"https://{h}{quote(snapshot_path)}" for h in snapshot_hosts],
        }

    def status_of(url: str) -> int:
        for attempt in range(3):
            try:
                return session.head(url, allow_redirects=True, timeout=60).status_code
            except Exception:  # noqa: BLE001 - a network error is retried, then recorded as 0
                time.sleep(2**attempt)
        return 0

    def on_data_gov(file_name: str) -> str:
        query = urlencode({"q": file_name})
        for attempt in range(3):
            try:
                response = session.get(f"https://catalog.data.gov/search?{query}", timeout=60)
                if response.status_code == 200:
                    break
            except Exception:  # noqa: BLE001 - retried, then reported as an error
                pass
            time.sleep(2**attempt)
        else:
            return "error"
        for result in json.loads(response.content)["results"]:
            for dist in (result.get("dcat") or {}).get("distribution") or []:
                link = dist.get("downloadURL") or dist.get("accessURL") or ""
                if unquote(link).lower().rstrip("/").endswith("/" + file_name.lower()):
                    return link
        return ""

    def check(address: str) -> dict[str, str]:
        file_name = address.rsplit("/", 1)[-1]
        row = {"address": address}
        for where, urls in candidate_urls(address).items():
            hits = [u for u in urls if status_of(u) == 200]
            row[where] = hits[0] if hits else ""
        row["data.gov"] = on_data_gov(file_name)
        return row

    population = sorted(data_files["address"])
    sample_addresses = random.Random(SEED).sample(population, min(SAMPLE_SIZE, len(population)))
    with ThreadPoolExecutor(max_workers=4) as pool:
        live_rows = list(pool.map(check, sample_addresses))
    return (live_rows,)


@app.cell
def _(OUT, live_rows, pd):
    live = pd.DataFrame(live_rows)
    places = ["www.epa.gov", "EPA snapshots", "data.gov"]
    assert (live["data.gov"] != "error").all(), "data.gov search failed for some files; rerun"
    live["any_live_copy"] = (live[places] != "").any(axis=1)
    live["origin"] = (
        live["address"]
        .str.startswith("archive.epa.gov/epa/sites/production/")
        .map({True: "moved from www.epa.gov", False: "legacy program site"})
    )
    live["section"] = live["address"].str.split("/").str[1]
    live.to_csv(OUT / "live_copy_sample.csv", index=False)
    live_summary = pd.DataFrame(
        {
            "files with a copy here": [(live[p] != "").sum() for p in places]
            + [live["any_live_copy"].sum(), (~live["any_live_copy"]).sum()],
        },
        index=places + ["anywhere", "nowhere (archive only)"],
    )
    live_summary["share of sample"] = (live_summary.iloc[:, 0] / len(live)).round(3)
    live_by_origin = live.groupby(["origin", "section"])["any_live_copy"].agg(["size", "sum"])
    live_by_origin = live_by_origin.rename(columns={"size": "sampled", "sum": "with a live copy"})
    live_summary
    return live, live_by_origin, live_summary


@app.cell
def _(live, live_by_origin, mo):
    mo.vstack(
        [
            mo.md(
                f"""
            **{live["any_live_copy"].mean():.0%} of {len(live)} sampled data files have a live
            copy we could find; {(~live["any_live_copy"]).mean():.0%} exist, as far as these
            checks can tell, only in the archive.** The split by origin is the finding:
            files EPA moved from www.epa.gov are still on www.epa.gov, while files from the
            legacy program sites are not on www.epa.gov, in the snapshots or in data.gov.
            """
            ),
            live_by_origin,
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 5: pull datasets out of the WARCs into Parquet

        For each chosen file we look up its CDX line, fetch just that WARC record from the
        Internet Archive with an HTTP `Range` request, and let
        [warcio](https://github.com/webrecorder/warcio) parse it. The payload is checked against
        the SHA-1 digest the CDX recorded at crawl time, hashed with SHA-256 for the catalog,
        and read into a table with the reader that fits its format:
        pandas for CSV, Excel and SAS transport files, and
        [access-parser](https://github.com/claroty/access_parser) for Access databases.
        Each table becomes one Parquet file; multi-table files become several.

        The picks cover every data format in the archive that has a Python reader: an EMAP
        coastal survey table as CSV and as SAS transport (the same dataset, so the row counts
        must agree), Animal Feeding Operation ammonia monitoring (old Excel), PM10 near the KCBX
        petcoke piles in Chicago (new Excel), the West Lake Landfill groundwater database
        (Access 2007), a NATA 1999 Access database, and a 1996 NATA tract-level file inside a zip.
        """
    )
    return


@app.cell
def _(
    AccessParser,
    ArchiveIterator,
    CACHE,
    DOWNLOAD,
    ITEM,
    base64,
    cdx,
    get,
    hashlib,
    io,
    pd,
    re,
    zipfile,
):
    picks = [
        "archive.epa.gov/emap/archive-emap/web/csv/ben_abun.csv",
        "archive.epa.gov/emap/archive-emap/web/xpt/ben_abun.xpt",
        "archive.epa.gov/airquality/afo2012/web/xls/bls_nh3_in4a_fall07.xls",
        "archive.epa.gov/epa/sites/production/files/2016-01/kcbx-hourly-data-20160103-20160109.xlsx",
        "archive.epa.gov/region07/cleanup/west_lake_landfill/web/accdb/west_lake_landfill_april_2013_groundwater_database.accdb",
        "archive.epa.gov/airtoxics/nata1999/web/mdb/99nei_hap_potential_errors-05-31-06.mdb",
        "archive.epa.gov/airtoxics/nata/web/zip/43601-tract.zip",
    ]

    def fetch_record(row: pd.Series) -> tuple[bytes, str]:
        """Return (payload, WARC-Date) for one CDX line, reading only its byte range."""
        end = row["offset"] + row["size"] - 1
        url = f"{DOWNLOAD}/{row['warc'].removeprefix(ITEM + '/')}"
        raw = get(url, headers={"Range": f"bytes={row['offset']}-{end}"})
        assert len(raw) == row["size"], f"range returned {len(raw)} bytes, CDX says {row['size']}"
        for record in ArchiveIterator(io.BytesIO(raw)):
            if record.rec_type == "response":
                return record.content_stream().read(), record.rec_headers.get_header("WARC-Date")
        raise ValueError(f"no response record at {url} offset {row['offset']}")

    def emap_csv(payload: bytes) -> dict[str, pd.DataFrame]:
        """EMAP CSVs start with a header block; the column row starts with the first variable."""
        text = payload.decode("latin-1")
        lines = text.splitlines()
        first_var = re.search(r"^Variables:\s+(\S+)", text, re.M)
        assert first_var, "EMAP header block not found"
        start = next(i for i, line in enumerate(lines) if line.startswith(first_var.group(1) + ","))
        table = pd.read_csv(io.StringIO("\n".join(lines[start:])), dtype=str, na_values=["."])
        return {"table": table.loc[:, ~table.columns.str.startswith("Unnamed")]}

    def access(payload: bytes, suffix: str) -> dict[str, pd.DataFrame]:
        path = CACHE / f"extract{suffix}"
        path.write_bytes(payload)
        db = AccessParser(str(path))
        names = [n for n in db.catalog if not n.startswith("MSys")]
        return {n: pd.DataFrame(db.parse_table(n)) for n in names}

    def read_tables(payload: bytes, name: str) -> dict[str, pd.DataFrame]:
        suffix = "." + name.rsplit(".", 1)[-1].lower()
        if suffix == ".zip":
            archive = zipfile.ZipFile(io.BytesIO(payload))
            inner = max(archive.infolist(), key=lambda m: m.file_size)
            return read_tables(archive.read(inner), inner.filename)
        if suffix == ".csv":
            return emap_csv(payload)
        if suffix == ".xpt":
            return {"table": pd.read_sas(io.BytesIO(payload), format="xport", encoding="latin-1")}
        if suffix in (".xls", ".xlsx"):
            sheets = pd.read_excel(
                io.BytesIO(payload), sheet_name=None, dtype=str, engine="calamine"
            )
            return {s: t for s, t in sheets.items() if not t.empty}
        if suffix in (".mdb", ".accdb"):
            return access(payload, suffix)
        raise ValueError(f"no reader for {suffix}")

    def sha1_base32(payload: bytes) -> str:
        return base64.b32encode(hashlib.sha1(payload).digest()).decode()

    pick_rows = cdx[cdx["address"].isin(picks) & (cdx["status"] == "200")].drop_duplicates(
        "address", keep="last"
    )
    assert len(pick_rows) == len(picks), "every pick should have a 200 capture in the CDX"
    return fetch_record, pick_rows, read_tables, sha1_base32


@app.cell
def _(OUT, fetch_record, hashlib, pick_rows, read_tables, re, sha1_base32, time):
    catalog = []
    for _, _row in pick_rows.iterrows():
        _name = _row["address"].rsplit("/", 1)[-1]
        _started = time.perf_counter()
        _entry = {
            "dataset": _name,
            "original_url": _row["url"],
            "capture_time": _row["timestamp"],
            "source_warc": f"https://archive.org/download/{_row['warc']}",
            "warc_offset": int(_row["offset"]),
            "warc_record_bytes": int(_row["size"]),
        }
        try:
            _payload, _warc_date = fetch_record(_row)
            _entry["warc_date"] = _warc_date
            _entry["payload_bytes"] = len(_payload)
            _entry["sha256"] = hashlib.sha256(_payload).hexdigest()
            _entry["sha1_matches_cdx"] = sha1_base32(_payload) == _row["digest"]
            _tables = read_tables(_payload, _name)
            _entry["tables"] = []
            for _table_name, _table in _tables.items():
                _slug = re.sub(r"[^a-z0-9]+", "_", f"{_name}__{_table_name}".lower()).strip("_")
                _path = OUT / "parquet" / f"{_slug}.parquet"
                _table.astype(str).to_parquet(_path, index=False)
                _entry["tables"].append(
                    {
                        "table": _table_name,
                        "parquet": str(_path.relative_to(OUT)),
                        "rows": len(_table),
                        "columns": len(_table.columns),
                        "parquet_bytes": _path.stat().st_size,
                    }
                )
            _entry["error"] = ""
        except Exception as _error:  # noqa: BLE001 - one bad file is recorded, the rest still run
            _entry["error"] = repr(_error)[:300]
        _entry["seconds"] = round(time.perf_counter() - _started, 2)
        catalog.append(_entry)
    return (catalog,)


@app.cell
def _(OUT, catalog, json, pd):
    (OUT / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    extraction = pd.DataFrame(
        [
            {
                "dataset": e["dataset"],
                "tables": len(e.get("tables", [])),
                "rows": sum(t["rows"] for t in e.get("tables", [])),
                "parquet_MB": round(sum(t["parquet_bytes"] for t in e.get("tables", [])) / 1e6, 2),
                "file_MB": round(e.get("payload_bytes", 0) / 1e6, 2),
                "sha1_matches_cdx": e.get("sha1_matches_cdx"),
                "seconds": e["seconds"],
                "error": e["error"],
            }
            for e in catalog
        ]
    )
    extraction.to_csv(OUT / "extraction.csv", index=False)
    extraction
    return (extraction,)


@app.cell
def _(catalog, mo):
    _emap = {
        e["dataset"]: sum(t["rows"] for t in e.get("tables", []))
        for e in catalog
        if e["dataset"].startswith("ben_abun")
    }
    mo.md(
        f"""
        **Checks on the extraction.** The EMAP CSV's own header declares 34,756 data records;
        the CSV extraction gave {_emap.get("ben_abun.csv", 0):,} rows and the SAS transport copy
        of the same dataset gave {_emap.get("ben_abun.xpt", 0):,}. Every payload's SHA-1 is
        compared with the digest the crawler wrote into the CDX (column `sha1_matches_cdx`).
        Catalog entries, with original URL, capture time, WARC location and SHA-256, are in
        `outputs/catalog.json`.
        """
    )
    return


@app.cell
def _(
    RUN_STARTED,
    by_kind,
    checks,
    data_files,
    data_share,
    dt,
    extraction,
    failed_hard,
    live,
    mo,
    time,
):
    _seconds = time.perf_counter() - RUN_STARTED
    _ok = extraction[extraction["error"] == ""]
    _origin = live.groupby("origin")["any_live_copy"].agg(["sum", "size"])
    _by_origin = "; ".join(f"{o}: {r['sum']} of {r['size']}" for o, r in _origin.iterrows())
    summary = f"""
    ## Result

    Run on {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC in {_seconds:.0f} seconds.

    - Distinct addresses captured with HTTP 200: {by_kind["addresses"].sum():,}.
      Data files: {len(data_files):,} ({data_share:.1%}).
    - Sitemap addresses captured with 200: {checks["sitemap addresses captured with HTTP 200"]:,}
      of {checks["distinct sitemap addresses after normalizing"]:,}. Extra addresses in no
      sitemap: {checks["extra addresses with 200, in no sitemap (claimed ~24,000)"]:,}
      ({checks["  of which everything else"]:,} not counting images, css and js).
    - WARC GB indexed: {checks["WARC GB indexed by the merged CDX (claimed 81.3)"]};
      in the item today: {checks["WARC GB in the item today"]}.
    - Addresses that ended in 404 or 403: {len(failed_hard):,}.
    - Sampled data files with a live copy elsewhere: {live["any_live_copy"].sum()} of
      {len(live)} ({live["any_live_copy"].mean():.0%}). By origin: {_by_origin}.
    - Datasets extracted: {len(_ok)} of {len(extraction)}, {_ok["rows"].sum():,} rows,
      {_ok["parquet_MB"].sum():.1f} MB of Parquet, median {_ok["seconds"].median():.1f} s each.
    """
    print(summary)
    mo.md(summary)
    return


if __name__ == "__main__":
    app.run()
