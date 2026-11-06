import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import io
    import itertools
    import json
    import os
    import re
    import time
    import urllib.request
    import xml.etree.ElementTree as ElementTree
    from decimal import Decimal, InvalidOperation
    from pathlib import Path
    from typing import Any

    import lxml.html
    import marimo as mo
    import pypdfium2 as pdfium
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from playwright.async_api import async_playwright
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent, BinaryContent
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models.openrouter import OpenRouterModelSettings
    from rapidfuzz import fuzz
    from reducto import Reducto

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("SEC_OUTPUT_DIR", HERE / "output"))
    RESULTS = HERE / "results"
    # SEC's fair-access rules: say who you are, and stay under 10 requests a second.
    SEC_HEADERS = {"User-Agent": os.environ.get("SEC_USER_AGENT") or "Fulton Ring info@fultonring.com"}
    STATEMENTS = ("balance", "income", "cash flow")


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Reducto against open pipelines on SEC 10-K and 10-Q financial statements

    **The question.** Reducto sells itself on complex financial tables and SEC filings. In #136 it made as many
    believable wrong values as Gemini on old federal records, but those weren't its home turf. Here every document
    is: the balance sheet, income statement and cash-flow statement from public companies' 10-Ks and 10-Qs. Does
    Reducto read them better than Gemini reading page images, and is it worth what it costs?

    **The answer key comes from the filers themselves.** Every filing since 2009–2011 carries XBRL, a
    machine-readable copy of its statements filed alongside the printed one. Nothing is typed by hand.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. The filings, fixed before any pipeline ran

    The list below names 30 filers across tech, banks, insurers, a utility, retail, energy, pharma, REITs,
    industrials and airlines, plus two small caps. It mixes 10-Ks and 10-Qs filed from 2011 to 2025. For each, the
    filing is the first of that form filed in that calendar year. The list and its order were written down before
    anything ran. A filing that can't be used is replaced by the next reserve: one whose XBRL viewer pages are
    missing, or whose statements can't be found in the printed text (section 3).

    The spike uses the first 24 usable filings in list order, not 30. Two runs of Reducto Extract on 30 filings
    and of Deep Extract on every third one would cost $6.72 at list price, over the $6 Reducto budget. The first 24
    cost $5.36. The Deep Extract and Gemini 4 Argon subset is every third of the 24 (8 filings), also fixed in
    advance. Set `SEC_FILINGS` to change the number.
    """)
    return


@app.cell
def _():
    CANDIDATES = [  # (CIK, form, calendar year filed, short name)
        (320193, "10-K", 2012, "Apple"),
        (789019, "10-Q", 2019, "Microsoft"),
        (35527, "10-K", 2016, "Fifth Third"),
        (86312, "10-K", 2015, "Travelers"),
        (1410636, "10-K", 2013, "American Water"),
        (104169, "10-Q", 2017, "Walmart"),
        (93410, "10-Q", 2018, "Chevron"),
        (310158, "10-K", 2019, "Merck"),
        (1063761, "10-K", 2017, "Simon Property"),
        (18230, "10-Q", 2012, "Caterpillar"),
        (21344, "10-K", 2018, "Coca-Cola"),
        (1166691, "10-Q", 2020, "Comcast"),
        (16160, "10-Q", 2013, "Cal-Maine Foods"),
        (19617, "10-Q", 2014, "JPMorgan Chase"),
        (731766, "10-Q", 2022, "UnitedHealth"),
        (50863, "10-K", 2016, "Intel"),
        (4977, "10-Q", 2021, "Aflac"),
        (909832, "10-K", 2020, "Costco"),
        (1163165, "10-K", 2022, "ConocoPhillips"),
        (200406, "10-Q", 2023, "Johnson & Johnson"),
        (726728, "10-Q", 2024, "Realty Income"),
        (315189, "10-K", 2021, "Deere"),
        (320187, "10-Q", 2016, "Nike"),
        (1065280, "10-K", 2015, "Netflix"),
        (95029, "10-K", 2014, "Sturm Ruger"),
        (27904, "10-K", 2023, "Delta Air Lines"),
        (12927, "10-Q", 2025, "Boeing"),
        (63908, "10-K", 2024, "McDonald's"),
        (59478, "10-K", 2011, "Eli Lilly"),
        (1048911, "10-Q", 2019, "FedEx"),
        # reserves, used in this order only if a filing above can't be used
        (66740, "10-K", 2013, "3M"),
        (27419, "10-K", 2014, "Target"),
        (907242, "10-K", 2012, "Monarch Casino"),
    ]
    WANTED = int(os.environ.get("SEC_FILINGS", "24"))  # 24 is what fits $6 of Reducto at two runs; see the README
    return CANDIDATES, WANTED


@app.function
def sec_get(url: str, attempts: int = 4) -> bytes:
    """One request to sec.gov, cached on disk. At most about 7 a second, with a declared User-Agent."""
    cached = OUT / "sec" / re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://")[1])
    if cached.exists():
        return cached.read_bytes()
    for attempt in range(attempts):
        time.sleep(0.15)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=SEC_HEADERS), timeout=60) as response:
                data = response.read()
            break
        except OSError as e:
            if attempt == attempts - 1:
                raise
            print(f"{url}: {e}; retrying")
            time.sleep(5 * (attempt + 1))
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


@app.function
def numbers_in(text: str) -> list[str]:
    """Every number in a stretch of text, as its absolute value without commas: '$ (1,234.50)' gives '1234.5'."""
    found = []
    for token in re.findall(r"\d[\d,]*(?:\.\d+)?|\.\d+", text):
        try:
            found.append(format(Decimal(token.replace(",", "")).normalize(), "f"))
        except InvalidOperation:
            continue
    return found


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. The key: each statement as the filer's XBRL gives it

    EDGAR renders every filing's XBRL into one page per statement: the `R` pages behind its "Financial Report"
    viewer. `FilingSummary.xml` says which page is which statement. Each `R` page gives the statement's line items,
    its period columns and every value. We keep the balance sheet, the income statement (which some filers call
    operations or earnings) and the cash-flow statement. We leave out the parenthetical, comprehensive-income and
    equity statements. Within the three, ratio lines (XBRL elements named `...Percent...`) are left out, and so are
    the comprehensive-income lines that some filers print at the foot of their income statement; the prompt tells
    every pipeline to skip those. A combined filing for a parent and its operating partnership (Simon Property)
    repeats each line in one `R` page; repeated lines count once.
    """)
    return


