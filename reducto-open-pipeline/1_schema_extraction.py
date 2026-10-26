import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import json
    import os
    import re
    import subprocess
    import sys
    import time
    from pathlib import Path
    from typing import Any, Literal

    import marimo as mo
    import pypdfium2 as pdfium
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from pydantic import BaseModel, Field, create_model
    from pydantic_ai import BinaryContent

    import model_call

    HERE = Path(__file__).parent
    K1 = HERE.parent / "k1-extraction-review-queue"
    OUT = Path(os.environ.get("REDUCTO_OUTPUT_DIR", HERE / "output"))
    K1_OUT = OUT / "k1"  # the K-1 spike's own output folder layout, so its scoring notebook reads our runs
    SAMPLES = K1_OUT / "samples"
    MODEL = model_call.MODEL

    sys.path.insert(0, str(K1))
    # The K-1 spike's reading of a printed amount, unchanged. ty can't see the folder added to sys.path above.
    from amounts import parse_value  # ty: ignore[unresolved-import]


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 1. Schema extraction: the VLM alone, or after Docling?

    **The question.** Reducto sells *Parse* (a document into chunks) followed by *Extract* (a JSON schema filled
    from what Parse saw). Can an open pipeline do the same? Our K-1 spike already showed Gemini 3.8 Flash reading
    a K-1 page image with no wrong values accepted. There, Docling did the parts around it: it found the K-1 page
    in a package and the attached statements. This notebook asks **how the VLM should be paired with Docling**,
    by running three pipelines on the K-1 spike's 30 documents:

    | Pipeline | Docling's part | What the model sees |
    |---|---|---|
    | **A. VLM alone** | none | the whole PDF |
    | **B. Docling text, then the model** | every page to Markdown (Tesseract on scans) | the Markdown, no image |
    | **C. Docling routing, then the VLM** | finds the form's page, and its Markdown | that page's image and Markdown |

    B is the parse-then-extract pattern of LlamaIndex, LlamaParse and Reducto itself: Reducto's docs say
    "Extract can only return what Parse sees." A is what a Gemini user does with no framework at all.

    All three use the same model (Gemini 3.8 Flash on OpenRouter, temperature 0), the K-1 spike's schemas and
    the same short review rules. They are scored by the K-1 spike's own `3_results.py`, run unchanged, so the
    numbers sit next to its README's.

    `run.sh` first runs the K-1 spike's `1_documents.py`, also unchanged, to make the 30 documents and their
    answer keys in `output/k1/`.
    """)
    return


@app.cell
def _():
    FILES = sorted(SAMPLES.glob("*.pdf"))
    if len(FILES) != 30:
        raise RuntimeError(f"expected the K-1 spike's 30 documents in {SAMPLES}, found {len(FILES)}; run ./run.sh")
    PAGES = {p.name: len(pdfium.PdfDocument(p)) for p in FILES}
    print(f"{len(FILES)} documents, {sum(PAGES.values())} pages")
    return FILES, PAGES


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Docling parses every document once

    The same settings as the K-1 spike: Tesseract for scanned pages, and table structure on. We keep each page's
    Markdown and how long Docling took. Results are saved in `output/k1/docling/`, so this runs once.
    """)
    return


