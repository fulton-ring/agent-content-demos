import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import random
    from pathlib import Path

    import marimo as mo
    import pandas as pd

    HERE = Path(__file__).parent
    DATA = HERE / "data"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 1. The test set: errors our research agent made, plus claims that passed

    **The question.** Our research pipeline writes notes on Notion cards, and review jobs re-read the sources and
    log what the notes got wrong. Issue #108 counted 290 such errors in 8 types. If we replay those errors against
    a second AI pass that re-reads the source, how many does it catch, and which kinds slip through?

    **The material.** The 88 errors from the 2026-10-08 re-check, listed one per row on
    [#108](https://github.com/fulton-ring/agent-content-demos/issues/108#issuecomment-6354565999). The 202 later
    errors on #108 were never published item by item, so they aren't here (see the README).

    For each of the 88, a research subagent read the card and its Corrections section, rebuilt the claim the note
    made, found the source it was checked against, fetched that source and copied the passage the claim is about.
    Notion keeps no page history from before 2026-10-08, so the note's original text is gone. Each claim is either
    **quoted** (the correction quotes the old words) or **reconstructed** from what the correction says was wrong.

    `data/logged_errors.jsonl` holds all 88 attempts, including the ones that couldn't be replayed and why.
    """)
    return


@app.cell
def _():
    def load(name: str) -> pd.DataFrame:
        return pd.DataFrame([json.loads(line) for line in (DATA / name).read_text().splitlines() if line.strip()])

    errors = load("logged_errors.jsonl")
    candidates = load("passing_candidates.jsonl")
    assert len(errors) == 88 and errors["id"].is_unique, "expected one row per #108 error"
    assert candidates["id"].is_unique
    return candidates, errors


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## How many logged errors can be replayed

    Replayable means we have a claim, the source is still online and readable, and there is a passage to check
    against.
    """)
    return


@app.cell
def _(errors):
    replay_by_type = (
        errors.groupby("error_type")["replayable"].agg(logged="size", replayable="sum").sort_values("logged")[::-1]
    )
    replay_by_type.loc["all"] = replay_by_type.sum()
    reasons = errors.loc[~errors["replayable"]].set_index("id")[["error_type", "not_replayable_reason"]]
    wording = errors.loc[errors["replayable"], "wording"].value_counts()
    print(replay_by_type.to_markdown(), "\n")
    print("Why the others can't be replayed:\n" + reasons.to_markdown(), "\n")
    print("How the replayable claims' wording was recovered:\n" + wording.to_markdown(), "\n")
    disputed = errors[errors["replayable"] & errors["disputed"]]
    for _, row in disputed.iterrows():
        print(f"Left out because the correction itself looks wrong: {row['id']}: {row['notes']}")
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Claims that passed review

    A failure log has no passes, and a checker that flags everything would score perfect recall on it. So we add an
    equal number of claims that passed. `random.Random(227)` drew 36 of the 72 cards our reviewer accepted
    (Draft requested, Drafted or Published, leaving out this card's parent and two promotion cards); a subagent
    took the first six claims in each card's Evidence sections that cite one outside public source, with the
    passage they draw on.
    That gives `data/passing_candidates.jsonl`. Below we draw as many as there are replayable errors, with the
    same seed.

    Passing review doesn't make a claim right. Where the subagent thought the source doesn't support a passing
    claim, it set `doubt`, and notebook 3 reports false alarms with and without those claims.
    """)
    return


@app.cell
def _(candidates, errors):
    usable = candidates[candidates["replayable"]].sort_values("id")
    n_errors = int((errors["replayable"] & ~errors["disputed"]).sum())
    assert len(usable) >= n_errors, f"only {len(usable)} usable passing claims for {n_errors} errors"
    drawn = random.Random(227).sample(list(usable["id"]), n_errors)
    passes = usable[usable["id"].isin(drawn)]
    print(
        f"{len(candidates)} candidate passing claims, {len(usable)} usable, {len(passes)} drawn "
        f"from {passes['card_url'].nunique()} cards; {int(passes['doubt'].sum())} the subagent doubted."
    )
    return (passes,)


@app.cell
def _(errors, passes):
    columns = ["id", "kind", "error_type", "claim", "source_url", "source_title", "passage", "wording", "doubt"]
    test_set = pd.concat([errors[errors["replayable"] & ~errors["disputed"]], passes])[columns]
    test_set["error_type"] = test_set["error_type"].fillna("pass")
    test_set["doubt"] = test_set["doubt"].fillna(False).astype(bool)
    (DATA / "test_set.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in test_set.to_dict("records")) + "\n"
    )
    print(test_set["error_type"].value_counts().to_markdown())
    return (test_set,)


@app.cell(hide_code=True)
def _(test_set):
    mo.md(f"""
    `data/test_set.jsonl` now holds {len(test_set)} items. Here are a few, so you can see what a checker gets:
    one claim and one passage.
    """)
    return


@app.cell
def _(test_set):
    test_set.groupby("error_type").head(1)[["id", "error_type", "claim", "passage"]]
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Limits of this set

    - **The passage was chosen by someone who knew the answer.** The subagent that cut each error's passage had
      read the correction, so it picked the part of the source that shows the problem. A checker in the pipeline
      has to find that part itself. Notebook 2's third checker, which reads the whole source, is the test of that.
    - **Reconstructed wording** was written by an agent that knew what was wrong, which can make an error plainer
      than the note made it. Notebook 3 splits recall by quoted and reconstructed claims.
    - **The errors were found by a Claude checker** (the 2026-10-08 Analyze job), so they lean toward errors a
      Claude checker can find. The passing claims went through Claude review too, so some are errors nobody caught.
    """)
    return


if __name__ == "__main__":
    app.run()
