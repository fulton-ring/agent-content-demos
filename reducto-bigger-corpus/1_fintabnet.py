import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import hashlib
    import io
    import json
    import os
    import random
    import urllib.request
    from pathlib import Path

    import marimo as mo
    import pyarrow.parquet as pq
    from PIL import Image

    import model_call
    from pipelines import Result, Runner, Task, fresh_copies, page_png, run_all, score_table, two_run_table

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("BIGGER_OUTPUT_DIR", HERE / "output")) / "fintabnet"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # FinTabNet: tables from S&P 500 annual reports

    **The question.** Reducto sells itself on complex financial tables. #136 found Reducto made the same kind of
    believable wrong values as Gemini 3.8 Flash reading page images, and more of them, but on 1940s federal records
    and synthetic tables. Here are the documents Reducto is built for: tables from S&P 500 companies' annual
    reports, with an answer key for every cell.

    **The data.** FinTabNet (IBM Research, 2020) is about 113,000 tables from S&P 500 annual reports, each with its
    cell grid and the text of every cell, taken from the PDF itself, so nothing was typed by hand. Its licence is
    CDLA-Permissive. We use IBM's own conversion to the OTSL format on Hugging Face, `docling-project/FinTabNet_OTSL`,
    pinned to one revision, and only the first file of its test split (5,199 tables, 142 MB), downloaded at run time.

    **One limit to keep in mind.** FinTabNet ships each table cropped from its page, not the page itself. So this
    tests reading a table, not finding it on a page of text.
    """)
    return


@app.cell
def _():
    REVISION = "1fe37f0f9478b4c571c51c5c4d11e3ef357e75c4"
    PARQUET_SHA256 = "fa4e457e3abe55eb6f41ea3b9ebb3bb2731e933f09d3dc28c9edbf882d79e734"
    _url = (
        f"https://huggingface.co/datasets/docling-project/FinTabNet_OTSL/resolve/{REVISION}/"
        "data/test-00000-of-00002-7d6f82c6161b0377.parquet"
    )
    _parquet = OUT / "test-00000.parquet"
    if not _parquet.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(_url, timeout=300) as _r:
            _parquet.write_bytes(_r.read())
    assert hashlib.sha256(_parquet.read_bytes()).hexdigest() == PARQUET_SHA256, "the FinTabNet file changed"
    tables = pq.read_table(_parquet).to_pylist()
    print(f"{len(tables):,} tables")
    return (tables,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The answer key

    Each table comes as OTSL tokens, one per grid position: `fcel` a cell with text, `ecel` an empty cell, `lcel`,
    `ucel` and `xcel` the rest of a cell merged left, up or both, and `nl` the end of a row. The cells' text comes in
    the same order as `fcel` and `ecel`. So the key is a grid: a merged cell's text sits in its top-left position and
    the positions it covers are empty. Header rows, rows that only name a group and total rows are all in the key.
    """)
    return