@app.function
def statement_type(name: str) -> str:
    """'balance', 'income', 'cash flow', or '' for a statement we don't score."""
    name = name.lower()
    if re.search(r"parenthetical|equity|shareholders|stockholders", name):
        return ""
    if "cash flow" in name:
        return "cash flow"
    if re.search(r"balance sheet|financial position|financial condition", name):
        return "balance"
    comprehensive_only = "comprehensive" in name and not re.search(
        r"(income|operations|earnings) and (other )?comprehensive", name
    )
    if re.search(r"income|operations|earnings", name) and not comprehensive_only:
        return "income"
    return ""


@app.function
def read_r_page(html: bytes) -> list[tuple[str, list[str], str]]:
    """An R page's line items: (label, the value in each period column or '', the XBRL element's name)."""
    table = lxml.html.fromstring(html).xpath("//table")[0]
    rows = []
    for tr in table.xpath(".//tr[td[contains(@class, 'pl')]]"):
        label_cell = tr.xpath("./td[contains(@class, 'pl')]")[0]
        label = " ".join(label_cell.text_content().split())
        element = re.search(r"defref_([\w-]+)", lxml.html.tostring(label_cell).decode())
        cells = tr.xpath("./td[contains(@class, 'num') or @class='text']")
        values = [" ".join(td.text_content().split()) for td in cells]
        if any(re.search(r"\d", v) for v in values):
            rows.append((label, values, element.group(1) if element else ""))
    return rows


