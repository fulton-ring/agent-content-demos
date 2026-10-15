"""Run each hazard's final pipeline, score it on training and held-out states, and summarize the
agent experiment logs. Writes results/scores.csv, results/largest_differences.csv,
results/swarm_summary.csv and results/kept_pipelines_held_out.csv (every pipeline the loop kept,
scored on held-out states after the fact, plus the Claude Code subagent comparison).
"""

import time
from pathlib import Path

import pandas as pd

from fri_rebuild import answer_key, score
from fri_rebuild.experiment import load_pipeline
from fri_rebuild.paths import HAZARDS_DIR, RESULTS_DIR

HAZARDS = ("extreme_heat", "drought", "wildfire")


def largest_differences(detail: pd.DataFrame, count: int = 5) -> pd.DataFrame:
    detail = detail.assign(abs_log_error=detail["log_error"].abs())
    return (
        detail.sort_values("abs_log_error", ascending=False)
        .groupby(["column", "subset"])
        .head(count)
        .sort_values(["column", "subset", "abs_log_error"], ascending=[True, False, False])
    )


def swarm_summary(hazard: str) -> dict[str, object]:
    path = RESULTS_DIR / f"experiments-{hazard}.tsv"
    if not path.exists():
        return {"hazard": hazard}
    log = pd.read_csv(path, sep="\t")
    agents = log[(log["round"] > 0) & (log["status"] != "resume")]
    tested = agents["metric_log_mae"].notna()
    baseline = log.loc[log["round"] == 0, "metric_log_mae"].iloc[0]
    return {
        "hazard": hazard,
        "rounds": int(agents["round"].max()) if len(agents) else 0,
        "proposals": len(agents),
        "ran": int(tested.sum()),
        "kept": int((agents["status"] == "keep").sum()),
        "crashed": int((agents["status"] == "crash").sum()),
        "duplicates": int((agents["status"] == "duplicate").sum()),
        "rejected": int((agents["status"] == "rejected").sum()),
        "baseline_train_log_mae": baseline,
        "best_train_log_mae": log.loc[log["status"] == "keep", "metric_log_mae"].min(),
        "pipeline_minutes": round(log["seconds"].sum() / 60, 1),
        "model_cost_usd": round(log["cost_usd"].sum(), 2),
    }


def final_and_baseline_scores(key: pd.DataFrame, hazard: str) -> pd.DataFrame:
    """Training and held-out metrics for the human baseline and every kept pipeline."""
    log = pd.read_csv(RESULTS_DIR / f"experiments-{hazard}.tsv", sep="\t")
    kept = log[log["status"].isin(["keep"])].drop_duplicates("id")
    rows = []
    for _, entry in kept.iterrows():
        pipeline = RESULTS_DIR / "candidates" / hazard / f"{entry['id']}.py"
        rows.append(
            summarize_pipeline(key, pipeline, hazard, f"{entry['id']} {entry['description']}")
        )
    return pd.DataFrame(rows)


def summarize_pipeline(key: pd.DataFrame, pipeline: Path, hazard: str, label: str) -> dict:
    rebuilt = load_pipeline(pipeline).hazard_multipliers()
    result, _ = score.score(key, rebuilt, ("train", "held_out"))
    row: dict = {"hazard": hazard, "pipeline": label}
    for subset in ("train", "held_out"):
        part = result[result["subset"] == subset]
        row[f"{subset}_log_mae"] = round(float(part["log_mae"].mean()), 4)
        row[f"{subset}_same_bin"] = round(float(part["same_bin"].mean()), 4)
        row[f"{subset}_pearson"] = round(float(part["pearson"].mean()), 4)
    return row


def claude_code_comparison(key: pd.DataFrame) -> pd.DataFrame:
    """Score the final files of the Claude Code subagent loop (wildfire) the same way."""
    folder = RESULTS_DIR / "claude-code-subagents" / "wildfire"
    return pd.DataFrame(
        [
            summarize_pipeline(key, path, "wildfire", f"Claude Code subagent {path.stem}")
            for path in sorted(folder.glob("agent*.py"))
        ]
    )


def main() -> None:
    key = answer_key.conus(answer_key.load())
    scores, details, timings = [], [], []
    for hazard in HAZARDS:
        started = time.time()
        rebuilt = load_pipeline(HAZARDS_DIR / hazard / "pipeline.py").hazard_multipliers()
        timings.append({"hazard": hazard, "seconds": round(time.time() - started)})
        rebuilt.to_csv(RESULTS_DIR / f"county_hm_{hazard}.csv")
        result, detail = score.score(key, rebuilt, ("train", "held_out"))
        scores.append(result.assign(hazard=hazard))
        details.append(detail)
        print(result.round(3).to_string(index=False), flush=True)
    pd.concat(scores).to_csv(RESULTS_DIR / "scores.csv", index=False)
    largest_differences(pd.concat(details)).round(4).to_csv(RESULTS_DIR / "largest_differences.csv")
    summary = pd.DataFrame([swarm_summary(h) for h in HAZARDS]).merge(pd.DataFrame(timings))
    summary.to_csv(RESULTS_DIR / "swarm_summary.csv", index=False)
    print(summary.to_string(index=False))
    progress = pd.concat(
        [*(final_and_baseline_scores(key, h) for h in HAZARDS), claude_code_comparison(key)]
    )
    progress.to_csv(RESULTS_DIR / "kept_pipelines_held_out.csv", index=False)
    print(progress.to_string(index=False))


if __name__ == "__main__":
    main()
