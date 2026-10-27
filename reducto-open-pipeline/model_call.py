"""One model call through OpenRouter, typed, cost-counted and saved to disk. Both notebooks use it."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openrouter import OpenRouterModelSettings

MODEL = "openrouter:google/gemini-3.8-flash"
ATTEMPTS = 4
# The K-1 spike's settings: temperature 0, and low thinking, since reading a page doesn't need long reasoning.
SETTINGS = OpenRouterModelSettings(temperature=0, max_tokens=8000, thinking="low", openrouter_usage={"include": True})


async def ask(saved: Path, output_type: Any, instructions: str, parts: list[Any], slots: asyncio.Semaphore) -> dict:
    """Ask the model for a typed answer, or read the answer saved at `saved` by an earlier run.

    Returns the answer's type name, the answer as JSON, and every attempt's cost (OpenRouter's own figure),
    seconds and failures. Raises after ATTEMPTS failed attempts.
    """
    if saved.exists():
        return json.loads(saved.read_text())
    agent = Agent(MODEL, output_type=output_type, instructions=instructions, retries=2)
    spent = {"usd": 0.0, "seconds": 0.0, "failed_attempts": 0}
    async with slots:
        for attempt in range(ATTEMPTS):
            t0 = time.time()
            try:
                result = await agent.run(parts, model_settings=SETTINGS)
            except Exception as e:  # rate limits, network errors, malformed output after Pydantic AI's retries
                spent["seconds"] += time.time() - t0
                spent["failed_attempts"] += 1
                print(f"{saved.parent.name}/{saved.stem}: attempt {attempt + 1} failed: {type(e).__name__}: {e!s:.150}")
                if attempt == ATTEMPTS - 1:
                    raise
                await asyncio.sleep(10 * (attempt + 1))
                continue
            spent["seconds"] += time.time() - t0
            spent["usd"] += sum(
                float((m.provider_details or {}).get("cost") or 0)
                for m in result.new_messages()
                if isinstance(m, ModelResponse)
            )
            assert isinstance(result.output, BaseModel), "the model answered with text, not the schema"
            answer = {"type": type(result.output).__name__, "output": result.output.model_dump(mode="json"), **spent}
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps(answer, indent=1))
            return answer
    raise AssertionError("unreachable")
