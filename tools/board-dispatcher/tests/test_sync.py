from datetime import date

from board_dispatcher.sync import Label, Signals, update_for

REVIEW = Label("l1", "move:review")
READY = Label("l2", "move:ready")
FOUNDER = Label("l3", "move:needs-founder")
SPIKE = Label("l4", "agent:spike")
NOTION = "https://app.notion.com/p/3f7cc69045cb81f98ec5f38865de68c8"


def signals(
    labels: tuple[Label, ...] = (),
    body: str = "",
    not_before: date | None = None,
    proposal: str | None = None,
) -> Signals:
    return Signals(labels=labels, body=body, not_before=not_before, proposal=proposal)


def test_no_signals_means_no_update() -> None:
    assert update_for(signals(labels=(SPIKE,), body="Just a plan.")).is_empty


def test_move_label_sets_status_and_is_removed() -> None:
    update = update_for(signals(labels=(SPIKE, REVIEW)))
    assert update.status == "Review"
    assert update.labels_to_remove == (REVIEW,)


def test_needs_founder_wins_over_other_moves() -> None:
    update = update_for(signals(labels=(READY, FOUNDER, REVIEW)))
    assert update.status == "Needs founder"
    assert set(update.labels_to_remove) == {READY, FOUNDER, REVIEW}


def test_body_lines_fill_empty_fields() -> None:
    body = f"**Card:** {NOTION}\nNot before: 2026-10-20\n\n## Argument\n..."
    update = update_for(signals(body=body))
    assert update.not_before == date(2026, 10, 20)
    assert update.proposal == NOTION


def test_fields_already_set_are_left_alone() -> None:
    body = f"Card: {NOTION}\nNot before: 2026-10-20"
    update = update_for(signals(body=body, not_before=date(2026, 11, 1), proposal="other"))
    assert update.is_empty


def test_bad_not_before_date_is_ignored() -> None:
    assert update_for(signals(body="Not before: 2026-13-45")).not_before is None
