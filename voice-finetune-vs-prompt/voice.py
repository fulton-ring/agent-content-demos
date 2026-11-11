import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")

with app.setup:
    import json
    import math
    import os
    import random
    import re
    import time
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date
    from pathlib import Path
    from typing import Any, Literal

    import httpx
    import marimo as mo
    import trafilatura
    from pydantic import BaseModel, Field, TypeAdapter
    from pydantic_ai import Agent, capture_run_messages
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models.openrouter import OpenRouterModelSettings

    HERE = Path(__file__).parent
    OUT = HERE / "output"
    REVIEW = HERE / "review"
    GUIDE = Path(os.environ.get("VOICE_GUIDE_PATH", HERE / "private" / "voice_guide.md"))
    WRITER = "openrouter:qwen/qwen3.8-27b"  # open weights: the model we'd LoRA if there were enough data
    HELPER = "openrouter:google/gemini-3.8-flash"  # writes the briefs, checks facts, and is the provisional judge
    FEW_HUNDRED = 200  # the low end of "a few hundred", the range style fine-tuning guides cite
    TEST_PIECES = 4
    SAMPLES = 3  # drafts per arm per brief, so the founder judges 12 pairs instead of 4


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Does a model fine-tuned on our writing beat a good prompt?

    The question from [issue #202](https://github.com/fulton-ring/agent-content-demos/issues/202): if we fine-tune a
    model on what we publish, does it write in our voice better than a strong prompt with examples? The fair
    comparison is fine-tuning against few-shot prompting, not fine-tuning against nothing, because public guidance
    says few-shot often matches fine-tuning for style.

    The plan had three arms on the same held-out briefs:

    - **A.** An open model with our voice guide.
    - **B.** The same, plus our published pieces as examples.
    - **C.** A LoRA fine-tune of the same open model on the training pieces.

    The issue says to count the examples first, and if there are far fewer than a few hundred, to stop at A and B.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. Collect what we've published

    The site's sitemap lists every page. Every blog post carries a `datePublished`, and the index pages
    (`/blog/articles/`, `/blog/whitepapers/` and so on) don't, so that's how we tell them apart.
    [trafilatura](https://trafilatura.readthedocs.io) pulls the article text out of each page as Markdown.
    Nothing is saved to the repo: the pieces are fetched fresh on every run.
    """)
    return


@app.cell
def _():
    _sitemap = httpx.get("https://fultonring.com/sitemap-0.xml", timeout=30)
    _sitemap.raise_for_status()
    _urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", _sitemap.text) if "/blog/" in u]
    assert 0 < len(_urls) < 500, f"unexpected sitemap: {len(_urls)} blog URLs"

    pieces = []
    for _url in _urls:
        _page = httpx.get(_url, timeout=30)
        _page.raise_for_status()
        _published = re.search(r'"datePublished":"(\d{4}-\d{2}-\d{2})', _page.text)
        if _published is None:
            continue  # an index page, not a post
        _title = re.search(r'"headline":"([^"]+)"', _page.text) or re.search(r"<title>([^<|]+)", _page.text)
        _text = trafilatura.extract(_page.text, output_format="markdown", include_formatting=True)
        assert _title and _text, f"could not read {_url}"
        pieces.append(
            {
                "url": _url,
                "title": _title.group(1).strip(),
                "published": date.fromisoformat(_published.group(1)),
                "text": _text,
                "words": len(_text.split()),
            }
        )
    pieces.sort(key=lambda p: p["published"])
    mo.ui.table(
        [{k: p[k] for k in ("published", "words", "title")} for p in pieces],
        selection=None,
    )
    return (pieces,)


@app.cell
def _(pieces):
    mo.md(f"""
    **{len(pieces)} published pieces, {sum(p["words"] for p in pieces):,} words in all**, from
    {pieces[0]["published"]} to {pieces[-1]["published"]}. Style fine-tuning guides cite a few hundred examples
    (we use {FEW_HUNDRED} as the low end). {len(pieces)} is {"far fewer" if len(pieces) < FEW_HUNDRED / 4 else "fewer"},
    so we stop at arms A and B, as the issue says. Cutting each piece into paragraphs would make more rows, but
    they'd be the same {len(pieces)} pieces on the same topics, and a fine-tune would mostly learn the topics.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. Hold out the most recent pieces

    The newest pieces are the test set, chosen before any model sees anything. Neither arm ever sees them. The rest
    are the training set: arm B gets all of them as examples, since there are fewer than the 5 to 20 the issue
    allows.
    """)
    return


@app.cell
def _(pieces):
    test, train = pieces[-TEST_PIECES:], pieces[:-TEST_PIECES]
    assert not {p["url"] for p in test} & {p["url"] for p in train}
    mo.md(
        f"**Train: {len(train)} pieces. Test: {len(test)} pieces**, published {test[0]['published']} to "
        f"{test[-1]['published']}:\n\n" + "\n".join(f"- {p['title']} ({p['words']:,} words)" for p in test)
    )
    return test, train


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. Model calls, typed and saved

    Every model call goes through Pydantic AI with a typed output, and its answer is saved in `output/` with its cost
    (OpenRouter reports the cost of each call) and time. A run with the saved answers in place makes no calls, so a
    reviewer can rescore from a clean checkout for free. Set `VOICE_REFRESH=1` to call the models again.
    """)
    return


@app.cell
def _():
    def call_model(model: str, output_type: Any, instructions: str, prompt: str, temperature: float) -> dict:
        """One typed model call, retried on errors up to 4 times. Returns the output with its cost and time."""
        assert temperature >= 0 and prompt, "bad call"
        agent = Agent(
            model,
            output_type=output_type,
            instructions=instructions,
            retries=2,
            model_settings=OpenRouterModelSettings(
                temperature=temperature,
                max_tokens=16000,
                thinking=False if model == WRITER else "low",  # the writer drafts directly, as a fine-tune would
                openrouter_usage={"include": True},
            ),
        )
        for attempt in range(4):
            started = time.time()
            with capture_run_messages() as messages:
                try:
                    output = agent.run_sync(prompt).output
                except Exception as error:  # rate limits, network errors, malformed output after retries
                    if attempt == 3:
                        raise
                    print(f"  retrying after {type(error).__name__}: {str(error)[:120]}")
                    time.sleep(10 * (attempt + 1))
                    continue
            responses = [m for m in messages if isinstance(m, ModelResponse)]
            costs = [(m.provider_details or {}).get("cost") for m in responses]
            assert all(c is not None for c in costs), "OpenRouter did not report a cost"
            return {
                "output": TypeAdapter(output_type).dump_python(output, mode="json"),
                "usd": sum(float(c or 0) for c in costs),
                "seconds": round(time.time() - started, 1),
                "input_tokens": sum(m.usage.input_tokens for m in responses),
                "output_tokens": sum(m.usage.output_tokens for m in responses),
            }
        raise AssertionError("unreachable")

    def saved(name: str, make: Any) -> Any:
        """Load output/<name>.json, or make it and save it when it's missing or VOICE_REFRESH is set."""
        path = OUT / f"{name}.json"
        if path.exists() and not os.environ.get("VOICE_REFRESH"):
            return json.loads(path.read_text())
        result = make()
        OUT.mkdir(exist_ok=True)
        path.write_text(json.dumps(result, indent=1, default=str))
        return result

    return call_model, saved


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. A neutral brief for each test piece

    Both arms write from the same brief: the topic, the reader, and the facts the piece states, written as plain
    notes with no sentences from the original. That way the drafts differ in voice, not in what they know. The
    helper model writes the briefs, and the fact check later uses them.
    """)
    return


@app.cell
def _(call_model, saved, test):
    class Brief(BaseModel):
        topic: str = Field(description="One sentence: what the piece is about")
        reader: str = Field(description="Who it's for")
        facts: list[str] = Field(
            description="Every concrete fact the piece states (numbers, names, datasets, steps, findings, "
            "limits), each as a short neutral note. Don't copy its sentences or phrasing."
        )

    def _make_briefs() -> list[dict]:
        def brief(p: dict) -> dict:
            return call_model(
                HELPER,
                Brief,
                "You turn a published article into a neutral writer's brief. Keep every fact, drop all voice.",
                f"# {p['title']}\n\n{p['text']}",
                temperature=0,
            ) | {"url": p["url"], "title": p["title"], "words": p["words"]}

        with ThreadPoolExecutor(6) as pool:
            return list(pool.map(brief, test))

    briefs = saved("briefs", _make_briefs)
    assert [b["url"] for b in briefs] == [p["url"] for p in test], "saved briefs are for a different test set"
    mo.md(f"First brief, for *{briefs[0]['title']}*:\n\n```json\n{json.dumps(briefs[0]['output'], indent=1)}\n```")
    return (briefs,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. Draft each piece with arms A and B

    The writer is Qwen 3.8 27B, an open-weight model small enough to LoRA on one GPU, so it's the model arm C would
    have trained. Both arms get the same instructions and the voice guide (its rules, without the guide's own
    example passages, so arm A sees no examples at all). Arm B also gets the full text of every training piece.
    Each arm writes 3 drafts per brief at temperature 0.8, so there are 12 pairs to judge rather than 4. Drafts are
    capped at 700 words so the founder can read 24 of them.
    """)
    return


