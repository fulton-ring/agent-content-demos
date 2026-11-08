# Can a second AI pass catch the errors in our research agent's notes?

Our research pipeline writes notes on Notion cards, and review jobs log what those notes got wrong
([#108](https://github.com/fulton-ring/agent-content-demos/issues/108) counted 290 errors in 8 types). This spike
replays those errors against three AI checkers that re-read the source, alongside claims that passed review, and
measures what each checker catches, what it misses and what it flags wrongly. Issue:
[#227](https://github.com/fulton-ring/agent-content-demos/issues/227).

## Run it

```bash
./run.sh
```

You need [uv](https://docs.astral.sh/uv/). The checker answers are committed in `answers/`, so a run from a clean
checkout rescores everything without calling a model. Set `OPENROUTER_API_KEY` only if you delete answers or add
claims. The dreaming checker refetches its full sources into `sources/`, which isn't committed.

To try it on your own agent, write your claims as `data/test_set.jsonl` (`id`, `kind` error or pass,
`error_type`, `claim`, `source_url`, `source_title`, `passage`, `wording`, `doubt`) and run notebooks 2 and 3.

| Notebook | What it does |
|---|---|
| `1_test_set.py` | Builds the test set from the logged errors and the passing claims, and counts what couldn't be replayed |
| `2_checkers.py` | Runs the three checkers (Pydantic AI, typed output, OpenRouter) and saves every answer with its cost and time |
| `3_results.py` | Recall and false alarms by type with Wilson intervals, the errors let through, cross-provider differences, cost |

## The data

- **Logged errors:** the 88 errors from the 2026-10-08 re-check, listed one per row on #108. Notion keeps no page
  history from before 2026-10-08, so the notes' original text is gone. Research subagents rebuilt each claim from
  its correction: 27 reuse the old words the correction quotes, and 48 are reconstructed from what it says was
  wrong. They then fetched the cited source and copied the passage the claim is about.
- **Passing claims:** `random.Random(227)` drew 36 of the 72 cards our reviewer accepted. From each, a subagent took
  up to six claims that cite one outside public source. That gave 151 candidates, 138 of them usable, and the same
  seed drew 75 to match the errors.
- **What's committed:** the claims, source URLs and passages of 30 to 150 words (`data/`), plus every checker answer
  (`answers/`). Full source pages are fetched at run time and not committed.

## Results

From `./run.sh`; the tables are in `results/` and in each notebook's output.

**Replay.** 76 of the 88 logged errors could be replayed. 5 had lost their wording (the correction says only "the
link was wrong"), 2 were videos with no transcript, 1 source was paywalled, 1 was internal product thinking, and 3
were other cases: a video date we couldn't read, an upload date YouTube wouldn't serve, and a README that has since
changed. One more (E21) was dropped because the correction itself looks wrong: the source does say what the note
claimed. That leaves **75 errors + 75 passing claims**. The full-source checker could refetch the same page for 103
of the 150; the others were blocked (28) or had changed (19).

**Recall** (caught / errors, 95% Wilson interval):

| Error type | Claude, passage | GPT, passage | Claude, full source |
|---|---|---|---|
| claim as fact (overstatement) | 15/15 (80–100%) | 15/15 (80–100%) | 11/11 (74–100%) |
| not in source | 13/13 (77–100%) | 13/13 (77–100%) | 9/10 (60–98%) |
| wrong figure | 12/12 (76–100%) | 12/12 (76–100%) | 9/9 (70–100%) |
| missed context | **7/11 (35–85%)** | **9/11 (52–95%)** | **7/9 (45–94%)** |
| wrong date | 9/9 (70–100%) | 9/9 (70–100%) | 5/5 (57–100%) |
| misattribution | 9/9 (70–100%) | 9/9 (70–100%) | 5/5 (57–100%) |
| overgeneralized | 5/5 (57–100%) | 4/5 (38–96%) | 2/2 (34–100%) |
| wrong source | 1/1 | 1/1 | 1/1 |
| **all errors** | **71/75 = 95% (87–98%)** | **72/75 = 96% (89–99%)** | **49/52 = 94% (84–98%)** |
| **flagged passing claims** | 52/75 = 69% (58–79%) | 54/75 = 72% (61–81%) | 30/51 = 59% (45–71%) |

**Are the flagged passing claims false alarms?** Not mostly. We read all 30 passing claims the full-source checker
flagged (`data/false_alarm_review.jsonl`). 16 have a real problem our reviewer missed: a quote credited to the wrong
body, a share of one subset reported as a share of everything, a detail the source doesn't contain. 12 are nits,
mostly dates that are on the page but missing from the text we extracted. In 2 the checker was wrong. So **about
31% of the sampled passing claims (16/51, 20–45%) had a real error**, and 27% (14/51, 17–41%) were flagged without
one. The passage checkers flag more because many passing claims' passages cover only part of the claim, so they
answer "not in source".

**Cross-provider.** Same claims, passage and prompt: GPT caught 2 errors Claude missed, and Claude caught 1 that GPT
missed. On these errors that's no measurable difference.

**Cost and time per claim.** Passage checkers $0.003 and 3–4 s. Full source $0.012 and 2.4 s. The whole run cost
$2.12 of the $5 budget.

## What it shows

- **The argument is wrong on overstatement.** We expected a re-check to miss "claims stated more strongly than the
  source allows". Every checker caught all 15. What slips through is **missed context**: a claim that's literally
  true and leaves out what changes its meaning (that the $800 million order was a copper mine's, or that a forecast
  system was an intern's research demo). Of the 7 errors any checker let through, 5 are that type.
- **Every checker catches nearly everything** we logged (94–96%), which the issue says would make the argument
  wrong. But this is an easy test (see below), and the checkers get their recall by being strict: they flag
  60–70% of what passed review.
- **A same-family and a cross-provider checker behave alike** on these claims. The cross-provider question needs
  errors no Claude checker found, which this log doesn't contain.
- **The checker's best use is on what passed.** On a random sample of accepted claims, a full-source re-check
  turned up a real error in roughly one claim in three, and most of its other flags were cheap to dismiss.

## Judgement calls

- **Overstatement and attribution.** A claim like "54% of PDFs don't need OCR" when the source is Firecrawl saying
  so counts as an error (vendor claim written as fact), even though the number is on the page.
- **Missed context.** Scored as caught only when the checker flags the claim. A checker that names a different
  problem still counts. Only 41–46% of catches named the type our log gave, so the types are a guide, not a
  label to grade against.
- **Disputed corrections.** Where the subagent found the source supports the "error" (E21), we left it out. Two
  others are borderline and kept, with notes: E23 ("turbines" for generators) and E30 (a post dated late on Oct 3,
  logged as Oct 4).
- **The false-alarm review** is one reader's call, by the same kind of model that ran the checks. The reasons are in
  the file, so anyone can disagree item by item.

## What it doesn't show

- **The passages were picked by someone who knew the answer**, and 48 of 75 claims were reworded from the
  correction. Recall on reworded claims (92–96%) is no higher than on quoted ones (95–100%), and the full-source
  checker, which finds the relevant part itself, scores about the same. Still, a real checker sees the note as
  written, in a long card, with nothing pointing at the claim.
- **The checker was told the 8 types to look for.** That helps it.
- **The log only holds errors a Claude checker already found**, so it can't show what all of them miss. The passing
  claims are the better test of that, and that's where the checkers found most.
- **Only the 88 errors from 2026-10-08.** The 202 later source errors on #108 were never published item by item.
  Replaying them means re-extracting them from the issues and cards (sub-issue #235).
- **"Dreaming" here is a full-source reread, without the card history the card asked for**, because a card's later
  history contains the correction itself. We used Sonnet 5.5, not the larger Claude the pipeline runs on, to stay in
  budget.

## What we looked at first

Pydantic AI's typed outputs over OpenRouter (as in `fema-nrc-extraction-accuracy/`), trafilatura for page text,
pypdfium2 for PDFs, and statsmodels for Wilson intervals. We wrote only the replay harness and the scoring.