@app.cell
def _(FILES):
    _options = PdfPipelineOptions(
        do_ocr=True, ocr_options=TesseractCliOcrOptions(lang=["eng"]), do_table_structure=True
    )
    _converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=_options)})
    (K1_OUT / "docling").mkdir(parents=True, exist_ok=True)
    parsed: dict[str, dict[str, Any]] = {}
    for _path in FILES:
        _saved = K1_OUT / "docling" / f"{_path.stem}.json"
        if not _saved.exists():
            _t0 = time.time()
            _doc = _converter.convert(_path).document
            _pages = [_doc.export_to_markdown(page_no=n) for n in range(1, _doc.num_pages() + 1)]
            _saved.write_text(json.dumps({"seconds": round(time.time() - _t0, 1), "pages": _pages}))
        parsed[_path.name] = json.loads(_saved.read_text())
    print(f"Docling: {sum(d['seconds'] for d in parsed.values()) / len(parsed):.1f} s per document")
    return (parsed,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The schemas, from the K-1 spike

    These are the K-1 spike's Pydantic models, copied from its `2_extraction.py` (section 2) because a marimo
    cell can't be imported: one per form, where every value carries what was printed, a bounding box and the
    model's confidence. A model call is given all four as possible answers and picks the one that fits, so the
    pipelines without Docling also have to tell which form they're reading.
    """)
    return


@app.cell
def _():
    # fmt: off
    K1_1065 = {
        "1": "Ordinary business income (loss)", "2": "Net rental real estate income (loss)",
        "3": "Other net rental income (loss)", "4a": "Guaranteed payments for services",
        "4b": "Guaranteed payments for capital", "4c": "Total guaranteed payments", "5": "Interest income",
        "6a": "Ordinary dividends", "6b": "Qualified dividends", "6c": "Dividend equivalents", "7": "Royalties",
        "8": "Net short-term capital gain (loss)", "9a": "Net long-term capital gain (loss)",
        "9b": "Collectibles (28%) gain (loss)", "9c": "Unrecaptured section 1250 gain",
        "10": "Net section 1231 gain (loss)", "11": "Other income (loss) [coded]", "12": "Section 179 deduction",
        "13": "Other deductions [coded]", "14": "Self-employment earnings (loss) [coded]", "15": "Credits [coded]",
        "16": "Foreign transactions [coded]", "17": "Alternative minimum tax (AMT) items [coded]",
        "18": "Tax-exempt income and nondeductible expenses [coded]", "19": "Distributions [coded]",
        "20": "Other information [coded]", "21": "Foreign taxes paid or accrued",
    }
    K1_LABELS = {
        "1065": K1_1065,
        "1120S": {"1": "Ordinary business income (loss)", "2": "Net rental real estate income (loss)",
                  "3": "Other net rental income (loss)", "4": "Interest income", "5a": "Ordinary dividends",
                  "5b": "Qualified dividends", "6": "Royalties", "7": "Net short-term capital gain (loss)",
                  "8a": "Net long-term capital gain (loss)", "9": "Net section 1231 gain (loss)",
                  "11": "Section 179 deduction", "12": "Other deductions [coded]", "13": "Credits [coded]",
                  "16": "Items affecting shareholder basis [coded]", "17": "Other information [coded]"},
        "1041": {"1": "Interest income", "2a": "Ordinary dividends", "2b": "Qualified dividends",
                 "3": "Net short-term capital gain", "4a": "Net long-term capital gain", "5": "Other portfolio and "
                 "nonbusiness income", "6": "Ordinary business income", "7": "Net rental real estate income",
                 "8": "Other rental income", "9": "Directly apportioned deductions [coded]",
                 "10": "Estate tax deduction", "11": "Final year deductions [coded]",
                 "13": "Credits and credit recapture [coded]", "14": "Other information [coded]"},
    }
    BROKER_LINES = ["DIV 1a", "DIV 1b", "DIV 2a", "DIV 3", "DIV 5", "DIV 7", "INT 1", "INT 3", "INT 4", "INT 8"]
    # fmt: on

    def boxes_for(form: str, year: int) -> set[str]:
        """The 1065 K-1 changed: box 4 split into 4a to 4c after 2018, and in 2021 box 16 became a checkbox and
        box 21 was added."""
        boxes = set(K1_LABELS[form])
        if form == "1065":
            boxes -= {"4a", "4b", "4c"} if year <= 2018 else set()
            boxes |= {"4"} if year <= 2018 else set()
            boxes -= {"21"} if year <= 2020 else {"16"}
        return boxes

    class Value(BaseModel):
        printed: str = Field(
            description="The value exactly as printed, keeping signs, parentheses, commas and decimals: "
            "'-27,942', '(18)', '1,629', '45,113.89', '-' for a printed dash, 'STMT', 'VARIOUS'."
        )
        bbox: list[int] = Field(description="[x0, y0, x1, y1] in 0-1000 page coordinates, tight around the value.")
        confidence: float = Field(ge=0, le=1, description="How sure you are every character is read right, 0 to 1.")

    class Row(BaseModel):
        code: str = Field(
            description="For a coded box, the code printed to the left of the amount, as printed, including any "
            "asterisk ('A', 'AH*', '*'). An empty string for a box with no codes."
        )
        value: Value

    def k1_model(form: str) -> type[BaseModel]:
        boxes = [*K1_LABELS[form], *(["4"] if form == "1065" else [])]
        row = create_model("K1Row", __base__=Row, box=(Literal[tuple(boxes)], ...))  # ty: ignore[invalid-type-form]
        return create_model(
            f"K1_{form}",
            __doc__=f"Schedule K-1 (Form {form}) as printed.",
            tax_year=(int, Field(description="The tax year printed on the form.")),
            payer_ein=(Value | None, Field(description="Part I item A: the employer identification number.")),
            payer_name=(Value | None, Field(description="Part I item B: the name only, without the address.")),
            boxes=(
                list[row],  # ty: ignore[invalid-type-form]
                Field(
                    description="Every Part III box with something printed in it. A coded box "
                    "gives one row per printed code line."
                ),
            ),
        )

    class BRow(BaseModel):
        proceeds: Value
        cost: Value
        wash: Value = Field(description="Wash sale loss disallowed")
        gain: Value = Field(description="Gain or loss")

    Brokerage1099 = create_model(  # ty: ignore[no-matching-overload]
        "Brokerage1099",
        __doc__="The summary amounts of a consolidated brokerage Form 1099.",
        **{k.replace(" ", "_"): (Value | None, Field(None, description=f"1099-{k}")) for k in BROKER_LINES},
        B_A=(BRow | None, Field(None, description="1099-B summary row: Short-term, basis reported (Box A)")),
        B_D=(BRow | None, Field(None, description="1099-B summary row: Long-term, basis reported (Box D)")),
    )
    FORMS = {"1065": k1_model("1065"), "1120S": k1_model("1120S"), "1041": k1_model("1041"), "BROKER": Brokerage1099}
    return BROKER_LINES, FORMS, K1_LABELS, boxes_for


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The prompt and the model call

    The instructions are the K-1 spike's, with the box labels of all three K-1 forms, since pipelines A and B
    don't know the form in advance. Settings are also the K-1 spike's: temperature 0, low thinking, 8,000 output
    tokens, and up to four attempts per call (`model_call.py`, which the section-parsing notebook shares). Every
    attempt's cost is OpenRouter's own figure. Answers are saved in `output/answers/`, so a re-run doesn't pay
    again; delete that folder for a fresh run.
    """)
    return


