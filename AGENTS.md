# AGENTS.md

Rules for every coding agent that works in this repo. Read this file first, then `README.md`, then your issue. These rules win over any other instructions on how to write code here.

## What this repo is

- Working demos and spikes that back Fulton Ring articles.
- One folder per project, named in a few lowercase words joined by hyphens, for example `k1-extraction-review-queue/`.
- Each project's work happens on a branch `spike/<folder>` with a PR into `main` titled `Spike: <proposal title>` that links its issue.
- Never touch another project's folder.

## How work is assigned

- Work arrives as a GitHub issue. The label `agent:spike` means a Claude worker owns it.
- Work only the issue you were given. Read the issue and all its comments before you start.
- If the issue has no plan, comment a short one before you start. If another worker commented on the issue in the last 2 hours, stop.
- Split off anything big or separable as a sub-issue of your issue, saying what's needed and what done means. Leave it unlabeled; the Spike manager assigns it.
- If a decision only a founder can make blocks you, ask it on the issue, add the label `needs:founder`, push what you have and stop.
- Commit and push work in progress at least every hour.
- Finish by commenting on the issue with what was built, the numbers, what failed, and either `Ready for review` or `Stopped at:` with what's left.

## The repo is public

- Use synthetic or public data only.
- Never commit client documents, personal information, credentials or API keys.
- Real public documents (such as published sample tax forms) are downloaded when the demo runs, not committed.
- Secrets come only from environment variables (for example `OPENROUTER_API_KEY`). Never print or log them.
- Use no paid services unless the issue names one.

## What to build

- Build the smallest thing that proves or disproves the issue's question.
- One command runs it.
- Measure it: accuracy against a known answer key, timings, cost and failure cases.
- Keep what didn't work as well as what did, and report both.
- Each project folder has:
  - `README.md`: what it shows, how to run it, where the data comes from, results with numbers, and what it doesn't show.
  - The code.
  - Sample outputs and screenshots.
- Before saying `Ready for review`, run it from a clean checkout following only the README. Confirm the numbers you report come from that run, not from a hard-coded table.

## Code style and tooling

### Python

- Use `uv` for environments and dependencies, with a `pyproject.toml` per project.
- Lint and format with `ruff` (`ruff check` and `ruff format`).
- Type-check with `ty`.
- Put type hints on every function.
- `ruff` and `ty` must both pass with zero warnings before you push.

### JavaScript and TypeScript

- Lint and format with `biome`.
- Use TypeScript in strict mode.
- `biome` and `tsc` must pass with zero warnings before you push.

### Clean code

- Small functions that do one thing.
- Names that say what things are.
- No dead code and no commented-out code.
- No duplication worth naming; extract it.
- Comments only where the why isn't obvious.

### Architecture

- Keep I/O separate from logic, so the core can be tested without the network or the filesystem.
- Keep module boundaries clear. Dependencies point inward: I/O and entry points depend on the core, never the reverse.

### Twelve-factor

- Config comes from environment variables only. No hard-coded paths, URLs or keys.
- Declare and pin every dependency (`uv.lock`, `package-lock.json`).
- Keep no state in the process between runs. Anything that must persist goes to a file or service named by config.
- Log to stdout.
- One command builds and runs the project.
- Keep dev runs and demo runs as alike as possible.

### Power of Ten, adapted

NASA/JPL's "Power of Ten" rules for safety-critical code, adapted for Python and TypeScript:

1. **Simple control flow.** No recursion, no `goto`-like tricks such as exceptions used for normal control flow. Prefer early returns over deep nesting.
2. **Bounded loops.** Every loop, retry and pagination has a fixed upper bound. Retries use a set maximum count and backoff.
3. **Bounded memory.** No unbounded growth of in-memory collections. Stream or batch large inputs, and cap caches and queues.
4. **Short functions.** A function fits on one screen, about 60 lines.
5. **Check inputs and invariants.** Validate arguments at boundaries and assert invariants with `assert` or explicit errors. Fail loudly on bad data.
6. **Smallest scope.** Declare data in the smallest scope that needs it. No module-level mutable state.
7. **Check every result.** Check every return value and every external call: HTTP status, subprocess exit code, file existence, and model output parsed against a schema (for example with Pydantic or Zod). Never ignore an error.
8. **Minimal metaprogramming.** Keep decorators, dynamic imports, monkey-patching, `eval` and reflection to a minimum.
9. **Plain data access.** Keep indirection shallow. Avoid chains of dynamic attribute access, and use typed objects instead of loose dicts where the shape is known.
10. **Zero warnings.** Linters and type checkers run at their strict settings and report nothing.

### Tests

- Tests cover behavior and production risk.
- Don't write tests that freeze prose or output text.
