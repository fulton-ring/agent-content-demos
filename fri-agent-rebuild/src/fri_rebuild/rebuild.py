"""Run each hazard's final pipeline, score it on training and held-out states, and summarize the
experiment record (experiments.jsonl): every pipeline the loop kept, scored on held-out states
after the fact, plus the Claude Code subagent comparison. The notebook notebooks/rebuild.py
writes the tables to results/rebuild/.
"""

import time
from types import ModuleType

import pandas as pd

from fri_rebuild.agents import records
from fri_rebuild.pipeline import hazard_pipeline, load_source
from fri_rebuild.scoring import metrics

HAZARDS = ("extreme_heat", "extreme_heat_loca2", "drought", "wildfire", "coastal_flooding")


def largest_differences(detail: pd.DataFrame, count: int = 5) -> pd.DataFrame:
    detail = detail.assign(abs_log_error=detail["log_error"].abs())
    return (
        detail.sort_values("abs_log_error", ascending=False)
        .groupby(["column", "subset"])
        .head(count)
        .sort_values(["column", "subset", "abs_log_error"], ascending=[True, False, False])
    )


def swarm_summary(hazard: str) -> dict[str, object]:
    log = records.table("swarm", hazard)
    if log.empty:
        return {"hazard": hazard}
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


def kept_pipeline_scores(key: pd.DataFrame, hazard: str) -> pd.DataFrame:
    """Training and held-out metrics for every pipeline the loop kept, baseline included."""
    log = records.table("swarm", hazard)
    kept = log[log["status"] == "keep"].drop_duplicates("id")
    rows = []
    for _, entry in kept.iterrows():
        pipeline = load_source(
            records.code("swarm", hazard, entry["id"]), f"{hazard}_{entry['id']}"
        )
        rows.append(
            summarize_pipeline(key, pipeline, hazard, f"{entry['id']} {entry['description']}")
        )
    return pd.DataFrame(rows)


def summarize_pipeline(key: pd.DataFrame, pipeline: ModuleType, hazard: str, label: str) -> dict:
    rebuilt = pipeline.hazard_multipliers()
    result, _ = metrics.score(key, rebuilt, ("train", "held_out"))
    row: dict = {"hazard": hazard, "pipeline": label}
    for subset in ("train", "held_out"):
        part = result[result["subset"] == subset]
        row[f"{subset}_log_mae"] = round(float(part["log_mae"].mean()), 4)
        row[f"{subset}_same_bin"] = round(float(part["same_bin"].mean()), 4)
        row[f"{subset}_pearson"] = round(float(part["pearson"].mean()), 4)
    return row


def claude_code_comparison(key: pd.DataFrame) -> pd.DataFrame:
    """Score the final files of the Claude Code subagent loops the same way."""
    finals = records.table("claude-code-subagent")
    finals = finals[finals["status"] == "final"].sort_values(["hazard", "run"])
    rows = []
    for _, final in finals.iterrows():
        hazard, run = str(final["hazard"]), str(final["run"])
        code = records.code("claude-code-subagent", hazard, "final", run)
        pipeline = load_source(code, f"{hazard}_{run}")
        rows.append(summarize_pipeline(key, pipeline, hazard, f"Claude Code subagent {run}"))
    return pd.DataFrame(rows)


def run_hazard(
    key: pd.DataFrame, hazard: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, float]:
    """Final pipeline's county multipliers, its scores, per-county detail and run seconds."""
    started = time.time()
    rebuilt = hazard_pipeline(hazard).hazard_multipliers()
    seconds = time.time() - started
    result, detail = metrics.score(key, rebuilt, ("train", "held_out"))
    return rebuilt, result.assign(hazard=hazard), detail, seconds
