import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import csv
    import json
    import math
    import os
    import re
    from collections import Counter
    from datetime import date
    from pathlib import Path

    import marimo as mo
    import pyarrow as pa
    import pyarrow.parquet as pq
    from PIL import Image, ImageDraw

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("CCR_OUTPUT_DIR", HERE / "output"))
    PAGES = OUT / "pages"
    SHOTS = HERE / "screenshots"
    RESULTS = HERE / "results"
    REVIEW_SECONDS, REVIEW_USD_PER_HOUR = 30, 40.0


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Review rule, scores and the dataset

    This notebook turns the two readings into values, sends a field to review when they disagree or fail a check,
    scores everything against each report's results table, writes the dataset, and sizes the whole job.

    ## Reading a result

    Both models copy each result as printed; the comparison is on what it means. A result is a number and a
    non-detect flag:

    - `< 0.00200` is a non-detect at 0.002;
    - `ND` (Energy Laboratories' style) is a non-detect at the reporting limit printed beside it;
    - units copied into the result (`ND mg/L`) are dropped, and only the day of a collection date is compared,
      because one model adds the time of day and the other doesn't;
    - anything else is a number, so `0.0088` and `0.00880` are the same value.

    Constituent names are matched to the twenty Appendix III and IV constituents the results table holds. Radium,
    conductivity, alkalinity and the rest are kept in the dataset but not scored.
    """)
    return


@app.cell
def _():
    CANONICAL = {
        "antimony": "antimony",
        "arsenic": "arsenic",
        "barium": "barium",
        "beryllium": "beryllium",
        "boron": "boron",
        "cadmium": "cadmium",
        "calcium": "calcium",
        "chloride": "chloride",
        "chromium": "chromium",
        "cobalt": "cobalt",
        "fluoride": "fluoride",
        "lead": "lead",
        "lithium": "lithium",
        "mercury": "mercury",
        "molybdenum": "molybdenum",
        "selenium": "selenium",
        "sulfate": "sulfate",
        "thallium": "thallium",
        "total dissolved solids": "tds",
        "tds": "tds",
        "solids, total dissolved": "tds",
    }

    def canonical(name: str) -> str | None:
        text = name.lower().strip()
        if re.fullmatch(r"ph\b.*", text) or text.startswith("ph,"):
            return "ph"
        return next((c for k, c in CANONICAL.items() if text.startswith(k) or text.split(",")[0] == k), None)

    def number(text: str | None) -> float | None:
        match = re.search(r"\d*\.?\d+(?:[eE]-?\d+)?", (text or "").replace(",", ""))
        return float(match.group()) if match else None

    def meaning(printed: str | None, reporting_limit: str | None = None) -> tuple[bool, float | None] | None:
        """(non-detect, value) for a printed result, or None if it can't be read."""
        text = re.sub(r"(MG/L|UG/L|S\.?U\.?)$", "", (printed or "").strip().upper().replace(" ", ""))
        if not text:
            return None
        if text.startswith("<"):
            return True, number(text)
        if text in ("ND", "U", "<RL", "NOTDETECTED"):
            return True, number(reporting_limit)
        value = number(text)
        return None if value is None else (False, value)

    def same(a: tuple | None, b: tuple | None) -> bool:
        if a is None or b is None or a[0] != b[0] or a[1] is None or b[1] is None:
            return False
        return math.isclose(a[1], b[1], rel_tol=1e-9, abs_tol=1e-12)

    def well_name(text: str | None) -> str:
        return re.sub(r"\s+", "", (text or "").upper()).translate(str.maketrans("‐‑‒–", "----"))

    return canonical, meaning, same, well_name


@app.cell
def _(canonical, meaning, well_name):
    reports = {r["id"]: r for r in json.loads((OUT / "reports.json").read_text())}
    pages = {p["key"]: p for p in json.loads((OUT / "pages.json").read_text())}
    key_rows = json.loads((OUT / "key.json").read_text())
    _r = json.loads((OUT / "readings.json").read_text())
    MODELS, readings = _r["models"], _r["readings"]
    adjudications = json.loads((HERE / "adjudications.json").read_text())

    def page_reading(output: dict | None) -> dict | None:
        """A model's answer for one page, reduced to well, date and {analyte: (meaning, row)}."""
        if not output or not output["is_lab_result_page"]:
            return None
        values = {}
        for row in output["results"]:
            analyte = canonical(row["analyte"])
            if analyte and analyte not in values:
                values[analyte] = (meaning(row["result"]["printed"], row.get("reporting_limit")), row)
        return {
            "well": well_name((output.get("client_sample_id") or {}).get("printed")),
            "date": ((output.get("collection_date") or {}).get("iso") or "")[:10] or None,
            "values": values,
        }

    reduced = {name: {k: page_reading(r["output"]) for k, r in by_page.items()} for name, by_page in readings.items()}
    key = {}
    for _k in key_rows:
        key.setdefault((_k["report"], well_name(_k["well"]), _k["date"]), {})[_k["analyte"]] = _k
    print(f"{len(key)} samples in the answer key; {len(adjudications)} fields checked on the scan")
    return MODELS, adjudications, key, pages, readings, reduced, reports


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The review rule

    A page counts as a lab result page when both models say so; if only one does, the whole page goes to review.
    On a lab page, a field goes to review with a reason when:

    - **the two models disagree** on its value, or only one of them read it;
    - **it fails a check**: the result can't be read as a number, the units aren't the usual ones for that
      constituent (mg/L, or s.u. for pH), the value is outside a plausible range (pH 0 to 14, anything else 0 to
      100,000 mg/L), or the collection date isn't in or just before the report's year.

    The well name and collection date are fields too, checked the same way. Every other field is accepted as read.
    """)
    return


@app.cell
def _(pages, reduced, reports, same):
    UNITS_OK = {"ph": {"s.u.", "su", "s.u", "units", "std units", "ph units", "none", ""}}

    def checks(analyte: str, value: tuple | None, units: str) -> list[str]:
        failed = []
        if value is None or value[1] is None:
            return ["unreadable result"]
        unit = units.lower().strip()
        if analyte == "ph":
            if unit not in UNITS_OK["ph"]:
                failed.append(f"units {units}")
            if not 0 <= value[1] <= 14:
                failed.append("pH outside 0-14")
        else:
            if unit != "mg/l":
                failed.append(f"units {units}")
            if not 0 <= value[1] <= 100_000:
                failed.append("implausible value")
        return failed

    fields, page_review = [], {}
    for _key, _page in pages.items():
        _g, _m = reduced["gemini"][_key], reduced["mistral"][_key]
        if (_g is None) != (_m is None):
            page_review[_key] = "only one model calls it a lab result page"
        if _g is None or _m is None:
            continue
        _year = int(reports[_page["report"]]["year"])
        for _f in ("well", "date"):
            _reasons = [] if _g[_f] == _m[_f] else ["models disagree"]
            if _f == "date" and not (_g["date"] or "").startswith((str(_year), str(_year - 1))):
                _reasons.append("date outside report year")
            fields.append({"page": _key, "field": _f, "gemini": _g[_f], "mistral": _m[_f], "reasons": _reasons})
        for _a in sorted(set(_g["values"]) | set(_m["values"])):
            _gv, _mv = _g["values"].get(_a), _m["values"].get(_a)
            _reasons = []
            if _gv is None or _mv is None:
                _reasons.append("read by one model only")
            elif not same(_gv[0], _mv[0]):
                _reasons.append("models disagree")
            for _v in (_gv, _mv):
                if _v is not None:
                    _reasons += [c for c in checks(_a, _v[0], _v[1]["units"]) if c not in _reasons]
            fields.append({"page": _key, "field": _a, "gemini": _gv, "mistral": _mv, "reasons": _reasons})
    lab_pages = {f["page"] for f in fields}
    reviewed = [f for f in fields if f["reasons"]]
    pages_in_review = {f["page"] for f in reviewed} | set(page_review)
    print(f"{len(lab_pages)} lab result pages both models agree on; {len(page_review)} pages where they don't")
    print(f"{len(fields)} fields; {len(reviewed)} ({len(reviewed) / len(fields):.1%}) sent to review")
    print(f"{len(pages_in_review)} of {len(lab_pages) + len(page_review)} pages have something in review")
    print(Counter(r for f in reviewed for r in f["reasons"]).most_common())
    return fields, lab_pages, page_review, pages_in_review, reviewed


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring against the results table

    Each lab page is matched to the results table by report, well and collection date (Gemini's reading first,
    then Mistral's). The match allows three days, because the table sometimes gives the event's date and the lab
    the day the bottle was filled, and treats the letter O and the digit 0 alike, because one Huntington well is
    `HLF-1O` (letter O) and the models often read it as `HLF-10`. The well name itself is then scored exactly.
    Pages that match nothing are counted with their reason: field duplicates and blanks aren't in the table,
    and blocks with an ambiguous well name were dropped from the key.

    On a matched page every scored constituent is **right**, **wrong** or **missing** for each model. The truth is
    the results table, except where the table itself is in doubt: when both models agree with each other and not
    with the table, or all three differ, the field was checked on the page image and the value seen there is in
    `adjudications.json`, which wins. A pair's accepted value is a field that didn't go to review, and it counts as
    **accepted wrong** if it isn't the truth.
    """)
    return