@app.cell
def _(briefs, call_model, saved, train):
    class Draft(BaseModel):
        title: str
        body: str = Field(description="The piece in Markdown, without the title")

    def _make_drafts() -> list[dict]:
        assert GUIDE.exists(), f"the voice guide is read from {GUIDE} (set VOICE_GUIDE_PATH); it isn't committed"
        guide = GUIDE.read_text()
        base = (
            "You write blog posts for fultonring.com, the site of Fulton Ring, a small data consulting firm. "
            "Write in the company's voice, following this guide.\n\n" + guide
        )
        examples = "\n\n".join(f"<example>\n# {p['title']}\n\n{p['text']}\n</example>" for p in train)
        arms = {
            "A": base,
            "B": base + "\n\nThese are pieces we've published. Match how they sound.\n\n" + examples,
        }
        jobs = [(b, arm, sample) for b in briefs for arm in arms for sample in range(SAMPLES)]

        def draft(job: tuple[dict, str, int]) -> dict:
            b, arm, sample = job
            prompt = (
                f"Write a post of about {min(b['words'], 700)} words from this brief. Use only these facts, and "
                f"invent no numbers, names, quotes or results.\n\n{json.dumps(b['output'], indent=1)}"
            )
            print(f"drafting {arm}{sample} for {b['title'][:50]}")
            result = call_model(WRITER, Draft, arms[arm], prompt, temperature=0.8)
            return result | {"url": b["url"], "arm": arm, "sample": sample}

        with ThreadPoolExecutor(6) as pool:
            return list(pool.map(draft, jobs))

    drafts = saved("drafts", _make_drafts)
    assert len(drafts) == len(briefs) * 2 * SAMPLES
    mo.ui.table(
        [
            {
                "arm": d["arm"],
                "piece": d["url"].split("/")[-2][:40],
                "words": len(d["output"]["body"].split()),
                "input tokens": d["input_tokens"],
                "cost $": round(d["usd"], 4),
                "seconds": d["seconds"],
            }
            for d in drafts
        ],
        selection=None,
    )
    return (drafts,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. Count factual errors

    The helper model compares each draft with its brief and with the original published piece, and lists every
    claim that neither supports: an invented number, client, quote, result or dataset, or a fact stated wrongly.
    General statements anyone could make don't count. A founder should spot-check these; the list for each draft is
    in `output/factcheck.json`.
    """)
    return


@app.cell
def _(briefs, call_model, drafts, saved, test):
    class Error(BaseModel):
        claim: str = Field(description="The draft's words")
        why: str = Field(description="What the brief and original actually say, or that they say nothing on it")

    class FactCheck(BaseModel):
        errors: list[Error]

    _originals = {p["url"]: p for p in test}
    _briefs = {b["url"]: b["output"] for b in briefs}

    def _make_checks() -> list[dict]:
        def check(d: dict) -> dict:
            return call_model(
                HELPER,
                FactCheck,
                "You check a draft blog post for factual errors. List each specific claim (a number, name, "
                "dataset, client, quote, result or step) that the brief and the original do not support, or that "
                "contradicts them. Ignore style, opinions, and general statements anyone could make.",
                f"<brief>\n{json.dumps(_briefs[d['url']], indent=1)}\n</brief>\n\n<original>\n"
                f"{_originals[d['url']]['text']}\n</original>\n\n<draft>\n# {d['output']['title']}\n\n"
                f"{d['output']['body']}\n</draft>",
                temperature=0,
            ) | {"url": d["url"], "arm": d["arm"], "sample": d["sample"]}

        with ThreadPoolExecutor(6) as pool:
            return list(pool.map(check, drafts))

    checks = saved("factcheck", _make_checks)
    assert [(c["url"], c["arm"], c["sample"]) for c in checks] == [(d["url"], d["arm"], d["sample"]) for d in drafts]
    return (checks,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 7. Off-voice tells we can count

    The guide names some things we never write: em-dashes, "it's not X, it's Y", "load-bearing", and a list of
    hype words. Counting them in each draft is cheap and objective, and it finds failures the blind picks can't
    explain. We count the same tells in the real pieces as a baseline.
    """)
    return


