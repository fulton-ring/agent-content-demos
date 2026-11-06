"""nfwatch: an agent that launches, watches, retries and summarizes Nextflow runs.

The agent (Pydantic AI, through OpenRouter) gets a written brief and a small set of tools: a
shell in its workspace, a tool that launches one pipeline run in the background, a tool that
waits on a run and reads its logs, and a tool that asks a person to approve any change to the
pipeline or its parameters. Every model turn, tool call, approval and human intervention is
appended to a JSONL log with a timestamp, so the run can be scored afterwards.

Usage:
  uv run nfwatch.py prepare                    make the workspace and the collaborator sample
  uv run nfwatch.py run [NOTE]                 start the agent on brief.md, or continue
                                               its last session with a note from the person
  uv run nfwatch.py approve <id> yes|no NOTE   answer an approval request (the person)
  uv run nfwatch.py intervene WHAT WHY         log something a person did by hand
  uv run nfwatch.py manifest                   record output checksums and traces in results/

Config (environment): OPENROUTER_API_KEY, NFWATCH_WORKSPACE (default .nfrun),
NFWATCH_MODEL (default anthropic/claude-sonnet-5.5), NFWATCH_BUDGET_USD (default 2.0),
NFWATCH_LOG (default log/events.jsonl).
"""

import asyncio
import gzip
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, Tool
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.usage import UsageLimits

HERE = Path(__file__).parent
WORKSPACE = Path(os.environ.get("NFWATCH_WORKSPACE", HERE / ".nfrun")).resolve()
LOG = Path(os.environ.get("NFWATCH_LOG", HERE / "log" / "events.jsonl"))
MODEL = os.environ.get("NFWATCH_MODEL", "anthropic/claude-sonnet-5.5")
BUDGET_USD = float(os.environ.get("NFWATCH_BUDGET_USD", "2.0"))
PIPELINE, RELEASE = "nf-core/rnaseq", "3.27.0"
FREE_ARGS = {"-profile", "test,docker", "-resume"}  # plus --input/--outdir/-name/-w values
MAX_TAIL = 4000
APPROVAL_WAIT_S = 3600
# The agent's shell runs only these programs, only inside its workspace, without secrets.
ALLOWED = {
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "zcat",
    "gzip",
    "gunzip",
    "wc",
    "find",
    "file",
    "md5sum",
    "sort",
    "uniq",
    "cut",
    "awk",
    "sed",
    "echo",
    "printf",
    "mkdir",
    "cp",
    "mv",
    "rm",
    "chmod",
    "curl",
    "wget",
    "java",
    "nextflow",
    "./nextflow",
    "docker",
    "test",
    "du",
    "df",
    "stat",
    "tar",
    "which",
    "date",
    "pwd",
    "tr",
    "column",
    "diff",
    "cd",
    "tee",
    "for",
    "done",
}
KEYWORDS_BEFORE_COMMAND = {"do"}
DOCKER_READ_ONLY = {"ps", "images", "info", "version", "--version", "logs", "inspect"}
OPERATORS = {"|", "||", "&&", ";", "&", ">", ">>", "<", "(", ")"}
COLLAB_SOURCE = "https://raw.githubusercontent.com/nf-core/test-datasets/rnaseq/testdata/GSE110004/SRR6357073_1.fastq.gz"


