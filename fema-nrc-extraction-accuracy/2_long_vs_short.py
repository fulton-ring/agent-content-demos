import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import json
    import random

    import marimo as mo
    import pandas as pd
    import pypdfium2 as pdfium
    from pydantic import BaseModel, Field
    from pydantic_ai import BinaryContent

    from common import ANSWERS, HERE, MODELS, ask, fis_pdf, image, page_png, same, tesseract, text_layer


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 2. Does accuracy fall on long flood studies?

    ExtractBench reports one system scoring 97.2 on short documents and 31.7 on long ones, and Joshua Cook found
    the cheapest large model returned well-formed, empty JSON on every long SEC filing it saw. Does that happen on
    FEMA flood studies? And how much does it matter whether the page needed OCR, against which model reads it?

    **The documents.** From notebook 1's 70 studies we take four groups: short (30 pages or fewer) and long (75 or
    more), each either scanned or born digital. Two studies per group are drawn with `random.Random(175)`; where a
    drawn study had no Summary of Discharges table (35001CV002 prints it in its other volume) the next draw is used.

    **The answer key** (`fis_key.json`) is one page of each study's *Summary of Discharges* table, the page drawn
    with `random.Random(175)` from the pages the table is printed on: each row's location, drainage area and the
    10%, 2%, 1% and 0.2% annual chance peak discharges, 404 values in all. We keyed every value by eye from the page
    image. On the four born-digital pages all 222 values were then found, in order, in the text layer. On the four
    scans, Tesseract at 300 dpi agreed on 177 of 182; the five it misread were checked again on the image.
    """)
    return


@app.cell
def _():
    KEY = {k: v for k, v in json.loads((HERE / "fis_key.json").read_text()).items() if not k.startswith("_")}
    GROUPS = {
        "510218V000": ("short", "scan"),
        "060724V000": ("short", "scan"),
        "45061CV000A": ("short", "digital"),
        "35053CV000A": ("short", "digital"),
        "51005CV000A": ("long", "scan"),
        "080290V000": ("long", "scan"),
        "39151CV001C": ("long", "digital"),
        "35049CV000A": ("long", "digital"),
    }
    # The pages each table is printed on, found from the text layer or Tesseract, and by eye where the table is
    # printed sideways and Tesseract reads it as noise (080290V000, 060724V000). The keyed page is drawn from these.
    TABLE_PAGES = {
        "39151CV001C": list(range(42, 52)),
        "35049CV000A": [12, 13, 14],
        "51005CV000A": [16, 17],
        "080290V000": [15, 16],
        "45061CV000A": [10],
        "35053CV000A": [9, 10, 11],
        "510218V000": [8],
        "060724V000": [11],
    }
    _rng = random.Random(175)
    for _doc, _pages in TABLE_PAGES.items():
        assert _rng.choice(_pages) == KEY[_doc]["page"], f"{_doc}: the keyed page isn't the drawn page"
    PDFS = {doc: fis_pdf(doc) for doc in GROUPS}
    LENGTH = {doc: len(pdfium.PdfDocument(pdf)) for doc, pdf in PDFS.items()}
    print({doc: (GROUPS[doc], LENGTH[doc], KEY[doc]["page"]) for doc in GROUPS})
    return GROUPS, KEY, LENGTH, PDFS


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Five pipelines, two models

    Every pipeline asks for the same typed rows. The first three are given the page the key is on, so they measure
    reading; the last two get the whole study and no page, so they measure finding the table in a long document
    as well.

    1. **Text layer, page**: the page's own text layer, as a text-only pipeline would get it. A scan has none, so
       nothing is sent and every value counts as missing. That's what a router that trusts the text layer gets.
    2. **Tesseract, page**: Tesseract 5's text of the page at 300 dpi, default settings.
    3. **Image, page**: the page rendered at 150 dpi.
    4. **Text layer, whole study**: every page's text layer, marked by page. Born-digital studies only.
    5. **PDF, whole study**: the whole PDF file, as OpenRouter passes it to each model.

    Each runs with Gemini 3.8 Flash and Claude Haiku 5.5, at temperature 0. Answers are saved in `answers/fis/` and
    committed; a re-run reads them instead of calling the model again.
    """)
    return


