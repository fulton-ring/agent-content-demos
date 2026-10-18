"""An autoresearch-style loop: agents propose edits to one hazard pipeline, and the harness keeps
the ones that score better on the training states.

Each round, several agents (Pydantic AI, Claude Sonnet through OpenRouter) work in parallel from
the current best pipeline. Each gets the hazard's program.md, the pipeline, its training scores,
the experiment log and notes on earlier hypotheses, and returns a complete new pipeline file.
The harness rejects code that reaches for the answer key, runs each candidate in a subprocess,
and keeps the round's best if it beats the current best by more than MIN_IMPROVEMENT. Every
proposal, with its code, is appended to experiments.jsonl.

Usage: uv run fri-swarm <hazard> [--rounds N] [--agents N] [--budget USD] [--resume NOTE]
Needs OPENROUTER_API_KEY.
"""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings

from fri_rebuild import data, inputs, scoring

MODEL = "anthropic/claude-sonnet-5.5"
RUN_TIMEOUT_SECONDS = 1500
MIN_IMPROVEMENT = 0.002
RECORD = data.PROJECT_DIR / "experiments.jsonl"
LOG_COLUMNS = ("id", "round", "agent", "parent", "metric_log_mae", "same_bin", "pearson")
LOG_COLUMNS += ("status", "seconds", "cost_usd", "description")
FORBIDDEN = re.compile(
    r"answer_key|fri_rebuild\.scor|from fri_rebuild import .*scor|fri_rebuild\.recipe"
    r"|read_excel|Master_Datasheet|nri-future-risk|raw\.githubusercontent|held_out"
)
RULES = """You are one of several research agents rebuilding a hazard multiplier (HM) from FEMA's
Future Risk Index. You can change exactly one file, pipeline.py. A fixed harness runs it and
scores the county multipliers it returns against FEMA's published values on a set of training
states (lower metric_log_mae is better; it is the mean absolute ln(rebuilt/published)).

Hard rules (a candidate that breaks them is rejected without being run):
- Follow FEMA's published methodology in program.md. You may resolve its ambiguities, fix bugs
  and make processing choices the documentation leaves open, but every change must be something
  FEMA could plausibly have done from the documented inputs.
- Never read the published multipliers, the answer key, the scorer, or the train/held-out split.
  No per-state or per-county adjustments, lookup tables, or constants fitted to the published
  values. Scores on other states are hidden from you and are what decides success.
- Use only `fri_rebuild.inputs` for data, plus numpy, pandas, scipy and geopandas.
- Keep `hazard_multipliers()` returning the same columns, indexed by county FIPS.
- The pipeline must finish in under 20 minutes on 4 CPU cores and 16 GB of RAM. Loading one
  variable for one 30-year period is about 0.6 GB as float32; free arrays you no longer need.

Do not wrap the method in try/except blocks that fall back to another method: a crash is logged
and tells everyone the idea failed, while a silent fallback hides it. Use the describe_input tool
to check table columns and values before you write code against them.

Make one focused change per experiment so the log shows what helped. Never resubmit an idea
the log already shows as tested. Return the complete file.
"""


class Proposal(BaseModel):
    """One experiment: a complete replacement for pipeline.py."""

    hypothesis: str = Field(
        description="What you think is wrong or open, and why this change helps"
    )
    description: str = Field(description="Under 90 characters, for the experiment log")
    pipeline_code: str = Field(description="The complete new contents of pipeline.py")


def records(harness: str, hazard: str) -> list[dict]:
    if not RECORD.exists():
        return []
    rows = [json.loads(line) for line in RECORD.read_text().splitlines()]
    return [r for r in rows if r["harness"] == harness and r["hazard"] == hazard]


