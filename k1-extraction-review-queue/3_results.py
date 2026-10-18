import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import re
    from pathlib import Path
    from typing import Any

    import marimo as mo
    import pdfplumber
    from playwright.async_api import async_playwright

    from amounts import parse_value

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("K1_OUTPUT_DIR", HERE / "output"))
    SAMPLES = OUT / "samples"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 3. Results

    The last of three notebooks. `1_documents.py` made the documents and their answer keys, and `2_extraction.py`
    read them with every model, writing each run's values to `output/<run>/extracted.json`. This one scores every run
    against the answer keys, shows the results and what didn't work, and builds each run's review screen.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. Scoring against the answer keys

    No extractor reads the answer keys; this step scores every run afterwards. The real K-1s are scored against the
    hand-keyed `real_answer_key.json`, and a scan against its original's key. The made-up documents are scored against
    the key the generator wrote. **Boxes** means every box on the key plus every value a run reported, so reading
    something in an empty box, or reporting a box twice, is an error. A box the run never reported counts as an
    accepted blank, unless the whole page went to review. It also counts as in review if a row of the same coded box,
    with the same letter or no letter, went to review. The **held-out set** is the 14 documents whose scans and values
    use seeds not used while building the rules.

    Statement lines are checked separately, against the issuer's own text layer, because the keys stop at `STMT`.
    """)
    return


@app.cell
def _():
    answer_keys = {k: v for k, v in json.loads((HERE / "real_answer_key.json").read_text()).items() if k[0] != "_"}
    answer_keys |= json.loads((OUT / "answer_key.json").read_text())

    def same(a: Any, b: Any) -> bool:
        if isinstance(a, int | float) and isinstance(b, int | float):
            return abs(a - b) < 0.005
        if isinstance(a, str) and isinstance(b, str):
            return re.sub(r"[^A-Z0-9]", "", a.upper()) == re.sub(r"[^A-Z0-9]", "", b.upper())
        return a is None and b is None

    def score_document(doc: dict[str, Any]) -> list[dict[str, Any]]:
        """One row per box: whether the run got it right, and whether it was accepted. Marks each value too."""
        key = answer_keys[re.sub(r"-scan\d[ab]\.pdf$", ".pdf", doc["file"])]
        truth = dict(key["fields"])
        if doc["form"] != "BROKER":
            truth |= {k: v for k, v in key["header"].items() if k in ("payer_ein", "payer_name")}
        got = {f["key"]: f for f in doc["fields"] if f["key"] != "page"}
        scan = re.search(r"-scan(\d)[ab]\.pdf$", doc["file"])
        levels = {"original": "born-digital", 0: "clean scan", 1: "office scan", 2: "bad scan"}
        level = {"1": "office scan", "2": "bad scan"}[scan.group(1)] if scan else levels[key["scan_level"]]
        group = "real" if doc["file"][:2] in ("01", "02", "03") else "made-up"
        held_out = doc["file"].startswith("2") or bool(re.search(r"-scan\db\.pdf$", doc["file"]))
        source = f"{'held out' if held_out else 'tuning'} / {group} / {level}"
        rows = []
        for k in sorted(set(truth) | set(got)):
            f, expected = got.get(k), truth.get(k)
            correct = same(f["value"] if f else None, expected) and (f is None or k in truth)
            status = f["status"] if f else ("review" if doc["page_review"] else "accepted")
            box, letter = k.split(" ")[0], k.split(" ")[1].rstrip("*") if " " in k else None
            if (
                f is None
                and letter
                and any(
                    g["status"] == "review" and g["key"].split(" (")[0].rstrip("*") in (f"{box} ?", f"{box} {letter}")
                    for g in doc["fields"]
                )
            ):
                status = "review"
            if f is not None:
                f["correct"], f["expected"] = correct, expected
            rows.append(
                {
                    "file": doc["file"],
                    "key": k,
                    "correct": correct,
                    "status": status,
                    "source": source,
                    "statement": expected == "STMT",
                }
            )
        return rows

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        accepted = [r for r in rows if r["status"] == "accepted"]
        review = [r for r in rows if r["status"] == "review"]
        wrong = [r for r in rows if not r["correct"]]
        silent = [r for r in wrong if r["status"] == "accepted"]
        return {
            "documents": len({r["file"] for r in rows}),
            "boxes_checked": len(rows),
            "correct": len(rows) - len(wrong),
            "accepted": len(accepted),
            "accepted_correct": sum(r["correct"] for r in accepted),
            "sent_to_review": len(review),
            "review_because_statement": sum(r["statement"] for r in review),
            "wrong": len(wrong),
            "wrong_caught_by_review": len(wrong) - len(silent),
            "silent_errors": len(silent),
            "silent_error_boxes": [f"{r['file']} box {r['key']}" for r in silent],
        }

    def statement_check(docs: list[dict[str, Any]]) -> dict[str, int] | None:
        """Each statement line a model read, against the line with that code on the issuer's own statement."""
        read = right = missed = 0
        for doc in docs:
            fields = [f for f in doc["fields"] if "statement_lines" in f]
            if not fields:
                continue
            with pdfplumber.open(SAMPLES / doc["file"]) as pdf:
                text = [ln for pg in pdf.pages for ln in (pg.extract_text() or "").splitlines()]
            for f in fields:
                box = f["key"].split(" ")[0]
                printed = {ln.split()[0]: ln.split()[-1] for ln in text if re.match(rf"^{box}[A-Z]{{1,2}}\d*\s", ln)}
                lines = {ln["code"].replace(" ", "").upper(): ln for ln in f["statement_lines"]}
                missed, read = missed + len(set(printed) - set(lines)), read + len(lines)
                right += sum(c in printed and parse_value(printed[c])[0] == ln["value"] for c, ln in lines.items())
        return {"lines_read": read, "right": right, "lines_missed": missed} if read or missed else None

    def score(run: dict[str, Any]) -> dict[str, Any]:
        docs = run["documents"]
        rows = [r for d in docs for r in score_document(d)]
        known = [d["cost_usd"] for d in docs if not d["cost_missing_responses"]]
        per_doc = {
            f"{k}_per_document": round(sum(d.get(k, 0) for d in docs) / len(docs), 1)
            for k in ("seconds", "model_seconds", "ocr_seconds")
        }
        sources = sorted({r["source"] for r in rows}, reverse=True)
        return {
            "all": summarize(rows),
            "held_out_set": summarize([r for r in rows if r["source"].startswith("held")]),
            "by_source": {s: summarize([r for r in rows if r["source"] == s]) for s in sources},
            "cost_usd_per_document": round(sum(known) / len(known), 5) if known else None,
            "cost_usd_total": round(sum(d["cost_usd"] for d in docs), 4),
            "cost_unknown_documents": [d["file"] for d in docs if d["cost_missing_responses"]],
            "failed_attempts": sum(d["failed_attempts"] for d in docs),
            "failed_documents": [f["file"] for f in run["failed_documents"]],
            "statement_lines": statement_check(docs),
            **per_doc,
        }

    return (score,)


