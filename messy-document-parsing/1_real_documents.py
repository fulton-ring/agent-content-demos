import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import hashlib
    import json
    import os
    import urllib.request
    from pathlib import Path

    import marimo as mo

    import model_call
    from pipelines import (
        PIPELINES,
        Result,
        Runner,
        Task,
        score_fields,
        score_table,
        word_error_rate,
    )

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("MESSY_OUTPUT_DIR", HERE / "output")) / "real"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 1. Real messy documents

    **The question.** #128 found that Gemini 3.8 Flash reading page images matched what Reducto sells on two FEMA
    flood studies. Those were close to easy mode. Where do the same open pipelines break on really messy public
    records: sideways tables, a table whose second page has no header, microfilm with four pages per sheet,
    handwriting under a stamp, and a grey 1958 halftone?

    **The documents.** Seven US federal documents, all public domain, downloaded at run time and hash-checked
    (nothing is committed). Each has one region keyed by hand from a 300 dpi render, in `real_key.json`, with a note
    on how it was checked (sums, symmetry, or the IRS's own extract).
    """)
    return


@app.cell
def _():
    DOCS = {  # name: (URL, sha256)
        "census-1951": (
            "https://www2.census.gov/prod2/statcomp/documents/1951-02.pdf",
            "d7666798491d3c2af8d745fcf665a9b3732c78694b335aed4c395b29b669ca8c",
        ),
        "usgs-of-49-60": (
            "https://pubs.usgs.gov/of/1949/0060/report.pdf",
            "7748c9cc297f21e81f2c5afe4e4df07f0274d1c56a0f1f2fd28729b09b3c7c2a",
        ),
        "naca-824": (
            "https://ntrs.nasa.gov/api/citations/19930090976/downloads/19930090976.pdf",
            "9f27283b704821192fc9dba4ed625f62002903b5127bc869cd04ac0a5cc54efd",
        ),
        "usgs-of-61-50": (
            "https://pubs.usgs.gov/of/1961/0050/report.pdf",
            "4def214839f905d45204795cecdb1087be0b88207eb682f3e0db140699bc5131",
        ),
        "irs-990ez-2017": (
            "https://apps.irs.gov/pub/epostcard/cor/465674229_201712_990EZ_2018050215281839.pdf",
            "3bb765006ca3add423106bd84e2e443a28e026cc6a85b791978bd44b047ae8d6",
        ),
        "state-foia-c09001239": (
            "https://foia.state.gov/DOCUMENTS/FOIA_Micro_Apr2024/F-1979-02932/DOC_0C09001239/C09001239.pdf",
            "a30fd39facae812c4cea6c847773fb4802ef253078ac0f6727be5fdd24b6775b",
        ),
        "usgs-wsp-1050": (
            "https://pubs.usgs.gov/wsp/1050/report.pdf",
            "55c24de4538e4e10fb67dcc7779c255eb41a209d18d15471d080eec15a6456b4",
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for _name, (_url, _sha) in DOCS.items():
        _path = OUT / f"{_name}.pdf"
        if _path.exists() and hashlib.sha256(_path.read_bytes()).hexdigest() == _sha:
            continue
        _request = urllib.request.Request(_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(_request, timeout=600) as _r:
            _data = _r.read()
        if (_got := hashlib.sha256(_data).hexdigest()) != _sha:
            raise RuntimeError(f"{_name}: the file at {_url} has changed (sha256 {_got})")
        _path.write_bytes(_data)
    print({n: f"{(OUT / f'{n}.pdf').stat().st_size / 1e6:.1f} MB" for n in DOCS})
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What each pipeline is asked

    One task per keyed region: a table read cell by cell, the 990-EZ's lines 1 to 21, or the FOIA letter
    transcribed. The two NACA tables come from the same page of ten small tables. Every prompt names the PDF page,
    so the pipelines are compared on reading, not on finding the page; #128 already showed that routing on OCR text
    fails silently.
    """)
    return