def append(record: dict) -> None:
    with RECORD.open("a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def mark(hazard: str, record_id: str, status: str) -> None:
    """Set the status of the latest 'tested' record of `record_id` to keep or discard."""
    rows = [json.loads(line) for line in RECORD.read_text().splitlines()]
    for row in reversed(rows):
        if (row["harness"], row["hazard"], row["id"], row["status"]) == (
            "swarm",
            hazard,
            record_id,
            "tested",
        ):
            row["status"] = status
            break
    RECORD.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def load_module(path: Path, name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def score_file(path: Path) -> None:
    """Run one pipeline file and print its training scores (the subprocess side of `run`)."""
    started = time.time()
    rebuilt = load_module(path, "candidate").hazard_multipliers()  # ty: ignore[unresolved-attribute]
    key = data.conus(data.answer_key())
    unknown = [c for c in rebuilt.columns if c not in key.columns]
    assert not unknown, f"pipeline returned columns not in the answer key: {unknown}"
    scores, detail = scoring.score(key, rebuilt)
    by_state = detail.groupby("state")["log_error"].agg(["mean", lambda e: e.abs().mean()])
    by_state.columns = ["mean_log_error", "mean_abs_log_error"]
    worst = by_state.sort_values("mean_abs_log_error", ascending=False).head(8)
    print(f"---\npipeline_seconds: {time.time() - started:.1f}\nsubset: train")
    print(f"metric_log_mae: {scores['log_mae'].mean():.6f}")
    print(f"mean_same_bin: {scores['same_bin'].mean():.4f}")
    print(f"mean_pearson: {scores['pearson'].mean():.4f}")
    print("per_column:\n" + scores.drop(columns=["subset"]).round(4).to_string(index=False))
    print("worst_states (log error = ln(rebuilt/published)):\n" + worst.round(3).to_string())


def run(path: Path) -> dict:
    """Score a candidate in a subprocess: its metric (None if it failed), summary and seconds."""
    started = time.time()
    try:
        done = subprocess.run(
            [sys.executable, "-m", "fri_rebuild.swarm", "--score", str(path)],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"metric": None, "summary": "timeout", "seconds": time.time() - started}
    found = dict(
        re.findall(r"^(metric_log_mae|mean_same_bin|mean_pearson): (\S+)$", done.stdout, re.M)
    )
    metric = float(found.get("metric_log_mae", "nan"))
    failed = done.returncode != 0 or metric != metric
    return {
        "metric": None if failed else metric,
        "same_bin": None if failed else float(found["mean_same_bin"]),
        "pearson": None
        if failed or found["mean_pearson"] == "nan"
        else float(found["mean_pearson"]),
        "summary": (done.stdout + "\n" + done.stderr[-3000:])[-3000:]
        if failed
        else done.stdout.split("---", 1)[-1].strip(),
        "seconds": time.time() - started,
    }


def describe_input(name: str) -> str:
    """Show the shape, columns, dtypes and first rows of an input table.

    Names: baseline, cell_coordinates, coastal:htf_decadal, coastal:htf_observed,
    coastal:extreme_water_levels, coastal:sea_level_projections, coastal:flood_thresholds.
    """
    tables = {"baseline": inputs.baseline, "cell_coordinates": inputs.cell_coordinates}
    coastal = (
        "htf_decadal",
        "htf_observed",
        "extreme_water_levels",
        "sea_level_projections",
        "flood_thresholds",
    )
    if name not in tables and name.removeprefix("coastal:") not in coastal:
        return f"unknown table {name!r}"
    table = (
        tables[name]() if name in tables else inputs.coastal_tables()[name.removeprefix("coastal:")]
    )
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        return (
            f"shape {table.shape}\ncolumns {list(table.columns)}\ndtypes\n"
            f"{table.dtypes.value_counts().to_string()}\nfirst rows\n{table.head(5).to_string()}"
        )[:6000]


def log_text(hazard: str) -> str:
    """The swarm's log for one hazard as tab-separated text, the form agents are shown."""
    lines: list[str] = ["\t".join(LOG_COLUMNS)]
    lines += [
        "\t".join("" if r.get(c) is None else str(r[c]) for c in LOG_COLUMNS)
        for r in records("swarm", hazard)
    ]
    return "\n".join(lines) + "\n"


def log(hazard: str, **fields: object) -> None:
    """Append one experiment; the code goes only on the first record of an id."""
    if "code" in fields and fields["id"] in {r["id"] for r in records("swarm", hazard)}:
        del fields["code"]
    append(
        {"harness": "swarm", "hazard": hazard} | {c: fields.get(c) for c in LOG_COLUMNS} | fields
    )


async def propose(agent: Agent[None, Proposal], prompt: str) -> tuple[Proposal | None, float, str]:
    try:
        result = await agent.run(prompt)
    except Exception as error:  # noqa: BLE001 - a failed agent is logged, not fatal
        return None, 0.0, f"agent error: {error}"[:500]
    responses = [m for m in result.all_messages() if isinstance(m, ModelResponse)]
    cost = sum(float((m.provider_details or {}).get("cost", 0.0)) for m in responses)
    return result.output, cost, ""


def evaluate(
    hazard: str, proposal: Proposal | None, cost: float, error: str, fields: dict
) -> dict | None:
    """Log one proposal: crashed agent, rejected, duplicate, or run and scored."""
    fields = fields | {"cost_usd": round(cost, 4), "seconds": 0}
    if proposal is None:
        log(hazard, **fields, id="-", status="crash", description=error)
        return None
    code = proposal.pipeline_code
    fields["id"] = hashlib.sha1(code.encode()).hexdigest()[:7]
    if found := FORBIDDEN.search(code):
        log(
            hazard,
            **fields,
            status="rejected",
            description=f"{proposal.description} (forbidden: {found.group(0)!r})",
        )
        return None
    if fields["id"] in {r["id"] for r in records("swarm", hazard)}:
        log(
            hazard,
            **fields,
            status="duplicate",
            description=f"{proposal.description} (identical code already run)",
        )
        return None
    path = data.cache("runs", hazard, f"{fields['id']}.py")
    path.write_text(code)
    outcome = run(path)
    log(
        hazard,
        **fields | {"seconds": round(outcome["seconds"])},
        metric_log_mae=outcome["metric"],
        same_bin=outcome.get("same_bin"),
        pearson=outcome.get("pearson"),
        status="crash" if outcome["metric"] is None else "tested",
        description=proposal.description,
        code=code,
    )
    return outcome


async def swarm(
    hazard: str, rounds: int, agents: int, budget: float, patience: int, resume: str | None
) -> None:
    folder = data.PROJECT_DIR / "hazards" / hazard
    model = OpenRouterModel(MODEL)
    settings = OpenRouterModelSettings(max_tokens=16000, temperature=0.8)
    agent = Agent(
        model, output_type=Proposal, instructions=RULES, model_settings=settings, retries=2
    )
    agent.tool_plain(describe_input)
    best_code = (folder / "pipeline.py").read_text()
    best_id = hashlib.sha1(best_code.encode()).hexdigest()[:7]
    start = max([0, *(r["round"] for r in records("swarm", hazard))]) + 1 if resume else 1
    outcome = run(folder / "pipeline.py")
    assert outcome["metric"] is not None, f"starting pipeline failed:\n{outcome['summary']}"
    log(
        hazard,
        id=best_id,
        round=start - 1,
        agent=0,
        parent="-",
        metric_log_mae=outcome["metric"],
        same_bin=outcome["same_bin"],
        pearson=outcome["pearson"],
        status="resume" if resume else "keep",
        seconds=round(outcome["seconds"]),
        cost_usd=0,
        description=f"resume: {resume}" if resume else "baseline (human-written)",
        code=best_code,
    )
    best_metric, best_summary = outcome["metric"], outcome["summary"]
    notes: list[str] = []
    stale, spent = 0, 0.0
    for round_number in range(start, start + rounds):
        if spent >= budget or stale >= patience:
            break
        prompts = [
            "\n\n".join(
                [
                    f"# program.md\n{(folder / 'program.md').read_text()}",
                    f"# Current best pipeline.py\n```python\n{best_code}\n```",
                    f"# Training-state scores of the current best\n```\n{best_summary}\n```",
                    f"# Experiment log so far\n```\n{log_text(hazard)}\n```",
                    "# Notes from earlier experiments\n" + ("\n".join(notes[-12:]) or "none yet"),
                    f"You are agent {a} of {agents} this round. Pick a different idea from the "
                    f"other agents: prefer open question number {a} in program.md if it has not "
                    "been settled yet, otherwise anything the log suggests.",
                ]
            )
            for a in range(1, agents + 1)
        ]
        proposals = await asyncio.gather(*(propose(agent, p) for p in prompts))
        spent += sum(cost for _, cost, _ in proposals)
        tried: list[str] = []
        winner: tuple[float, str, str, str] | None = None
        for a, (proposal, cost, error) in enumerate(proposals, 1):
            fields = {"round": round_number, "agent": a, "parent": best_id}
            result = evaluate(hazard, proposal, cost, error, fields)
            if proposal is None:
                continue
            code_id = hashlib.sha1(proposal.pipeline_code.encode()).hexdigest()[:7]
            metric = None if result is None else result["metric"]
            said = "crashed or rejected" if metric is None else f"metric {metric:.4f}"
            notes.append(
                f"- {code_id} ({proposal.description}): {said} vs best {best_metric:.4f}. "
                f"Hypothesis: {proposal.hypothesis[:400]}"
            )
            if result is not None and metric is None:
                notes.append(f"  error tail: {result['summary'][-600:]}")
            tried.append(code_id)
            if result is not None and metric is not None and (winner is None or metric < winner[0]):
                winner = (metric, code_id, proposal.pipeline_code, result["summary"])
        print(f"round {round_number}: spent ${spent:.2f}", flush=True)
        stale += 1
        if winner is not None and winner[0] < best_metric - MIN_IMPROVEMENT:
            best_metric, best_id, best_code, best_summary = winner
            (folder / "pipeline.py").write_text(best_code)
            stale = 0
        for code_id in tried:
            mark(hazard, code_id, "keep" if code_id == best_id else "discard")
    print(f"best {best_id}: metric {best_metric:.6f}; spent ${spent:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hazard", nargs="?")
    parser.add_argument("--score", type=Path, help="score one pipeline file (used by the loop)")
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--agents", type=int, default=3)
    parser.add_argument("--budget", type=float, default=4.0)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--resume", metavar="NOTE", help="continue the existing log; NOTE says why")
    args = parser.parse_args()
    if args.score:
        score_file(args.score)
        return
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    asyncio.run(
        swarm(args.hazard, args.rounds, args.agents, args.budget, args.patience, args.resume)
    )


if __name__ == "__main__":
    main()