@app.cell
def _(tables):
    def grid(table: dict) -> list[list[str]]:
        cells, rows = iter(table["cells"][0]), [[]]
        for token in table["otsl"]:
            if token == "nl":
                rows.append([])
            else:
                rows[-1].append("".join(next(cells)["tokens"]) if token in ("fcel", "ecel") else "")
        return [r for r in rows if r]

    for _r in grid(tables[1])[:6]:
        print(_r)
    return (grid,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The sample

    102 tables, seeded, stratified two ways: by size (rows times columns, in thirds of the file) and by whether the
    table has a merged cell, which is how multi-level headers show up. That gives six groups of 17. Each table image
    is wrapped as a one-page PDF at 150 dpi, so the PDF pipelines and the image pipelines see the same pixels.
    """)
    return


@app.cell
def _(grid, tables):
    def size(t: dict) -> int:
        return t["rows"] * t["cols"]

    _sizes = sorted(size(t) for t in tables)
    _cuts = (_sizes[len(_sizes) // 3], _sizes[2 * len(_sizes) // 3])

    def stratum(t: dict) -> str:
        band = "small" if size(t) < _cuts[0] else "medium" if size(t) < _cuts[1] else "large"
        merged = any(tok in t["otsl"] for tok in ("lcel", "ucel", "xcel"))
        return f"{band}, {'merged cells' if merged else 'no merged cells'}"

    _rng = random.Random(141)
    sample = []
    for _s in sorted({stratum(t) for t in tables}):
        sample += _rng.sample([t for t in tables if stratum(t) == _s], 17)

    (OUT / "pdfs").mkdir(parents=True, exist_ok=True)
    KEYS, STRATA, TASKS = {}, {}, []
    for _t in sample:
        _name = _t["filename"].removesuffix(".png").replace(".pdf_", "-")
        _pdf = OUT / "pdfs" / f"{_name}.pdf"
        if not _pdf.exists():
            Image.open(io.BytesIO(_t["image"]["bytes"])).convert("RGB").save(_pdf, resolution=150)
        KEYS[_name], STRATA[_name] = grid(_t), stratum(_t)
        TASKS.append(
            Task(
                name=_name,
                pdf=_pdf,
                kind="table",
                ask=f"the financial table on this page, {_t['cols']} columns wide",
                pages=(1,),
                rules=(
                    f"Give every row, header rows included, top to bottom, each as exactly {_t['cols']} cells from "
                    "left to right. A cell that spans several columns goes in the leftmost of them, with '' in the "
                    "others; a cell that spans several rows goes in the top one. Keep rows that only name a group, "
                    "and subtotal and total rows. Join a cell's wrapped lines with spaces. Copy text and numbers as "
                    "printed, with $ and % signs. An empty cell is ''."
                ),
            )
        )
    print({_s: list(STRATA.values()).count(_s) for _s in sorted(set(STRATA.values()))})
    print(f"{sum(sum(c != '' for c in r) for k in KEYS.values() for r in k):,} non-empty key cells")
    return KEYS, STRATA, TASKS


@app.cell
def _(TASKS):
    mo.image(page_png(TASKS[0].pdf, 1).data, width=600)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The pipelines

    The same six as #136 (see `pipelines.py`, copied from `messy-document-parsing/`): Docling alone, Gemini 3.8 Flash
    given the PDF, Gemini given the page image, Docling's Markdown next to the image, Reducto Parse (r-1) and
    Reducto Extract with the same schema and prompt as Gemini. The prompt names the column count, as #136's names
    the columns, and says how merged cells go in the grid.

    The Gemini pipelines run twice on all 102 tables, into `run1/` and `run2/`, since #136 found answers change
    between runs. Docling is deterministic, so it runs once and run 2's "Docling, then Gemini" reuses its output.
    Reducto runs once on all 102; its second run is on the subset below, for a reason shown there.
    """)
    return


