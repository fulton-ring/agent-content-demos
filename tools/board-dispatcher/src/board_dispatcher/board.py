"""Which Ready cards get a worker. Pure logic: no network, no clock."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

READY = "Ready"
IN_PROGRESS = "In progress"
CLAUDE_WORKER = "Claude worker"
WORKER_STARTED = "Worker started"


@dataclass(frozen=True)
class Card:
    item_id: str
    issue_id: str
    issue_ref: str  # owner/repo#number
    issue_open: bool
    status: str | None
    agent: str | None
    not_before: date | None
    open_blockers: int
    last_worker_start: datetime | None


def is_claude_card(card: Card) -> bool:
    return card.agent in (None, CLAUDE_WORKER)


def is_startable(card: Card, now: datetime, cooldown: timedelta) -> bool:
    if not card.issue_open or card.status != READY or not is_claude_card(card):
        return False
    if card.open_blockers > 0:
        return False
    if card.not_before is not None and card.not_before > now.date():
        return False
    return card.last_worker_start is None or now - card.last_worker_start >= cooldown


def cards_to_start(
    cards: list[Card], now: datetime, max_in_progress: int, cooldown: timedelta
) -> list[Card]:
    """Ready Claude cards to start now, oldest first, without going over the in-progress cap."""
    assert max_in_progress >= 0
    running = sum(
        1 for c in cards if c.issue_open and c.status == IN_PROGRESS and is_claude_card(c)
    )
    free_slots = max(0, max_in_progress - running)
    startable = [c for c in cards if is_startable(c, now, cooldown)]
    return startable[:free_slots]


def last_worker_start(comments: list[tuple[str, datetime]]) -> datetime | None:
    """The latest time a comment recorded a worker starting on the issue."""
    starts = [created for body, created in comments if body.startswith(WORKER_STARTED)]
    return max(starts, default=None)