@app.cell
def _(score):
    runs = [
        json.loads((OUT / name / "extracted.json").read_text()) for name in json.loads((OUT / "runs.json").read_text())
    ]
    _lines = [
        "| Pipeline | Values right | Accepted without review | Wrong but accepted | Sent to review (STMT) "
        "| Cost per document | Model time per document | Failed documents |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _run in runs:
        _run["metrics"] = _m = score(_run)
        (OUT / _run["name"] / "metrics.json").write_text(json.dumps(_m, indent=1))
        _a = _m["all"]
        _cost = "unknown" if _m["cost_usd_per_document"] is None else f"${_m['cost_usd_per_document']:.4f}"
        _gpu = f"{_m['ocr_seconds_per_document']} s GPU + " if _m["ocr_seconds_per_document"] else ""
        _lines.append(
            f"| {_run['label']} | {_a['correct']} of {_a['boxes_checked']} | {_a['accepted']} "
            f"| {_a['silent_errors']} | {_a['sent_to_review']} ({_a['review_because_statement']}) | {_cost} "
            f"| {_gpu}{_m['model_seconds_per_document']} s | {len(_m['failed_documents'])} |"
        )
    results_table = "\n".join(_lines)
    print(results_table)
    return results_table, runs


@app.cell
def _(results_table):
    mo.md(
        '## 2. Results\n\n"Wrong but accepted" counts wrong values that were accepted, and boxes on the key that a '
        "run never reported, since a missed row reads as a blank box. A run that failed some documents is scored on "
        "the rest, so it isn't comparable box for box. Model time leaves out Docling's layout pass, which adds its own "
        "seconds per document on CPU to every vision-model row.\n\n" + results_table
    )
    return


@app.cell
def _(runs):
    _out = [
        "# Pipelines compared",
        "",
        "Same documents and answer keys. A silent error is a wrong value accepted "
        "without review. Written by 3_results.py.",
        "",
    ]
    for _source in ["held_out_set", *runs[0]["metrics"]["by_source"]]:
        _out += [
            f"## {_source.replace('_', ' ')}",
            "",
            "| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |",
            "|---|---|---|---|---|",
        ]
        for _run in runs:
            if _s := _run["metrics"].get(_source) or _run["metrics"]["by_source"].get(_source):
                _out.append(
                    f"| {_run['label']} | {_s['boxes_checked']} | {_s['accepted']} ({_s['accepted_correct']}) "
                    f"| {_s['sent_to_review']} | {_s['silent_errors']} |"
                )
        _out.append("")
    for _run in runs:
        _m, _st = _run["metrics"], _run["metrics"]["statement_lines"]
        _stmt = (
            f"Statement lines: {_st['right']} of {_st['lines_read']} right, {_st['lines_missed']} missed. "
            if _st
            else ""
        )
        _out += [
            f"**{_run['label']}**: ${_m['cost_usd_total']:.2f} in all, {_m['failed_attempts']} failed attempts. "
            f"{_stmt}Failed documents: {', '.join(_m['failed_documents']) or 'none'}. "
            f"Unknown cost: {', '.join(_m['cost_unknown_documents']) or 'none'}. "
            f"Silent errors: {'; '.join(_m['all']['silent_error_boxes']) or 'none'}.",
            "",
        ]
    comparison = "\n".join(_out)
    (OUT / "comparison.md").write_text(comparison)
    _total = sum(r["metrics"]["cost_usd_total"] for r in runs if not r["name"].startswith("pair-"))
    print(f"Total cost of this run: ${_total:.2f}")  # a pair's cost is its two models' cost again
    mo.md(comparison)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. The review screen

    Each run gets a review screen, `output/<run>/index.html`. Clicking a value highlights its box on the page, and a
    STMT value opens the statement page. The queue shows each flagged box cropped from the page, with its reason, and
    lets a person correct or confirm it. Corrections stay in the browser and export to CSV. With `K1_SCREENSHOTS=1`
    (`./run.sh --screenshots`), Playwright saves `screenshots/` from Gemini 3.8 Flash's screen.
    """)
    return


@app.cell
def _(runs):
    _template = (HERE / "review_screen.html").read_text()
    for _run in runs:
        _docs = sorted(_run["documents"], key=lambda d: (d["file"][:2], "-scan" in d["file"], d["file"]))
        _data = json.dumps({"description": _run["description"], "documents": _docs})
        _html = _template.replace("__DATA__", _data).replace("__METRICS__", json.dumps(_run["metrics"]))
        (OUT / _run["name"] / "index.html").write_text(_html)
    review_screen = OUT / "gemini-3.8-flash-alone" / "index.html"
    return (review_screen,)


@app.cell
async def _(review_screen):
    # The async API, because marimo runs the notebook inside an event loop.
    if os.environ.get("K1_SCREENSHOTS") == "1":
        _shots, _errors = HERE / "screenshots", []
        _shots.mkdir(exist_ok=True)
        async with async_playwright() as _p:
            _browser = await _p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH"))
            _page = await _browser.new_page(viewport={"width": 1440, "height": 900})
            _page.on("pageerror", lambda e: _errors.append(str(e)))
            await _page.goto(review_screen.resolve().as_uri())
            await _page.evaluate("localStorage.clear()")
            await _page.reload()
            await _page.wait_for_timeout(1500)

            async def _step(selector: str, wait: int = 900, shot: str = "") -> None:
                await _page.click(selector)
                await _page.wait_for_timeout(wait)
                if shot:
                    await _page.screenshot(path=_shots / shot)

            _doc, _box = ".docs a:has(small:text-matches('^{}'))", "tr.v:has(td:text-is('{}'))"
            await _step(_doc.format("02-enviva-2021-k1.pdf"), 700)
            await _step(_box.format("1"), shot="1-value-linked-to-box.png")  # every value points at its box
            await _step(_box.format("20 *"), shot="2-statement-sent-to-review.png")  # a STMT amount goes to review
            await _step("#otherpage", 1200, "3-attached-statement.png")
            await _step(_doc.format("03-blackstone-2019-k1-scan1a.pdf"), 700)
            await _step(_box.format("16 B"), shot="4-scanned-copy.png")
            await _step("#t-queue", 1200)
            await _page.locator(".item", has=_page.locator(".stmt")).first.scroll_into_view_if_needed()
            await _page.wait_for_timeout(800)
            await _page.screenshot(path=_shots / "5-review-queue.png")
            await _page.check("#showkey")
            await _step("#t-values", 500)
            await _step(_doc.format("03-blackstone-2019-k1-scan2b.pdf"), 700)
            await _step(_box.format("6b"), shot="6-answer-key.png")  # every value against the hand-keyed answer key
            await _browser.close()
        if _errors:
            raise RuntimeError(f"the review screen raised errors: {_errors}")
        print(f"screenshots saved from {review_screen}")
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. What didn't work, and what this doesn't show

    **What didn't work.**

    - **Tesseract and rules.** The first versions of this demo read the forms with Tesseract OCR. They straightened
      a scan, lined it up with its blank IRS form, whited out the form's own printing, and OCR'd each box on its
      own. On the held-out set this accepted 182 of 321 boxes, with 2 silent errors, and sent 43% to review.
      Checking Qwen3-VL 235B box by box against Tesseract accepted 236, with no silent errors, and sent 28% to
      review, much of it because Tesseract couldn't read a box the model had read right. Gemini 3.8 Flash on its own
      beats both, so that code was removed. It is in the repository's history, in `extract.py` at commit `0fff276`.
    - **Docling's own OCR as a check on scans.** It picked up 26% of the values on the scanned K-1s.
    - **olmOCR 2** reads the characters well, but it lays a K-1's two columns of boxes out as one HTML table. Once
      the form is text, the box an amount belongs to is easy to lose. The text model put amounts one box off, filed
      coded rows under the wrong box (`20 V` as `13 V`), and missed rows. A vision model reading the image sees the
      grid.
    - **granite-docling can't read these forms.** On most pages Docling gets nothing usable back, and they go to
      review whole. Where it returns text, it often repeats one token until it runs out of output. A repetition
      penalty didn't help, and Docling's own Transformers pipeline on a Modal GPU gave the same result at 257 seconds
      a page.
    - **GLM 5.3 Flash** can fail every attempt on the made-up 1099s, with Pydantic AI's `Exceeded maximum output
      retries`: its answer never fits the schema. When it does answer, it often reads only part of the page. The
      three-quarter page check in `2_extraction.py` was added after it read 4 to 8 values on five summary pages
      and got past the quarter line. And when it's asked which form a scan is, it often names the wrong one,
      mostly "Form 1065" for a made-up 1120-S or 1041. It then reads the page with that form's boxes, and nothing in
      the review rules notices.
    - **Gemma 4 31B** shifts amounts into neighbouring boxes, misreads names and skips coded rows. It sometimes runs
      out of its 8,000 output tokens. Across runs, between a third and 43% of what it accepted was wrong.

    **What it doesn't show.**

    - **This is not our production extraction**, and a prospect who sends real documents will see different numbers.
    - **The scans are simulated.** Real scans have staples, handwriting, stamps, other scales and colour backgrounds.
    - **The sample is small**: three real K-1s, all Form 1065. There are no real 1120-S, 1041 or brokerage 1099s.
    - **Model answers vary from run to run** at temperature 0, and the open models' answers vary a lot (see the
      README).
    - **A model that skips one section of a 1099 can get through.** The page check catches an answer that skips the
      1099-B rows, or DIV and INT together. It doesn't catch one that skips only DIV (12 values left) or only INT
      (14), and it can't catch values put in the wrong box.
    - **A failed document isn't in the review queue.** In production it would go to a person whole.
    """)
    return


if __name__ == "__main__":
    app.run()
