"""One command: render the template and call questions, fill a policy from each call, fit it to a page, check it."""

import argparse
from pathlib import Path

from policy_builder import checks, published, render
from policy_builder.fill import DEFAULT_MODEL, Drafter, RunMeta
from policy_builder.report import write_published, write_reports
from policy_builder.schema import Policy

PROJECT = Path(__file__).resolve().parents[2]
CALLS = PROJECT / "calls"
OUTPUT = PROJECT / "output"
SCREENSHOTS = PROJECT / "screenshots"
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


def draft_to_fit(call_notes: str, slug: str, model: str) -> tuple[Policy, RunMeta, render.Printed]:
    """Fill the template, then ask for a shorter version while it spills past one page."""
    drafter = Drafter(PROJECT, model)
    policy = drafter.fill(call_notes)
    printed = print_policy(policy, slug)
    drafter.meta.first_draft_pages, drafter.meta.first_draft_fill = printed.pages, printed.page_fill
    while printed.pages > 1 and drafter.meta.shorten_passes < MAX_SHORTEN_PASSES:
        policy = drafter.shorten(call_notes, policy, printed.page_fill)
        printed = print_policy(policy, slug)
    return policy, drafter.meta, printed


def load_or_draft(call: Path, model: str, reuse: bool) -> tuple[Policy, RunMeta, render.Printed]:
    folder = OUTPUT / call.stem
    policy_path, run_path = folder / "policy.json", folder / "run.json"
    if reuse and policy_path.exists():
        policy = Policy.model_validate_json(policy_path.read_text())
        return policy, RunMeta.model_validate_json(run_path.read_text()), print_policy(policy, call.stem)
    policy, meta, printed = draft_to_fit(call.read_text(), call.stem, model)
    policy_path.write_text(policy.model_dump_json(indent=2) + "\n")
    run_path.write_text(meta.model_dump_json(indent=2) + "\n")
    return policy, meta, printed


def build_policy(call: Path, model: str, reuse: bool) -> tuple[Policy, checks.PolicyResult]:
    policy, meta, printed = load_or_draft(call, model, reuse)
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
        **checks.reading_level(policy).model_dump(),
        **meta.model_dump(),
    )
    print(
        f"{call.stem}: {result.pages} page(s), fill {result.page_fill} (first draft {result.first_draft_fill}), "
        f"grade {result.flesch_kincaid_grade}, {result.sections_filled}/{result.sections_total} sections, "
        f"{result.seconds}s, ${result.cost_usd}"
    )
    return policy, result


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
    SCREENSHOTS.mkdir(exist_ok=True)
    build_template_pages()
    built = [build_policy(call, args.model, args.reuse) for call in args.calls or sorted(CALLS.glob("*.md"))]
    write_reports(OUTPUT, built)
    if not args.skip_published:
        ours = [published.measure_pdf(p.organization, OUTPUT / r.slug / "policy.pdf") for p, r in built]
        write_published(OUTPUT, ours + published.measure_published(PROJECT / ".cache" / "published"))
