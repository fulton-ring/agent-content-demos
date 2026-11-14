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

    from ccr import ask, spent

    HERE = Path(__file__).parent
    UTILITY = os.environ.get("CCR_UTILITY", "pacificorp")
    OUT = Path(os.environ.get("CCR_OUTPUT_DIR", HERE / "output")) / ("" if UTILITY == "pacificorp" else UTILITY)
    PAGES = OUT / "pages"
    ANSWERS = HERE / "answers"
    # Counted across every answer saved under this schema: PacifiCorp (#188) spent $2.10, and AEP (#223) up to $3.
    # The multi-sample schema in 4_multi_sample.py has its own folder and budget.
    BUDGET_USD = 5.1


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Reading the pages

    This notebook drafts the schema from sample pages and freezes it. Then two vision models, from different
    companies, read every page into that schema, each value with the box it came from. `3_results.py` compares the
    two readings and scores them.

    ## Step 1: draft the schema from sample pages, then freeze it

    Agree what to pull out before reading hundreds of pages, then stop changing it. We show a model four lab pages,
    two scanned and two born-digital from different labs, and ask it to list every field.
    """)
    return


@app.cell
def _():
    pages = json.loads((OUT / "pages.json").read_text())
    page_png = {p["key"]: PAGES / f"{p['key']}.png" for p in pages}
    print(f"{len(page_png)} pages to read")
    return page_png, pages


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Calling a model.** Models are named by a Pydantic AI model string and called through OpenRouter at
    temperature 0 and low thinking effort, as in `scanned-990ez-extraction/`. Each call gets up to four attempts,
    and Pydantic AI retries malformed output twice within each. Every attempt is paid for and counted, at the cost
    OpenRouter reports (the call itself is `ask` in `ccr.py`, shared with `4_multi_sample.py`). Answers are saved
    under `answers/`, **which is committed**, so anyone can rescore from a
    clean checkout without paying again. The run stops if total spending passes $5.10: the $2.10 PacifiCorp
    cost plus up to $3 for AEP.
    """)
    return


@app.cell
async def _(page_png):
    class DraftField(BaseModel):
        name: str = Field(description="Short field name.")
        where: str = Field(description="Where it is printed: page header, or a column of the results table.")
        example: str = Field(description="One value as printed on these pages.")

    class DraftSchema(BaseModel):
        fields: list[DraftField]

    _samples = [
        "hunter_ccr-landfill_2018_p0157",
        "huntington_ccr-landfill_2019_p0283",
        "dave-johnston_ash-pond_2022_p0117",
        "jim-bridger_landfill_2021_p0107",
    ]
    _samples = [k for k in _samples if k in page_png]
    draft = await ask(
        "openrouter:google/gemini-3.8-flash",
        DraftSchema,
        "You design data schemas for scanned laboratory reports.",
        "These are laboratory analytical report pages for groundwater samples from coal ash monitoring wells. "
        "List every field a database of the results would need, from the page header and from the results table.",
        [page_png[k] for k in _samples],
        ANSWERS / "schema_draft.json",
    )
    mo.ui.table(draft["output"]["fields"], selection=None, page_size=40)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Freezing it.** We keep what a groundwater dataset needs and what we can score: the well (the lab's *client
    sample ID*), the collection date, and for each constituent its name, result, units, reporting limit and lab
    qualifier. The result is copied exactly as printed (`< 0.00200`, `ND`, `1.86`); turning it into a number and a
    non-detect flag happens in code, in `3_results.py`, where it can be checked. We drop lab sample numbers, analysis
    dates, methods and the lab's address, which nobody downstream asked for.

    Every value carries the box it was printed in and the model's own confidence. A page also says whether it is a
    lab result page at all, because the scanned candidates include custody forms, QC summaries and cover letters.
    The schema's hash is printed; readings saved under `answers/` belong to that hash.
    """)
    return


@app.cell
def _():
    class Printed(BaseModel):
        printed: str = Field(description="The value exactly as printed or handwritten.")
        bbox: list[int] = Field(description="Tight box around the value, [x0, y0, x1, y1] in 0-1000 page coordinates.")
        confidence: float = Field(description="0 to 1. Below 0.9 if any character is faint, smudged or ambiguous.")

    class CollectionDate(Printed):
        iso: str = Field(description="The collection date as YYYY-MM-DD.")

    class Result(BaseModel):
        analyte: str = Field(description="Constituent name as printed, e.g. 'Boron' or 'Total Dissolved Solids'.")
        result: Printed = Field(description="The result exactly as printed, including any '<' or 'ND'.")
        units: str = Field(description="Units as printed, e.g. 'mg/L', 's.u.', 'pCi/L'.")
        reporting_limit: str | None = Field(None, description="The reporting limit (RL or MRL) as printed.")
        qualifier: str | None = Field(None, description="Any qualifier flag printed beside the result.")

    class LabPage(BaseModel):
        """One page of a laboratory analytical report for one groundwater sample."""

        is_lab_result_page: bool = Field(
            description="True only if the page reports analytical results for one field sample. False for chain of "
            "custody forms, QC or method blank summaries, cover letters, case narratives and anything else."
        )
        client_sample_id: Printed | None = Field(None, description="The client sample ID: the monitoring well name.")
        collection_date: CollectionDate | None = None
        results: list[Result] = Field(default_factory=list, description="Every row of the results table, in order.")

    SCHEMA_HASH = hashlib.sha256(json.dumps(LabPage.model_json_schema(), sort_keys=True).encode()).hexdigest()[:12]
    print(f"frozen schema {SCHEMA_HASH}")
    return LabPage, SCHEMA_HASH


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Step 2: two independent readings

    Two vision models read every page: **Gemini 3.8 Flash** (Google) and **Mistral Small 2603** (Mistral, open
    weights). Coming from different companies, they are less likely to make the same mistake. Each sees only the
    page image and the schema.

    The 990-EZ spike paired Gemini with **Qwen 3.8 27B**. We swapped Qwen for Mistral after a one-page test, with
    an earlier draft of the schema, in which Qwen named the well and returned no results. One page was too little to
    go on: the cell after next has Qwen read ten lab pages with the frozen schema, and it reads every row. So Qwen
    may work as well here; we didn't measure it on the full set.
    """)
    return


