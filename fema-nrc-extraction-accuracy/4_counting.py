import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import json
    import re
    from collections.abc import Callable

    import marimo as mo
    import pandas as pd
    from pydantic import BaseModel, Field
    from rank_bm25 import BM25Okapi

    from common import ANSWERS, HERE, MODELS, ask, fis_pdf, norm, tesseract, text_layer


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 4. Counting questions: retrieval against an extracted table

    AI21 Labs found common retrieval pipelines answered 5% and 11% of counting and ranking questions right on a
    22-document corpus, and fixed it by extracting the facts to a table first. Does that hold on flood studies?

    **Check first.** The card asked us to check the founders' draft "Beating the financebench RAG dataset". We found
    it in Notion: it is a list of notes on parsers, chunking and BM25-first retrieval, with no counting test, so it
    doesn't make this argument. We cite it for the BM25 baseline and keep this part small.

    **The document set** is the eight keyed Summary of Discharges pages from notebook 2: 87 locations in eight
    studies. Questions are about these pages only, so the answer key covers them fully.
    """)
    return


@app.cell
def _():
    KEY = {k: v for k, v in json.loads((HERE / "fis_key.json").read_text()).items() if not k.startswith("_")}
    COLUMNS = ["source", "location", "area", "q10", "q2", "q1", "q02"]

    def as_table(rows_by_study: dict[str, list[list[str]]]) -> pd.DataFrame:
        """Rows as a typed table: numbers as floats, blanks as missing."""
        frame = pd.DataFrame(
            [[study, *row] for study, rows in rows_by_study.items() for row in rows], columns=["study", *COLUMNS]
        )
        for column in ["area", "q10", "q2", "q1", "q02"]:
            frame[column] = pd.to_numeric(frame[column].map(lambda v: norm(v)[1:] if norm(v).startswith("#") else None))
        return frame

    truth_table = as_table({study: v["rows"] for study, v in KEY.items()})
    print(f"{len(truth_table)} locations on {truth_table.source.nunique()} named sources")
    return KEY, as_table, truth_table


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Ten questions, written before any answers came back

    Each is a counting, totalling or ranking question, with the query that answers it from a table. The same query
    run on the hand-keyed table gives the right answer, and run on the extracted table gives the table's answer.
    """)
    return


