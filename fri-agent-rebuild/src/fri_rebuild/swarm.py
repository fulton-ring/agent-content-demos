"""An autoresearch-style loop: agents propose edits to one hazard pipeline, the harness keeps
the ones that score better on the training states.

Each round, several agents work in parallel from the current best pipeline. Every agent gets
the hazard's program.md, the current pipeline, the experiment log and the latest training-state
scores, and returns a complete new pipeline file. The harness rejects code that reaches for the
answer key, runs each candidate, and keeps the best one if it beats the current best.

Usage: python -m fri_rebuild.swarm <hazard> [--rounds N] [--agents N] [--budget USD]
       [--resume NOTE]
"""

import argparse
import asyncio
import hashlib
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings

from fri_rebuild.paths import HAZARDS_DIR, RESULTS_DIR, cache_path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
MODEL = "anthropic/claude-sonnet-5.5"
RUN_TIMEOUT_SECONDS = 1500
MIN_IMPROVEMENT = 0.002
LOG_COLUMNS = (
    "id\tround\tagent\tparent\tmetric_log_mae\tsame_bin\tpearson\tstatus\tseconds\tcost_usd\t"
    "description"
)
FORBIDDEN = (
    re.compile(r"answer_key|fri_rebuild\.score|from fri_rebuild import .*score"),
    re.compile(r"read_excel|Master_Datasheet|nri-future-risk|raw\.githubusercontent"),
    re.compile(r"held_out|split\.label"),
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
- Use only `fri_rebuild.inputs` for data, plus numpy, pandas and scipy.
- Keep `hazard_multipliers()` returning the same columns, indexed by county FIPS.
- The pipeline must finish in under 20 minutes on 4 CPU cores and 16 GB of RAM. Loading one
  variable for one 30-year period is about 0.6 GB as float32; free arrays you no longer need.

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


@dataclass
class Outcome:
    metric: float | None
    same_bin: float | None
    pearson: float | None
    summary: str
    seconds: float


@dataclass
class Candidate:
    id: str
    agent: int
    proposal: Proposal | None
    cost: float
    error: str = ""


def code_id(code: str) -> str:
    return hashlib.sha1(code.encode()).hexdigest()[:7]


def forbidden_reason(code: str) -> str | None:
    for pattern in FORBIDDEN:
        if match := pattern.search(code):
            return f"forbidden reference: {match.group(0)!r}"
    return None


def run_pipeline(path: Path, output: Path) -> Outcome:
    started = time.time()
    try:
        done = subprocess.run(
            [sys.executable, "-m", "fri_rebuild.experiment", str(path), str(output)],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return Outcome(None, None, None, "timeout", time.time() - started)
    seconds = time.time() - started
    text = done.stdout + "\n" + done.stderr[-3000:]
    metric = re.search(r"^metric_log_mae: ([\d.]+|nan)", done.stdout, re.M)
    if done.returncode != 0 or not metric or metric.group(1) == "nan":
        return Outcome(None, None, None, text[-3000:], seconds)
    same_bin = re.search(r"^mean_same_bin: ([\d.]+)", done.stdout, re.M)
    pearson = re.search(r"^mean_pearson: (-?[\d.]+|nan)", done.stdout, re.M)
    return Outcome(
        float(metric.group(1)),
        float(same_bin.group(1)) if same_bin else None,
        float(pearson.group(1)) if pearson and pearson.group(1) != "nan" else None,
        done.stdout.split("---", 1)[-1].strip(),
        seconds,
    )


def response_cost(messages: list) -> float:
    return sum(
        float((m.provider_details or {}).get("cost", 0.0))
        for m in messages
        if isinstance(m, ModelResponse)
    )


class Swarm:
    def __init__(self, hazard: str, agents: int, budget: float) -> None:
        self.hazard = hazard
        self.agents = agents
        self.budget = budget
        self.folder = HAZARDS_DIR / hazard
        self.pipeline = self.folder / "pipeline.py"
        self.program = (self.folder / "program.md").read_text()
        self.log_path = RESULTS_DIR / f"experiments-{hazard}.tsv"
        self.candidates = RESULTS_DIR / "candidates" / hazard
        self.candidates.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.write_text(LOG_COLUMNS + "\n")
        self.spent = 0.0
        self.agent = Agent(
            OpenRouterModel(MODEL),
            output_type=Proposal,
            instructions=RULES,
            model_settings=OpenRouterModelSettings(max_tokens=16000, temperature=0.8),
            retries=2,
        )

    def log(self, row: list[object]) -> None:
        with self.log_path.open("a") as handle:
            handle.write(
                "\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n"
            )

    def prompt(self, best_code: str, best_summary: str, notes: list[str], agent: int) -> str:
        return "\n\n".join(
            [
                f"# program.md\n{self.program}",
                f"# Current best pipeline.py\n```python\n{best_code}\n```",
                f"# Training-state scores of the current best\n```\n{best_summary}\n```",
                f"# Experiment log so far\n```\n{self.log_path.read_text()}\n```",
                "# Notes from earlier experiments\n" + ("\n".join(notes[-12:]) or "none yet"),
                f"You are agent {agent} of {self.agents} this round. Pick a different idea from "
                f"the other agents: prefer open question number {agent} in program.md if it has "
                "not been settled yet, otherwise anything the log suggests.",
            ]
        )

    async def propose(self, prompt: str, agent: int) -> Candidate:
        try:
            result = await self.agent.run(prompt)
        except Exception as error:  # noqa: BLE001 - a failed agent is logged, not fatal
            return Candidate("-", agent, None, 0.0, f"agent error: {error}"[:500])
        cost = response_cost(result.all_messages())
        proposal = result.output
        return Candidate(code_id(proposal.pipeline_code), agent, proposal, cost)

    def evaluate(self, candidate: Candidate, round_number: int, parent: str) -> Outcome | None:
        proposal = candidate.proposal
        if proposal is None:
            self.log(
                [
                    candidate.id,
                    round_number,
                    candidate.agent,
                    parent,
                    "",
                    "",
                    "",
                    "crash",
                    0,
                    f"{candidate.cost:.4f}",
                    candidate.error,
                ]
            )
            return None
        if reason := forbidden_reason(proposal.pipeline_code):
            self.log(
                [
                    candidate.id,
                    round_number,
                    candidate.agent,
                    parent,
                    "",
                    "",
                    "",
                    "rejected",
                    0,
                    f"{candidate.cost:.4f}",
                    f"{proposal.description} ({reason})",
                ]
            )
            return None
        path = self.candidates / f"{candidate.id}.py"
        path.write_text(proposal.pipeline_code)
        outcome = run_pipeline(path, cache_path("runs", self.hazard, f"{candidate.id}.parquet"))
        status = "crash" if outcome.metric is None else "tested"
        self.log(
            [
                candidate.id,
                round_number,
                candidate.agent,
                parent,
                "" if outcome.metric is None else f"{outcome.metric:.6f}",
                outcome.same_bin or "",
                outcome.pearson or "",
                status,
                f"{outcome.seconds:.0f}",
                f"{candidate.cost:.4f}",
                proposal.description,
            ]
        )
        return outcome

    def mark(self, candidate_id: str, status: str) -> None:
        lines = self.log_path.read_text().splitlines()
        for index in range(len(lines) - 1, 0, -1):
            fields = lines[index].split("\t")
            if fields[0] == candidate_id and fields[7] == "tested":
                fields[7] = status
                lines[index] = "\t".join(fields)
                break
        self.log_path.write_text("\n".join(lines) + "\n")

    def last_round(self) -> int:
        rows = self.log_path.read_text().splitlines()[1:]
        return max((int(row.split("\t")[1]) for row in rows), default=0)

    async def run(self, rounds: int, patience: int, resume_note: str | None) -> None:
        """Run the loop. With resume_note, continue an existing log from the kept pipeline."""
        best_code = self.pipeline.read_text()
        best_id = code_id(best_code)
        (self.candidates / f"{best_id}.py").write_text(best_code)
        start = self.last_round() + 1 if resume_note else 1
        start_run = run_pipeline(
            self.pipeline, cache_path("runs", self.hazard, f"{best_id}.parquet")
        )
        if start_run.metric is None:
            sys.exit(f"starting pipeline failed:\n{start_run.summary}")
        self.log(
            [
                best_id,
                start - 1,
                0,
                "-",
                f"{start_run.metric:.6f}",
                start_run.same_bin,
                start_run.pearson,
                "resume" if resume_note else "keep",
                f"{start_run.seconds:.0f}",
                "0",
                f"resume: {resume_note}" if resume_note else "baseline (human-written)",
            ]
        )
        best_metric, best_summary = start_run.metric, start_run.summary
        notes: list[str] = []
        stale = 0
        for round_number in range(start, start + rounds):
            if self.spent >= self.budget:
                print(f"budget reached: ${self.spent:.2f}")
                break
            prompts = [
                self.prompt(best_code, best_summary, notes, a) for a in range(1, self.agents + 1)
            ]
            candidates = await asyncio.gather(
                *(self.propose(p, a) for a, p in enumerate(prompts, 1))
            )
            self.spent += sum(c.cost for c in candidates)
            round_best: tuple[float, Candidate, Outcome] | None = None
            for candidate in candidates:
                outcome = self.evaluate(candidate, round_number, best_id)
                if candidate.proposal is not None:
                    result = (
                        "crashed or rejected"
                        if outcome is None or outcome.metric is None
                        else (f"metric {outcome.metric:.4f} vs best {best_metric:.4f}")
                    )
                    notes.append(
                        f"- {candidate.id} ({candidate.proposal.description}): {result}. "
                        f"Hypothesis: {candidate.proposal.hypothesis[:400]}"
                    )
                    if outcome is not None and outcome.metric is None:
                        notes.append(f"  error tail: {outcome.summary[-600:]}")
                if (
                    outcome
                    and outcome.metric is not None
                    and (round_best is None or outcome.metric < round_best[0])
                ):
                    round_best = (outcome.metric, candidate, outcome)
            print(f"round {round_number}: spent ${self.spent:.2f}", flush=True)
            if round_best and round_best[0] < best_metric - MIN_IMPROVEMENT:
                metric, candidate, outcome = round_best
                assert candidate.proposal is not None
                best_metric, best_summary = metric, outcome.summary
                best_code, best_id = candidate.proposal.pipeline_code, candidate.id
                self.pipeline.write_text(best_code)
                stale = 0
            else:
                stale += 1
            for candidate in candidates:
                if candidate.proposal is not None:
                    self.mark(candidate.id, "keep" if candidate.id == best_id else "discard")
            if stale >= patience:
                print(f"no improvement for {patience} rounds; stopping")
                break
        print(f"best {best_id}: metric {best_metric:.6f}; spent ${self.spent:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hazard")
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--agents", type=int, default=3)
    parser.add_argument("--budget", type=float, default=4.0)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--resume", metavar="NOTE", help="continue the existing log; NOTE says why")
    args = parser.parse_args()
    swarm = Swarm(args.hazard, args.agents, args.budget)
    asyncio.run(swarm.run(args.rounds, args.patience, args.resume))


if __name__ == "__main__":
    main()
