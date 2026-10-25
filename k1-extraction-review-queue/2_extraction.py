import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import json
    import os
    import re
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from typing import Any, Literal

    import marimo as mo
    import modal
    import pypdfium2 as pdfium
    from docling.datamodel import vlm_model_specs
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions, VlmPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.pipeline.vlm_pipeline import VlmPipeline
    from pydantic import AnyUrl, BaseModel, Field, TypeAdapter, create_model
    from pydantic_ai import Agent, BinaryContent, capture_run_messages
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models import infer_model
    from pydantic_ai.models.openrouter import OpenRouterModelSettings
    from pydantic_ai.settings import ModelSettings

    import ocr_modal
    from amounts import parse_value

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("K1_OUTPUT_DIR", HERE / "output"))
    SAMPLES = OUT / "samples"
    Fields = list[dict[str, Any]]


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 2. Reading every document with every model

    The second of three notebooks. `1_documents.py` made the 30 documents in `output/samples/`. This one reads each
    of them with five vision-language models, a pair of two of them, and two OCR models, and applies the review rules.
    It writes each run's values to `output/<run>/extracted.json`, and `3_results.py` scores them.
    """)
    return


@app.cell
def _():
    FILES = sorted(SAMPLES.glob("*.pdf"))
    if len(FILES) != 30:
        raise RuntimeError(f"expected the 30 documents from 1_documents.py in {SAMPLES}, found {len(FILES)}")
    return (FILES,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. Docling reads every page once

    Docling runs on CPU, with Tesseract for scanned pages, and gives us each page's text and a Markdown version with
    tables. We use it three ways. It finds the K-1 page or the 1099 summary page. It finds the supplemental statement
    pages and their Box / Description / Amount tables. And it counts the amounts printed on a page, which is an
    independent check on how many values a model should have read. The layout is saved under `output/layout/`, so it
    runs once.
    """)
    return


@app.cell
def _(FILES):
    def read_layout(converter: DocumentConverter, path: Path) -> dict[str, Any]:
        t0 = time.time()
        result = converter.convert(path)
        pages = []
        for page in result.pages:
            assert page.parsed_page is not None and page.size is not None, f"{path.name}: Docling parsed no page"
            cells = page.parsed_page.word_cells or page.parsed_page.textline_cells
            words = [(word, cell.from_ocr) for cell in cells for word in cell.text.split()]
            markdown = result.document.export_to_markdown(page_no=page.page_no)
            pages.append(
                {
                    "index": page.page_no - 1,
                    "width": page.size.width,
                    "height": page.size.height,
                    "ocr": any(ocr for _w, ocr in words),
                    "text": " ".join(w for w, _ocr in words),
                    "markdown": markdown,
                }
            )
        return {"file": path.name, "seconds": round(time.time() - t0, 1), "pages": pages}

    _options = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=TesseractCliOcrOptions(lang=["eng"]),
        do_table_structure=True,
        generate_parsed_pages=True,
    )
    _converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=_options)})
    (OUT / "layout").mkdir(exist_ok=True)
    layouts: dict[str, dict[str, Any]] = {}
    for _path in FILES:
        _saved = OUT / "layout" / f"{_path.stem}.json"
        if not _saved.exists():
            _saved.write_text(json.dumps(read_layout(_converter, _path)))
        layouts[_path.name] = json.loads(_saved.read_text())
    print(f"Docling: {sum(d['seconds'] for d in layouts.values()) / len(layouts):.1f} s per document")
    return (layouts,)