@app.cell
def _(CANDIDATES):
    def find_filing(cik: int, form: str, year: int) -> dict[str, Any]:
        """The first `form` the filer filed in `year`, from its EDGAR submissions history."""
        history = json.loads(sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
        pages = [history["filings"]["recent"]] + [
            json.loads(sec_get(f"https://data.sec.gov/submissions/{f['name']}")) for f in history["filings"]["files"]
        ]
        found = [
            {key: page[key][i] for key in ("filingDate", "accessionNumber", "primaryDocument", "reportDate")}
            for page in pages
            for i in range(len(page["form"]))
            if page["form"][i] == form and page["filingDate"][i].startswith(str(year))
        ]
        assert found, f"CIK {cik} filed no {form} in {year}"
        return min(found, key=lambda f: f["filingDate"])

    FILINGS = []
    for _cik, _form, _year, _name in CANDIDATES:
        _filing = find_filing(_cik, _form, _year)
        _base = f"https://www.sec.gov/Archives/edgar/data/{_cik}/{_filing['accessionNumber'].replace('-', '')}/"
        _keys: dict[str, list[tuple[str, list[str]]]] = {}
        _xbrl_numbers: set[str] = set()  # every number on any statement R page, to check printed numbers against
        for _report in ElementTree.fromstring(sec_get(_base + "FilingSummary.xml")).iter("Report"):
            _long, _html = _report.findtext("LongName") or "", _report.findtext("HtmlFileName")
            if " - Statement - " not in _long or not _html:
                continue
            _rows = read_r_page(sec_get(_base + _html))
            _xbrl_numbers |= {n for _, values, _ in _rows for v in values for n in numbers_in(v)}
            _kind = statement_type(_report.findtext("ShortName") or _long)
            if _kind and _kind not in _keys:
                # Left out: ratios (J&J prints each line as a percent of sales) and, where a filer combines its
                # income statement with comprehensive income, the comprehensive-income lines the prompt excludes.
                _keys[_kind] = [
                    (label, values)
                    for label, values, element in _rows
                    if "Percent" not in element and not (_kind == "income" and "ComprehensiveIncome" in element)
                ]
        FILINGS.append(
            {
                "name": _name,
                "form": _form,
                "period": _filing["reportDate"],
                "slug": re.sub(r"[^a-z0-9]+", "-", f"{_name} {_form} {_filing['reportDate']}".lower()),
                "url": _base + _filing["primaryDocument"],
                "keys": _keys,
                "xbrl_numbers": _xbrl_numbers,
            }
        )
    return (FILINGS,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. The printed filing, and where its statements are

    Each filing's main HTML document is printed to PDF with headless Chromium, as a reader would print it: US
    Letter, with network requests blocked so nothing else is fetched from sec.gov. Then we find the statement pages
    from the key. Pages that print at least 80% as many of the statement's line items as the best page are
    candidates. A candidate whose first lines carry the statement's title wins, so a quarterly-data table in the
    notes or a summary in MD&A loses to the statement itself. Ties go to the page that prints the most values. The
    next or previous page is added when the statement runs over onto it. Only those pages go to the pipelines, as
    one small PDF per filing. So every pipeline reads, and is billed for, the same 3 or 4 pages.

    Matching the key to print works both ways, so nothing is dropped silently:
    - **XBRL values not printed.** A key value counts only if it's printed on the statement's pages, either as
      filed or divided by 1,000 or 1,000,000 (newer `R` pages show whole dollars where the page prints millions).
      Key columns with fewer than half their values printed are dropped; these are periods that `R` pages show and
      the statement doesn't, such as Costco's quarters. Single values that aren't printed are counted and left out.
      A zero counts even when it's printed as a dash.
    - **Printed values not in XBRL.** Every number on the statement pages, other than years, that matches no value
      on any of the filing's statement `R` pages.

    A filing is used only if each of its three statements has at least 80% of its line items found in print.
    Otherwise the next reserve takes its place.
    """)
    return


@app.cell
async def _(FILINGS):
    async def render(filing: dict[str, Any], browser: Any) -> Path:
        pdf = OUT / "printed" / f"{filing['slug']}.pdf"
        if not pdf.exists():
            page = await browser.new_page()
            await page.route("**/*", lambda route: route.abort())  # images and styles stay unfetched
            await page.set_content(sec_get(filing["url"]).decode("utf-8", "replace"), wait_until="load")
            pdf.parent.mkdir(parents=True, exist_ok=True)
            await page.pdf(path=pdf, format="Letter", print_background=True)
            await page.close()
        return pdf

    PRINTED: dict[str, Path] = {}
    async with async_playwright() as _p:
        _browser = await _p.chromium.launch()
        for _filing in FILINGS:
            if _filing["keys"]:
                PRINTED[_filing["slug"]] = await render(_filing, _browser)
        await _browser.close()
    return (PRINTED,)


@app.cell
def _(FILINGS, PRINTED, WANTED):
    TITLES = {
        "balance": r"balance sheets?|statements? of (consolidated )?(financial (position|condition)|condition)",
        "income": r"statements? of (consolidated )?(income|operations|earnings)|income statements?",
        "cash flow": r"statements? of (consolidated )?cash flows?|cash flows? statements?",
    }

    def printed_forms(value: str) -> list[str]:
        """The forms an R value can take in print: as filed, in thousands, in millions."""
        found = numbers_in(value)
        return [format((Decimal(found[0]) / s).normalize(), "f") for s in (1, 1000, 1000000)] if found else []

    def locate(rows: list[tuple[str, list[str]]], texts: list[str], numbers: list[set[str]], kind: str) -> list[int]:
        """The 0-based PDF pages a statement is printed on."""
        cells = [(r, c, printed_forms(v)) for r, (_, values) in enumerate(rows) for c, v in enumerate(values)]

        def cover(p: int) -> set[tuple[int, int]]:
            if p >= len(numbers):
                return set()
            return {(r, c) for r, c, forms in cells if any(f in numbers[p] for f in forms)}

        def line_items(p: int) -> int:  # with the next page, in case the statement runs over
            return len({r for r, _ in cover(p) | cover(p + 1)})

        def titled(p: int) -> bool:
            heads = [" ".join(texts[q][:400].lower().split()) for q in (p, p + 1) if q < len(texts)]
            return any(re.search(TITLES[kind], head) for head in heads)

        most = max(line_items(p) for p in range(len(texts)))
        candidates = [p for p in range(len(texts)) if line_items(p) >= 0.8 * most]
        best = max(candidates, key=lambda p: (titled(p), len(cover(p) | cover(p + 1))))
        if len(cover(best + 1) - cover(best)) > len(cover(best)):
            best += 1
        pages, covered = [best], cover(best)
        for p in (best + 1, best - 1):
            if 0 <= p < len(texts) and len(cover(p) - covered) >= max(3, 0.15 * len(cells)):
                pages, covered = [*pages, p], covered | cover(p)
        return sorted(pages)

    def key_on_print(
        rows: list[tuple[str, list[str]]], printed: set[str]
    ) -> tuple[list[tuple[str, list[str | None]]], int]:
        """The key as printed: each value in its printed form, None if it isn't printed. Plus how many were dropped."""
        forms = [[printed_forms(v) for v in values] for _, values in rows]
        width = max(len(f) for f in forms)

        def share_printed(c: int) -> float:
            filled = [f[c] for f in forms if c < len(f) and f[c]]
            return sum(any(x in printed for x in options) for options in filled) / max(len(filled), 1)

        keep = [c for c in range(width) if share_printed(c) >= 0.5]
        key, dropped = [], 0
        for (label, _), row in zip(rows, forms, strict=True):
            values: list[str | None] = []
            for c in keep:
                options = row[c] if c < len(row) else []
                match = "0" if options[:1] == ["0"] else next((x for x in options if x in printed), None)
                dropped += bool(options) and match is None
                values.append(match if options else None)
            if any(v is not None for v in values) and (label, values) not in key:  # a combined filing repeats rows
                key.append((label, values))
        return key, dropped

    def share_found(rows: list[tuple[str, list[str]]], printed: set[str]) -> float:
        """The share of a statement's line items with at least one value printed."""
        return sum(any(set(printed_forms(v)) & printed for v in values) for _, values in rows) / len(rows)

    CORPUS, SKIPPED = [], []
    for _filing in FILINGS:
        if len(CORPUS) == WANTED:
            break
        if set(_filing["keys"]) != set(STATEMENTS):
            SKIPPED.append(f"{_filing['name']} (its filing has no viewer pages for all three statements)")
            continue
        _doc = pdfium.PdfDocument(PRINTED[_filing["slug"]])
        _texts = [_doc[i].get_textpage().get_text_range() for i in range(len(_doc))]
        _numbers = [set(numbers_in(t)) for t in _texts]
        _where = {k: locate(_filing["keys"][k], _texts, _numbers, k) for k in STATEMENTS}
        _printed = {k: set().union(*(_numbers[p] for p in _where[k])) for k in STATEMENTS}
        _worst = min(share_found(_filing["keys"][k], _printed[k]) for k in STATEMENTS)
        if _worst < 0.8:
            SKIPPED.append(f"{_filing['name']} (only {_worst:.0%} of a statement's line items found in its text layer)")
            continue
        _pages = sorted({p for ps in _where.values() for p in ps})
        _pdf = pdfium.PdfDocument.new()
        _pdf.import_pages(_doc, _pages)
        _out = OUT / "statements" / f"{_filing['slug']}.pdf"
        _out.parent.mkdir(parents=True, exist_ok=True)
        _pdf.save(_out)
        _entry: dict[str, Any] = {k: _filing[k] for k in ("name", "form", "period", "slug", "url")}
        _entry |= {"pdf": _out, "pages": len(_pages), "statements": {}, "not_printed": 0}
        for _kind in STATEMENTS:
            _key, _dropped = key_on_print(_filing["keys"][_kind], _printed[_kind])
            _entry["statements"][_kind] = {"key": _key, "pages": [_pages.index(p) + 1 for p in _where[_kind]]}
            _entry["not_printed"] += _dropped
        _on_pages = [n for p in _pages for n in numbers_in(_texts[p]) if not re.fullmatch(r"(19|20)\d\d", n)]
        _entry["printed_numbers"] = len(_on_pages)
        _entry["printed_not_in_xbrl"] = sum(n not in _filing["xbrl_numbers"] for n in _on_pages)
        CORPUS.append(_entry)
    SUBSET = [f["slug"] for f in CORPUS[::3]]
    return CORPUS, SKIPPED, SUBSET


@app.cell(hide_code=True)
def _(CORPUS, SKIPPED, SUBSET):
    def key_values(filing: dict[str, Any]) -> int:
        return sum(v is not None for s in filing["statements"].values() for _, vs in s["key"] for v in vs)

    _values = sum(key_values(f) for f in CORPUS)
    _not_printed = sum(f["not_printed"] for f in CORPUS)
    _printed = sum(f["printed_numbers"] for f in CORPUS)
    _not_xbrl = sum(f["printed_not_in_xbrl"] for f in CORPUS)
    _rows = "\n".join(
        f"| {f['name']} | {f['form']} | {f['period']} | {f['pages']} | {key_values(f)} | {f['not_printed']} | "
        f"{f['printed_not_in_xbrl']} of {f['printed_numbers']} | {'yes' if f['slug'] in SUBSET else ''} |"
        for f in CORPUS
    )
    CORPUS_TABLE = (
        f"**{len(CORPUS)} filings, {sum(f['pages'] for f in CORPUS)} statement pages, {_values:,} key values.** "
        f"{_not_printed} XBRL values ({_not_printed / (_values + _not_printed):.1%}) weren't printed on the "
        f"statement pages and are left out. {_not_xbrl} of the {_printed:,} numbers printed on those pages "
        f"({_not_xbrl / _printed:.1%}) match no value on the filing's statement `R` pages.\n\n"
        + ("Replaced by reserves: " + "; ".join(SKIPPED) + ".\n\n" if SKIPPED else "")
        + "| Filer | Form | Period | Pages | Key values | XBRL not printed | Printed not in XBRL | Subset |\n"
        "|---|---|---|---|---|---|---|---|\n" + _rows
    )
    mo.md(CORPUS_TABLE)
    return (CORPUS_TABLE,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. The pipelines

    The pipelines are the four from #136 that can read a statement, copied from `messy-document-parsing/pipelines.py`
    and given one schema and one prompt:

    - **Gemini, whole PDF:** Gemini 3.8 Flash reads the statement PDF in one call.
    - **Gemini, page by page:** one call per page image (150 dpi). The rows are joined in page order.
    - **Docling, then Gemini:** Docling's Markdown of each page goes next to the page image. These PDFs are
      born-digital, so Docling reads their text layer and needs no OCR.
    - **Reducto Extract:** Reducto's schema extraction, with the same schema and prompt as Gemini.

    On the subset, two stronger readers:
    - **Reducto Deep Extract:** the same call with `deep_extract: True`, Reducto's agentic mode. It's billed at $40
      per 1,000 pages.
    - **Gemini 4 Argon, whole PDF.**

    Each runs twice. Answers are saved under `output/answers/run-1/` and `run-2/`, so re-running the notebook
    rescores without paying again. Reducto Parse isn't run; the budget went to Deep Extract.
    """)
    return


@app.cell
def _():
    class Row(BaseModel):
        label: str = Field(description="The line item's label, as printed.")
        values: list[str] = Field(
            description="The line's amounts, one per period column, left to right, exactly as printed "
            "(keep parentheses and minus signs). '' for a column with nothing printed."
        )

    class Statement(BaseModel):
        rows: list[Row] = Field(description="Every line item that has an amount, in order, including totals.")

    class Statements(BaseModel):
        """The company's three primary financial statements."""

        balance_sheet: Statement = Field(description="Balance sheet, or statement of financial position.")
        income_statement: Statement = Field(description="Income statement, or statement of operations or earnings.")
        cash_flow_statement: Statement = Field(description="Statement of cash flows.")

    FIELDS = {"balance": "balance_sheet", "income": "income_statement", "cash flow": "cash_flow_statement"}
    INSTRUCTIONS = "You read financial statements. Report only what is printed. Never compute or fill in a value."
    PROMPT = (
        "These pages are from a company's SEC filing. Read its balance sheet, its income statement (it may be called "
        "the statement of operations or of earnings) and its cash-flow statement. For each, give every line item "
        "that has an amount, in printed order, including subtotals and totals: its label and its amounts left to "
        "right as printed. Leave out other statements and tables, such as comprehensive income or equity. If one of "
        "the three statements isn't on these pages, give it no rows."
    )
    ONE_PAGE = " You are shown one page. Give only what is on this page."
    return FIELDS, INSTRUCTIONS, ONE_PAGE, PROMPT, Statements


@app.cell
def _(INSTRUCTIONS, PROMPT, Statements):
    FLASH, ARGON = "openrouter:google/gemini-3.8-flash", "openrouter:google/gemini-4-argon"
    # #136's settings: temperature 0, low thinking, room for 100-row answers.
    SETTINGS = OpenRouterModelSettings(
        temperature=0, max_tokens=16000, thinking="low", openrouter_usage={"include": True}
    )
    # Reducto's list prices from docs.reducto.ai/reference/credit-usage: Extract $20 and Deep Extract $40 per
    # 1,000 pages. The API reports pages, not dollars, so cost is pages times these.
    REDUCTO_USD_PER_PAGE = {"extract": 0.020, "deep": 0.040}
    ATTEMPTS = 3
    SLOTS = asyncio.Semaphore(8)

    async def ask(saved: Path, parts: list[Any], model: str) -> dict[str, Any]:
        """One typed model call through OpenRouter, saved to disk with its cost (OpenRouter's own figure) and time."""
        if saved.exists():
            return json.loads(saved.read_text())
        agent = Agent(model, output_type=Statements, instructions=INSTRUCTIONS, retries=2)
        answer: dict[str, Any] = {"output": None, "usd": 0.0, "seconds": 0.0, "error": ""}
        async with SLOTS:
            for attempt in range(ATTEMPTS):
                t0 = time.time()
                try:
                    result = await agent.run(parts, model_settings=SETTINGS)
                except Exception as e:  # rate limits, network errors, malformed output after Pydantic AI's retries
                    answer["seconds"] += time.time() - t0
                    answer["error"] = f"{type(e).__name__}: {e!s:.200}"
                    print(f"{saved}: attempt {attempt + 1} failed: {answer['error']}")
                    await asyncio.sleep(10 * (attempt + 1))
                    continue
                answer["seconds"] += time.time() - t0
                answer["usd"] += sum(
                    float((m.provider_details or {}).get("cost") or 0)
                    for m in result.new_messages()
                    if isinstance(m, ModelResponse)
                )
                assert isinstance(result.output, BaseModel), "the model answered with text, not the schema"
                answer |= {"output": result.output.model_dump(), "error": ""}
                break
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(answer, indent=1))
        return answer

    def reducto_call(pdf: Path, deep: bool) -> dict[str, Any]:
        client = Reducto()
        upload = client.upload(file=pdf)
        response = client.extract.run(
            input=upload.file_id,
            instructions={"schema": Statements.model_json_schema(), "system_prompt": f"{INSTRUCTIONS} {PROMPT}"},
            settings={"deep_extract": deep},
        )
        return response.model_dump(mode="json")

    async def reducto(saved: Path, pdf: Path, deep: bool) -> dict[str, Any]:
        """Reducto Extract or Deep Extract, saved like the model's answers, costed at list price."""
        if saved.exists():
            return json.loads(saved.read_text())
        answer: dict[str, Any] = {"output": None, "usd": 0.0, "seconds": 0.0, "error": ""}
        if not os.environ.get("REDUCTO_API_KEY"):
            return answer | {"error": "REDUCTO_API_KEY isn't set"}
        async with SLOTS:
            for attempt in range(ATTEMPTS):
                t0 = time.time()
                try:
                    response = await asyncio.to_thread(reducto_call, pdf, deep)
                except Exception as e:  # rate limits, server errors; reported after the last attempt
                    answer["seconds"] += time.time() - t0
                    answer["error"] = f"{type(e).__name__}: {e!s:.200}"
                    print(f"{saved}: attempt {attempt + 1} failed: {answer['error']}")
                    await asyncio.sleep(10 * (attempt + 1))
                    continue
                result = response["result"][0] if isinstance(response["result"], list) else response["result"]
                pages = response["usage"]["num_pages"]
                answer |= {
                    "output": Statements.model_validate(result).model_dump(),
                    "seconds": answer["seconds"] + time.time() - t0,
                    "usd": pages * REDUCTO_USD_PER_PAGE["deep" if deep else "extract"],
                    "pages_billed": pages,
                    "error": "",
                }
                break
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(answer, indent=1))
        return answer

    return ARGON, FLASH, ask, reducto


@app.cell
def _(FIELDS, ONE_PAGE, PROMPT, ask, reducto):
    def page_png(pdf: Path, page: int) -> BinaryContent:
        image = pdfium.PdfDocument(pdf)[page - 1].render(scale=150 / 72).to_pil().convert("RGB")
        out = io.BytesIO()
        image.save(out, "PNG")
        return BinaryContent(out.getvalue(), media_type="image/png")

    def docling_markdown(filing: dict[str, Any]) -> tuple[list[str], float]:
        """Docling's Markdown of each page, from the PDF's text layer (no OCR), table structure on. Saved."""
        saved = OUT / "docling" / f"{filing['slug']}.json"
        if not saved.exists():
            options = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
            converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
            t0 = time.time()
            document = converter.convert(filing["pdf"]).document
            pages = [document.export_to_markdown(page_no=p) for p in range(1, filing["pages"] + 1)]
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps({"pages": pages, "seconds": time.time() - t0}))
        stored = json.loads(saved.read_text())
        return stored["pages"], stored["seconds"]

    DOCLING_LOCK = asyncio.Lock()  # one Docling conversion at a time

    async def gemini_whole_pdf(filing: dict[str, Any], out: Path, model: str) -> dict[str, Any]:
        pdf = BinaryContent(filing["pdf"].read_bytes(), media_type="application/pdf")
        return await ask(out / f"{filing['slug']}.json", [PROMPT, pdf], model)

    async def gemini_page_by_page(filing: dict[str, Any], out: Path, model: str) -> dict[str, Any]:
        calls = [
            ask(out / f"{filing['slug']}-p{p}.json", [PROMPT + ONE_PAGE, page_png(filing["pdf"], p)], model)
            for p in range(1, filing["pages"] + 1)
        ]
        parts = await asyncio.gather(*calls)
        joined: dict[str, Any] = {field: {"rows": []} for field in FIELDS.values()}
        for part in parts:
            for field in FIELDS.values():
                joined[field]["rows"] += (part["output"] or {}).get(field, {}).get("rows", [])
        errors = "; ".join(p["error"] for p in parts if p["error"])
        return {
            "output": None if errors else joined,
            "usd": sum(p["usd"] for p in parts),
            "seconds": sum(p["seconds"] for p in parts),
            "error": errors,
        }

    async def docling_then_gemini(filing: dict[str, Any], out: Path, model: str) -> dict[str, Any]:
        async with DOCLING_LOCK:
            markdown, docling_seconds = await asyncio.to_thread(docling_markdown, filing)
        parts: list[Any] = [PROMPT]
        for p in range(1, filing["pages"] + 1):
            parts += [f"--- PDF page {p}, Docling's Markdown ---\n{markdown[p - 1]}", page_png(filing["pdf"], p)]
        answer = await ask(out / f"{filing['slug']}.json", parts, model)
        return answer | {"seconds": answer["seconds"] + docling_seconds}

    async def reducto_extract(filing: dict[str, Any], out: Path, model: str) -> dict[str, Any]:
        return await reducto(out / f"{filing['slug']}.json", filing["pdf"], deep=False)

    async def reducto_deep_extract(filing: dict[str, Any], out: Path, model: str) -> dict[str, Any]:
        return await reducto(out / f"{filing['slug']}.json", filing["pdf"], deep=True)

    return (
        docling_then_gemini,
        gemini_page_by_page,
        gemini_whole_pdf,
        reducto_deep_extract,
        reducto_extract,
    )


