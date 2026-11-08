import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # Which live EPA pages still send readers to the archive EPA retires on December 31?

        EPA says it retires `archive.epa.gov` on December 31, 2026. Our earlier spike
        (`epa-archive-datasets/`, issue #217) inventoried what's inside the archive and found
        that data files from the legacy program sites almost never have a live copy anywhere
        else. This notebook looks at the archive from the outside instead. **How many pages on
        EPA's current site, www.epa.gov, link into the archive, how many of those links are
        data files, and how many of those files can a reader get nowhere else?**

        If almost no live page links into the archive for data, EPA has already cut the
        dependency, and that's the finding.

        The steps:

        1. Read www.epa.gov's robots.txt and sitemaps, then fetch every page in them politely.
        2. Pull out every link into the archive and sort it by kind: data file, document or page.
        3. Check what each data link returns today.
        4. Look for a live copy of each data file: the same path on www.epa.gov, EPA's snapshot
           sites, and data.gov.
        5. Correct the file-name match with a hand check of a sample.
        6. Count the pages whose data is only in the archive, by program, and list the top ten.

        Everything is fetched from public sites at run time.
        """
    )
    return (mo,)


@app.cell
def _():
    import io as io_module
    import json
    import os
    import random
    import re
    import time
    import urllib.robotparser
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pathlib import Path
    from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit

    import pandas as pd
    import requests
    from selectolax.lexbor import LexborHTMLParser

    HERE_DIR = Path(__file__).parent
    CACHE = Path(os.environ.get("EPA_CACHE_DIR", HERE_DIR / "cache"))
    OUT = Path(os.environ.get("EPA_OUT_DIR", HERE_DIR / "outputs"))
    PAGE_CAP = int(os.environ.get("EPA_PAGE_CAP", "80000"))
    WORKERS = int(os.environ.get("EPA_WORKERS", "6"))
    DELAY = float(os.environ.get("EPA_DELAY", "0.5"))
    SEED = int(os.environ.get("EPA_SEED", "233"))
    HAND_CHECK_SIZE = int(os.environ.get("EPA_HAND_CHECK_SIZE", "30"))
    PARENT_URL = os.environ.get(
        "EPA_PARENT_OUTPUTS_URL",
        "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/"
        "spike/epa-archive-datasets/epa-archive-datasets/outputs",
    )
    assert PAGE_CAP > 0 and 1 <= WORKERS <= 8 and DELAY >= 0.2, "keep the crawl bounded and polite"
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "fulton-ring-epa-live-archive-links/0.1 (research spike)"
    RUN_STARTED = time.perf_counter()
    return (
        CACHE,
        DELAY,
        HAND_CHECK_SIZE,
        HERE_DIR,
        LexborHTMLParser,
        OUT,
        PAGE_CAP,
        PARENT_URL,
        RUN_STARTED,
        SEED,
        ThreadPoolExecutor,
        WORKERS,
        as_completed,
        io_module,
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
        urljoin,
        urllib,
        urlsplit,
    )


@app.cell
def _(requests, session, time):
    def get(url: str, *, method: str = "GET", timeout: int = 60) -> requests.Response | None:
        """Three tries with backoff. Returns the last response, or None if the network failed."""
        response = None
        for attempt in range(3):
            try:
                response = session.request(method, url, timeout=timeout, allow_redirects=True)
                if response.status_code < 500:
                    return response
            except requests.RequestException:
                response = None
            time.sleep(2**attempt)
        return response

    return (get,)


@app.cell
def _(mo):
    mo.md(
        """
        ## The data: www.epa.gov's sitemaps

        EPA's Drupal site publishes a sitemap index at `www.epa.gov/sitemap.xml`. It points to
        numbered pages of 2,000 addresses each. The sitemap is the bounded list we crawl: every
        page EPA itself lists as part of its current site. We drop anything robots.txt
        disallows, and if `EPA_PAGE_CAP` is below the sitemap's size we take a seeded random
        sample of that many pages.
        """
    )
    return


@app.cell
def _(PAGE_CAP, SEED, get, random, re, urllib):
    robots = urllib.robotparser.RobotFileParser("https://www.epa.gov/robots.txt")
    robots.read()
    index_response = get("https://www.epa.gov/sitemap.xml")
    assert index_response is not None and index_response.status_code == 200, "no sitemap index"
    sitemap_pages = re.findall(r"<loc>([^<]+)</loc>", index_response.text)
    assert 0 < len(sitemap_pages) < 200, f"unexpected sitemap index size {len(sitemap_pages)}"
    sitemap_urls: list[str] = []
    for sitemap_page in sitemap_pages:
        page_response = get(sitemap_page.replace("&amp;", "&"))
        assert page_response is not None and page_response.status_code == 200, sitemap_page
        sitemap_urls += re.findall(r"<loc>([^<]+)</loc>", page_response.text)
    sitemap_urls = sorted(set(u.replace("&amp;", "&") for u in sitemap_urls))
    allowed = [u for u in sitemap_urls if robots.can_fetch("*", u)]
    crawl_list = (
        allowed
        if len(allowed) <= PAGE_CAP
        else sorted(random.Random(SEED).sample(allowed, PAGE_CAP))
    )
    print(
        f"sitemap: {len(sitemap_pages)} pages, {len(sitemap_urls):,} addresses, "
        f"{len(allowed):,} allowed by robots.txt, {len(crawl_list):,} to crawl"
    )
    return allowed, crawl_list, sitemap_urls


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 1: fetch every page and keep its links into the archive

        A link counts if it resolves to `archive.epa.gov`, or to `www.epa.gov/archive/`, which
        serves the same archive content under the main site's address. We note whether the link
        sits inside the page's `<main>` element, so site-wide navigation can be told apart from a
        link a program office put in its own content.

        The crawl is polite: `EPA_WORKERS` requests at a time (default 6), each worker waits
        `EPA_DELAY` seconds (default 0.5) after every request, and failed requests are retried
        at most three times. Each fetched page is appended to `cache/pages.jsonl`, so a crawl
        that stops can resume where it left off. The full sitemap takes about three hours.
        """
    )
    return


