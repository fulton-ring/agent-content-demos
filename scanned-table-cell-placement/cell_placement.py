import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import collections
    import json
    import os
    import re
    import time
    from decimal import Decimal
    from pathlib import Path

    import marimo as mo
    import pandas as pd
    from rapidfuzz import fuzz
    from scipy.stats import binomtest

    STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # When AI reads an old scanned table, does each number land in the right cell?

    The `fema-nrc-extraction-accuracy` spike (issue #175) found that a vision model reading the page image finds
    99.3% of the numbers printed on old NRC scans. "Found" there means the number appears somewhere in the
    transcript. A table is only useful if each number sits in its own row and column, so this notebook asks two
    things of the same saved answers:

    1. **How far does "found" overstate "in the right cell"?** Each pipeline is scored both ways, side by side.
    2. **Can the totals printed on the page catch the misplaced and misread numbers without an answer key?**
       Where a table prints a total, we add up the extracted column and compare.

    Everything here rescores answers that spike saved. No model is called and nothing is downloaded.
    """)
    return


@app.cell
def _():
    HERE = mo.notebook_dir()
    assert HERE is not None, "run this as a notebook file"
    SOURCE = Path(os.environ.get("SOURCE_SPIKE_DIR", HERE.parent / "fema-nrc-extraction-accuracy"))
    RESULTS = Path(os.environ.get("CELL_PLACEMENT_RESULTS_DIR", HERE / "results"))
    assert (SOURCE / "answers").is_dir(), f"the source spike's saved answers aren't at {SOURCE}"
    RESULTS.mkdir(parents=True, exist_ok=True)

    FIS_KEY = json.loads((SOURCE / "fis_key.json").read_text())
    NRC_NUMBERS = json.loads((SOURCE / "nrc_key.json").read_text())
    CELL_KEY = json.loads((HERE / "nrc_cell_key.json").read_text())
    # Scan type of each FIS study and scan quality of each NRC page, as the source spike measured them.
    FIS_KIND = pd.read_csv(SOURCE / "results" / "2_scores.csv").groupby("doc").kind.first().to_dict()
    NRC_QUALITY = pd.read_csv(SOURCE / "results" / "3_scores.csv").groupby("osti").quality.first()
    NRC_QUALITY.index = NRC_QUALITY.index.astype(str)
    MODELS = {"claude-haiku-5.5": "Claude Haiku 5.5", "gemini-3.8-flash": "Gemini 3.8 Flash"}
    return CELL_KEY, FIS_KEY, FIS_KIND, MODELS, NRC_NUMBERS, NRC_QUALITY, RESULTS, SOURCE


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## How the source spike scored

    The issue asked us to check this first, because if the spike already graded by cell, there's nothing to
    re-score.

    - **FIS tables: already by cell.** `2_long_vs_short.py` pairs each key row with the answer row that agrees
      with it most (the location counts double), then compares column by column. A number in the wrong row or
      column counts as wrong. Below we add a "found anywhere" score next to it to show the gap.
    - **NRC pages: not by cell.** `nrc_key.json` is a flat list of the numbers on each page, and an answer was
      scored by how many of those numbers appear anywhere in its transcript. That's the 99.3%. A number in the
      wrong row still counted. The spike's README says so: "A number found in the wrong place still counts as
      found."

    So the NRC side needs a key that says where each number goes.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The data: which keyed pages hold a table, and which print a total

    The NRC key covers one page drawn at random from each of 10 reports. Only 4 of those pages are tables. The
    other 6 are two reference lists, a table of contents, a page of prose, a page of figures and a references
    page set in two columns. We keyed rows and columns for the 4 tables (5 tables in all, since one page holds
    two) in `nrc_cell_key.json`: each row is a pattern that finds its label in a transcript, and the values
    printed in it, left to right.

    The FIS key is already rows and columns: one *Summary of Discharges* table from each of 8 studies.

    The cell below checks the new key against the source key's numbers: every value we keyed should be among
    the numbers the source spike keyed for that page.
    """)
    return


