import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        r"""
    # Can our FEMA and NRC answer keys become an open OCR benchmark for US public records?

    The spike `fema-nrc-extraction-accuracy/` (PR #177) keyed 1,121 values by hand-and-model on 18 pages of US
    federal records: 404 values on 8 *Summary of Discharges* pages from FEMA Flood Insurance Studies (FIS), and 717
    numbers on 10 pages of 1975-1984 NRC reports scanned at OSTI. This notebook turns those keys into
    [olmOCR-Bench](https://github.com/allenai/olmocr/tree/main/olmocr/bench) unit tests, scores six pipelines with
    olmOCR's own test code, and writes a review file so a person can check every test against the page.

    **We expected** the born-digital FIS pages to saturate and the poor NRC scans to split the pipelines. **It's
    wrong** if every pipeline scores near 100% on every group.

    Note on size: the issue speaks of "70 FIS and 10 NRC documents". The keys cover one page of each of 8 FIS studies
    and 10 NRC reports, so this is an **18-page** benchmark.
    """
    )
    return (mo,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## First: does this already exist, and may we republish the pages?

    **No benchmark like it exists that we could find.** olmOCR-Bench's 1,403 PDFs come from arXiv, Internet Archive
    books, AI2's own web crawl and, for "old scans", Library of Congress letters (19th-century correspondence, not
    agency reports). OmniDocBench, READoc, CC-OCR, FUNSD/RVL-CDIP and DocVQA (tobacco-industry documents) hold no US
    agency records. The closest are KDoc-OCRBench-V2 (same olmOCR format, 849 *Korean* public-sector pages) and
    LlamaIndex's ExtractBench (49 US government forms among 370 documents, but schema extraction, not OCR tests). No
    Hugging Face dataset mentions FEMA or NUREG.

    **Reuse.** FEMA's site says "Most material on FEMA.gov is free of copyright"; the Map Service Center has no terms
    of its own. NUREG/CR reports were written by contractors, so 17 U.S.C. 105 doesn't make them public domain, and
    OSTI says to treat unmarked items "as if they are protected by copyright"; DOE policy, though, gives contractor
    reports without a copyright claim "unlimited distribution", and none of our ten carries a notice (one,
    NUREG/CR-1724, holds conference papers with contractor licence notices). So the PDFs are downloaded at run time,
    not committed, and only short numbers and phrases appear in the tests. Sources are in the README.
    """
    )
    return


@app.cell
def _():
    import asyncio
    import base64
    import hashlib
    import io
    import json
    import os
    import re
    import subprocess
    import sys
    import time
    import urllib.request
    from collections import Counter
    from pathlib import Path

    import pandas as pd
    import pypdfium2 as pdfium
    import pytesseract
    from olmocr.bench.prompts import build_basic_prompt
    from olmocr.bench.tests import load_tests
    from pydantic_ai import Agent, BinaryContent
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models.openrouter import OpenRouterModelSettings

    HERE = Path(__file__).parent
    SOURCE = HERE.parent / "fema-nrc-extraction-accuracy"  # the spike whose keys we convert; read, never edited
    BENCH = HERE / "bench"  # olmOCR-Bench layout: *.jsonl, pdfs/, one folder of .md output per pipeline
    OUT = Path(os.environ.get("OCR_BENCH_OUTPUT_DIR", HERE / "output"))  # downloads and the review file
    return (
        Agent,
        BENCH,
        BinaryContent,
        Counter,
        HERE,
        ModelResponse,
        OUT,
        OpenRouterModelSettings,
        Path,
        SOURCE,
        asyncio,
        base64,
        build_basic_prompt,
        hashlib,
        io,
        json,
        load_tests,
        pd,
        pdfium,
        pytesseract,
        re,
        subprocess,
        sys,
        time,
        urllib,
    )


@app.cell
def _(mo):
    mo.md(
        r"""
    ## The pages

    Each keyed page goes into one group, and each group becomes one JSONL file, because olmOCR-Bench reports a score
    per JSONL file. FIS pages split into born digital and scanned, as in the source spike. NRC pages split into thirds
    by scan quality (Tesseract's mean word confidence on the page, measured in the source spike's notebook 3). The
    hashes are copied from the source spike's `common.py`, so a changed download fails loudly.
    """
    )
    return


@app.cell
def _():
    # doc: (group, keyed page, sha256 of the whole PDF)
    PAGES = {
        "45061CV000A": ("fis_born_digital", 10, "55cdcfecc58ae9f4ee9d76a3844bc33c533113bc16f185950e6504630edc525a"),
        "35053CV000A": ("fis_born_digital", 11, "107cfebc2aa574a3d23b9a4a7d9b332b954e72c5ea7769d0de2f759f096b549b"),
        "39151CV001C": ("fis_born_digital", 49, "695e35a08d9102ec259ef4361d6df6b6fc49bdaec9c89951bfba5f3d8a2000bc"),
        "35049CV000A": ("fis_born_digital", 12, "3423cc327b5f38c63e1ba7323ea67428dfd730e1cdb4ce1e92ea2d3191808df8"),
        "510218V000": ("fis_scanned", 8, "5c897f58e634b715facce8f1c95448e0f73c30bbee89cf6c316bc349c0fbe2f5"),
        "060724V000": ("fis_scanned", 11, "4eaa85046401b7011c94a654e268c189033fd36f50cc327936ae55c74d3d57d2"),
        "51005CV000A": ("fis_scanned", 16, "85a534f278e82e3097ee444064d67d27fdc2724a9a0c240902158e0f4119fd21"),
        "080290V000": ("fis_scanned", 15, "25c9ea4091cd910915bfc56b5b303993e47fb51216123ba53b6e018c7610dde6"),
        "1083948": ("nrc_poor_scan", 21, "1a4b4e5285e30b67a038425d2a52d552d2fd7d354dafe0587185d2b7f407f9d3"),
        "10125120": ("nrc_poor_scan", 493, "966a499f4420ed22a30e6210227ae3b06f52efb4e87b57d2270dfc39282d0871"),
        "5777799": ("nrc_poor_scan", 77, "b9307d4f33cfc0456c9239340f854686745c0ea4fd84bb047f592735a92c7749"),
        "1083928": ("nrc_poor_scan", 73, "85e0dce4f8e8a2f7365c8c561823d00e3ef3c1f826e78ac2aadacb3ce10364e6"),
        "5507271": ("nrc_fair_scan", 114, "33b18c606d2e939fb0217f65c2a75843a856724db2b6c4d853562ab874b125c7"),
        "5063304": ("nrc_fair_scan", 51, "df03b85275d34cd1467c535c5441d8ff0d2590fdd5b7dfa42f88ddcea0964491"),
        "5533698": ("nrc_fair_scan", 72, "16a5c6cce6463ab5b885a44fdb5186f56a5a4a0e44401fa8ad31a3e92746bb74"),
        "6623512": ("nrc_good_scan", 42, "ab0018aeb7a00198ce6a74fa94e650247a1e26786056285e1e3b2e9784bca4dc"),
        "5239714": ("nrc_good_scan", 10, "05369a6f808d6535c6dc418968651c720325ab4e11387ff83dab067640fa8a39"),
        "6613275": ("nrc_good_scan", 204, "86a109b386a27d643f239619a654ca750eeb014d7dc6e22ba43c9eaebc31a90e"),
    }
    return (PAGES,)


@app.cell
def _(mo):
    mo.md(
        r"""
    Download each document once (FEMA's Map Service Center and OSTI), check its hash, and cut the keyed page out as
    a one-page PDF, because olmOCR-Bench scores single-page PDFs. The PDFs go to `bench/pdfs/`, which isn't committed.
    """
    )
    return


@app.cell
def _(BENCH, OUT, PAGES, hashlib, pdfium, time, urllib):
    def download(doc: str, sha256: str) -> bytes:
        cached = OUT / "docs" / f"{doc}.pdf"
        if cached.exists() and hashlib.sha256(cached.read_bytes()).hexdigest() == sha256:
            return cached.read_bytes()
        fema = not doc.isdigit()
        url = (
            f"https://msc.fema.gov/portal/downloadProduct?productID={doc}"
            if fema
            else f"https://www.osti.gov/servlets/purl/{doc}"
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=300) as response:
                    data = response.read()
                break
            except OSError as e:
                if attempt == 2:
                    raise RuntimeError(f"couldn't download {url}: {e}") from e
                time.sleep(5 * (attempt + 1))
        if hashlib.sha256(data).hexdigest() != sha256:
            raise RuntimeError(f"{url} has changed since the key was made")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
        return data

    (BENCH / "pdfs").mkdir(parents=True, exist_ok=True)
    PDF_NAME = {}  # doc -> the one-page PDF's name inside bench/pdfs
    for _doc, (_group, _page, _sha) in PAGES.items():
        PDF_NAME[_doc] = f"{_doc}_p{_page}.pdf"
        _target = BENCH / "pdfs" / PDF_NAME[_doc]
        if not _target.exists():
            _source = pdfium.PdfDocument(download(_doc, _sha))
            _single = pdfium.PdfDocument.new()
            _single.import_pages(_source, [_page - 1])
            _single.save(_target)
    print(f"{len(PDF_NAME)} one-page PDFs in {BENCH / 'pdfs'}")
    return (PDF_NAME,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## From answer keys to unit tests

    olmOCR-Bench tests are pass/fail facts about a page's text output (format confirmed in `olmocr/bench/tests.py`
    and `README.md` at olmocr 0.4.27). We use three of its test types:

    - **FIS rows become `table` tests.** For every keyed number we test that a table cell holds it *and* that the cell
      to its left holds the row's previous value (the cell to its right for the first discharge when the drainage
      area is blank). The drainage area must sit to the right of its location text. So a pipeline passes only if it
      keeps each number in its row, which is what someone building a dataset from these tables needs. Tables may be
      Markdown or HTML, as olmOCR allows. Each flooding source name becomes a `present` test, ignoring case.
    - **NRC numbers become `present` tests.** The NRC key is a bag of numbers per page with no positions, so the
      most a test can honestly claim is "this number is printed on the page". Numbers of one or two characters
      ("1", "04") would pass on almost any output, so we keep the distinct numbers of three or more characters.
    - **Page numbers become `absent` tests**, olmOCR's header and footer check: the printed page number must not be
      among the first (header) or last (footer) few characters of the output. The page labels were read off the
      page images by the AI worker, like the keys.
    """
    )
    return