@app.cell
def _(
    CACHE,
    DELAY,
    LexborHTMLParser,
    ThreadPoolExecutor,
    WORKERS,
    as_completed,
    crawl_list,
    get,
    json,
    time,
    urljoin,
    urlsplit,
):
    def archive_links(page_url: str, html: str) -> tuple[str, list[dict[str, object]]]:
        tree = LexborHTMLParser(html)
        title_node = tree.css_first("title")
        main = tree.css_first("main")
        main_anchors = main.css("a[href]") if main is not None else []
        main_hrefs = {(a.attributes.get("href") or "").strip() for a in main_anchors}
        found = []
        for anchor in tree.css("a[href]"):
            href = (anchor.attributes.get("href") or "").strip()
            target = urljoin(page_url, href)
            parts = urlsplit(target)
            host = parts.netloc.lower()
            if host == "archive.epa.gov" or (
                host == "www.epa.gov" and parts.path.startswith("/archive/")
            ):
                found.append(
                    {
                        "href": target,
                        "text": anchor.text(strip=True)[:200],
                        "in_main": href in main_hrefs,
                    }
                )
        title = title_node.text(strip=True) if title_node is not None else ""
        return title, found

    def fetch_page(url: str) -> dict[str, object]:
        started = time.perf_counter()
        response = get(url)
        time.sleep(DELAY)
        record: dict[str, object] = {
            "url": url,
            "final_url": "",
            "status": 0,
            "bytes": 0,
            "title": "",
            "links": [],
        }
        if response is not None:
            record |= {
                "status": response.status_code,
                "final_url": response.url,
                "bytes": len(response.content),
            }
            if response.status_code == 200 and "html" in response.headers.get("content-type", ""):
                record["title"], record["links"] = archive_links(response.url, response.text)
        record["seconds"] = round(time.perf_counter() - started, 3)
        return record

    pages_file = CACHE / "pages.jsonl"
    done = set()
    if pages_file.exists():
        done = {json.loads(line)["url"] for line in pages_file.read_text().splitlines()}
    todo = [u for u in crawl_list if u not in done]
    crawl_started = time.perf_counter()
    print(f"{len(done):,} pages cached, {len(todo):,} to fetch")
    with pages_file.open("a") as sink, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for batch_start in range(0, len(todo), 600):
            futures = [pool.submit(fetch_page, u) for u in todo[batch_start : batch_start + 600]]
            for future in as_completed(futures):
                sink.write(json.dumps(future.result()) + "\n")
            sink.flush()
            print(f"  fetched {batch_start + len(futures):,} of {len(todo):,}", flush=True)
    crawl_seconds = time.perf_counter() - crawl_started
    return crawl_seconds, pages_file