@app.cell
async def _(TASKS):
    OPEN_AND_REDUCTO = [
        "Docling alone",
        "Gemini, whole PDF",
        "Gemini, page by page",
        "Docling, then Gemini",
        "Reducto Parse",
        "Reducto Extract",
    ]
    run1 = await run_all(Runner(OUT / "run1"), OPEN_AND_REDUCTO, TASKS)
    run2 = await run_all(Runner(OUT / "run2", docling_out=OUT / "run1"), OPEN_AND_REDUCTO[1:4], TASKS)
    for (_n, _p), _r in (run1 | run2).items():
        if _r.error:
            print(f"{_n}, {_p}: {_r.error}")
    return OPEN_AND_REDUCTO, run1, run2


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Reducto answers a file it has seen from a cache

    Our first second run of Reducto came back identical to the first on all 102 tables, under new job IDs, in about
    0.2 seconds a table against 2 to 170 the first time. Reducto's docs don't mention a cache, but that's what it
    is. Below, the 22 subset tables go to Reducto Extract twice more: once on the same files (run 2) and once on
    copies with a comment line added after the end of each PDF (run 3). The pages are the same; the files' hashes
    aren't. So a real second read needs new bytes, and every second Reducto run in this spike uses such copies.
    """)
    return


@app.cell
async def _(TASKS, run1, score):
    SUBSET = random.Random(1412).sample(TASKS, 22)
    same = await run_all(Runner(OUT / "run2"), ["Reducto Extract"], SUBSET)
    run3 = await run_all(
        Runner(OUT / "run3"), ["Reducto Extract", "Reducto Deep Extract"], fresh_copies(SUBSET, OUT / "pdfs-run3")
    )
    _extract = [(n, r) for (n, p), r in run1.items() if p == "Reducto Extract" and (n, p) in same]
    _identical = sum(same[(n, "Reducto Extract")].output == r.output for n, r in _extract)
    _changed = sum(run3[(n, "Reducto Extract")].output != r.output for n, r in _extract)
    _right = [sum(score(n, run[(n, "Reducto Extract")])["right"] for n, _r in _extract) for run in (run1, same, run3)]
    cache_note = (
        f"Reducto Extract on the 22 subset tables. Same files again: {_identical} of 22 answers identical to run 1, "
        f"{sum(r.seconds for r in same.values()) / 22:.1f} seconds a table. New bytes: {_changed} of 22 answers "
        f"differ. Cells right: {_right[0]} in run 1, {_right[1]} on the same files, {_right[2]} on new bytes."
    )
    print(cache_note)
    return SUBSET, cache_note, run3, same


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Deep Extract and Gemini 4 Argon, on a subset fixed in advance

    Reducto Deep Extract runs Extract in an agentic loop that checks its answer against the document; it costs $40
    per 1,000 pages, twice Extract. Gemini 4 Argon is the strongest Gemini on OpenRouter, given the page image. Both
    run twice on the 22 tables, drawn with a seed before any pipeline ran, so not chosen by results. Reducto's
    second runs are run 3, on new bytes.
    """)
    return


@app.cell
async def _(SUBSET):
    deep1 = await run_all(Runner(OUT / "run1"), ["Reducto Deep Extract"], SUBSET)
    argon = [
        await run_all(Runner(OUT / f"run{i}", model=model_call.BIG), ["Gemini, page by page"], SUBSET) for i in (1, 2)
    ]
    return argon, deep1


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring

    #136's scorer: each key row is matched to the found row that agrees with it most, then compared cell by cell
    in column order. A cell is **right**, **wrong** (a value is there but isn't the key's, so it looks fine to a
    reader) or **missing**. Numbers compare by value and sign, so `(1,234)` and `-1234` agree; text matches if 85%
    similar. Only cells with text in the key are counted, so leaving an empty cell empty earns nothing. An **empty
    answer** is a table that came back with no values and no error: the silent failure.
    """)
    return


@app.cell
def _(KEYS):
    def score(name: str, result: Result) -> dict[str, int]:
        rows = result.output["rows"] if result.output else []
        return score_table(rows, KEYS[name], skip_empty=True)

    return (score,)


@app.cell
def _(OPEN_AND_REDUCTO, SUBSET, TASKS, argon, deep1, run1, run2, run3, score):
    _names = [t.name for t in TASKS]
    main_table, tallies = two_run_table(OPEN_AND_REDUCTO, _names, score, [run1, run2])

    def as_argon(run: dict) -> dict:
        return {(n, "Argon, page by page"): r for (n, _p), r in run.items()}

    _subset_runs = [run1 | deep1 | as_argon(argon[0]), run2 | run3 | as_argon(argon[1])]
    _subset_pipelines = ["Gemini, page by page", "Argon, page by page", "Reducto Extract", "Reducto Deep Extract"]
    subset_table, subset_tallies = two_run_table(_subset_pipelines, [t.name for t in SUBSET], score, _subset_runs)
    mo.md(f"**All 102 tables**\n\n{main_table}\n\n**The 22-table subset**\n\n{subset_table}")
    return main_table, subset_table, subset_tallies, tallies


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Where Reducto wins and loses, by kind of table

    Share of key cells right in each group, both runs pooled, for Reducto Extract against the best open pipeline in
    that group.
    """)
    return


