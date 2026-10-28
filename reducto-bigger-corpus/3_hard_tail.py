import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import shutil
    import subprocess
    from pathlib import Path

    import marimo as mo

    import model_call
    from pipelines import Result, Runner, Task, run_all, score_fields, score_table, word_error_rate

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("BIGGER_OUTPUT_DIR", HERE / "output")) / "hard-tail"
    MESSY = HERE.parent / "messy-document-parsing"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # #136's documents, run twice

    **The question.** #136 (`messy-document-parsing/`) ran six pipelines once on seven messy real documents and 39
    synthetic broken tables, and found Reducto made the same kind of believable wrong values as Gemini, and more.
    Its reviewer's second run moved Reducto Extract's census score from 95% to 14%. This notebook runs #136
    unchanged, twice, to see how much of that holds from run to run, and adds Reducto Deep Extract and Gemini 4
    Argon on the seven real documents.

    **How.** #136's folder is copied into `output/hard-tail/code/` and its `run.sh` is run twice, each time into
    its own output folder. So its documents, keys, generator, prompts, scorer and pipelines are exactly #136's, and
    nothing in `messy-document-parsing/` changes. A run takes about 40 minutes and $6 ($3.70 Gemini, $2.30 Reducto);
    finished runs are reused.
    """)
    return


@app.cell
def _():
    _code = OUT / "code"
    if not _code.exists():
        shutil.copytree(MESSY, _code, ignore=shutil.ignore_patterns("output", ".venv", "__pycache__"))
    for _i in (1, 2):
        _run = OUT / f"run{_i}"
        if not ((_run / "real" / "results.json").exists() and (_run / "synthetic" / "results.json").exists()):
            print(f"running #136, run {_i}")
            _done = subprocess.run(["./run.sh"], cwd=_code, env=os.environ | {"MESSY_OUTPUT_DIR": str(_run)})
            assert _done.returncode == 0, f"#136's run.sh failed on run {_i}"
    real = [json.loads((OUT / f"run{i}" / "real" / "results.json").read_text()) for i in (1, 2)]
    synthetic = [json.loads((OUT / f"run{i}" / "synthetic" / "results.json").read_text()) for i in (1, 2)]
    print(
        f"{len(real[0])} and {len(real[1])} real-document runs; {len(synthetic[0])} and {len(synthetic[1])} synthetic"
    )
    return real, synthetic


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The seven real documents

    #136's real-document runs save each pipeline's answer, so each is scored here with #136's scorer and key
    (`real_key.json`): the share of key cells right, then wrong and missing; or the word error rate for the letter.
    """)
    return


@app.cell
def _():
    KEY = json.loads((MESSY / "real_key.json").read_text())

    def score(task: str, output: dict | None) -> str:
        key = KEY[task]
        if output is None:
            return "failed"
        if key["kind"] == "text":
            return f"WER {word_error_rate(output['text'], key['text']):.1%}"
        s = (
            score_table(output["rows"], key["rows"])
            if key["kind"] == "table"
            else score_fields(output["lines"], key["fields"])
        )
        return f"{s['right'] / s['cells']:.0%}, {s['wrong']} wrong"

    return KEY, score