@app.cell
def _(Counter, SOURCE, json):
    FIS_KEY = {k: v for k, v in json.loads((SOURCE / "fis_key.json").read_text()).items() if not k.startswith("_")}
    NRC_KEY = {k: v for k, v in json.loads((SOURCE / "nrc_key.json").read_text()).items() if not k.startswith("_")}
    # The printed page number on each keyed page, and whether it is a header (top) or footer (bottom).
    # 5507271 page 114 prints none.
    PAGE_LABELS = {
        "45061CV000A": ("6", "bottom"),
        "35053CV000A": ("7", "bottom"),
        "39151CV001C": ("43", "bottom"),
        "35049CV000A": ("8", "bottom"),
        "510218V000": ("5", "bottom"),
        "060724V000": ("7", "bottom"),
        "51005CV000A": ("12", "bottom"),
        "080290V000": ("11", "bottom"),
        "1083948": ("xix", "bottom"),
        "10125120": ("8.324", "bottom"),
        "5777799": ("54", "top"),
        "1083928": ("A.6", "bottom"),
        "5063304": ("37", "top"),
        "5533698": ("58", "bottom"),
        "6623512": ("35", "bottom"),
        "5239714": ("-8-", "bottom"),
        "6613275": ("193", "bottom"),
    }
    _fis_numbers = sum(1 for v in FIS_KEY.values() for r in v["rows"] for c in r[2:] if c not in ("", "*"))
    print(
        f"Source keys: {_fis_numbers} FIS numbers, "
        f"{sum(len(v['numbers']) for v in NRC_KEY.values())} NRC numbers "
        f"({sum(len(Counter(v['numbers'])) for v in NRC_KEY.values())} distinct per page)"
    )
    return FIS_KEY, NRC_KEY, PAGE_LABELS