def log_event(kind: str, **fields: object) -> None:
    """Append one timestamped event to the run log and echo it to stdout."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    event = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "kind": kind, **fields}
    with LOG.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")
    print(json.dumps(event, default=str)[:300], flush=True)


def tail(text: str, limit: int = MAX_TAIL) -> str:
    return text if len(text) <= limit else "...[truncated]...\n" + text[-limit:]


# ---------------------------------------------------------------- typed agent output and inputs


class RunResult(BaseModel):
    run_name: str
    samples: list[str]
    finished: bool
    attempts: int = Field(ge=1)
    wall_clock_minutes: float
    failure_cause: str = Field(description="Empty if the first attempt succeeded")
    what_fixed_it: str = Field(description="Empty if no failure, 'nothing' if it never passed")


class RunReport(BaseModel):
    setup_steps: list[str] = Field(description="What you installed or configured, in order")
    runs: list[RunResult]
    failures_caught: list[str] = Field(description="Failures you diagnosed, one line each")
    needs_a_person: list[str] = Field(description="Anything left for a person to decide or fix")


class ChangeRequest(BaseModel):
    kind: Literal["parameter", "config", "pipeline_code", "resources"]
    run_name: str
    exact_args: list[str] = Field(description="The exact extra command-line arguments")
    reason: str


# ------------------------------------------------------------------------------- the tools


def run_dir(name: str) -> Path:
    assert name.replace("_", "").replace("-", "").isalnum(), f"bad run name {name!r}"
    return WORKSPACE / "runs" / name


def read_state() -> dict:
    path = WORKSPACE / "state.json"
    return json.loads(path.read_text()) if path.exists() else {"approved": [], "runs": {}}


def write_state(state: dict) -> None:
    (WORKSPACE / "state.json").write_text(json.dumps(state, indent=1))


def find_nextflow() -> str | None:
    local = WORKSPACE / "nextflow"
    return str(local) if local.exists() else shutil.which("nextflow")


def clean_env() -> dict[str, str]:
    """The environment for agent commands and runs, with API keys and tokens removed."""
    secret = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    env = {k: v for k, v in os.environ.items() if not any(w in k.upper() for w in secret)}
    return env | {"PATH": f"{WORKSPACE}:{os.environ['PATH']}", "NXF_ANSI_LOG": "false"}


def shell_refusal(command: str) -> str:
    """Why a shell command is refused, or an empty string if it is allowed."""
    if "`" in command or "$(" in command or "<(" in command:
        return "no command substitution"
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as err:
        return f"could not parse: {err}"
    head = True
    for i, token in enumerate(tokens):
        if token in OPERATORS:
            head = token not in {">", ">>", "<"}
            continue
        if ".." in token or token.startswith("~"):
            return "no '..' or '~' paths"
        if token.startswith("/") and not token.startswith((str(WORKSPACE), "/dev/null")):
            return f"path {token} is outside the workspace"
        if head and token in KEYWORDS_BEFORE_COMMAND:
            continue
        if head and token not in ALLOWED:
            return f"{token} is not an allowed program"
        if head and token in {"nextflow", "./nextflow"} and tokens[i + 1 : i + 2] == ["run"]:
            return "start pipeline runs with launch_run so they are logged and approved"
        if head and token == "docker" and not set(tokens[i + 1 : i + 2]) <= DOCKER_READ_ONLY:
            return "docker is read-only here (ps, images, info, version, logs, inspect)"
        head = False
    return ""


def shell(command: str, timeout_s: int = 600) -> str:
    """Run a shell command in the workspace and return its exit code and output (tail).

    Use it to install tools, inspect files and read logs. Only common file, download and
    inspection programs are allowed, only on paths inside the workspace; no sudo, no scripts.
    Do not start pipeline runs with it; use launch_run. Timeout is capped at 900 seconds.
    """
    refusal = shell_refusal(command)
    if refusal:
        log_event("shell_refused", command=command, reason=refusal)
        return f"Refused: {refusal}."
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["bash", "-c", command],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=min(max(timeout_s, 1), 900),
            env=clean_env(),
        )
    except subprocess.TimeoutExpired as err:
        log_event("shell", command=command, exit="timeout", seconds=time.monotonic() - started)
        return f"timed out after {err.timeout} s\n{tail(str(err.output or ''))}"
    out = tail(proc.stdout + proc.stderr)
    log_event("shell", command=command, exit=proc.returncode, seconds=time.monotonic() - started)
    return f"exit {proc.returncode}\n{out}"


def unapproved(extra_args: list[str], approved: list[str]) -> list[str]:
    return [a for a in extra_args if a not in FREE_ARGS and a not in approved]


def launch_run(
    run_name: str, samplesheet: str = "", resume: bool = False, extra_args: list[str] | None = None
) -> str:
    """Start one nf-core/rnaseq 3.27.0 run in the background with -profile test,docker.

    run_name: e.g. validation or sample_WT_REP1. samplesheet: path or URL for --input, empty for
    the test profile's own. resume: add -resume (use for retries, same run_name). extra_args:
    any other arguments; each must have been approved through request_approval first.
    Returns at once; then call wait_for_run.
    """
    extra = extra_args or []
    state = read_state()
    blocked = unapproved(extra, state["approved"])
    if blocked:
        return f"Refused: {blocked} need approval first (request_approval)."
    running = [n for n, r in state["runs"].items() if r.get("pid") and pid_alive(r["pid"])]
    if running:
        return f"Refused: {running} still running; run one pipeline at a time."
    nextflow = find_nextflow()
    if nextflow is None:
        return "Refused: no nextflow found in the workspace or on PATH. Install it first."
    folder = run_dir(run_name)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    cmd = [
        nextflow,
        "run",
        PIPELINE,
        "-r",
        RELEASE,
        "-profile",
        "test,docker",
        "--outdir",
        str(folder / "results"),
        "-w",
        str(folder / "work"),
        "-with-trace",
        str(folder / f"trace_{stamp}.txt"),
        *extra,
    ]
    if samplesheet:
        cmd += ["--input", samplesheet]
    if resume:
        cmd.append("-resume")
    out = (folder / f"stdout_{stamp}.txt").open("w")
    proc = subprocess.Popen(
        cmd,
        cwd=folder,
        stdout=out,
        stderr=subprocess.STDOUT,
        env=clean_env(),
    )
    run = state["runs"].setdefault(run_name, {"attempts": 0})
    run.pop("ended", None)
    run.update(
        pid=proc.pid,
        attempts=run["attempts"] + 1,
        started=time.time(),
        stdout=out.name,
        samplesheet=samplesheet,
    )
    write_state(state)
    log_event(
        "run_launched",
        run=run_name,
        attempt=run["attempts"],
        resume=resume,
        command=" ".join(cmd[1:]),
    )
    return f"Started {run_name} attempt {run['attempts']} (pid {proc.pid})."


def pid_alive(pid: int) -> bool:
    try:
        finished, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return Path(f"/proc/{pid}").exists()
    return finished == 0


def wait_for_run(run_name: str, max_minutes: int = 60) -> str:
    """Wait until a run exits or max_minutes pass (cap 120), then report its state and log tail."""
    state = read_state()
    run = state["runs"].get(run_name)
    if run is None:
        return f"No run named {run_name}."
    deadline = time.monotonic() + min(max(max_minutes, 1), 120) * 60
    while pid_alive(run["pid"]) and time.monotonic() < deadline:
        time.sleep(30)
    stdout = Path(run["stdout"]).read_text(errors="replace")
    alive = pid_alive(run["pid"])
    succeeded = "Pipeline completed successfully" in stdout or "Succeeded   :" in stdout
    status = "running" if alive else ("succeeded" if succeeded else "failed")
    minutes = (time.time() - run["started"]) / 60
    if not alive and "ended" not in run:
        run.update(ended=time.time(), status=status)
        write_state(state)
        log_event(
            "run_finished",
            run=run_name,
            attempt=run["attempts"],
            status=status,
            minutes=round(minutes, 2),
        )
    return (
        f"{run_name}: {status} after {minutes:.1f} min (attempt {run['attempts']})\n{tail(stdout)}"
    )


def request_approval(change: ChangeRequest) -> str:
    """Ask a person to approve a change to the pipeline or its parameters; wait for the answer."""
    pending = WORKSPACE / "approvals"
    pending.mkdir(exist_ok=True)
    approval_id = f"a{len(list(pending.glob('*.request.json'))) + 1}"
    (pending / f"{approval_id}.request.json").write_text(change.model_dump_json(indent=1))
    log_event("approval_requested", id=approval_id, change=change.model_dump())
    answer_path = pending / f"{approval_id}.answer.json"
    deadline = time.monotonic() + APPROVAL_WAIT_S
    while not answer_path.exists() and time.monotonic() < deadline:
        time.sleep(15)
    if not answer_path.exists():
        log_event("approval_timeout", id=approval_id)
        return "No answer within an hour: treat it as denied."
    answer = json.loads(answer_path.read_text())
    return f"{'Approved' if answer['approved'] else 'Denied'}: {answer['note']}"


# ------------------------------------------------------------------------------ the commands


def approve(approval_id: str, approved: bool, note: str) -> None:
    """Record a person's answer; an approval lets launch_run use the requested arguments."""
    folder = WORKSPACE / "approvals"
    change = ChangeRequest.model_validate_json((folder / f"{approval_id}.request.json").read_text())
    if approved:
        state = read_state()
        state["approved"] += change.exact_args
        write_state(state)
    answer = {"approved": approved, "note": note}
    (folder / f"{approval_id}.answer.json").write_text(json.dumps(answer))
    log_event("approval_answered", id=approval_id, **answer)


