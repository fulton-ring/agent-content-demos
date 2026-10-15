"""Fill the policy template from call notes with typed model calls through OpenRouter."""

import time
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings

from policy_builder.schema import Policy

DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"


class RunMeta(BaseModel):
    """Totals across every model call that produced one policy."""

    model: str
    model_calls: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    shorten_passes: int = 0
    first_draft_pages: int = 0
    first_draft_fill: float = 0.0


def build_instructions(project: Path) -> str:
    prompt = (project / "prompts" / "fill-policy.md").read_text()
    template = (project / "template" / "policy-template.md").read_text()
    questions = (project / "template" / "call-questions.md").read_text()
    return f"{prompt}\n\n<template>\n{template}\n</template>\n\n<call_questions>\n{questions}\n</call_questions>"


def reported_cost(responses: list[ModelResponse]) -> float:
    """Sum the cost OpenRouter reports for each response (usage accounting)."""
    return sum(float((r.provider_details or {}).get("cost", 0.0)) for r in responses)


class Drafter:
    def __init__(self, project: Path, model_name: str = DEFAULT_MODEL) -> None:
        self.project = project
        self.meta = RunMeta(model=model_name)
        self.agent = Agent(
            OpenRouterModel(model_name),
            output_type=Policy,
            instructions=build_instructions(project),
            model_settings=OpenRouterModelSettings(openrouter_usage={"include": True}, temperature=0),
            retries=2,
        )

    def run(self, prompt: str) -> Policy:
        started = time.perf_counter()
        result = self.agent.run_sync(prompt)
        responses = [m for m in result.all_messages() if isinstance(m, ModelResponse)]
        meta = self.meta
        meta.model_calls += len(responses)
        meta.seconds = round(meta.seconds + time.perf_counter() - started, 1)
        meta.cost_usd = round(meta.cost_usd + reported_cost(responses), 4)
        meta.input_tokens += result.usage.input_tokens
        meta.output_tokens += result.usage.output_tokens
        return result.output

    def fill(self, call_notes: str) -> Policy:
        return self.run(f"<call_notes>\n{call_notes}\n</call_notes>")

    def shorten(self, call_notes: str, policy: Policy, page_fill: float) -> Policy:
        self.meta.shorten_passes += 1
        request = (self.project / "prompts" / "shorten-policy.md").read_text().format(percent=round(page_fill * 100))
        return self.run(
            f"<call_notes>\n{call_notes}\n</call_notes>\n\n<draft>\n{policy.model_dump_json(indent=1)}\n</draft>\n\n"
            f"{request}"
        )
