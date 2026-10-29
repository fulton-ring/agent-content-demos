"""The pipelines and the scoring that the three notebooks share.

Copied from messy-document-parsing/pipelines.py (#136), with seven changes:
- a Task can carry its own table rules, since FinTabNet's key keeps header, group and total rows that #136's drops;
- a Runner can read Docling's saved output from another run's folder, so Docling (deterministic) runs once;
- Reducto Deep Extract, Extract with its agentic loop on ($40 per 1,000 pages);
- score_table can skip cells that are empty in the key, so a blank cell left blank doesn't count as a right answer;
- a null from Reducto Extract, where the schema asks for a string, is read as empty instead of crashing the run;
- Reducto's seconds are its own reported duration, not our clock, which also counted waiting for a slot;
- fresh_copies, because Reducto returns a cached answer for a file it has seen, so a second run needs new bytes.
"""

import asyncio
import io
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import jiwer
import pypdfium2 as pdfium
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DoclingDocument, TableItem
from pydantic import BaseModel, Field
from pydantic_ai import BinaryContent
from rapidfuzz import fuzz
from reducto import Reducto
from reducto.types.formatting_param import FormattingParam
from reducto.types.instructions_param import InstructionsParam
from reducto.types.settings_param import SettingsParam

import model_call


@dataclass(frozen=True)
class Task:
    name: str
    pdf: Path
    kind: Literal["table", "fields", "text"]
    ask: str
    pages: tuple[int, ...]  # the PDF pages the answer is on, 1-based
    where: str = ""  # a hint added to the prompt, such as "It is on PDF page 25."
    rules: str = ""  # replaces the table rules below, when a key keeps rows they leave out


@dataclass
class Result:
    output: dict[str, Any] | None
    usd: float = 0.0
    seconds: float = 0.0
    docling_seconds: float = 0.0
    pages_read: int = 0
    error: str = ""


@dataclass
class Runner:
    """Where answers are saved, how many calls run at once, and which model reads."""

    out: Path
    model: str = model_call.FLASH
    slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(8))
    docling_lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one Docling conversion at a time
    docling_out: Path | None = None  # where Docling's saved output is, if not under `out`


class Table(BaseModel):
    """One table's data rows, joined across pages if it continues."""

    rows: list[list[str]] = Field(description="Each data row as its cells, left to right, exactly as printed.")


class Line(BaseModel):
    line: str = Field(description="The form's line number, such as 5a or 17.")
    amount: str = Field(description="The amount written on the line, or '' if none.")


class Fields(BaseModel):
    """Amounts on a form's numbered lines."""

    lines: list[Line]


class Transcript(BaseModel):
    """The typed text of a page."""

    text: str


OUTPUT_TYPES: dict[str, type[BaseModel]] = {"table": Table, "fields": Fields, "text": Transcript}
INSTRUCTIONS = (
    "You read scanned and printed documents. Report only what is printed or written. Never infer, compute or fill in "
    "a value."
)


def prompt(task: Task) -> str:
    if task.kind != "table":
        return f"{task.ask} {task.where}".strip()
    rules = task.rules or (
        "Give its data rows only, each as its cells from left to right in the column order given. Leave out header "
        "rows, rows that only name a group, subtotal and total rows, carried-forward lines, and footnote markers. Join "
        "a cell's wrapped lines with spaces. Copy numbers as printed. An empty cell is ''."
    )
    return f"Read the table: {task.ask}. {task.where} If it continues on other pages, join its parts in order. {rules}"


def page_png(pdf: Path, page: int) -> BinaryContent:
    image = pdfium.PdfDocument(pdf)[page - 1].render(scale=150 / 72).to_pil().convert("RGB")
    out = io.BytesIO()
    image.save(out, "PNG")
    return BinaryContent(out.getvalue(), media_type="image/png")


