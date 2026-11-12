# Can a second AI pass catch the errors in our research agent's notes?

Our research pipeline writes notes on Notion cards, and review jobs log what those notes got wrong
([#108](https://github.com/fulton-ring/agent-content-demos/issues/108) counted 290 errors in 8 types). This spike
replays those errors against three AI checkers that re-read the source, alongside claims that passed review, and
measures what each checker catches, what it misses and what it flags wrongly. Issues:
[#227](https://github.com/fulton-ring/agent-content-demos/issues/227) (the first 88 errors) and
[#235](https://github.com/fulton-ring/agent-content-demos/issues/235) (the later errors).

## Run it

```bash
./run.sh
```

You need [uv](https://docs.astral.sh/uv/). The checker answers are committed in `answers/`, so a run from a clean
checkout rescores everything without calling a model. Set `OPENROUTER_API_KEY` only if you delete answers or add
claims. The dreaming checker refetches its full sources into `sources/`, which isn't committed.

To try it on your own agent, write your claims as `data/test_set.jsonl` (`id`, `kind` error or pass, `error_type`,
`claim`, `source_url`, `source_title`, `passage`, `wording`, `doubt`) and run notebooks 2 and 3.

| Notebook | What it does |
|---|---|
| `1_test_set.py` | Builds the test set from both batches of logged errors and the passing claims, and counts what couldn't be replayed |
| `2_checkers.py` | Runs the three checkers (Pydantic AI, typed output, OpenRouter) and saves every answer with its cost and time |
| `3_results.py` | Recall by type and batch with Wilson intervals, false alarms, the errors let through, cross-provider differences, cost |

## The data

- **Logged errors:** the 88 errors from the 2026-10-08 re-check, listed one per row on #108. Notion keeps no page
  history from before 2026-10-08, so the notes' original text is gone. Research subagents rebuilt each claim from its
  correction: 27 reuse the old words the correction quotes, and 48 are reconstructed from what it says was wrong.
  They then fetched the cited source and copied the passage the claim is about.
- **Later errors (#235):** the fixes review jobs made from 2026-10-08 to 2026-10-22. #108's extraction was lost, so
  subagents re-extracted every fix from the issues, spike PRs and 178 cards as they stood at #108's count
  (`data/later_extraction.jsonl`, 1,197 fixes, #108's codes). For the 444 against a document source they grouped
  repeats (147), read each card **just before the fix** in Notion's page history to recover the note's own words, and
  copied the source passage (`data/later_errors.jsonl`).
- **Passing claims:** `random.Random(227)` drew 36 of the 72 cards our reviewer accepted. From each, a subagent took
  up to six claims that cite one outside public source. That gave 151 candidates, 138 of them usable, and the same
  seed drew 75 to match the errors.
- **What's committed:** the claims, source URLs and passages of 30 to 150 words (`data/`), plus every checker answer
  (`answers/`). Full source pages are fetched at run time and not committed.

## Results

From `./run.sh`; the tables are in `results/` and in each notebook's output.

**Replay.** 76 of the 88 first-batch errors could be replayed. 5 had lost their wording, 2 were videos, 1 was
paywalled, 1 was internal, and 3 were other cases (two video dates, a README that has since changed). One more (E21)
was dropped because the source does say what the note claimed. That leaves **75 errors + 75 passing claims**. The
full-source checker could refetch the same page for 104 of the 150 (one more than in #227, after PC04-3's PDF fetched
in the #235 run); the others were blocked or had changed.

**Later errors.** 297 distinct errors against a document source (#108 counted 202). 58 turned out on a closer read
not to be document-source errors (a fix about our own catalog or spike, a check item where nothing was wrong), 37 had
no single passage to check (a caution with no wrong wording, a claim resting on our own search, a stand-in source), 3
had lost their wording, 3 were videos, 3 blocked, 2 offline, 1 private. Of the 190 replayable, 20 were left out
because the source supports the note. **170 kept, 161 in the note's own words** (27 of 75 in the first).

**Recall**, each cell "first batch · later batch" (caught / errors; 95% Wilson intervals on the totals and in
`results/recall.md` and `results/recall_later.md`):

| Error type | Claude, passage | GPT, passage | Claude, full source |
|---|---|---|---|
| claim as fact (overstatement) | 15/15 · 25/27 | 15/15 · 25/27 | 11/11 · **13/17** |
| not in source | 13/13 · 16/16 | 13/13 · 16/16 | 9/10 · 14/14 |
| wrong figure | 12/12 · 7/7 | 12/12 · 7/7 | 9/9 · 4/4 |
| missed context | **7/11** · 66/67 | **9/11** · 66/67 | **7/9** · 45/48 |
| wrong date | 9/9 · 9/10 | 9/9 · 9/10 | 5/5 · 9/9 |
| misattribution | 9/9 · 16/16 | 9/9 · 15/16 | 5/5 · 10/11 |
| overgeneralized | 5/5 · 22/22 | 4/5 · 22/22 | 2/2 · 18/18 |
| wrong source | 1/1 · 5/5 | 1/1 · 5/5 | 1/1 · 4/4 |
| **all errors, first batch** | **71/75 = 95% (87–98%)** | **72/75 = 96% (89–99%)** | **49/52 = 94% (84–98%)** |
| **all errors, later batch** | **166/170 = 98% (94–99%)** | **165/170 = 97% (93–99%)** | **117/125 = 94% (88–97%)** |
| **flagged passing claims** | 52/75 = 69% (58–79%) | 54/75 = 72% (61–81%) | 31/52 = 60% (46–72%) |

By who caught them, recall is flat: 96–99% on passages whether a worker, the manager or the Draft job (after the
manager passed the card) found the error. Of the 4 both passage checkers let through, 3 are debatable fixes: the
statute does allow "up to 90%", the article itself gives "about 200,000 strikes", and GAO gives both dates.

**Are the flagged passing claims false alarms?** Not mostly. We read all 31 passing claims the full-source checker
flagged (`data/false_alarm_review.jsonl`). 16 have a real problem our reviewer missed: a quote credited to the wrong
body, a share of one subset reported as a share of everything, a detail the source doesn't contain. 13 are nits,
mostly dates that are on the page but missing from the text we extracted. In 2 the checker was wrong. So **about 31%
of the sampled passing claims (16/52, 20–44%) had a real error**, and 29% (15/52, 18–42%) were flagged without one;
one more passing claim's PDF fetched in the #235 run, so these are one higher than #227 reported. The passage
checkers flag more because many passing claims' passages cover only part of the claim.

**Cross-provider.** Same claims, passage and prompt: on the first batch GPT caught 2 errors Claude missed and Claude
caught 1 that GPT missed; on the later batch, 0 and 1. On these errors that's no measurable difference.

**Cost and time per claim.** Passage checkers $0.003 and 3–4 s. Full source $0.014 and 2.4 s. The first batch cost
$2.12 of its $5 budget in #227 and the later batch $2.91 of its $3 (all committed answers total $5.06, printed by
notebook 2), which left nothing for passing claims to match it (see
below). The times are wall-clock with 8 calls running at once, so they reflect provider load more than the checker;
don't compare them across checkers.

## What it shows

- **The argument is wrong on overstatement.** We expected a re-check to miss "claims stated more strongly than the
  source allows". Every checker caught all 15. What slips through is **missed context**: a claim that's literally
  true and leaves out what changes its meaning (that the $800 million order was a copper mine's, or that a forecast
  system was an intern's research demo). In the first batch, of the 7 errors any checker let
  through, 5 are that type.
- **The later errors don't confirm that blind spot.** On 170 errors caught after an earlier check had passed the
  card, the passage checkers caught 66 of 67 missed-context errors. What the later batch adds is that the full-source
  checker is weaker on overstatement (13/17, 53–90%) than the passage checkers (25/27), perhaps because a whole page
  holds more sentences that sound like the claim. With these counts that's a lead, not a finding.
- **Every checker catches nearly everything** we logged (94–98% across both batches), which the issue says would make
  the argument wrong. But this is an easy test (see below), and the checkers get their recall by being strict: they
  flag 60–70% of what passed review.
- **A same-family and a cross-provider checker behave alike.** Testing that needs errors no Claude checker found.
- **The checker's best use is on what passed.** On a random sample of accepted claims, a full-source re-check turned
  up a real error in roughly one claim in three, and most of its other flags were cheap to dismiss.

## Judgement calls

- **Overstatement and attribution.** A claim like "54% of PDFs don't need OCR" when the source is Firecrawl saying so
  counts as an error (vendor claim written as fact), even though the number is on the page.
- **Missed context.** Scored as caught only when the checker flags the claim. A checker that names a different
  problem still counts. Only 25–30% of catches across both batches named the type our log gave, so the types are a
  guide, not a label to grade against.
- **Disputed corrections.** Where the subagent found the source supports the "error" (E21, and 20 later errors with
  the reason in `data/later_errors.jsonl`), we left it out. Two others are borderline and kept, with notes: E23
  ("turbines" for generators) and E30 (a post dated late on Oct 3, logged as Oct 4).
- **The false-alarm review** is one reader's call, by the same kind of model that ran the checks. The reasons are in
  the file, so anyone can disagree item by item.

## What it doesn't show

- **The passages were picked by someone who knew the answer**, and 48 of 75 claims were reworded from the correction.
  Recall on reworded claims (92–96%) is no higher than on quoted ones (95–100%), and the full-source checker, which
  finds the relevant part itself, scores about the same. Still, a real checker sees the note as written, in a long
  card, with nothing pointing at the claim.
- **The checker was told the 8 types to look for.** That helps it.
- **The log only holds errors a Claude checker already found**, so it can't show what all of them miss. The passing
  claims are the better test of that, and that's where the checkers found most.
- **The later batch has no passing claims of its own.** Its errors used the $3 budget, so false alarms come from the
  first batch's 75 passing claims; 63 unused candidates are ready in `data/passing_candidates.jsonl` (set
  `N_LATER_PASSES` in notebook 1). And its passages were also cut by agents who had read the fix, which for missed
  context means the passage holds exactly the context the note left out. That may be why recall there is so high.
- **The re-extraction isn't #108's:** 297 errors to its 202, with subagents' own duplicate and coding calls.
- **"Dreaming" here is a full-source reread, without the card history the card asked for**, because a card's later
  history contains the correction itself. We used Sonnet 5.5, not the larger Claude the pipeline runs on, to stay in
  budget.

## What we looked at first

Pydantic AI's typed outputs over OpenRouter (as in `fema-nrc-extraction-accuracy/`), trafilatura for page text,
pypdfium2 for PDFs, and statsmodels for Wilson intervals. We wrote only the replay harness and the scoring.
