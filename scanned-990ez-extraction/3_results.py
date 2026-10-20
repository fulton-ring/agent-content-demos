import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import re
    from pathlib import Path

    import marimo as mo
    from PIL import Image, ImageDraw

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("EZ_OUTPUT_DIR", HERE / "output"))
    PAGES = OUT / "pages"
    SHOTS = HERE / "screenshots"
    SOI_COLUMN = {
        "ein": "ein",
        "tax_period": "tax_pd",
        "line_1": "totcntrbs",
        "line_2": "prgmservrev",
        "line_3": "duesassesmnts",
        "line_4": "othrinvstinc",
        "line_5a": "grsamtsalesastothr",
        "line_5b": "basisalesexpnsothr",
        "line_5c": "gnsaleofastothr",
        "line_6a": "grsincgaming",
        "line_6b": "grsrevnuefndrsng",
        "line_6c": "direxpns",
        "line_6d": "netincfndrsng",
        "line_7a": "grsalesminusret",
        "line_7b": "costgoodsold",
        "line_7c": "grsprft",
        "line_8": "othrevnue",
        "line_9": "totrevnue",
        "line_17": "totexpns",
        "line_18": "totexcessyr",
        "line_20": "othrchgsnetassetfnd",
        "line_21": "networthend",
    }


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Review rule and scoring

    This notebook turns the two readings into numbers, sends a field to review when they disagree, scores everything
    against the IRS SOI extract, and reports what got through.

    ## Reading a printed amount

    Both models report the text as printed, and the comparison is on the number. The rules follow what SOI does:

    - an empty box, a dash or "NONE" is 0, because SOI records an empty box as 0;
    - `(1,200)`, `-1,200` and `<1,200>` are negative;
    - **cents are dropped, not rounded**. SOI keys `21,658.73` as 21658. Some filers print cents without a point,
      as `34,796 19` or `210 8`, so one or two digits after a space at the end are read as cents too.
    """)
    return


@app.cell
def _():
    def to_number(field: str, value: dict | None) -> int | None:
        """The number a reading stands for, or None if it can't be read as one."""
        if value is None:
            return None if field in ("ein", "tax_period") else 0
        text = value["yyyymm"] if field == "tax_period" else value["printed"]
        text = text.upper().replace("$", "").replace(",", "").strip().rstrip(".").strip()
        if field in ("ein", "tax_period"):
            digits = re.sub(r"\D", "", text)
            return int(digits) if digits else None
        if text in ("", "-", "-0-", "--", "NONE", "N/A", "NA", "0"):
            return 0
        negative = text.startswith(("(", "-", "<")) or text.endswith((")", ">"))
        text = re.sub(r"[()<>\-]", "", text).strip().rstrip(".")
        text = re.sub(r"[.\s]\d{1,2}$", "", text).strip()
        if not re.fullmatch(r"\d+", text.replace(" ", "")):
            return None
        number = int(text.replace(" ", ""))
        return -number if negative else number

    return (to_number,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## One row per field

    Each page has 22 fields. Each row holds both models' numbers, their confidence, their boxes and the SOI value.
    A page that both models say isn't page 1 of the 990-EZ is set aside. In this sample, those were files whose first
    page is another schedule. Those pages are counted as unreadable, not scored.
    """)
    return


@app.cell
def _(to_number):
    _sample = {f"{s['ein']}_{s['tax_pd']}": s for s in json.loads((OUT / "sample.json").read_text())}
    _saved = json.loads((OUT / "readings.json").read_text())
    readings, model_ids = _saved["readings"], _saved["models"]
    not_page_1 = [
        k for k in readings["gemini"] if not any(readings[m][k]["output"]["is_990ez_page_1"] for m in readings)
    ]
    rows = []
    for _key in readings["gemini"]:
        if _key in not_page_1:
            continue
        _g, _q = readings["gemini"][_key]["output"], readings["qwen"][_key]["output"]
        for _field, _column in SOI_COLUMN.items():
            rows.append(
                {
                    "page": _key,
                    "field": _field,
                    "gemini": to_number(_field, _g[_field]),
                    "qwen": to_number(_field, _q[_field]),
                    "soi": int(_sample[_key]["soi"][_column]),
                    "gemini_conf": _g[_field]["confidence"] if _g[_field] else 1.0,
                    "qwen_conf": _q[_field]["confidence"] if _q[_field] else 1.0,
                    "bbox": (_g[_field] or _q[_field] or {}).get("bbox"),
                }
            )
    print(f"{len(rows)} fields on {len(rows) // len(SOI_COLUMN)} pages; {len(not_page_1)} pages weren't page 1")
    return model_ids, not_page_1, readings, rows


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Checking the answer key

    SOI typed its extract from the same paper returns, so it is a good key but not a perfect one. Where the
    readings disagree with SOI, someone has to look at the scan. We looked at:

    - every field where **both models agree with each other but not with SOI**, which is either a shared model
      error or an SOI error;
    - every field where **all three differ**.

    Where one model matches SOI, we take SOI as right: two independent readings agree. Each decision is in
    `adjudications.json`, with the value on the scan and a short note. The adjudication was done by the agent that
    built this demo, looking at each page image. A person has not re-checked it.
    """)
    return


