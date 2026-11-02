import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import random
    import re
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    import marimo as mo
    import pandas as pd
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    from common import FIS, HERE, fis_pdf, tesseract, text_layer


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 1. How many pages of a FEMA flood study need OCR?

    Firecrawl says it built its `pdf-inspector` to skip OCR "for the ~54% of PDFs that don't need them", with no
    source or method given. Before any model reads a page, a pipeline has to decide whether the page's own text
    layer can be trusted or whether it needs OCR (or a vision model). This notebook measures that on a sample of
    FEMA Flood Insurance Studies (FIS), page by page and PDF by PDF.

    **The sample.** Twelve counties drawn with `random.Random(175)` from the Census 2024 county list, and every FIS
    report FEMA's Map Service Center lists for them, current and superseded: 70 PDFs from 1978 to 2024. The draw
    is fixed in `common.py` with each file's hash; the cell below re-runs it only if `REDRAW_SAMPLE=1`.
    """)
    return


@app.cell
def _():
    def draw_sample() -> list[str]:
        """The draw as it was run on 2026-11-01. The MSC's listings change, so the run uses the frozen list."""
        url = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_counties_national.txt"
        lines = urllib.request.urlopen(url, timeout=120).read().decode().splitlines()
        counties = [line.split("\t")[1] for line in lines[1:] if not line.startswith("PR")]
        products = []
        for geoid in random.Random(175).sample(counties, 12):
            search = (
                "https://msc.fema.gov/portal/advanceSearch?affiliate=fema&query&method=search"
                f"&selstate={geoid[:2]}&selcounty={geoid}&selcommunity={geoid}C&searchedCid={geoid}C"
            )
            listing = json.load(urllib.request.urlopen(search, timeout=120))
            products += [p["product_NAME"] for p in listing.get("FIS_REPORT", [])]
        return products

    if os.environ.get("REDRAW_SAMPLE") == "1":
        print("redrawn:", sorted(draw_sample()) == sorted(FIS))
    pdfs = {product: fis_pdf(product) for product in FIS}
    print(f"{len(pdfs)} FIS PDFs downloaded")
    return (pdfs,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Classify every page from the PDF itself

    This is the cheap check a router runs in milliseconds, much as `pdf-inspector` does: look at what the page is
    made of, without OCR. A page is

    - **text** if its text layer has at least 50 characters;
    - **scan** if it has less, and one image covers at least 70% of the page;
    - **drawing** if it has less and no such image, but is drawn in vector paths: the flood profiles, whose
      labels are drawn as outlines rather than text;
    - **blank** otherwise.

    A page **needs OCR** if it is a scan or a drawing: something is printed on it that its text layer doesn't carry.
    """)
    return


@app.cell
def _(pdfs):
    _rows = []
    for _product, _pdf in pdfs.items():
        _doc = pdfium.PdfDocument(_pdf)
        for _i in range(len(_doc)):
            _page = _doc[_i]
            _width, _height = _page.get_size()
            _image_share, _paths = 0.0, 0
            for _obj in _page.get_objects(max_depth=3):
                if _obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
                    _l, _b, _r, _t = _obj.get_bounds()
                    _image_share = max(_image_share, (_r - _l) * (_t - _b) / (_width * _height))
                _paths += _obj.type == pdfium_c.FPDF_PAGEOBJ_PATH
            _chars = len(re.sub(r"\s", "", _page.get_textpage().get_text_bounded()))
            if _chars >= 50:
                _kind = "text"
            elif _image_share >= 0.7:
                _kind = "scan"
            elif _paths >= 50:
                _kind = "drawing"
            else:
                _kind = "blank"
            _rows.append({"pdf": _product, "page": _i + 1, "chars": _chars, "kind": _kind})
    pages = pd.DataFrame(_rows)
    pages["needs_ocr"] = pages.kind.isin(["scan", "drawing"])
    pages["year"] = pages.pdf.map(lambda p: int(FIS[p][1][-4:]))
    print(pages.kind.value_counts().to_string())
    return (pages,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Check the classifier against Tesseract

    The check above never looks at the pixels, so we test it. On 200 pages drawn with `random.Random(175)`,
    Tesseract reads the rendered page. Tesseract's verdict is that a page **needs OCR** if Tesseract finds at least
    15 words of three or more letters and the text layer holds fewer than half as many.
    """)
    return