@app.cell
def _(BENCH, FIS_KEY, NRC_KEY, PAGES, PAGE_LABELS, PDF_NAME, json, re):
    BLANK = {"", "*"}
    _tests = []

    def add(doc: str, **fields: object) -> None:
        _tests.append(
            {"pdf": PDF_NAME[doc], "page": 1, "id": f"{doc}_{len(_tests):04d}", "group": PAGES[doc][0], **fields}
        )

    for _doc, _entry in FIS_KEY.items():
        for _source in sorted({row[0] for row in _entry["rows"] if row[0]}):
            add(_doc, type="present", text=_source, case_sensitive=False)
        # Key columns that sit side by side on the printed page. 39151CV001C prints two more discharge columns
        # (4% and "1% plus") that the source key left out, so there only two key pairs are neighbours.
        _pairs = {(0, 1), (2, 3)} if _doc == "39151CV001C" else {(0, 1), (1, 2), (2, 3), (3, 4)}
        for _source, _location, *_numbers in _entry["rows"]:
            # Area beside its location. The area must match exactly; the location only loosely (olmOCR's floor of
            # 50% similarity), so indents such as "&nbsp;" and footnote marks don't fail a correct row.
            if _numbers[0] not in BLANK and len(_location) > 3:
                add(_doc, type="table", cell=_numbers[0], left=_location, max_diffs=len(_location))
            for _i, _value in enumerate(_numbers[1:], start=1):
                if _value in BLANK:
                    continue
                if (_i - 1, _i) in _pairs and _numbers[_i - 1] not in BLANK:
                    add(_doc, type="table", cell=_value, left=_numbers[_i - 1])
                elif (_i, _i + 1) in _pairs and _numbers[_i + 1] not in BLANK:
                    add(_doc, type="table", cell=_value, right=_numbers[_i + 1])

    for _doc, _entry in NRC_KEY.items():
        _label = PAGE_LABELS.get(_doc, ("", ""))[0]
        _numbers = set()
        for _number in _entry["numbers"]:
            # The key's number pattern joins "December 12,1974" into "12,1974"; a comma counts only as a
            # thousands separator.
            if "," in _number and not re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", _number):
                _numbers.update(_number.split(","))
            else:
                _numbers.add(_number)
        for _number in sorted(_numbers, key=lambda n: (len(n), n)):
            if len(_number) >= 3 and _number != _label:
                add(_doc, type="present", text=_number)

    for _doc, (_label, _where) in PAGE_LABELS.items():
        _window = {"first_n" if _where == "top" else "last_n": len(_label) + 4}
        add(_doc, type="absent", text=_label, **_window, group="headers_footers")

    # A person's verdicts, once the review is done (see the end of this notebook), go into olmOCR's "checked" field.
    _decisions_file = BENCH / "review_decisions.json"
    DECISIONS = json.loads(_decisions_file.read_text()) if _decisions_file.exists() else {}
    for _t in _tests:
        if _t["id"] in DECISIONS:
            _t["checked"] = DECISIONS[_t["id"]]["verdict"]

    TESTS = _tests
    for _group in sorted({t["group"] for t in TESTS}):
        with open(BENCH / f"{_group}.jsonl", "w") as _f:
            for _t in TESTS:
                if _t["group"] == _group:
                    _f.write(json.dumps({k: v for k, v in _t.items() if k != "group"}) + "\n")
    return DECISIONS, TESTS


