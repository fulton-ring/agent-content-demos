import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import hashlib
    import io
    import json
    import os
    import time
    import urllib.request
    from pathlib import Path
    from typing import Literal

    import marimo as mo
    import pandas as pd
    import pypdfium2 as pdfium
    import trafilatura
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models.openrouter import OpenRouterModelSettings

    HERE = Path(__file__).parent
    ANSWERS = HERE / "answers"  # committed, so a reviewer can rescore without paying again
    SOURCES = Path(os.environ.get("SECOND_PASS_SOURCES_DIR", HERE / "sources"))  # fetched pages, not committed


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 2. Three checkers on the same claims

    Each checker reads one claim and says whether its source supports it, as a typed answer: supported or not,
    which of the parent's 8 error types it sees, and a one-line reason.

    1. **Same family, passage.** Claude Sonnet 5.5, the family our pipeline runs on, reads the claim and the
       passage. (The pipeline's jobs run on a larger Claude; Sonnet keeps the run inside the $5 budget.)
    2. **Other provider, passage.** OpenAI's GPT-5.6 Terra, a similar price tier, with the same prompt and passage.
    3. **Dreaming, full source.** Claude Sonnet 5.5 rereads the whole source, fetched at run time, instead of a
       passage someone already picked. It's our version of the offline "dreaming" pass in Anthropic's *The
       Components of Agent Memory*, which rereads the raw record to check notes against it. The card asked for the
       card history too; we left it out, because the card's later history contains the correction itself.

    All three use temperature 0 where the model allows it, and the same instructions on what counts as supported.
    """)
    return


@app.cell
def _():
    test_set = [json.loads(line) for line in (HERE / "data/test_set.jsonl").read_text().splitlines() if line]
    print(len(test_set), "claims")
    return (test_set,)


@app.cell
def _():
    ErrorType = Literal[
        "claim as fact",
        "not in source",
        "wrong date",
        "wrong figure",
        "missed context",
        "misattribution",
        "overgeneralized",
        "wrong source",
        "none",
    ]

    class Verdict(BaseModel):
        supported: bool = Field(description="True only if the source supports the claim as stated.")
        problem: ErrorType = Field(description="The main problem if not supported; 'none' if supported.")
        reason: str = Field(description="One or two sentences, quoting the source where it helps.")

    INSTRUCTIONS = """You check a research note against the source it cites. Decide whether the source supports the
    claim exactly as stated. It is not supported if any of these is true:
    - claim as fact: it states as fact what the source gives as speculation, opinion, a forecast or a vendor's claim,
      or states it more strongly than the source does;
    - not in source: it includes a detail, figure or quote the source doesn't contain;
    - wrong date or wrong figure: a date or number differs from the source;
    - missed context: it leaves out context in the source that changes its meaning;
    - misattribution: it credits words, findings or actions to the wrong person, organization, document or part;
    - overgeneralized: it extends a finding beyond the case, place or population the source covers;
    - wrong source: the source isn't about the claim at all.
    Judge only from the source text you are given. If the claim is supported, answer supported with problem 'none'."""
    return INSTRUCTIONS, Verdict


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The full sources for the dreaming pass

    We fetch each source page and keep its main text (trafilatura for web pages, the text layer for PDFs). Sources
    are saved in `sources/`, which isn't committed: they're other people's pages. A long source is cut to 40,000
    characters (about 10,000 tokens) around the place the passage comes from, to keep the run inside budget. If the
    passage can't be found in the page we fetched, the page has changed or the fetch got something else, and we
    count it.
    """)
    return