@app.cell
def _(FILES):
    # Every page is rendered once, before any model runs, so rendering doesn't hold up the model calls and their
    # timings: the 200-dpi image a model sees, and the 150-dpi image the review screen shows.
    (OUT / "pages").mkdir(exist_ok=True)
    for _path in FILES:
        for _i, _page in enumerate(pdfium.PdfDocument(_path)):
            _png = OUT / "pages" / f"{_path.stem}-p{_i + 1}.png"
            if not _png.exists():
                _page.render(scale=200 / 72).to_pil().convert("RGB").save(_png)
                _page.render(scale=150 / 72).to_pil().convert("L").save(_png.with_suffix(".jpg"), quality=72)

    def page_png(path: Path, index: int) -> bytes:
        return (OUT / "pages" / f"{path.stem}-p{index + 1}.png").read_bytes()

    def page_image(path: Path, index: int) -> str:
        """Where the review screen in a run's folder finds the page."""
        return f"../pages/{path.stem}-p{index + 1}.jpg"

    return page_image, page_png


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. What each model is asked for

    The K-1 page (or the 1099 summary page) goes to the model as an image at 200 dpi. Pydantic AI asks for a typed
    result: one Pydantic model per form, where every value carries what was printed, its bounding box and the model's
    own confidence. The boxes each form has, and their printed labels, are below; the labels go into the prompt. In a
    coded box the code letter is a required field: when it was optional, GLM and Qwen 3.8 27B left it out of every row.
    """)
    return


@app.cell
def _():
    # fmt: off
    # Part III of Schedule K-1 (Form 1065). "coded" boxes hold rows of a code letter and an amount.
    K1_1065 = {
        "1": ("Ordinary business income (loss)", "amount"), "2": ("Net rental real estate income (loss)", "amount"),
        "3": ("Other net rental income (loss)", "amount"), "4a": ("Guaranteed payments for services", "amount"),
        "4b": ("Guaranteed payments for capital", "amount"), "4c": ("Total guaranteed payments", "amount"),
        "5": ("Interest income", "amount"), "6a": ("Ordinary dividends", "amount"),
        "6b": ("Qualified dividends", "amount"), "6c": ("Dividend equivalents", "amount"), "7": ("Royalties", "amount"),
        "8": ("Net short-term capital gain (loss)", "amount"), "9a": ("Net long-term capital gain (loss)", "amount"),
        "9b": ("Collectibles (28%) gain (loss)", "amount"), "9c": ("Unrecaptured section 1250 gain", "amount"),
        "10": ("Net section 1231 gain (loss)", "amount"), "11": ("Other income (loss)", "coded"),
        "12": ("Section 179 deduction", "amount"), "13": ("Other deductions", "coded"),
        "14": ("Self-employment earnings (loss)", "coded"), "15": ("Credits", "coded"),
        "16": ("Foreign transactions", "coded"), "17": ("Alternative minimum tax (AMT) items", "coded"),
        "18": ("Tax-exempt income and", "coded"), "19": ("Distributions", "coded"),
        "20": ("Other information", "coded"), "21": ("Foreign taxes paid or accrued", "amount"),
    }
    K1_LABELS = {
        "1120S": {"1": ("Ordinary business income (loss)", "amount"),
                  "2": ("Net rental real estate income (loss)", "amount"),
                  "3": ("Other net rental income (loss)", "amount"), "4": ("Interest income", "amount"),
                  "5a": ("Ordinary dividends", "amount"), "5b": ("Qualified dividends", "amount"),
                  "6": ("Royalties", "amount"), "7": ("Net short-term capital gain (loss)", "amount"),
                  "8a": ("Net long-term capital gain (loss)", "amount"),
                  "9": ("Net section 1231 gain (loss)", "amount"), "11": ("Section 179 deduction", "amount"),
                  "12": ("Other deductions", "coded"), "13": ("Credits", "coded"),
                  "16": ("Items affecting shareholder basis", "coded"), "17": ("Other information", "coded")},
        "1041": {"1": ("Interest income", "amount"), "2a": ("Ordinary dividends", "amount"),
                 "2b": ("Qualified dividends", "amount"), "3": ("Net short-term capital gain", "amount"),
                 "4a": ("Net long-term capital gain", "amount"), "5": ("nonbusiness income", "amount"),
                 "6": ("Ordinary business income", "amount"), "7": ("Net rental real estate income", "amount"),
                 "8": ("Other rental income", "amount"), "9": ("Directly apportioned deductions", "coded"),
                 "10": ("Estate tax deduction", "amount"), "11": ("Final year deductions", "coded"),
                 "13": ("Credits and credit recapture", "coded"), "14": ("Other information", "coded")},
    }
    HEADER_LABELS = {
        "1065": ("Partnership's employer identification number",
                 "Partnership's name, address, city, state, and ZIP code"),
        "1120S": ("Corporation's employer identification number",
                  "Corporation's name, address, city, state, and ZIP code"),
        "1041": ("Estate's or trust's employer identification number", "Estate's or trust's name"),
    }
    BROKER_LINES = {"DIV 1a": "1a Total ordinary dividends", "DIV 1b": "1b Qualified dividends",
                    "DIV 2a": "2a Total capital gain distributions", "DIV 3": "3 Nondividend distributions",
                    "DIV 5": "5 Section 199A dividends", "DIV 7": "7 Foreign tax paid", "INT 1": "1 Interest income",
                    "INT 3": "3 Interest on U.S. Treasury obligations", "INT 4": "4 Federal income tax withheld",
                    "INT 8": "8 Tax-exempt interest"}
    BROKER_ROWS = {"A": "Short-term, basis reported (Box A)", "D": "Long-term, basis reported (Box D)"}
    B_COLS = ["proceeds", "cost", "wash", "gain"]
    # fmt: on

    def k1_labels(form: str, year: int) -> dict[str, tuple[str, str]]:
        """The boxes a form has. The 1065 K-1 changed: box 4 split into 4a to 4c after 2018, and in 2021 box 16
        became the Schedule K-3 checkbox and box 21 was added."""
        if form != "1065":
            return K1_LABELS[form]
        labels = dict(K1_1065)
        if year <= 2018:
            for k in ("4a", "4b", "4c"):
                del labels[k]
            labels["4"] = ("Guaranteed payments", "amount")
        del labels["21" if year <= 2020 else "16"]
        return labels

    return BROKER_LINES, BROKER_ROWS, B_COLS, HEADER_LABELS, K1_1065, K1_LABELS, k1_labels


@app.cell
def _(K1_1065, K1_LABELS):
    class Value(BaseModel):
        printed: str = Field(
            description="The value exactly as printed, keeping signs, parentheses, commas and decimals: "
            "'-27,942', '(18)', '1,629', '45,113.89', '-' for a printed dash, 'STMT', 'VARIOUS'."
        )
        bbox: list[int] = Field(
            description="Tight box around the printed value only (not its label or code letter): "
            "[x0, y0, x1, y1] in 0-1000 coordinates relative to the page image."
        )
        confidence: float = Field(
            ge=0, le=1, description="How sure you are that every character is read correctly, 0 to 1."
        )

    class Row(BaseModel):
        code: str = Field(
            description="For a coded box, the code printed to the left of the amount, as printed, "
            "including any asterisk ('A', 'AH*', '*'). An empty string for a box with no codes."
        )
        value: Value

    def k1_model(form: str, boxes: list[str]) -> type[BaseModel]:
        box = Field(description="The box number printed on the form, e.g. '1', '6a', '20'.")
        row = create_model("K1Row", __base__=Row, box=(Literal[tuple(boxes)], box))  # ty: ignore[invalid-type-form]
        return create_model(
            f"K1_{form}",
            __doc__=f"Schedule K-1 (Form {form}) as printed.",
            tax_year=(int, Field(description="The tax year printed on the form.")),
            payer_ein=(Value | None, Field(description="Part I item A: the employer identification number.")),
            payer_name=(Value | None, Field(description="Part I item B: the name only, without the address lines.")),
            boxes=(
                list[row],  # ty: ignore[invalid-type-form]
                Field(
                    description="Every Part III box that has something printed in it. "
                    "A coded box gives one row per printed code line."
                ),
            ),
        )

    K1_MODELS = {
        "1065": k1_model("1065", [*K1_1065, "4"]),
        "1120S": k1_model("1120S", list(K1_LABELS["1120S"])),
        "1041": k1_model("1041", list(K1_LABELS["1041"])),
    }

    class BRow(BaseModel):
        proceeds: Value
        cost: Value
        wash: Value = Field(description="Wash sale loss disallowed")
        gain: Value = Field(description="Gain or loss")

    class Brokerage1099(BaseModel):
        """The summary page of a consolidated brokerage Form 1099."""

        DIV_1a: Value | None = Field(None, description="1099-DIV 1a Total ordinary dividends")
        DIV_1b: Value | None = Field(None, description="1099-DIV 1b Qualified dividends")
        DIV_2a: Value | None = Field(None, description="1099-DIV 2a Total capital gain distributions")
        DIV_3: Value | None = Field(None, description="1099-DIV 3 Nondividend distributions")
        DIV_5: Value | None = Field(None, description="1099-DIV 5 Section 199A dividends")
        DIV_7: Value | None = Field(None, description="1099-DIV 7 Foreign tax paid")
        INT_1: Value | None = Field(None, description="1099-INT 1 Interest income")
        INT_3: Value | None = Field(None, description="1099-INT 3 Interest on U.S. Treasury obligations")
        INT_4: Value | None = Field(None, description="1099-INT 4 Federal income tax withheld")
        INT_8: Value | None = Field(None, description="1099-INT 8 Tax-exempt interest")
        B_A: BRow | None = Field(None, description="1099-B summary row: Short-term, basis reported (Box A)")
        B_D: BRow | None = Field(None, description="1099-B summary row: Long-term, basis reported (Box D)")

    class StatementLine(BaseModel):
        code: str = Field(description="The box and code as the statement prints it, e.g. '20AH', '11A1'.")
        description: str
        printed: str = Field(description="The amount exactly as printed.")
        bbox: list[int] = Field(description="Tight box around the amount, [x0, y0, x1, y1] in 0-1000 page coordinates.")

    class StatementLines(BaseModel):
        """Lines of a K-1 supplemental statement that belong to one box."""

        lines: list[StatementLine]

    FormQuestion = Literal[
        "Schedule K-1 (Form 1065)",
        "Schedule K-1 (Form 1120-S)",
        "Schedule K-1 (Form 1041)",
        "Consolidated brokerage Form 1099",
        "other",
    ]
    return Brokerage1099, FormQuestion, K1_MODELS, StatementLines


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Calling a model.** Each model is named by a Pydantic AI model string, such as
    `openrouter:google/gemini-3.8-flash`. A model from another provider is a different string and needs no code
    change. Models run at temperature 0, and thinking models at low effort: reading a form doesn't need long reasoning,
    and at the default they spent their whole 8,000-token output budget thinking. Each call gets six attempts, and
    Pydantic AI retries malformed output twice within each. **Every attempt is paid for and counted**, including one
    that failed after the model answered. The cost is the provider's own figure (OpenRouter reports it), or else
    Pydantic AI's price table. A response with no known cost is counted, and its document is left out of the average.

    Each answer is saved under `output/answers/`, with its cost and time. You can re-run this notebook, or open it in
    marimo, without calling the models again. Delete that folder for a fresh run.
    """)
    return