@app.cell
def _(rows):
    adjudicated = {(a["page"], a["field"]): a for a in json.loads((HERE / "adjudications.json").read_text())}
    to_check = [r for r in rows if r["soi"] != r["gemini"] and (r["gemini"] == r["qwen"] or r["qwen"] != r["soi"])]
    missing = [r for r in to_check if (r["page"], r["field"]) not in adjudicated]
    for r in rows:
        decision = adjudicated.get((r["page"], r["field"]))
        r["truth"] = decision["scan"] if decision and r in to_check else r["soi"]
    soi_wrong = [r for r in to_check if r["truth"] != r["soi"]]
    print(f"{len(to_check)} fields checked on the scan; SOI was wrong on {len(soi_wrong)} of them")
    print(f"SOI disagrees with the scan on {len(soi_wrong)} of {len(rows)} fields ({len(soi_wrong) / len(rows):.1%})")
    _kinds = [adjudicated[(r["page"], r["field"])]["kind"] for r in to_check if (r["page"], r["field"]) in adjudicated]
    print("decisions by kind:", {k: _kinds.count(k) for k in sorted(set(_kinds))})
    (OUT / "to_adjudicate.json").write_text(json.dumps(missing, indent=1))
    if missing:
        print(f"{len(missing)} fields needed checking but have no decision, so SOI is taken as right for them;")
        print("they are listed in output/to_adjudicate.json")
    mo.ui.table(
        [{k: r[k] for k in ("page", "field", "gemini", "qwen", "soi", "truth")} for r in soi_wrong],
        selection=None,
        page_size=15,
    )
    return (to_check,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The review rule

    **A field goes to review when the two readings disagree.** When they agree, the value is accepted as read.
    We assume a reviewer who looks at the scan gets the value right. The demo doesn't measure that (see the README).

    For comparison, the usual alternative: **send the fields a model is least sure of**, by its own confidence. To
    compare fairly, each model's confidence rule gets the same review budget: the same number of fields as the
    disagreement rule sends, taking that model's lowest-confidence fields.
    """)
    return


@app.cell
def _(rows):
    n = len(rows)
    review = [r for r in rows if r["gemini"] != r["qwen"]]
    accepted = [r for r in rows if r["gemini"] == r["qwen"]]
    wrong_accepted = [r for r in accepted if r["gemini"] != r["truth"]]
    pages_in_review = {r["page"] for r in review}
    pages = {r["page"] for r in rows}

    def routed_by_confidence(model: str) -> list[dict]:
        return sorted(rows, key=lambda r: r[f"{model}_conf"])[: len(review)]

    comparison = []
    for _model in ("gemini", "qwen"):
        _wrong = [r for r in rows if r[_model] != r["truth"]]
        _by_conf = routed_by_confidence(_model)
        comparison.append(
            {
                "single model": _model,
                "wrong values": len(_wrong),
                "error rate": f"{len(_wrong) / n:.2%}",
                "error rate against SOI as published": f"{sum(r[_model] != r['soi'] for r in rows) / n:.2%}",
                "caught by disagreement": sum(r in review for r in _wrong),
                "caught by own confidence (same budget)": sum(r[_model] != r["truth"] for r in _by_conf),
                "fields below 0.9 confidence": sum(r[f"{_model}_conf"] < 0.9 for r in rows),
            }
        )
    _p, _k, _z = len(wrong_accepted) / len(accepted), len(accepted), 1.96
    _centre = (_p + _z**2 / (2 * _k)) / (1 + _z**2 / _k)
    _half = _z * (_p * (1 - _p) / _k + _z**2 / (4 * _k**2)) ** 0.5 / (1 + _z**2 / _k)
    headline = {
        "fields": n,
        "pages": len(pages),
        "sent to review": f"{len(review)} ({len(review) / n:.1%})",
        "pages with a field in review": f"{len(pages_in_review)} ({len(pages_in_review) / len(pages):.0%})",
        "accepted without review": len(accepted),
        "wrong but accepted": f"{len(wrong_accepted)} ({len(wrong_accepted) / n:.2%} of all fields, "
        f"{len(wrong_accepted) / len(accepted):.2%} of accepted)",
        "error after review": f"{len(wrong_accepted) / n:.2%}",
        "wrong-but-accepted rate, 95% Wilson interval": f"{_centre - _half:.2%} to {_centre + _half:.2%}",
    }
    mo.vstack([mo.ui.table([headline], selection=None), mo.ui.table(comparison, selection=None)])
    return comparison, headline, review, wrong_accepted


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Error by field

    Before review is each model alone. After review is the pair: a value that the two disagree on is fixed by a
    reviewer, and one they agree on stands, right or wrong.
    """)
    return


