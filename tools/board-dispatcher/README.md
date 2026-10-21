# Board dispatcher

Starts a Claude Research worker on each Ready card on the [Agent work](https://github.com/orgs/fulton-ring/projects/1) board. The `Board dispatcher` GitHub Action runs it every 15 minutes, and right away whenever a `move:*` label is added to an issue.

Cloud agent sessions can't reach the org's project board, so agents signal on the issue and the dispatcher moves the card. Each run, first:

- A `move:ready`, `move:review`, `move:needs-founder` or `move:backlog` label sets the card's Status to Ready, Review, Needs founder or Backlog, and the label is removed. If several are present, the first in that order wins.
- A line `Not before: YYYY-MM-DD` in the issue body fills the card's Not before field, and a line `Card: <Notion URL>` fills Proposal, when those fields are empty.

Then a card gets a worker when all of these hold:

- Status is **Ready** and the issue is open.
- Agent is **Claude worker** or empty.
- Not before is empty or today or earlier.
- The issue isn't blocked by an open issue.
- No `Worker started` comment on the issue in the last 6 hours.
- Fewer than `MAX_IN_PROGRESS` Claude cards are **In progress** (30 in the workflow, a safety ceiling rather than a throttle).
- Fewer than `MAX_STARTS_PER_DAY` workers were started in the last 24 hours, counting `Worker started` comments on every issue on the board (5 in the workflow). This sets the pace; extra Ready cards wait, oldest first.

For each one it starts the worker routine with the issue in the payload, moves the card to **In progress** and comments `Worker started <time>: <session url>` on the issue. If a start fails, it logs the error, goes on to the next card, and the run exits with an error so the failure shows in Actions. The card stays Ready and is tried again next run.

## Run it

```sh
cd tools/board-dispatcher
DRY_RUN=1 GH_TOKEN=... SPIKE_WORKER_TOKEN=... WORKER_ROUTINE_ID=trig_01QFJTcXruuR1BDyYQMK7kgU \
  PROJECT_OWNER=fulton-ring PROJECT_NUMBER=1 REPO=fulton-ring/agent-content-demos \
  uv run board-dispatcher
```

`DRY_RUN=1` lists the cards it would start without starting anything. From GitHub, run the workflow by hand; it defaults to a dry run.

## Configuration

| Variable | Meaning |
| --- | --- |
| `GH_TOKEN` | Fine-grained token with Projects read/write on the org and Issues read/write on this repo (Actions secret `AGENT_BOARD_TOKEN`) |
| `SPIKE_WORKER_TOKEN` | API token for the Research worker routine (Actions secret `SPIKE_WORKER_TOKEN`) |
| `WORKER_ROUTINE_ID` | The Research worker routine |
| `PROJECT_OWNER`, `PROJECT_NUMBER` | The board |
| `REPO` | Only issues from this repo are started |
| `MAX_IN_PROGRESS` | Cap on Claude cards In progress (default 5) |
| `MAX_STARTS_PER_DAY` | Cap on workers started in any 24 hours (default 5) |
| `COOLDOWN_HOURS` | Hours after a `Worker started` comment before another worker can start on that issue (default 6) |
| `DRY_RUN` | `1` to list without starting |

## Check

```sh
uv run ruff format --check . && uv run ruff check . && uv run ty check && uv run pytest
```