@app.cell
def _(CELL_KEY, FIS_KEY, NRC_NUMBERS):
    NUMBER = re.compile(r"\d+(?:[.,]\d+)*")  # the source spike's definition of a number on an NRC page

    _rows = []
    for _osti, _page in CELL_KEY.items():
        if _osti == "_about":
            continue
        _source = collections.Counter(n.replace(",", "") for n in NRC_NUMBERS[_osti]["numbers"])
        for _table in _page["tables"]:
            _ours = collections.Counter(
                n.replace(",", "")
                for _row in _table["rows"]
                if _row["scored"]
                for v in _row["values"]
                for n in NUMBER.findall(v)
            )
            _rows.append(
                {
                    "page": _osti,
                    "table": _table["name"],
                    "rows": sum(r["scored"] for r in _table["rows"]),
                    "printed totals": len(_table["totals"]),
                    "numbers keyed": sum(_ours.values()),
                    "not in source key": sum((_ours - _source).values()),
                }
            )
    for _doc, _entry in FIS_KEY.items():
        if _doc != "_about":
            _rows.append(
                {
                    "page": _doc,
                    "table": "FIS Summary of Discharges",
                    "rows": len(_entry["rows"]),
                    "printed totals": 0,
                    "numbers keyed": sum(bool(v) for r in _entry["rows"] for v in r[2:]),
                    "not in source key": 0,
                }
            )
    tables = pd.DataFrame(_rows)
    assert tables["not in source key"].sum() == 0, "the cell key has a number the source key doesn't"
    print(tables.to_string(index=False))
    return NUMBER, tables


@app.cell(hide_code=True)
def _(tables):
    mo.md(rf"""
    **{int((tables["printed totals"] > 0).sum())} of {len(tables)} keyed tables print a total**, both on NRC
    pages: Table II on 5777799 (fuel leakage for 10 µ and 30 µ particles, and their total, for each case) and the
    1981 dot-matrix pellet table on 1083928 (total UO2 weight and total fuel length under the table). FIS
    discharge tables print none: peak flows at different points on a river don't add up. That leaves
    {int(tables["printed totals"].sum())} checkable columns, so the totals check below rests on very few columns.

    The pellet table has 60 rows and the source key covers rows 1-15. To score the totals we need the whole
    weight and length columns. Both image reads agree on all 600 values in rows 1-60, and their weight and
    length columns add up exactly to the printed totals, so we take that transcription as the truth for rows
    16-60. We use those rows only for the totals check and leave them out of the accuracy scores, since scoring
    the image pipelines against their own reading would be circular.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Reading cells out of a transcript

    The NRC answers are transcripts, not tables. The image pipeline was asked for "tables row by row" and mostly
    wrote Markdown tables. The two OCR-text pipelines were asked for "a clean transcription" and wrote lines of
    text. For each table we:

    1. cut the transcript down to the table (from its title to the note under it),
    2. find each row's label, and take the text from there up to the next row's label,
    3. read the values in that stretch left to right: numbers, ranges like 10-30, powers like 4.133x10-4, and
       printed placeholders such as `-`, `---`, `NA` and `*`, which hold a column but aren't scored.

    A value is **in the right cell** if it's the n-th value in its row, as printed. It is **in the right row**
    if it's anywhere in that row's stretch, and **found** if it's anywhere in the transcript, which is what the
    source spike measured. A wrong value is a **wrong cell** if its value is somewhere else in the transcript,
    a **wrong digit** if a different value sits in its place, and **missing** if nothing does.
    """)
    return


