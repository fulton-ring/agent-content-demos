import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import csv
    import hashlib
    import json
    import os
    import re
    import time
    from collections import Counter
    from datetime import date, timedelta
    from pathlib import Path

    import marimo as mo
    import pypdfium2 as pdfium
    from pydantic import BaseModel, Field

    from ccr import ask, canonical, checks, in_mg_per_l, meaning, same, spent, well_name

    HERE = Path(__file__).parent
    OUTPUT = Path(os.environ.get("CCR_OUTPUT_DIR", HERE / "output"))
    ANSWERS = HERE / "answers"
    RESULTS = HERE / "results" / "multi_sample"
    BUDGET_USD = 2.0  # issue #275's budget, counted over this schema's answers only
    REVIEW_SECONDS, REVIEW_USD_PER_HOUR = 30, 40.0  # the same assumption as 3_results.py
    # How each lab starts a sample on the page: Shreveport "Cust Sample ID", Dolan "Sample Number:" (to 2020)
    # and "Customer Sample ID" (from 2021).
    SAMPLE_MARK = r"Cust Sample ID|Customer Sample ID|Sample Number:|Client Sample ID"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Lab pages that hold several samples

    **The question.** The schema frozen in #188 has one well, one date and one results table per page. That
    held for PacifiCorp's labs. At AEP (#223), 19 of the 86 born-digital lab pages we read print two to six
    samples, 55 in all, and AEP's lab prints several samples on many pages of its newer reports too. On those
    pages Gemini mostly said "not a lab page" and Mistral read the first sample. Disagreement sent 16 pages to
    review, but on 3 the two models agreed, and the samples after the first were lost with nobody told.

    This notebook (issue #275) tries a second schema, which allows a list of samples per page, on those 19 pages
    and on every multi-sample lab page of three newer AEP reports. It asks:

    1. Does the pair read every sample, and how often is an accepted value wrong? (field error, against the
       consultant's results table, as in `3_results.py`)
    2. How much goes to review, and what does it cost?
    3. Can a page's sample count be checked without a model?

    The old answers aren't touched. Only these pages are read again, with the new schema, and the answers are
    saved under that schema's own hash, so every number in `3_results.py` stays as it was.

    It needs `1_documents.py` to have run with `CCR_UTILITY=aep` and `CCR_UTILITY=aep2022`, and
    `2_extraction.py` with `CCR_UTILITY=aep` (for the old readings of the 19 pages). `run.sh` does that.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The pages

    Every AEP lab page here is born-digital, so its text layer says how many samples it holds: each lab starts a
    sample with the same words (`Customer Sample ID`, `Sample Number:` or `Cust Sample ID`). A page with two or
    more is a multi-sample page.

    - **#223's 19.** The born-digital pages read in #223 that hold two or more samples, with what the old pair did
      on each: sent to review, or both models accepting or rejecting it (lost without review).
    - **AEP from 2022 on.** Every multi-sample page in three Northeastern reports posted in 2023 and 2024
      (landfill 2023 and 2024, bottom ash pond 2023) that names at least one CCR constituent and isn't the
      results table. These are all read, not sampled.
    """)
    return


@app.cell
def _():
    ANALYTE_WORDS = ["Antimony", "Arsenic", "Barium", "Beryllium", "Boron", "Cadmium", "Calcium", "Chloride"]
    ANALYTE_WORDS += ["Chromium", "Cobalt", "Fluoride", "Lead", "Lithium", "Mercury", "Molybdenum", "Selenium"]
    ANALYTE_WORDS += ["Sulfate", "Thallium", "TDS"]

    old = json.loads((OUTPUT / "aep" / "readings.json").read_text())["readings"]
    reports, keys, pages, single = {}, [], [], Counter()
    for _set in ("aep", "aep2022"):
        _out = OUTPUT / _set
        reports |= {r["id"]: {**r, "set": _set} for r in json.loads((_out / "reports.json").read_text())}
        keys += json.loads((_out / "key.json").read_text())
        if _set == "aep":
            _read = json.loads((_out / "pages.json").read_text())
            _where = [(p["report"], p["page"]) for p in _read if p["kind"] == "born-digital"]
        else:
            _where = [
                (r, i + 1)
                for r in [x["id"] for x in json.loads((_out / "reports.json").read_text())]
                for i in range(len(pdfium.PdfDocument(_out / "pdfs" / f"{r}.pdf")))
            ]
        _docs = {}
        for _report, _page in _where:
            _doc = _docs.setdefault(_report, pdfium.PdfDocument(_out / "pdfs" / f"{_report}.pdf"))
            _text = _doc[_page - 1].get_textpage().get_text_range()
            _n = len(re.findall(SAMPLE_MARK, _text))
            if _n < 1 or "Groundwater Data Summary" in _text or not any(a in _text for a in ANALYTE_WORDS):
                continue
            if _n == 1:
                single[_set] += 1
                continue
            _key = f"{_report}_p{_page:04d}"
            _png = _out / "pages" / f"{_key}.png"
            if not _png.exists():
                _png.parent.mkdir(parents=True, exist_ok=True)
                _doc[_page - 1].render(scale=150 / 72).to_pil().convert("L").save(_png)
            _before = None
            if _set == "aep":
                _g, _m = (old[m][_key]["output"]["is_lab_result_page"] for m in ("gemini", "mistral"))
                _before = "sent to review" if _g != _m else "lost: both accept" if _g else "lost: both reject"
            pages.append(
                {"key": _key, "set": _set, "report": _report, "page": _page, "png": str(_png), "text": _text}
                | {"text_samples": _n, "before": _before}
            )
    for _set in ("aep", "aep2022"):
        _p = [p for p in pages if p["set"] == _set]
        print(f"{_set}: {len(_p)} multi-sample pages holding {sum(p['text_samples'] for p in _p)} samples")
    print(f"lab pages with one sample, not read here: {dict(single)}")
    print("#223's pages, by what the old pair did:", Counter(p["before"] for p in pages if p["before"]))
    return keys, pages, reports


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The page's own text layer

    The text layer is a second, exact copy of the page. We use it twice:

    - **to count samples.** If the models' list of samples is longer or shorter than the text layer's count, the
      page goes to review. That is the check that would have caught #223's three lost pages;
    - **to settle the answer key.** The consultant's table is the key, as in `3_results.py`, but in #223 it
      differed from the lab page 77 times, and the page was right every time. So where the table and the page's
      text layer differ, the text layer wins. In #223 that was done by hand into `adjudications_aep.json`; here
      a few regular expressions do it, because the three lab layouts print every value on one line:
      `Boron, B 0.007 mg/L ...`, `Fluoride < 0.083 mg/L ...`, `Antimony 0.51 µg/L ...`.

    Each sample's block of text runs from one sample marker to the next. Its sample ID is the customer sample ID
    (in Dolan's older layout, the line after the sample number), and its well is the first word of that ID, since
    Dolan adds the unit (`SP-1 BAP`) or a note (`SP-10 -20190314`). Duplicates, blanks and dissolved-metals
    samples share a well's name but aren't in the results table, so they aren't matched to it.
    """)
    return


@app.cell
def _(pages):
    ROW = re.compile(
        r"^(?P<name>[A-Za-z][A-Za-z0-9 ,()\-]*?)\s+(?P<value><\s?[\d.]+|[\d.]+)\s+"
        r"(?P<unit>mg/L|µg/L|ug/L|ng/L|SU|S\.U\.|pH Units|Std Units)\b",
        re.M,
    )
    for _p in pages:
        _starts = [m.start() for m in re.finditer(SAMPLE_MARK, _p["text"])] + [len(_p["text"])]
        _p["text_layer"] = []
        for _a, _b in zip(_starts, _starts[1:], strict=False):
            _block = _p["text"][_a:_b]
            _id = re.match(r"(?:Cust|Customer|Client) Sample ID:?\s*([^\n]+?)(?:\s+Matrix:.*)?$", _block, re.M)
            _id = _id or re.search(r"Sample Number:[^\n]*\n\s*([^\n]+)", _block)
            _day = re.search(r"(?:Date Collected|Collected Date):\s*(\d{1,2})/(\d{1,2})/(\d{4})", _block)
            _values = {}
            for _row in ROW.finditer(_block):
                _analyte = "tds" if "TDS" in _row["name"] else canonical(_row["name"])
                if _analyte and _analyte not in _values:
                    _values[_analyte] = in_mg_per_l(meaning(_row["value"]), _row["unit"])
            _p["text_layer"].append(
                {
                    "id": well_name(_id.group(1)) if _id else None,
                    "well": well_name(_id.group(1).split()[0]) if _id else None,
                    "date": date(int(_day[3]), int(_day[1]), int(_day[2])).isoformat() if _day else None,
                    "values": _values,
                }
            )
    _blocks = [s for p in pages for s in p["text_layer"]]
    print(
        f"{len(_blocks)} samples in the text layer: {sum(bool(s['well']) for s in _blocks)} with a well, "
        f"{sum(bool(s['date']) for s in _blocks)} with a date, {sum(len(s['values']) for s in _blocks)} CCR values"
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Schema 2: a list of samples per page

    The per-value fields are copied unchanged from the frozen schema in `2_extraction.py`: each result as
    printed, with its box and the model's confidence, its units, reporting limit and qualifier. What changes is
    that the well, the date and the results now sit inside a `Sample`, and a page holds a list of them. The hash
    is printed; the readings are saved under `answers/<hash>/`, beside the old schema's.
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

    class Sample(BaseModel):
        """One field sample on the page: one well, one collection date, its results."""

        client_sample_id: Printed | None = Field(None, description="The client sample ID: the monitoring well name.")
        collection_date: CollectionDate | None = None
        results: list[Result] = Field(default_factory=list, description="Every row of this sample's results.")

    class LabPageSamples(BaseModel):
        """One page of a laboratory analytical report, which may hold one sample or several."""

        is_lab_result_page: bool = Field(
            description="True only if the page reports analytical results for field samples. False for chain of "
            "custody forms, QC or method blank summaries, cover letters, case narratives and anything else."
        )
        samples: list[Sample] = Field(
            default_factory=list,
            description="Every sample on the page, in the order printed. Many pages hold one; some hold several.",
        )

    SCHEMA_HASH = hashlib.sha256(json.dumps(LabPageSamples.model_json_schema(), sort_keys=True).encode()).hexdigest()
    SCHEMA_HASH = SCHEMA_HASH[:12]
    print(f"frozen schema 2: {SCHEMA_HASH}")
    return LabPageSamples, SCHEMA_HASH


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Two readings

    The same two models as before, Gemini 3.8 Flash and Mistral Small 2603, through OpenRouter, at the same
    settings (the call is `ask` in `ccr.py`, shared with `2_extraction.py`). The instructions add one sentence:
    a page can hold several samples, and each is reported. Spending stops at $2 over this schema's answers.
    """)
    return


@app.cell
async def _(LabPageSamples, SCHEMA_HASH, pages):
    MODELS = {"gemini": "openrouter:google/gemini-3.8-flash", "mistral": "openrouter:mistralai/mistral-small-2603"}
    INSTRUCTIONS = "\n".join(
        [
            "You read scanned and printed laboratory reports. Report only what is printed or handwritten on the page.",
            "Never compute, infer or fill in a value. Copy every result exactly as printed.",
            "A page can hold several samples, each with its own sample ID and collection date. Report every one.",
            "Bounding boxes are [x0, y0, x1, y1] in 0-1000 coordinates relative to the page image.",
        ]
    )
    PROMPT = "Read this page of a groundwater laboratory report."
    _folder = ANSWERS / SCHEMA_HASH
    _slots = asyncio.Semaphore(8)

    async def read(name: str, page: dict) -> dict:
        async with _slots:
            save = _folder / name / f"{page['key']}.json"
            if not save.exists() and spent(_folder) > BUDGET_USD:
                raise RuntimeError(f"spent more than the ${BUDGET_USD} budget")
            return await ask(MODELS[name], LabPageSamples, INSTRUCTIONS, PROMPT, [Path(page["png"])], save)

    _t0 = time.time()
    readings = {
        name: dict(zip([p["key"] for p in pages], await asyncio.gather(*(read(name, p) for p in pages)), strict=True))
        for name in MODELS
    }
    print(f"read in {time.time() - _t0:.0f} s; ${spent(_folder):.2f} spent with schema 2")
    for _name, _by_page in readings.items():
        _ok = [r for r in _by_page.values() if r["output"]]
        print(
            f"{_name}: {len(_ok)} of {len(_by_page)} pages answered, "
            f"{sum(r['output']['is_lab_result_page'] for r in _ok)} called lab pages, "
            f"{sum(len(r['output']['samples']) for r in _ok)} samples, "
            f"${sum(r['usd'] for r in _by_page.values()):.3f}, "
            f"{sum(r['seconds'] for r in _by_page.values()) / len(_by_page):.1f} s a page"
        )
    return MODELS, readings


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The review rule, per sample

    The rule in `3_results.py`, applied to each sample, plus two page-level checks:

    - a page goes to review whole if only one model calls it a lab page, or **the two models list a different
      number of samples, or either count differs from the text layer's**;
    - the two models' samples are paired in the order printed. In each pair, the well and the date go to review
      if the models disagree, if the well isn't on the report's well list, or if the date is outside the period
      the results table covers (give or take three days). A value goes to review if the models disagree, only one
      read it, or it fails a check (`checks` in `ccr.py`: readable, usual units, plausible size).
    """)
    return


@app.cell
def _(pages, readings, reports, keys):
    def samples_read(output: dict | None) -> list[dict] | None:
        """A model's samples, each reduced to well, date and {analyte: (meaning, row)}; None if not a lab page."""
        if not output or not output["is_lab_result_page"]:
            return None
        reduced = []
        for sample in output["samples"]:
            values = {}
            for row in sample["results"]:
                analyte = canonical(row["analyte"])
                if analyte and analyte not in values:
                    value = meaning(row["result"]["printed"], row.get("reporting_limit"))
                    values[analyte] = (in_mg_per_l(value, row["units"]), row)
            reduced.append(
                {
                    "well": well_name((sample.get("client_sample_id") or {}).get("printed")),
                    "date": ((sample.get("collection_date") or {}).get("iso") or "")[:10] or None,
                    "values": values,
                }
            )
        return reduced

    period = {}
    for _k in keys:
        _lo, _hi = period.get(_k["report"], (_k["date"], _k["date"]))
        period[_k["report"]] = (min(_lo, _k["date"]), max(_hi, _k["date"]))

    reduced = {name: {k: samples_read(r["output"]) for k, r in by_page.items()} for name, by_page in readings.items()}
    fields, page_review = [], {}
    for _p in pages:
        _g, _m = reduced["gemini"][_p["key"]], reduced["mistral"][_p["key"]]
        _why = []
        if (_g is None) != (_m is None):
            _why.append("only one model calls it a lab page")
        elif _g is not None and _m is not None:
            if len(_g) != len(_m):
                _why.append("models list a different number of samples")
            if _p["text_samples"] != len(_g) or _p["text_samples"] != len(_m):
                _why.append("sample count differs from the text layer")
        if _g is None and _m is None:
            _why.append("neither model calls it a lab page")
        if _why:
            page_review[_p["key"]] = _why
        if _g is None or _m is None:
            continue
        _wells = {well_name(w) for w in reports[_p["report"]]["wells"]}
        _lo, _hi = (date.fromisoformat(d) for d in period[_p["report"]])
        for _i in range(max(len(_g), len(_m))):
            _gs = _g[_i] if _i < len(_g) else None
            _ms = _m[_i] if _i < len(_m) else None
            _base = {"page": _p["key"], "sample": _i}
            if _gs is None or _ms is None:
                fields.append(_base | {"field": "sample", "gemini": _gs, "mistral": _ms, "reasons": ["one model only"]})
                continue
            for _f in ("well", "date"):
                _reasons = [] if _gs[_f] == _ms[_f] else ["models disagree"]
                if _f == "well" and not {_gs["well"], _ms["well"]} <= _wells:
                    _reasons.append("well not on the report's well list")
                if _f == "date":
                    _day = (
                        _gs["date"]
                        and re.fullmatch(r"\d{4}-\d\d-\d\d", _gs["date"])
                        and date.fromisoformat(_gs["date"])
                    )
                    if not _day or not (_lo - timedelta(days=3) <= _day <= _hi + timedelta(days=3)):
                        _reasons.append("date outside the results table's period")
                fields.append(_base | {"field": _f, "gemini": _gs[_f], "mistral": _ms[_f], "reasons": _reasons})
            for _a in sorted(set(_gs["values"]) | set(_ms["values"])):
                _gv, _mv = _gs["values"].get(_a), _ms["values"].get(_a)
                _reasons = []
                if _gv is None or _mv is None:
                    _reasons.append("read by one model only")
                elif not same(_gv[0], _mv[0]):
                    _reasons.append("models disagree")
                for _v in (_gv, _mv):
                    if _v is not None:
                        _reasons += [c for c in checks(_a, _v[0], _v[1]["units"]) if c not in _reasons]
                fields.append(_base | {"field": _a, "gemini": _gv, "mistral": _mv, "reasons": _reasons})
    _values = [f for f in fields if f["field"] not in ("well", "date", "sample")]
    _in_review = {f["page"] for f in fields if f["reasons"]} | set(page_review)
    print(f"{len(page_review)} pages sent to review whole: {Counter(r for w in page_review.values() for r in w)}")
    print(
        f"{len(_values)} values on {len(pages) - sum(k in page_review for k in [p['key'] for p in pages])} pages read "
        f"alike; {sum(bool(f['reasons']) for f in _values)} sent to review"
    )
    print(f"{len(_in_review)} of {len(pages)} pages have something in review")
    print(Counter(r for f in fields for r in f["reasons"]).most_common())
    return fields, page_review, reduced


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Can the sample count be checked?

    On a born-digital page, yes: the text layer's count of sample markers is exact. Here is how often each model's
    count matched it, and on how many pages both models gave the same wrong count, which is the case
    disagreement alone can't catch.
    """)
    return


@app.cell
def _(pages, reduced):
    count_check = Counter()
    for _p in pages:
        _n = {m: len(reduced[m][_p["key"]] or []) for m in ("gemini", "mistral")}
        count_check["pages"] += 1
        for _m, _c in _n.items():
            count_check[f"{_m} count right"] += _c == _p["text_samples"]
        count_check["both the same wrong count"] += _n["gemini"] == _n["mistral"] != _p["text_samples"]
    count_check = dict(count_check)
    print(json.dumps(count_check))
    return (count_check,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring

    The truth is each sample in the text layer, matched to the results table by report, well (the letter O and
    the digit 0 alike) and collection date within three days, as in `3_results.py`. A value is scored where the
    table has it and the page prints it. Where the table and the page's text layer differ, the text layer wins,
    and the difference is counted.

    For each model, a true sample's values are **right**, **wrong** or **missing**; a sample the model didn't
    list, or listed under a different well or date, is missing whole. For the pair, an **accepted** value is a
    value on a page and sample with nothing in review; it is **accepted wrong** if it isn't the truth. A sample
    is **lost** if the pair accepted no reading of it and nothing about it went to review. That is the failure
    #223 found.
    """)
    return


