"""Entry point: apply agents' signals to the board, then start a worker on each Ready card."""

import os
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from board_dispatcher.board import IN_PROGRESS, WORKER_STARTED, Card, cards_to_start
from board_dispatcher.github import BoardFields, BoardItem, GitHub
from board_dispatcher.routine import start_worker
from board_dispatcher.sync import update_for


@dataclass(frozen=True)
class Config:
    github_token: str
    worker_token: str
    worker_routine_id: str
    project_owner: str
    project_number: int
    repo: str
    max_in_progress: int
    cooldown: timedelta
    dry_run: bool


def load_config() -> Config:
    def required(name: str) -> str:
        value = os.environ.get(name, "")
        if not value:
            raise SystemExit(f"{name} is not set")
        return value

    return Config(
        github_token=required("GH_TOKEN"),
        worker_token=required("SPIKE_WORKER_TOKEN"),
        worker_routine_id=required("WORKER_ROUTINE_ID"),
        project_owner=required("PROJECT_OWNER"),
        project_number=int(required("PROJECT_NUMBER")),
        repo=required("REPO"),
        max_in_progress=int(os.environ.get("MAX_IN_PROGRESS", "5")),
        cooldown=timedelta(hours=float(os.environ.get("COOLDOWN_HOURS", "6"))),
        dry_run=os.environ.get("DRY_RUN", "") == "1",
    )


def apply_signals(github: GitHub, fields: BoardFields, item: BoardItem, dry_run: bool) -> Card:
    """Apply the issue's move label and body fields to its card. Returns the updated card."""
    update = update_for(item.signals)
    if update.is_empty:
        return item.card
    print(f"{item.card.issue_ref}: {update}")
    if dry_run:
        return item.card
    card = item.card
    if update.status:
        github.set_status(fields, card.item_id, update.status)
        card = replace(card, status=update.status)
    if update.not_before:
        github.set_not_before(fields, card.item_id, update.not_before)
        card = replace(card, not_before=update.not_before)
    if update.proposal:
        github.set_proposal(fields, card.item_id, update.proposal)
    if update.labels_to_remove:
        github.remove_labels(card.issue_id, update.labels_to_remove)
    return card


def run(config: Config) -> int:
    github = GitHub(config.github_token)
    fields = github.fields(config.project_owner, config.project_number)
    items = github.items(config.project_owner, config.project_number, config.repo)
    cards = [apply_signals(github, fields, item, config.dry_run) for item in items]
    now = datetime.now(UTC)
    chosen = cards_to_start(cards, now, config.max_in_progress, config.cooldown)
    print(f"{len(cards)} cards on the board, {len(chosen)} to start")
    for card in chosen:
        if config.dry_run:
            print(f"dry run: would start a worker on {card.issue_ref}")
            continue
        session_url = start_worker(config.worker_routine_id, config.worker_token, card.issue_ref)
        github.set_status(fields, card.item_id, IN_PROGRESS)
        stamp = now.strftime("%Y-%m-%dT%H:%MZ")
        github.comment(card.issue_id, f"{WORKER_STARTED} {stamp}: {session_url}")
        print(f"started a worker on {card.issue_ref}: {session_url}")
    return 0


def main() -> None:
    sys.exit(run(load_config()))