@app.cell
def _():
    TOKEN = re.compile(
        r"(?<![A-Za-z\d.])-?(?:\d+(?:[.,]\d+)*|\.\d+)(?:\s*x\s*10\s*-\s*\d+)?(?:-(?:\d+(?:[.,]\d+)*|\.\d+))?"
        r"|(?<![\w-])-{1,3}(?![\w-])|\bNA\b|\bNil\b|\*{1,2}",  # a range is printed without spaces: 10-30
        re.IGNORECASE,
    )
    SIMPLE = re.compile(r"-?(\d[\d,]*\.?\d*|\.\d+)")
    SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")

    def clean(text: str) -> str:
        """Write powers of ten one way, and drop Markdown's |---|---| rule lines, which aren't printed values."""
        text = text.replace("×", "x").replace("−", "-").replace("–", "-")
        text = re.sub(r"10([⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+)", lambda m: "10" + m.group(1).translate(SUPERSCRIPT), text)
        return re.sub(r"(?m)^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-*\s*$", "", text)

    def value(token: str) -> tuple[str, ...]:
        """A printed value in a form that compares fairly: .4204 equals 0.4204, 10,800 equals 10800."""
        token = re.sub(r"\s+", "", token)
        if SIMPLE.fullmatch(token):
            return (format(Decimal(token.replace(",", "")).normalize(), "f"),)
        return tuple(format(Decimal(n.replace(",", "")).normalize(), "f") for n in re.findall(r"\d[\d,]*\.?\d*", token))

    def amount(token: str | None) -> Decimal | None:
        """The number a cell holds for adding up: a placeholder is 0, anything not a plain number is None."""
        if token is None:
            return None
        token = re.sub(r"\s+", "", token)
        if not value(token):
            return Decimal(0)
        return Decimal(token.replace(",", "")) if SIMPLE.fullmatch(token) else None

    def segment(text: str, table: dict) -> dict[int, list[str]]:
        """The values in each row of `table` found in `text`, keyed by row number. Rows not found are left out."""
        text = clean(text)
        start = re.search(table["start"], text, re.IGNORECASE)
        region = text[start.end() :] if start else text
        end = re.search(table["end"], region, re.IGNORECASE)
        region = region[: end.start()] if end else region
        hits = sorted(
            (m.start(), m.end(), i)
            for i, row in enumerate(table["rows"])
            if (m := re.search(row["label"], region, re.IGNORECASE))
        )
        cut = [h[0] for h in hits[1:]] + [len(region)] if hits else []
        return {i: TOKEN.findall(region[b:stop]) for (_, b, i), stop in zip(hits, cut, strict=True)}

    return TOKEN, amount, clean, segment, value


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring the NRC tables

    Six model pipelines from the source spike: the PDF's text layer, Tesseract's text or the page image, each
    read by Claude Haiku 5.5 and by Gemini 3.8 Flash. (The two no-model pipelines aren't saved as answers; they
    would need Tesseract and the PDFs, and they aren't AI reads.)
    """)
    return


@app.cell
def _(CELL_KEY, MODELS, NRC_QUALITY, SOURCE, TOKEN, clean, segment, value):
    NRC_PIPELINES = {
        "Text-layer-then-model": "Text layer, then model",
        "Tesseract-then-model": "Tesseract, then model",
        "Image-model": "Page image",
    }
    _slots = []
    nrc_usd = 0.0
    for _model, _model_name in MODELS.items():
        for _folder, _pipeline in NRC_PIPELINES.items():
            for _osti, _page in CELL_KEY.items():
                if _osti == "_about":
                    continue
                _saved = json.loads((SOURCE / "answers" / "nrc" / _model / _folder / f"{_osti}.json").read_text())
                nrc_usd += float(_saved["usd"])
                _text = (_saved["output"] or {}).get("text", "")
                _on_page = collections.Counter(value(t) for t in TOKEN.findall(clean(_text)))
                for _table in _page["tables"]:
                    _cells = segment(_text, _table)
                    for _r, _row in enumerate(_table["rows"]):
                        _got = _cells.get(_r)
                        for _c, _printed in enumerate(_row["values"]):
                            _key = value(_printed)
                            if not _key:
                                continue
                            _found = _on_page[_key] > 0
                            _on_page[_key] -= _found
                            _there = _got[_c] if _got is not None and _c < len(_got) else None
                            _right = _there is not None and value(_there) == _key
                            _slots.append(
                                {
                                    "model": _model_name,
                                    "pipeline": _pipeline,
                                    "osti": _osti,
                                    "quality": NRC_QUALITY[_osti],
                                    "table": _table["name"],
                                    "row": _r,
                                    "col": _c,
                                    "scored": _row["scored"],
                                    "key": _printed,
                                    "read": _there,
                                    "found": _found,
                                    "in_row": _got is not None and _key in {value(t) for t in _got},
                                    "in_cell": _right,
                                    "outcome": "right"
                                    if _right
                                    else "wrong cell"
                                    if _found
                                    else "wrong digit"
                                    if _there is not None and value(_there)
                                    else "missing",
                                    "failed": bool(_saved["error"]),
                                }
                            )
    slots = pd.DataFrame(_slots)
    print(f"{slots.scored.sum()} scored cells, {(~slots.scored).sum()} more for the totals check")
    print(slots[slots.scored].groupby(["model", "pipeline"]).outcome.value_counts().unstack(fill_value=0))
    return nrc_usd, slots


@app.cell
def _():
    def share(k: int, n: int) -> str:
        """k of n as a percentage with its Wilson 95% interval."""
        if n == 0:
            return "n/a"
        ci = binomtest(int(k), int(n)).proportion_ci(method="wilson")
        return f"{100 * k / n:.1f}% ({100 * ci.low:.0f}-{100 * ci.high:.0f})"

    return (share,)


@app.cell
def _(share, slots):
    _scored = slots[slots.scored]
    _parts = []
    for _quality, _group in [("all", _scored), *_scored.groupby("quality")]:
        _g = _group.groupby(["model", "pipeline"]).agg(
            cells=("key", "size"), found=("found", "sum"), in_row=("in_row", "sum"), in_cell=("in_cell", "sum")
        )
        _g["scan"] = _quality
        _parts.append(_g.reset_index())
    nrc_table = pd.concat(_parts)
    nrc_table["found %"] = [share(k, n) for k, n in zip(nrc_table.found, nrc_table.cells, strict=True)]
    nrc_table["right row %"] = [share(k, n) for k, n in zip(nrc_table.in_row, nrc_table.cells, strict=True)]
    nrc_table["right cell %"] = [share(k, n) for k, n in zip(nrc_table.in_cell, nrc_table.cells, strict=True)]
    nrc_table["gap (cells)"] = nrc_table.found - nrc_table.in_cell
    nrc_table = nrc_table[
        ["scan", "model", "pipeline", "cells", "found %", "right row %", "right cell %", "gap (cells)"]
    ]
    print(nrc_table.to_string(index=False))
    print(_scored.groupby("osti").agg(quality=("quality", "first"), cells=("key", "size")).to_string())
    return (nrc_table,)


@app.cell(hide_code=True)
def _(nrc_table):
    _all = nrc_table[nrc_table.scan == "all"].set_index(["model", "pipeline"])
    _img = _all.loc[("Claude Haiku 5.5", "Page image")]
    _tess = _all.loc[("Claude Haiku 5.5", "Tesseract, then model")]
    mo.md(rf"""
    **What this shows.** Reading the image, Haiku put {_img["right cell %"]} of the NRC table values in the right
    cell, against {_img["found %"]} found. The gap is {_img["gap (cells)"]} cells. Through Tesseract's text
    the gap opens up: Haiku found {_tess["found %"]} but placed {_tess["right cell %"]}. Most of the
    gap is values that landed in the right row but the wrong column, or in a different row, as OCR text loses
    the table's layout. Gemini's image read has no answer for 5777799: Gemini refused that page four times
    in the source spike (HTTP 502, "blocked the response: OTHER"), so its 79 values there count as missing.

    The intervals are Wilson 95% intervals that treat every cell as independent. They aren't: cells on one page
    share a scan and a layout, and there are only 4 pages, so the real uncertainty is wider than shown.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### What a misplaced row looks like

    One row of 5777799 Table II, as each pipeline left it. Every number below was "found" by the source
    spike's measure.
    """)
    return


@app.cell
def _(slots):
    _row = slots[(slots.osti == "5777799") & (slots.table.str.startswith("Table II")) & (slots.row == 6)]
    example = _row.pivot_table(index=["model", "pipeline"], columns="col", values="read", aggfunc="first")
    example = example.reindex(columns=sorted(_row.col.unique()))
    example.loc[("key", "printed"), :] = _row.drop_duplicates("col").set_index("col").key[example.columns].tolist()
    example.columns = [f"Case {c + 1}" for c in example.columns]
    print("Total fuel mass remaining in bubble when bubble release starts (Kg)")
    print(example.fillna("").to_string())
    return (example,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring the FIS tables

    The FIS answers are typed rows (location, drainage area, four discharges), so the cell score is the source
    spike's own method: pair each key row with the answer row that agrees most, then compare column by column.
    We compare numbers exactly, as the source did. The found score asks only whether the value appears in any
    row or column of the answer.
    """)
    return