@app.cell
def _():
    QUESTIONS: list[tuple[str, Callable[[pd.DataFrame], str]]] = [
        ("How many locations are listed in all the tables together?", lambda t: str(len(t))),
        (
            "How many locations have a 1-percent annual chance (100-year) peak discharge of 10,000 cfs or more?",
            lambda t: str(int((t.q1 >= 10000).sum())),
        ),
        (
            "How many locations have a drainage area under 1 square mile?",
            lambda t: str(int((t.area < 1).sum())),
        ),
        (
            "How many locations have no 10-percent annual chance (10-year) discharge given?",
            lambda t: str(int(t.q10.isna().sum())),
        ),
        (
            "What is the sum of the 1-percent annual chance discharges at all Jackson River locations, in cfs?",
            lambda t: f"{t[t.source.str.lower().str.contains('jackson')].q1.sum():.0f}",
        ),
        (
            "What is the largest 0.2-percent annual chance (500-year) peak discharge in any table, in cfs?",
            lambda t: f"{t.q02.max():.0f}",
        ),
        (
            "How many Blue River locations have a drainage area over 350 square miles?",
            lambda t: str(int(((t.source.str.lower() == "blue river") & (t.area > 350)).sum())),
        ),
        (
            "How many locations are described as 'Above Levee'?",
            lambda t: str(int(t.location.str.lower().str.contains("above levee").sum())),
        ),
        (
            "What is the smallest 1-percent annual chance discharge in any table, in cfs?",
            lambda t: f"{t.q1.min():.0f}",
        ),
        (
            "How many locations have a 1-percent annual chance discharge between 1,000 and 2,000 cfs, inclusive?",
            lambda t: str(int(t.q1.between(1000, 2000).sum())),
        ),
    ]
    return (QUESTIONS,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Three ways to answer

    1. **Retrieval.** Each page's text (its text layer, or Tesseract's text for a scan, as a search index would hold
       it) is cut into chunks of about 600 characters. BM25 picks the 8 chunks that best match the question, and
       the model answers from them. BM25 is the "boring recipe" the founders' notes say to try first.
    2. **Whole text.** The model gets all eight pages' text at once. On eight pages this fits; on a real archive it
       wouldn't, so it is the ceiling for answering from text.
    3. **Extracted table.** Notebook 2's Gemini 3.8 Flash page-image reading of each page, loaded into a table and
       answered by the query above. No model is asked the question.
    """)
    return


@app.cell
def _(KEY):
    _texts = {}
    for _study, _v in KEY.items():
        _pdf = fis_pdf(_study)
        _layer = text_layer(_pdf, _v["page"])
        _texts[_study] = _layer if len(_layer.strip()) >= 50 else tesseract(_pdf, _v["page"])[0]
    CHUNKS = []
    for _study, _text in _texts.items():
        _lines, _buf = _text.splitlines(), ""
        for _line in _lines:
            if len(_buf) + len(_line) > 600:
                CHUNKS.append(f"[study {_study}]\n{_buf}")
                _buf = ""
            _buf += _line + "\n"
        CHUNKS.append(f"[study {_study}]\n{_buf}")
    INDEX = BM25Okapi([re.findall(r"\w+", c.lower()) for c in CHUNKS])
    WHOLE = "\n\n".join(f"[study {s}, page {KEY[s]['page']}]\n{t}" for s, t in _texts.items())
    print(f"{len(CHUNKS)} chunks")
    return CHUNKS, INDEX, WHOLE


@app.cell
async def _(CHUNKS, INDEX, QUESTIONS, WHOLE):
    class Answer(BaseModel):
        answer: str = Field(description="The answer alone: a number, without units or commas.")

    _instructions = (
        "You answer questions about FEMA Flood Insurance Study 'Summary of Discharges' tables from the text given. "
        "Discharges are peak discharges in cfs. Count and add carefully."
    )
    _model = MODELS["Gemini 3.8 Flash"]
    _slots = asyncio.Semaphore(8)

    def _retrieved(question: str) -> str:
        scores = INDEX.get_scores(re.findall(r"\w+", question.lower()))
        best = sorted(range(len(CHUNKS)), key=lambda i: -scores[i])[:8]
        return "\n\n".join(CHUNKS[i] for i in sorted(best))

    async def _answer(arm: str, n: int, question: str, context: str) -> dict:
        saved = ANSWERS / "counting" / arm / f"q{n + 1}.json"
        return await ask(_model, Answer, _instructions, [f"{context}\n\nQuestion: {question}"], saved, _slots)

    _calls = []
    for _n, (_q, _) in enumerate(QUESTIONS):
        _calls.append(_answer("retrieval", _n, _q, _retrieved(_q)))
        _calls.append(_answer("whole-text", _n, _q, WHOLE))
    _got = await asyncio.gather(*_calls)
    model_answers = {
        "Retrieval (BM25, 8 chunks)": [(a["output"] or {}).get("answer", "") for a in _got[0::2]],
        "Whole text": [(a["output"] or {}).get("answer", "") for a in _got[1::2]],
    }
    cost = sum(a["usd"] for a in _got)
    print(f"${cost:.3f}")
    return (model_answers,)


@app.cell
def _(KEY, QUESTIONS, as_table, model_answers, truth_table):
    def _page_rows(study: str) -> list[list[str]]:
        saved = ANSWERS / "fis" / "gemini-3.8-flash" / "Image-page" / f"{study}.json"
        rows = (json.loads(saved.read_text())["output"] or {}).get("rows", [])
        fields = ["flooding_source", "location", "drainage_area", "q10", "q2", "q1", "q02"]
        return [[r.get(f, "") for f in fields] for r in rows]

    extracted = as_table({study: _page_rows(study) for study in KEY})
    _rows = []
    for _n, (_q, _query) in enumerate(QUESTIONS):
        _truth = _query(truth_table)
        _row = {"question": _q, "right answer": _truth}
        for _arm, _answers in model_answers.items():
            _row[_arm] = _answers[_n]
        _row["Extracted table"] = _query(extracted)
        _rows.append(_row)
    results = pd.DataFrame(_rows)
    arms = ["Retrieval (BM25, 8 chunks)", "Whole text", "Extracted table"]
    right = {
        arm: int(sum(norm(a) == norm(t) for a, t in zip(results[arm], results["right answer"], strict=True)))
        for arm in arms
    }
    print(results.to_string(index=False))
    print(right)
    return arms, results, right


@app.cell
def _(arms, results, right):
    _out = HERE / "results"
    _out.mkdir(exist_ok=True)
    (_out / "4_counting.md").write_text(
        "# Counting questions\n\n"
        + results.to_markdown(index=False)
        + "\n\nRight out of 10: "
        + ", ".join(f"{a} {right[a]}" for a in arms)
        + "\n"
    )
    mo.md(", ".join(f"**{a}**: {right[a]} of 10 right" for a in arms))
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this doesn't show

    - Ten questions over eight pages. On so small a set the whole text fits in one prompt; the retrieval arm is
      what a system over a large archive would do.
    - The table arm's queries were written by us. A system that has a model write the query adds its own errors.
    - One model answers. Notebook 2 shows the extracted table's own errors; they carry into the table's answers.
    """)
    return


if __name__ == "__main__":
    app.run()
