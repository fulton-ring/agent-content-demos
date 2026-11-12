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

    There are two batches of errors. **2026-10-08** is the 75 errors from the Analyze job's re-check, with 75
    passing claims. **Later** is the 170 errors review jobs caught from 2026-10-08 to 2026-10-22 (issue #235),
    many after an earlier Claude check had passed the card, so they are the harder test. We report them side by
    side rather than pooled.
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
    def table(batch: pd.Series, passes: pd.Index) -> pd.DataFrame:
        errors = items.index[(items["kind"] == "error") & batch]
        rows = {}
        for error_type in [*items.loc[errors, "error_type"].value_counts().index, "all errors"]:
            ids = errors[(items.loc[errors, "error_type"] == error_type) | (error_type == "all errors")]
            rows[error_type] = {
                c: rate(int(flags.loc[ids, c].sum()), int(flags.loc[ids, c].notna().sum())) for c in CHECKERS
            }
        rows["false alarms (passing claims)"] = {
            c: rate(int(flags.loc[passes, c].sum()), int(flags.loc[passes, c].notna().sum())) for c in CHECKERS
        }
        return pd.DataFrame(rows).T

    first, later = items["batch"] == "2026-10-08", items["batch"] == "later"
    all_passes = items.index[items["kind"] == "pass"]
    clean_passes = items.index[(items["kind"] == "pass") & ~items["doubt"]]
    recall = table(first, all_passes[first[all_passes]])
    recall_later = table(later, all_passes[later[all_passes]])
    (HERE / "results").mkdir(exist_ok=True)
    print("**2026-10-08 batch**\n" + recall.to_markdown())
    (HERE / "results/recall.md").write_text(recall.to_markdown() + "\n")
    print("\n**Later batch (#235)**\n" + recall_later.to_markdown())
    (HERE / "results/recall_later.md").write_text(recall_later.to_markdown() + "\n")
    print("\nFalse alarms on all passing claims, leaving out the ones our subagent doubted:")
    print(table(first | later, clean_passes).tail(1).to_markdown())
    return recall, recall_later


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    The dreaming checker answered fewer claims, so here are all three on only the claims it answered: the same
    claims, scored the same way. And when a checker catches an error, does it name the type our log gave it?
    """)
    return


@app.cell
def _(answers, flags, items, rate):
    both = flags.dropna().index
    same_claims = {}
    for _kind, _label in [("error", "recall"), ("pass", "false alarms")]:
        _ids = both[items.loc[both, "kind"] == _kind]
        same_claims[_label] = {c: rate(int(flags.loc[_ids, c].sum()), len(_ids)) for c in CHECKERS}
    print(pd.DataFrame(same_claims).T.to_markdown(), "\n")
    type_match = {}
    for _checker in CHECKERS:
        _caught = [i for i in items.index[items["kind"] == "error"] if flags.loc[i, _checker] == True]  # noqa: E712
        _same = sum(answers[(_checker, i)]["verdict"]["problem"] == items.loc[i, "error_type"] for i in _caught)
        type_match[_checker] = rate(_same, len(_caught))
    print("Catches that named the logged type:\n" + pd.Series(type_match).to_markdown())
    return


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
    for _batch, _wording in [(b, w) for b in ["2026-10-08", "later"] for w in ["quoted", "reconstructed"]]:
        _ids = items.index[(items["kind"] == "error") & (items["wording"] == _wording) & (items["batch"] == _batch)]
        by_wording[f"{_batch}, {_wording}"] = {
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
    for _batch in ["2026-10-08", "later"]:
        _in = items.loc[errs.index, "batch"] == _batch
        _count = {name: int(_in[ids].sum()) for name, ids in [("GPT", only_gpt), ("Claude", only_claude)]}
        print(
            f"{_batch}: caught only by GPT {_count['GPT']}; only by Claude {_count['Claude']}; "
            f"by neither {int(_in[neither].sum())}"
        )
    print("\nBy type and batch, missed by both passage checkers:")
    print(pd.crosstab(items.loc[neither, "error_type"], items.loc[neither, "batch"]).to_markdown())
    return only_claude, only_gpt


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
    ## The errors a checker let through

    Every logged error at least one checker called supported, with what the Claude passage checker said.
    """)
    return