@app.cell
def _(FIS_KEY, FIS_KIND, MODELS, SOURCE, value):
    _fields = ["drainage_area", "q10", "q2", "q1", "q02"]
    _out = []
    fis_usd = 0.0
    for _model, _model_name in MODELS.items():
        for _path in sorted((SOURCE / "answers" / "fis" / _model).glob("*/*.json")):
            _doc, _pipeline = _path.stem, _path.parent.name.replace("-", " ")
            _saved = json.loads(_path.read_text())
            fis_usd += float(_saved["usd"])
            _found_rows = (_saved["output"] or {}).get("rows", [])
            _answer = [[r.get("location", "")] + [value(r.get(f, "") or "") for f in _fields] for r in _found_rows]
            _anywhere = collections.Counter(v for a in _answer for v in a[1:] if v)
            _unused = list(range(len(_answer)))
            for _key_row in FIS_KEY[_doc]["rows"]:
                _key = [_key_row[1]] + [value(v) for v in _key_row[2:]]

                def _agree(i: int, key: list = _key, answer: list = _answer) -> int:
                    _location = fuzz.ratio(answer[i][0].lower(), key[0].lower()) >= 85
                    return 2 * _location + sum(a == k for a, k in zip(answer[i][1:], key[1:], strict=True) if k)

                _best = max(_unused, key=_agree, default=None)
                _paired = _best is not None and _agree(_best) >= 2
                if _paired:
                    _unused.remove(_best)
                for _j, _k in enumerate(_key[1:], start=1):
                    if not _k:
                        continue
                    _found = _anywhere[_k] > 0
                    _anywhere[_k] -= _found
                    _there = _answer[_best][_j] if _paired else ()
                    _out.append(
                        {
                            "model": _model_name,
                            "pipeline": _pipeline,
                            "doc": _doc,
                            "scan": FIS_KIND[_doc],
                            "found": _found,
                            "in_cell": _there == _k,
                            "outcome": "right"
                            if _there == _k
                            else "wrong cell"
                            if _found
                            else "wrong digit"
                            if _there
                            else "missing",
                        }
                    )
    fis_slots = pd.DataFrame(_out)
    return fis_slots, fis_usd


