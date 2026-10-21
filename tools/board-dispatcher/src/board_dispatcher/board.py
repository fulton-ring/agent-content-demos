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
    worker_starts: tuple[datetime, ...]  # times of the issue's Worker started comments


def is_claude_card(card: Card) -> bool:
    return card.agent in (None, CLAUDE_WORKER)


def is_startable(card: Card, now: datetime, cooldown: timedelta) -> bool:
    if not card.issue_open or card.status != READY or not is_claude_card(card):
        return False
    if card.open_blockers > 0:
        return False
    if card.not_before is not None and card.not_before > now.date():
        return False
    last_start = max(card.worker_starts, default=None)
    return last_start is None or now - last_start >= cooldown


def starts_in_last_day(cards: list[Card], now: datetime) -> int:
    """Workers started on any issue on the board in the 24 hours before `now`."""
    return sum(1 for c in cards for started in c.worker_starts if now - started < timedelta(days=1))


def cards_to_start(
    cards: list[Card],
    now: datetime,
    max_in_progress: int,
    max_starts_per_day: int,
    cooldown: timedelta,
) -> list[Card]:
    """Ready Claude cards to start now, oldest first, within the in-progress and daily caps."""
    assert max_in_progress >= 0
    assert max_starts_per_day >= 0
    running = sum(
        1 for c in cards if c.issue_open and c.status == IN_PROGRESS and is_claude_card(c)
    )
    free_slots = max(0, max_in_progress - running)
    starts_left = max(0, max_starts_per_day - starts_in_last_day(cards, now))
    startable = [c for c in cards if is_startable(c, now, cooldown)]
    return startable[: min(free_slots, starts_left)]


def worker_starts(comments: list[tuple[str, datetime]]) -> tuple[datetime, ...]:
    """The times comments recorded a worker starting on the issue."""
    return tuple(created for body, created in comments if body.startswith(WORKER_STARTED))
