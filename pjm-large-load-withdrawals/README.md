# How many large-load projects in PJM's planning slides are later withdrawn?

Issue [#234](https://github.com/fulton-ring/agent-content-demos/issues/234). Each month PJM's transmission
owners present "supplemental" projects to PJM's planning committees. Some are driven by one customer
asking for a lot of power ("Customer in DeKalb: 504 MW"), and later decks list some of them as withdrawn.
This spike reads every supplemental deck since January 2025, extracts each customer-load need with a
typed model call, follows each need number from deck to deck, and checks the named substations against
the public map.

Everything is in one marimo notebook, [`withdrawals.py`](withdrawals.py), which reads top to bottom.

## Run it

```bash
./run.sh            # needs uv; writes outputs/ and outputs/run_log.txt
uv run marimo edit withdrawals.py   # to read it with the outputs next to the code
```

The saved model answers in `outputs/extractions/` are reused, so a rerun needs no API key and costs
nothing. To pay for fresh answers, delete that folder and set `OPENROUTER_API_KEY`
(`EXTRACTION_MODEL` picks the model; the default is `anthropic/claude-haiku-5.5`).

## Data

| Source | What we use | How |
|---|---|---|
| PJM TEAC, SRRTEP-West, SRRTEP-Mid-Atlantic, SRRTEP-South meeting materials | 434 "supplemental projects" decks, 2025-01-07 to 2026-11-13 | Listed through the form post behind each committee page's year drop-down (`/m/CommitteesAndGroups/RefreshMaterials`), downloaded to `data/` at run time, not committed |
| `us-substations-verified/dataset/` on `main` (commit `a9bdd88`) | `us_substations_hifld_only.csv` (HIFLD Next substations, derived from line ends) and `us_substations.parquet` (adds OpenStreetMap) | Downloaded at run time |
| HIFLD Next transmission lines v1.0.0 | `SUB_1`/`SUB_2` names | Downloaded at run time |
| Census cartographic county boundaries 2024 | the map | Downloaded at run time |

The issue says TEAC. Most owners present supplemental needs at the subregional committees instead
(AEP, ATSI, APS, Dayton and DEOK mostly at SRRTEP-West), so we read all four committees.

## Method, briefly

1. Text from every page with `pdfplumber` (4,610 pages). Only pages that tie a need number to a customer
   and an MW figure go to the model, plus every withdrawal or cancellation page, and every later page in
   the same deck that names those need numbers: 925 pages from 247 decks. Nine withdrawal pages that are
   pictures of tables go as images.
2. One Pydantic AI call per deck over OpenRouter, with output validated against a `DeckNeeds` schema:
   need number, stage (need / solution / withdrawn), whether it's one customer's load, area, MW by year,
   ultimate MW, estimated cost, in-service date, lines cut into, existing and new substations.
3. Each need is followed by number. "Presented" is its needs-meeting date; "withdrawn" is the first deck
   that lists it as withdrawn or cancelled. A **large load** is a customer-load need of 100 MW or more
   (our line; PJM's decks define none).
4. Resubmission check: a withdrawn need counts as resubmitted if a later need from the same owner names
   the same new substation, or the same area and a common existing substation.
5. Named existing substations are matched by normalised name within the state, as in
   `bpa-load-request-substations/` (#190); lines match if a HIFLD Next line has both end names.

## Results (from the run in `outputs/run_log.txt`)

**Extraction accuracy.** 37 needs keyed by hand, in a random sample of 29 and a sample of 8 withdrawal
slides (see `hand_keyed.csv` and the notebook for how they were drawn): 168 of 174 field checks right
(96.6%). Stage 36/37, customer-load call 34/36, area 30/30, ultimate MW 28/28, cost 32/33, named
substations 8/10. Two of my own keys were wrong (costs on the next slide); I corrected them against the
PDF before the final run.

**Withdrawals.** Of **216 large-load requests** in the decks since January 2025, **26 (12%) were
withdrawn**: 9.3 of 100.9 GW (9%), and $883M of $11.8B in estimated transmission cost (7.5%). Counting
every customer-load need (287), 31 were withdrawn (11%).

| Owner | Large-load requests | Withdrawn | GW | GW withdrawn | Est. cost $M | Cost withdrawn $M |
|---|---|---|---|---|---|---|
| Dominion (DOM) | 76 | 13 | 14.6 | 2.1 | 1,517 | 30 |
| AEP | 44 | 0 | 22.6 | 0 | 575 | 0 |
| PPL | 31 | 0 | 25.4 | 0 | 3,172 | 0 |
| ComEd | 19 | **9 (47%)** | 12.4 | **4.9** | 1,930 | **492** |
| Dayton | 10 | 0 | 6.8 | 0 | 1,749 | 0 |
| All 18 owners | 216 | 26 | 100.9 | 9.3 | 11,768 | 883 |

Full table, including DEOK, PECO (PE), UGI and BGE with one withdrawal each:
`outputs/large_load_by_owner.csv`.

- **Time to withdrawal:** median 11 months from first presentation (4.8 to 46). 10 of the 26 had a
  solution and a cost estimate presented before they were withdrawn, among them ComEd's $245M DeKalb
  project (ComEd-2025-009), withdrawn a month after its solution was shown.
- **Cohort first presented in 2025 or later:** 14 of 164 large-load needs withdrawn (9%).
- **Not resolved yet:** 75 large-load needs have no solution and no withdrawal in any deck so far.
- **Resubmissions:** none found. Seven withdrawn Dominion needs have a later need in the same county
  with similar MW, but each names a different new substation (for example Hera, Nero and Caesar against
  Mudel), so they look like different sites (`outputs/resubmissions.csv`).

**The public map.** Of 242 distinct existing substations named by large-load needs, **43% are in HIFLD
Next** and **57% in us-substations-verified** under the same name in the same state
(`outputs/map_coverage.csv`). Only 20 of 151 lines cut into (13%) match a HIFLD Next line by both end
names. HIFLD splits lines at taps and names the ends differently, so this test is too strict to read as
coverage.
`outputs/large_load_map.png` maps requested and withdrawn GW by county. Luzerne County, PA (8.1 GW over
7 requests) leads.

**Cost and time.** The saved answers cost $0.28 (887k input and 376k output tokens, 30 minutes of model
time, about 4 minutes of wall clock at 8 calls in parallel). Including two earlier full runs while I
fixed the prompt, the spike spent about $0.85 of its $5 budget.

## Is the dropout argument right?

Partly. Withdrawals are not rare at ComEd, which withdrew 9 of its 19 large-load requests (40% of the
GW and 26% of the estimated cost), and Dominion cancelled 13 old requests in three decks in autumn 2026.
Across PJM as a whole, 12% of requests and 9% of GW were withdrawn. AEP, PPL and Dayton, with half the
requested GW between them, withdrew none. So the churn is real but concentrated in a few owners, and
the queue elsewhere looks firmer than a flat 50% dropout assumes. Many requests are too new to judge.

## What it doesn't show, and what didn't work

- **Only what owners present under PJM's M-3 process.** Loads served at distribution voltage, or
  through other processes, never appear. A need that silently disappears is counted as pending.
- **"Withdrawn" mixes reasons.** ComEd and PECO "withdraw need"; Dominion and APS list "cancellations".
  We don't separate a customer walking away from a utility reshaping its plan.
- **Costs are incomplete.** Only needs that reached a solution carry a cost. Dominion's Do No Harm
  follow-up projects, which some customer loads trigger, are separate need numbers and aren't added.
- **The model double-counted one cost** in the hand sample (Dayton-2026-001: $103.4M against $51.7M,
  the components plus the total). Telling it never to add a total to its parts fixed that once, but it
  also made it drop costs printed only in phases. The final prompt ("use the printed total, otherwise
  sum the parts") still double-counted this slide, so some solution costs may be too high, Dayton's in
  particular.
- **Name matching is exact after clean-up.** "Taneytown No. 1" on the slide isn't "Taneytown" on the
  map. The notebook lists misses.
- **Customer identity.** The decks name no customer, and nothing here is labelled a data center.
  Dominion's and PSE&G's slides themselves sometimes say "data center"; we don't use that.
- **Sensitive join.** The need-to-substation table with coordinates stays in `data/` (not committed);
  founders decide whether to publish it. `outputs/` has counts, a county map and need-level rows without
  coordinates.

## What I looked at first

PJM has no API for committee documents and no index of past decks, so the year drop-down's form post is
the only listing. `pdfplumber` reads the slides without OCR. The substation matching reuses #190's
method; the lines check reuses `hifld-grid-gaps/`'s HIFLD Next URLs.
