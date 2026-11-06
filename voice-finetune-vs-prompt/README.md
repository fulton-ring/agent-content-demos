# Fine-tuning vs prompting for our writing voice

Issue: [#202](https://github.com/fulton-ring/agent-content-demos/issues/202). Does a model fine-tuned on what we
publish write in our voice better than a strong prompt with examples?

## What it shows

The fine-tune never got started. **fultonring.com has 13 published pieces** (about 21,000 words). Style
fine-tuning guides cite a few hundred examples, so as the issue says, the spike stops at the two prompting arms:

- **A.** Qwen 3.8 27B, an open-weight model, with our voice guide.
- **B.** The same model and guide, plus all 9 training pieces as examples.

The 4 most recent pieces are held out. For each one, a helper model (Gemini 3.8 Flash) writes a neutral brief: the
topic, the reader and the facts, with none of the piece's wording. Each arm writes 3 drafts from each brief, which
gives 12 blind A-vs-B pairs for a founder to judge. The notebook also counts factual errors per draft, counts the
off-voice tells the guide bans, and has the helper model judge the pairs as a stand-in until the founder picks.

## Results

RESULTS

## How to run it

```sh
./run.sh                    # rescore from the saved answers in output/: no model calls, no key
VOICE_REFRESH=1 ./run.sh    # call the models again
uv run marimo edit voice.py # read the notebook with its outputs
```

`VOICE_REFRESH=1` needs `OPENROUTER_API_KEY` and the voice guide. The guide is our internal *Marketing Voice &
Ad-Copy Guide*. It isn't public, so it isn't committed: put its text in `private/voice_guide.md` (gitignored), or
point `VOICE_GUIDE_PATH` at it. The run used the guide's rules sections without its illustrative example passages,
so that arm A sees no examples at all. A full refresh costs about COST and takes about MINUTES minutes.

To score the founder's picks, read `review/pairs.md`, then write `review/picks.json` as
`{"1": "left", "2": "right", "3": "tie", ...}` and run `./run.sh`. `review/key.json` says which arm is which. Don't
open it first.

## Where the data comes from

- The 13 pieces are fetched from [fultonring.com](https://fultonring.com/blog/) on every run, from its sitemap. They
  aren't committed. A piece counts if its page has a `datePublished`; the blog's index pages don't.
- `output/briefs.json`, `output/drafts.json`, `output/factcheck.json` and `output/judge.json` are the saved model
  answers, each with its cost (as OpenRouter reports it) and time.
- `review/pairs.md` and `review/key.json` are the blind pairs and their key.

## What it doesn't show

- **Whether fine-tuning would win with enough data.** Arm C wasn't run. This shows only that our own site's 13 pieces
  aren't enough to try it on. LinkedIn posts or Buffer history might reach a few hundred, but the issue limited the
  training data to fultonring.com.
- **Small differences.** 12 pairs from 4 test pieces can only show a large gap between A and B.
- **Other writer models.** One open model was tested. A stronger closed model might close the gap or widen it.
- **Ground truth for errors and voice.** The fact check and the provisional judge are one model's opinion. The
  founder's blind picks and a spot-check of the fact lists are the real scores.

## What I looked at first

Pydantic AI for typed model calls, with OpenRouter's own per-call cost. trafilatura to pull article text out of
the pages. No fine-tuning service was used.