@app.cell
def _(FORMS, K1_LABELS):
    INSTRUCTIONS = "\n".join(
        [
            "You read US tax documents for a tax preparer. Report only what is printed on the page.",
            "Never compute, infer or fill in a value. Leave out boxes that are empty.",
            "Bounding boxes are [x0, y0, x1, y1] in 0-1000 coordinates relative to the page image, "
            "tight around the printed value.",
            "Set confidence below 0.9 for any value where a character is smudged, faint, cut off or ambiguous.",
        ]
    )
    PROMPT = (
        "This document holds one Schedule K-1 (Form 1065, 1120-S or 1041) or one consolidated brokerage Form 1099. "
        "Answer with the schema for that form. For a K-1, read Part III. Its boxes are:\n"
        + "\n".join(f"Form {f}: " + "; ".join(f"{b} {lbl}" for b, lbl in K1_LABELS[f].items()) for f in K1_LABELS)
        + "\nIn a coded box, report one row per printed line, with the code letter printed to the left of the "
        "amount (every line in a coded box has one), including lines whose amount is a dash and lines coded '*' "
        "with STMT. For a brokerage 1099, read the summary amounts."
    )
    _slots = asyncio.Semaphore(8)
    _forms = {model.__name__: form for form, model in FORMS.items()}

    async def ask(pipeline: str, doc: str, parts: list[Any]) -> dict[str, Any]:
        """One extraction call: the form the model chose, its typed answer, and its cost and time."""
        saved = OUT / "answers" / pipeline / f"{Path(doc).stem}.json"
        answer = await model_call.ask(saved, list(FORMS.values()), INSTRUCTIONS, [PROMPT, *parts], _slots)
        return {**answer, "form": _forms[answer["type"]]}

    return (ask,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The three pipelines

    Each pipeline is only the list of things it hands the model. **C** routes the way the K-1 spike did: the
    form's page is the first one whose Docling text says "share of current year" (a K-1) or "consolidated form
    1099"; when Docling can't tell, as on some bad scans, it takes page 1.
    """)
    return


@app.cell
def _(parsed):
    def page_png(path: Path, index: int) -> bytes:
        png = OUT / "pages" / f"{path.stem}-p{index + 1}.png"
        if not png.exists():
            png.parent.mkdir(parents=True, exist_ok=True)
            pdfium.PdfDocument(path)[index].render(scale=200 / 72).to_pil().convert("RGB").save(png)
        return png.read_bytes()

    def form_page(pages: list[str]) -> int:
        for i, md in enumerate(pages):
            if re.search(r"share\s+of\s+current\s+year|consolidated\s+form\s+1099", md, re.I):
                return i
        return 0

    def markdown_of(pages: list[str]) -> str:
        return "\n\n".join(f"--- page {i + 1} ---\n{md}" for i, md in enumerate(pages))

    PIPELINES = {
        "a-vlm-alone": (
            "A. VLM alone, whole PDF",
            lambda p: [BinaryContent(p.read_bytes(), media_type="application/pdf")],
        ),
        "b-docling-text": (
            "B. Docling Markdown, then the model (text only)",
            lambda p: ["Docling's Markdown of the document:\n\n" + markdown_of(parsed[p.name]["pages"])],
        ),
        "c-docling-page": (
            "C. Docling finds the page, the VLM reads its image and Markdown",
            lambda p: [
                "Docling's Markdown of the page, for reference:\n\n"
                + parsed[p.name]["pages"][form_page(parsed[p.name]["pages"])][:8000],
                BinaryContent(page_png(p, form_page(parsed[p.name]["pages"])), media_type="image/png"),
            ],
        ),
    }
    return (PIPELINES,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## From an answer to scored values

    Each answer becomes the K-1 spike's list of values, so its scoring can read it. A value goes to review when
    the model's confidence is below 0.9, it's `STMT`, it isn't a well-formed amount, a coded row has no code, the
    form has no such box, or the box is reported twice. These are the K-1 spike's per-value rules. Its
    cross-checks, page-level check and statement reading are left out, the same for all three pipelines, so the
    difference between them is the pipeline. The K-1 README's Gemini row, with every rule, is the reference.
    """)
    return


