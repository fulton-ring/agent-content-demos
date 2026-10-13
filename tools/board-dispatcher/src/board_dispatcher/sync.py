"""Turns signals agents leave on issues into board changes. Pure logic: no network.

Cloud agent sessions can't reach the org's project board, so they signal on the
issue instead: a `move:*` label asks for a Status change, and lines in the issue
body set Not before and Proposal. The dispatcher applies them and removes the labels.
"""

import re
from dataclasses import dataclass
from datetime import date

MOVE_LABELS = {
    "move:needs-founder": "Needs founder",
    "move:review": "Review",
    "move:ready": "Ready",
    "move:backlog": "Backlog",
}  # in priority order: the first one present wins

NOT_BEFORE_LINE = re.compile(r"(?im)^\W*not before\W*\s*(\d{4}-\d{2}-\d{2})")
CARD_LINE = re.compile(r"(?im)^\W*card\W*\s*<?(https://\S*notion\S*?)>?\s*$")


@dataclass(frozen=True)
class Label:
    label_id: str
    name: str


@dataclass(frozen=True)
class Signals:
    labels: tuple[Label, ...]
    body: str
    not_before: date | None  # current field value
    proposal: str | None  # current field value


@dataclass(frozen=True)
class Update:
    status: str | None
    not_before: date | None
    proposal: str | None
    labels_to_remove: tuple[Label, ...]

    @property
    def is_empty(self) -> bool:
        return not (self.status or self.not_before or self.proposal or self.labels_to_remove)


def requested_status(labels: tuple[Label, ...]) -> str | None:
    names = {label.name for label in labels}
    return next((status for name, status in MOVE_LABELS.items() if name in names), None)


def body_not_before(body: str) -> date | None:
    match = NOT_BEFORE_LINE.search(body)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def body_proposal(body: str) -> str | None:
    match = CARD_LINE.search(body)
    return match.group(1) if match else None


def update_for(signals: Signals) -> Update:
    """Board changes the issue asks for. Fields already set on the board are left alone."""
    not_before = body_not_before(signals.body) if signals.not_before is None else None
    proposal = body_proposal(signals.body) if signals.proposal is None else None
    return Update(
        status=requested_status(signals.labels),
        not_before=not_before,
        proposal=proposal,
        labels_to_remove=tuple(label for label in signals.labels if label.name in MOVE_LABELS),
    )