@app.cell
async def _(
    ARGON,
    CORPUS,
    FLASH,
    SUBSET,
    docling_then_gemini,
    gemini_page_by_page,
    gemini_whole_pdf,
    reducto_deep_extract,
    reducto_extract,
):
    PIPELINES = {  # name: (function, model, subset only)
        "Gemini, whole PDF": (gemini_whole_pdf, FLASH, False),
        "Gemini, page by page": (gemini_page_by_page, FLASH, False),
        "Docling, then Gemini": (docling_then_gemini, FLASH, False),
        "Reducto Extract": (reducto_extract, "", False),
        "Reducto Deep Extract": (reducto_deep_extract, "", True),
        "Gemini 4 Argon, whole PDF": (gemini_whole_pdf, ARGON, True),
    }
    OPEN = ["Gemini, whole PDF", "Gemini, page by page", "Docling, then Gemini"]

    async def run_one(run: int, name: str, filing: dict[str, Any]) -> tuple[tuple[int, str, str], dict[str, Any]]:
        function, model, _ = PIPELINES[name]
        out = OUT / "answers" / f"run-{run}" / re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return (run, name, filing["slug"]), await function(filing, out, model)

    _jobs = [
        run_one(_run, _name, _filing)
        for _run in (1, 2)
        for _name, (_, _, _subset_only) in PIPELINES.items()
        for _filing in CORPUS
        if not _subset_only or _filing["slug"] in SUBSET
    ]
    ANSWERS = dict(await asyncio.gather(*_jobs))
    return ANSWERS, OPEN, PIPELINES


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. Scoring

    We score each statement on its own. The extracted rows' columns are lined up with the key's periods by trying
    every assignment and keeping the one that agrees with the key most. Pipelines differ in whether they keep a
    `$` column or a note-reference column, and this stops a shifted column from being scored as every value wrong.
    Each key line item is then matched to the unused extracted row that agrees with it most: its values, plus its
    label if the label is close. Each key value is then:

    - **right:** the same number as printed. Signs are ignored, because XBRL and the printed page disagree on sign
      for lines like "Less: cost of sales". A dash or a blank counts as right for a zero;
    - **wrong:** a different number. This is the dangerous case, since it looks fine;
    - **missing:** blank, or its line item wasn't found.

    A **silent failure** is a statement that came back with no error but with fewer than 20% of its key values,
    such as a statement returned with no rows. An **error** is a call that failed every attempt; it's reported, and
    its values count as missing.
    """)
    return


@app.cell
def _(CORPUS, FIELDS):
    def number(text: Any) -> str:
        """A printed amount as its absolute value, '' for a blank or a dash, or the text itself if it isn't one."""
        text = str(text).strip()
        if re.fullmatch(r"[\s$€£()\-–—.]*", text):
            return ""
        found = numbers_in(text)
        if len(found) > 1 and all(len(n) == 1 for n in found[1:]):  # a footnote marker after the amount
            return found[0]
        return found[0] if len(found) == 1 else text

    def right(found: Any, key: str) -> bool:
        return number(found) == key or (key == "0" and number(found) in ("", "0"))

    def align(found: list[list[str]], key: list[list[str | None]]) -> tuple[int, ...]:
        """The extracted column for each key column: the assignment under which the most key values appear."""
        width = max([len(r) for r in found] + [len(key[0])])
        seen = [{number(r[i]) for r in found if i < len(r)} for i in range(width)]
        agree = [
            [sum(1 for k in key if k[j] not in (None, "0") and k[j] in seen[i]) for i in range(width)]
            for j in range(len(key[0]))
        ]
        options = itertools.permutations(range(min(width, 16)), len(key[0]))
        return max(options, key=lambda cols: sum(agree[j][i] for j, i in enumerate(cols)), default=())

    def score_statement(
        output: dict[str, Any] | None, key: list[tuple[str, list[str | None]]]
    ) -> tuple[dict[str, int], list[str]]:
        """Counts of right, wrong and missing values, and each wrong value as 'label: printed, got'."""
        rows = [(r["label"], r["values"]) for r in (output or {}).get("rows", [])]
        counts = {"values": 0, "right": 0, "wrong": 0, "missing": 0}
        wrongs = []
        cols = align([v for _, v in rows], [v for _, v in key]) if rows and key else ()
        unused = list(range(len(rows)))
        for label, values in key:
            wanted = [(j, v) for j, v in enumerate(values) if v is not None]
            counts["values"] += len(wanted)

            def cell(i: int, j: int) -> str:
                return rows[i][1][cols[j]] if cols and cols[j] < len(rows[i][1]) else ""

            def agreement(i: int, label: str = label, wanted: list = wanted) -> int:
                hits = sum(right(cell(i, j), v) for j, v in wanted if v != "0")
                return hits + (fuzz.ratio(rows[i][0].lower(), label.lower()) >= 85)

            best = max(unused, key=agreement, default=None)
            if best is None or agreement(best) == 0:
                counts["missing"] += len(wanted)
                continue
            unused.remove(best)
            for j, v in wanted:
                f = cell(best, j)
                outcome = "right" if right(f, v) else "missing" if number(f) == "" else "wrong"
                counts[outcome] += 1
                if outcome == "wrong":
                    wrongs.append(f'"{label}": printed {v}, got {f}')
        return counts, wrongs

    def score(answer: dict[str, Any], filing: dict[str, Any]) -> dict[str, Any]:
        """Counts per statement type for one pipeline's answer on one filing, and its wrong values."""
        out: dict[str, Any] = {"wrong values": []}
        for kind, field in FIELDS.items():
            counts, wrongs = score_statement((answer["output"] or {}).get(field), filing["statements"][kind]["key"])
            counts["silent"] = int(not answer["error"] and counts["right"] + counts["wrong"] < 0.2 * counts["values"])
            out[kind] = counts
            out["wrong values"] += [f"{filing['name']}, {kind}, {w}" for w in wrongs]
        return out

    BY_SLUG = {f["slug"]: f for f in CORPUS}
    return BY_SLUG, score


