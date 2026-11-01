import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import collections
    import json
    import os
    import random
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    import marimo as mo
    import pandas as pd
    import pypdfium2 as pdfium
    from pydantic import BaseModel

    from common import ANSWERS, HERE, MODELS, NRC, NUMBER, ask, image, norm, nrc_pdf, page_png, tesseract, text_layer


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 3. What still comes out of old NRC scans?

    The NRC scanned and destroyed its paper records; the scans are now the record. How much of what's printed on
    them can a pipeline still read, and does it depend on how good the scan is?

    **Where the scans come from.** The issue asked for NRC ADAMS. From the machine this ran on, `adams.nrc.gov` was
    refused by the network and `www.nrc.gov/docs/` answered 403 Access Denied, so we used the same NRC reports as
    served by OSTI, the Department of Energy's report library, which holds NRC's NUREG series as scanned PDFs.
    Each has a hidden text layer from an earlier OCR pass, as ADAMS scans do.

    **The sample.** The 68 reports OSTI lists as NRC-sponsored NUREG reports dated 1975 to 1984 with full text, and
    10 of them drawn with `random.Random(175)`: 2,495 pages. The cell below shows the draw; it re-runs only if
    `REDRAW_SAMPLE=1`, since OSTI's listing can change.
    """)
    return


@app.cell
def _():
    def draw_sample() -> list[str]:
        pool = []
        for start, end in (("1975", "1979"), ("1980", "1984")):
            url = (
                "https://www.osti.gov/api/v1/records?sponsor_org=Nuclear%20Regulatory%20Commission&has_fulltext=true"
                f"&publication_date_start=01/01/{start}&publication_date_end=12/31/{end}&rows=100"
            )
            request = urllib.request.Request(url, headers={"Accept": "application/json"})
            pool += [
                r
                for r in json.load(urllib.request.urlopen(request, timeout=120))
                if "NUREG" in (r.get("report_number") or "")
            ]
        pool.sort(key=lambda r: int(r["osti_id"]))
        return [r["osti_id"] for r in random.Random(175).sample(pool, 10)]

    if os.environ.get("REDRAW_SAMPLE") == "1":
        print("redrawn:", draw_sample() == list(NRC))
    PDFS = {osti: nrc_pdf(osti) for osti in NRC}
    LENGTH = {osti: len(pdfium.PdfDocument(pdf)) for osti, pdf in PDFS.items()}
    print(f"{len(PDFS)} reports, {sum(LENGTH.values()):,} pages")
    return LENGTH, PDFS


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scan quality

    We measure scan quality as Tesseract's mean word confidence (0 to 100) on the page: it needs no answer key, and
    it drops with faint type, dot-matrix print, skew and noise. For each report we take 20 pages (all 13 of the shortest) drawn with
    `random.Random(175)`, to describe the report, plus the keyed page.
    """)
    return