@app.cell
def _(fis_slots, share):
    _g = fis_slots.groupby(["scan", "model", "pipeline"]).agg(
        cells=("found", "size"), found=("found", "sum"), in_cell=("in_cell", "sum")
    )
    _g["found %"] = [share(k, n) for k, n in zip(_g.found, _g.cells, strict=True)]
    _g["right cell %"] = [share(k, n) for k, n in zip(_g.in_cell, _g.cells, strict=True)]
    _g["gap (cells)"] = _g.found - _g.in_cell
    fis_table = _g.reset_index()[["scan", "model", "pipeline", "cells", "found %", "right cell %", "gap (cells)"]]
    print(fis_table.to_string(index=False))
    return (fis_table,)


@app.cell(hide_code=True)
def _(fis_table):
    _scan = fis_table[fis_table.scan == "scan"]
    mo.md(rf"""
    **What this shows.** On the scanned FIS tables the gap between found and right cell is
    {int(_scan["gap (cells)"].min())} to {int(_scan["gap (cells)"].max())} cells per pipeline. The page image put
    every value in its cell with both models. The text pipelines lose values outright (wrong digits and missing
    rows) more than they misplace them, because each FIS row is typed by the model into named fields, which
    keeps a value and its column together. The whole-study runs aren't given the page, so a few of their
    numbers come from elsewhere in the study.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The totals check

    For each column with a printed total, add up the extracted values and compare with the extracted total. It
    passes if they agree to the last printed decimal. A column that can't be added up (a value is missing or
    isn't a number) fails too, since a reviewer would have to look at it. For the pellet table the length
    total is the sum of the mean of the two length readings (L-1 and L-2), which is how the printed 30.0435 adds
    up.

    Then we compare with the key: a column with any wrong value (a part or the total) should fail, and a column
    with every value right should pass.
    """)
    return