@app.cell
def _(crawl_list, json, pages_file, pd):
    wanted = set(crawl_list)
    records = [json.loads(line) for line in pages_file.read_text().splitlines()]
    pages = pd.DataFrame([r for r in records if r["url"] in wanted]).drop_duplicates(
        "url", keep="last"
    )
    assert len(pages) == len(wanted), "every page in the crawl list should have a record"
    pages["section"] = pages["url"].str.split("/").str[3]
    pages["archive_links"] = pages["links"].str.len()
    crawl_summary = pd.DataFrame(
        {
            "pages": [
                len(pages),
                (pages["status"] == 200).sum(),
                (pages["status"] == 404).sum(),
                (~pages["status"].isin([200, 404])).sum(),
                (pages["archive_links"] > 0).sum(),
            ]
        },
        index=[
            "crawled",
            "HTTP 200",
            "HTTP 404",
            "other status or network failure",
            "link into archive.epa.gov",
        ],
    )
    crawl_summary
    return crawl_summary, pages


@app.cell
def _(crawl_summary, mo):
    linking = crawl_summary.loc["link into archive.epa.gov", "pages"]
    crawled = crawl_summary.loc["crawled", "pages"]
    mo.md(
        f"""
        **{linking:,} of {crawled:,} live pages ({linking / crawled:.1%}) link into the
        archive.** The next step sorts those links by what they point at.
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 2: what do the links point at?

        We sort each link by its file extension, as #217 did inside the archive. **Data file**
        means the types the issue names (xls, xlsx, csv, xpt, mdb, zip) plus their close
        relatives (xlsm, tsv, dbf, wk4, accdb, sav, dta, gz, tar, tgz). A zip counts as data
        here because on the archive's program sites zips mostly hold data. **Document** means
        PDFs, Word, PowerPoint and plain text. **Page** is everything that ends in `.htm`,
        `.html`, a script extension or no extension at all, except the archive's home page,
        which we count apart because it's where EPA sends readers to search. The address is
        spelled the way #217 spelled it (`archive.epa.gov/<path>`, with `www.epa.gov/archive/`
        folded in), so we can join to its inventory.
        """
    )
    return