@app.cell
def _(BROKER_LINES, K1_LABELS, boxes_for):
    def to_fields(answer: dict[str, Any]) -> list[dict[str, Any]]:
        form, out, fields = answer["form"], answer["output"], []
        raw: list[tuple[str, dict[str, Any], list[str]]] = []
        if form == "BROKER":
            raw += [(k, out[k.replace(" ", "_")], []) for k in BROKER_LINES if out.get(k.replace(" ", "_"))]
            for term in ("A", "D"):
                raw += [(f"B {term} {c}", v, []) for c, v in (out.get(f"B_{term}") or {}).items()]
        else:
            raw += [(k, out[k], []) for k in ("payer_ein", "payer_name") if out.get(k)]
            valid = boxes_for(form, out["tax_year"])
            for r in out["boxes"]:
                reasons = [] if r["box"] in valid else [f"Form {form} has no box {r['box']}"]
                key = r["box"]
                if "[coded]" in K1_LABELS[form].get(r["box"], ""):
                    code = r["code"].replace(" ", "").upper()
                    key, reasons = f"{r['box']} {code or '?'}", reasons + ([] if code else ["coded row, no code"])
                raw.append((key, r["value"], reasons))
        for key, v, reasons in raw:
            payer = key.startswith("payer")
            value, kind = (v["printed"].split("\n")[0].strip(), "text") if payer else parse_value(v["printed"])
            reasons += [f"confidence {v['confidence']:.2f}"] if v["confidence"] < 0.9 else []
            reasons += ["on the attached statement"] if kind == "statement" else []
            reasons += (
                [f"can't read '{v['printed']}'"]
                if kind == "unreadable" or (kind == "text" and not (payer or key[:3] == "16 "))
                else []
            )
            if any(f["key"] == key for f in fields):
                key, reasons = f"{key} (again)", ["reported twice", *reasons]
            fields.append(
                {
                    "key": key,
                    "label": key,
                    "value": value,
                    "raw": v["printed"],
                    "page": 0,
                    "bbox": None,
                    "confidence": round(v["confidence"] * 100),
                    "reasons": reasons,
                    "status": "review" if reasons else "accepted",
                }
            )
        return fields

    return (to_fields,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Every pipeline reads every document

    The three pipelines run side by side. A document that fails every attempt is listed as failed and the run
    goes on. Each run is written in the K-1 spike's format to `output/k1/<pipeline>/extracted.json`.
    """)
    return


@app.cell
async def _(FILES, PAGES, PIPELINES, ask, parsed, to_fields):
    async def read(name: str, path: Path) -> dict[str, Any] | None:
        try:
            answer = await ask(name, path.name, PIPELINES[name][1](path))
        except Exception as e:
            print(f"{name} {path.name}: failed: {type(e).__name__}: {str(e)[:200]}")
            return None
        docling = 0.0 if name.startswith("a-") else parsed[path.name]["seconds"]
        return {
            "file": path.name,
            "form": answer["form"],
            "page_review": None,
            "pages": {},
            "fields": to_fields(answer),
            "cost_usd": round(answer["usd"], 6),
            "cost_missing_responses": 0,
            "failed_attempts": answer["failed_attempts"],
            "model_seconds": round(answer["seconds"], 1),
            "docling_seconds": docling,
            "seconds": round(answer["seconds"] + docling, 1),
            "pdf_pages": PAGES[path.name],
        }

    async def run(name: str) -> dict[str, Any]:
        docs = await asyncio.gather(*(read(name, p) for p in FILES))
        result = {
            "name": name,
            "label": PIPELINES[name][0],
            "description": f"{PIPELINES[name][0]}, {MODEL}",
            "model": MODEL,
            "documents": [d for d in docs if d],
            "failed_documents": [
                {"file": p.name, "error": "failed"} for p, d in zip(FILES, docs, strict=True) if not d
            ],
        }
        (K1_OUT / name).mkdir(parents=True, exist_ok=True)
        (K1_OUT / name / "extracted.json").write_text(json.dumps(result, indent=1))
        return result

    extraction_runs = await asyncio.gather(*(run(n) for n in PIPELINES))
    (K1_OUT / "runs.json").write_text(json.dumps(list(PIPELINES)))
    return (extraction_runs,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring, with the K-1 spike's notebook

    `3_results.py` from the K-1 spike runs unchanged on these runs, in the K-1 spike's own pinned environment.
    It writes `metrics.json` for each run and `output/k1/comparison.md`. "Wrong but accepted" counts a wrong value
    accepted without review, and a box on the answer key the run never reported, since that reads as blank.
    """)
    return