@app.cell
def _(rows):
    by_field = []
    for _field in SOI_COLUMN:
        _f = [r for r in rows if r["field"] == _field]
        by_field.append(
            {
                "field": _field,
                "SOI column": SOI_COLUMN[_field],
                "Gemini wrong": sum(r["gemini"] != r["truth"] for r in _f),
                "Qwen wrong": sum(r["qwen"] != r["truth"] for r in _f),
                "sent to review": sum(r["gemini"] != r["qwen"] for r in _f),
                "wrong after review": sum(r["gemini"] == r["qwen"] != r["truth"] for r in _f),
                "SOI wrong": sum(r["soi"] != r["truth"] for r in _f),
                "of": len(_f),
            }
        )
    mo.ui.table(by_field, selection=None, page_size=25)
    return (by_field,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Cost and time per page

    Model cost is what OpenRouter charged for both readings, every attempt counted. Time is the model's response
    time per page; the two models run side by side, so a page waits for the slower one. **Review time is an
    assumption, not a measurement**: 30 seconds to check one field against the scan, the box already highlighted,
    at a loaded $40 an hour.
    """)
    return


@app.cell
def _(readings, review, rows):
    SECONDS_PER_REVIEWED_FIELD, REVIEWER_USD_PER_HOUR = 30, 40.0
    _keys = sorted({r["page"] for r in rows} | set(readings["gemini"]))
    _n = len(_keys)
    model_usd = sum(readings[m][k]["usd"] for m in readings for k in _keys)
    review_minutes = len(review) * SECONDS_PER_REVIEWED_FIELD / 60
    cost = {
        "pages read": _n,
        "model cost per page": f"${model_usd / _n:.4f}",
        "Gemini seconds per page": round(sum(readings["gemini"][k]["seconds"] for k in _keys) / _n, 1),
        "Qwen seconds per page": round(sum(readings["qwen"][k]["seconds"] for k in _keys) / _n, 1),
        "review minutes per page": round(review_minutes / _n, 2),
        "review cost per page": f"${review_minutes / 60 * REVIEWER_USD_PER_HOUR / _n:.3f}",
        "all-in cost per page": f"${(model_usd + review_minutes / 60 * REVIEWER_USD_PER_HOUR) / _n:.3f}",
    }
    mo.ui.table([cost], selection=None)
    return (cost,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What got through: every wrong value accepted without review

    Each crop is the scan, with the box both models pointed to outlined in red.
    """)
    return


