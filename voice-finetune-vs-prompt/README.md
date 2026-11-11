# Fine-tuning vs prompting for our writing voice

Issue: [#202](https://github.com/fulton-ring/agent-content-demos/issues/202). Does a model fine-tuned on what we
publish write in our voice better than a strong prompt with examples?

## What it shows

The fine-tune never got started. **fultonring.com has 12 published pieces** (5 articles and 7 whitepapers, 19,178
words). Style fine-tuning guides cite a few hundred examples, so as the issue says, the spike stops at the two
prompting arms:

- **A.** Qwen 3.8 27B, an open-weight model, with our voice guide.
- **B.** The same model and guide, plus all 8 training pieces as examples (about 17,000 extra input tokens).

The 4 most recent pieces are held out. For each one, a helper model (Gemini 3.8 Flash) writes a neutral brief: the
topic, the reader and the facts, with none of the piece's wording. Each arm writes 3 drafts from each brief, which
gives 12 blind A-vs-B pairs for a founder to judge. The notebook also counts factual errors per draft, counts the
off-voice tells the guide bans, and has the helper model judge the pairs as a stand-in until the founder picks.

## Results

From the run committed here (`./run.sh` prints the same from the saved answers):

| | A: guide only | B: guide + 8 examples |
|---|---|---|
| Drafts | 12 | 12 |
| Founder's blind picks | pending | pending |
| Provisional judge, pairs won (12 pairs) | 2 | 6 (4 ties) |
| Factual errors per draft | 0.58 | 0.67 |
| Drafts with no factual errors | 8 | 7 |
| Off-voice tells per draft (real pieces: 0.42) | 0.25 | 0.00 |
| Cost per draft | $0.0029 | $0.0042 |
| Seconds per draft | 18.9 | 14.7 |
| Training run | not run | not run |

- **Data:** 12 pieces, split 8 train and 4 test (the 4 most recent, 2026-10-12 to 2026-11-02).
- **Provisional judge:** B won 6 pairs, A won 2, and 4 were ties (the judge disagreed with itself when the sides
  were swapped). A sign test on 6 to 2 gives p = 0.29, so 12 pairs can't separate the arms. The founder's picks
  are the real score.
- **Cost:** $0.255 for drafts, fact checks and judging, plus $0.037 for the briefs. Prompting is cheap whichever
  arm wins: the 8 examples add $0.0013 per draft.
- **Failure cases, arm B:** examples carry facts across. 3 of B's 12 drafts call HIFLD Next "the project we
  engineered with Public Environmental Data Partners". That line comes from the training pieces, not the brief.
  It may be true, but nobody asked for it in a piece about NFIP or hospitals.
- **Failure cases, arm A:** with no examples to borrow from, A's errors were wrong dates and causes. It moved the
  Medicare incident "two months later", turned a 338-vs-203 bed gap into "a 335-Bed Discrepancy", and said HIFLD Open's shutdown "removed the
  channel" for reporting errors when the brief says there never was one. 3 of A's drafts use the "it's not X,
  it's Y" construction the guide bans. B's drafts use none. Our own 12 pieces average 0.42 of these tells each, so
  the count is a rough signal, not a rule we keep perfectly.
- **Length:** both arms ignored the 700-word cap on the longest brief (A wrote about 1,100 words).

## How to run it

```sh
./run.sh                    # rescore from the saved answers in output/: no model calls, no key
VOICE_REFRESH=1 ./run.sh    # call the models again
uv run marimo edit voice.py # read the notebook with its outputs
```

`VOICE_REFRESH=1` needs `OPENROUTER_API_KEY` and the voice guide. The guide is our internal *Marketing Voice &
Ad-Copy Guide*. It isn't public, so it isn't committed: put its text in `private/voice_guide.md` (gitignored), or
point `VOICE_GUIDE_PATH` at it. The run used the guide's rules sections without its illustrative example passages,
so that arm A sees no examples at all. A full refresh costs about $0.30 and takes about 2 minutes.

To score the founder's picks, read `review/pairs.md`, then write `review/picks.json` as
`{"1": "left", "2": "right", "3": "tie", ...}` and run `./run.sh`. `review/key.json` says which arm is which. Don't
open it first.

## Where the data comes from

- The 12 pieces are fetched from [fultonring.com](https://fultonring.com/blog/) on every run, from its sitemap. They
  aren't committed. A piece counts if its page has a `datePublished`; the blog's index pages don't.
- `output/briefs.json`, `output/drafts.json`, `output/factcheck.json` and `output/judge.json` are the saved model
  answers, each with its cost (as OpenRouter reports it) and time.
- `review/pairs.md` and `review/key.json` are the blind pairs and their key.

## What it doesn't show

- **Whether fine-tuning would win with enough data.** Arm C wasn't run. This shows only that our own site's 12 pieces
  aren't enough to try it on. LinkedIn posts or Buffer history might reach a few hundred, but the issue limited the
  training data to fultonring.com.
- **Small differences.** 12 pairs from 4 test pieces can only show a large gap between A and B.
- **Other writer models.** One open model was tested. A stronger closed model might close the gap or widen it.
- **Ground truth for errors and voice.** The fact check and the provisional judge are one model's opinion. The
  founder's blind picks and a spot-check of the fact lists are the real scores.

## What I looked at first

Pydantic AI for typed model calls, with OpenRouter's own per-call cost. trafilatura to pull article text out of
the pages. No fine-tuning service was used.