@app.cell
def _(OUT, pages, pd, unquote, urlsplit):
    kind_of_ext = {
        **dict.fromkeys(
            ["xls", "xlsx", "xlsm", "csv", "tsv", "dbf", "wk4", "mdb", "accdb"]
            + ["xpt", "sav", "dta", "zip", "gz", "tar", "tgz"],
            "data file",
        ),
        **dict.fromkeys(["pdf", "doc", "docx", "ppt", "pptx", "wpd", "txt", "rtf"], "document"),
        **dict.fromkeys(["", "htm", "html", "shtml", "asp", "aspx", "cfm", "php"], "page"),
    }

    def classify(url: str) -> dict[str, str]:
        """The archive address in #217's spelling, its extension and its kind."""
        parts = urlsplit(unquote(url))
        path = parts.path.removeprefix("/archive") if parts.netloc == "www.epa.gov" else parts.path
        leaf = path.rsplit("/", 1)[-1].lower()
        ext = leaf.rsplit(".", 1)[-1] if "." in leaf else ""
        kind = "archive home" if path in ("", "/") else kind_of_ext.get(ext, "other")
        return {
            "address": "archive.epa.gov" + path + (f"?{parts.query}" if parts.query else ""),
            "archive_section": path.split("/")[1] if path.count("/") > 1 else "",
            "ext": ext,
            "kind": kind,
        }

    link_rows = []
    for page in pages[pages["archive_links"] > 0].itertuples():
        for link in page.links:
            link_rows.append(
                {
                    "page": page.url,
                    "page_title": page.title.removesuffix(" | US EPA"),
                    "section": page.section,
                    **classify(link["href"]),
                    "link_text": link["text"],
                    "in_main": link["in_main"],
                }
            )
    links = pd.DataFrame(link_rows).drop_duplicates(["page", "address"])
    links.to_csv(OUT / "archive_links.csv", index=False)
    links_by_kind = links.groupby("kind").agg(
        links=("address", "size"),
        distinct_targets=("address", "nunique"),
        pages=("page", "nunique"),
        in_main=("in_main", "sum"),
    )
    links_by_kind.loc["all"] = [
        len(links),
        links["address"].nunique(),
        links["page"].nunique(),
        links["in_main"].sum(),
    ]
    links_by_kind.to_csv(OUT / "links_by_kind.csv")
    print(links_by_kind.to_string())
    links_by_kind
    return classify, links


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 2b: follow page links one step into the archive

        A live page rarely needs to link a spreadsheet directly. EPA's NAEMS page, the case that
        started this spike, links to the archive's home page and tells readers to search it,
        and many program pages link to an archive page that lists the files. So for every
        distinct archive page a live page links to, we fetch that page from archive.epa.gov
        (same politeness rules, cached in `cache/archive_pages.jsonl`) and collect its links to
        data files in the archive. A live page then reaches a data file through the archive
        **directly** (it links the file) or **via an archive page** (it links a page that links
        the file). We go one step only.
        """
    )
    return


@app.cell
def _(
    CACHE,
    DELAY,
    LexborHTMLParser,
    ThreadPoolExecutor,
    WORKERS,
    classify,
    get,
    json,
    links,
    pd,
    time,
    urljoin,
    urlsplit,
):
    def data_links_on(address: str) -> dict[str, object]:
        response = get(f"https://{address}")
        time.sleep(DELAY)
        record: dict[str, object] = {"address": address, "status": 0, "files": []}
        if response is None:
            return record
        record["status"] = response.status_code
        if response.status_code == 200 and "html" in response.headers.get("content-type", ""):
            hrefs = [
                urljoin(response.url, a.attributes.get("href") or "")
                for a in LexborHTMLParser(response.text).css("a[href]")
            ]
            on_archive = [
                classify(h)
                for h in hrefs
                if urlsplit(h).netloc == "archive.epa.gov"
                or (
                    urlsplit(h).netloc == "www.epa.gov" and urlsplit(h).path.startswith("/archive/")
                )
            ]
            record["files"] = sorted({c["address"] for c in on_archive if c["kind"] == "data file"})
        return record

    archive_pages_file = CACHE / "archive_pages.jsonl"
    archive_done = {}
    if archive_pages_file.exists():
        for line in archive_pages_file.read_text().splitlines():
            archive_done[json.loads(line)["address"]] = json.loads(line)
    page_targets = sorted(links.loc[links["kind"] == "page", "address"].unique())
    archive_todo = [a for a in page_targets if a not in archive_done]
    with archive_pages_file.open("a") as archive_sink, ThreadPoolExecutor(WORKERS) as hop_pool:
        for hop_record in hop_pool.map(data_links_on, archive_todo):
            archive_sink.write(json.dumps(hop_record) + "\n")
            archive_done[hop_record["address"]] = hop_record
    archive_pages = pd.DataFrame([archive_done[a] for a in page_targets])
    hop_links = archive_pages[["address", "files"]].explode("files").dropna()
    hop_links = hop_links.rename(columns={"address": "via", "files": "file"})
    print(
        f"{len(archive_pages):,} archive pages fetched: "
        f"{(archive_pages['status'] == 200).sum():,} returned 200, "
        f"{(archive_pages['files'].str.len() > 0).sum():,} list data files, "
        f"{hop_links['file'].nunique():,} distinct data files among them"
    )
    return archive_pages, hop_links


@app.cell
def _(OUT, classify, hop_links, links, mo, pd):
    direct = links.loc[links["kind"] == "data file"].assign(via="", route="direct link")
    via_page = links.loc[links["kind"] == "page"].merge(
        hop_links, left_on="address", right_on="via"
    )
    via_page = via_page.drop(columns=["address"]).rename(columns={"file": "address"})
    via_page["route"] = "via archive page"
    data_links = pd.concat([direct, via_page], ignore_index=True)
    data_links["ext"] = [classify(f"https://{a}")["ext"] for a in data_links["address"]]
    data_links = data_links.drop_duplicates(["page", "address"])
    data_links = data_links[["page", "page_title", "section", "address", "ext", "route", "via"]]
    data_links.to_csv(OUT / "data_links.csv", index=False)
    route_summary = data_links.groupby("route").agg(
        pages=("page", "nunique"), files=("address", "nunique"), links=("address", "size")
    )
    home = links[links["kind"] == "archive home"]
    mo.vstack(
        [
            mo.md(
                f"""
            **{data_links["page"].nunique():,} live pages reach
            {data_links["address"].nunique():,} distinct data files through the archive.**
            Another {home["page"].nunique():,} pages link to the archive's home page, as the
            NAEMS page does, which can't be followed to particular files.
            """
            ),
            route_summary,
        ]
    )
    return (data_links,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 3: what does each data link return today, and did #217 capture it?

        We send each distinct data file address a HEAD request (GET if HEAD is refused) and
        record the status. We also join to #217's inventory of the Internet Archive crawl
        (`data_files.csv`, every data file and zip the crawl captured with HTTP 200) and its
        extraction catalog (`catalog.json`, the seven datasets it turned into Parquet). Both are
        read from that spike's published outputs.
        """
    )
    return


