from dataclasses import replace
from datetime import UTC, datetime

from board_dispatcher.board import Card
from board_dispatcher.github import BoardFields, GitHub
from board_dispatcher.main import start_workers
from board_dispatcher.routine import RoutineError

NOW = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
FIELDS = BoardFields(
    project_id="project",
    status_field_id="status",
    status_option_ids={"In progress": "option"},
    not_before_field_id="not-before",
    proposal_field_id="proposal",
)
CARD = Card(
    item_id="item1",
    issue_id="issue1",
    issue_ref="fulton-ring/agent-content-demos#1",
    issue_open=True,
    status="Ready",
    agent=None,
    not_before=None,
    open_blockers=0,
    worker_starts=(),
)


class FakeGitHub(GitHub):
    def __init__(self) -> None:
        self.moved: list[str] = []
        self.commented: list[str] = []

    def set_status(self, fields: BoardFields, item_id: str, status: str) -> None:
        self.moved.append(item_id)

    def comment(self, issue_id: str, body: str) -> None:
        self.commented.append(issue_id)


def test_failed_start_does_not_skip_the_remaining_cards() -> None:
    failing = replace(CARD, item_id="item2", issue_id="issue2", issue_ref="repo#2")
    last = replace(CARD, item_id="item3", issue_id="issue3", issue_ref="repo#3")

    def start(issue_ref: str) -> str:
        if issue_ref == failing.issue_ref:
            raise RoutineError("Routine fire returned HTTP 500")
        return f"https://claude.ai/code/{issue_ref}"

    github = FakeGitHub()
    failures = start_workers(github, FIELDS, [CARD, failing, last], start, NOW)

    assert failures == 1
    assert github.moved == ["item1", "item3"]
    assert github.commented == ["issue1", "issue3"]