def docling(task: Task, out: Path) -> tuple[DoclingDocument, float]:
    """Docling on the task's pages, as in #128: Tesseract OCR, table structure on. Saved, so it runs once."""
    saved, timing = out / "docling" / f"{task.name}.json", out / "docling" / f"{task.name}.seconds"
    if not saved.exists():
        options = PdfPipelineOptions(
            do_ocr=True, ocr_options=TesseractCliOcrOptions(lang=["eng"]), do_table_structure=True
        )
        converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
        t0 = time.time()
        document = converter.convert(task.pdf, page_range=(min(task.pages), max(task.pages))).document
        saved.parent.mkdir(parents=True, exist_ok=True)
        document.save_as_json(saved)
        timing.write_text(f"{time.time() - t0:.1f}")
    return DoclingDocument.load_from_json(saved), float(timing.read_text())


async def _ask(run: Runner, pipeline: str, task: Task, call: str, parts: list[Any]) -> Result:
    saved = run.out / "answers" / run.model.split("/")[-1] / pipeline / f"{task.name}-{call}.json"
    try:
        answer = await model_call.ask(saved, OUTPUT_TYPES[task.kind], INSTRUCTIONS, parts, run.slots, run.model)
    except Exception as e:  # the call failed every attempt; that's a result to report, not a crash
        return Result(None, error=f"{type(e).__name__}: {e!s:.200}")
    return Result(answer["output"], usd=answer["usd"], seconds=answer["seconds"])


async def docling_alone(task: Task, run: Runner) -> Result:
    """Every Docling table on the task's pages, joined with header rows kept; or its Markdown for a transcript."""
    async with run.docling_lock:
        document, seconds = await asyncio.to_thread(docling, task, run.docling_out or run.out)
    result = Result(None, docling_seconds=seconds, pages_read=len(task.pages))
    if task.kind == "fields":
        result.error = "Docling has no way to map handwriting to form lines without a model"
        return result
    if task.kind == "text":
        result.output = {"text": document.export_to_markdown()}
        return result
    rows: list[list[str]] = []
    for item, _level in document.iterate_items():
        if isinstance(item, TableItem) and item.prov and item.prov[0].page_no in task.pages:
            frame = item.export_to_dataframe(document)
            rows += [[str(c) for c in frame.columns], *[[str(c) for c in r] for r in frame.values.tolist()]]
    result.output = {"rows": rows}
    return result


async def vlm_whole_pdf(task: Task, run: Runner) -> Result:
    data = task.pdf.read_bytes()
    pages = len(pdfium.PdfDocument(task.pdf))
    result = await _ask(
        run, "vlm-whole-pdf", task, "all", [prompt(task), BinaryContent(data, media_type="application/pdf")]
    )
    result.pages_read = pages
    return result


async def vlm_page_by_page(task: Task, run: Runner) -> Result:
    """Each page read on its own, then the answers stitched together in page order."""
    note = "You are shown one page. Give only what is on this page; if none of it is, return nothing."
    calls = [
        _ask(run, "vlm-page-by-page", task, f"p{p}", [f"{prompt(task)} {note}", page_png(task.pdf, p)])
        for p in task.pages
    ]
    parts = await asyncio.gather(*calls)
    failed = [r.error for r in parts if r.error]
    stitched: dict[str, Any] = {"rows": [], "lines": [], "text": ""}
    for part in parts:
        if part.output:
            stitched["rows"] += part.output.get("rows", [])
            stitched["lines"] += part.output.get("lines", [])
            stitched["text"] += " " + part.output.get("text", "")
    return Result(
        stitched if not failed else None,
        usd=sum(r.usd for r in parts),
        seconds=sum(r.seconds for r in parts),
        pages_read=len(task.pages),
        error="; ".join(failed),
    )


async def docling_then_vlm(task: Task, run: Runner) -> Result:
    """Docling's Markdown of each page next to the page image."""
    async with run.docling_lock:
        document, seconds = await asyncio.to_thread(docling, task, run.docling_out or run.out)
    parts: list[Any] = [prompt(task)]
    for p in task.pages:
        parts += [f"--- PDF page {p}, Docling's Markdown ---\n{document.export_to_markdown(page_no=p)}"]
        parts += [page_png(task.pdf, p)]
    result = await _ask(run, "docling-then-vlm", task, "all", parts)
    result.docling_seconds, result.pages_read = seconds, len(task.pages)
    return result