@app.cell
def _(PARENT_URL, ThreadPoolExecutor, data_links, get, io_module, json, pd):
    def status_of(url: str) -> int:
        response = get(url, method="HEAD")
        if response is not None and response.status_code in (403, 405):
            response = get(url)
        return response.status_code if response is not None else 0

    targets = pd.DataFrame({"address": sorted(data_links["address"].unique())})
    with ThreadPoolExecutor(max_workers=4) as status_pool:
        targets["status_today"] = list(
            status_pool.map(lambda a: status_of(f"https://{a}"), targets["address"])
        )
    parent_files = get(f"{PARENT_URL}/data_files.csv")
    parent_catalog = get(f"{PARENT_URL}/catalog.json")
    assert parent_files is not None and parent_files.status_code == 200, "no #217 inventory"
    assert parent_catalog is not None and parent_catalog.status_code == 200, "no #217 catalog"
    inventory = pd.read_csv(io_module.StringIO(parent_files.text), dtype=str)
    extracted = {
        "archive.epa.gov" + entry["original_url"].split("archive.epa.gov", 1)[1]
        for entry in json.loads(parent_catalog.text)
    }
    targets["in_217_crawl"] = targets["address"].isin(set(inventory["address"]))
    targets["in_217_parquet"] = targets["address"].isin(extracted)
    targets.groupby("status_today").size().rename("data files")
    return status_of, targets


@app.cell
def _(mo, targets):
    mo.md(
        f"""
        **Today {(targets["status_today"] == 200).sum():,} of {len(targets):,} archive data files
        still download.** {(targets["status_today"] == 404).sum():,} are already 404, so
        those links were broken before the retirement. #217's crawl captured
        {targets["in_217_crawl"].sum():,} of them, and extracted
        {targets["in_217_parquet"].sum():,} to Parquet.
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 4: does each data file have a live copy anywhere else?

        This is #217's matching, run on every distinct data file a live page reaches:

        - **www.epa.gov.** Files under `archive.epa.gov/epa/sites/production/files/` were moved
          from www.epa.gov, so we try `www.epa.gov/sites/default/files/<same path>`. For other
          files we try `www.epa.gov/<same path>`.
        - **EPA's snapshot sites** (`19january2017snapshot`, `…2021…`, `…2025…`) at the same
          paths. These are frozen copies, not the live site, so we report them separately.
        - **data.gov**, by searching the catalog for the file name and accepting a hit only if a
          listed download URL ends in the same file name.

        A copy counts only on HTTP 200. gaftp.epa.gov has no search and is too big to list, so
        it's covered by the hand check in Step 5. A file counts as **archive-only** when neither
        www.epa.gov nor data.gov has it. Matching by file name misses a dataset republished
        under a new name, so this count is an upper bound.
        """
    )
    return