@app.cell
def _(CELL_KEY, MODELS, SOURCE, amount, clean, segment, slots, value):
    _checks = []
    for _model, _model_name in MODELS.items():
        for _folder, _pipeline in [
            ("Text-layer-then-model", "Text layer, then model"),
            ("Tesseract-then-model", "Tesseract, then model"),
            ("Image-model", "Page image"),
        ]:
            for _osti, _page in CELL_KEY.items():
                if _osti == "_about":
                    continue
                _saved = json.loads((SOURCE / "answers" / "nrc" / _model / _folder / f"{_osti}.json").read_text())
                _text = (_saved["output"] or {}).get("text", "")
                for _table in _page["tables"]:
                    _cells = segment(_text, _table)
                    _mine = slots[
                        (slots.model == _model_name)
                        & (slots.pipeline == _pipeline)
                        & (slots.osti == _osti)
                        & (slots.table == _table["name"])
                    ].set_index(["row", "col"])
                    for _check in _table["totals"]:
                        _outcomes = [_mine.outcome[(r, c)] for r, c in _check["parts"] if (r, c) in _mine.index]
                        _parts = [
                            amount(_cells[r][c] if r in _cells and c < len(_cells[r]) else None)
                            for r, c in _check["parts"]
                        ]
                        if "total_regex" in _check:
                            _m = re.search(_check["total_regex"], clean(_text), re.IGNORECASE)
                            _total = amount(_m.group(1)) if _m else None
                            _printed = _check["total_value"]
                            _right = _m is not None and value(_m.group(1)) == value(_printed)
                            _outcomes.append("right" if _right else "missing" if _m is None else "wrong digit")
                        else:
                            _r, _c = _check["total"]
                            _printed = _table["rows"][_r]["values"][_c]
                            _total = amount(_cells[_r][_c] if _r in _cells and _c < len(_cells[_r]) else None)
                            _outcomes.append(_mine.outcome[(_r, _c)])
                        _decimals = len(_printed.split(".")[1]) if "." in _printed else 0
                        _adds_up = (
                            _total is not None
                            and None not in _parts
                            and abs(sum(_parts) / _check["divide"] - _total) <= Decimal(5) / 10 ** (_decimals + 1)
                        )
                        _errors = collections.Counter(o for o in _outcomes if o != "right")
                        _checks.append(
                            {
                                "model": _model_name,
                                "pipeline": _pipeline,
                                "osti": _osti,
                                "column": _check["name"],
                                "cells": len(_outcomes),
                                "parts add to": None if None in _parts else str(sum(_parts) / _check["divide"]),
                                "total read": None if _total is None else str(_total),
                                "flagged": not _adds_up,
                                "errors": sum(_errors.values()),
                                "wrong cell": _errors["wrong cell"],
                                "wrong digit": _errors["wrong digit"],
                                "missing": _errors["missing"],
                            }
                        )
    checks = pd.DataFrame(_checks)
    print(checks.to_string(index=False))
    return (checks,)


@app.cell
def _(checks):
    _bad = checks[checks.errors > 0]
    _good = checks[checks.errors == 0]
    _rows = [
        {"": "columns checked", "count": len(checks)},
        {"": "columns with an error", "count": len(_bad)},
        {"": "  flagged by the check (caught)", "count": int(_bad.flagged.sum())},
        {"": "  passed the check (missed)", "count": int((~_bad.flagged).sum())},
        {"": "columns with every value right", "count": len(_good)},
        {"": "  flagged anyway (false alarm)", "count": int(_good.flagged.sum())},
    ]
    for _kind in ["wrong cell", "wrong digit", "missing"]:
        _rows.append(
            {
                "": f"{_kind} errors: caught / missed",
                "count": f"{int(_bad[_bad.flagged][_kind].sum())} / {int(_bad[~_bad.flagged][_kind].sum())}",
            }
        )
    totals_summary = pd.DataFrame(_rows)
    print(totals_summary.to_string(index=False))
    return (totals_summary,)