@app.cell
def _(drafts, pieces):
    TELLS = {
        "em-dash": r"—",
        "it's not X, it's Y": (
            r"\b(?:it's|it is|this is|that's|that is) not [^.;]{1,60}[.,;] (?:it's|it is|this is|but)\b"
        ),
        "load-bearing": r"load-bearing",
        "hype word": r"\b(?:revolutionary|game-changing|seamless|best-in-class|powerful|robust|transformative)\b",
        "press-release opener": r"\b(?:proud to announce|thrilled to|excited to)\b",
    }

    def tells(text: str) -> dict[str, int]:
        return {name: len(re.findall(pattern, text, flags=re.IGNORECASE)) for name, pattern in TELLS.items()}

    real_tells = [tells(p["text"]) for p in pieces]
    draft_tells = [tells(d["output"]["title"] + "\n" + d["output"]["body"]) for d in drafts]
    return draft_tells, real_tells


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 8. Blind pairs for the founder

    Each pair puts arm A's draft *n* next to arm B's draft *n* for the same brief, in random left/right order
    (fixed seed, so the pairs are the same on every run). `review/pairs.md` shows them with no labels. The founder
    picks which one sounds more like us, or calls it a tie, and the picks go in `review/picks.json` as
    `{"1": "left", "2": "right", "3": "tie", ...}`. The key is `review/key.json`; don't open it before picking.

    I dropped one thing from the plan: pairs against the real published piece. The founder wrote or approved those
    pieces and would recognise them, so that pair can't be blind.
    """)
    return


@app.cell
def _(briefs, drafts):
    _rng = random.Random(202)
    _by = {(d["url"], d["arm"], d["sample"]): d for d in drafts}
    pairs: list[dict[str, Any]] = []
    for _b in briefs:
        for _s in range(SAMPLES):
            _a, _bb = _by[(_b["url"], "A", _s)], _by[(_b["url"], "B", _s)]
            _left, _right = (_a, _bb) if _rng.random() < 0.5 else (_bb, _a)
            pairs.append(
                {
                    "pair": str(len(pairs) + 1),
                    "url": _b["url"],
                    "left": _left,
                    "right": _right,
                }
            )

    _lines = [
        "# Which one sounds like us?\n",
        "For each pair, pick the draft that sounds more like Fulton Ring, or call it a tie. Judge the voice, not "
        "which one got the facts right. Reply on the issue as `1 L, 2 R, 3 tie, ...`, or put the picks in "
        "`review/picks.json`. Don't open `review/key.json` first.\n",
    ]
    for _p in pairs:
        _lines.append(f"\n---\n\n## Pair {_p['pair']}\n")
        for _side in ("left", "right"):
            _d = _p[_side]["output"]
            _lines.append(f"\n### {_side.title()}: {_d['title']}\n\n{_d['body']}\n")
    REVIEW.mkdir(exist_ok=True)
    (REVIEW / "pairs.md").write_text("\n".join(_lines))
    (REVIEW / "key.json").write_text(
        json.dumps(
            {p["pair"]: {"left": p["left"]["arm"], "right": p["right"]["arm"]} for p in pairs},
            indent=1,
        )
    )
    mo.md(f"Wrote {len(pairs)} blind pairs to `review/pairs.md`.")
    return (pairs,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 9. A provisional judge, until the founder picks

    The founder's picks are the result. Until they're in, the helper model judges the same pairs as a stand-in. It
    sees the real held-out piece (which neither arm saw) as the reference for how we sound, and runs each pair twice
    with the sides swapped, since LLM judges lean toward one position. A pair counts for an arm only when both runs
    agree. This judge may also favour whichever draft is closer to the reference in content, so treat it as a
    sanity check, not the answer.
    """)
    return