@app.cell
def _(ANSWERS, BY_SLUG, PIPELINES, SUBSET, score):
    SCORES = {k: score(a, BY_SLUG[k[2]]) for k, a in ANSWERS.items()}

    def totals(run: int, name: str, slugs: list[str], kinds: tuple[str, ...] = STATEMENTS) -> dict[str, float]:
        t: dict[str, float] = {"values": 0, "right": 0, "wrong": 0, "missing": 0, "silent": 0, "statements": 0}
        t |= {"errors": 0, "usd": 0.0, "seconds": 0.0, "pages": 0}
        for slug in slugs:
            answer = ANSWERS[(run, name, slug)]
            t["errors"] += bool(answer["error"])
            t["usd"] += answer["usd"]
            t["seconds"] += answer["seconds"]
            t["pages"] += BY_SLUG[slug]["pages"]
            for kind in kinds:
                for field in ("values", "right", "wrong", "missing", "silent"):
                    t[field] += SCORES[(run, name, slug)][kind][field]
                t["statements"] += 1
        return t

    def slugs_for(name: str, subset: bool) -> list[str]:
        return SUBSET if subset or PIPELINES[name][2] else list(BY_SLUG)

    def pct(part: float, whole: float) -> str:
        return f"{part / whole:.1%}" if whole else "–"

    return SCORES, pct, slugs_for, totals


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. Results

    **All filings, both runs.** The share of key values each pipeline got right, wrong and missing in run 1 and
    run 2. "Flipped" counts statements whose number of right values changed between runs. Cost and time are per
    page, averaged over both runs. Reducto is costed at list price.
    """)
    return


@app.cell
def _(BY_SLUG, OPEN, PIPELINES, SCORES, pct, slugs_for, totals):
    def flipped(name: str, slugs: list[str]) -> tuple[int, int]:
        """Statements whose right-count changed between runs, and how many values that moved."""
        statements = moved = 0
        for slug in slugs:
            for kind in STATEMENTS:
                a, b = SCORES[(1, name, slug)][kind], SCORES[(2, name, slug)][kind]
                statements += a["right"] != b["right"]
                moved += abs(a["right"] - b["right"])
        return statements, moved

    def results_table(names: list[str], subset: bool) -> str:
        lines = [
            "| Pipeline | Filings | Right, run 1 | Right, run 2 | Wrong (1 / 2) | Missing (1 / 2) | Statements flipped "
            "| Silent failures (1 / 2) | Errors (1 / 2) | $ per page | Seconds per page |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for name in names:
            slugs = slugs_for(name, subset)
            a, b = totals(1, name, slugs), totals(2, name, slugs)
            statements, moved = flipped(name, slugs)
            lines.append(
                f"| {name} | {len(slugs)} | {pct(a['right'], a['values'])} | {pct(b['right'], b['values'])} | "
                f"{pct(a['wrong'], a['values'])} / {pct(b['wrong'], b['values'])} | "
                f"{pct(a['missing'], a['values'])} / {pct(b['missing'], b['values'])} | "
                f"{statements} of {a['statements']} ({moved} values) | "
                f"{a['silent']} / {b['silent']} of {a['statements']} | {a['errors']} / {b['errors']} | "
                f"{(a['usd'] + b['usd']) / (a['pages'] + b['pages']):.4f} | "
                f"{(a['seconds'] + b['seconds']) / (a['pages'] + b['pages']):.1f} |"
            )
        return "\n".join(lines)

    MAIN_TABLE = results_table([n for n in PIPELINES if not PIPELINES[n][2]], subset=False)
    SUBSET_TABLE = results_table(list(PIPELINES), subset=True)
    BEST_OPEN = max(OPEN, key=lambda n: sum(totals(r, n, list(BY_SLUG))["right"] for r in (1, 2)))
    mo.md(MAIN_TABLE)
    return BEST_OPEN, MAIN_TABLE, SUBSET_TABLE


@app.cell(hide_code=True)
def _(SUBSET_TABLE):
    mo.md(
        "**The subset**, every third filing, where Deep Extract and Gemini 4 Argon also ran. The same columns as "
        "above, on these filings only.\n\n" + SUBSET_TABLE
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **By statement type.** Reducto Extract against the best open pipeline (the one with the most values right
    over both runs), and Deep Extract against Gemini 4 Argon on the subset. The table shows the share right and
    wrong for each statement type, both runs pooled.
    """)
    return