def prepare() -> None:
    """Make an empty workspace with the collaborator's sample: a public test FASTQ, cut short."""
    (WORKSPACE / "inputs").mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(COLLAB_SOURCE, timeout=120) as resp:
        assert resp.status == 200, f"download failed: {resp.status}"
        data = resp.read()
    fastq = gzip.decompress(data)
    assert fastq.startswith(b"@"), "not a FASTQ"
    truncated = data[: len(data) // 2]  # a transfer that stopped halfway
    target = WORKSPACE / "inputs" / "COLLAB_REP1_R1.fastq.gz"
    target.write_bytes(truncated)
    (WORKSPACE / "inputs" / "collab_samplesheet.csv").write_text(
        f"sample,fastq_1,fastq_2,strandedness\nCOLLAB_REP1,{target},,reverse\n"
    )
    log_event(
        "prepared", workspace=str(WORKSPACE), collab_bytes=len(truncated), source_bytes=len(data)
    )


def session_costs() -> list[float]:
    """Model cost of each earlier agent session (its last reported running total), from the log."""
    if not LOG.exists():
        return []
    costs: list[float] = []
    for line in LOG.read_text().splitlines():
        event = json.loads(line)
        if event["kind"] == "agent_started":
            costs.append(0.0)
        elif "cost_usd" in event and costs:
            costs[-1] = max(costs[-1], event["cost_usd"])
    return costs


async def run_agent(note: str) -> None:
    brief = (HERE / "brief.md").read_text()
    settings = OpenRouterModelSettings(
        max_tokens=4000,
        openrouter_cache_instructions=True,
        openrouter_cache_messages=True,
        openrouter_cache_tool_definitions=True,
    )
    agent = Agent(
        OpenRouterModel(MODEL),
        output_type=RunReport,
        instructions=brief,
        model_settings=settings,
        retries=2,
        tools=[
            Tool(shell, takes_ctx=False),
            Tool(launch_run, takes_ctx=False),
            Tool(wait_for_run, takes_ctx=False),
            Tool(request_approval, takes_ctx=False),
        ],
    )
    log_event(
        "agent_started",
        model=MODEL,
        budget_usd=BUDGET_USD,
        brief_sha256=hashlib.sha256(brief.encode()).hexdigest(),
    )
    messages_path = LOG.parent / "messages.json"
    history = []
    prompt = "Start the job in the brief."
    if note:
        history = ModelMessagesTypeAdapter.validate_json(messages_path.read_bytes())
        if isinstance(history[-1], ModelResponse):  # a tool call the last session never answered
            history = history[:-1]
        prompt = f"A person replied to your report: {note}\nCarry on with the job in the brief."
        log_event("agent_resumed", note=note)
    budget_left = BUDGET_USD - sum(session_costs())
    assert budget_left > 0, "the model budget is spent"
    async with agent.iter(
        prompt, message_history=history, usage_limits=UsageLimits(request_limit=200)
    ) as run:
        async for node in run:
            usage = run.usage
            cost = float(usage.cost or 0)
            if Agent.is_call_tools_node(node):
                calls = [p for p in node.model_response.parts if p.part_kind == "tool-call"]
                log_event(
                    "model_turn",
                    cost_usd=round(cost, 4),
                    input_tokens=usage.input_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    output_tokens=usage.output_tokens,
                    tool_calls=[{"tool": c.tool_name, "args": c.args} for c in calls],
                )
            messages_path.write_bytes(run.all_messages_json())
            if cost > budget_left:
                log_event("budget_stop", cost_usd=cost)
                return
    assert run.result is not None
    log_event(
        "report",
        cost_usd=round(float(run.usage.cost or 0), 4),
        requests=run.usage.requests,
        report=run.result.output.model_dump(),
    )


def manifest() -> None:
    """Write each run's output checksums and Nextflow traces into results/ for scoring."""
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    for folder in sorted((WORKSPACE / "runs").iterdir()):
        target = out / folder.name
        target.mkdir(exist_ok=True)
        for trace in folder.glob("trace_*.txt"):
            shutil.copy(trace, target / trace.name)
        results = folder / "results"
        rows = ["path\tmd5"]
        for path in sorted(p for p in results.rglob("*") if results.exists()):
            rel = path.relative_to(results)
            digest = hashlib.md5(path.read_bytes()).hexdigest() if path.is_file() else ""
            rows.append(f"{rel}\t{digest}")
        (target / "outputs.tsv").write_text("\n".join(rows) + "\n")
    log_event("manifest", runs=[p.name for p in out.iterdir() if p.is_dir()])


def main() -> None:
    args = sys.argv[1:]
    assert args, __doc__
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    if args[0] == "prepare":
        prepare()
    elif args[0] == "run":
        assert os.environ.get("OPENROUTER_API_KEY"), "set OPENROUTER_API_KEY"
        asyncio.run(run_agent(" ".join(args[1:])))
    elif args[0] == "approve" and len(args) == 4:
        approve(args[1], args[2] == "yes", args[3])
    elif args[0] == "intervene" and len(args) == 3:
        log_event("intervention", what=args[1], why=args[2])
    elif args[0] == "manifest":
        manifest()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
