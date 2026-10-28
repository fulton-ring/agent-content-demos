import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import csv
    import io
    import json
    import os
    import random
    import re
    import time
    import urllib.error
    import urllib.request
    import zipfile
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import marimo as mo
    import pypdfium2 as pdfium

    import model_call
    from pipelines import Result, Runner, Task, page_png, run_all, two_run_table

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("BIGGER_OUTPUT_DIR", HERE / "output")) / "990"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Scanned IRS Form 990-EZ returns

    **The question.** Reducto says it handles forms, scans and handwriting. #136 had one handwritten 990-EZ, where
    Reducto Extract put lines 12 to 21 one line off. Here are 100 real paper-filed returns, typed and handwritten,
    with an answer key typed by someone else.

    **The data.** As in `scanned-990ez-extraction/` (#58), whose sampling and answer key this copies without
    changing that folder:

    - **Answer key**: the IRS Statistics of Income (SOI) 990-EZ extract for 2018, paper returns only. IRS staff typed
      it from the same paper returns.
    - **Scans**: found through ProPublica's Nonprofit Explorer API and downloaded from the IRS at run time.
    - **The 20 Part I amounts on page 1** that SOI also has: lines 1 to 9, 17, 18, 20 and 21.
    - **`adjudications.json`**: #58's file of fields where SOI differs from the scan, each checked on the scan, plus
      the fields this run turned up (see "Checking the answer key").
    """)
    return


@app.cell
def _():
    _zip = OUT / "18eoextractez.zip"
    if not _zip.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen("https://www.irs.gov/pub/irs-soi/18eoextractez.zip", timeout=120) as _r:
            _zip.write_bytes(_r.read())
    with zipfile.ZipFile(_zip) as _z, _z.open("18eoextractez.csv") as _f:
        _rows = list(csv.DictReader(io.TextIOWrapper(_f, encoding="utf-8-sig")))
    # #58's seeded draw of 220 paper returns, unchanged, so its adjudications apply.
    sample = random.Random(990).sample([r for r in _rows if r["elf"] == "P"], 220)
    print(f"{len(_rows):,} returns in the extract; 220 paper returns drawn")
    return (sample,)


@app.cell
def _(sample):
    def fetch(url: str) -> bytes:
        """GET with three attempts. A 404 isn't retried."""
        request = urllib.request.Request(url, headers={"User-Agent": "fulton-ring-990ez-spike/0.1"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    return response.read()
            except urllib.error.HTTPError as e:
                if e.code == 404 or attempt == 2:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
            time.sleep(5 * (attempt + 1))
        raise AssertionError("unreachable")

    def page_one(row: dict) -> Path | str:
        """#58's lookup: ProPublica names the image file, the IRS serves it. Returns page 1 as a PDF, or why not."""
        name = f"{row['ein']}_{row['tax_pd']}"
        pdf = OUT / "pdfs" / f"{name}.pdf"
        if pdf.exists():
            return pdf
        try:
            org = json.loads(
                fetch(f"https://projects.propublica.org/nonprofits/api/v2/organizations/{row['ein']}.json")
            )
        except urllib.error.HTTPError as e:
            return f"ProPublica lookup: HTTP {e.code}"
        filings = org.get("filings_with_data", []) + org.get("filings_without_data", [])
        urls = [f["pdf_url"] for f in filings if str(f["tax_prd"]) == row["tax_pd"] and f.get("pdf_url")]
        if not urls:
            return "ProPublica lists no image for this tax period"
        try:
            data = fetch(f"https://apps.irs.gov/pub/epostcard/cor/{urls[0].split('%2F')[-1]}")
        except urllib.error.HTTPError as e:
            return f"IRS download: HTTP {e.code}"
        if not data.startswith(b"%PDF"):
            return "IRS download: not a PDF"
        first = pdfium.PdfDocument.new()
        first.import_pages(pdfium.PdfDocument(data), [0])
        first.save(pdf)
        return pdf

    (OUT / "pdfs").mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as _pool:
        _found = list(_pool.map(page_one, sample))
    _failed = [f for f in _found if isinstance(f, str)]
    print(f"{len(_found) - len(_failed)} of 220 downloaded; {len(_failed)} failed: {sorted(set(_failed))}")
    downloaded = [(row, f) for row, f in zip(sample, _found, strict=True) if isinstance(f, Path)]
    return (downloaded,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The returns and the prompt

    The first 100 returns of the draw that downloaded, each as a one-page PDF of page 1. Every pipeline is asked for
    the same 20 lines, with #136's form schema (line number and amount as written).
    """)
    return


@app.cell
def _(downloaded):
    LINES = ["1", "2", "3", "4", "5a", "5b", "5c", "6a", "6b", "6c", "6d", "7a", "7b", "7c", "8", "9"]
    LINES += ["17", "18", "20", "21"]
    SOI_COLUMN = dict(
        zip(
            LINES,
            "totcntrbs prgmservrev duesassesmnts othrinvstinc grsamtsalesastothr basisalesexpnsothr gnsaleofastothr "
            "grsincgaming grsrevnuefndrsng direxpns netincfndrsng grsalesminusret costgoodsold grsprft othrevnue "
            "totrevnue totexpns totexcessyr othrchgsnetassetfnd networthend".split(),
            strict=True,
        )
    )
    RETURNS = downloaded[:100]
    TASKS = [
        Task(
            name=pdf.stem,
            pdf=pdf,
            kind="fields",
            ask=(
                "This is page 1 of an IRS Form 990-EZ. Give the amount written in the right-hand column on each of "
                f"Part I's lines {', '.join(LINES)}, exactly as written, or '' if the line is empty. Line 6b is the "
                "amount in the 6b box."
            ),
            pages=(1,),
        )
        for _row, pdf in RETURNS
    ]
    mo.image(page_png(TASKS[0].pdf, 1).data, width=600)
    return LINES, RETURNS, SOI_COLUMN, TASKS


@app.cell
async def _(TASKS):
    PIPELINES_990 = ["Gemini, whole PDF", "Gemini, page by page", "Docling, then Gemini", "Reducto Extract"]
    run1 = await run_all(Runner(OUT / "run1"), PIPELINES_990, TASKS)
    run2 = await run_all(Runner(OUT / "run2", docling_out=OUT / "run1"), PIPELINES_990, TASKS)
    SUBSET = random.Random(1412).sample(TASKS, 20)
    deep = [await run_all(Runner(OUT / f"run{i}"), ["Reducto Deep Extract"], SUBSET) for i in (1, 2)]
    argon = [
        await run_all(Runner(OUT / f"run{i}", model=model_call.BIG), ["Gemini, page by page"], SUBSET) for i in (1, 2)
    ]
    for (_n, _p), _r in (run1 | run2).items():
        if _r.error:
            print(f"{_n}, {_p}: {_r.error}")
    return PIPELINES_990, SUBSET, argon, deep, run1, run2


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Docling alone and Reducto Parse don't run here: neither can put an amount on a form line without a model. Deep
    Extract and Gemini 4 Argon (page image) run twice on 20 returns drawn with a seed before any pipeline ran.

    ## Reading amounts

    #58's rules, which follow SOI's: an empty box, a dash or "NONE" is 0; cents are dropped, not rounded; a
    trailing one or two digits after a space are cents. An amount is **right** if it equals the key, **missing** if
    the line came back empty where the key isn't 0, and **wrong** otherwise: a believable number that isn't the one
    on the form.
    """)
    return


@app.cell
def _():
    def to_number(text: str) -> int | None:
        """#58's reading of an amount as SOI keys it, or None if it can't be read as one."""
        text = text.upper().replace("$", "").replace(",", "").strip().rstrip(".").strip()
        if text in ("", "-", "-0-", "--", "NONE", "N/A", "NA", "0"):
            return 0
        negative = text.startswith(("(", "-", "<")) or text.endswith((")", ">"))
        text = re.sub(r"[()<>\-]", "", text).strip().rstrip(".")
        text = re.sub(r"[.\s]\d{1,2}$", "", text).strip()
        if not re.fullmatch(r"\d+", text.replace(" ", "")):
            return None
        number = int(text.replace(" ", ""))
        return -number if negative else number

    def lines_of(result: Result) -> dict[str, str]:
        found = result.output["lines"] if result.output else []
        return {re.sub(r"[^0-9a-z]", "", f["line"].lower().replace("line", "")): f["amount"] for f in found}

    return lines_of, to_number


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Checking the answer key

    SOI is a good key but not a perfect one: #58 found it differs from the scan on 1.4% of fields, mostly where SOI
    recomputed a total or moved an amount between lines. #58 checked those fields on the scan and wrote down what
    is printed, in `adjudications.json`; we take its value where there is one, and SOI's otherwise.

    Any field where two or more pipelines agree with each other but not with the key is either a shared misreading
    or a key error, so it was checked on the scan too. Those not yet decided are written to
    `output/990/to_adjudicate.json`; the decisions are added to `adjudications.json` with the note `#141`.
    """)
    return


@app.cell
def _(LINES, PIPELINES_990, RETURNS, SOI_COLUMN, lines_of, run1, run2, to_number):
    _decided = {(a["page"], a["field"]): a["scan"] for a in json.loads((HERE / "adjudications.json").read_text())}
    TRUTH = {
        (pdf.stem, line): _decided.get((pdf.stem, f"line_{line}"), int(row[SOI_COLUMN[line]]))
        for row, pdf in RETURNS
        for line in LINES
    }
    _undecided = []
    for (_page, _line), _truth in TRUTH.items():
        _reads = [to_number(lines_of(run[(_page, p)]).get(_line, "")) for run in (run1, run2) for p in PIPELINES_990]
        _common = max(set(_reads) - {_truth, None}, key=_reads.count, default=None)
        if _common is not None and _reads.count(_common) >= 2 and (_page, f"line_{_line}") not in _decided:
            _undecided.append({"page": _page, "field": f"line_{_line}", "key": _truth, "read": _common})
    (OUT / "to_adjudicate.json").write_text(json.dumps(_undecided, indent=1))
    print(f"{len(_decided)} decisions in adjudications.json; {len(_undecided)} fields still to check on the scan")
    return (TRUTH,)


@app.cell
def _(LINES, TRUTH, lines_of, to_number):
    def score(name: str, result: Result) -> dict[str, int]:
        counts = {"cells": len(LINES), "right": 0, "wrong": 0, "missing": 0}
        found = lines_of(result)
        for line in LINES:
            text, truth = found.get(line, ""), TRUTH[(name, line)]
            outcome = "right" if to_number(text) == truth else "missing" if text.strip() == "" else "wrong"
            counts[outcome] += 1
        return counts

    return (score,)


@app.cell
def _(PIPELINES_990, SUBSET, TASKS, argon, deep, run1, run2, score):
    _names = [t.name for t in TASKS]
    main_table, tallies = two_run_table(PIPELINES_990, _names, score, [run1, run2])
    _subset_runs = [
        run | d | {(n, "Argon, page by page"): r for (n, _p), r in a.items()}
        for run, d, a in ((run1, deep[0], argon[0]), (run2, deep[1], argon[1]))
    ]
    _subset_pipelines = ["Gemini, page by page", "Argon, page by page", "Reducto Extract", "Reducto Deep Extract"]
    subset_table, subset_tallies = two_run_table(_subset_pipelines, [t.name for t in SUBSET], score, _subset_runs)
    mo.md(f"**All 100 returns, 2,000 fields**\n\n{main_table}\n\n**The 20-return subset**\n\n{subset_table}")
    return main_table, subset_table, subset_tallies, tallies


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Which lines go wrong

    Wrong values by line, both runs pooled. A wrong value on a total (lines 9, 17, 18, 21) is the one most likely
    to be used.
    """)
    return


@app.cell
def _(LINES, PIPELINES_990, TASKS, TRUTH, lines_of, run1, run2, to_number):
    _lines = ["| Line | " + " | ".join(PIPELINES_990) + " |", "|---" * (len(PIPELINES_990) + 1) + "|"]
    for _line in LINES:
        _wrong = []
        for _p in PIPELINES_990:
            _reads = [(lines_of(run[(t.name, _p)]).get(_line, ""), t.name) for run in (run1, run2) for t in TASKS]
            _wrong.append(sum(x.strip() != "" and to_number(x) != TRUTH[(n, _line)] for x, n in _reads))
        _lines.append(f"| {_line} | " + " | ".join(map(str, _wrong)) + " |")
    line_table = "\n".join(_lines)
    mo.md(line_table)
    return (line_table,)


@app.cell
def _(line_table, main_table, subset_table, subset_tallies, tallies):
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "scanned_990s.md").write_text(
        f"# Scanned 990-EZ, 100 returns\n\n{main_table}\n\n## 20-return subset\n\n{subset_table}\n\n"
        f"## Wrong values by line, both runs\n\n{line_table}\n"
    )
    (OUT / "results.json").write_text(
        json.dumps(
            {
                "tallies": {f"{p}, run {i + 1}": t for (p, i), t in tallies.items()},
                "subset_tallies": {f"{p}, run {i + 1}": t for (p, i), t in subset_tallies.items()},
            },
            indent=1,
        )
    )
    _extra = [t for (p, _i), t in subset_tallies.items() if p in ("Argon, page by page", "Reducto Deep Extract")]
    print(f"cost of every call in this notebook: ${sum(t['usd'] for t in [*tallies.values(), *_extra]):.2f}")
    return


if __name__ == "__main__":
    app.run()