@app.cell
def _(BEST_OPEN, BY_SLUG, SUBSET, pct, totals):
    def by_type(names: list[str], slugs: list[str]) -> str:
        lines = ["| Statement | " + " | ".join(f"{n}: right / wrong" for n in names) + " |"]
        lines.append("|---|" + "---|" * len(names))
        for kind in STATEMENTS:
            cells = []
            for name in names:
                a, b = totals(1, name, slugs, (kind,)), totals(2, name, slugs, (kind,))
                values = a["values"] + b["values"]
                cells.append(f"{pct(a['right'] + b['right'], values)} / {pct(a['wrong'] + b['wrong'], values)}")
            lines.append(f"| {kind} | " + " | ".join(cells) + " |")
        return "\n".join(lines)

    _subset_names = [BEST_OPEN, "Reducto Extract", "Gemini 4 Argon, whole PDF", "Reducto Deep Extract"]
    TYPE_TABLE = (
        f"All filings:\n\n{by_type([BEST_OPEN, 'Reducto Extract'], list(BY_SLUG))}\n\n"
        f"Subset:\n\n{by_type(_subset_names, SUBSET)}"
    )
    mo.md(TYPE_TABLE)
    return (TYPE_TABLE,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Per filing.** The share right in run 1 and run 2, for every pipeline that ran on the filing. This is where to
    look for which filings each pipeline struggles with.
    """)
    return


@app.cell
def _(ANSWERS, BY_SLUG, PIPELINES, SCORES):
    def filing_cell(name: str, slug: str) -> str:
        if (1, name, slug) not in ANSWERS:
            return ""
        shares = []
        for run in (1, 2):
            s = SCORES[(run, name, slug)]
            shares.append(f"{sum(s[k]['right'] for k in STATEMENTS) / sum(s[k]['values'] for k in STATEMENTS):.0%}")
        return " / ".join(shares)

    FILING_TABLE = "| Filing | " + " | ".join(PIPELINES) + " |\n|---|" + "---|" * len(PIPELINES) + "\n"
    FILING_TABLE += "\n".join(
        f"| {f['name']} {f['form']} {f['period']} | " + " | ".join(filing_cell(n, slug) for n in PIPELINES) + " |"
        for slug, f in BY_SLUG.items()
    )
    mo.md(FILING_TABLE)
    return (FILING_TABLE,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **What the wrong values look like.** For each pipeline, how many wrong values it gave in run 1, and the first
    of them on up to six filings: the line item, what the filing prints and what the pipeline returned.
    """)
    return


