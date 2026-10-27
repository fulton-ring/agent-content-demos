import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import hashlib
    import json
    import os
    import re
    import time
    import urllib.request
    from pathlib import Path
    from typing import Any

    import marimo as mo
    import pypdfium2 as pdfium
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling_core.types.doc import DoclingDocument, SectionHeaderItem, TableItem, TitleItem
    from pydantic import BaseModel, Field
    from pydantic_ai import BinaryContent
    from rapidfuzz import fuzz

    import model_call

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("REDUCTO_OUTPUT_DIR", HERE / "output")) / "sections"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 2. Section parsing on long government reports

    **The question.** Reducto's *Parse* turns a long document into sections and tables, with each section's
    heading and page. Schema extraction on a one-page form (notebook 1) is the easy half. Can Docling, a vision
    language model, or the two together find the sections of a long, messy public report and read its tables?

    **The documents.** Two FEMA Flood Insurance Studies for the same county, Henrico County in Virginia,
    downloaded at run time from FEMA's Map Service Center and hash-checked:

    - **1980**: 65 pages, typewritten and scanned, with no text layer. Two tables are printed sideways, and the
      printed table numbers don't match the table of contents.
    - **2024**: 94 pages, born digital, with a text layer, tables that run over many pages, and three heading
      levels.

    **The answer key** is `section_key.json`, keyed by hand from the page images: every numbered section
    heading in the body (69 in all), its level and the PDF page it starts on, plus three tables from each
    report (587 cells). The key's tables cover what Reducto's docs single out: a table that continues on the
    next page, a table printed sideways, dense numbers under a two-level header, and a 60-word cell.

    **Three reports without heading numbers** (issue #130), where a heading is known only by its type size,
    capitals, centring or underline:

    - **USGS SIR 2023-5014**, flood frequency in Hawaii: 78 pages, born digital, two columns, three heading levels,
      and a table printed sideways over four pages.
    - **USGS Circular 166** (1953), irrigation wells in Box Butte County, Nebraska: 46 pages, typewritten and scanned
      with no text layer, two columns, with headings five levels deep shown by capitals, centring, underlining
      and run-in headings ("Chadron formation.--The ...").
    - **Lewis County, NY 2026 Adopted Budget**: 130 pages, a county budget book, born digital, whose contents page
      is a page early for five departments.

    Their keys give the contents' entries (141 headings) with the page each is printed on in the body, and one
    table of three or more pages from each (1,861 cells).
    """)
    return


@app.cell
def _():
    _fema = "https://msc.fema.gov/portal/downloadProduct?productID="
    DOCS = {  # name: (URL, sha256)
        "fis-henrico-1980": (_fema + "510077V000", "f426f88411f8816d5f96b8edcf7444c85b09f9074fb0b804c8909ef407dfaf1f"),
        "fis-henrico-2024": (_fema + "51087CV001B", "bbca76cb3f306b26c6b53c53e9748b63d6f45599394d6367fdfc22493a7a6c4b"),
        "usgs-sir-2023-5014": (
            "https://pubs.usgs.gov/sir/2023/5014/sir20235014.pdf",
            "108ae4adb572dcf6b054eafc9c1d4461482bb592996fd6cd07e005e40cc7b2e6",
        ),
        "usgs-circ-166-1953": (
            "https://pubs.usgs.gov/circ/1953/0166/report.pdf",
            "d0cf441da37e011da89be5755bc4ed3ca8d9c392f37d692bf7f8e8d7ecabe03f",
        ),
        "lewis-county-budget-2026": (
            "https://lewiscountyny.gov/wp-content/uploads/2025/12/2026-Adopted-Budget.pdf",
            "773f8fdc308c8bd5c9a8ff4337cb49818ba94daa3a989f52cb964f0a25489f55",
        ),
    }
    KEY = {k: v for k, v in json.loads((HERE / "section_key.json").read_text()).items() if k[0] != "_"}
    OUT.mkdir(parents=True, exist_ok=True)
    for _name, (_url, _sha) in DOCS.items():
        _path = OUT / f"{_name}.pdf"
        if _path.exists() and hashlib.sha256(_path.read_bytes()).hexdigest() == _sha:
            continue
        with urllib.request.urlopen(
            urllib.request.Request(_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=300
        ) as r:
            _data = r.read()
        if (_got := hashlib.sha256(_data).hexdigest()) != _sha:
            raise RuntimeError(f"{_name}: the file at {_url} has changed (sha256 {_got})")
        _path.write_bytes(_data)
    PAGES = {name: len(pdfium.PdfDocument(OUT / f"{name}.pdf")) for name in DOCS}
    print(PAGES)
    return DOCS, KEY, PAGES


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Three pipelines

    - **Docling alone.** Sections are its section-header and title items, with their level and page. A table is
      every Docling table on the key table's pages, joined, since a table that continues is two tables to Docling.
    - **VLM alone.** Gemini 3.8 Flash gets the whole PDF, and returns the outline, then each table by its name.
    - **Docling, then the VLM.** Gemini gets Docling's Markdown, page by page, and returns the outline. For a table,
      Docling finds the pages that name it, and Gemini reads their images along with Docling's Markdown of them.

    Docling runs as in notebook 1: Tesseract on scanned pages, table structure on. It is saved in
    `output/sections/`, so it runs once.
    """)
    return