@app.cell
def _():
    KEY = json.loads((HERE / "real_key.json").read_text())

    def pdf_of(name: str) -> Path:
        return OUT / f"{'naca-824' if name.startswith('naca-824') else name}.pdf"

    TASKS = [
        Task(
            name=name,
            pdf=pdf_of(name),
            kind=k["kind"],
            ask=k["ask"],
            pages=tuple(k["pages"]),
            where=f"It is on PDF page{'s' if len(k['pages']) > 1 else ''} {' and '.join(map(str, k['pages']))}.",
        )
        for name, k in KEY.items()
    ]
    print([t.name for t in TASKS])
    return KEY, TASKS


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Four pipelines

    - **Docling alone**: its tables on the keyed pages, header rows kept, or its Markdown for the letter. It runs on
      the keyed pages only, since Docling on CPU takes about 7 seconds a page and the long reports have up to 492.
    - **Gemini, whole PDF**: Gemini 3.8 Flash gets the whole file. A file over 15 MB can't be sent in one request.
    - **Gemini, page by page**: each keyed page alone, and the answers stitched in page order.
    - **Docling, then Gemini**: Docling's Markdown of each keyed page next to the page image.

    They're defined in `pipelines.py`, shared with notebook 2. Answers are saved in `output/answers/` and reused.
    """)
    return


@app.cell
async def _(TASKS):
    async def run_all(runner: Runner, pipelines: list[str], tasks: list[Task]) -> dict[tuple[str, str], Result]:
        jobs = [(t, p) for t in tasks for p in pipelines]
        results = await asyncio.gather(*(PIPELINES[p](t, runner) for t, p in jobs))
        return {(t.name, p): r for (t, p), r in zip(jobs, results, strict=True)}

    flash = await run_all(Runner(OUT.parent), list(PIPELINES), TASKS)
    for (_task, _pipeline), _r in flash.items():
        if _r.error:
            print(f"{_task}, {_pipeline}: {_r.error}")
    return flash, run_all


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring

    - **Tables**: each key row against the found row that agrees with it most; each cell is **right**, **wrong** (a
      value is there and it isn't the key's, which looks fine to a reader), or **missing** (blank, or the row wasn't
      found). Numbers compare by value and sign (`(5)`, `<5>` and `-5` agree; `.5` and `0.50` agree); dashes and
      leader dots count as empty; text matches loosely (85% similar). **Extra rows** are found rows matching no key
      row: header rows, rows from the wrong table, or rows split in two.
    - **990-EZ**: each of 28 lines right, wrong or missing, the same way.
    - **The letter**: word error rate after lowercasing and dropping punctuation.
    """)
    return


@app.cell
def _(KEY):
    def score(task: Task, result: Result) -> dict:
        key = KEY[task.name]
        if result.output is None:
            return {"failed": result.error}
        if task.kind == "table":
            return score_table(result.output["rows"], key["rows"])
        if task.kind == "fields":
            return score_fields(result.output["lines"], key["fields"])
        return {"wer": word_error_rate(result.output["text"], key["text"])}

    def row(task: Task, pipeline: str, result: Result) -> str:
        s, pages = score(task, result), max(result.pages_read, 1)
        if "failed" in s:
            measure = f"failed: {s['failed'][:60]} | | |"
        elif "wer" in s:
            measure = f"word error rate {s['wer']:.1%} | | |"
        else:
            measure = (
                f"{s['right']} of {s['cells']} ({s['right'] / s['cells']:.0%}) | {s['wrong']} | {s['missing']} "
                f"| {s['extra_rows']}"
            )
        seconds = (result.docling_seconds + result.seconds) / pages
        return f"| {task.name} | {pipeline} | {measure} | ${result.usd / pages:.4f} | {seconds:.1f} |"

    HEADER = (
        "| Document | Pipeline | Right | Wrong | Missing | Extra rows | Cost per page | Seconds per page |\n"
        "|---|---|---|---|---|---|---|---|"
    )
    return HEADER, row, score


@app.cell
def _(HEADER, TASKS, flash, row):
    real_table = "\n".join([HEADER, *(row(t, p, flash[(t.name, p)]) for t in TASKS for p in PIPELINES)])
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "real_documents.md").write_text(real_table + "\n")
    print(real_table)
    mo.md("## Results, Gemini 3.8 Flash\n\n" + real_table)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Does a bigger model fix the failures?

    A failure case is a task where a Gemini pipeline got under 95% of cells right, or a word error rate over 5%.
    Those pipelines are run again on Gemini 4 Argon, the strongest Gemini on OpenRouter, at about 2.4 times Flash's
    price per token. If Argon fixes it, the fix is a bigger model; if not, it needs a check, a different input, or
    fine-tuning.
    """)
    return


@app.cell
async def _(HEADER, TASKS, flash, row, run_all, score):
    def failed(task: Task, pipeline: str) -> bool:
        s = score(task, flash[(task.name, pipeline)])
        if "failed" in s:
            return not s["failed"].startswith("the PDF is")
        if "wer" in s:
            return s["wer"] > 0.05
        return s["right"] / s["cells"] < 0.95

    _gemini = [p for p in PIPELINES if "Gemini" in p]
    failures = [(t, p) for t in TASKS for p in _gemini if failed(t, p)]
    big: dict[tuple[str, str], Result] = {}
    for _t, _p in failures:
        big |= await run_all(Runner(OUT.parent, model=model_call.BIG), [_p], [_t])
    big_table = "\n".join(
        [HEADER]
        + [
            row(t, f"{p}, Flash", flash[(t.name, p)]) + "\n" + row(t, f"{p}, Argon", big[(t.name, p)])
            for t, p in failures
        ]
    )
    (HERE / "results" / "real_documents_bigger_model.md").write_text(big_table + "\n")
    print(big_table)
    mo.md("## Failure cases, Flash against Argon\n\n" + big_table)
    return (big,)


@app.cell
def _(TASKS, big, flash):
    _rows = []
    for _model, _results in (("flash", flash), ("argon", big)):
        for (_task, _pipeline), _r in _results.items():
            _rows.append({"model": _model, "task": _task, "pipeline": _pipeline, **_r.__dict__})
    (OUT / "results.json").write_text(json.dumps(_rows, indent=1, default=str))
    print(f"{len(TASKS)} tasks, {len(_rows)} pipeline runs saved to {OUT / 'results.json'}")
    return


if __name__ == "__main__":
    app.run()
