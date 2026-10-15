"""Run one hazard pipeline file and score it on the training states.

Usage: python -m fri_rebuild.experiment <pipeline.py> <output.parquet> [--held-out]

Prints a summary block the swarm parses. Held-out scores are printed only with --held-out,
which the swarm never passes.
"""

import argparse
import importlib.util
import sys
import time
from pathlib import Path

import pandas as pd

from fri_rebuild import answer_key, score


def load_pipeline(path: Path):  # noqa: ANN201 - returns a module
    spec = importlib.util.spec_from_file_location(f"pipeline_{path.parent.name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worst_states(detail: pd.DataFrame, count: int = 8) -> pd.DataFrame:
    by_state = detail.groupby("state")["log_error"].agg(["mean", lambda e: e.abs().mean()])
    by_state.columns = ["mean_log_error", "mean_abs_log_error"]
    return by_state.sort_values("mean_abs_log_error", ascending=False).head(count)


def summarize(scores: pd.DataFrame, detail: pd.DataFrame, subset: str) -> str:
    part = scores[scores["subset"] == subset]
    lines = [
        f"subset: {subset}",
        f"metric_log_mae: {part['log_mae'].mean():.6f}",
        f"mean_same_bin: {part['same_bin'].mean():.4f}",
        f"mean_pearson: {part['pearson'].mean():.4f}",
        "per_column:",
        part.drop(columns=["subset"]).round(4).to_string(index=False),
        "worst_states (log error = ln(rebuilt/published)):",
        worst_states(detail[detail["subset"] == subset]).round(3).to_string(),
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pipeline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--held-out", action="store_true")
    args = parser.parse_args()

    started = time.time()
    rebuilt = load_pipeline(args.pipeline).hazard_multipliers()
    seconds = time.time() - started
    key = answer_key.conus(answer_key.load())
    unknown = [c for c in rebuilt.columns if c not in key.columns]
    if unknown:
        sys.exit(f"pipeline returned columns not in the answer key: {unknown}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rebuilt.to_parquet(args.output)
    subsets = ("train", "held_out") if args.held_out else ("train",)
    scores, detail = score.score(key, rebuilt, subsets)
    print("---")
    print(f"pipeline_seconds: {seconds:.1f}")
    for subset in subsets:
        print(summarize(scores, detail, subset))


if __name__ == "__main__":
    main()
