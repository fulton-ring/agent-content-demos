"""One command: render the template and questions, then draft each call's policy, fit it to a page and check it."""

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from policy_builder import checks, published, render
from policy_builder.fill import DEFAULT_MODEL, Drafter, RunMeta
from policy_builder.report import write_published, write_reports
from policy_builder.review import FidelityCounts, ReviewRecord
from policy_builder.schema import Policy

PROJECT = Path(__file__).resolve().parents[2]
CALLS = PROJECT / "calls"
OUTPUT = Path(os.environ.get("POLICY_OUTPUT_DIR", PROJECT / "output"))
SCREENSHOTS = OUTPUT / "screenshots"
MAX_SHORTEN_PASSES = 2


def print_html(html: str, folder: Path, name: str, screenshot: str) -> render.Printed:
    folder.mkdir(parents=True, exist_ok=True)
    html_path = folder / f"{name}.html"
    html_path.write_text(html)
    return render.print_page(html_path, folder / f"{name}.pdf", SCREENSHOTS / f"{screenshot}.png")


def build_template_pages() -> None:
    for name, title in [("policy-template", "AI use policy template"), ("call-questions", "Call questions")]:
        html = render.markdown_html(PROJECT / "template" / f"{name}.md", title)
        printed = print_html(html, OUTPUT / "template", name, name)
        print(f"{name}: {printed.pages} page(s)")


def print_policy(policy: Policy, slug: str) -> render.Printed:
    return print_html(render.policy_html(policy), OUTPUT / slug, "policy", slug)


def fit_to_page(drafter: Drafter, call_notes: str, policy: Policy, slug: str) -> tuple[Policy, render.Printed]:
    """Ask for a shorter version while the policy spills past one page, at most MAX_SHORTEN_PASSES times."""
    printed = print_policy(policy, slug)
    for _ in range(MAX_SHORTEN_PASSES):
        if printed.pages == 1:
            break
        policy = drafter.shorten(call_notes, policy, printed.page_fill)
        printed = print_policy(policy, slug)
    return policy, printed


@dataclass
class Drafted:
    policy: Policy
    meta: RunMeta
    printed: render.Printed
    review: ReviewRecord


def draft_and_check(call_notes: str, slug: str, model: str) -> Drafted:
    """Fill the template, fit it to a page, check it against the call, and revise once if the check finds problems."""
    drafter = Drafter(PROJECT, model)
    policy = drafter.fill(call_notes)
    first_print = print_policy(policy, slug)
    drafter.meta.first_draft_pages, drafter.meta.first_draft_fill = first_print.pages, first_print.page_fill
    policy, printed = fit_to_page(drafter, call_notes, policy, slug)
    first = final = drafter.review(call_notes, policy)
    print(f"{slug}: first check {FidelityCounts.of(first).summary()}")
    if first.problems():
        policy = drafter.revise(call_notes, policy, first)
        policy, printed = fit_to_page(drafter, call_notes, policy, slug)
        final = drafter.review(call_notes, policy)
    return Drafted(policy, drafter.meta, printed, ReviewRecord(first=first, final=final))


def load_or_draft(call: Path, model: str, reuse: bool) -> Drafted:
    folder = OUTPUT / call.stem
    policy_path, run_path, review_path = folder / "policy.json", folder / "run.json", folder / "review.json"
    if reuse and policy_path.exists():
        policy = Policy.model_validate_json(policy_path.read_text())
        meta = RunMeta.model_validate_json(run_path.read_text())
        review = ReviewRecord.model_validate_json(review_path.read_text())
        return Drafted(policy, meta, print_policy(policy, call.stem), review)
    drafted = draft_and_check(call.read_text(), call.stem, model)
    policy_path.write_text(drafted.policy.model_dump_json(indent=2) + "\n")
    run_path.write_text(drafted.meta.model_dump_json(indent=2) + "\n")
    review_path.write_text(drafted.review.model_dump_json(indent=2) + "\n")
    return drafted


def build_policy(call: Path, model: str, reuse: bool) -> tuple[Policy, checks.PolicyResult, ReviewRecord]:
    drafted = load_or_draft(call, model, reuse)
    policy, printed = drafted.policy, drafted.printed
    filled = checks.sections_filled(policy)
    result = checks.PolicyResult(
        slug=call.stem,
        organization=policy.organization,
        pages=printed.pages,
        page_fill=printed.page_fill,
        sections_filled=sum(filled.values()),
        sections_total=len(filled),
        unfilled_sections=[s for s, ok in filled.items() if not ok],
        untraced_names=checks.untraced_names(policy, call.read_text()),
        open_questions=len(policy.open_questions),
        run=drafted.meta,
        fidelity_first=FidelityCounts.of(drafted.review.first),
        fidelity_final=FidelityCounts.of(drafted.review.final),
        **checks.reading_level(policy).model_dump(),
    )
    print(
        f"{call.stem}: {result.pages} page(s), fill {result.page_fill}, grade {result.flesch_kincaid_grade}, "
        f"{result.sections_filled}/{result.sections_total} sections, final check {result.fidelity_final.summary()}, "
        f"draft {drafted.meta.draft.seconds}s ${drafted.meta.draft.cost_usd}, "
        f"check {drafted.meta.check.seconds}s ${drafted.meta.check.cost_usd}"
    )
    return policy, result, drafted.review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model id")
    parser.add_argument(
        "--reuse", action="store_true", help="Re-render and re-check saved policies instead of calling the model"
    )
    parser.add_argument(
        "--skip-published", action="store_true", help="Don't download and measure the published templates"
    )
    parser.add_argument("calls", nargs="*", type=Path, help="Call notes to build (default: every file in calls/)")
    args = parser.parse_args()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    build_template_pages()
    built = [build_policy(call, args.model, args.reuse) for call in args.calls or sorted(CALLS.glob("*.md"))]
    write_reports(OUTPUT, built)
    if not args.skip_published:
        ours = [published.measure_pdf(p.organization, OUTPUT / r.slug / "policy.pdf") for p, r, _ in built]
        write_published(OUTPUT, ours + published.measure_published(PROJECT / ".cache" / "published"))