@app.cell
def _():
    INSTRUCTIONS = "\n".join(
        [
            "You read US tax documents for a tax preparer. Report only what is printed on the page.",
            "Never compute, infer or fill in a value. Leave out boxes that are empty.",
            "Bounding boxes are [x0, y0, x1, y1] in 0-1000 coordinates relative to the page image, "
            "tight around the printed value.",
            "Set confidence below 0.9 for any value where a character is smudged, faint, cut off or ambiguous.",
        ]
    )
    ATTEMPTS = 6

    def response_cost(m: ModelResponse) -> float | None:
        if (m.provider_details or {}).get("cost") is not None:
            return float((m.provider_details or {})["cost"])
        try:
            return float(m.cost().total_price)
        except LookupError:
            return None

    class Runner:
        """One model: asks it for typed answers, counts the cost of every attempt, and saves each answer."""

        def __init__(self, model_name: str, answers: Path, overrides: dict[str, Any] | None = None) -> None:
            self.model = infer_model(model_name)
            settings = {"temperature": 0, "max_tokens": 8000, "thinking": "low", **(overrides or {})}
            self.settings: ModelSettings = (
                OpenRouterModelSettings(**settings, openrouter_usage={"include": True})  # OpenRouter reports cost
                if model_name.startswith("openrouter:")
                else ModelSettings(**settings)
            )
            self.answers = answers
            answers.mkdir(parents=True, exist_ok=True)
            self.slots = asyncio.Semaphore(6)
            self.cost: dict[str, dict[str, float]] = {}
            self.served_by: set[str] = set()  # the hosts OpenRouter sent the calls to

        def spent(self, doc: str) -> dict[str, float]:
            return self.cost.setdefault(doc, {"usd": 0.0, "cost_missing": 0, "failed_attempts": 0, "seconds": 0.0})

        async def ask(self, doc: str, call: str, output_type: Any, prompt: str, images: list[bytes]) -> Any:
            saved_path = self.answers / f"{Path(doc).stem}.json"
            saved = json.loads(saved_path.read_text()) if saved_path.exists() else {}
            adapter = TypeAdapter(output_type)
            if call not in saved:
                output, cost, hosts = await self.call(output_type, prompt, images)
                saved[call] = {"output": adapter.dump_python(output, mode="json"), "cost": cost, "served_by": hosts}
                saved_path.write_text(json.dumps(saved, indent=1))
            for k, v in saved[call]["cost"].items():
                self.spent(doc)[k] += v
            self.served_by.update(saved[call].get("served_by", []))
            return adapter.validate_python(saved[call]["output"])

        async def call(
            self, output_type: Any, prompt: str, images: list[bytes]
        ) -> tuple[Any, dict[str, float], list[str]]:
            agent = Agent(
                self.model, output_type=output_type, instructions=INSTRUCTIONS, retries=2, model_settings=self.settings
            )
            parts = [prompt] + [BinaryContent(png, media_type="image/png") for png in images]
            cost = {"usd": 0.0, "cost_missing": 0, "failed_attempts": 0, "seconds": 0.0}
            hosts: set[str] = set()
            async with self.slots:
                for attempt in range(ATTEMPTS):
                    t0, error = time.time(), None
                    with capture_run_messages() as messages:
                        try:
                            output = (await agent.run(parts)).output
                        except Exception as e:  # rate limits, network errors, malformed output after retries
                            error = e
                    for m in (m for m in messages if isinstance(m, ModelResponse)):
                        usd = response_cost(m)
                        cost["usd"] += usd or 0.0
                        cost["cost_missing"] += usd is None
                        hosts.add((m.provider_details or {}).get("downstream_provider") or "unknown")
                    cost["seconds"] += time.time() - t0
                    if error is None:
                        return output, cost, sorted(hosts)
                    cost["failed_attempts"] += 1
                    if attempt == ATTEMPTS - 1:
                        raise error
                    print(f"  retrying after {type(error).__name__}: {str(error)[:120]}")
                    await asyncio.sleep(15 * (attempt + 1))
            raise AssertionError("unreachable")

    return (Runner,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. When a value goes to review

    A value goes to the review queue when:

    - the model's confidence is below 0.9;
    - the amount is on an attached statement (`STMT`);
    - it isn't a well-formed amount;
    - a coded row has no code letter;
    - the form has no such box, or the same box is reported twice;
    - or a cross-check fails: qualified dividends above ordinary dividends, 4a + 4b ≠ 4c, or a 1099-B row where
      proceeds − cost + wash sale ≠ gain.

    **The whole page goes to review** when the model read nothing on it, wasn't sure of any value it read, or read too
    few values for the amounts Docling sees printed on it (when there are at least 8). Without this, every box the
    model left out would count as an accepted blank. "Too few" depends on the form. A K-1 prints many amounts the
    schema doesn't ask for, such as the capital account, so a K-1 answer is near-empty only below a quarter of the
    printed amounts. A 1099 summary page prints only the 18 amounts the schema asks for, so there the line is three
    quarters. Docling sees 15 to 17 amounts on each made-up summary page, and a full answer has 16 to 18 values. In
    an earlier run, GLM's sparse answers had 4 to 8.
    """)
    return


@app.cell
def _(BROKER_LINES, BROKER_ROWS, B_COLS, HEADER_LABELS, K1_1065):
    CONFIDENCE_MIN = 0.9

    def code_of(t: str) -> str:
        """Codes are capital letters; a model sometimes doubles a letter in the other case ("Cc")."""
        m = re.fullmatch(r"([A-Za-z])\1\*?", t, re.I)
        if m and len(t.rstrip("*")) == 2 and t[0] != t[1]:
            return m.group(1).upper() + ("*" if t.endswith("*") else "")
        return t.upper()

    def same_text(a: str | None, b: str | None) -> bool:
        return re.sub(r"[^A-Z0-9]", "", (a or "").upper()) == re.sub(r"[^A-Z0-9]", "", (b or "").upper())

    def agrees(a: str, b: str) -> bool:
        """Two readings say the same: the same value, or the same digits and sign."""
        (va, ka), (vb, kb) = parse_value(a), parse_value(b)
        if ka == kb == "text":
            return same_text(a, b)
        if va is not None and va == vb:
            return True
        digits = re.sub(r"\D", "", a)
        negative = [bool(re.match(r"^\s*[(\-]", t)) for t in (a, b)]
        return bool(digits) and digits == re.sub(r"\D", "", b) and negative[0] == negative[1]

    def value_reasons(v: Any, allow_text: bool) -> list[str]:
        kind, reasons = parse_value(v.printed)[1], []
        if kind == "unreadable" or (kind == "text" and not allow_text):
            reasons.append(f"can't read '{v.printed}' as an amount")
        if kind == "statement":
            reasons.append("amount is on the attached statement")
        if v.confidence < CONFIDENCE_MIN:
            reasons.append(f"the model's confidence is {v.confidence:.2f}")
        return reasons

    def answer_fields(form: str, labels: dict[str, tuple[str, str]], out: Any, page: int) -> Fields:
        """The model's answer as values, each with its reasons for review."""
        fields: Fields = []

        def add(key: str, label: str, v: Any, reasons: list[str]) -> None:
            payer = key.startswith("payer")
            if not payer:
                reasons += value_reasons(v, allow_text=key.startswith("16 "))
            elif v.confidence < CONFIDENCE_MIN:
                reasons.append(f"the model's confidence is {v.confidence:.2f}")
            if any(f["key"] == key for f in fields):
                reasons.insert(0, f"{key} appears twice")
                key = f"{key} (again)"
            value = v.printed.split("\n")[0].strip() if payer else parse_value(v.printed)[0]
            bbox = [round(b / 1000, 4) for b in v.bbox] if len(v.bbox) == 4 else None
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "value": value,
                    "raw": v.printed,
                    "page": page,
                    "bbox": bbox,
                    "confidence": round(v.confidence * 100),
                    "reasons": reasons,
                }
            )

        if form == "BROKER":
            for key, label in BROKER_LINES.items():
                if (v := getattr(out, key.replace(" ", "_"))) is not None:
                    add(key, label, v, [])
            for term, label in BROKER_ROWS.items():
                for col in B_COLS if (row := getattr(out, f"B_{term}")) is not None else []:
                    add(f"B {term} {col}", f"1099-B {label}: {col}", getattr(row, col), [])
            broker_crosschecks(fields)
            return fields
        for key, label in zip(("payer_ein", "payer_name"), HEADER_LABELS[form], strict=True):
            if getattr(out, key) is not None:
                add(key, label, getattr(out, key), [])
        for r in out.boxes:
            label, kind = labels.get(r.box, (K1_1065.get(r.box, ("", ""))[0], "amount"))
            reasons, key = ([] if r.box in labels else [f"Form {form} for this year has no box {r.box}"]), r.box
            if kind == "coded":
                code = code_of(r.code.strip().replace(" ", "")) if r.code.strip() else "?"
                reasons += ["the model gave no code for a row in a coded box"] if code == "?" else []
                key, label = f"{r.box} {code}", f"{label}, code {code}"
            add(key, label, r.value, reasons)
        k1_crosschecks(fields, form)
        return fields

    def number(fields: Fields, key: str) -> float | None:
        f = next((f for f in fields if f["key"] == key), None)
        return f["value"] if f and isinstance(f["value"], int | float) else None

    def flag(fields: Fields, keys: list[str], reason: str) -> None:
        for f in (f for f in fields if f["key"] in keys):
            f["reasons"].append(reason)

    def k1_crosschecks(fields: Fields, form: str) -> None:
        total, part = {"1065": ("6a", "6b"), "1120S": ("5a", "5b"), "1041": ("2a", "2b")}[form]
        t, p = number(fields, total), number(fields, part)
        if t is not None and p is not None and p > t:
            flag(fields, [total, part], f"qualified dividends ({part}) exceed ordinary dividends ({total})")
        if p is not None and not any(f["key"] == total for f in fields):
            flag(fields, [part], f"qualified dividends ({part}) present but ordinary dividends ({total}) blank")
        keys = ["4a", "4b", "4c"]
        if form == "1065" and any(f["key"] in keys for f in fields):
            a, b, c = (number(fields, k) or 0 for k in keys)
            if a + b != c:
                flag(fields, keys, "4a + 4b doesn't equal 4c")

    def broker_crosschecks(fields: Fields) -> None:
        a, q = number(fields, "DIV 1a"), number(fields, "DIV 1b")
        if a is not None and q is not None and q > a:
            flag(fields, ["DIV 1a", "DIV 1b"], "qualified dividends (1b) exceed ordinary dividends (1a)")
        for term in BROKER_ROWS:
            keys = [f"B {term} {c}" for c in B_COLS]
            vals = [number(fields, k) for k in keys]
            if None in vals:
                continue
            p, c, w, g = (v or 0.0 for v in vals)
            if abs(p - c + w - g) > 0.011:
                flag(fields, keys, "proceeds - cost + wash sale doesn't equal gain or loss")

    # An amount as printed: with a thousands comma or cents, so box numbers and years don't count. Zeros don't
    # count either, since an empty box can print as 0.00.
    PRINTED_AMOUNT = re.compile(r"^[($-]*(\d{1,3}(,\d{3})+(\.\d\d)?|\d+\.\d\d)\)?$")
    MIN_READ_SHARE = {"BROKER": 0.75, "K-1": 0.25}

    def page_review(page_text: str, fields: Fields, form: str) -> str | None:
        """Why the whole page should go to review, or None."""
        read = [f for f in fields if f["raw"] and not f["key"].startswith("payer") and f["key"] != "page"]
        if not read:
            return "the model read nothing on this page"
        printed = sum(1 for w in page_text.split() if PRINTED_AMOUNT.match(w) and re.search(r"[1-9]", w))
        if printed >= 8 and len(read) < printed * MIN_READ_SHARE["BROKER" if form == "BROKER" else "K-1"]:
            values = f"{len(read)} value" + ("" if len(read) == 1 else "s")
            return f"the model read only {values} on a page that shows about {printed} amounts"
        if all(f["reasons"] for f in read):
            return "the model wasn't sure of any value on this page, so a box it left out may not be blank"
        return None

    def whole_page(page: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "key": "page",
            "label": "The whole page",
            "value": None,
            "raw": "",
            "page": page["index"],
            "bbox": None,
            "confidence": 0,
            "reasons": [reason],
        }

    def finish(fields: Fields, page: dict[str, Any], form: str) -> str | None:
        """Add the whole-page check and set each value's status."""
        reason = page_review(page["text"], fields, form)
        if reason and not any(f["key"] == "page" for f in fields):
            fields.append(whole_page(page, reason))
        for f in fields:
            f["status"] = "review" if f["reasons"] else "accepted"
        return reason

    return agrees, answer_fields, finish, same_text, whole_page


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. Reading a document

    For each document, we find the K-1 or 1099 page from Docling's text. On a bad scan Docling sometimes can't tell,
    so the model is asked which form it is. The model reads the page, and its answer becomes values with their reasons
    for review. For each `STMT` amount, the model reads the statement page and lists that box's lines. The reviewer
    sees those lines as a suggestion, each marked by whether Docling's table has the same code and amount. The value
    stays in the queue.
    """)
    return


@app.cell
def _(
    Brokerage1099,
    FormQuestion,
    K1_MODELS,
    StatementLines,
    answer_fields,
    finish,
    k1_labels,
    layouts,
    page_png,
    page_image,
):
    FORM_ANSWERS = {
        "Schedule K-1 (Form 1065)": "1065",
        "Schedule K-1 (Form 1120-S)": "1120S",
        "Schedule K-1 (Form 1041)": "1041",
        "Consolidated brokerage Form 1099": "BROKER",
    }

    def k1_kind(text: str) -> str | None:
        t = re.sub(r"[^a-z0-9%()]", "", text.lower())
        for form, who in (("1120S", "shareholders"), ("1041", "beneficiarys"), ("1065", "partners")):
            if f"{who}shareofcurrentyear" in t:
                return form
        return None

    def find_form(pages: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any]]:
        for p in pages:
            if "consolidated form 1099" in p["text"].lower():
                return "BROKER", p
            if form := k1_kind(p["text"]):
                return form, p
        return None, pages[0]

    def calendar_year(text: str) -> int | None:
        m = re.search(r"calendar\s*year\s*(20\d\d)", text, re.I)
        return int(m.group(1)) if m else None

    def k1_prompt(form: str, intro: str = "") -> str:
        boxes = k1_labels(form, 2025).items()
        guide = "; ".join(f"{b} {label}" + (" (coded)" if kind == "coded" else "") for b, (label, kind) in boxes)
        return f"{intro}Read this Schedule K-1 (Form {form}). Part III boxes on this form include: {guide}."

    def statement_rows(markdown: str) -> list[tuple[str, str, str]]:
        """Box / Description / Amount rows from Docling's tables on a statement page."""
        rows = []
        for line in markdown.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and re.fullmatch(r"\d{1,2}[A-Z]{1,2}\d*", cells[0].replace(" ", "")):
                rows.append((cells[0].replace(" ", ""), cells[1], cells[-1]))
        return rows

    async def read_statements(runner: Any, path: Path, fields: Fields, pages: list[dict[str, Any]]) -> None:
        for f in (f for f in fields if f["value"] == "STMT"):
            box = f["key"].split(" ")[0]
            if not pages:
                f["reasons"] = ["amount is on an attached statement, but there's no statement page in the file"]
                continue
            hits = [
                p
                for p in pages
                if any(re.match(rf"{re.escape(box)}[A-Z]", r[0]) for r in statement_rows(p["markdown"]))
            ]
            sp = (hits or pages)[0]
            prompt = (
                f"This is a supplemental statement to a Schedule K-1. List every line that belongs to box {box} "
                f"(codes starting with {box}). Docling's reading of the page, for reference:\n\n{sp['markdown'][:6000]}"
            )
            lines = await runner.ask(
                path.name, f"statement {box}", StatementLines, prompt, [page_png(path, sp["index"])]
            )
            table = {code: amount for code, _d, amount in statement_rows(sp["markdown"])}
            f["reasons"] = [f"amount is on the attached statement (page {sp['index'] + 1})"]
            f["statement_page"], f["statement_lines"] = sp["index"], []
            for ln in lines.lines:
                value, code = parse_value(ln.printed)[0], ln.code.replace(" ", "").upper()
                bbox = [round(b / 1000, 4) for b in ln.bbox] if len(ln.bbox) == 4 else None
                agrees_with_docling = code in table and parse_value(table[code])[0] == value
                f["statement_lines"].append(
                    {
                        "code": ln.code,
                        "description": ln.description,
                        "printed": ln.printed,
                        "value": value,
                        "bbox": bbox,
                        "docling_agrees": agrees_with_docling,
                    }
                )

    async def read_document(runner: Any, path: Path) -> dict[str, Any] | None:
        layout = layouts[path.name]
        pages = layout["pages"]
        form, main = find_form(pages)
        if form is None:
            kind = await runner.ask(
                path.name, "form", FormQuestion, "Which tax form is this page?", [page_png(path, 0)]
            )
            form = FORM_ANSWERS.get(kind)
        if form is None:
            return None
        png, year = page_png(path, main["index"]), None
        if form == "BROKER":
            prompt = "Read the summary amounts on this consolidated brokerage 1099 page."
            fields = answer_fields(
                form, {}, await runner.ask(path.name, "extraction", Brokerage1099, prompt, [png]), main["index"]
            )
        else:
            prompt = k1_prompt(form) + (
                " In a coded box, report one row per printed line, with the code letter printed to the left of the "
                "amount on that line (every line in a coded box has one), including lines whose amount is a dash and "
                "lines coded '*' with STMT."
            )
            out = await runner.ask(path.name, "extraction", K1_MODELS[form], prompt, [png])
            year = calendar_year(main["text"]) or out.tax_year
            fields = answer_fields(form, k1_labels(form, year), out, main["index"])
            later = [p for p in pages if p["index"] > main["index"] and statement_rows(p["markdown"])]
            await read_statements(runner, path, fields, later)
        reason = finish(fields, main, form)
        shown = [main["index"]] + ([main["index"] + 1] if form == "BROKER" and len(pages) > main["index"] + 1 else [])
        shown += sorted({f["statement_page"] for f in fields if "statement_page" in f})
        spent = runner.spent(path.name)
        return {
            "file": path.name,
            "form": form,
            "year": year,
            "source": "OCR" if main["ocr"] else "text layer",
            "page_review": reason,
            "pages": {str(i): page_image(path, i) for i in shown},
            "docling_seconds": layout["seconds"],
            "model_seconds": round(spent["seconds"], 1),
            "seconds": round(layout["seconds"] + spent["seconds"], 1),
            "cost_usd": round(spent["usd"], 6),
            "cost_missing_responses": spent["cost_missing"],
            "failed_attempts": spent["failed_attempts"],
            "fields": fields,
        }

    return calendar_year, find_form, k1_kind, k1_prompt, read_document


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. Every model reads every document

    The five models run side by side, all through OpenRouter. A model that fails every attempt on some documents is
    scored on the rest, and its failed documents are listed. The run stops only if Gemini 3.8 Flash or Qwen 3.8 27B
    produce nothing, since the pair below needs both.
    """)
    return


@app.cell
async def _(FILES, Runner, read_document):
    MODELS = {
        "gemini-3.8-flash": "openrouter:google/gemini-3.8-flash",
        "qwen3.8-27b": "openrouter:qwen/qwen3.8-27b",
        "qwen3-vl-235b-a22b-instruct": "openrouter:qwen/qwen3-vl-235b-a22b-instruct",
        "glm-5.3-flash": "openrouter:z-ai/glm-5.3-flash",
        "gemma-4-31b-it": "openrouter:google/gemma-4-31b-it",
    }
    PAIR = ("gemini-3.8-flash", "qwen3.8-27b")

    def save_run(run: dict[str, Any]) -> None:
        (OUT / run["name"]).mkdir(parents=True, exist_ok=True)
        (OUT / run["name"] / "extracted.json").write_text(json.dumps(run, indent=1))

    async def read_all(name: str, model_name: str, read: Any, label: str, description: str) -> dict[str, Any]:
        """Run read(path) on every document. A document that fails is listed as failed, and doesn't stop the run."""

        async def one(path: Path) -> tuple[Path, dict[str, Any] | None, str]:
            try:
                doc = await read(path)
            except Exception as e:
                print(f"{name} {path.name}: failed: {type(e).__name__}: {str(e)[:200]}")
                return path, None, f"{type(e).__name__}: {str(e)[:200]}"
            if doc:
                n = sum(f["status"] == "review" for f in doc["fields"])
                print(f"{name} {path.name}: {len(doc['fields'])} values, {n} to review, ${doc['cost_usd']:.4f}")
            return path, doc, "no result"

        results = await asyncio.gather(*(one(p) for p in FILES))
        run = {
            "name": name,
            "label": label,
            "description": description,
            "model": model_name,
            "documents": [d for _p, d, _e in results if d],
            "failed_documents": [{"file": p.name, "error": e} for p, d, e in results if not d],
        }
        save_run(run)
        return run

    async def read_with(name: str, model_name: str) -> dict[str, Any]:
        runner = Runner(model_name, OUT / "answers" / name)
        description = f"Read by {model_name} through OpenRouter, with no second read."
        return await read_all(
            f"{name}-alone", model_name, lambda p: read_document(runner, p), f"{name}, alone", description
        )

    # ./run.sh --gemma-google sets K1_GEMMA_ONLY and runs only section 5b below.
    _chosen = {} if os.environ.get("K1_GEMMA_ONLY") else MODELS
    model_runs = dict(zip(_chosen, await asyncio.gather(*(read_with(n, m) for n, m in _chosen.items())), strict=True))
    for _name in PAIR if _chosen else ():
        if not model_runs[_name]["documents"]:
            raise RuntimeError(f"{_name} produced no results, and the pair needs it")
    model_runs = {k: r for k, r in model_runs.items() if r["documents"]}
    return MODELS, PAIR, model_runs, read_all, save_run


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5b. Gemma 4 31B again, with Google's recommended settings

    Gemma 4 31B came last above. We called it at temperature 0, at the image size the host picked, on whichever host
    OpenRouter chose. [Google's model card](https://ai.google.dev/gemma/docs/core/model_card_4) recommends temperature
    1.0, top_p 0.95 and top_k 64, and a higher visual token budget for reading small text. So Gemma runs three more
    times here with those sampling settings, on one pinned host at full precision: Crusoe, which serves the bf16
    weights. Most of OpenRouter's hosts for Gemma 4 31B serve it at fp4 or fp8. The prompt, schema, review rules and
    scoring are the same as above.

    **The image budget couldn't be raised.** Gemma 4 turns an image into 70, 140, 280, 560 or 1120 tokens, and 280
    is the default. vLLM takes the budget as `mm_processor_kwargs.max_soft_tokens`. We sent a 1700 × 2200 page with
    budgets 70 and 1120 to Crusoe, Novita, Parasail, DeepInfra, CoreWeave, SiliconFlow and Chutes through OpenRouter.
    Every host reported the same prompt size either way: about 290 tokens, the default 280 plus the question. OpenRouter
    has no image-budget parameter of its own. So every run here, like every run above, sees each page at 280 tokens,
    about 700 × 900 pixels for a K-1 page.

    `require_parameters` makes OpenRouter refuse a host that would drop top_k. Crusoe is often rate-limited
    upstream, so its runs take longer and count more failed attempts; a refused call isn't charged.
    """)
    return


@app.cell
async def _(Runner, read_all, read_document):
    GEMMA_GOOGLE_SETTINGS = {
        "temperature": 1.0,
        "top_p": 0.95,
        "extra_body": {"top_k": 64},  # OpenAI-style APIs have no top_k field; OpenRouter passes it on
        "openrouter_provider": {
            "order": ["crusoe"],
            "quantizations": ["bf16"],
            "allow_fallbacks": False,
            "require_parameters": True,
        },
    }

    async def read_gemma_google(n: int) -> dict[str, Any]:
        model_name, name = "openrouter:google/gemma-4-31b-it", f"gemma-4-31b-it-google-{n}"
        runner = Runner(model_name, OUT / "answers" / name, GEMMA_GOOGLE_SETTINGS)
        description = f"Read by {model_name} on Crusoe (bf16) at temperature 1.0, top_p 0.95, top_k 64."
        run = await read_all(
            name,
            model_name,
            lambda p: read_document(runner, p),
            f"Gemma 4 31B, Google's settings, run {n}",
            description,
        )
        run["served_by"] = sorted(runner.served_by)
        print(f"{name}: served by {', '.join(run['served_by']) or 'nothing'}")
        if run["served_by"] != ["Crusoe"]:
            raise RuntimeError(f"{name} was served by {run['served_by']}, not only by the pinned host")
        return run

    # One run after another, so the three don't compete for Crusoe's rate limit.
    gemma_google_runs = [await read_gemma_google(_n) for _n in (1, 2, 3)]
    return (gemma_google_runs,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. Two models that must agree

    Gemini 3.8 Flash's own confidence never flags anything: everything it sends to review is a STMT amount or a
    malformed one. So when it misreads a bad scan, nothing in its own answer catches it. A second, independent read
    can catch it. The pair combines the two models' saved answers, with no further calls. A value is accepted only
    when both models report the same box and code with the same amount, and neither has its own reason to send it to
    review. Anything only one reported, or that they read differently, goes to review. A pair costs the sum of its
    two models and takes as long as the slower one.
    """)
    return