@app.cell
def _(TESTS, mo, pd):
    test_counts = pd.crosstab(
        pd.Series([t["group"] for t in TESTS], name="group"),
        pd.Series([t["type"] for t in TESTS], name="type"),
        margins=True,
        margins_name="total",
    )
    print(test_counts.to_string())
    mo.md(f"**{len(TESTS)} tests** written to `bench/*.jsonl`:\n\n{test_counts.to_markdown()}")
    return (test_counts,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Six pipelines

    Each pipeline writes one Markdown file per page into `bench/<pipeline>/<pdf>_pg1_repeat1.md`, the layout
    `olmocr.bench.benchmark` reads. Outputs are committed, so a rerun rescores without paying; delete a file to run
    that page again.

    1. **text_layer**: the text the PDF itself carries (pypdfium2). Scans carry none, or an old OCR layer.
    2. **tesseract**: Tesseract 5 at 300 dpi, default settings.
    3. **tesseract_haiku**: Tesseract's text handed to Claude Haiku 5.5 to tidy into Markdown with tables.
    4. **image_haiku** and 5. **image_gemini**: the page image (150 dpi) to Claude Haiku 5.5 and Gemini 3.8 Flash.
    6. **image_qwen3vl8b**: the page image to Qwen3-VL-8B-Instruct, an open-weights model, as the open OCR model.
       The dedicated open OCR models in olmOCR's table (olmOCR 2, Chandra, PaddleOCR-VL) need a GPU, and none is on
       OpenRouter.

    Every model gets olmOCR-Bench's own prompt (`build_basic_prompt`), through OpenRouter, temperature 0.
    """
    )
    return


@app.cell
def _(BENCH, HERE, PDF_NAME, pdfium, pytesseract):
    def page_image(pdf: str, dpi: int):
        return pdfium.PdfDocument(BENCH / "pdfs" / pdf)[0].render(scale=dpi / 72).to_pil().convert("RGB")

    def md_path(pipeline: str, pdf: str):
        return BENCH / pipeline / f"{pdf.removesuffix('.pdf')}_pg1_repeat1.md"

    def call_log(pipeline: str, pdf: str):
        return HERE / "calls" / pipeline / f"{pdf.removesuffix('.pdf')}.json"

    for _pdf in PDF_NAME.values():
        _target = md_path("text_layer", _pdf)
        if not _target.exists():
            _target.parent.mkdir(parents=True, exist_ok=True)
            _target.write_text(pdfium.PdfDocument(BENCH / "pdfs" / _pdf)[0].get_textpage().get_text_bounded())
        _target = md_path("tesseract", _pdf)
        if not _target.exists():
            _target.parent.mkdir(parents=True, exist_ok=True)
            _target.write_text(pytesseract.image_to_string(page_image(_pdf, 300)))
    print(f"text_layer and tesseract outputs for {len(PDF_NAME)} pages in {BENCH}")
    return call_log, md_path, page_image


@app.cell
async def _(
    Agent,
    BinaryContent,
    ModelResponse,
    OpenRouterModelSettings,
    PDF_NAME,
    asyncio,
    build_basic_prompt,
    call_log,
    io,
    json,
    md_path,
    page_image,
    time,
):
    MODELS = {
        "haiku": "openrouter:anthropic/claude-haiku-5.5",
        "gemini": "openrouter:google/gemini-3.8-flash",
        "qwen3vl8b": "openrouter:qwen/qwen3-vl-8b-instruct",
    }
    RUNS = {  # pipeline: (model, input)
        "tesseract_haiku": ("haiku", "tesseract"),
        "image_haiku": ("haiku", "image"),
        "image_gemini": ("gemini", "image"),
        "image_qwen3vl8b": ("qwen3vl8b", "image"),
    }
    ATTEMPTS = 3
    _slots = asyncio.Semaphore(6)

    async def transcribe(pipeline: str, pdf: str) -> None:
        """One page through one model pipeline; the text goes to the .md file, cost and time to calls/."""
        model, source = RUNS[pipeline]
        if md_path(pipeline, pdf).exists():
            return
        if source == "image":
            _png = io.BytesIO()
            page_image(pdf, 150).save(_png, "PNG")
            parts = [build_basic_prompt(), BinaryContent(_png.getvalue(), media_type="image/png")]
        else:
            ocr = md_path("tesseract", pdf).read_text()
            parts = [f"Below is Tesseract OCR text of one page of a PDF.\n\n{ocr}\n\n{build_basic_prompt()}"]
        settings = OpenRouterModelSettings(
            temperature=0,
            max_tokens=12000,
            timeout=240,
            openrouter_usage={"include": True},
            **({"thinking": "low"} if model == "gemini" else {}),
        )
        agent = Agent(MODELS[model], output_type=str)
        log = {"usd": 0.0, "seconds": 0.0, "failed_attempts": 0, "error": ""}
        text = ""
        async with _slots:
            for attempt in range(ATTEMPTS):
                t0 = time.time()
                try:
                    result = await agent.run(parts, model_settings=settings)
                except Exception as e:  # network errors, refusals, rate limits: recorded as a result, not a crash
                    log["seconds"] += time.time() - t0
                    log["failed_attempts"] += 1
                    log["error"] = f"{type(e).__name__}: {e!s:.200}"
                    print(f"{pipeline}/{pdf}: attempt {attempt + 1} failed: {log['error']}")
                    await asyncio.sleep(10 * (attempt + 1))
                    continue
                log["seconds"] += time.time() - t0
                log["usd"] += sum(
                    float((m.provider_details or {}).get("cost") or 0)
                    for m in result.new_messages()
                    if isinstance(m, ModelResponse)
                )
                assert isinstance(result.output, str)
                text, log["error"] = result.output, ""
                break
        md_path(pipeline, pdf).parent.mkdir(parents=True, exist_ok=True)
        md_path(pipeline, pdf).write_text(text)  # an empty file is a failed page: it fails that page's tests
        call_log(pipeline, pdf).parent.mkdir(parents=True, exist_ok=True)
        call_log(pipeline, pdf).write_text(json.dumps(log, indent=1))

    await asyncio.gather(*(transcribe(_p, _pdf) for _p in RUNS for _pdf in PDF_NAME.values()))
    PIPELINES = ["text_layer", "tesseract", *RUNS]
    return (PIPELINES,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Scores

    Each test is run with olmOCR's own test classes (`olmocr.bench.tests.load_tests` and each test's `run`) against
    the pipeline's Markdown. A group's score is the share of its tests passed. `run.sh` also runs the official
    `python -m olmocr.bench.benchmark --dir bench` and saves its report to `results/olmocr_benchmark.txt`, which adds
    olmOCR's baseline checks (output not empty, not repeating) and bootstrap confidence intervals.
    """
    )
    return