@app.cell
def _(LENGTH, PDFS):
    _rng = random.Random(175)
    _pages = [
        (osti, p) for osti in PDFS for p in sorted(_rng.sample(range(1, LENGTH[osti] + 1), min(20, LENGTH[osti])))
    ]
    with ThreadPoolExecutor(4) as _pool:
        _conf = list(_pool.map(lambda op: tesseract(PDFS[op[0]], op[1])[1], _pages))
    quality = pd.DataFrame(
        [(o, p, c) for (o, p), c in zip(_pages, _conf, strict=True)], columns=["osti", "page", "conf"]
    )
    _by = quality.groupby("osti").conf.describe()[["mean", "min", "max"]].round(1)
    _by.insert(0, "report", [NRC[o][0] for o in _by.index])
    print(_by.to_string())
    return (quality,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The answer key

    `nrc_key.json` holds every number printed on one page of each report: 717 numbers. A number is a run of digits
    with any `.` or `,` inside it (`common.NUMBER`), so the key needs no judgement about what a field is. Numbers
    are what extraction is for, and a misread number looks as plausible as a right one. The keyed page was drawn
    with `random.Random(175)` from the pages whose text layer holds 40 or more numbers: tables, references,
    figures. Three independent reads were compared (the PDF's own OCR layer, Tesseract, and Gemini 4 Argon, which
    isn't tested here) and every disagreement that decided the key was checked on the page image; the key file
    says how for each page. On one page, a dot-matrix printout of about 700 numbers, we keyed only rows 1-15 and
    the summary lines, so there we can count what was found but not what was invented.
    """)
    return


@app.cell
def _(PDFS):
    KEY = {k: v for k, v in json.loads((HERE / "nrc_key.json").read_text()).items() if not k.startswith("_")}
    keyed = pd.DataFrame(
        [(o, v["page"], len(v["numbers"]), tesseract(PDFS[o], v["page"])[1]) for o, v in KEY.items()],
        columns=["osti", "page", "numbers", "conf"],
    )
    # Thirds of the keyed pages by Tesseract confidence.
    keyed["quality"] = pd.qcut(keyed.conf, 3, labels=["poor", "fair", "good"])
    print(keyed.to_string(index=False))
    return KEY, keyed


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Five ways to read the page

    Two need no model: the numbers in the **text layer** the PDF already carries, and in **Tesseract**'s text.
    Three add a model, each asked for a full transcription, from which the numbers are taken the same way: the
    **text layer, then a model**; **Tesseract, then a model**; and the **page image** at 200 dpi. Each model
    pipeline runs with both models. Answers are saved in `answers/nrc/`.
    """)
    return


@app.cell
async def _(KEY, PDFS):
    class Transcript(BaseModel):
        text: str

    _instructions = "You transcribe scanned report pages. Report only what is printed. Never infer or fill in."
    _ask_page = "Transcribe this page exactly as printed, every word and number, in reading order; tables row by row."
    _ask_text = (
        "Below is OCR text of one scanned report page. Give a clean transcription of the page, fixing what the OCR "
        "got wrong only where the right text is clear. Keep every number."
    )
    _slots = asyncio.Semaphore(8)

    def _parts(osti: str, pipeline: str) -> list:
        pdf, page = PDFS[osti], KEY[osti]["page"]
        if pipeline == "Text layer, then model":
            return [_ask_text, text_layer(pdf, page)]
        if pipeline == "Tesseract, then model":
            return [_ask_text, tesseract(pdf, page)[0]]
        return [_ask_page, image(page_png(pdf, page, 200))]

    _jobs = [
        (name, pipeline, osti)
        for osti in KEY
        for pipeline in ("Text layer, then model", "Tesseract, then model", "Image, model")
        for name in MODELS
    ]
    _calls = [
        ask(
            MODELS[n],
            Transcript,
            _instructions,
            _parts(o, p),
            ANSWERS / "nrc" / MODELS[n].split("/")[-1] / p.replace(", ", "-").replace(" ", "-") / f"{o}.json",
            _slots,
        )
        for n, p, o in _jobs
    ]
    _answers = await asyncio.gather(*_calls)
    reads = {}
    for (_n, _p, _o), _a in zip(_jobs, _answers, strict=True):
        reads[(_n, _p, _o)] = {"text": (_a["output"] or {}).get("text", ""), "usd": _a["usd"], "seconds": _a["seconds"]}
    for _o in KEY:
        reads[("no model", "Text layer alone", _o)] = {
            "text": text_layer(PDFS[_o], KEY[_o]["page"]),
            "usd": 0.0,
            "seconds": 0.0,
        }
        reads[("no model", "Tesseract alone", _o)] = {
            "text": tesseract(PDFS[_o], KEY[_o]["page"])[0],
            "usd": 0.0,
            "seconds": 0.0,
        }
    print(f"{len(_jobs)} model reads, ${sum(r['usd'] for r in reads.values()):.2f}")
    return (reads,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring

    The numbers read are matched to the key's numbers by value (`common.norm`), as a multiset. **Found** is the
    share of key numbers matched. **Extra** counts numbers read that match nothing in the key: a misread number
    shows up as one missed and one extra. Extra isn't counted on the partly keyed page.
    """)
    return


@app.cell
def _(KEY, keyed, reads):
    _rows = []
    for (_model, _pipeline, _osti), _r in reads.items():
        _key = collections.Counter(norm(n) for n in KEY[_osti]["numbers"])
        _got = collections.Counter(norm(n) for n in NUMBER.findall(_r["text"]))
        _found = sum((_key & _got).values())
        _full = KEY[_osti]["scope"] == "page"
        _rows.append(
            {
                "model": _model,
                "pipeline": _pipeline,
                "osti": _osti,
                "numbers": sum(_key.values()),
                "found": _found,
                "extra": sum((_got - _key).values()) if _full else None,
                "usd": _r["usd"],
                "seconds": _r["seconds"],
            }
        )
    scores = pd.DataFrame(_rows).merge(keyed[["osti", "conf", "quality"]], on="osti")
    _g = scores.groupby(["model", "pipeline", "quality"], observed=True)[["numbers", "found"]].sum()
    _g["pct_found"] = (100 * _g.found / _g.numbers).round(1)
    by_quality = _g.pct_found.unstack("quality")
    _t = scores.groupby(["model", "pipeline"]).agg(
        numbers=("numbers", "sum"), found=("found", "sum"), extra=("extra", "sum"), usd=("usd", "sum")
    )
    _t["pct_found"] = (100 * _t.found / _t.numbers).round(1)
    totals = _t
    print(by_quality.to_string())
    print(totals.to_string())
    print(scores.pivot_table(index="osti", columns="pipeline", values="found", aggfunc="max").to_string())
    return by_quality, scores, totals


@app.cell
def _(by_quality, keyed, quality, scores, totals):
    _out = HERE / "results"
    _out.mkdir(exist_ok=True)
    scores.to_csv(_out / "3_scores.csv", index=False)
    (_out / "3_old_nrc_scans.md").write_text(
        "# Old NRC scans\n\nShare of key numbers found, by scan quality of the keyed page.\n\n"
        + by_quality.to_markdown()
        + "\n\n## Totals\n\n"
        + totals.to_markdown()
        + "\n\n## Keyed pages\n\n"
        + keyed.to_markdown(index=False)
        + "\n\n## Tesseract confidence on 20 sampled pages per report\n\n"
        + quality.groupby("osti").conf.describe().round(1).to_markdown()
        + "\n"
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this doesn't show

    - Ten pages, one per report, 717 numbers. The quality thirds hold three or four pages each.
    - It counts numbers, not fields: a number found in the wrong place still counts as found here.
      `2_long_vs_short.py` scores fields in place.
    - The scans come from OSTI, not ADAMS. They are the same reports, but ADAMS may hold other scans of them.
    """)
    return


if __name__ == "__main__":
    app.run()
