import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    from pathlib import Path

    import marimo as mo
    import pandas as pd
    from statsmodels.stats.proportion import proportion_confint

    HERE = Path(__file__).parent
    CHECKERS = ["claude_passage", "gpt_passage", "claude_dreaming"]


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 3. What each checker caught and missed

    A checker **flags** a claim when it answers "not supported". On a logged error, a flag is a catch; recall is
    the share of errors flagged. On a claim that passed review, a flag is a false alarm. We don't require the
    checker to name the same error type as our log: catching the claim is what a reviewer needs.

    Counts are small (a few to a few dozen per type), so every rate comes with a 95% Wilson interval.
    """)
    return


@app.cell
def _():
    items = pd.DataFrame(
        [json.loads(line) for line in (HERE / "data/test_set.jsonl").read_text().splitlines() if line]
    ).set_index("id")
    answers = {}
    for _checker in CHECKERS:
        for _item_id in items.index:
            _path = HERE / "answers" / _checker / f"{_item_id}.json"
            answers[(_checker, _item_id)] = json.loads(_path.read_text()) if _path.exists() else None

    def flagged(checker: str, item_id: str) -> bool | None:
        """True if the checker said 'not supported'; None if it never gave an answer for this claim."""
        answer = answers[(checker, item_id)]
        if not answer or not answer["verdict"]:
            return None
        return not answer["verdict"]["supported"]

    flags = pd.DataFrame({c: [flagged(c, i) for i in items.index] for c in CHECKERS}, index=items.index)
    print("Claims without an answer (dreaming skips a source we couldn't fetch as the passage's page):")
    print(flags.isna().sum().to_markdown())
    return answers, flags, items


@app.cell
def _():
    def rate(hits: int, n: int) -> str:
        if n == 0:
            return "–"
        low, high = proportion_confint(hits, n, method="wilson")
        return f"{hits}/{n} = {hits / n:.0%} ({low:.0%}–{high:.0%})"

    return (rate,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Recall by error type, and false alarms

    Each cell is caught / errors of that type, with its interval. The dreaming column counts only claims whose full
    source we could fetch, so its denominators can be smaller.
    """)
    return


@app.cell
def _(flags, items, rate):
    order = items.loc[items["kind"] == "error", "error_type"].value_counts().index.tolist()

    def table(passes: pd.Index) -> pd.DataFrame:
        rows = {}
        for error_type in [*order, "all errors"]:
            ids = items.index[
                (items["kind"] == "error") & ((items["error_type"] == error_type) | (error_type == "all errors"))
            ]
            rows[error_type] = {
                c: rate(int(flags.loc[ids, c].sum()), int(flags.loc[ids, c].notna().sum())) for c in CHECKERS
            }
        rows["false alarms (passing claims)"] = {
            c: rate(int(flags.loc[passes, c].sum()), int(flags.loc[passes, c].notna().sum())) for c in CHECKERS
        }
        return pd.DataFrame(rows).T

    all_passes = items.index[items["kind"] == "pass"]
    clean_passes = items.index[(items["kind"] == "pass") & ~items["doubt"]]
    recall = table(all_passes)
    print(recall.to_markdown())
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results/recall.md").write_text(recall.to_markdown() + "\n")
    print("\nFalse alarms leaving out the passing claims our subagent doubted:")
    print(table(clean_passes).tail(1).to_markdown())
    return (recall,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Does how we recovered the wording matter?

    Quoted claims keep the note's own words; reconstructed ones were rewritten from the correction by an agent that
    knew what was wrong. If reconstructed claims are caught much more often, the rewrite made errors easier to see.
    """)
    return


@app.cell
def _(flags, items, rate):
    by_wording = {}
    for _wording in ["quoted", "reconstructed"]:
        _ids = items.index[(items["kind"] == "error") & (items["wording"] == _wording)]
        by_wording[_wording] = {
            c: rate(int(flags.loc[_ids, c].sum()), int(flags.loc[_ids, c].notna().sum())) for c in CHECKERS
        }
    print(pd.DataFrame(by_wording).T.to_markdown())
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Which errors only one provider caught

    Same claims, same passage, same prompt: the only difference between the first two checkers is the model.
    """)
    return


