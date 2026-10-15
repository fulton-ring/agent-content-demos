# A one-page nonprofit AI use policy from one short call

Spike for [issue #16](https://github.com/fulton-ring/agent-content-demos/issues/16) ([proposal card](https://app.notion.com/p/3f7cc69045cb817ea12dcac615764e5e)): can a short, plain AI use policy, drafted after one 30-minute call, give a nonprofit's board something real to react to?

**Every organization, person and call in this folder is invented.** No real nonprofit was interviewed and no real nonprofit has reviewed these policies.

## What's here

- [`template/policy-template.md`](template/policy-template.md): the blank one-page template ([PDF](output/template/policy-template.pdf)).
- [`template/call-questions.md`](template/call-questions.md): the six questions we ask on the call, each mapped to the sections it fills ([PDF](output/template/call-questions.pdf)).
- [`calls/`](calls): four mock call transcripts, each labelled as invented:
  - Cedar Valley Family Center, a mid-sized family services nonprofit and the main sample;
  - Northgate Community Food Bank;
  - Bright Futures After School;
  - Eastside Community Health Clinic.
- `output/<organization>/policy.{json,html,pdf}`: the policy drafted from each call. Also `output/checks.md` with the checks, `output/side-by-side.md` with how the policies differ, and `output/published-comparison.md` with length and reading level against published policies.
- [`screenshots/`](screenshots): a PNG of each policy, the template and the questions.
- [`prompts/`](prompts): the two prompts sent to the model, committed as run.
- [`review/`](review): an independent statement-by-statement check of the policies against their calls.
- `src/policy_builder/`: the code.

## How to run it

You need [uv](https://docs.astral.sh/uv/) and an OpenRouter key. A full run makes four to eight model calls and costs about $0.50.

```sh
cd nonprofit-ai-use-policy
uv sync
uv run playwright install chromium   # skip if you set CHROMIUM_PATH to a Chromium you already have
export OPENROUTER_API_KEY=...
uv run build-policies
```

That one command does all of this:

1. Renders the blank template and the call questions to HTML and PDF.
2. Fills the template from each file in `calls/` with one typed model call: Pydantic AI, `anthropic/claude-sonnet-5.5` through OpenRouter, temperature 0. The output is validated against the `Policy` schema in `src/policy_builder/schema.py`, and Pydantic AI retries when validation fails.
3. Prints each policy to a Letter PDF with Chromium. If it spills onto a second page, it asks the model to cut it down (`prompts/shorten-policy.md`), at most twice.
4. Checks each policy: pages, how full the page is, reading grade, whether every template section is filled, names that don't appear in the call, time and cost.
5. Downloads the published templates listed under Sources and measures them the same way. The PDFs are cached in `.cache/`, which is not committed. Pass `--skip-published` to skip this step.

Useful options:

- `uv run build-policies calls/your-call.md` drafts from one transcript or answers file. Any text file works, and the questions file says what it needs to cover.
- `--reuse` re-renders and re-checks the saved policies without calling the model.
- `--model` picks a different OpenRouter model.

The readability check fetches the CMU Pronouncing Dictionary through NLTK the first time it runs. Behind a proxy, NLTK refuses this unless you set `NLTK_ALLOW_PROXIED_URLOPEN=1`.