@app.cell
def _(BENCH, PIPELINES, load_tests, md_path, pd):
    _rows = []
    for _jsonl in sorted(BENCH.glob("*.jsonl")):
        for _test in load_tests(str(_jsonl)):
            for _pipeline in PIPELINES:
                _passed, _why = _test.run(md_path(_pipeline, _test.pdf).read_text())
                _rows.append(
                    {
                        "group": _jsonl.stem,
                        "pipeline": _pipeline,
                        "id": _test.id,
                        "pdf": _test.pdf,
                        "type": _test.type,
                        "passed": _passed,
                        "why": _why,
                        "checked": _test.checked.value if _test.checked else "",
                    }
                )
    results = pd.DataFrame(_rows)
    scores = (results.pivot_table(index="pipeline", columns="group", values="passed", aggfunc="mean") * 100).round(1)
    scores = scores.reindex(PIPELINES)
    scores["all tests"] = (results.groupby("pipeline").passed.mean().reindex(PIPELINES) * 100).round(1)
    print(scores.to_string())
    return results, scores


@app.cell
def _(HERE, PIPELINES, json, pd, results):
    by_type = (results.pivot_table(index="pipeline", columns="type", values="passed", aggfunc="mean") * 100).round(1)
    by_type = by_type.reindex(PIPELINES)
    _calls = []
    for _log in sorted((HERE / "calls").glob("*/*.json")):
        _calls.append({"pipeline": _log.parent.name, **json.loads(_log.read_text())})
    calls = pd.DataFrame(_calls)
    spend = calls.groupby("pipeline").agg(
        usd=("usd", "sum"),
        seconds_per_page=("seconds", "mean"),
        failed_pages=("error", lambda e: int((e != "").sum())),
    )
    print(by_type.to_string())
    print(spend.round(4).to_string())
    print(f"Model spend in all: ${calls.usd.sum():.2f}")
    return by_type, calls, spend


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Where pipelines fail

    The tests each pipeline failed, by page, show whether a group is hard because of the scan or because of one
    page. A page where a model returned nothing shows up as a page whose every test failed.
    """
    )
    return


@app.cell
def _(results):
    by_page = (results.pivot_table(index="pdf", columns="pipeline", values="passed", aggfunc="mean") * 100).round(0)
    print(by_page.to_string())
    return (by_page,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## The person check

    The keys, the page labels and so the tests were made by an AI worker. Before publishing, a person should check
    every test against the page. The review file `output/review.html` shows, for each test, what it expects and a
    crop of the page around where Tesseract found that value (the whole page when it found nothing, for example on the
    sideways table). The reviewer marks each test *right* or *wrong* and downloads the verdicts as
    `review_decisions.json`; saved into `bench/`, this notebook writes them into olmOCR's `checked` field
    (`verified` or `rejected`) and counts the tests the check overturned. olmOCR's own review app
    (`uv run python -m olmocr.bench.review_app bench/fis_scanned.jsonl`) does the same on the whole page, without crops.
    """
    )
    return


