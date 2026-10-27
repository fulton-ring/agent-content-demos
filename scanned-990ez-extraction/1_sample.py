import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import csv
    import hashlib
    import io
    import json
    import os
    import random
    import time
    import urllib.error
    import urllib.request
    import zipfile
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import marimo as mo
    import pypdfium2 as pdfium

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("EZ_OUTPUT_DIR", HERE / "output"))
    PDFS = OUT / "pdfs"
    PAGES = OUT / "pages"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Turning scanned public records into data you can trust

    **The question.** Four steps are meant to turn scanned government records into a dataset people can rely on:
    draft the schema from sample pages and freeze it; measure error on a checked sample; send a field to review when
    two independent readings disagree, not when a model says it is unsure; and keep a link from every value to its
    page and box. Nobody has published the three numbers together for scanned public records: **field-level error,
    review rate, and all-in cost per page**. This demo measures them on real paper-filed IRS Form 990-EZ returns.

    **Why the 990-EZ.** Small nonprofits file it, many still on paper. The IRS scans the paper returns and publishes
    the images, and its Statistics of Income (SOI) division separately types the numbers from the same returns into
    a public annual extract. So we have real scans and an answer key typed from them by someone else.

    The demo is three notebooks, which hand their results on through files in `output/`:

    1. **This one** draws the sample and downloads the scans.
    2. **`2_extraction.py`** drafts and freezes the schema, then has two vision models read every page.
    3. **`3_results.py`** applies the review rule, scores everything against the SOI extract, and reports.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The answer key

    The SOI 990-EZ extract for 2018 lists every 990-EZ the IRS processed that year, one row per return. The `elf`
    column says how it was filed: `E` for e-filed, `P` for paper. E-filed returns also have page images, but those
    are drawn from the data, not scanned, so **we keep only the paper rows**.
    """)
    return


@app.cell
def _():
    SOI_URL = "https://www.irs.gov/pub/irs-soi/18eoextractez.zip"
    soi_zip = OUT / "18eoextractez.zip"
    if not soi_zip.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(SOI_URL, timeout=120) as _r:
            soi_zip.write_bytes(_r.read())
    with zipfile.ZipFile(soi_zip) as _z, _z.open("18eoextractez.csv") as _f:
        soi_rows = list(csv.DictReader(io.TextIOWrapper(_f, encoding="utf-8-sig")))
    paper = [r for r in soi_rows if r["elf"] == "P"]
    print(f"{len(soi_rows):,} returns in the extract, {len(paper):,} filed on paper")
    return (paper,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The sample

    A fixed random sample of 220 paper returns, seeded so every run draws the same ones. We aimed for about 200
    readable pages and expected some downloads to fail.

    **Finding each scan.** The IRS doesn't publish an index from a return to its image file. ProPublica's Nonprofit
    Explorer API lists each organization's filings with the image file's name, so we look up the EIN and take the
    filing whose tax period matches the SOI row. The file itself we fetch from the IRS, at
    `apps.irs.gov/pub/epostcard/cor/<file>`, because ProPublica's download link refuses scripts. Every failure is
    logged with its reason.
    """)
    return


@app.cell
def _(paper):
    SAMPLE_SIZE, SEED = 220, 990
    sample = random.Random(SEED).sample(paper, SAMPLE_SIZE)
    return (sample,)


@app.cell
def _(sample):
    def fetch(url: str) -> bytes:
        """GET with three attempts. A 404 isn't retried."""
        request = urllib.request.Request(url, headers={"User-Agent": "fulton-ring-990ez-spike/0.1"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    return response.read()
            except urllib.error.HTTPError as e:
                if e.code == 404 or attempt == 2:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
            time.sleep(5 * (attempt + 1))
        raise AssertionError("unreachable")

    def get_scan(row: dict) -> dict:
        """Find the return's image file through ProPublica, download it from the IRS and render page 1."""
        ein, tax_pd = row["ein"], row["tax_pd"]
        result = {"ein": ein, "tax_pd": tax_pd}
        pdf, png = PDFS / f"{ein}_{tax_pd}.pdf", PAGES / f"{ein}_{tax_pd}.png"
        if not pdf.exists():
            try:
                org = json.loads(fetch(f"https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json"))
            except urllib.error.HTTPError as e:
                return result | {"failure": f"ProPublica lookup: HTTP {e.code}"}
            filings = org.get("filings_with_data", []) + org.get("filings_without_data", [])
            urls = [f["pdf_url"] for f in filings if str(f["tax_prd"]) == tax_pd and f.get("pdf_url")]
            if not urls:
                return result | {"failure": "ProPublica lists no image for this tax period"}
            result["file"] = urls[0].split("%2F")[-1]
            try:
                data = fetch(f"https://apps.irs.gov/pub/epostcard/cor/{result['file']}")
            except urllib.error.HTTPError as e:
                return result | {"failure": f"IRS download: HTTP {e.code}"}
            if not data.startswith(b"%PDF"):
                return result | {"failure": "IRS download: not a PDF"}
            pdf.write_bytes(data)
        result["sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
        doc = pdfium.PdfDocument(pdf)
        result["pages_in_file"] = len(doc)
        if not png.exists():
            doc[0].render(scale=150 / 72).to_pil().convert("L").save(png)
        return result

    PDFS.mkdir(parents=True, exist_ok=True)
    PAGES.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as pool:
        scans = list(pool.map(get_scan, sample))
    failures = [s for s in scans if "failure" in s]
    print(f"{len(scans) - len(failures)} of {len(scans)} scans downloaded; {len(failures)} failed")
    for s in failures:
        print(f"  {s['ein']} {s['tax_pd']}: {s['failure']}")
    return (scans,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    We keep page 1 only, rendered at 150 dpi in greyscale. It holds the header (name, EIN, tax year) and Part I,
    revenue, expenses and net assets: about 20 numbers. The file's sha256 is logged, so a later run can tell if the
    IRS replaced an image. Here is one page as the models see it.
    """)
    return


@app.cell
def _(sample, scans):
    (OUT / "sample.json").write_text(
        json.dumps([{"soi": row} | scan for row, scan in zip(sample, scans, strict=True)], indent=1)
    )
    _first = next(s for s in scans if "failure" not in s)
    mo.image(PAGES / f"{_first['ein']}_{_first['tax_pd']}.png", width=600)
    return


if __name__ == "__main__":
    app.run()
