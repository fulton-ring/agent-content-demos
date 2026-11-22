# What do state public-records portals require, and are agencies tightening it because of AI agents?

Issue [#319](https://github.com/fulton-ring/agent-content-demos/issues/319). In November 2026 the Virginia
Department of Education (VDOE) said it asks "non-verifiable" records requesters for photo ID and "will soon move to
requiring ID for all submissions", after "an influx in nonsensical or incomplete communication requests"
([WVTF, 2026-11-16](https://www.wvtf.org/news/2026-11-16/anthropic-ai-agents-submitted-records-requests-to-virginias-education-department)).
We read the records-request portal of one agency in every state and DC, and searched for every other 2026 change
to how records requests are taken in.

**Short answer: almost no portal asks for ID, and the 2026 reaction is spreading, but not as ID checks.**
On 2026-11-21, none of the 37 environmental-agency portals whose form we could see required photo ID. 10 of 51
require an account, 8 states limit requests to residents by law, 31 accept requests by plain email and none
offers an API. Outside VDOE we found 10 tightenings in 2026, 9 of them aimed at AI or bots:
- state laws in Indiana (CAPTCHA, address and residency checks, surcharges for automated requests), Illinois
  (verify you're a person, with photo ID banned) and California (AI agents aren't a "person"; effective 2027)
- local rules in six towns and counties.

VDOE's is the only ID requirement we found. The bills that would have added ID or residency proof (KY, NH, RI) or
let agencies deny suspected AI requests (PA) all died. So the expected trend is half right: agencies are tightening
because of automated requests, but with captchas, human checks and surcharges, not ID.

## Run it

```bash
./run.sh                # re-fetch every surveyed page once (about 3 min), then the summary; needs uv
SKIP_FETCH=1 ./run.sh   # the summary only, from the committed results/fetch.csv
```

There are no keys, no paid services and nothing to download: cost $0.

## What's here

- `survey.csv`: the hand-read survey, one row per state and DC. Each row has the page it was read from and the
  date read, plus:
  - who must do what: account, name, postal address, residency on the form, photo ID, captcha
  - which channels work: email, API
  - whether the state's records statute limits requests to residents, with the citation and its operative words
  - any 2026 change, with sources and a hand-coded `change_2026_kind`
  - `read_status`: `read`, `partial` or `blocked`
- `changes_2026.csv`: every 2026 change to records-request intake we found, across state laws, state agencies and
  local governments. Each row gives its status (enacted, adopted, said or died), whether it cites AI or bots,
  whether it requires photo ID, and whether the source is primary.
- `collect.py` (part 1, marimo): fetches each surveyed URL once with a plain script and an honest user agent. It
  records the status, any bot-challenge or captcha markers, and a SHA-256 of the page, so a later run can tell
  whether a page changed. It writes `results/fetch.csv`.
- `survey.py` (part 2, marimo): counts everything below from the two CSVs and `fetch.csv`, and writes
  `results/summary.json`. `outputs/survey.html` is the rendered notebook.

## How the survey was done

- **Selection rule:** the state environmental agency (DEQ, DEP, DEC or equivalent; DOEE for DC). Every state has
  one, they get steady requests from the public, consultants and nonprofits, and the card named it first.
- **Hand-read fields:** every field in `survey.csv` was read by hand, by five research agents working ten states
  each, from public pages only. Each agent read the statute text on the legislature's site where it could reach it.
- **Rules followed:**
  - No accounts were created, nothing was submitted and no bot check was bypassed.
  - Louisiana's form shows its contact fields only after a first step, so one agent typed placeholder text, clicked
    Next and stopped before Submit.
  - Where a site refused us, the row was filled from search-engine copies of its pages and marked `blocked`.
- **Script-checked:** only `results/fetch.csv`.
- **2026 changes:** found in a separate search of news, legislatures, attorney-general and records-counselor
  pages. The Indiana and Illinois statute text and the WVTF quotes were re-checked against the primary source.
  California SB 1159 rests on law-firm alerts, because the state's bill site blocked automated reading.

## Results (2026-11-21)

| | yes | optional | no | unknown |
|---|---|---|---|---|
| Account required | 10 | 6 | 32 | 3 |
| Name required | 21 | | 11 | 19 |
| Postal address required | 14 | | 15 | 22 |
| Form asks for residency | 4 | | 30 | 17 |
| Photo ID required | 0 | | 37 | 14 |
| Captcha on form | 6 | | 21 | 24 |
| Accepts requests by email | 31 | | 11 | 9 |
| API or machine channel | 0 | | 51 | 0 |

- **Coverage:** 51 portals surveyed: 22 read fully, 24 partly (form behind a login, script or bot check), 5
  blocked (AK, AZ, CO, ME, VT). With a plain script, 7 to 8 records pages refused or failed (the count varies by
  run and network) and all 6 JustFOIA forms in the sample refused or answered with a bot challenge
  (`results/fetch.csv`).
- **Residency by law:** AL, AR, DE, KY, NH, NJ, TN and VA limit requests to their own residents or citizens by the
  statute's text. New Jersey's courts have let out-of-state requesters sue anyway. Pennsylvania limits requests to
  legal residents of the United States and is coded `us_only`.
- **Residency on the form:** DE, ID, PA and TN ask about it. Idaho's question is "for tracking purposes only", and
  Pennsylvania's asks about US residency.
- **Short of photo ID:** Tennessee's rule and Alabama's law let the agency ask for ID to prove residency. None of
  the forms we could see requires it.
- **2026 tightenings, and their motives:** the 4 surveyed agencies that changed in 2026 are CA, IL and IN (state
  laws) and GA (moved to a portal-only channel and dropped email). Of the 10 tightenings outside VDOE in
  `changes_2026.csv`, 9 cite AI or bots. Georgia's gives no reason.

## What it doesn't show

- **What the hidden forms ask:** GovQA and AccessGov portals show nothing before you register, so about a third of
  the name, address and captcha fields are `unknown`.
- **Whole states:** a state law binds every agency, but an agency policy like VDOE's binds only that agency. The
  survey reads one agency per state.
- **A census of local rules:** the local rows are what a search turned up, and several rest on meeting summaries
  (`source_kind`).
- **What any AI agent did:** the only facts here are VDOE's statement and the governor's release. We make no claim
  about what Anthropic's agents were doing.
- **Our first pass at captchas:** `collect.py`'s `captcha_marker` is a text match and fires on pages that merely
  mention a captcha. The captcha column in the table comes from the hand read, not from that marker.