@app.cell
def _(fields, keys, page_review, pages, reduced):
    def loose(well: str | None) -> str:
        return (well or "").replace("O", "0")

    def near(a: str | None, b: str | None) -> bool:
        if not a or not b or not re.fullmatch(r"\d{4}-\d\d-\d\d", a) or not re.fullmatch(r"\d{4}-\d\d-\d\d", b):
            return False
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days) <= 3

    def is_sample(well: str, text_sample: dict) -> bool:
        """A model's well names this text-layer sample: its well, or its whole sample ID (`SP-1 BAP`)."""
        if loose(well) == loose(text_sample["well"]):
            return True
        return len(well) > len(text_sample["well"]) and loose(text_sample["id"]).startswith(loose(well))

    table = {}
    for _k in keys:
        table.setdefault((_k["report"], well_name(_k["well"])), []).append(_k)
    _review = {(f["page"], f["sample"]) for f in fields if f["reasons"]}
    scored, samples, table_differs = [], [], []
    for _p in pages:
        for _t in _p["text_layer"]:
            _rows = [k for k in table.get((_p["report"], _t["well"]), []) if near(k["date"], _t["date"])]
            _rows = [] if any(w in (_t["id"] or "") for w in ("DISSOLVED", "DUP", "BLANK")) else _rows
            # One table row per constituent: the nearest date, then the first printed (the table repeats some).
            _rows.sort(key=lambda k: abs((date.fromisoformat(k["date"]) - date.fromisoformat(_t["date"])).days))
            _rows = list({k["analyte"]: k for k in reversed(_rows)}.values())
            _found = {}
            for _m in ("gemini", "mistral"):
                _list = reduced[_m][_p["key"]] or []
                _found[_m] = next(
                    (i for i, s in enumerate(_list) if near(s["date"], _t["date"]) and is_sample(s["well"], _t)),
                    None,
                )
            _i = _found["gemini"]
            _flagged = _p["key"] in page_review or (_i is not None and (_p["key"], _i) in _review)
            _accepted = _i is not None and not _flagged
            samples.append(
                {"page": _p["key"], "well": _t["well"], "date": _t["date"], "in_table": bool(_rows)}
                | {f"{m} found": _found[m] is not None for m in _found}
                | {"accepted": _accepted, "in review": _flagged, "lost": not _accepted and not _flagged}
            )
            for _k in _rows:
                if _k["analyte"] not in _t["values"]:
                    continue
                _truth = _t["values"][_k["analyte"]]
                if not same(meaning(_k["value"]), _truth):
                    table_differs.append({"page": _p["key"], "well": _t["well"], "analyte": _k["analyte"]})
                    table_differs[-1] |= {"table": _k["value"], "page says": _truth}
                _verdict = {}
                for _m, _j in _found.items():
                    _v = reduced[_m][_p["key"]][_j]["values"].get(_k["analyte"]) if _j is not None else None
                    _verdict[_m] = "missing" if _v is None else "right" if same(_v[0], _truth) else "wrong"
                _gv = reduced["gemini"][_p["key"]][_i]["values"].get(_k["analyte"]) if _i is not None else None
                _field_review = any(
                    f["reasons"]
                    for f in fields
                    if (f["page"], f["sample"], f["field"]) == (_p["key"], _i, _k["analyte"])
                )
                _ok = _accepted and _gv is not None and not _field_review
                scored.append(
                    {"page": _p["key"], "set": _p["set"], "well": _t["well"], "analyte": _k["analyte"]}
                    | {"verdict": _verdict, "accepted": _ok, "accepted_wrong": _ok and not same(_gv[0], _truth)}
                )
    print(
        f"{len(samples)} true samples, {sum(s['in_table'] for s in samples)} in the results table; "
        f"{len(scored)} values scored; the table differs from the page on {len(table_differs)}"
    )
    print(f"samples lost without review: {sum(s['lost'] for s in samples)}")
    for _d in table_differs:
        print(_d)
    return samples, scored, table_differs


