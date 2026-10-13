from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from board_dispatcher.board import Card, cards_to_start, last_worker_start

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=UTC)
COOLDOWN = timedelta(hours=6)

READY_CARD = Card(
    item_id="item",
    issue_id="issue",
    issue_ref="fulton-ring/agent-content-demos#1",
    issue_open=True,
    status="Ready",
    agent="Claude worker",
    not_before=None,
    open_blockers=0,
    last_worker_start=None,
)


def start(cards: list[Card], max_in_progress: int = 5) -> list[Card]:
    return cards_to_start(cards, NOW, max_in_progress, COOLDOWN)


def test_ready_claude_card_starts() -> None:
    assert start([READY_CARD]) == [READY_CARD]


def test_card_with_no_agent_counts_as_claude() -> None:
    card = replace(READY_CARD, agent=None)
    assert start([card]) == [card]


def test_other_agents_and_columns_are_left_alone() -> None:
    cards = [
        replace(READY_CARD, agent="Codex (paused)"),
        replace(READY_CARD, status="Backlog"),
        replace(READY_CARD, issue_open=False),
    ]
    assert start(cards) == []


def test_blocked_card_waits() -> None:
    assert start([replace(READY_CARD, open_blockers=1)]) == []


def test_not_before_holds_until_that_day() -> None:
    tomorrow = replace(READY_CARD, not_before=date(2026, 10, 14))
    today = replace(READY_CARD, not_before=date(2026, 10, 13))
    assert start([tomorrow, today]) == [today]


def test_recent_worker_start_prevents_a_second_worker() -> None:
    recent = replace(READY_CARD, last_worker_start=NOW - timedelta(hours=1))
    stale = replace(READY_CARD, last_worker_start=NOW - timedelta(hours=7))
    assert start([recent, stale]) == [stale]


def test_in_progress_cap_limits_new_starts() -> None:
    running = [replace(READY_CARD, status="In progress") for _ in range(4)]
    ready = [replace(READY_CARD, item_id=f"ready-{n}") for n in range(3)]
    assert [c.item_id for c in start(running + ready)] == ["ready-0"]


def test_last_worker_start_reads_only_start_comments() -> None:
    earlier = datetime(2026, 10, 12, tzinfo=UTC)
    later = datetime(2026, 10, 13, tzinfo=UTC)
    comments = [
        ("Worker started 2026-10-12: url", earlier),
        ("Plan: ...", later + timedelta(hours=1)),
        ("Worker started 2026-10-13: url", later),
    ]
    assert last_worker_start(comments) == later
    assert last_worker_start([]) is None