# Reducto's list prices per page from 2026-09-01 (docs.reducto.ai/reference/credit-usage): Parse r-1 $10 and Extract
# $20 per 1,000 pages. The API reports pages, not dollars, so cost is pages times these.
REDUCTO_USD_PER_PAGE = {"parse": 0.010, "extract": 0.020, "deep-extract": 0.040}
Endpoint = Literal["parse", "extract", "deep-extract"]
REDUCTO_ATTEMPTS = 3


def _reducto_call(task: Task, endpoint: Endpoint) -> dict[str, Any]:
    """One Reducto call on the task's pages, with Parse's r-1 model. Uploads the PDF first. Raises on failure."""
    client = Reducto()
    upload = client.upload(file=task.pdf)
    pages: SettingsParam = {"model": "r-1", "page_range": {"start": min(task.pages), "end": max(task.pages)}}
    if endpoint == "parse":
        tables: FormattingParam = {"table_output_format": "json"}
        response = client.parse.run(input=upload.file_id, settings=pages, formatting=tables)
    else:
        schema = OUTPUT_TYPES[task.kind].model_json_schema()
        instructions: InstructionsParam = {"schema": schema, "system_prompt": f"{INSTRUCTIONS} {prompt(task)}"}
        response = client.extract.run(
            input=upload.file_id,
            instructions=instructions,
            parsing={"settings": pages},
            settings={"deep_extract": endpoint == "deep-extract"},
        )
    answer = response.model_dump(mode="json")
    assert answer["result"] is not None, f"Reducto {endpoint} returned no result"
    return answer


async def _reducto(task: Task, run: Runner, endpoint: Endpoint) -> tuple[dict[str, Any], Result]:
    """Reducto's answer, saved like the model's so a re-run reuses it, with its cost at list price."""
    saved = run.out / "answers" / "reducto" / endpoint / f"{task.name}.json"
    if not saved.exists():
        if not os.environ.get("REDUCTO_API_KEY"):
            return {}, Result(None, error="REDUCTO_API_KEY isn't set")
        t0, error = time.time(), ""
        for attempt in range(REDUCTO_ATTEMPTS):
            try:
                async with run.slots:
                    answer = await asyncio.to_thread(_reducto_call, task, endpoint)
                break
            except Exception as e:  # rate limits, server errors; reported after the last attempt
                error = f"{type(e).__name__}: {e!s:.200}"
                await asyncio.sleep(10 * (attempt + 1))
        else:
            return {}, Result(None, error=error)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps({"seconds": time.time() - t0, "answer": answer}))
    stored = json.loads(saved.read_text())
    pages = stored["answer"]["usage"]["num_pages"]
    # Reducto's own processing time; our clock also counts time spent waiting for a free slot.
    seconds = stored["answer"].get("duration") or stored["seconds"]
    result = Result(None, usd=pages * REDUCTO_USD_PER_PAGE[endpoint], seconds=seconds, pages_read=pages)
    return stored["answer"], result


def _cells(table_json: str) -> list[list[str]]:
    """A Parse table block's JSON rows, with the HTML tags it puts in cells (<b>, <sup>) dropped."""
    return [[re.sub(r"<[^>]+>", "", str(c)) for c in row] for row in json.loads(table_json)]


async def reducto_parse(task: Task, run: Runner) -> Result:
    """Every table Reducto Parse finds on the task's pages, joined with header rows kept, as for Docling alone."""
    answer, result = await _reducto(task, run, "parse")
    if not answer:
        return result
    if task.kind == "fields":
        result.error = "Parse returns blocks, not form lines; Extract fills them"
        return result
    blocks = [b for chunk in answer["result"]["chunks"] for b in chunk["blocks"]]
    if task.kind == "text":
        result.output = {"text": " ".join(b["content"] for b in blocks)}
    else:
        result.output = {"rows": [row for b in blocks if b["type"] == "Table" for row in _cells(b["content"])]}
    return result


