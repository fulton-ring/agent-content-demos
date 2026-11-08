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

    HERE = Path(__file__).parent
    CACHE = Path(os.environ.get("EPA_CACHE_DIR", HERE / "cache"))
    OUT = Path(os.environ.get("EPA_OUT_DIR", HERE / "outputs"))
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
    assert PAGE_CAP > 0 and 1 <= WORKERS <= 8 and DELAY >= 0.2, (
        "keep the crawl bounded and polite"
    )
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = (
        "fulton-ring-epa-live-archive-links/0.1 (research spike)"
    )
    RUN_STARTED = time.perf_counter()
    return (
        CACHE,
        DELAY,
        HAND_CHECK_SIZE,
        LexborHTMLParser,
        OUT,
        PAGE_CAP,
        PARENT_URL,
        RUN_STARTED,
        SEED,
        ThreadPoolExecutor,
        WORKERS,
        as_completed,
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
    def get(
        url: str, *, method: str = "GET", timeout: int = 60
    ) -> requests.Response | None:
        """Three tries with backoff. Returns the last response, or None if the network failed."""
        response = None
        for attempt in range(3):
            try:
                response = session.request(
                    method, url, timeout=timeout, allow_redirects=True
                )
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
    assert index_response is not None and index_response.status_code == 200, (
        "no sitemap index"
    )
    sitemap_pages = re.findall(r"<loc>([^<]+)</loc>", index_response.text)
    assert 0 < len(sitemap_pages) < 200, (
        f"unexpected sitemap index size {len(sitemap_pages)}"
    )
    sitemap_urls: list[str] = []
    for sitemap_page in sitemap_pages:
        page_response = get(sitemap_page.replace("&amp;", "&"))
        assert page_response is not None and page_response.status_code == 200, (
            sitemap_page
        )
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
            if response.status_code == 200 and "html" in response.headers.get(
                "content-type", ""
            ):
                record["title"], record["links"] = archive_links(
                    response.url, response.text
                )
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
            futures = [
                pool.submit(fetch_page, u)
                for u in todo[batch_start : batch_start + 600]
            ]
            for future in as_completed(futures):
                sink.write(json.dumps(future.result()) + "\n")
            sink.flush()
            print(
                f"  fetched {batch_start + len(futures):,} of {len(todo):,}", flush=True
            )
    crawl_seconds = time.perf_counter() - crawl_started
    return crawl_seconds, pages_file


@app.cell
def _(crawl_list, json, pages_file, pd):
    wanted = set(crawl_list)
    records = [json.loads(line) for line in pages_file.read_text().splitlines()]
    pages = pd.DataFrame([r for r in records if r["url"] in wanted]).drop_duplicates(
        "url", keep="last"
    )
    assert len(pages) == len(wanted), (
        "every page in the crawl list should have a record"
    )
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


if __name__ == "__main__":
    app.run()