@app.cell
async def _(LabPage, SCHEMA_HASH, page_png):
    MODELS = {"gemini": "openrouter:google/gemini-3.8-flash", "mistral": "openrouter:mistralai/mistral-small-2603"}
    INSTRUCTIONS = "\n".join(
        [
            "You read scanned and printed laboratory reports. Report only what is printed or handwritten on the page.",
            "Never compute, infer or fill in a value. Copy every result exactly as printed.",
            "Bounding boxes are [x0, y0, x1, y1] in 0-1000 coordinates relative to the page image.",
        ]
    )
    PROMPT = "Read this page of a groundwater laboratory report."
    slots = asyncio.Semaphore(8)

    async def read(name: str, model: str, key: str) -> dict:
        async with slots:
            if spent(ANSWERS / SCHEMA_HASH) > BUDGET_USD:
                raise RuntimeError(f"spent more than the ${BUDGET_USD} budget")
            save = ANSWERS / SCHEMA_HASH / name / f"{key}.json"
            return await ask(model, LabPage, INSTRUCTIONS, PROMPT, [page_png[key]], save)

    t0 = time.time()
    readings = {
        name: dict(zip(page_png, await asyncio.gather(*(read(name, model, k) for k in page_png)), strict=True))
        for name, model in MODELS.items()
    }
    print(f"read in {time.time() - t0:.0f} s; ${spent(ANSWERS / SCHEMA_HASH):.2f} spent on reading with this schema")
    for name, by_page in readings.items():
        ok = [r for r in by_page.values() if r["output"]]
        lab = [r for r in ok if r["output"]["is_lab_result_page"]]
        print(
            f"{name}: {len(ok)} of {len(by_page)} pages answered, {len(lab)} called lab result pages, "
            f"{sum(len(r['output']['results']) for r in lab)} results, ${sum(r['usd'] for r in by_page.values()):.3f}, "
            f"{sum(r['seconds'] for r in by_page.values()) / len(by_page):.1f} s a page, "
            f"{sum(r['failed_attempts'] for r in by_page.values())} failed attempts"
        )
    return MODELS, read, readings


@app.cell
async def _(pages, read, readings):
    _lab = [
        p["key"]
        for p in pages
        if p["kind"] == "scanned" and (readings["gemini"][p["key"]]["output"] or {}).get("is_lab_result_page")
    ][:10]
    _lab = _lab if UTILITY == "pacificorp" else []  # the Qwen trial is PacifiCorp's only
    qwen = dict(
        zip(_lab, await asyncio.gather(*(read("qwen", "openrouter:qwen/qwen3.8-27b", k) for k in _lab)), strict=True)
    )
    for _k, _r in qwen.items():
        _o = _r["output"] or {}
        print(
            f"{_k}: qwen gave {len(_o.get('results', []))} results, "
            f"gemini {len(readings['gemini'][_k]['output']['results'])}"
        )
    return


@app.cell
def _(MODELS, SCHEMA_HASH, readings):
    (OUT / "readings.json").write_text(
        json.dumps({"models": MODELS, "schema": SCHEMA_HASH, "readings": readings}, indent=1)
    )
    return


if __name__ == "__main__":
    app.run()