@app.cell
def _(test_set):
    LIMIT = 40_000

    def fetch(url: str) -> str:
        cached = SOURCES / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".txt")
        if cached.exists():
            return cached.read_text()
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (second-pass-checker demo)"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body, kind = response.read(), response.headers.get("Content-Type", "")
        except Exception as e:  # offline, blocked, timed out: an empty source we count, not a crash
            print(f"fetch failed: {url}: {type(e).__name__}")
            return ""
        if "pdf" in kind or body[:5] == b"%PDF-":
            pdf = pdfium.PdfDocument(io.BytesIO(body))
            text = "\n".join(page.get_textpage().get_text_range() for page in pdf)
        else:
            text = trafilatura.extract(body.decode("utf-8", "replace"), include_tables=True) or ""
        SOURCES.mkdir(parents=True, exist_ok=True)
        cached.write_text(text)
        return text

    def squash(text: str) -> str:
        for fancy, plain in [("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), ("\xa0", " ")]:
            text = text.replace(fancy, plain)
        return " ".join(text.split())

    full_sources = {}
    found = {}
    for _item in test_set:
        _text = squash(fetch(_item["source_url"]))
        # The passage was copied by a subagent, sometimes through a different reader, so we look for any of its
        # sentences rather than its exact opening.
        _sentences = [x for x in squash(_item["passage"]).replace("…", ". ").split(". ") if len(x) >= 40]
        _at = next((i for x in _sentences if (i := _text.lower().find(x[:60].lower())) >= 0), -1)
        found[_item["id"]] = _at >= 0 if _text else None
        if len(_text) > LIMIT:  # a window around the passage, or the start of the page if it can't be found
            _begin = max(0, min(_at - LIMIT // 2, len(_text) - LIMIT)) if _at >= 0 else 0
            _text = _text[_begin : _begin + LIMIT]
        full_sources[_item["id"]] = _text
    fetch_report = pd.Series(found).map({True: "passage found", False: "passage not found", None: "fetch failed"})
    print(fetch_report.value_counts().to_markdown())
    return found, full_sources


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Running the checkers

    One typed call per claim per checker. A saved answer in `answers/<checker>/<id>.json` is reused, so a rerun
    costs nothing unless an answer is missing. Each answer stores OpenRouter's reported cost and the seconds taken.
    A call that still fails after four tries is saved as a failure, which notebook 3 counts as "not flagged".
    """)
    return


@app.cell
async def _(INSTRUCTIONS, Verdict, found, full_sources, test_set):
    SETTINGS = OpenRouterModelSettings(
        temperature=0, max_tokens=4000, thinking="low", openrouter_usage={"include": True}
    )
    CHECKERS = {
        "claude_passage": "openrouter:anthropic/claude-sonnet-5.5",
        "gpt_passage": "openrouter:openai/gpt-5.6-terra",
        "claude_dreaming": "openrouter:anthropic/claude-sonnet-5.5",
    }

    def prompt(checker: str, item: dict) -> str | None:
        if checker != "claude_dreaming":
            return f"CLAIM:\n{item['claim']}\n\nSOURCE ({item['source_title']}), passage:\n{item['passage']}"
        if not found[item["id"]]:
            return None  # the page we fetched isn't the page the passage came from
        return (
            f"CLAIM:\n{item['claim']}\n\nSOURCE ({item['source_title']}), full text. Reread all of it and find "
            f"every part that bears on the claim before you decide.\n\n{full_sources[item['id']]}"
        )

    async def check(checker: str, item: dict, slots: asyncio.Semaphore) -> None:
        saved = ANSWERS / checker / f"{item['id']}.json"
        text = prompt(checker, item)
        if saved.exists() or text is None:
            return
        agent = Agent(CHECKERS[checker], output_type=Verdict, instructions=INSTRUCTIONS, retries=2)
        answer = {"verdict": None, "usd": 0.0, "seconds": 0.0, "error": ""}
        async with slots:
            for attempt in range(4):
                t0 = time.time()
                try:
                    result = await agent.run(text, model_settings=SETTINGS)
                except Exception as e:  # rate limits, network errors, output that failed the schema
                    answer["seconds"] += time.time() - t0
                    answer["error"] = f"{type(e).__name__}: {e!s:.200}"
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                answer["seconds"] += time.time() - t0
                answer["usd"] += sum(
                    float((m.provider_details or {}).get("cost") or 0)
                    for m in result.new_messages()
                    if isinstance(m, ModelResponse)
                )
                assert isinstance(result.output, BaseModel), "the model answered with text, not the schema"
                answer["verdict"], answer["error"] = result.output.model_dump(), ""
                break
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(answer, indent=1, ensure_ascii=False))

    slots = asyncio.Semaphore(8)
    await asyncio.gather(*(check(c, item, slots) for c in CHECKERS for item in test_set))
    return (CHECKERS,)


@app.cell
def _(CHECKERS, test_set):
    rows = []
    for _checker in CHECKERS:
        for _item in test_set:
            _path = ANSWERS / _checker / f"{_item['id']}.json"
            _answer = json.loads(_path.read_text()) if _path.exists() else None
            rows.append(
                {
                    "checker": _checker,
                    "answered": bool(_answer and _answer["verdict"]),
                    "usd": _answer["usd"] if _answer else 0.0,
                    "seconds": _answer["seconds"] if _answer else 0.0,
                }
            )
    spend = (
        pd.DataFrame(rows)
        .groupby("checker")
        .agg(claims=("answered", "size"), answered=("answered", "sum"), usd=("usd", "sum"), seconds=("seconds", "sum"))
    )
    print(spend.round(3).to_markdown())
    print(f"\nTotal OpenRouter cost: ${spend['usd'].sum():.2f}")
    return


if __name__ == "__main__":
    app.run()
