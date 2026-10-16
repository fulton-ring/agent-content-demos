"""Fill the policy template from call notes, and check and revise it, with typed model calls through OpenRouter."""

import time
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings

from policy_builder.review import FidelityReview, problem_list
from policy_builder.schema import Policy

DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"
CHECK_EFFORT = "low"  # the check lists statements one by one; it needs little reasoning, and this keeps it cheap
Output = TypeVar("Output")


class Usage(BaseModel):
    """Totals across a group of model calls."""

    model_calls: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


class RunMeta(BaseModel):
    """What it took to produce one policy: drafting calls and checking calls kept apart."""

    model: str
    draft: Usage = Usage()
    check: Usage = Usage()
    shorten_passes: int = 0
    revise_passes: int = 0
    first_draft_pages: int = 0
    first_draft_fill: float = 0.0


def read_prompt(project: Path, name: str) -> str:
    return (project / "prompts" / f"{name}.md").read_text()


def with_template(project: Path, prompt: str) -> str:
    template = (project / "template" / "policy-template.md").read_text()
    questions = (project / "template" / "call-questions.md").read_text()
    return f"{prompt}\n\n<template>\n{template}\n</template>\n\n<call_questions>\n{questions}\n</call_questions>"


def review_instructions(project: Path) -> str:
    rules = read_prompt(project, "fill-policy")
    return f"{read_prompt(project, 'review-policy')}\n\n<drafting_rules>\n{rules}\n</drafting_rules>"


def reported_cost(responses: list[ModelResponse]) -> float:
    """Sum the cost OpenRouter reports for each response (usage accounting)."""
    return sum(float((r.provider_details or {}).get("cost", 0.0)) for r in responses)


def run_agent(agent: Agent[None, Output], prompt: str, usage: Usage) -> Output:
    started = time.perf_counter()
    result = agent.run_sync(prompt)
    responses = [m for m in result.all_messages() if isinstance(m, ModelResponse)]
    usage.model_calls += len(responses)
    usage.seconds = round(usage.seconds + time.perf_counter() - started, 1)
    usage.cost_usd = round(usage.cost_usd + reported_cost(responses), 4)
    usage.input_tokens += result.usage.input_tokens
    usage.output_tokens += result.usage.output_tokens
    return result.output


def drafting_message(call_notes: str, policy: Policy, request: str) -> str:
    return (
        f"<call_notes>\n{call_notes}\n</call_notes>\n\n<draft>\n{policy.model_dump_json(indent=1)}\n</draft>\n\n"
        f"{request}"
    )


class Drafter:
    def __init__(self, project: Path, model_name: str = DEFAULT_MODEL) -> None:
        self.project = project
        self.meta = RunMeta(model=model_name)
        settings = OpenRouterModelSettings(openrouter_usage={"include": True}, temperature=0)
        model = OpenRouterModel(model_name)
        self.writer = Agent(
            model,
            output_type=Policy,
            instructions=with_template(project, read_prompt(project, "fill-policy")),
            model_settings=settings,
            retries=2,
        )
        self.checker = Agent(
            model,
            output_type=FidelityReview,
            instructions=with_template(project, review_instructions(project)),
            model_settings=OpenRouterModelSettings(**settings, openrouter_reasoning={"effort": CHECK_EFFORT}),
            retries=2,
        )

    def fill(self, call_notes: str) -> Policy:
        return run_agent(self.writer, f"<call_notes>\n{call_notes}\n</call_notes>", self.meta.draft)

    def shorten(self, call_notes: str, policy: Policy, page_fill: float) -> Policy:
        self.meta.shorten_passes += 1
        request = read_prompt(self.project, "shorten-policy").format(percent=round(page_fill * 100))
        return run_agent(self.writer, drafting_message(call_notes, policy, request), self.meta.draft)

    def revise(self, call_notes: str, policy: Policy, review: FidelityReview) -> Policy:
        self.meta.revise_passes += 1
        request = read_prompt(self.project, "revise-policy").format(problems=problem_list(review))
        return run_agent(self.writer, drafting_message(call_notes, policy, request), self.meta.draft)

    def review(self, call_notes: str, policy: Policy) -> FidelityReview:
        message = (
            f"<call_notes>\n{call_notes}\n</call_notes>\n\n<policy>\n{policy.model_dump_json(indent=1)}\n</policy>"
        )
        return run_agent(self.checker, message, self.meta.check)