@app.cell
def _(answers, flags, items):
    errors = flags[items["kind"] == "error"]
    let_through = errors.index[(errors == False).any(axis=1)]  # noqa: E712
    missed = pd.DataFrame(
        {
            "batch": items.loc[let_through, "batch"],
            "type": items.loc[let_through, "error_type"],
            "missed by": [", ".join(c for c in CHECKERS if errors.loc[i, c] == False) for i in let_through],  # noqa: E712
            "claim": items.loc[let_through, "claim"],
            "claude_passage said": [answers[("claude_passage", i)]["verdict"]["reason"] for i in let_through],
        }
    )
    print(missed[["batch", "type", "missed by"]].to_markdown())
    (HERE / "results/let_through.md").write_text(missed.to_markdown() + "\n")
    mo.ui.table(missed)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Are the false alarms false?

    A passing claim is one our reviewer accepted, not one known to be right. So we read every passing claim the
    dreaming checker flagged (it saw the whole source, so its flags aren't caused by a short passage) and judged
    each one: **real** (a careful editor would change the claim), **nit** (true in substance; the flag is about
    emphasis, or about a detail like a date that's on the page but not in the text we extracted) or **checker
    wrong**. One reader made these calls; they're in `data/false_alarm_review.jsonl` with a reason each. The
    review covers the 2026-10-08 batch's passing claims.
    """)
    return


@app.cell
def _(flags, items, rate):
    review = pd.read_json(HERE / "data/false_alarm_review.jsonl", lines=True).set_index("id")
    first_passes = (items["kind"] == "pass") & (items["batch"] == "2026-10-08")
    flagged_passes = items.index[first_passes & (flags["claude_dreaming"] == True)]  # noqa: E712
    assert set(review.index) == set(flagged_passes), "every flagged passing claim needs a judgement"
    answered_passes = int(flags.loc[first_passes, "claude_dreaming"].notna().sum())
    counts = review["judgement"].value_counts()
    print(counts.to_markdown(), "\n")
    print(f"Passing claims with a real problem review missed: {rate(int(counts['real']), answered_passes)}")
    wrong = int(counts.drop("real").sum())
    print(f"Passing claims the dreaming checker flagged without a real problem: {rate(wrong, answered_passes)}")
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
def _():
    mo.md(r"""
    ## The later errors by who caught them

    The Research manager reviewed cards a worker had already checked; the Draft job caught errors after the manager
    had passed the card. If the errors that got furthest are the hardest to see, recall should fall from left to right.
    """)
    return


@app.cell
def _(flags, items, rate):
    by_catcher = {}
    for _catcher in ["research_worker", "research_manager", "draft_job"]:
        _ids = items.index[(items["batch"] == "later") & (items["caught_by"] == _catcher)]
        by_catcher[_catcher] = {
            c: rate(int(flags.loc[_ids, c].sum()), int(flags.loc[_ids, c].notna().sum())) for c in CHECKERS
        }
    print(pd.DataFrame(by_catcher).T.to_markdown())
    return


@app.cell(hide_code=True)
def _(recall, recall_later):
    mo.md(f"""
    ## Headline

    Overall recall: Claude on the passage **{recall.loc["all errors", "claude_passage"]}**, GPT on the passage
    **{recall.loc["all errors", "gpt_passage"]}**, Claude rereading the full source
    **{recall.loc["all errors", "claude_dreaming"]}**. False alarms on claims that passed review:
    {recall.loc["false alarms (passing claims)", "claude_passage"]},
    {recall.loc["false alarms (passing claims)", "gpt_passage"]} and
    {recall.loc["false alarms (passing claims)", "claude_dreaming"]}.

    On the later errors (#235): **{recall_later.loc["all errors", "claude_passage"]}**,
    **{recall_later.loc["all errors", "gpt_passage"]}** and **{recall_later.loc["all errors", "claude_dreaming"]}**.
    The README reads these against the card's argument.
    """)
    return


if __name__ == "__main__":
    app.run()
