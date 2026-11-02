import marimo

__generated_with = "0.17.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import re
    from pathlib import Path

    import marimo as mo
    import pandas as pd

    return Path, json, mo, pd, re


@app.cell
def _(mo):
    mo.md(r"""
    # Part 3: what the agent got wrong

    This notebook scores the saved runs in `runs/` against `answer_key.json`, lists every wrong
    answer with the transcript lines that show the mistake, and counts accuracy, errors by type,
    cost and time. It needs no network and no API key, so anyone can rescore from a clean checkout.
    """)
    return


@app.cell
def _(Path, json):
    HERE = Path(__file__).parent
    KEY = json.loads((HERE / "answer_key.json").read_text())["questions"]
    RUNS = [json.loads(f.read_text()) | {"file": f"{f.parent.name}/{f.name}"} for f in sorted((HERE / "runs").glob("*/Q*_*.json"))]
    LABELS = json.loads((HERE / "error_labels.json").read_text())
    OUT = HERE / "results"
    OUT.mkdir(exist_ok=True)
    print(f"{len(RUNS)} saved runs")
    return KEY, LABELS, OUT, RUNS


@app.cell
def _(mo):
    mo.md(r"""
    ## Scoring rules

    Each run is **right**, **wrong** or **refused/unsure**.

    - A run that errored, hit a limit, or answered `unsure` is *refused/unsure*. So is
      `unavailable`, except on Q9.
    - Q9 asks about substations, which HIFLD Next doesn't have. `unavailable` is right; any count
      is wrong.
    - Counts must be one the key accepts. Names must match an accepted set exactly, after
      upper-casing and dropping punctuation; a list with one name missing or extra is wrong. A
      length must be within 3%, a percentage within 0.5 points, a bed total exact.
    """)
    return


@app.cell
def _(KEY, re):
    def norm(name: str) -> str:
        return re.sub(r"[^A-Z0-9 ]", "", name.upper()).strip()

    def score(run: dict) -> str:
        q, out = KEY[run["question_id"]], run["output"]
        if out is None or out["status"] == "unsure":
            return "refused/unsure"
        if q["kind"] == "unavailable":
            return "right" if out["status"] == "unavailable" else "wrong"
        if out["status"] == "unavailable":
            return "refused/unsure"
        if q["kind"] == "names":
            got = {norm(n) for n in out["names"]}
            return "right" if any(got == {norm(n) for n in s} for s in q["accepted_sets"]) else "wrong"
        number = out["count"] if out["count"] is not None else out["value"]
        if number is None:
            return "wrong"
        if q["kind"] == "count" or q.get("unit") == "beds":
            return "right" if any(abs(number - a) < 0.5 for a in q["accepted"]) else "wrong"
        if "tolerance_pct" in q:
            return "right" if any(abs(number - a) <= a * q["tolerance_pct"] / 100 for a in q["accepted"]) else "wrong"
        return "right" if any(abs(number - a) <= q["tolerance"] for a in q["accepted"]) else "wrong"

    def answer_text(run: dict) -> str:
        out = run["output"]
        if out is None:
            return f"error: {run['error'][:120]}"
        if out["names"]:
            return "; ".join(out["names"])
        number = out["count"] if out["count"] is not None else out["value"]
        return f"{out['status']}: {number if number is not None else ''} {out.get('unit') or ''}".strip()

    def failed_calls(run: dict) -> int:
        """Tool calls whose result was an error: QGIS's 'failed', or an MCP error the model was asked to retry."""
        parts = [p for m in run["messages"] for p in m.get("parts", [])]
        failed = [p for p in parts if p.get("part_kind") == "tool-return" and str(p.get("content", "")).startswith(("failed", "error"))]
        retried = [p for p in parts if p.get("part_kind") == "retry-prompt" and p.get("tool_name")]
        return len(failed) + len(retried)

    return answer_text, failed_calls, score


@app.cell
def _(KEY, RUNS, answer_text, failed_calls, pd, score):
    scored = pd.DataFrame(
        [
            {
                "model": r["file"].split("/")[0],
                "question": r["question_id"],
                "repeat": r["repeat"],
                "verdict": score(r),
                "answer": answer_text(r),
                "seconds": r["seconds"],
                "cost_usd": r["cost_usd"],
                "tool_calls": len(r["tool_log"]),
                "failed_tool_calls": failed_calls(r),
                "file": r["file"],
            }
            for r in RUNS
        ]
    )
    scored["level"] = scored.question.map(lambda q: KEY[q]["level"])
    scored
    return (scored,)