@app.cell
def _(wrong_accepted):
    def crop(row: dict) -> Image.Image:
        """The page around the field's box, with the box outlined; the whole page, small, if no model gave a box."""
        page = Image.open(PAGES / f"{row['page']}.png").convert("RGB")
        w, h = page.size
        if not row["bbox"] or len(row["bbox"]) != 4:
            return page.resize((w // 3, h // 3))
        xa, ya, xb, yb = (row["bbox"][i] * (w if i % 2 == 0 else h) / 1000 for i in range(4))
        x0, x1, y0, y1 = min(xa, xb), max(xa, xb), min(ya, yb), max(ya, yb)
        ImageDraw.Draw(page).rectangle([x0 - 4, y0 - 4, x1 + 4, y1 + 4], outline="red", width=3)
        return page.crop((max(0, x0 - 550), max(0, y0 - 30), min(w, x1 + 60), min(h, y1 + 20)))

    SHOTS.mkdir(exist_ok=True)
    for _old in SHOTS.glob("accepted-wrong-*.png"):
        _old.unlink()
    _items = []
    for _r in wrong_accepted:
        _path = SHOTS / f"accepted-wrong-{_r['page']}-{_r['field']}.png"
        crop(_r).save(_path)
        _items.append(
            mo.vstack(
                [mo.md(f"`{_r['page']}` {_r['field']}: read {_r['gemini']}, scan says {_r['truth']}"), mo.image(_path)]
            )
        )
    mo.vstack(_items)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What didn't work

    - **Both models miss the IRS's own corrections.** When a filer prints a wrong EIN or tax year, an IRS clerk
      circles it and writes the right one by hand, often beside the organization's name or at the top of the page.
      SOI keys the correction. Both models read the typed value, agree, and the wrong value goes through without
      review. This is most of what the disagreement rule lets through. Two readings that make the same mistake
      don't disagree; a prompt that asks for handwritten corrections might catch them, but this demo didn't test it.
    - **Both models put a value one line down** on a page where line 17 was empty and line 16 wasn't.
    - **Model confidence is close to useless as a routing signal.** Both models put 0.9 or 0.95 on nearly every
      value, right or wrong. Ranked by confidence, the same review budget catches far fewer errors than
      disagreement (table above).
    - **The first frozen schema asked for the tax year as YYYYMM in a field described as "exactly as printed".**
      Both models followed "as printed" and returned dates like `2017` or `06/30/2017`, so the tax period disagreed
      with SOI on every page. Freezing a schema doesn't make it right. The fix was a separate `yyyymm` field and a
      second full reading, which cost about as much as the first; this run has only the second.
    - **Reading amounts.** The first scoring rounded cents, so `21,658.73` scored as 21659 against SOI's 21658, and
      it read `34,796 19` as 3479619 and couldn't read `(2,390.)` at all. These were scoring bugs, not model
      errors, and checking the disagreements on the scan is what found them. A production pipeline would put the
      rule in the schema, so each model returns whole dollars.
    - **The SOI extract is not a transcription.** SOI recomputes totals when the filer's arithmetic is wrong, fixes
      signs, moves amounts between lines, fills in lines the filer left empty, and sometimes mistypes. Scored
      against SOI as published, without checking on the scan, the models look two to three times worse than they
      are (the "against SOI as published" column above). Each case is in `adjudications.json` with its kind:
      `SOI edit`, `SOI typo`, `IRS mark`, `both models wrong` or `ambiguous`.
    """)
    return


@app.cell
def _(by_field, comparison, cost, headline, model_ids, not_page_1, to_check):
    (OUT / "results.json").write_text(
        json.dumps(
            {
                "models": model_ids,
                "headline": headline,
                "comparison": comparison,
                "by_field": by_field,
                "cost": cost,
                "not_page_1": not_page_1,
                "checked_on_scan": len(to_check),
            },
            indent=1,
        )
    )
    return


if __name__ == "__main__":
    app.run()
