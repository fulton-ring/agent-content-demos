# What does one answer cost an AI agent through a public data MCP server?

We asked 60 questions with known answers through three public data MCP servers, 20 per server
and each question twice, with the same client and model. For every answer we counted tokens,
tool calls, time, dollars, whether it was right and whether it carried a link a reader could
check. Then we changed one thing about HIFLD Next's server, on our side of the wire, and asked
its 20 questions again. Issue: #240.

Everything is in one marimo notebook, [`cost_per_answer.py`](cost_per_answer.py). It reads top
to bottom: what each server sends, the questions, the agent, the runs, scoring, cost per correct
answer, where the tokens go, the design change, the verdict and the limits. A rendered copy
from the run below is in [`outputs/cost_per_answer.html`](outputs/cost_per_answer.html).

## Run it

```bash
export OPENROUTER_API_KEY=...   # about $1.60 of model calls per full run
./run.sh                        # runs the notebook as a script, about 12 minutes
RESCORE=1 ./run.sh              # rescores the committed runs; no model calls, no key needed, about 8 minutes (it re-checks every cited link)
```

To read it with its tables, run `uv run marimo edit cost_per_answer.py`. Settings are
environment variables: `AGENT_REPEATS` (default 2), `AGENT_BUDGET_USD` (default 4; the run
stops starting questions past it) and `AGENT_MODEL` (default `anthropic/claude-haiku-5.5`).