@app.cell
def _(flags, items):
    errs = flags[items["kind"] == "error"]
    only_gpt = errs.index[(errs["gpt_passage"] == True) & (errs["claude_passage"] == False)]  # noqa: E712
    only_claude = errs.index[(errs["claude_passage"] == True) & (errs["gpt_passage"] == False)]  # noqa: E712
    neither = errs.index[(errs["claude_passage"] == False) & (errs["gpt_passage"] == False)]  # noqa: E712
    missed_by_all = errs.index[(errs == False).sum(axis=1) == errs.notna().sum(axis=1)]  # noqa: E712
    print(f"Caught only by GPT: {len(only_gpt)}; only by Claude: {len(only_claude)}; by neither: {len(neither)}")
    print(f"Missed by every checker that answered: {len(missed_by_all)}")
    print("\nBy type, missed by both passage checkers:")
    print(items.loc[neither, "error_type"].value_counts().to_markdown())
    return missed_by_all, only_claude, only_gpt


@app.cell
def _(answers, items, only_claude, only_gpt):
    def show(ids: pd.Index, checker: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "type": items.loc[ids, "error_type"],
                "claim": items.loc[ids, "claim"],
                f"{checker} said": [answers[(checker, i)]["verdict"]["reason"] for i in ids],
            }
        )

    mo.vstack(
        [
            mo.md("**Caught only by GPT**"),
            show(only_gpt, "gpt_passage"),
            mo.md("**Caught only by Claude**"),
            show(only_claude, "claude_passage"),
        ]
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The errors no checker caught

    These are the claims a human still has to read for. Each row shows what the Claude passage checker said.
    """)
    return


@app.cell
def _(answers, items, missed_by_all):
    missed = pd.DataFrame(
        {
            "type": items.loc[missed_by_all, "error_type"],
            "wording": items.loc[missed_by_all, "wording"],
            "claim": items.loc[missed_by_all, "claim"],
            "claude said": [answers[("claude_passage", i)]["verdict"]["reason"] for i in missed_by_all],
        }
    ).sort_values("type")
    (HERE / "results/missed_by_every_checker.md").write_text(missed.to_markdown() + "\n")
    mo.ui.table(missed)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Cost and time per claim
    """)
    return


@app.cell
def _(answers, items):
    cost = {}
    for _checker in CHECKERS:
        _done = [a for i in items.index if (a := answers[(_checker, i)]) and a["verdict"]]
        cost[_checker] = {
            "claims answered": len(_done),
            "total $": round(sum(a["usd"] for a in _done), 3),
            "$ per claim": round(sum(a["usd"] for a in _done) / max(len(_done), 1), 5),
            "seconds per claim": round(sum(a["seconds"] for a in _done) / max(len(_done), 1), 1),
        }
    print(pd.DataFrame(cost).T.to_markdown())
    return


@app.cell(hide_code=True)
def _(recall):
    mo.md(f"""
    ## Headline

    Overall recall: Claude on the passage **{recall.loc["all errors", "claude_passage"]}**, GPT on the passage
    **{recall.loc["all errors", "gpt_passage"]}**, Claude rereading the full source
    **{recall.loc["all errors", "claude_dreaming"]}**. False alarms on claims that passed review:
    {recall.loc["false alarms (passing claims)", "claude_passage"]},
    {recall.loc["false alarms (passing claims)", "gpt_passage"]} and
    {recall.loc["false alarms (passing claims)", "claude_dreaming"]}. The README reads these against the card's
    argument.
    """)
    return


if __name__ == "__main__":
    app.run()