@app.cell
def _(KEY, real, score):
    _pipelines = list(dict.fromkeys(r["pipeline"] for r in real[0]))
    _lines = ["| Document | " + " | ".join(_pipelines) + " |", "|---" * (len(_pipelines) + 1) + "|"]
    for _task in KEY:
        _cells = []
        for _p in _pipelines:
            _runs = [next(r for r in run if r["task"] == _task and r["pipeline"] == _p and r["model"] == "flash")
                     for run in real]  # fmt: skip
            _cells.append(" / ".join(score(_task, r["output"]) for r in _runs))
        _lines.append(f"| {_task} | " + " | ".join(_cells) + " |")
    real_table = "\n".join(_lines)
    mo.md("Run 1 / run 2, Flash for the Gemini pipelines.\n\n" + real_table)
    return (real_table,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Deep Extract and Argon on the real documents

    The seven real documents (eight tasks, since one NACA page has two keyed tables) are this corpus's share of
    the 50-document subset that gets Reducto Deep Extract and Gemini 4 Argon, page image, twice each. They're run
    with `pipelines.py`, our copy of #136's, on the same PDFs, prompts and schema, into the same run folders, so
    where #136 already ran Argon page by page on a document, that answer is reused rather than paid for twice.
    """)
    return


@app.cell
async def _(KEY):
    TASKS = [
        Task(
            name=name,
            pdf=OUT / "run1" / "real" / f"{'naca-824' if name.startswith('naca-824') else name}.pdf",
            kind=k["kind"],
            ask=k["ask"],
            pages=tuple(k["pages"]),
            where=f"It is on PDF page{'s' if len(k['pages']) > 1 else ''} {' and '.join(map(str, k['pages']))}.",
        )
        for name, k in KEY.items()
    ]
    deep = [await run_all(Runner(OUT / f"run{i}"), ["Reducto Deep Extract"], TASKS) for i in (1, 2)]
    argon = [
        await run_all(Runner(OUT / f"run{i}", model=model_call.BIG), ["Gemini, page by page"], TASKS) for i in (1, 2)
    ]
    return TASKS, argon, deep


@app.cell
def _(TASKS, argon, deep, real, score):
    def flash_extract(task: str, i: int) -> dict:
        return next(r for r in real[i] if r["task"] == task and r["pipeline"] == "Reducto Extract")

    _lines = [
        "| Document | Reducto Extract | Reducto Deep Extract | Argon, page by page | Deep Extract cost per page |",
        "|---|---|---|---|---|",
    ]
    for _t in TASKS:
        _ext = " / ".join(score(_t.name, flash_extract(_t.name, i)["output"]) for i in (0, 1))
        _deep = " / ".join(score(_t.name, d[(_t.name, "Reducto Deep Extract")].output) for d in deep)
        _argon = " / ".join(score(_t.name, a[(_t.name, "Gemini, page by page")].output) for a in argon)
        _r: Result = deep[0][(_t.name, "Reducto Deep Extract")]
        _lines.append(f"| {_t.name} | {_ext} | {_deep} | {_argon} | ${_r.usd / max(_r.pages_read, 1):.3f} |")
    for _d in deep:
        for (_n, _p), _r in _d.items():
            if _r.error:
                print(f"{_n}, {_p}: {_r.error}")
    subset_table = "\n".join(_lines)
    mo.md("Run 1 / run 2.\n\n" + subset_table)
    return (subset_table,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The 39 broken tables

    #136's synthetic runs save scores, not answers. Summed over the 39 documents, by pipeline, for each run, Flash
    only (#136's Argon re-runs on its failures are left out, since which documents get one depends on the run).
    """)
    return


@app.cell
def _(synthetic):
    _pipelines = list(dict.fromkeys(r["pipeline"] for r in synthetic[0]))
    _lines = [
        "| Pipeline | Right, run 1 | Right, run 2 | Wrong | Missing | Cost, both runs |",
        "|---|---|---|---|---|---|",
    ]
    synthetic_tallies = {}
    for _p in _pipelines:
        _t = [
            {k: sum(r[k] for r in run if r["pipeline"] == _p and r["model"] == "flash")
             for k in ("cells", "right", "wrong", "missing", "usd")}
            for run in synthetic
        ]  # fmt: skip
        synthetic_tallies[_p] = _t
        _lines.append(
            f"| {_p} | {_t[0]['right'] / _t[0]['cells']:.1%} | {_t[1]['right'] / _t[1]['cells']:.1%} "
            f"| {_t[0]['wrong']} / {_t[1]['wrong']} | {_t[0]['missing']} / {_t[1]['missing']} "
            f"| ${_t[0]['usd'] + _t[1]['usd']:.2f} |"
        )
    _modes = sorted({r["document"][:3] for r in synthetic[0]})
    _lines += ["", "Share right by failure mode, run 1 / run 2:", ""]
    _lines += ["| Mode | " + " | ".join(_pipelines) + " |", "|---" * (len(_pipelines) + 1) + "|"]
    for _m in _modes:
        _cells = []
        for _p in _pipelines:
            _shares = []
            for run in synthetic:
                _rows = [r for r in run if r["pipeline"] == _p and r["model"] == "flash" and r["document"][:3] == _m]
                _shares.append(f"{sum(r['right'] for r in _rows) / max(sum(r['cells'] for r in _rows), 1):.0%}")
            _cells.append(" / ".join(_shares))
        _lines.append(f"| {_m} | " + " | ".join(_cells) + " |")
    synthetic_table = "\n".join(_lines)
    mo.md(synthetic_table)
    return synthetic_table, synthetic_tallies


@app.cell
def _(argon, deep, real, real_table, subset_table, synthetic, synthetic_table, synthetic_tallies):
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "hard_tail.md").write_text(
        f"# #136's documents, run twice\n\n## Real documents, run 1 / run 2\n\n{real_table}\n\n"
        f"## Deep Extract and Argon, run 1 / run 2\n\n{subset_table}\n\n## Broken tables\n\n{synthetic_table}\n"
    )
    (OUT / "results.json").write_text(json.dumps({"synthetic": synthetic_tallies}, indent=1))
    _spent = sum(float(r["usd"]) for runs in (real, synthetic) for run in runs for r in run)
    _spent += sum(r.usd for runs in (deep, argon) for run in runs for r in run.values())
    print(f"cost of both #136 runs plus Deep Extract and Argon: ${_spent:.2f}")
    return


if __name__ == "__main__":
    app.run()
