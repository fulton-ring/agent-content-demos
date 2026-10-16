"""Checks on a filled policy: sections filled, reading level, length, and names that trace back to the call."""

import re

import nltk
from pydantic import BaseModel
from textstat import textstat

from policy_builder.fill import RunMeta
from policy_builder.review import FidelityCounts
from policy_builder.schema import SECTIONS, Policy

PLACEHOLDER = re.compile(r"\[|\]|\bTBD\b|lorem|not yet named|^none\b", re.IGNORECASE)


def field_texts(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, BaseModel):
        return [t for v in value.model_dump().values() for t in field_texts(v)]
    if isinstance(value, dict):
        return [t for v in value.values() for t in field_texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in field_texts(v)]
    return []


def is_filled(value: object) -> bool:
    texts = field_texts(value)
    return bool(texts) and all(t.strip() and not PLACEHOLDER.search(t) for t in texts)


def sections_filled(policy: Policy) -> dict[str, bool]:
    return {section: all(is_filled(getattr(policy, f)) for f in fields) for section, fields in SECTIONS.items()}


def as_sentences(policy: Policy) -> str:
    """The policy's visible text as sentences, so readability formulas see bullets as sentences."""
    texts = field_texts(policy.model_dump(exclude={"organization", "owner", "next_review"}))
    return " ".join(t if t.rstrip().endswith((".", "?", "!")) else f"{t.rstrip()}." for t in texts)


class ReadingLevel(BaseModel):
    flesch_kincaid_grade: float
    flesch_reading_ease: float
    words: int


def ensure_syllable_dictionary() -> None:
    """textstat counts syllables with the CMU Pronouncing Dictionary, fetched once into ~/nltk_data."""
    try:
        nltk.data.find("corpora/cmudict")
    except LookupError:
        nltk.download("cmudict", quiet=True)


def reading_level(policy: Policy) -> ReadingLevel:
    ensure_syllable_dictionary()
    text = as_sentences(policy)
    return ReadingLevel(
        flesch_kincaid_grade=round(textstat.flesch_kincaid_grade(text), 1),
        flesch_reading_ease=round(textstat.flesch_reading_ease(text), 1),
        words=textstat.lexicon_count(text),
    )


def words_missing_from_call(phrase: str, call_notes: str) -> list[str]:
    notes = call_notes.lower()
    words = [w.removesuffix("'s") for w in re.findall(r"[A-Za-z][A-Za-z.']{3,}", phrase)]
    return [w for w in words if w[0].isupper() and w.lower().rstrip(".") not in notes]


def untraced_names(policy: Policy, call_notes: str) -> list[str]:
    """Capitalized words in tool names and approvers that never appear in the call notes."""
    phrases = [t.name for t in policy.tools] + [r.approver for r in policy.needs_approval] + [policy.owner]
    return sorted({w for p in phrases for w in words_missing_from_call(p, call_notes)})


class PolicyResult(ReadingLevel):
    """Everything measured for one policy in one run."""

    run: RunMeta
    fidelity_first: FidelityCounts
    fidelity_final: FidelityCounts
    slug: str
    organization: str
    pages: int
    page_fill: float
    sections_filled: int
    sections_total: int
    unfilled_sections: list[str]
    untraced_names: list[str]
    open_questions: int