`outputs/` holds `runs_shipped.jsonl` and `runs_no_map_tools.jsonl` (usage and the typed answer
for every run), `transcripts/` (every run's full messages), `scored.csv`, `summary.json`,
`tool_definitions.json` (what each server lists), and the HTML and two screenshots.

## Where the data comes from

- **The servers**, all public with no key: HIFLD Next at `https://hifld.publicenvirodata.org/mcp`,
  MoSPI at `https://mcp.mospi.gov.in/mcp`
  ([source](https://github.com/nso-india/esankhyiki-mcp)), and Urban's Education Data Portal at
  `https://educationdata.urban.org/mcp/edp` (linked from Urban's
  [October 2026 brief](https://www.urban.org/research/publication/improving-how-llms-handle-education-and-workforce-pathway-data)).
- **The questions** ([`questions/`](questions/)) are written the way each server's users would
  ask, each pinned to one answer: a number with a tolerance for honest rounding, or a name. We
  looked up every answer ourselves from the publisher's own API, not through a model, and
  `how_found` gives the exact call. HIFLD answers were checked three ways (MCP SQL, the OGC
  features API, local GeoParquet), 19 of 20 Urban answers two ways, and 8 MoSPI answers against
  a press release. Questions with two defensible answers were dropped.

## Results

From a clean run on 2026-11-09 (`./run.sh` from a fresh clone, 12 minutes, $1.61 on
OpenRouter). Every number is in `outputs/summary.json`. Model: Claude Haiku 5.5.

| server | answers | correct | link from tools | median tokens (p90) | median tool calls (p90) | median s (p90) | $ per answer | $ per correct |
|---|---|---|---|---|---|---|---|---|
| HIFLD Next | 40 | 100% | 100% | 140,044 (202,331) | 6 (7) | 11.9 (14.9) | 0.0157 | 0.0157 |
| MoSPI | 40 | 100% | 0% | 43,957 (113,249) | 3.5 (4) | 11.2 (13.6) | 0.0068 | 0.0068 |
| Urban EDP | 40 | 92.5% | 100% | 55,194 (111,237) | 5 (8) | 11.2 (58.1) | 0.0079 | 0.0085 |

"Link from tools" means the answer's source URL came out of a tool result. The stricter
"checkable" column in the notebook (the link is on the publisher's domain and opens) gives about
the same (95–100% / 0% / 97.5–100%); it depends on live link checks.

**Where the tokens go.** Every step resends the tool definitions, so the first request of a run
is the fixed price of a step:

| server | tools listed | fixed tokens per step | median steps | share of input tokens that is fixed |
|---|---|---|---|---|
| HIFLD Next | 16 | 17,023 | 6 | 70% |
| MoSPI | 4 | 5,002 | 4 | 35% |
| Urban EDP | 6 | 5,125 | 6 | 47% |

HIFLD Next lists five map-widget tools for clients that can render an
[MCP Apps](https://modelcontextprotocol.io/docs/extensions/apps) map. Their definitions are
about 49,000 of its 63,000 characters of tool definitions. The largest results are HIFLD's
`get_dataset_file` (median 20,000 characters, a full STAC record), MoSPI's `list_datasets`
(26,000) and `get_metadata` (8,000), and Urban's `describe_dataset` (7,300). MoSPI's four-step
workflow costs less than we expected: the dataset names are listed in the tool schema, so the
agent skipped `list_datasets` in 28 of 40 runs.

**The design change.** We dropped every tool HIFLD Next marks with a UI resource from the list
the model sees. A server can make the same change itself, because clients declare MCP Apps
support when they connect.

| HIFLD Next | fixed tokens per step | median tokens | $ per answer | correct | link from tools |
|---|---|---|---|---|---|
| as shipped | 17,023 | 140,044 | 0.0157 | 100% | 100% |
| map tools listed only to UI clients | 6,886 | 92,487 | 0.0099 | 100% | 100% |

That cuts cost per answer by 37%, and the spread between servers goes from 2.3x to 1.5x.

**Verdict: it fails on cost and holds on the cause.** Cost per correct answer differs 2.3x
(0.68¢ to 1.57¢), not by an order of magnitude; all three answer for about a cent. But the
difference is tool design, not data size. The costliest server is the one that sends the most
tool definitions on every step, and one change to its tool list closes most of the gap. The
difference that is large is citation. Urban attaches a provenance block with the API URL and a
ready-made citation to every result, and HIFLD's results carry file URLs, so every answer
passed a link on. MoSPI's results carry none: its answers were right, but no answer had a link
from the tools, so a reader has nothing to check them against.

**Misses.** The 3 wrong answers were all Urban's: Delaware's 2021-22 enrollment taken from the
2022 year (the portal labels a school year by its fall), a Wyoming total summed from school rows
(92,495 against the district total of 92,467), and Wyoming's open schools counted as 358, with
3 more under another status, against the key's 361.

**Total cost and time.** This run cost $1.61 and took 12 minutes. All model spend while building
this was about $4.40 of the $5 budget: a smoke test, a full run whose usage was lost to a crash in
scoring (now fixed: each section saves its runs as it finishes), the run that set the scoring,
and this clean run.

## What it doesn't show

- **Harder questions.** Almost every answer was right, so cost per correct answer is close to
  cost per answer. The judgment calls Urban's own study found agents miss (choosing a source,
  the right denominator) would separate the servers on accuracy; this set can't.
- **Equal questions.** The data differs, so the questions do. Each has one answer, but they
  aren't equally hard.
- **Other clients and models.** Pydantic AI sends every listed tool on every step. A client
  that loads tool definitions only when needed would erase most of HIFLD Next's fixed cost, and
  another model may take more or fewer steps. One model, two repeats per question.
- **Lasting dollar figures.** Haiku 5.5 is $0.10 per million input tokens; tokens and steps
  will date more slowly than prices.
- **Whether MoSPI's agent-built links open.** Its API host needs TLS legacy renegotiation, so
  our client and proxy can't open it. That's why we report `link_from_tools`, which doesn't
  depend on our network.
- **A neutral party.** We built HIFLD Next. It is the most expensive of the three as shipped.

## What we looked at first

Pydantic AI's `MCPToolset` connects to each server, passes on its instructions and validates the
typed answer. Its `filtered()` makes the design change without touching the server, and
OpenRouter reports each request's cost. We wrote only the scoring rules, the tables and the
question keys.