@app.cell
def _(ThreadPoolExecutor, get, json, quote, status_of, targets, unquote, urlencode):
    snapshot_hosts = [
        "19january2017snapshot.epa.gov",
        "19january2021snapshot.epa.gov",
        "19january2025snapshot.epa.gov",
    ]
    moved_prefix = "/epa/sites/production/files/"

    def on_data_gov(file_name: str) -> str:
        response = get(f"https://catalog.data.gov/search?{urlencode({'q': file_name})}")
        if response is None or response.status_code != 200:
            return "error"
        for result in json.loads(response.content)["results"]:
            for dist in (result.get("dcat") or {}).get("distribution") or []:
                link = dist.get("downloadURL") or dist.get("accessURL") or ""
                if unquote(link).lower().rstrip("/").endswith("/" + file_name.lower()):
                    return link
        return ""

    def check(address: str) -> dict[str, str]:
        path = address.removeprefix("archive.epa.gov")
        www_path, snapshot_path = path, path
        if path.startswith(moved_prefix):
            www_path = "/sites/default/files/" + path.removeprefix(moved_prefix)
            snapshot_path = "/sites/production/files/" + path.removeprefix(moved_prefix)
        www_url = f"https://www.epa.gov{quote(www_path)}"
        snapshot_urls = [f"https://{h}{quote(snapshot_path)}" for h in snapshot_hosts]
        return {
            "address": address,
            "www.epa.gov": www_url if status_of(www_url) == 200 else "",
            "EPA snapshots": next((u for u in snapshot_urls if status_of(u) == 200), ""),
            "data.gov": on_data_gov(path.rsplit("/", 1)[-1]),
        }

    with ThreadPoolExecutor(max_workers=4) as copy_pool:
        copies = list(copy_pool.map(check, targets["address"]))
    return (copies,)


@app.cell
def _(OUT, copies, pd, targets):
    copy_columns = ["address", "www.epa.gov", "EPA snapshots", "data.gov"]
    files = targets.merge(pd.DataFrame(copies, columns=copy_columns), on="address")
    assert (files["data.gov"] != "error").all(), "data.gov search failed for some files; rerun"
    files["origin"] = (
        files["address"]
        .str.startswith("archive.epa.gov/epa/sites/production/")
        .map({True: "moved from www.epa.gov", False: "legacy program site"})
    )
    files["archive_only_by_name"] = (files["www.epa.gov"] == "") & (files["data.gov"] == "")
    files.to_csv(OUT / "data_file_copies.csv", index=False)
    copy_summary = files.groupby("origin").agg(
        data_files=("address", "size"),
        on_www=("www.epa.gov", lambda c: (c != "").sum()),
        on_data_gov=("data.gov", lambda c: (c != "").sum()),
        in_snapshots=("EPA snapshots", lambda c: (c != "").sum()),
        archive_only_by_name=("archive_only_by_name", "sum"),
    )
    copy_summary.loc["all"] = copy_summary.sum()
    print(copy_summary.to_string())
    copy_summary
    return (files,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 5: hand-check a sample of the archive-only files

        File-name matching overstates archive-only files, because EPA often republished a
        dataset under a new name or moved it to gaftp.epa.gov or another EPA system. We draw a
        seeded sample of the files the matcher called archive-only and, for each one, searched
        by hand: the file name and the dataset's title on the web, the linking page's program
        on www.epa.gov, gaftp.epa.gov directory listings and data.gov. The verdicts are in
        `hand_check.csv`, which this notebook reads. `outputs/hand_check_sample.csv` is the
        sample to fill in if the crawl turns up different files.

        The share of sampled files the hand check confirms as archive-only is the correction
        we apply to the file-name count.
        """
    )
    return


@app.cell
def _(HAND_CHECK_SIZE, HERE_DIR, OUT, SEED, files, pd, random):
    archive_only = sorted(files.loc[files["archive_only_by_name"], "address"])
    hand_sample = sorted(
        random.Random(SEED).sample(archive_only, min(HAND_CHECK_SIZE, len(archive_only)))
    )
    pd.DataFrame({"address": hand_sample}).to_csv(OUT / "hand_check_sample.csv", index=False)
    hand_check = pd.read_csv(HERE_DIR / "hand_check.csv", dtype=str, keep_default_na=False)
    assert set(hand_check["archive_only"]) <= {"yes", "no"}, "archive_only must be yes or no"
    checked = hand_check[hand_check["address"].isin(hand_sample)]
    confirmed_rate = (checked["archive_only"] == "yes").mean()
    print(
        f"hand-checked {len(checked)} of {len(hand_sample)} sampled archive-only files; "
        f"{(checked['archive_only'] == 'yes').sum()} confirmed archive-only "
        f"({confirmed_rate:.0%})"
    )
    checked
    return checked, confirmed_rate, hand_check


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 6: which live pages depend on the archive for their data?

        A page **depends on the archive for data** when at least one of its data links points
        at an archive-only file. We count those pages by the program that owns them (the
        first part of the page's address on www.epa.gov), and list the ten with the most
        archive-only files, with how many of those files #217's crawl captured and extracted.
        Files the hand check found elsewhere no longer count as archive-only. Pages with at
        least one hand-confirmed archive-only file are a lower bound; the estimated number of
        archive-only files multiplies the file-name count by the hand-check rate.
        """
    )
    return