@app.cell
def _(OUT, PDF_NAME, TESTS, base64, io, page_image, pytesseract, re):
    from PIL import ImageDraw

    def crop_for(words: dict, image, test: dict):
        """A band of the page around where Tesseract read the test's value, with the value boxed; None if not found.

        Looks for the value's words in a row; for a table test, preferably where the neighbour is the word before (or
        after) it. The last match is used for a footer, the first otherwise.
        """

        def clean(text: str) -> list[str]:
            return [re.sub(r"[^\w.,-]", "", w) for w in text.lower().split()]

        tokens = [(clean(w) or [""])[0] for w in words["text"]]
        target = clean(str(test.get("text") or test.get("cell")))
        before = clean(str(test.get("left") or ""))[-1:]
        after = clean(str(test.get("right") or ""))[:1]
        hits, loose = [], []
        for i in range(len(tokens) - len(target) + 1):
            window = tokens[i : i + len(target)]
            # A lone number may sit inside a longer token, as "1983" in "1983." or "10-22".
            single = len(target) == 1 and test["type"] == "present" and target[0] in window[0]
            if not target or (window != target and not single):
                continue
            loose.append(range(i, i + len(target)))
            if before and (i == 0 or tokens[i - 1] != before[0]):
                continue
            if after and tokens[i + len(target) : i + len(target) + 1] != after:
                continue
            hits.append(range(i, i + len(target)))
        hits = hits or loose  # without the neighbour when Tesseract misread it
        if not hits:
            return None
        hit = hits[-1] if test.get("last_n") else hits[0]
        left = min(words["left"][j] for j in hit)
        right = max(words["left"][j] + words["width"][j] for j in hit)
        top = min(words["top"][j] for j in hit)
        bottom = max(words["top"][j] + words["height"][j] for j in hit)
        band = image.copy()
        ImageDraw.Draw(band).rectangle((left - 6, top - 6, right + 6, bottom + 6), outline="black", width=4)
        return band.crop((0, max(0, top - 110), image.width, min(image.height, bottom + 110)))

    def jpeg(image, width: int) -> str:
        scaled = image.resize((width, max(1, int(image.height * width / image.width)))).convert("L")
        buffer = io.BytesIO()
        scaled.save(buffer, "JPEG", quality=60)
        return base64.b64encode(buffer.getvalue()).decode()

    _cards = []
    _cropped = 0
    for _doc, _pdf in PDF_NAME.items():
        _image = page_image(_pdf, 200)
        # Turn sideways tables upright so the crops read naturally: keep the turn Tesseract reads most confidently.
        _best = -1.0
        for _turn in (0, 90, 270):
            _turned = _image.rotate(-_turn, expand=True)
            _data = pytesseract.image_to_data(_turned, output_type=pytesseract.Output.DICT)
            _conf = [float(c) for c in _data["conf"] if float(c) >= 0]
            _mean = sum(_conf) / len(_conf) if _conf else 0.0
            if _mean > _best + (10 if _turn else 0):  # turn only when clearly better than upright
                _best, _words, _upright = _mean, _data, _turned
        _image = _upright
        _cards.append(
            f'<details class="my-4"><summary class="font-bold cursor-pointer">{_pdf}: whole page</summary>'
            f'<img class="border" src="data:image/jpeg;base64,{jpeg(_image, 900)}"></details>'
        )
        for _t in (t for t in TESTS if t["pdf"] == _pdf):
            _expect = {
                "present": f"printed on the page: <b>{_t.get('text')}</b>",
                "absent": f"page number <b>{_t.get('text')}</b> (should be left out of the output)",
                "table": f"cell <b>{_t.get('cell')}</b> with <b>{_t.get('left') or _t.get('right')}</b> to its "
                f"{'left' if _t.get('left') else 'right'}",
            }[_t["type"]]
            _crop = crop_for(_words, _image, _t)
            _cropped += _crop is not None
            _img = (
                f'<img class="border" src="data:image/jpeg;base64,{jpeg(_crop, 900)}">'
                if _crop
                else '<p class="text-amber-700">Not found by Tesseract: check on the whole page above.</p>'
            )
            _cards.append(
                f'<div class="border rounded p-3 my-2" data-id="{_t["id"]}"><p class="text-sm text-gray-500">'
                f"{_t['id']} · {_t['type']} · {_t['group']}</p><p>{_expect}</p>{_img}"
                f'<label class="mr-4"><input type="radio" name="{_t["id"]}" value="verified"> right</label>'
                f'<label class="mr-4"><input type="radio" name="{_t["id"]}" value="rejected"> wrong</label>'
                f'<input class="border px-1 w-1/2" placeholder="note (optional)" name="{_t["id"]}-note"></div>'
            )
    _html = f"""<!doctype html><html><head><meta charset="utf-8"><title>OCR bench review</title>
    <script src="https://cdn.tailwindcss.com/3.4.17"></script></head>
    <body class="max-w-4xl mx-auto p-4 font-sans">
    <h1 class="text-2xl font-bold">Public-records OCR bench: person check</h1>
    <p>For each test, look at the crop (or the whole page) and mark whether the test is right. Choices are kept in
    this browser. When done, press the button and save the file as <code>bench/review_decisions.json</code>.</p>
    <button class="bg-black text-white px-3 py-1 rounded my-2" onclick="save()">Download review_decisions.json</button>
    <p id="count"></p>{"".join(_cards)}
    <script>
    const KEY = "ocr-bench-review";
    let state = {{}};
    try {{ state = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{}}
    function count() {{ document.getElementById("count").textContent =
      Object.keys(state).length + " of {len(TESTS)} tests checked"; }}
    document.querySelectorAll("[data-id]").forEach(card => {{
      const id = card.dataset.id, note = card.querySelector("input[type=text], input:not([type])");
      if (state[id]) {{
        card.querySelector(`input[value=${{state[id].verdict}}]`).checked = true;
        note.value = state[id].note || "";
      }}
      card.addEventListener("change", () => {{
        const pick = card.querySelector("input[type=radio]:checked");
        if (pick) state[id] = {{verdict: pick.value, note: note.value}};
        try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch (e) {{}}
        count();
      }});
    }});
    count();
    function save() {{
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(state, null, 1)], {{type: "application/json"}}));
      a.download = "review_decisions.json"; a.click();
    }}
    </script></body></html>"""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "review.html").write_text(_html)
    print(f"Review file: {OUT / 'review.html'} ({len(_html) / 1e6:.1f} MB, {len(TESTS)} tests, {_cropped} with a crop)")
    return


