# Running a public nf-core pipeline with an AI agent

Can an AI agent take a public nf-core pipeline and do what a PhD student would: install it, run
it on its test data and on a batch of samples, retry failures and report, with a person only
approving changes? This is the spike for
[issue #200](https://github.com/fulton-ring/agent-content-demos/issues/200)
([proposal card](https://app.notion.com/p/403cc69045cb81c3ac2ecdf63ec11bd8)).

## What it shows

**Yes, on a small machine, with three kinds of human help.** The agent installed Nextflow, got
**nf-core/rnaseq 3.27.0** to reproduce the pipeline's own answer key, and ran six one-sample runs.
It retried the failures it could fix, and stopped on the one it shouldn't fix, a deliberately
truncated input file. Model cost was **$0.35**. Compute was free.

| | |
|---|---|
| Pipeline, samples | nf-core/rnaseq 3.27.0, `-profile test,docker` (yeast test data), then one run per sample for its 5 samples plus 1 "collaborator" sample |
| Runs | 7 runs, 10 attempts, 3 retries (all on the validation run). 6 finished |
| Validation vs the nf-test snapshot | 234 of 234 tasks succeeded. All 1,173 expected output paths present. 133 of 143 stable files match by md5 exactly, and 143 of 143 once the thread count written into 10 files is set from 4 back to 2 |
| Batch vs validation | All 5 real samples: 24 of 24 stable per-sample files identical to the validation run's |
| The planted failure | The collaborator's FASTQ (a public test file cut off halfway) failed at `FQ_LINT`. The agent confirmed it with `gzip -t`, didn't retry, didn't touch the data, and asked a person to get the file resent |
| Human help | 1 environment fix, 2 approved changes (4 requests: one lost to a harness crash, one repeated after a restart), 3 fixes to our own harness. Details below |
| Time | 39 min of pipeline time over 10 attempts (validation 15.0 min, one-sample runs 3 to 4.5 min each). 48 min from agent start to its final report, including the waits for a person |
| Cost | $0.35 model (Claude Sonnet 5.5 via OpenRouter, 44 calls, 818k input tokens, 92% read from cache) + $0 compute = **$0.35** |

**What a person did**, in the order it happened (all of it is in `log/events.jsonl`):

1. **Environment.** Nextflow couldn't download the pipeline: this sandbox's GitHub proxy blocks
   the GitHub API for repos not attached to the session (HTTP 403). The agent diagnosed that
   from the Nextflow log, refused to work around it, and asked for access. The person cloned the
   3.27.0 tag with git into Nextflow's asset cache. On a normal laptop or cluster this wouldn't
   happen.
2. **Approval: STAR memory.** STAR's genome indexing asked for 15 GB on a 15 GB machine with
   13.4 GB free. The agent wrote a config lowering that one process to 12 GB and asked. Approved.
3. **Approval: a global memory cap and one extra retry.** BBSplit then hit the same wall. The
   agent switched to `process.resourceLimits = [memory: 12.GB]`, the standard nf-core fix, and
   asked for one more validation attempt beyond its retry limit. Approved. It asked twice
   because the harness was restarted in between (item 6).
4. **Harness fix:** the agent's shell allowlist was stricter than intended (no `cd`, `tee` or
   `for` loops), so the agent couldn't write the per-sample sheets and stopped.
5. **Harness fix:** `request_approval` crashed while logging the request, so it never reached
   the person.
6. **Harness fix:** retries weren't logged when they finished. The person caught this by reading
   the log, and backfilled the two missing events from `nextflow log`.

Before the agent started, the person also started the Docker daemon, which the brief promises.

**The failures the agent caught on its own:** the GitHub 403, both out-of-memory failures, and
the truncated FASTQ. **The one a person had to catch:** none in the pipeline. The person caught
the gaps in our own run log (item 6). **What it did less well than an experienced user:** it
fixed memory one process at a time first, which cost one extra attempt before it found the cap
that works for every process.

## Read it

- [`brief.md`](brief.md): the agent's task, word for word, committed before the run.
- [`notebook.py`](notebook.py): a [marimo](https://marimo.io) notebook that reads the log and
  output checksums and scores the run, top to bottom: setup, runs, answer key, batch check,
  interventions, time and cost, the agent's own report.
- [`nfwatch.py`](nfwatch.py): the agent and the free tool. It is a Pydantic AI agent with a typed
  `RunReport` output and four tools: an allowlisted shell inside its workspace (no secrets in
  its environment), `launch_run`, `wait_for_run` and `request_approval`. Any argument beyond
  `--input`, `--outdir`, `-profile`, `-resume`, `-name` and `-w` is refused until a person
  approves it.
- `log/events.jsonl`: every model turn, shell command, run, approval and intervention, with
  timestamps. `log/messages.json` holds the full model conversation.
- `results/<run>/`: each run's Nextflow traces, and `outputs.tsv` with an md5 for every output
  file (nf-test style, so `.gz` files are hashed decompressed).
- `results/score.json`: the headline numbers, written by the notebook.

## Run it

```bash
./run.sh          # rescore the committed log and checksums (no model calls, about 10 s)
./run.sh --live   # run the agent again: needs OPENROUTER_API_KEY, Java 17+, Docker, ~1 h
```

To open the notebook interactively, run `uv run marimo edit notebook.py`. To point the tool at another
pipeline, set `NFWATCH_PIPELINE`, `NFWATCH_RELEASE` and `NFWATCH_PROFILE`, and rewrite
`brief.md`. While it runs, a person answers approval requests with
`uv run nfwatch.py approve <id> yes|no "note"`. When the agent stops with a question, the
person continues it with `uv run nfwatch.py run "<answer>"`.

## Where the data comes from

The pipeline is nf-core/rnaseq at tag 3.27.0. The test data are the files its `test` profile
points at in [nf-core/test-datasets](https://github.com/nf-core/test-datasets), which Nextflow
downloads at run time. The answer key is the pipeline's `tests/default.nf.test.snap` at the same
tag, which the notebook downloads. The collaborator sample is
`SRR6357073_1.fastq.gz` from the same test data, cut to half its bytes by `nfwatch.py prepare`.
Nothing downloaded is committed.

The machine was this worker's cloud container: 4 vCPU, 15 GB of memory, Docker 29.9, Java 21,
Nextflow 25.10.4 (the agent's choice). There was no charge for it.

## Why Pydantic AI, and what we looked at first

The issue asked for Pydantic AI with typed outputs, or a reason to use Claude Code itself.
We used Pydantic AI, so the agent's tools, approvals, budget and log are explicit code a lab can
read and reuse. Claude Code would also have run the pipeline, but its permission prompts are not
a log you can score. Before writing tools, we checked what exists. Nextflow's `-resume`, trace
files and `nextflow log` already do retries and accounting, and nf-core's `resourceLimits`
handles small machines, so the tool wraps them instead of reimplementing them. nf-test snapshots
gave the answer key.

## What it doesn't show

- **One run, one model, one small pipeline.** The test profile is tiny. Real data means longer
  runs, more failure modes (spot preemption, quota, disk) and a bigger bill. Nothing here was
  run in the cloud or on a scheduler.
- **The "person" was the supervising worker session**, not a bioinformatician, and the planted
  failure was ours. Real collaborators break things in more ways.
- **Three of six interventions were bugs in our harness**, found during the run. With them fixed,
  a rerun would need one environment fix (none outside this sandbox) and two approvals.
- **The thread-count match is our normalisation.** Exactly 133 of 143 checksums match. The other
  10 differ only in the thread number the tool records (`THREAD_RECORDS` in `nfwatch.py`).
- **The approval check is per argument**: once `-c <file>` is approved, the harness doesn't stop
  the agent editing that file. A person still has to read what changed.
- **No science**: the agent chose no methods and interpreted no results.