@app.cell
def _(BY_SLUG, PIPELINES, SCORES):
    def wrong_examples(name: str) -> str:
        found = [SCORES[(1, name, s)]["wrong values"] for s in BY_SLUG if (1, name, s) in SCORES]
        firsts = [w[0] for w in found if w][:6]
        return f"{sum(len(w) for w in found)} wrong. " + "; ".join(firsts)

    EXAMPLES = "\n".join(f"- **{n}:** {wrong_examples(n)}" for n in PIPELINES)
    mo.md(EXAMPLES)
    return (EXAMPLES,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 7. What didn't work, and what to read into it

    - **The first scoring blamed the readers for the key's mistakes.** Every pipeline showed the same ~70 wrong
      values. They came from Simon Property's combined filing, which repeats every line in one `R` page; from
      Deere's segment columns, which column alignment first looked past; and from comprehensive-income and
      percent-of-sales lines that the prompt tells pipelines to skip. Section 2 and section 5 now handle all
      three, the same way for every pipeline. When every reader gets the same value wrong, suspect the key.
    - **Finding the statements in print needs care.** Quarterly-data tables in the notes and MD&A summaries print
      many of the same numbers. Hence the title rule in section 3. For Deere it still chose the supplemental
      consolidating cash-flow statement, whose 12 columns include the consolidated ones. That page caused every
      silent failure in the run.
    - **Two filings couldn't be used.** Eli Lilly's 2011 filing has only the older XML viewer pages. Sturm
      Ruger's printed PDF puts every character on its own line in the text layer, so its statements couldn't be
      found. Reserves replaced both.
    - **Signs aren't scored**, and a row whose numbers are all wrong under a label that differs from XBRL's
      counts as missing, so "wrong" is a floor (see the README).
    """)
    return


@app.cell
def _(CORPUS_TABLE, EXAMPLES, FILING_TABLE, MAIN_TABLE, SUBSET_TABLE, TYPE_TABLE):
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "results.md").write_text(
        "# Results\n\nWritten by `sec_filings.py`; see the notebook for how each number is made.\n\n"
        f"## Corpus\n\n{CORPUS_TABLE}\n\n## All filings\n\n{MAIN_TABLE}\n\n## Subset\n\n{SUBSET_TABLE}\n\n"
        f"## By statement type\n\n{TYPE_TABLE}\n\n## Per filing\n\n{FILING_TABLE}\n\n## Wrong values\n\n{EXAMPLES}\n"
    )
    print((RESULTS / "results.md").read_text())
    return


if __name__ == "__main__":
    app.run()