@app.cell
def _(pages, samples, scored):
    def wilson_high(k: int, n: int) -> float:
        """Upper end of the 95% Wilson interval for k of n."""
        if n == 0:
            return float("nan")
        z, p = 1.96, k / n
        centre = (p + z * z / (2 * n)) / (1 + z * z / n)
        half = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / (1 + z * z / n)
        return centre + half

    scores = []
    for _set in ("aep", "aep2022", "all"):
        _s = [f for f in scored if _set == "all" or f["set"] == _set]
        _pk = {p["key"] for p in pages if _set == "all" or p["set"] == _set}
        _samp = [s for s in samples if s["page"] in _pk]
        _row = {"pages": f"{_set} ({len(_pk)})", "samples": len(_samp), "values scored": len(_s)}
        for _m in ("gemini", "mistral"):
            _c = Counter(f["verdict"][_m] for f in _s)
            _row[f"{_m} wrong"] = _c["wrong"]
            _row[f"{_m} missing"] = _c["missing"]
            _row[f"{_m} samples found"] = sum(s[f"{_m} found"] for s in _samp)
        _acc = [f for f in _s if f["accepted"]]
        _row["accepted"] = len(_acc)
        _row["accepted wrong"] = sum(f["accepted_wrong"] for f in _acc)
        _row["95% upper bound"] = f"{wilson_high(_row['accepted wrong'], len(_acc)):.2%}"
        _row["samples in review"] = sum(s["in review"] for s in _samp)
        _row["samples lost"] = sum(s["lost"] for s in _samp)
        scores.append(_row)
    mo.ui.table(scores, selection=None)
    return (scores,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## #223's three lost pages

    The pages where both old readings agreed, so their extra samples were lost without review: how many samples
    each holds, how many each model listed this time, and where they went.
    """)
    return


@app.cell
def _(pages, reduced, samples):
    lost_before = []
    for _p in [p for p in pages if p["before"] and p["before"].startswith("lost")]:
        _s = [s for s in samples if s["page"] == _p["key"]]
        lost_before.append(
            {"page": _p["key"], "before": _p["before"], "samples on the page": _p["text_samples"]}
            | {f"{m} listed": len(reduced[m][_p["key"]] or []) for m in ("gemini", "mistral")}
            | {k: sum(s[k] for s in _s) for k in ("accepted", "in review", "lost")}
        )
    mo.ui.table(lost_before, selection=None)
    return (lost_before,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Cost

    What OpenRouter charged for both readings of every page, per page and per sample, and the assumed review
    time, with the same assumption as `3_results.py`: 30 seconds a reviewed field at $40 an hour, and a page sent
    to review whole counted as 20 fields for each sample the text layer finds on it.
    """)
    return


