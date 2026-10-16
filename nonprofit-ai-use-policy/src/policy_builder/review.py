"""The independent fidelity check: every statement in a policy labelled against its call, plus what it missed."""

from enum import StrEnum

from pydantic import BaseModel, Field


class Label(StrEnum):
    SUPPORTED = "supported"
    DEFAULT = "default"
    UNSUPPORTED = "unsupported"
    CONTRADICTS = "contradicts"


PROBLEM_LABELS = (Label.UNSUPPORTED, Label.CONTRADICTS)


class StatementCheck(BaseModel):
    section: str = Field(description="Template section the statement sits in.")
    statement: str = Field(description="The statement, quoted briefly.")
    label: Label
    reason: str = Field(description="One short sentence. For a problem, what is wrong and what would fix it.")


class FidelityReview(BaseModel):
    statements: list[StatementCheck] = Field(min_length=1, max_length=70)
    missed: list[str] = Field(
        max_length=8, description="Points from the call a staff member would need that the policy leaves out."
    )

    def count(self, label: Label) -> int:
        return sum(s.label == label for s in self.statements)

    def problems(self) -> list[StatementCheck]:
        return [s for s in self.statements if s.label in PROBLEM_LABELS]


class FidelityCounts(BaseModel):
    statements: int
    supported: int
    default: int
    unsupported: int
    contradicts: int
    missed: int

    @classmethod
    def of(cls, review: FidelityReview) -> "FidelityCounts":
        return cls(
            statements=len(review.statements),
            supported=review.count(Label.SUPPORTED),
            default=review.count(Label.DEFAULT),
            unsupported=review.count(Label.UNSUPPORTED),
            contradicts=review.count(Label.CONTRADICTS),
            missed=len(review.missed),
        )

    def summary(self) -> str:
        return f"{self.unsupported} unsupported, {self.contradicts} contradicts, {self.missed} missed"


def problem_list(review: FidelityReview) -> str:
    """The review's problems as bullets for the revise prompt."""
    return "\n".join(f'- {s.label} ({s.section}): "{s.statement}". {s.reason}' for s in review.problems())


class ReviewRecord(BaseModel):
    """The check of the first fitted draft, and of the final policy after any revise pass."""

    first: FidelityReview
    final: FidelityReview