@app.cell
def _(mo, pd, scored):
    by_question = (
        scored.pivot_table(index=["question", "level"], columns=["model", "verdict"], values="repeat", aggfunc="count", fill_value=0)
        .astype(int)
        .sort_index(key=lambda s: s.str.extract(r"(\d+)", expand=False).astype(float) if s.name == "question" else s)
    )
    overall = scored.groupby(["model", "verdict"]).size().unstack(fill_value=0)
    mo.vstack([mo.md("## Accuracy\n\nRuns per verdict, by model."), overall, mo.md("By question:"), by_question])
    return by_question, overall


@app.cell
def _(mo):
    mo.md(r"""
    ## The error log

    Every wrong or refused run, with the type of mistake and the lines from its transcript that
    show it. We assigned the types by reading each transcript; they're in `error_labels.json`. The
    notebook checks that every wrong run has a label and that every quoted line really is in that
    run's transcript.

    Types: **wrong layer or dataset**, **wrong join or filter**, **CRS or projection**, **units**,
    **invented attribute or value**, **stale data**, **tool failure**, and **gave up** for runs
    that stopped without a wrong answer.
    """)
    return


@app.cell
def _(LABELS, RUNS, json, pd, scored):
    _text = {r["file"]: json.dumps(r["messages"]) + json.dumps(r["tool_log"]) for r in RUNS}
    _needs_label = set(scored[scored.verdict != "right"].file)
    _missing = sorted(_needs_label - set(LABELS))
    assert not _missing, f"wrong or refused runs with no label: {_missing}"
    _stale = sorted(set(LABELS) - _needs_label)
    assert not _stale, f"labels for runs that are right or don't exist: {_stale}"
    for _file, _label in LABELS.items():
        for _quote in _label["quotes"]:
            assert json.dumps(_quote)[1:-1] in _text[_file], f"{_file}: quote not in transcript: {_quote[:80]}"
    error_log = pd.DataFrame(
        [{"file": f, "type": lab["type"], "what happened": lab["note"], "evidence": " / ".join(lab["quotes"])} for f, lab in LABELS.items()]
    ).merge(scored[["file", "model", "question", "verdict", "answer"]], on="file")
    error_log = error_log[["model", "question", "file", "verdict", "type", "answer", "what happened", "evidence"]].sort_values(["question", "model", "file"])
    error_log
    return (error_log,)


@app.cell
def _(error_log, mo):
    by_type = error_log.groupby(["type", "model"]).size().unstack(fill_value=0)
    by_type["total"] = by_type.sum(axis=1)
    by_type = by_type.sort_values("total", ascending=False)
    examples = error_log.drop_duplicates("type")[["type", "file", "what happened", "evidence"]]
    mo.vstack([mo.md("## Errors by type"), by_type, mo.md("One example of each:"), examples])
    return by_type, examples


@app.cell
def _(mo, scored):
    cost_time = scored.groupby(["model", "question"]).agg(
        runs=("repeat", "count"),
        usd_per_run=("cost_usd", "mean"),
        seconds_per_run=("seconds", "mean"),
        tool_calls_per_run=("tool_calls", "mean"),
        failed_tool_calls_per_run=("failed_tool_calls", "mean"),
    ).round(3)
    totals = scored.groupby("model").agg(
        runs=("repeat", "count"), total_usd=("cost_usd", "sum"), total_seconds=("seconds", "sum"), median_seconds=("seconds", "median")
    ).round(2)
    mo.vstack([mo.md("## Cost and time"), totals, cost_time])
    return cost_time, totals


@app.cell
def _(OUT, by_question, by_type, cost_time, error_log, json, overall, scored, totals):
    scored.to_csv(OUT / "scored_runs.csv", index=False)
    error_log.to_csv(OUT / "error_log.csv", index=False)
    summary = {
        "runs": int(len(scored)),
        "overall": overall.to_dict(orient="index"),
        "by_question": {"|".join(map(str, k)): v for k, v in by_question.to_dict(orient="index").items()},
        "errors_by_type": by_type.to_dict(orient="index"),
        "totals": totals.to_dict(orient="index"),
        "cost_time_by_question": {"|".join(k): v for k, v in cost_time.to_dict(orient="index").items()},
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary["overall"], indent=1), json.dumps(summary["totals"], indent=1))
    return


if __name__ == "__main__":
    app.run()