async def reducto_extract(task: Task, run: Runner, endpoint: Endpoint = "extract") -> Result:
    """Reducto Extract, given the same schema and prompt as Gemini."""
    answer, result = await _reducto(task, run, endpoint)
    if not answer:
        return result
    output = answer["result"][0] if isinstance(answer["result"], list) else answer["result"]
    # Extract sometimes gives null where the schema asks for a string, for a line or cell it found empty.
    for line in output.get("lines") or []:
        line["amount"] = line["amount"] if line.get("amount") is not None else ""
    if output.get("rows"):
        output["rows"] = [[c if c is not None else "" for c in row] for row in output["rows"]]
    result.output = OUTPUT_TYPES[task.kind].model_validate(output).model_dump()
    return result


PIPELINES: dict[str, Callable[[Task, Runner], Awaitable[Result]]] = {
    "Docling alone": docling_alone,
    "Gemini, whole PDF": vlm_whole_pdf,
    "Gemini, page by page": vlm_page_by_page,
    "Docling, then Gemini": docling_then_vlm,
    "Reducto Parse": reducto_parse,
    "Reducto Extract": reducto_extract,
    "Reducto Deep Extract": lambda task, run: reducto_extract(task, run, "deep-extract"),
}


def norm(value: Any) -> str:
    """A cell in a form that compares fairly: numbers by value and sign, dashes and leaders as empty, text loosely."""
    text = re.sub(r"\s+", "", str(value)).lower()
    text = re.sub(
        "[\u00b9\u00b2\u00b3\u2070-\u2079]", "", text
    )  # a footnote marker kept as a superscript, as Reducto does
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    if re.fullmatch(r"[-.…_]*", text):
        return ""
    number = re.fullmatch(r"([(<]?)(-?)\$?(\d[\d,]*\.?\d*|\.\d+)%?([)>]?)", text)
    if number:
        try:
            amount = Decimal(number.group(3).replace(",", ""))
        except InvalidOperation:
            return text
        negative = bool(number.group(2)) or (number.group(1) + number.group(4) in ("()", "<>"))
        amount = -amount if negative and amount else amount
        return "#" + format(amount.normalize(), "f")
    return re.sub(r"[^a-z0-9.%?]+", "", re.sub(r"\.{2,}", "", text))  # leader dots after a row label


def same(found: Any, key: str | list[str]) -> bool:
    if isinstance(key, list):
        return any(same(found, k) for k in key)
    f, k = norm(found), norm(key)
    if f.startswith("#") or k.startswith("#") or not f or not k:
        return f == k
    return fuzz.ratio(f, k) >= 85


def score_table(found: list[list[str]], key: list[list[Any]], skip_empty: bool = False) -> dict[str, int]:
    """Each key row against the unused found row that agrees with it most, cell by cell in column order.

    A cell is right, wrong (a value is there but isn't the key's: the dangerous case, since it looks fine), or
    missing (blank, or its row wasn't found). Extra rows are found rows that match no key row. With skip_empty, a
    cell that is empty in the key isn't counted.
    """
    unused = list(range(len(found)))
    counts = {"cells": 0, "right": 0, "wrong": 0, "missing": 0, "extra_rows": 0}
    for k in key:
        counted = [j for j, kc in enumerate(k) if not (skip_empty and norm(kc) == "")]
        counts["cells"] += len(counted)

        def agree(i: int, k: list[Any] = k) -> int:
            return sum(same(f, kc) for f, kc in zip(found[i], k, strict=False))

        best = max(unused, key=agree, default=None)
        if best is None or agree(best) == 0:
            counts["missing"] += len(counted)
            continue
        unused.remove(best)
        row = found[best]
        for j in counted:
            f = row[j] if j < len(row) else ""
            outcome = "right" if same(f, k[j]) else "missing" if norm(f) == "" else "wrong"
            counts[outcome] += 1
    counts["extra_rows"] = len(unused)
    return counts