@app.cell
def _(DOCS):
    _options = PdfPipelineOptions(
        do_ocr=True, ocr_options=TesseractCliOcrOptions(lang=["eng"]), do_table_structure=True
    )
    _converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=_options)})
    docling_docs: dict[str, DoclingDocument] = {}
    docling_seconds: dict[str, float] = {}
    for _name in DOCS:
        _saved, _timing = OUT / f"{_name}.docling.json", OUT / f"{_name}.docling-seconds.txt"
        if not _saved.exists():
            _t0 = time.time()
            _converter.convert(OUT / f"{_name}.pdf").document.save_as_json(_saved)
            _timing.write_text(f"{time.time() - _t0:.1f}")
        docling_docs[_name] = DoclingDocument.load_from_json(_saved)
        docling_seconds[_name] = float(_timing.read_text())
    print(docling_seconds)
    return docling_docs, docling_seconds


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What each pipeline is asked for

    The model returns typed answers: an outline (each heading as printed, its level, its PDF page) and a table
    (its data rows, each a list of cells). Both prompts are the same for both pipelines that use the model.
    """)
    return


@app.cell
def _():
    class Heading(BaseModel):
        text: str = Field(description="The heading exactly as printed, with its number if it has one.")
        level: int = Field(ge=1, le=6, description="1 for a top-level section, 2 for its subsections, and so on.")
        page: int = Field(ge=1, description="The PDF page the heading is on; 1 is the file's first page.")

    class Outline(BaseModel):
        """The document's sections, in reading order."""

        headings: list[Heading]

    class Table(BaseModel):
        """One table's data rows, joined across pages if it continues."""

        rows: list[list[str]] = Field(description="Each data row as its cells, left to right, exactly as printed.")

    INSTRUCTIONS = "You read long US government reports. Report only what is printed. Never infer or fill in text."
    OUTLINE_PROMPT = (
        "List the section headings of this report's body, in order: each heading as printed, its level in the "
        "outline and the PDF page it is on (1 is the file's first page, the cover). Leave out the table of "
        "contents, running headers, and the titles of tables and figures."
    )

    def table_prompt(ask: str) -> str:
        return (
            f"Read the table: {ask}. If it continues on later pages, join its parts. Give its data rows only, "
            "each as its cells from left to right; leave out header rows, rows that only name a group, and "
            "footnote markers. Join a cell's wrapped lines with spaces. An empty cell is ''."
        )

    return INSTRUCTIONS, OUTLINE_PROMPT, Outline, Table, table_prompt


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Docling alone

    A heading is any section-header or title item. A table is every Docling table on the key table's pages,
    joined in order, with its header rows kept, since Docling doesn't say which rows are headers. Extra rows
    don't cost anything in the scoring below; missing or split rows do.
    """)
    return


@app.cell
def _(DOCS, KEY, docling_docs):
    def page_of(item: Any) -> int:
        return item.prov[0].page_no if item.prov else 0

    docling_alone: dict[str, dict[str, Any]] = {}
    for _name in DOCS:
        _doc = docling_docs[_name]
        _items = [item for item, _level in _doc.iterate_items()]
        _headings = [
            {"text": i.text, "level": i.level if isinstance(i, SectionHeaderItem) else 1, "page": page_of(i)}
            for i in _items
            if isinstance(i, SectionHeaderItem | TitleItem)
        ]
        _tables = []
        for _t in KEY[_name]["tables"]:
            _rows = []
            for _item in (i for i in _items if isinstance(i, TableItem) and page_of(i) in _t["pages"]):
                _df = _item.export_to_dataframe(_doc)
                _rows += [[str(c) for c in _df.columns], *[[str(c) for c in r] for r in _df.values.tolist()]]
            _tables.append(_rows)
        docling_alone[_name] = {"headings": _headings, "tables": _tables}
        print(f"{_name}: Docling found {len(_headings)} headings")
    return (docling_alone,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The VLM alone, and Docling then the VLM

    For tables, the hybrid pipeline needs Docling to find the pages: every page whose Markdown names the table
    (fuzzy match on its title), at most the first five. That's how a pipeline without the answer key would find
    them. Answers are saved in `output/answers/`.
    """)
    return