@app.cell
def _(OUT, checked, confirmed_rate, data_links, files, hand_check, pd):
    joined = data_links.merge(files, on="address")
    confirmed_no = set(hand_check.loc[hand_check["archive_only"] == "no", "address"])
    confirmed_yes = set(hand_check.loc[hand_check["archive_only"] == "yes", "address"])
    joined["archive_only"] = joined["archive_only_by_name"] & ~joined["address"].isin(confirmed_no)
    joined["confirmed_archive_only"] = joined["address"].isin(confirmed_yes)
    per_page = joined.groupby(["page", "page_title", "section"]).agg(
        data_links=("address", "size"),
        archive_only_files=("archive_only", "sum"),
        hand_confirmed=("confirmed_archive_only", "sum"),
        files_404_today=("status_today", lambda s: (s == 404).sum()),
        in_217_crawl=("in_217_crawl", "sum"),
        in_217_parquet=("in_217_parquet", "sum"),
    )
    per_page = per_page.reset_index().sort_values(
        ["archive_only_files", "data_links"], ascending=False
    )
    per_page.to_csv(OUT / "pages_with_data_links.csv", index=False)
    dependent = per_page[per_page["archive_only_files"] > 0]
    by_program = (
        dependent.groupby("section")
        .agg(pages=("page", "size"), archive_only_file_links=("archive_only_files", "sum"))
        .sort_values(["pages", "archive_only_file_links"], ascending=False)
    )
    by_program.to_csv(OUT / "dependent_pages_by_program.csv")
    top_ten = dependent.head(10)
    top_ten.to_csv(OUT / "top_ten_pages.csv", index=False)
    headline = pd.Series(
        dtype=object,
        data={
            "pages with a data link into the archive": len(per_page),
            "pages with an archive-only data file": len(dependent),
            "pages with a hand-confirmed archive-only file (lower bound)": int(
                (dependent["hand_confirmed"] > 0).sum()
            ),
            "programs with a dependent page": dependent["section"].nunique(),
            "archive-only data files by file name": int(files["archive_only_by_name"].sum()),
            "hand-check confirmation rate": round(confirmed_rate, 3) if len(checked) else "none",
            "estimated archive-only data files": (
                round(files["archive_only_by_name"].sum() * confirmed_rate) if len(checked) else ""
            ),
        },
    )
    print(headline.to_string())
    print(by_program.to_string())
    headline
    return by_program, dependent, headline, top_ten