@app.cell
def _(call_model, pairs, saved, test):
    class Pick(BaseModel):
        reason: str = Field(description="One or two sentences on how each draft matches or misses the voice")
        pick: Literal["first", "second", "tie"]

    _originals = {p["url"]: p for p in test}

    def _make_judgments() -> list[dict]:
        jobs = [(p, order) for p in pairs for order in (("left", "right"), ("right", "left"))]

        def judge(job: tuple[dict, tuple[str, str]]) -> dict:
            p, (first, second) = job
            result = call_model(
                HELPER,
                Pick,
                "You judge writing voice. The reference is a real piece by a company. Pick the draft that "
                "sounds more like the same writer: sentence rhythm, word choice, how it opens and closes, how "
                "it handles evidence and uncertainty. Ignore which draft has more facts.",
                f"<reference>\n{_originals[p['url']]['text']}\n</reference>\n\n<first>\n"
                f"{p[first]['output']['body']}\n</first>\n\n<second>\n{p[second]['output']['body']}\n</second>",
                temperature=0,
            )
            pick = result["output"]["pick"]
            arm = {
                "first": p[first]["arm"],
                "second": p[second]["arm"],
                "tie": "tie",
            }[pick]
            return result | {"pair": p["pair"], "order": f"{first}-{second}", "winner": arm}

        with ThreadPoolExecutor(6) as pool:
            return list(pool.map(judge, jobs))

    judgments = saved("judge", _make_judgments)
    assert len(judgments) == 2 * len(pairs)
    return (judgments,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 10. Results
    """)
    return


@app.cell
def _(checks, draft_tells, drafts, judgments, pairs, real_tells):
    def sign_test(wins: int, losses: int) -> float:
        """Two-sided exact binomial p-value for wins vs losses, ties dropped."""
        n = wins + losses
        if n == 0:
            return 1.0
        tail = sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n
        return min(1.0, 2 * tail)

    def tally(winners: list[str]) -> str:
        b, a, ties = winners.count("B"), winners.count("A"), winners.count("tie")
        return f"B {b}, A {a}, tie {ties} of {len(winners)} pairs (sign test p = {sign_test(b, a):.2f})"

    _picks_path = REVIEW / "picks.json"
    if _picks_path.exists():
        _picks = json.loads(_picks_path.read_text())
        assert set(_picks) == {p["pair"] for p in pairs}, "picks.json must have a pick for every pair"
        assert set(_picks.values()) <= {"left", "right", "tie"}
        _founder = [p[_picks[p["pair"]]]["arm"] if _picks[p["pair"]] != "tie" else "tie" for p in pairs]
        founder_line = tally(_founder)
    else:
        founder_line = "not in yet (`review/picks.json` is missing)"

    _judge = []
    for _p in pairs:
        _w = {j["winner"] for j in judgments if j["pair"] == _p["pair"]}
        _judge.append(_w.pop() if len(_w) == 1 else "tie")

    rows = []
    for _arm in ("A", "B"):
        _idx = [i for i, d in enumerate(drafts) if d["arm"] == _arm]
        _errors = [len(checks[i]["output"]["errors"]) for i in _idx]
        rows.append(
            {
                "arm": _arm,
                "drafts": len(_idx),
                "factual errors per draft": round(sum(_errors) / len(_idx), 2),
                "drafts with 0 errors": sum(e == 0 for e in _errors),
                "off-voice tells per draft": round(sum(sum(draft_tells[i].values()) for i in _idx) / len(_idx), 2),
                "cost per draft $": round(sum(drafts[i]["usd"] for i in _idx) / len(_idx), 5),
                "seconds per draft": round(sum(drafts[i]["seconds"] for i in _idx) / len(_idx), 1),
            }
        )
    _real = round(sum(sum(t.values()) for t in real_tells) / len(real_tells), 2)
    _spent = sum(d["usd"] for d in drafts) + sum(c["usd"] for c in checks) + sum(j["usd"] for j in judgments)
    mo.vstack(
        [
            mo.md(
                f"**Founder's blind picks:** {founder_line}\n\n"
                f"**Provisional judge (helper model, both orders must agree):** {tally(_judge)}\n\n"
                f"**Off-voice tells in the {len(real_tells)} real pieces:** {_real} per piece\n\n"
                f"**Spent on drafts, fact checks and judging:** ${_spent:.3f}"
            ),
            mo.ui.table(rows, selection=None),
        ]
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 11. Failure cases

    Every draft with an off-voice tell or a factual error, with the first few of each, so a reader can see what
    went wrong rather than just the counts.
    """)
    return


@app.cell
def _(checks, draft_tells, drafts):
    _rows = []
    for _i, _d in enumerate(drafts):
        _t = {k: v for k, v in draft_tells[_i].items() if v}
        _e = checks[_i]["output"]["errors"]
        if _t or _e:
            _rows.append(
                {
                    "draft": f"{_d['arm']}{_d['sample']} {_d['url'].split('/')[-2][:30]}",
                    "tells": ", ".join(f"{k} ×{v}" for k, v in _t.items()),
                    "errors": len(_e),
                    "first errors": " | ".join(e["claim"][:90] for e in _e[:2]),
                }
            )
    mo.ui.table(_rows, selection=None)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this doesn't show

    - **Arm C, the fine-tune, wasn't run.** 12 pieces is far below the few hundred examples guides cite. So this
      can't say whether fine-tuning would win with enough data; it says we don't have enough to try it on our own
      published pieces alone.
    - **The test set is 4 pieces.** 12 pairs can only show a large difference between A and B.
    - **One writer model.** Qwen 3.8 27B; a stronger closed model may close or widen the gap.
    - **The fact check and the provisional judge are a model's opinion.** The founder's picks and a spot-check of the
      fact list are the real scores.
    """)
    return


if __name__ == "__main__":
    app.run()