@app.cell
async def _(DOCS, INSTRUCTIONS, KEY, OUTLINE_PROMPT, Outline, Table, docling_docs, table_prompt):
    _slots = asyncio.Semaphore(6)

    def markdown_pages(name: str) -> list[str]:
        doc = docling_docs[name]
        return [doc.export_to_markdown(page_no=n) for n in range(1, doc.num_pages() + 1)]

    def png(name: str, page: int) -> BinaryContent:
        image = pdfium.PdfDocument(OUT / f"{name}.pdf")[page - 1].render(scale=150 / 72).to_pil().convert("RGB")
        path = OUT / f"{name}-p{page}.png"
        image.save(path)
        return BinaryContent(path.read_bytes(), media_type="image/png")

    async def answer(pipeline: str, name: str, call: str, output_type: Any, parts: list[Any]) -> dict[str, Any]:
        saved = OUT.parent / "answers" / pipeline / f"{name}-{call}.json"
        return await model_call.ask(saved, output_type, INSTRUCTIONS, parts, _slots)

    async def vlm_alone(name: str) -> dict[str, Any]:
        pdf = BinaryContent((OUT / f"{name}.pdf").read_bytes(), media_type="application/pdf")
        calls = [answer("vlm-alone", name, "outline", Outline, [OUTLINE_PROMPT, pdf])]
        calls += [
            answer("vlm-alone", name, f"table{i}", Table, [table_prompt(t["ask"]), pdf])
            for i, t in enumerate(KEY[name]["tables"])
        ]
        return dict(
            zip(["outline", *[f"table{i}" for i in range(len(calls) - 1)]], await asyncio.gather(*calls), strict=True)
        )

    async def docling_then_vlm(name: str) -> dict[str, Any]:
        pages = markdown_pages(name)
        marked = "\n\n".join(f"--- PDF page {i + 1} ---\n{md}" for i, md in enumerate(pages))
        calls = [answer("docling-vlm", name, "outline", Outline, [OUTLINE_PROMPT, "Docling's Markdown:\n\n" + marked])]
        for i, t in enumerate(KEY[name]["tables"]):
            found = [n + 1 for n, md in enumerate(pages) if fuzz.partial_ratio(t["find"].lower(), md.lower()) >= 90]
            found = found[:5] or [1]
            parts = [table_prompt(t["ask"])]
            for p in found:
                parts += [f"--- PDF page {p}, Docling's Markdown ---\n{pages[p - 1]}", png(name, p)]
            calls.append(answer("docling-vlm", name, f"table{i}", Table, parts))
        results = await asyncio.gather(*calls)
        return dict(zip(["outline", *[f"table{i}" for i in range(len(calls) - 1)]], results, strict=True))

    vlm_answers = dict(zip(DOCS, await asyncio.gather(*(vlm_alone(n) for n in DOCS)), strict=True))
    hybrid_answers = dict(zip(DOCS, await asyncio.gather(*(docling_then_vlm(n) for n in DOCS)), strict=True))
    return hybrid_answers, vlm_answers


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring

    - **Heading recall**: the share of the key's headings a pipeline found, matching text after lowercasing and
      dropping punctuation and the word "section" (a fuzzy ratio of 85 or more, each found heading used once).
    - **Section recall**: found, *and* on the right PDF page, so the section's boundary is right.
    - **Level right**: of the headings found, the share at the key's outline level.
    - **Extra headings**: found headings that match none of the key's. Some are real headings the key leaves out
      (an unnumbered sub-heading such as "James River"), so this is not precision.
    - **Table cell accuracy**: for each key row, the found row that agrees with it on the most cells; the share of
      the key's cells that agree. The row label is compared fuzzily, and each later key cell must equal (after
      dropping spaces) a cell to the right of the last one matched, so a found row with an extra column, such as
      Docling keeping a column the key leaves out, isn't scored as all wrong.
    """)
    return


@app.cell
def _():
    def clean(text: str) -> str:
        text = re.sub(r"\bsection\b", " ", text.lower())
        return " ".join(re.sub(r"[^a-z0-9.]+", " ", text).split()).strip(" .")

    def score_headings(found: list[dict[str, Any]], key: list[dict[str, Any]]) -> dict[str, Any]:
        unused, hits = list(found), []
        for k in key:
            best = max(unused, key=lambda f: fuzz.ratio(clean(f["text"]), clean(k["heading"])), default=None)
            if best is not None and fuzz.ratio(clean(best["text"]), clean(k["heading"])) >= 85:
                unused.remove(best)
                hits.append((k, best))
        return {
            "headings": len(key),
            "found": len(hits),
            "right_page": sum(k["page"] == f["page"] for k, f in hits),
            "right_level": sum(k["level"] == f["level"] for k, f in hits),
            "extra": len(unused),
            "missed": [k["heading"] for k in key if all(k is not h for h, _f in hits)],
            "wrong_page": [
                f"{k['heading']} (p{k['page']}, found p{f['page']})" for k, f in hits if k["page"] != f["page"]
            ],
        }

    def cell(text: str) -> str:
        return re.sub(r"\s+", "", str(text)).replace("–", "-").replace("—", "-").replace("−", "-").lower()

    def score_table(found: list[list[str]], key: list[list[str]]) -> dict[str, int]:
        def agree(row: list[str], k: list[str]) -> int:
            label = fuzz.ratio(clean(row[0]) if row else "", clean(k[0])) >= 85
            found, at, right = [cell(c) for c in row[1:]], 0, int(label)
            for want in (cell(c) for c in k[1:]):
                if want in found[at:]:
                    at = found.index(want, at) + 1
                    right += 1
            return right

        right = sum(max((agree(r, k) for r in found), default=0) for k in key)
        return {"cells": sum(len(k) for k in key), "right": right}

    return score_headings, score_table


@app.cell
def _(DOCS, KEY, PAGES, docling_alone, docling_seconds, hybrid_answers, score_headings, score_table, vlm_answers):
    def from_model(answers: dict[str, Any]) -> dict[str, Any]:
        tables = [answers[k]["output"]["rows"] for k in answers if k.startswith("table")]
        return {"headings": answers["outline"]["output"]["headings"], "tables": tables}

    def spent(answers: dict[str, Any]) -> tuple[float, float]:
        return sum(a["usd"] for a in answers.values()), sum(a["seconds"] for a in answers.values())

    results = []
    for _name in DOCS:
        for _pipeline, _found, (_usd, _secs), _docling in [
            ("Docling alone", docling_alone[_name], (0.0, 0.0), docling_seconds[_name]),
            ("VLM alone", from_model(vlm_answers[_name]), spent(vlm_answers[_name]), 0.0),
            (
                "Docling, then the VLM",
                from_model(hybrid_answers[_name]),
                spent(hybrid_answers[_name]),
                docling_seconds[_name],
            ),
        ]:
            _tables = [
                {"title": t["title"], **score_table(f, t["rows"])}
                for t, f in zip(KEY[_name]["tables"], _found["tables"], strict=True)
            ]
            results.append(
                {
                    "document": _name,
                    "pipeline": _pipeline,
                    "sections": score_headings(_found["headings"], KEY[_name]["headings"]),
                    "tables": _tables,
                    "usd_per_page": _usd / PAGES[_name],
                    "docling_seconds_per_page": _docling / PAGES[_name],
                    "model_seconds_per_page": _secs / PAGES[_name],
                    "found": _found,
                }
            )
    (OUT / "results.json").write_text(json.dumps(results, indent=1))
    return (results,)


@app.cell
def _(results):
    _lines = [
        "| Document | Pipeline | Heading recall | Section recall | Level right | Extra headings | Table cells right "
        "| Cost per page | Seconds per page (Docling + model) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for _r in results:
        _s, _cells = _r["sections"], sum(t["cells"] for t in _r["tables"])
        _right = sum(t["right"] for t in _r["tables"])
        _lines.append(
            f"| {_r['document']} | {_r['pipeline']} | {_s['found']} of {_s['headings']} "
            f"| {_s['right_page']} of {_s['headings']} | {_s['right_level']} of {_s['found']} | {_s['extra']} "
            f"| {_right} of {_cells} ({_right / _cells:.0%}) | ${_r['usd_per_page']:.4f} "
            f"| {_r['docling_seconds_per_page']:.1f} + {_r['model_seconds_per_page']:.1f} |"
        )
    _tables = ["| Document | Table | " + " | ".join(r["pipeline"] for r in results[:3]) + " |", "|---|---|---|---|---|"]
    for _i in range(0, len(results), 3):
        for _j, _t in enumerate(results[_i]["tables"]):
            _cells = [f"{r['tables'][_j]['right']} of {_t['cells']}" for r in results[_i : _i + 3]]
            _tables.append(f"| {results[_i]['document']} | {_t['title']} | " + " | ".join(_cells) + " |")
    section_table = "\n".join(_lines) + "\n\n" + "\n".join(_tables)
    (OUT / "section_parsing.md").write_text(section_table + "\n")
    print(section_table)
    mo.md("## Results\n\n" + section_table)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Where each pipeline went wrong

    The key's headings each pipeline missed, and those it put on the wrong page.
    """)
    return