@app.cell
def _(by_program, mo, top_ten):
    mo.vstack([mo.md("**Dependent pages by program**"), by_program, mo.md("**Top ten**"), top_ten])
    return


@app.cell
def _(checked, confirmed_rate, crawl_summary, data_links, dependent, files, links, mo):
    crawled_ok = crawl_summary.loc["HTTP 200", "pages"]
    linking_pages = links["page"].nunique()
    direct_files = (data_links["route"] == "direct link").sum()
    home_pages = links.loc[links["kind"] == "archive home", "page"].nunique()
    found_live = checked.loc[checked["archive_only"] == "no", "where_found"]
    cair_via = "archive.epa.gov/airmarkets/programs/cair/web/html/index.html"
    cair_pages = data_links.loc[
        (data_links["via"] == cair_via) & data_links["page"].isin(dependent["page"]), "page"
    ].nunique()
    mo.md(
        f"""
        ## Result

        **The argument mostly fails for data, and EPA has largely cut the dependency.** Of
        {crawled_ok:,} live pages, {linking_pages:,} ({linking_pages / crawled_ok:.1%}) link into
        the archive, and **{direct_files} of those links point straight at a data file**. Following
        page links one step into the archive, {data_links["page"].nunique()} live pages reach
        {len(files)} data files, and {len(dependent)} of them reach at least one file with no live
        copy elsewhere, across {dependent["section"].nunique()} programs. The hand check confirmed
        {(checked["archive_only"] == "yes").sum()} of {len(checked)} sampled archive-only files
        ({confirmed_rate:.0%}); the {len(found_live)} copies it found were in a regulations.gov
        docket, not on EPA's site. {(dependent["hand_confirmed"] > 0).sum()} pages have at least
        one hand-confirmed archive-only file. {cair_pages} of the {len(dependent)} pages reach
        their files through a single archive page, the Clean Air Interstate Rule's.

        **The wider dependency is reading, not data.** {home_pages} live pages send readers to the
        archive's home page to search for something, as the NAEMS page does ("Search EPA
        Archive"), and the other links point at archived pages and PDFs: old news releases,
        enforcement case documents and program history. Those are the links that will break for
        ordinary readers on January 1.

        **What didn't work.** The Wayback Machine's availability and CDX APIs returned HTTP 429
        from this environment, so we couldn't check which files the Internet Archive holds
        beyond #217's indexed crawl. gaftp.epa.gov can't be searched by file name, so it was
        only checked by hand. Sorting by extension counts a zip as data even when it holds Word
        or WordPerfect documents, which several SAP and ozone zips do.
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Coverage, timing and what the crawl couldn't reach

        The crawl covers the pages in EPA's sitemap. It doesn't see pages EPA leaves out of the
        sitemap, links inside PDFs or other documents, links written by JavaScript, or other EPA
        hosts (cfpub.epa.gov, ofmpub.epa.gov, the regional subdomains). Pages that didn't
        return HTTP 200 are counted below and their links are unknown.
        """
    )
    return


@app.cell
def _(OUT, RUN_STARTED, WORKERS, allowed, crawl_seconds, pages, sitemap_urls, time):
    coverage = {
        "sitemap addresses": len(sitemap_urls),
        "allowed by robots.txt": len(allowed),
        "crawled": len(pages),
        "returned 200": int((pages["status"] == 200).sum()),
        "not reached (non-200 or network failure)": int((pages["status"] != 200).sum()),
        "MB downloaded": round(pages["bytes"].sum() / 1e6, 1),
        "median seconds per page": round(float(pages["seconds"].median()), 2),
        "estimated crawl hours from scratch": round(pages["seconds"].sum() / 3600 / WORKERS, 2),
        "crawl seconds this run (0 when cached)": round(crawl_seconds),
        "whole run seconds": round(time.perf_counter() - RUN_STARTED),
    }
    not_reached = pages.loc[pages["status"] != 200, ["url", "status"]]
    not_reached.to_csv(OUT / "pages_not_reached.csv", index=False)
    for name, value in coverage.items():
        print(f"{name}: {value:,}")
    not_reached["status"].value_counts().rename("pages not reached")
    return


if __name__ == "__main__":
    app.run()