@app.cell
def _(extraction_runs):
    _env = {**os.environ, "K1_OUTPUT_DIR": str(K1_OUT), "UV_PROJECT_ENVIRONMENT": str(HERE / ".venv-k1")}
    _env.pop("K1_SCREENSHOTS", None)
    _done = subprocess.run(
        ["uv", "run", "--frozen", "--project", str(K1), str(K1 / "3_results.py")],
        env=_env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if _done.returncode != 0:
        raise RuntimeError(f"the K-1 spike's 3_results.py failed:\n{_done.stderr[-3000:]}")
    metrics = {r["name"]: json.loads((K1_OUT / r["name"] / "metrics.json").read_text()) for r in extraction_runs}
    return (metrics,)


@app.cell
def _(extraction_runs, metrics):
    _rows = [
        "| Pipeline | Values right | Accepted without review | Wrong but accepted | Sent to review | "
        "Cost per document | Cost per page | Seconds per document (Docling + model) | Failed documents |",
        "|---|---|---|---|---|---|---|---|---|",
        "| *K-1 spike, Gemini 3.8 Flash (from its README, run 2026-10-18, all its review rules)* | *676 of 676* "
        "| *652* | *0* | *24* | *$0.0064* | | *8.3 + 11.8* | *0* |",
    ]
    for _run in extraction_runs:
        _m, _a, _docs = metrics[_run["name"]], metrics[_run["name"]]["all"], _run["documents"]
        _pages = sum(d["pdf_pages"] for d in _docs)
        _docling = sum(d["docling_seconds"] for d in _docs) / len(_docs)
        _rows.append(
            f"| {_run['label']} | {_a['correct']} of {_a['boxes_checked']} | {_a['accepted']} "
            f"| {_a['silent_errors']} | {_a['sent_to_review']} | ${_m['cost_usd_total'] / len(_docs):.4f} "
            f"| ${_m['cost_usd_total'] / _pages:.4f} | {_docling:.1f} + {_m['model_seconds_per_document']} "
            f"| {len(_m['failed_documents'])} |"
        )
    schema_table = "\n".join(_rows)
    (OUT / "schema_extraction.md").write_text(schema_table + "\n")
    print(schema_table)
    mo.md("## Results\n\n" + schema_table)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Where each pipeline went wrong

    Every wrong value that was accepted, grouped by the kind of document, from the K-1 scoring's per-source
    breakdown. `output/k1/comparison.md` has the full list of boxes.
    """)
    return


@app.cell
def _(extraction_runs, metrics):
    _lines = ["| Pipeline | Kind of document | Boxes | Wrong but accepted |", "|---|---|---|---|"]
    for _run in extraction_runs:
        for _source, _s in metrics[_run["name"]]["by_source"].items():
            if _s["silent_errors"]:
                _lines.append(f"| {_run['label']} | {_source} | {_s['boxes_checked']} | {_s['silent_errors']} |")
        _boxes = metrics[_run["name"]]["all"]["silent_error_boxes"]
        print(f"{_run['name']}: {'; '.join(_boxes[:12]) or 'none'}{' …' if len(_boxes) > 12 else ''}")
    (OUT / "schema_failures.md").write_text("\n".join(_lines) + "\n")
    mo.md("\n".join(_lines))
    return


if __name__ == "__main__":
    app.run()