@app.cell
def _(OPEN_AND_REDUCTO, STRATA, run1, run2, score):
    _lines = [
        "| Tables | Best open pipeline | Its cells right | Reducto Extract | Reducto Parse |",
        "|---|---|---|---|---|",
    ]
    by_stratum = {}
    for _s in sorted(set(STRATA.values())):
        _names = [n for n, s in STRATA.items() if s == _s]

        def share(p: str, names: list[str] = _names) -> float:
            found = [score(n, run[(n, p)]) for run in (run1, run2) for n in names if (n, p) in run]
            return sum(f["right"] for f in found) / max(sum(f["cells"] for f in found), 1)

        _shares = {p: share(p) for p in OPEN_AND_REDUCTO}
        _best = max(OPEN_AND_REDUCTO[:4], key=_shares.__getitem__)
        by_stratum[_s] = _shares
        _lines.append(
            f"| {_s} | {_best} | {_shares[_best]:.1%} | {_shares['Reducto Extract']:.1%} "
            f"| {_shares['Reducto Parse']:.1%} |"
        )
    stratum_table = "\n".join(_lines)
    mo.md(stratum_table)
    return by_stratum, stratum_table


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Where Reducto Extract's cells go: the shape of the answer

    Most of Reducto Extract's lost cells aren't misread digits. The table comes back the wrong shape: empty, all
    in one row, short of rows, or with rows of the wrong width. Counted for each pipeline's run 1 against the key's
    rows and columns.
    """)
    return


@app.cell
def _(KEYS, OPEN_AND_REDUCTO, run1):
    def shape(rows: list[list[str]], key: list[list[str]]) -> str:
        if not rows:
            return "empty"
        if len(rows) == 1 and len(key) > 2:
            return "one row"
        if len(rows) < 0.8 * len(key):
            return "under 80% of the rows"
        if any(len(r) != len(key[0]) for r in rows):
            return "a row of the wrong width"
        return "right shape"

    _kinds = ["right shape", "empty", "one row", "under 80% of the rows", "a row of the wrong width"]
    _lines = ["| Pipeline | " + " | ".join(_kinds) + " |", "|---" * (len(_kinds) + 1) + "|"]
    for _p in OPEN_AND_REDUCTO[1:]:
        _shapes = [shape((r.output or {}).get("rows", []), KEYS[n]) for (n, p), r in run1.items() if p == _p]
        _lines.append(f"| {_p} | " + " | ".join(str(_shapes.count(k)) for k in _kinds) + " |")
    shape_table = "\n".join(_lines)
    mo.md(shape_table)
    return (shape_table,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The wrong values, by example

    The tables where a pipeline gave the most believable wrong values, with a few of them next to the key.
    """)
    return


@app.cell
def _(KEYS, run1, run2, score):
    _worst = sorted(
        ((score(n, r)["wrong"], n, p, i) for i, run in enumerate((run1, run2), 1) for (n, p), r in run.items()),
        reverse=True,
    )[:8]
    for _w, _n, _p, _i in _worst:
        print(f"{_w:3} wrong: {_n}, {_p}, run {_i} ({sum(c != '' for r in KEYS[_n] for c in r)} key cells)")
    return


@app.cell
def _(
    STRATA,
    argon,
    by_stratum,
    cache_note,
    deep1,
    main_table,
    run1,
    run2,
    run3,
    same,
    shape_table,
    stratum_table,
    subset_table,
    subset_tallies,
    tallies,
):
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "fintabnet.md").write_text(
        f"# FinTabNet, 102 tables\n\n{main_table}\n\n## 22-table subset\n\n{subset_table}\n\n"
        f"## By kind of table\n\n{stratum_table}\n\n## Shape of each answer, run 1\n\n{shape_table}\n\n"
        f"## Reducto's cache\n\n{cache_note}\n"
    )
    (OUT / "results.json").write_text(
        json.dumps(
            {
                "tallies": {f"{p}, run {i + 1}": t for (p, i), t in tallies.items()},
                "subset_tallies": {f"{p}, run {i + 1}": t for (p, i), t in subset_tallies.items()},
                "by_stratum": by_stratum,
                "strata": STRATA,
            },
            indent=1,
        )
    )
    _spent = sum(r.usd for run in (run1, run2, run3, same, deep1, *argon) for r in run.values())
    print(f"cost of every call in this notebook: ${_spent:.2f}")
    return


if __name__ == "__main__":
    app.run()