def score_fields(found: list[dict[str, str]], key: dict[str, str]) -> dict[str, int]:
    def line_id(text: str) -> str:
        return re.sub(r"[^0-9a-z]", "", text.lower().replace("line", ""))

    by_line = {line_id(f["line"]): f["amount"] for f in found}
    counts = {"cells": len(key), "right": 0, "wrong": 0, "missing": 0, "extra_rows": 0}
    for line, amount in key.items():
        f = by_line.get(line_id(line), "")
        counts["right" if same(f, amount) else "missing" if norm(f) == "" else "wrong"] += 1
    return counts


def word_error_rate(found: str, key: str) -> float:
    def words(text: str) -> str:
        text = re.sub(r"-\s*", "", text.lower())
        return " ".join(re.sub(r"[^a-z0-9%]+", " ", text).split())

    return float(jiwer.wer(words(key), words(found) or "-"))


async def run_all(runner: Runner, pipelines: list[str], tasks: list[Task]) -> dict[tuple[str, str], Result]:
    """Every pipeline on every task, keyed by (task name, pipeline)."""
    jobs = [(t, p) for t in tasks for p in pipelines]
    results = await asyncio.gather(*(PIPELINES[p](t, runner) for t, p in jobs))
    return {(t.name, p): r for (t, p), r in zip(jobs, results, strict=True)}


def tally(scores: list[dict[str, int]], results: list[Result]) -> dict[str, float]:
    """Cells summed over tasks, with answers that failed or came back empty, and cost and seconds per page.

    An empty answer is the silent failure: no error, but not one value where the key has some.
    """
    total: dict[str, float] = {k: sum(s[k] for s in scores) for k in ("cells", "right", "wrong", "missing")}
    pages = max(sum(r.pages_read for r in results), 1)
    total["errors"] = sum(bool(r.error) for r in results)
    total["empty"] = sum(s["right"] + s["wrong"] == 0 and not r.error for s, r in zip(scores, results, strict=True))
    total["usd"] = sum(r.usd for r in results)
    total["usd_per_page"] = total["usd"] / pages
    total["seconds_per_page"] = sum(r.seconds + r.docling_seconds for r in results) / pages
    return total


def two_run_table(
    pipelines: list[str],
    names: list[str],
    score: Callable[[str, Result], dict[str, int]],
    runs: list[dict[tuple[str, str], Result]],
) -> tuple[str, dict[tuple[str, int], dict[str, float]]]:
    """A Markdown table with one row per pipeline and each run's figures side by side, and the tallies behind it."""
    tallies: dict[tuple[str, int], dict[str, float]] = {}
    lines = [
        "| Pipeline | Right, run 1 | Right, run 2 | Wrong | Missing | Empty answers | Errors | Cost per page "
        "| Seconds per page |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for p in pipelines:
        for i, run in enumerate(runs):
            if (names[0], p) in run:
                tallies[(p, i)] = tally([score(n, run[(n, p)]) for n in names], [run[(n, p)] for n in names])
        t = [tallies[(p, i)] for i in range(len(runs)) if (p, i) in tallies]

        def both(k: str, t: list[dict[str, float]] = t) -> str:
            return " / ".join(f"{x[k]:g}" for x in t)

        right = [f"{x['right'] / max(x['cells'], 1):.1%}" for x in t] + ["(once)"] * (2 - len(t))
        lines.append(
            f"| {p} | {right[0]} | {right[1]} | {both('wrong')} | {both('missing')} | {both('empty')} "
            f"| {both('errors')} | ${t[0]['usd_per_page']:.4f} | {t[0]['seconds_per_page']:.1f} |"
        )
    return "\n".join(lines), tallies


def fresh_copies(tasks: list[Task], folder: Path) -> list[Task]:
    """The tasks on copies of their PDFs with a comment line added at the end: the same pages, a different file.

    Reducto answers a file it has already seen from a cache, in about 0.2 seconds, so a second run on the same bytes
    is the first run again. A PDF reader ignores a comment after the end of the file.
    """
    folder.mkdir(parents=True, exist_ok=True)
    copies = []
    for task in tasks:
        copy = folder / task.pdf.name
        if not copy.exists():
            copy.write_bytes(task.pdf.read_bytes() + b"\n% second run\n")
        copies.append(replace(task, pdf=copy))
    return copies