@app.cell(hide_code=True)
def _(checks, totals_summary):
    _bad = checks[checks.errors > 0]
    _clean_flagged = checks[(checks.errors == 0) & checks.flagged]
    _missed = _bad[~_bad.flagged]
    _missed_list = "".join(f"; {r.pipeline} ({r.model}) on {r.column}" for r in _missed.itertuples())
    _w = checks[(checks.pipeline == "Tesseract, then model") & (checks.column == "Total UO2 weight")].set_index("model")
    mo.md(rf"""
    **What this shows.** Of {len(checks)} column checks (7 columns times six pipelines), {len(_bad)} had at
    least one wrong value, and the check flagged {int(_bad.flagged.sum())} of them. It missed
    {len(_missed)}{_missed_list},
    and raised {len(_clean_flagged)} false alarms on the {len(checks) - len(_bad)} columns that were right.

    Most of what it caught a reviewer would see anyway: whole rows missing, or a column where OCR turned every
    `.4204` into `.24204`. The case it's for is the quiet one, and the pellet table has it twice. Reading
    Tesseract's text, Haiku misread {_w.loc["Claude Haiku 5.5", "wrong digit"]} of the 60 weights by a digit or
    two (11.595 for 11.505), and the column added up to {_w.loc["Claude Haiku 5.5", "parts add to"]} g instead
    of the printed {_w.loc["Claude Haiku 5.5", "total read"]}. Flash misread
    {_w.loc["Gemini 3.8 Flash", "wrong digit"]} and added up to {_w.loc["Gemini 3.8 Flash", "parts add to"]}.
    Every value there looks plausible on its own; only the sum gives them away.

    The check says a column is wrong, not which cell, and it rests on 7 columns from 2 tables. It can't see
    errors that leave the sum unchanged, such as two values swapped within a column.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this doesn't show

    - **Very few totals.** 2 of 13 keyed tables and 7 columns print a total. The catch rate rests on those 7
      columns read by six pipelines, which is 42 checks but far fewer independent cases.
    - **Swaps within a column pass.** If two values in one column trade places, the column still adds up. The
      check only sees errors that change a column's sum. Two errors that cancel out would also pass.
    - **Tables with no totals get no check.** None of the FIS discharge tables, the absorbent table or the
      fragility table print a total.
    - **A small, AI-built key.** Four NRC pages and eight FIS pages. The NRC number key was built by an AI
      worker, and the row/column key here was too, by eye from the page images. Rows 16-60 of the pellet table
      come from the two image reads (checked against the printed totals), not by eye.
    - **The OCR-text pipelines weren't asked for a table.** They were asked for a clean transcription, so their
      cell scores measure whether their output can be used as a table, not whether they followed an
      instruction to make one. Our row finder also only sees a row if its label survived OCR.
    """)
    return


@app.cell
def _(RESULTS, checks, example, fis_table, fis_usd, nrc_table, nrc_usd, slots, tables, totals_summary):
    _seconds = time.perf_counter() - STARTED
    slots.to_csv(RESULTS / "nrc_cells.csv", index=False)
    checks.to_csv(RESULTS / "totals_checks.csv", index=False)
    (RESULTS / "results.md").write_text(
        "# Results\n\n"
        + "## Keyed tables\n\n"
        + tables.to_markdown(index=False)
        + "\n\n## NRC tables: found vs right row vs right cell (Wilson 95% interval)\n\n"
        + nrc_table.to_markdown(index=False)
        + "\n\n### One row of 5777799 Table II: total fuel mass remaining when bubble release starts (Kg)\n\n"
        + example.fillna("").to_markdown()
        + "\n\n## FIS tables: found vs right cell (Wilson 95% interval)\n\n"
        + fis_table.to_markdown(index=False)
        + "\n\n## Totals check\n\n"
        + totals_summary.to_markdown(index=False)
        + "\n\n"
        + checks.to_markdown(index=False)
        + f"\n\nThis run: {_seconds:.1f} s, $0 (no model calls). The saved answers it rescores cost"
        + f" ${nrc_usd + fis_usd:.2f} when the source spike made them (NRC ${nrc_usd:.2f}, FIS ${fis_usd:.2f}).\n"
    )
    print(f"wrote {RESULTS}, {_seconds:.1f} s")
    return


if __name__ == "__main__":
    app.run()