@app.cell
def _(pages, pdfs):
    _sample = pages.sample(200, random_state=175)

    def _words(text: str) -> int:
        return len(re.findall(r"[A-Za-z]{3,}", text))

    def _tesseract_says(row: pd.Series) -> bool:
        seen = _words(tesseract(pdfs[row.pdf], row.page)[0])
        return seen >= 15 and _words(text_layer(pdfs[row.pdf], row.page)) < seen / 2

    with ThreadPoolExecutor(4) as _pool:
        _verdicts = list(_pool.map(_tesseract_says, [r for _, r in _sample.iterrows()]))
    _sample = _sample.assign(tesseract_says=_verdicts)
    check = pd.crosstab(_sample.needs_ocr, _sample.tesseract_says, rownames=["classifier"], colnames=["Tesseract"])
    agreement = (_sample.needs_ocr == _sample.tesseract_says).mean()
    disagree = _sample[_sample.needs_ocr != _sample.tesseract_says][["pdf", "page", "kind", "chars"]]
    print(check.to_string())
    print(f"agreement on {len(_sample)} pages: {agreement:.1%}")
    print(disagree.to_string(index=False))
    return agreement, check


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The share that needs OCR, by page and by PDF

    Firecrawl's figure is per PDF, so we give both. A PDF "doesn't need OCR" only if none of its pages do. Flood
    profiles are drawings that a reader of the tables can skip, so we also give the share with drawings set aside,
    which is the generous reading for a router.
    """)
    return


@app.cell
def _(pages):
    _by_pdf = pages.groupby("pdf").agg(
        year=("year", "first"),
        pages=("page", "size"),
        scan=("kind", lambda k: (k == "scan").sum()),
        drawing=("kind", lambda k: (k == "drawing").sum()),
    )
    _by_pdf["era"] = pd.cut(_by_pdf.year, [0, 1999, 2009, 2030], labels=["1978-1999", "2000-2009", "2010-2024"])
    _kind = pages.kind.value_counts()
    summary = {
        "pdfs": len(_by_pdf),
        "pages": len(pages),
        "pages_text": int(_kind.get("text", 0)),
        "pages_scan": int(_kind.get("scan", 0)),
        "pages_drawing": int(_kind.get("drawing", 0)),
        "pages_blank": int(_kind.get("blank", 0)),
        "share_pages_need_ocr": float(pages.needs_ocr.mean()),
        "share_pdfs_no_ocr": float(((_by_pdf.scan + _by_pdf.drawing) == 0).mean()),
        "share_pdfs_no_ocr_drawings_aside": float((_by_pdf.scan == 0).mean()),
        "pdfs_all_scanned": int((_by_pdf.scan == _by_pdf.pages).sum()),
    }
    _era = _by_pdf.groupby("era", observed=True).agg(
        pdfs=("pages", "size"),
        pages=("pages", "sum"),
        scan=("scan", "sum"),
        drawing=("drawing", "sum"),
        no_ocr_pdfs=("scan", lambda s: int(((s + _by_pdf.loc[s.index, "drawing"]) == 0).sum())),
    )
    _era["share_pages_need_ocr"] = ((_era.scan + _era.drawing) / _era.pages).round(3)
    print(json.dumps(summary, indent=1))
    print(_era.to_string())
    by_era = _era
    return by_era, summary


@app.cell
def _(agreement, by_era, check, summary):
    _out = HERE / "results"
    _out.mkdir(exist_ok=True)
    (_out / "1_ocr_share.json").write_text(
        json.dumps({**summary, "tesseract_check_agreement": float(agreement)}, indent=1)
    )
    (_out / "1_ocr_share.md").write_text(
        "# OCR share, FEMA FIS sample\n\n"
        + pd.Series(summary).to_markdown()
        + "\n\n## By effective date\n\n"
        + by_era.to_markdown()
        + "\n\n## Classifier against Tesseract, 200 seeded pages\n\n"
        + check.to_markdown()
        + "\n"
    )
    mo.md(f"""
    **Result.** Of {summary["pages"]:,} pages in {summary["pdfs"]} FIS PDFs,
    {summary["share_pages_need_ocr"]:.0%} need OCR: {summary["pages_scan"]:,} scans with no text layer and
    {summary["pages_drawing"]:,} vector drawings. Only {summary["share_pdfs_no_ocr"]:.0%} of the PDFs need no OCR
    at all ({summary["share_pdfs_no_ocr_drawings_aside"]:.0%} if the flood profiles are set aside), against
    Firecrawl's ~54%. {summary["pdfs_all_scanned"]} PDFs are scans from cover to cover, with no text layer at
    all. The cheap classifier agreed with Tesseract on {agreement:.0%} of 200 sampled pages.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this doesn't show

    - It counts pages that need OCR, not pages a pipeline needs. A tables-only reader can skip most drawings.
    - The text layer on "text" pages is trusted here. `2_long_vs_short.py` tests whether it reads right.
    - Twelve counties is a small draw. The split between scanned and born-digital studies follows FEMA's history:
      community studies before about 2005 were typed and are now scans, countywide studies since are digital.
    """)
    return


if __name__ == "__main__":
    app.run()
