import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import hashlib
    import json
    import os
    import time
    from pathlib import Path

    import marimo as mo
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent, BinaryContent, capture_run_messages
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models import infer_model
    from pydantic_ai.models.openrouter import OpenRouterModelSettings

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("EZ_OUTPUT_DIR", HERE / "output"))
    PAGES = OUT / "pages"
    ANSWERS = OUT / "answers"
    BUDGET_USD = 10.0


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Reading the pages

    This notebook drafts the schema from sample pages and freezes it. Then it has two vision models, from different
    companies, read every page into that schema, each value with the box it came from. `3_results.py` compares the
    two readings and scores them.

    ## Step 1: draft the schema from sample pages, then freeze it

    The first step is to agree what to pull out before reading thousands of pages, and then stop changing it. We
    show a model five sample pages and ask it to list every field printed in the header and Part I.
    """)
    return


@app.cell
def _():
    sample = json.loads((OUT / "sample.json").read_text())
    pages = [s for s in sample if "failure" not in s]
    page_png = {f"{s['ein']}_{s['tax_pd']}": PAGES / f"{s['ein']}_{s['tax_pd']}.png" for s in pages}
    print(f"{len(page_png)} pages to read")
    return (page_png,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Calling a model.** Models are named by a Pydantic AI model string and called through OpenRouter, at
    temperature 0 and low thinking effort, the settings `k1-extraction-review-queue/` settled on. Each call gets up
    to four attempts, and Pydantic AI retries malformed output twice within each. Every attempt is paid for and
    counted, at the cost OpenRouter reports. Answers are saved under `output/answers/`, so re-running reuses them.
    The run stops if spending passes the $10 budget.
    """)
    return


@app.cell
def _():
    def response_cost(m: ModelResponse) -> float:
        return float((m.provider_details or {}).get("cost") or 0.0)

    async def ask(
        model: str, output_type: type[BaseModel], instructions: str, prompt: str, pngs: list[Path], save: Path
    ) -> dict:
        """One typed model call, with its cost and time, saved to `save` and reused if it's already there."""
        if save.exists():
            return json.loads(save.read_text())
        agent = Agent(
            infer_model(model),
            output_type=output_type,
            instructions=instructions,
            retries=2,
            model_settings=OpenRouterModelSettings(
                temperature=0, max_tokens=8000, thinking="low", openrouter_usage={"include": True}
            ),
        )
        parts = [prompt] + [BinaryContent(p.read_bytes(), media_type="image/png") for p in pngs]
        result = {"usd": 0.0, "seconds": 0.0, "failed_attempts": 0, "output": None, "error": None}
        for attempt in range(4):
            t0 = time.time()
            with capture_run_messages() as messages:
                try:
                    result["output"] = (await agent.run(parts)).output.model_dump(mode="json")
                except Exception as e:  # rate limits, network errors, malformed output after retries
                    result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            result["usd"] += sum(response_cost(m) for m in messages if isinstance(m, ModelResponse))
            result["seconds"] += time.time() - t0
            if result["output"] is not None:
                result["error"] = None
                break
            result["failed_attempts"] += 1
            await asyncio.sleep(10 * (attempt + 1))
        save.parent.mkdir(parents=True, exist_ok=True)
        save.write_text(json.dumps(result, indent=1))
        return result

    def spent() -> float:
        return sum(json.loads(p.read_text())["usd"] for p in ANSWERS.rglob("*.json"))

    return ask, spent


