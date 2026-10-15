"""Run each hazard's final pipeline, score it on training and held-out states, and summarize the
agent experiment logs. Writes results/scores.csv, results/largest_differences.csv and
results/swarm_summary.csv.
"""

import time

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
    agents = log[log["round"] > 0]
    tested = agents["metric_log_mae"].notna()
    baseline = log.loc[log["round"] == 0, "metric_log_mae"].iloc[0]
    return {
        "hazard": hazard,
        "rounds": int(agents["round"].max()) if len(agents) else 0,
        "proposals": len(agents),
        "ran": int(tested.sum()),
        "kept": int((agents["status"] == "keep").sum()),
        "crashed": int((agents["status"] == "crash").sum()),
        "rejected": int((agents["status"] == "rejected").sum()),
        "baseline_train_log_mae": baseline,
        "best_train_log_mae": log["metric_log_mae"].min(),
        "pipeline_minutes": round(log["seconds"].sum() / 60, 1),
        "model_cost_usd": round(log["cost_usd"].sum(), 2),
    }


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


if __name__ == "__main__":
    main()