@app.cell
def _(PAIR, agrees, model_runs, same_text, save_run):
    def combine(da: dict[str, Any], db: dict[str, Any], na: str, nb: str) -> dict[str, Any]:
        other_fields, fields = {f["key"]: f for f in db["fields"]}, []
        for fa in da["fields"]:
            f = dict(fa, reasons=list(fa["reasons"]))
            if (other := other_fields.pop(fa["key"], None)) is None:
                f["reasons"].append(f"only {na} reported it")
            else:
                f["reasons"] += [r for r in other["reasons"] if r not in f["reasons"]]
                payer = fa["key"].startswith("payer")
                if not (same_text(fa["value"], other["value"]) if payer else agrees(fa["raw"], other["raw"])):
                    f["reasons"].append(f"{nb} read '{other['raw']}'")
                f["confidence"] = min(fa["confidence"], other["confidence"])
            fields.append(f)
        fields += [dict(o, reasons=[*o["reasons"], f"only {nb} reported it"]) for o in other_fields.values()]
        for f in fields:
            f["status"] = "review" if f["reasons"] else "accepted"
        slower = max(da["model_seconds"], db["model_seconds"])
        return da | {
            "fields": fields,
            "page_review": da["page_review"] or db["page_review"],
            "cost_usd": round(da["cost_usd"] + db["cost_usd"], 6),
            "cost_missing_responses": da["cost_missing_responses"] + db["cost_missing_responses"],
            "failed_attempts": da["failed_attempts"] + db["failed_attempts"],
            "model_seconds": slower,
            "seconds": round(da["docling_seconds"] + slower, 1),
        }

    pair_run = None
    if all(n in model_runs for n in PAIR):  # not when K1_GEMMA_ONLY skipped the models
        _a, _b = (model_runs[n] for n in PAIR)
        _docs_b = {d["file"]: d for d in _b["documents"]}
        _pair_docs = [combine(d, _docs_b[d["file"]], *PAIR) for d in _a["documents"] if d["file"] in _docs_b]
        _done = {d["file"] for d in _pair_docs}
        _failed = {f["file"]: f["error"] for r in (_a, _b) for f in r["failed_documents"]}
        _failed |= {
            d["file"]: "only one model read it" for r in (_a, _b) for d in r["documents"] if d["file"] not in _done
        }
        pair_run = {
            "name": f"pair-{PAIR[0]}+{PAIR[1]}",
            "label": f"{PAIR[0]} + {PAIR[1]}, must agree",
            "model": f"{_a['model']} checked by {_b['model']}",
            "documents": _pair_docs,
            "description": f"Read by {_a['model']} and {_b['model']} through OpenRouter. "
            "A value is accepted only when both models read the same thing.",
            "failed_documents": [{"file": f, "error": e} for f, e in sorted(_failed.items())],
        }
        save_run(pair_run)
    return (pair_run,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 7. Reading text instead of the image: OCR models on Modal

    olmOCR 2 and granite-docling turn a page into text rather than filling a schema. So each is followed by a text
    model, Gemini 3.8 Flash, which fills the same typed schema from the OCR text with the same review rules and never
    sees the image. `ocr_modal.py` is the Modal app. A CPU container downloads both models' weights into a Modal
    Volume once, and the L4 GPU containers only read pages.

    - **olmOCR 2** (`allenai/olmOCR-2-7B-1025-FP8`) runs on vLLM with olmOCR's own prompt and 1288-pixel page
      images, and returns Markdown with HTML tables.
    - **granite-docling** (`ibm-granite/granite-docling-258M`) is served by vLLM behind an API key made for each run.
      Docling's VLM pipeline runs here and calls it, using Docling's own `GRANITEDOCLING_VLLM_API` preset with two
      changes. The preset asks the server to skip special tokens, but granite-docling's DocTags *are* special tokens,
      so Docling got nothing to parse. And a dense form needs more than the preset's 4,096 output tokens.

    The GPU cost is Modal's L4 list price ($0.000222 a second) for each page's GPU time. For granite-docling that time
    is each page's round trip to a server handling several pages at once, so it overstates its share. This section
    runs only when `MODAL_TOKEN_ID` is set. OCR results are saved under `output/ocr/`. The text model has no image to
    point into, so these runs' review screens don't highlight values on the page.
    """)
    return


@app.cell
def _():
    ENGINES = {
        "olmocr": "olmOCR 2 (allenai/olmOCR-2-7B-1025-FP8)",
        "granite-docling": "granite-docling (ibm-granite/granite-docling-258M) in Docling's VLM pipeline",
    }
    L4_USD_PER_SECOND = 0.000222

    def granite_page(url: str, path: Path, index: int) -> dict[str, Any]:
        """One page through Docling's VLM pipeline, with granite-docling running on Modal."""
        spec = vlm_model_specs.GRANITEDOCLING_VLLM_API.model_copy(deep=True)
        spec.url = AnyUrl(f"{url}/v1/chat/completions")
        spec.headers = {"Authorization": f"Bearer {ocr_modal.API_KEY}"}
        spec.timeout = 600
        spec.params["skip_special_tokens"] = False
        spec.params["max_tokens"] = 7000  # what the server's 8,192-token context leaves after the page image
        options = VlmPipelineOptions(vlm_options=spec, enable_remote_services=True)
        pdf = PdfFormatOption(pipeline_cls=VlmPipeline, pipeline_options=options)
        t0 = time.time()
        result = DocumentConverter(format_options={InputFormat.PDF: pdf}).convert(
            path, page_range=(index + 1, index + 1)
        )
        return {"markdown": result.document.export_to_markdown(), "seconds": round(time.time() - t0, 1)}

    def ocr_pages(engine: str, jobs: dict[Path, int], page_png: Any) -> dict[str, dict[str, Any]]:
        """OCR each document's page on Modal, unless it was read before."""
        saved = OUT / "ocr" / engine
        saved.mkdir(parents=True, exist_ok=True)
        todo = [(p, i) for p, i in jobs.items() if not (saved / f"{p.stem}-p{i + 1}.json").exists()]
        if todo:
            print(f"{engine}: reading {len(todo)} pages on Modal")
            with modal.enable_output(), ocr_modal.app.run():
                ocr_modal.download.remote()
                if engine == "olmocr":
                    outs = ocr_modal.OlmOCR().ocr.remote([page_png(p, i) for p, i in todo])
                else:
                    url = ocr_modal.GraniteServer().serve.get_web_url()  # ty: ignore[call-non-callable]
                    assert url, "the granite-docling server has no URL"
                    with ThreadPoolExecutor(8) as pool:
                        outs = list(pool.map(lambda job: granite_page(url, *job), todo))
            for (p, i), out in zip(todo, outs, strict=True):
                (saved / f"{p.stem}-p{i + 1}.json").write_text(json.dumps(out))
        return {p.name: json.loads((saved / f"{p.stem}-p{i + 1}.json").read_text()) for p, i in jobs.items()}

    return ENGINES, L4_USD_PER_SECOND, ocr_pages


@app.cell
async def _(
    Brokerage1099,
    ENGINES,
    FILES,
    K1_MODELS,
    L4_USD_PER_SECOND,
    MODELS,
    Runner,
    answer_fields,
    calendar_year,
    find_form,
    finish,
    k1_kind,
    k1_labels,
    k1_prompt,
    layouts,
    ocr_pages,
    page_png,
    read_all,
    page_image,
    whole_page,
):
    def form_of(text: str) -> str | None:
        """The form, from the OCR text: the Part III heading, or the form named in the title."""
        if "consolidated form 1099" in text.lower() or "1099-div" in text.lower():
            return "BROKER"
        if form := k1_kind(text):
            return form
        m = re.search(r"Schedule K-1\s*\(Form (1065|1120-?S|1041)\)", text[:600], re.I)
        return m.group(1).upper().replace("-", "") if m else None

    async def read_ocr_text(runner: Any, engine: str, path: Path, ocr: dict[str, Any]) -> dict[str, Any]:
        page = find_form(layouts[path.name]["pages"])[1]
        text = re.sub(r"\A---\n.*?\n---\n", "", ocr["markdown"], flags=re.S).strip()  # without olmOCR's front matter
        note = (
            f"Below is the text of one page of a tax document, as read by an OCR model ({ENGINES[engine]}). "
            "You don't have the image, so set every bbox to [0, 0, 0, 0]. Set confidence below 0.9 where the text "
            "looks garbled or a value is ambiguous.\n\n"
        )
        form, year = form_of(text), None
        if form == "BROKER":
            prompt = note + "Read the summary amounts of this consolidated brokerage 1099.\n\n" + text
            fields = answer_fields(
                form, {}, await runner.ask(path.name, "extraction", Brokerage1099, prompt, []), page["index"]
            )
        elif form:
            coded = " In a coded box, report one row per printed line with its code letter, including lines whose "
            prompt = k1_prompt(form, note) + coded + "amount is a dash and lines coded '*' with STMT.\n\n" + text
            out = await runner.ask(path.name, "extraction", K1_MODELS[form], prompt, [])
            year = calendar_year(text) or out.tax_year
            fields = answer_fields(form, k1_labels(form, year), out, page["index"])
        else:
            fields = [whole_page(page, "couldn't tell from the OCR text which form this is")]
        reason = finish(fields, page, form or "")
        for f in fields:
            f["bbox"] = None
        spent, gpu = runner.spent(path.name), ocr["seconds"]
        return {
            "file": path.name,
            "form": form,
            "year": year,
            "source": f"{engine} OCR",
            "page_review": reason,
            "pages": {str(page["index"]): page_image(path, page["index"])},
            "docling_seconds": 0.0,
            "ocr_seconds": gpu,
            "model_seconds": round(spent["seconds"], 1),
            "seconds": round(gpu + spent["seconds"], 1),
            "cost_usd": round(spent["usd"] + gpu * L4_USD_PER_SECOND, 6),
            "failed_attempts": spent["failed_attempts"],
            "cost_missing_responses": spent["cost_missing"],
            "fields": fields,
        }

    async def read_with_ocr(engine: str) -> dict[str, Any]:
        model_name, name = MODELS["gemini-3.8-flash"], f"{engine}+gemini-3.8-flash"
        ocr = await asyncio.to_thread(
            ocr_pages, engine, {p: find_form(layouts[p.name]["pages"])[1]["index"] for p in FILES}, page_png
        )
        runner = Runner(model_name, OUT / "answers" / name)
        label = f"{engine} OCR + gemini-3.8-flash on the text"
        description = f"Read by {ENGINES[engine]} on Modal; {model_name} filled the form from its text."
        return await read_all(
            name, model_name, lambda p: read_ocr_text(runner, engine, p, ocr[p.name]), label, description
        )

    ocr_runs: dict[str, dict[str, Any]] = {}
    if os.environ.get("K1_GEMMA_ONLY"):
        print("K1_GEMMA_ONLY is set, so the OCR models didn't run.")
    elif os.environ.get("MODAL_TOKEN_ID"):
        for _engine in ENGINES:  # one after the other: ephemeral runs of the Modal app share the server's URL
            if (_run := await read_with_ocr(_engine))["documents"]:
                ocr_runs[_engine] = _run
    else:
        print("MODAL_TOKEN_ID isn't set, so the OCR models didn't run.")
    return (ocr_runs,)


@app.cell
def _(gemma_google_runs, model_runs, ocr_runs, pair_run):
    # The runs for 3_results.py to score, in the order its tables show them.
    _runs = [*model_runs.values(), *ocr_runs.values(), *([pair_run] if pair_run else []), *gemma_google_runs]
    _order = [r["name"] for r in _runs]
    (OUT / "runs.json").write_text(json.dumps(_order))
    print("Runs for 3_results.py:", ", ".join(_order))
    return


if __name__ == "__main__":
    app.run()
