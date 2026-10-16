"""The experiment record: every proposal from every agent harness, in experiments.jsonl.

One JSON object per line, in the order things happened. Every record has `harness` (swarm,
swarm-guard-bug, claude-code-subagent, recipe-search), `hazard`, `run` (the agent run within a
harness), `id`, `status` and `description`, plus whatever metrics that harness logged.

`code` holds the file an experiment produced. Swarm candidates carry it on their first record (a
resume record repeats an id without it). The Claude Code subagents and the recipe-search agents
logged only metrics per experiment, so each of their runs ends with one record of status
"final" holding the run's final file.
"""

import json
from collections.abc import Iterator

import pandas as pd

from fri_rebuild.paths import PROJECT_DIR

PATH = PROJECT_DIR / "experiments.jsonl"
SWARM_COLUMNS = (
    "id",
    "round",
    "agent",
    "parent",
    "metric_log_mae",
    "same_bin",
    "pearson",
    "status",
    "seconds",
    "cost_usd",
    "description",
)


def read() -> Iterator[dict]:
    with PATH.open() as handle:
        for line in handle:
            yield json.loads(line)


def write(records: list[dict]) -> None:
    PATH.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def append(record: dict) -> None:
    with PATH.open("a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def table(harness: str | None = None, hazard: str | None = None) -> pd.DataFrame:
    """Records as a table (without code), optionally for one harness and hazard."""
    rows = [
        {k: v for k, v in r.items() if k != "code"} | {"has_code": "code" in r}
        for r in read()
        if (harness is None or r["harness"] == harness)
        and (hazard is None or r["hazard"] == hazard)
    ]
    return pd.DataFrame(rows)


def code(harness: str, hazard: str, record_id: str, run: str | None = None) -> str:
    """The file an experiment (or, with record_id "final", an agent run) produced."""
    for r in read():
        if (
            r["harness"] == harness
            and r["hazard"] == hazard
            and r["id"] == record_id
            and (run is None or r.get("run") == run)
            and "code" in r
        ):
            return r["code"]
    raise KeyError(f"no code for {harness} {hazard} {run} {record_id}")


def set_status(harness: str, hazard: str, record_id: str, old: str, new: str) -> None:
    """Change the latest record of `record_id` with status `old` to `new`."""
    records = list(read())
    for record in reversed(records):
        if (record["harness"], record["hazard"], record["id"], record["status"]) == (
            harness,
            hazard,
            record_id,
            old,
        ):
            record["status"] = new
            break
    write(records)


def swarm_log_text(hazard: str) -> str:
    """The swarm's log for one hazard as tab-separated text, the form agents are shown."""
    lines = ["\t".join(SWARM_COLUMNS)]
    for r in read():
        if r["harness"] == "swarm" and r["hazard"] == hazard:
            lines.append("\t".join("" if r.get(c) is None else str(r[c]) for c in SWARM_COLUMNS))
    return "\n".join(lines) + "\n"