@app.cell
def _(DECISIONS, TESTS):
    overturned = [d for d in DECISIONS.values() if d["verdict"] == "rejected"]
    person_check = (
        f"{len(DECISIONS)} of {len(TESTS)} tests checked by a person; {len(overturned)} overturned"
        if DECISIONS
        else "not yet checked"
    )
    print("Person check:", person_check)
    return (person_check,)


@app.cell
def _(HERE, by_page, by_type, person_check, scores, spend, test_counts):
    _report = HERE / "results" / "scores.md"
    _report.parent.mkdir(exist_ok=True)
    _report.write_text(
        "# Public-records OCR bench: scores\n\nWritten by `bench.py`.\n\n## Tests\n\n"
        + test_counts.to_markdown()
        + "\n\n## Share of tests passed, by group (%)\n\n"
        + scores.to_markdown()
        + "\n\n## By test type (%)\n\n"
        + by_type.to_markdown()
        + "\n\n## By page (%)\n\n"
        + by_page.to_markdown()
        + "\n\n## Model calls\n\n"
        + spend.round(4).to_markdown()
        + f"\n\nPerson check: {person_check}.\n"
    )
    print(f"wrote {_report}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## What didn't work, and what this doesn't show

    - **18 pages.** olmOCR-Bench has 1,403 PDFs and KDoc-OCRBench-V2 849. This is a seed set, not a benchmark yet.
    - **The key and the page disagreed once.** 39151CV001C prints six discharge columns; the source key holds four,
      so our first neighbour tests there were wrong and every model "failed" 43% of that page. The tests now pair
      only columns that are side by side on the page. A person check would catch more errors of this kind.
    - **The NRC key's number pattern** joins "December 12,1974" into "12,1974"; such numbers are split at the comma.
    - **NRC tests check numbers only.** The NRC key has no positions, so a number found in the wrong table cell still
      passes, and a three-character number can pass inside a longer one ("185" inside "1850"). Three of 5063304's
      tests are axis labels on a chart, which every vision model left out.
    - **The text layer and Tesseract fail table tests by design**: olmOCR's table tests need a Markdown or HTML
      table, and plain text has none, even when every number is there in order.
    - **Each pipeline ran once.** Model outputs vary from run to run; olmOCR supports repeats, which we didn't use.
    - **The tests are AI-made until a person checks them.**
    """
    )
    return


if __name__ == "__main__":
    app.run()