@app.cell
def _(results):
    _out = []
    for _r in results:
        _s = _r["sections"]
        _out.append(
            f"**{_r['document']}, {_r['pipeline']}.** Missed: {'; '.join(_s['missed']) or 'none'}. "
            f"Wrong page: {'; '.join(_s['wrong_page']) or 'none'}."
        )
    print("\n\n".join(_out))
    mo.md("\n\n".join(_out))
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What didn't work

    - **Docling's outline is flat.** Every heading comes back at level 1, so the hierarchy has to come from the
      heading numbers or a model. It also counts the cover lines and the table of contents as headings, and on
      the scan it drops some headings' numbers ("Coordination" for "1.2 Coordination"). Passing Docling's
      Markdown to Gemini fixed the levels and most of the extras.
    - **Docling merges the rows of a table without rules between them.** On the 2024 Floodway Data page, its
      table is one row whose cells are whole columns of numbers (see `screenshots/`). Gemini reading the page
      image got every cell.
    - **Docling can't read a page printed sideways.** The 1980 Flood Insurance Zone Data table comes out as
      fragments. Worse, its OCR text never names the table, so the Docling-then-VLM pipeline couldn't find the
      page and returned nothing, while Gemini given the whole PDF read every cell. Routing on Docling's text
      fails on exactly the pages that need help most.
    - **The printed table number disagrees with the contents** on the 1980 report (the contents' Table 4 is
      printed "TABLE 3"). We asked for that table by its title and streams, not its number.

    On the three reports without heading numbers:

    - **Routing on Docling's text loses whole pages of a table, silently.** In the budget book, Docling splits
      "Department of Social Services" across two header cells, so the page finder matched no page and the model
      returned no rows (see `screenshots/`). On the 1953 scan, Docling's OCR never found the title on the table's
      second page, so that page was never sent and its rows are missing. Gemini given the whole PDF got every cell
      of both.
    - **The model nests headings by meaning, not by type.** In the two-column USGS report, "Rainfall" and
      "El Niño ..." are set in the same type as "Climate", but Gemini put them under it. Docling's Markdown, which
      flattens the type, made it worse.
    - **Docling alone misses run-in headings** ("Chadron formation.--The ...") on the scan, and still puts almost
      every heading at level 1.
    """)
    return


if __name__ == "__main__":
    app.run()