@app.cell
def _(fields, page_review, pages, readings):
    _usd = sum(r["usd"] for by_page in readings.values() for r in by_page.values())
    _n_samples = sum(p["text_samples"] for p in pages)
    _review_fields = sum(bool(f["reasons"]) for f in fields if f["page"] not in page_review)
    _review_fields += sum(20 * p["text_samples"] for p in pages if p["key"] in page_review)
    _review_usd = _review_fields * REVIEW_SECONDS / 3600 * REVIEW_USD_PER_HOUR
    cost = {
        "pages read": len(pages),
        "model cost": round(_usd, 3),
        "model cost per page": round(_usd / len(pages), 4),
        "model cost per sample": round(_usd / _n_samples, 4),
        "fields to review (assumed)": _review_fields,
        "review cost per sample (assumed)": round(_review_usd / _n_samples, 4),
        "seconds per page, each model": {
            m: round(sum(r["seconds"] for r in by_page.values()) / len(pages), 1) for m, by_page in readings.items()
        },
    }
    print(json.dumps(cost, indent=1))
    return (cost,)


@app.cell
def _(MODELS, SCHEMA_HASH, cost, count_check, fields, lost_before, page_review, pages, samples, scores, table_differs):
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "results.json").write_text(
        json.dumps(
            {
                "models": MODELS,
                "schema": SCHEMA_HASH,
                "scores": scores,
                "sample_count_check": count_check,
                "lost_in_223": lost_before,
                "table_differs_from_page": table_differs,
                "pages_in_review_whole": {k: v for k, v in page_review.items()},
                "cost": cost,
            },
            indent=1,
        )
    )
    with open(RESULTS / "samples.csv", "w", newline="") as _fh:
        _w = csv.DictWriter(_fh, fieldnames=list(samples[0]))
        _w.writeheader()
        _w.writerows(samples)
    _queue = [
        {"page": f["page"], "sample": f["sample"], "field": f["field"], "reasons": "; ".join(f["reasons"])}
        for f in fields
        if f["reasons"]
    ] + [{"page": k, "sample": "", "field": "whole page", "reasons": "; ".join(v)} for k, v in page_review.items()]
    with open(RESULTS / "review_queue.csv", "w", newline="") as _fh:
        _w = csv.DictWriter(_fh, fieldnames=["page", "sample", "field", "reasons"])
        _w.writeheader()
        _w.writerows(_queue)
    print(f"wrote {RESULTS}: {len(samples)} samples on {len(pages)} pages, {len(_queue)} rows in the review queue")
    return


if __name__ == "__main__":
    app.run()