@app.cell
def _(KEY, PDFS):
    class Row(BaseModel):
        flooding_source: str = Field(description="The stream the row falls under, '' if not printed on the page.")
        location: str
        drainage_area: str = Field(description="Drainage area in square miles, as printed.")
        q10: str = Field(description="10-percent annual chance (10-year) peak discharge, cfs.")
        q2: str = Field(description="2-percent annual chance (50-year) peak discharge, cfs.")
        q1: str = Field(description="1-percent annual chance (100-year) peak discharge, cfs.")
        q02: str = Field(description="0.2-percent annual chance (500-year) peak discharge, cfs.")

    class Discharges(BaseModel):
        rows: list[Row]

    INSTRUCTIONS = (
        "You read FEMA Flood Insurance Studies. Report only what is printed. Never infer, compute or fill in a value."
    )
    _ask_rows = (
        "give every row of the Summary of Discharges table: flooding source, location, drainage area, and the peak "
        "discharges for the 10%, 2%, 1% and 0.2% annual chance floods (10-, 50-, 100- and 500-year). Copy numbers "
        "as printed. A cell that is blank, '*' or 'not determined' is ''. Leave out other columns, such as 4% or "
        "1% plus, and leave out header, subtotal and footnote lines."
    )

    def page_prompt(doc: str) -> str:
        return f"This is page {KEY[doc]['page']} of a FEMA Flood Insurance Study. From this page only, {_ask_rows}"

    def whole_prompt() -> str:
        return f"This is a whole FEMA Flood Insurance Study. Find its Summary of Discharges table and {_ask_rows}"

    def whole_text(doc: str) -> str:
        pages = len(pdfium.PdfDocument(PDFS[doc]))
        return "\n".join(f"--- page {p} ---\n{text_layer(PDFS[doc], p)}" for p in range(1, pages + 1))

    return Discharges, INSTRUCTIONS, page_prompt, whole_prompt, whole_text


@app.cell
async def _(Discharges, GROUPS, INSTRUCTIONS, KEY, PDFS, page_prompt, whole_prompt, whole_text):
    _slots = asyncio.Semaphore(8)

    def _inputs(doc: str) -> dict[str, list | None]:
        pdf, page = PDFS[doc], KEY[doc]["page"]
        layer = text_layer(pdf, page)
        digital = GROUPS[doc][1] == "digital"
        return {
            "Text layer, page": [page_prompt(doc), layer] if len(layer.strip()) >= 50 else None,
            "Tesseract, page": [page_prompt(doc), tesseract(pdf, page)[0]],
            "Image, page": [page_prompt(doc), image(page_png(pdf, page))],
            "Text layer, whole study": [whole_prompt(), whole_text(doc)] if digital else None,
            "PDF, whole study": [whole_prompt(), BinaryContent(pdf.read_bytes(), media_type="application/pdf")],
        }

    async def _run(model: str, pipeline: str, doc: str, parts: list | None) -> dict:
        if parts is None:
            return {"output": {"rows": []}, "usd": 0.0, "seconds": 0.0, "error": "no text layer", "skipped": True}
        saved = ANSWERS / "fis" / model.split("/")[-1] / pipeline.replace(", ", "-").replace(" ", "-") / f"{doc}.json"
        return await ask(model, Discharges, INSTRUCTIONS, parts, saved, _slots)

    _jobs = [
        (name, pipeline, doc, parts)
        for doc in GROUPS
        for pipeline, parts in _inputs(doc).items()
        for name in MODELS
        if not (pipeline == "Text layer, whole study" and parts is None)
    ]
    _answers = await asyncio.gather(*[_run(MODELS[n], p, d, parts) for n, p, d, parts in _jobs])
    answers = {(n, p, d): a for (n, p, d, _), a in zip(_jobs, _answers, strict=True)}
    print(f"{len(answers)} answers, ${sum(a['usd'] for a in answers.values()):.2f}")
    return (answers,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring

    Each key row is paired with the reported row that agrees with it most (its location counts double), and each
    of its numbers is then **right**, **wrong** (a different value is there: the dangerous case, since it looks
    fine) or **missing**. Blank key cells aren't scored. `common.same` compares numbers by value, so 12.1 and 12.10
    match.
    """)
    return


@app.cell
def _(KEY):
    def score(found_rows: list[dict], doc: str) -> dict[str, int]:
        fields = ["drainage_area", "q10", "q2", "q1", "q02"]
        found = [[r.get("location", "")] + [r.get(f, "") for f in fields] for r in found_rows]
        unused = list(range(len(found)))
        counts = {"values": 0, "right": 0, "wrong": 0, "missing": 0}
        for key_row in KEY[doc]["rows"]:
            key = key_row[1:]

            def agree(i: int, key: list[str] = key) -> int:
                return 2 * same(found[i][0], key[0]) + sum(
                    same(f, k) for f, k in zip(found[i][1:], key[1:], strict=True) if k
                )

            best = max(unused, key=agree, default=None)
            matched = best is not None and agree(best) >= 2
            if matched:
                unused.remove(best)
            for j, k in enumerate(key[1:], start=1):
                if not k:
                    continue
                counts["values"] += 1
                f = found[best][j] if matched else ""
                counts["right" if same(f, k) else "wrong" if f.strip() not in ("", "*") else "missing"] += 1
        return counts

    return (score,)


@app.cell
def _(GROUPS, LENGTH, answers, score):
    _rows = []
    for (_model, _pipeline, _doc), _a in answers.items():
        _found = (_a["output"] or {}).get("rows", [])
        _rows.append(
            {
                "model": _model,
                "pipeline": _pipeline,
                "doc": _doc,
                "length": GROUPS[_doc][0],
                "kind": GROUPS[_doc][1],
                "pages": LENGTH[_doc],
                **score(_found, _doc),
                "usd": _a["usd"],
                "seconds": _a["seconds"],
                "error": _a.get("error", ""),
            }
        )
    scores = pd.DataFrame(_rows)
    scores["pct_right"] = (100 * scores.right / scores["values"]).round(1)
    print(scores.drop(columns=["error"]).to_string(index=False))
    print(scores[scores.error != ""][["model", "pipeline", "doc", "error"]].to_string(index=False))
    return (scores,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Short against long, scanned against born digital

    Values right out of values keyed, summed over the two studies in each group.
    """)
    return