@app.cell
async def _(ask, page_png):
    class DraftField(BaseModel):
        line: str = Field(description="The line number or header letter printed on the form, e.g. 'D', '5a', '17'.")
        label: str = Field(description="The printed label, shortened.")
        kind: str = Field(description="'amount', 'identifier', 'date', 'checkbox' or 'text'.")

    class DraftSchema(BaseModel):
        fields: list[DraftField]

    draft = await ask(
        "openrouter:google/gemini-3.8-flash",
        DraftSchema,
        "You design data schemas for scanned government forms.",
        "These are five scanned first pages of IRS Form 990-EZ. List every field printed in the header (items A to L) "
        "and Part I, one per line number, in the order printed, whether or not it is filled in on these copies.",
        list(page_png.values())[:5],
        ANSWERS / "schema_draft.json",
    )
    mo.ui.table(draft["output"]["fields"], selection=None, page_size=40)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Freezing it.** The draft lists every field on the page. We keep the ones we can score: the EIN, the end of the
    tax year, and the 20 Part I amounts the SOI extract also has. We drop the name, address, phone and checkboxes,
    which SOI doesn't hold, and lines 10 to 16 and 19, the expense lines and opening net assets, which it doesn't
    break out. That gives 22 fields. Each field becomes a `Value`, which carries the text as printed, the box it was
    printed in, and the model's own confidence. Page and box are what let a reviewer or a reader check any number
    against the scan.

    The frozen schema is the class below, and its hash is printed. Any change to a field shows up as a new hash, and
    the readings saved under `output/answers/` belong to that hash.
    """)
    return


@app.cell
def _():
    class Value(BaseModel):
        printed: str = Field(description="The value exactly as printed or handwritten, e.g. '12,345.' or '(1,200)'.")
        bbox: list[int] = Field(description="Tight box around the value, [x0, y0, x1, y1] in 0-1000 page coordinates.")
        confidence: float = Field(description="0 to 1. Below 0.9 if any character is faint, smudged or ambiguous.")

    class TaxYearEnd(Value):
        """The end of the tax year: the 'and ending' date, or the form's year for a calendar-year return."""

        yyyymm: str = Field(description="The end of the tax year as YYYYMM, e.g. '201706'; December for calendar year.")

    def amount(line: str, label: str) -> Value | None:
        return Field(None, description=f"Part I line {line}: {label}. Leave out if the box is empty.")

    class Page990EZ(BaseModel):
        """Page 1 of IRS Form 990-EZ as printed."""

        is_990ez_page_1: bool = Field(description="False if this page is not page 1 of Form 990-EZ.")
        ein: Value | None = Field(None, description="Item D: employer identification number, as NN-NNNNNNN.")
        tax_period: TaxYearEnd | None = None
        line_1: Value | None = amount("1", "Contributions, gifts, grants, and similar amounts received")
        line_2: Value | None = amount("2", "Program service revenue")
        line_3: Value | None = amount("3", "Membership dues and assessments")
        line_4: Value | None = amount("4", "Investment income")
        line_5a: Value | None = amount("5a", "Gross amount from sale of assets other than inventory")
        line_5b: Value | None = amount("5b", "Less: cost or other basis and sales expenses")
        line_5c: Value | None = amount("5c", "Gain or (loss) from sale of assets")
        line_6a: Value | None = amount("6a", "Gross income from gaming")
        line_6b: Value | None = amount("6b", "Gross income from fundraising events (the amount in the 6b box)")
        line_6c: Value | None = amount("6c", "Less: direct expenses from gaming and fundraising events")
        line_6d: Value | None = amount("6d", "Net income or (loss) from gaming and fundraising events")
        line_7a: Value | None = amount("7a", "Gross sales of inventory")
        line_7b: Value | None = amount("7b", "Less: cost of goods sold")
        line_7c: Value | None = amount("7c", "Gross profit or (loss) from sales of inventory")
        line_8: Value | None = amount("8", "Other revenue")
        line_9: Value | None = amount("9", "Total revenue")
        line_17: Value | None = amount("17", "Total expenses")
        line_18: Value | None = amount("18", "Excess or (deficit) for the year")
        line_20: Value | None = amount("20", "Other changes in net assets or fund balances")
        line_21: Value | None = amount("21", "Net assets or fund balances at end of year")

    SCHEMA_HASH = hashlib.sha256(json.dumps(Page990EZ.model_json_schema(), sort_keys=True).encode()).hexdigest()[:12]
    FIELDS = [f for f in Page990EZ.model_fields if f != "is_990ez_page_1"]
    print(f"frozen schema {SCHEMA_HASH}: {len(FIELDS)} fields")
    return FIELDS, Page990EZ, SCHEMA_HASH


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Step 2: two independent readings

    Two vision models read every page: **Gemini 3.8 Flash** (Google) and **Qwen 3.8 27B** (Alibaba, open weights).
    They are the pair that let no wrong value through in `k1-extraction-review-queue/`, and coming from different
    companies, they are less likely to make the same mistake. Each sees only the page image and the schema.
    """)
    return


@app.cell
async def _(FIELDS, Page990EZ, SCHEMA_HASH, ask, page_png, spent):
    MODELS = {"gemini": "openrouter:google/gemini-3.8-flash", "qwen": "openrouter:qwen/qwen3.8-27b"}
    INSTRUCTIONS = "\n".join(
        [
            "You read scanned US tax forms. Report only what is printed or handwritten on the page.",
            "Never compute, infer or fill in a value. Leave out boxes that are empty.",
            "Bounding boxes are [x0, y0, x1, y1] in 0-1000 coordinates relative to the page image.",
        ]
    )
    PROMPT = "Read page 1 of this Form 990-EZ."
    slots = asyncio.Semaphore(8)

    async def read(name: str, key: str) -> dict:
        async with slots:
            if spent() > BUDGET_USD:
                raise RuntimeError(f"spent more than the ${BUDGET_USD} budget")
            save = ANSWERS / SCHEMA_HASH / name / f"{key}.json"
            return await ask(MODELS[name], Page990EZ, INSTRUCTIONS, PROMPT, [page_png[key]], save)

    t0 = time.time()
    readings = {
        name: dict(zip(page_png, await asyncio.gather(*(read(name, k) for k in page_png)), strict=True))
        for name in MODELS
    }
    print(f"read in {time.time() - t0:.0f} s; ${spent():.2f} spent on model calls so far, including the schema draft")
    for name, by_page in readings.items():
        ok = [r for r in by_page.values() if r["output"]]
        print(
            f"{name}: {len(ok)} of {len(by_page)} pages answered, "
            f"{sum(len([f for f in FIELDS if r['output'][f]]) for r in ok)} values, "
            f"${sum(r['usd'] for r in by_page.values()):.3f}, "
            f"{sum(r['seconds'] for r in by_page.values()) / len(by_page):.1f} s a page, "
            f"{sum(r['failed_attempts'] for r in by_page.values())} failed attempts"
        )
    (OUT / "readings.json").write_text(json.dumps({"models": MODELS, "readings": readings}, indent=1))
    return


if __name__ == "__main__":
    app.run()