@app.cell
def _(adjudications, fields, key, meaning, pages, reduced, same):
    def loose(well: str) -> str:
        return well.replace("O", "0")

    def match(page_key: str) -> tuple | None:
        """The results-table sample for a page: same report, well (O and 0 alike) and date within three days."""
        report = pages[page_key]["report"]
        for name in ("gemini", "mistral"):
            r = reduced[name][page_key]
            if not r or not r["date"]:
                continue
            day = date.fromisoformat(r["date"])
            near = [
                s
                for s in key
                if s[0] == report
                and loose(s[1]) == loose(r["well"])
                and abs((date.fromisoformat(s[2]) - day).days) <= 3
            ]
            if near:
                return min(near, key=lambda s: abs((date.fromisoformat(s[2]) - day).days))
        return None

    matched = {p: match(p) for p in {f["page"] for f in fields}}
    scored, to_check = [], []
    for _f in fields:
        _sample = matched[_f["page"]]
        if _sample is None or _f["field"] in ("well", "date") or _f["field"] not in key[_sample]:
            continue
        _row = key[_sample][_f["field"]]
        _id = f"{_f['page']}:{_f['field']}"
        _table = meaning(_row["value"])
        _truth = meaning(adjudications[_id]["scan"]) if _id in adjudications else _table
        _verdict = {}
        for _name in ("gemini", "mistral"):
            _v = _f[_name]
            _verdict[_name] = "missing" if _v is None else ("right" if same(_v[0], _truth) else "wrong")
        _gv, _mv = _f["gemini"], _f["mistral"]
        _pair_agree = _gv is not None and _mv is not None and same(_gv[0], _mv[0])
        if _id not in adjudications and (
            (_pair_agree and not same(_gv[0], _table))
            or (_gv and _mv and not _pair_agree and not same(_gv[0], _table) and not same(_mv[0], _table))
        ):
            to_check.append(
                {
                    "id": _id,
                    "table": _row["value"],
                    "gemini": _gv[1]["result"]["printed"],
                    "mistral": _mv[1]["result"]["printed"],
                    "table_page": _row["table_page"],
                }
            )
        _accepted = None if _f["reasons"] else _gv
        scored.append(
            {
                **_f,
                "id": _id,
                "sample": _sample,
                "table": _row["value"],
                "truth": _truth,
                "checked": _id in adjudications,
                "verdict": _verdict,
                "accepted_wrong": _accepted is not None and not same(_accepted[0], _truth),
            }
        )
    _unmatched = [p for p, s in matched.items() if s is None]
    print(
        f"{len(matched) - len(_unmatched)} of {len(matched)} lab pages matched to the results table; "
        f"{len(scored)} fields scored"
    )
    print(
        f"unmatched pages: {len(_unmatched)}, e.g. {[(reduced['gemini'][p] or {}).get('well') for p in _unmatched[:8]]}"
    )
    print(f"{len(to_check)} fields still to check on the scan")

    def true_well(page_key: str, sample: tuple) -> str:
        return adjudications.get(f"{page_key}:well", {}).get("scan", sample[1])

    well_scores = {"pages": sum(s is not None for s in matched.values())}
    for _name in ("gemini", "mistral"):
        well_scores[f"{_name} wrong"] = sum(
            1 for p, s in matched.items() if s and reduced[_name][p] and reduced[_name][p]["well"] != true_well(p, s)
        )
    well_scores["accepted wrong"] = sum(
        1
        for p, s in matched.items()
        if s and reduced["gemini"][p]["well"] == reduced["mistral"][p]["well"] != true_well(p, s)
    )
    print("well names:", well_scores)
    SHOTS.mkdir(exist_ok=True)
    for _old in SHOTS.glob("accepted-wrong-*.png"):
        _old.unlink()
    for _p, _s in matched.items():
        if _s and reduced["gemini"][_p]["well"] == reduced["mistral"][_p]["well"] != true_well(_p, _s):
            _img = Image.open(PAGES / f"{_p}.png")
            _img.crop((0, 0, _img.size[0], _img.size[1] // 4)).save(SHOTS / f"accepted-wrong-well-{_p}.png")
    (OUT / "to_check.json").write_text(json.dumps(to_check, indent=1))
    return matched, scored, to_check, well_scores


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The scores

    Error per model reading alone, then the pair with review on disagreement. Scanned and born-digital pages are
    shown apart, then together.
    """)
    return


@app.cell
def _(pages, scored):
    def wilson(k: int, n: int) -> str:
        if n == 0:
            return "n/a"
        z, p = 1.96, k / n
        centre, half = (
            (p + z * z / (2 * n)) / (1 + z * z / n),
            z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n),
        )
        return f"{max(0, centre - half):.2%} to {centre + half:.2%}"

    accuracy = []
    for _kind in ("scanned", "born-digital", "all"):
        _s = [f for f in scored if _kind == "all" or pages[f["page"]]["kind"] == _kind]
        if not _s:
            continue
        _row = {"pages": _kind, "fields scored": len(_s)}
        for _name in ("gemini", "mistral"):
            _c = Counter(f["verdict"][_name] for f in _s)
            _row[f"{_name} wrong"] = f"{_c['wrong']} ({_c['wrong'] / len(_s):.2%})"
            _row[f"{_name} missing"] = f"{_c['missing']} ({_c['missing'] / len(_s):.2%})"
        _rev = [f for f in _s if f["reasons"]]
        _acc = [f for f in _s if not f["reasons"]]
        _aw = sum(f["accepted_wrong"] for f in _acc)
        _row["sent to review"] = f"{len(_rev)} ({len(_rev) / len(_s):.1%})"
        _row["accepted wrong"] = f"{_aw} of {len(_acc)} ({_aw / max(1, len(_acc)):.2%})"
        _row["95% interval"] = wilson(_aw, len(_acc))
        _g_err = [f for f in _s if f["verdict"]["gemini"] != "right"]
        _row["gemini errors caught by review"] = f"{sum(bool(f['reasons']) for f in _g_err)} of {len(_g_err)}"
        accuracy.append(_row)
    for _row in accuracy:
        print(json.dumps(_row))
    mo.ui.table(accuracy, selection=None)
    return (accuracy,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Disagreement versus confidence.** Would Gemini's own confidence have done as well? We give it the same review
    budget: send its lowest-confidence fields, as many as disagreement sent, and count how many of its errors that
    catches.
    """)
    return


@app.cell
def _(scored):
    _budget = sum(bool(f["reasons"]) for f in scored)
    _with_conf = [f for f in scored if f["gemini"] is not None]
    _lowest = sorted(_with_conf, key=lambda f: f["gemini"][1]["result"]["confidence"])[:_budget]
    _errors = [f for f in scored if f["verdict"]["gemini"] != "right"]
    confidence_caught = sum(f in _lowest for f in _errors)
    print(
        f"review budget {_budget} fields: disagreement caught {sum(bool(f['reasons']) for f in _errors)} of "
        f"Gemini's {len(_errors)} errors, its lowest confidence caught {confidence_caught}"
    )
    print(
        "Gemini confidence values used:",
        Counter(f["gemini"][1]["result"]["confidence"] for f in _with_conf).most_common(5),
    )
    return (confidence_caught,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What got through

    Every value accepted without review that isn't the truth, with a crop of the page around Gemini's box.
    """)
    return


@app.cell
def _(scored):
    SHOTS.mkdir(exist_ok=True)
    _wrong = [f for f in scored if f["accepted_wrong"]]
    for _f in _wrong:
        _img = Image.open(PAGES / f"{_f['page']}.png").convert("RGB")
        _w, _h = _img.size
        _x0, _y0, _x1, _y1 = (v / 1000 for v in _f["gemini"][1]["result"]["bbox"])
        _box = (_x0 * _w, _y0 * _h, _x1 * _w, _y1 * _h)
        ImageDraw.Draw(_img).rectangle(_box, outline=(220, 0, 0), width=3)
        _img.crop((0, max(0, _box[1] - 160), _w, min(_h, _box[3] + 160))).save(
            SHOTS / f"accepted-wrong-{_f['id'].replace(':', '-')}.png"
        )
    mo.ui.table(
        [
            {
                "field": f["id"],
                "both read": f["gemini"][1]["result"]["printed"],
                "table": f["table"],
                "checked on scan": f["checked"],
            }
            for f in _wrong
        ],
        selection=None,
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Cost and time

    Model cost is what OpenRouter charged, for every candidate page read, including the custody forms and QC pages
    the models turned away. Review is an assumption, not a measurement: 30 seconds a reviewed field at $40 an hour.
    """)
    return


@app.cell
def _(lab_pages, page_review, readings, reviewed):
    _n = len(readings["gemini"])
    model_usd = sum(r["usd"] for by_page in readings.values() for r in by_page.values())
    seconds = {name: sum(r["seconds"] for r in by_page.values()) / _n for name, by_page in readings.items()}
    _review_fields = len(reviewed) + 20 * len(page_review)
    review_usd = _review_fields * REVIEW_SECONDS / 3600 * REVIEW_USD_PER_HOUR
    _lab = len(lab_pages)
    cost = {
        "candidate pages read": _n,
        "lab result pages": _lab,
        "model cost per page read": round(model_usd / _n, 4),
        "model cost per lab page": round(model_usd / _lab, 4),
        "review cost per lab page (assumed)": round(review_usd / _lab, 4),
        "all-in cost per lab page": round((model_usd + review_usd) / _lab, 4),
        "seconds per page, each model": {k: round(v, 1) for k, v in seconds.items()},
    }
    print(json.dumps(cost, indent=1))
    print(f"(a page in review with no field reading is counted as 20 fields to review; model total ${model_usd:.2f})")
    return (cost,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The dataset

    One row per constituent per lab page, as the pair reads it: Gemini's value where both agree, and the field
    marked for review where they don't. `checked` marks values a person (here, the agent that built this) looked up
    on the page. `page_url` opens the report at the page, and `bbox` is the box on that page.
    """)
    return


@app.cell
def _(fields, matched, page_review, pages, reports, scored):
    _checked = {f["id"]: f for f in scored}
    RESULTS.mkdir(exist_ok=True)

    def _box_suspect(box: list[int]) -> bool:
        """A printed number is wider than it is tall; a box that isn't is probably [y, x, y, x] or wrong."""
        return len(box) != 4 or (box[2] - box[0]) <= (box[3] - box[1])

    rows = []
    for _f in fields:
        if _f["field"] in ("well", "date"):
            continue
        _page = pages[_f["page"]]
        _report = reports[_page["report"]]
        _v = _f["gemini"] or _f["mistral"]
        _head = {x["field"]: x for x in fields if x["page"] == _f["page"] and x["field"] in ("well", "date")}
        _id = f"{_f['page']}:{_f['field']}"
        rows.append(
            {
                "plant": _report["plant"],
                "ccr_unit": _report["unit"],
                "report_year": int(_report["year"]),
                "page_url": f"{_report['url']}#page={_page['page']}",
                "page": _page["page"],
                "page_kind": _page["kind"],
                "well": _head["well"]["gemini"],
                "collection_date": _head["date"]["gemini"],
                "analyte": _f["field"],
                "result_printed": _v[1]["result"]["printed"],
                "nondetect": _v[0][0] if _v[0] else None,
                "value": _v[0][1] if _v[0] else None,
                "units": _v[1]["units"],
                "reporting_limit": _v[1].get("reporting_limit"),
                "lab_qualifier": _v[1].get("qualifier"),
                "bbox": json.dumps(_v[1]["result"]["bbox"]),
                "bbox_suspect": _box_suspect(_v[1]["result"]["bbox"]),
                "gemini_read": _f["gemini"][1]["result"]["printed"] if _f["gemini"] else None,
                "mistral_read": _f["mistral"][1]["result"]["printed"] if _f["mistral"] else None,
                "in_review": bool(_f["reasons"]) or bool(_head["well"]["reasons"]) or bool(_head["date"]["reasons"]),
                "review_reason": "; ".join(
                    _f["reasons"] + [f"{k}: {r}" for k, x in _head.items() for r in x["reasons"]]
                ),
                "checked": _id in _checked and _checked[_id]["checked"],
                "in_results_table": matched.get(_f["page"]) is not None,
            }
        )
    with open(RESULTS / "groundwater_results.csv", "w", newline="") as _fh:
        _w = csv.DictWriter(_fh, fieldnames=list(rows[0]))
        _w.writeheader()
        _w.writerows(rows)
    pq.write_table(pa.Table.from_pylist(rows), RESULTS / "groundwater_results.parquet")
    _queue = [r for r in rows if r["in_review"]] + [
        {"page_url": f"{reports[pages[k]['report']]['url']}#page={pages[k]['page']}", "review_reason": why}
        for k, why in page_review.items()
    ]
    with open(RESULTS / "review_queue.csv", "w", newline="") as _fh:
        _w = csv.DictWriter(_fh, fieldnames=list(rows[0]))
        _w.writeheader()
        _w.writerows(_queue)
    print(f"{len(rows)} rows in groundwater_results.csv/.parquet, {len(_queue)} in review_queue.csv")
    suspect_pages = {r["page_url"] for r in rows if r["bbox_suspect"]}
    _suspect = len([r for r in rows if r["bbox_suspect"]])
    print(
        f"{_suspect} values ({_suspect / len(rows):.1%}) "
        f"on {len(suspect_pages)} pages have a box taller than wide: the box, not the value, is suspect"
    )
    return rows, suspect_pages


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The whole job

    How much is there, and what would reading all of it cost? PacifiCorp's list gives a count of reports per unit
    and year, and our seven reports give pages per report and lab result pages per report. Nationally, EIP counted
    443 reports from 265 plants in the first year (posted in 2018, covering 2017); EPA counted 768 regulated CCR
    units in 2019. Each posts one report a year, and eight report years (2018 to 2025) are not in EIP's database.
    The national figures are an estimate built on PacifiCorp's averages.
    """)
    return


@app.cell
def _(cost, lab_pages, pages, reports):
    _all = json.loads((OUT / "all_reports.json").read_text())
    _since_2018 = [r for r in _all if r["year"] and 2018 <= int(r["year"]) <= 2025]
    _per_report = {}
    for _id, _r in reports.items():
        _scanned_lab = sum(1 for p in lab_pages if pages[p]["report"] == _id and pages[p]["kind"] == "scanned")
        _per_report[_id] = {"pages": _r["pages"], "lab_pages": _scanned_lab + _r["born_digital_candidates"]}
    _pages = sum(v["pages"] for v in _per_report.values()) / len(_per_report)
    _lab = sum(v["lab_pages"] for v in _per_report.values()) / len(_per_report)
    _per_lab_page = cost["all-in cost per lab page"]
    sizing = {
        "PacifiCorp reports listed": len(_all),
        "PacifiCorp reports for 2018-2025": len(_since_2018),
        "pages per report (sample mean)": round(_pages),
        "lab result pages per report (sample mean)": round(_lab),
    }
    for _label, _per_year in (("EIP's 2018 count", 443), ("EPA's unit count", 768)):
        _reports = _per_year * 8
        sizing[f"national reports 2018-2025, {_label}"] = _reports
        sizing[f"national pages, {_label}"] = round(_reports * _pages)
        sizing[f"national lab pages, {_label}"] = round(_reports * _lab)
        sizing[f"national all-in cost, {_label}"] = round(_reports * _lab * _per_lab_page)
    print(json.dumps(sizing, indent=1))
    return (sizing,)


@app.cell
def _(MODELS, accuracy, confidence_caught, cost, rows, sizing, suspect_pages, well_scores):
    (RESULTS / "results.json").write_text(
        json.dumps(
            {
                "models": MODELS,
                "accuracy": accuracy,
                "well_names": well_scores,
                "dataset_rows": len(rows),
                "pages_with_suspect_boxes": len(suspect_pages),
                "confidence_caught": confidence_caught,
                "cost": cost,
                "sizing": sizing,
            },
            indent=1,
        )
    )
    with open(RESULTS / "accuracy.csv", "w", newline="") as _fh:
        _w = csv.DictWriter(_fh, fieldnames=list(accuracy[0]))
        _w.writeheader()
        _w.writerows(accuracy)
    return


if __name__ == "__main__":
    app.run()