@app.cell
def _(scores):
    _g = scores.groupby(["model", "pipeline", "length", "kind"])[["values", "right", "wrong", "missing"]].sum()
    _g["pct_right"] = (100 * _g.right / _g["values"]).round(1)
    grid = _g.pct_right.unstack(["length", "kind"])
    by_group = _g.reset_index()
    print(grid.to_string())
    return by_group, grid


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Cost and time

    OpenRouter's own cost for each call, divided by the pages the model was sent: one for the page pipelines, the
    whole study for the others. Seconds are wall time for the call, with up to eight calls running at once.
    """)
    return


@app.cell
def _(KEY, LENGTH, scores):
    _s = scores[scores.error != "no text layer"].copy()
    _s["pages_sent"] = [LENGTH[d] if "whole" in p else 1 for d, p in zip(_s.doc, _s.pipeline, strict=True)]
    _c = _s.groupby(["model", "pipeline"]).agg(
        calls=("doc", "size"), usd=("usd", "sum"), pages=("pages_sent", "sum"), seconds=("seconds", "sum")
    )
    _c["usd_per_page"] = (_c.usd / _c.pages).round(5)
    _c["seconds_per_page"] = (_c.seconds / _c.pages).round(2)
    cost = _c
    print(cost.to_string())
    print(f"keyed values: {sum(sum(1 for r in v['rows'] for c in r[2:] if c) for v in KEY.values())}")
    return (cost,)


@app.cell
def _(by_group, cost, grid, scores):
    _out = HERE / "results"
    _out.mkdir(exist_ok=True)
    scores.to_csv(_out / "2_scores.csv", index=False)
    (_out / "2_long_vs_short.md").write_text(
        "# Long against short, FEMA FIS\n\nShare of keyed values right.\n\n"
        + grid.to_markdown()
        + "\n\n## Right, wrong, missing by group\n\n"
        + by_group.to_markdown(index=False)
        + "\n\n## Cost and time\n\n"
        + cost.to_markdown()
        + "\n"
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this doesn't show

    - One keyed page per study, eight studies, 404 values. The short scans carry only 17 values between them, so
      their percentages move a lot with one error.
    - Length and scanning go together in FEMA's history: the long studies here are 81 to 127 pages, not the
      300-page volumes some benchmarks call long.
    - Each pipeline ran once. The model's answers change from run to run (see `messy-document-parsing/`).
    """)
    return


if __name__ == "__main__":
    app.run()
