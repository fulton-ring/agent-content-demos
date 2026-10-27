import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import asyncio
    import hashlib
    import io
    import json
    import os
    import random
    import urllib.request
    from dataclasses import dataclass, field
    from pathlib import Path
    from typing import cast

    import marimo as mo
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas

    import model_call
    from pipelines import PIPELINES, Result, Runner, Task, same, score_table

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("MESSY_OUTPUT_DIR", HERE / "output")) / "synthetic"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 2. Tables broken on purpose

    **The question.** Real documents mix many problems at once, so notebook 1 can say *that* a pipeline failed but
    not always *why*. Here each document has one table broken in one known way, so each failure mode gets its own
    score. Every document is made by this notebook from seeded, made-up data (a fictional county's capital projects),
    so the answer key is exact.

    **Twelve failure modes**, three documents each, plus three with everything at once. In each mode the third
    document goes through the K-1 spike's scan degrader (an office scan), so clean and scanned can be compared;
    mode 11 is scan damage itself.
    """)
    return


@app.cell
def _():
    # Reenie Beanie, a handwriting font under the SIL Open Font License, for the handwritten corrections (mode 12).
    _font_url = "https://fonts.gstatic.com/s/reeniebeanie/v22/z7NSdR76eDkaJKZJFkkjuvWxbP0.ttf"
    _font_sha = "f1fb0e13ec7cf2cc4d66723e70e7adcf1fd81c1b7d9218f0aada5ef7a5af7372"
    HAND_FONT = OUT / "ReenieBeanie.ttf"
    OUT.mkdir(parents=True, exist_ok=True)
    if not HAND_FONT.exists() or hashlib.sha256(HAND_FONT.read_bytes()).hexdigest() != _font_sha:
        with urllib.request.urlopen(_font_url, timeout=60) as _r:
            _data = _r.read()
        assert hashlib.sha256(_data).hexdigest() == _font_sha, f"{_font_url} has changed"
        HAND_FONT.write_bytes(_data)
    pdfmetrics.registerFont(TTFont("Hand", str(HAND_FONT)))
    return (HAND_FONT,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The data

    Each table is a list of projects: a project number and name (sometimes with a long description that wraps),
    a fund, and amounts. The last amount column is a variance, which is negative about a quarter of the time. The
    key is the data as generated, so it never depends on how the page was drawn.
    """)
    return


@app.cell
def _():
    PLACES = ["Mill Road", "Cedar Creek", "Harbor St", "Route 9", "Oak Hill", "North Yard", "Elm Ave", "Pine Ridge"]
    WORKS = ["culvert replacement", "bridge deck repair", "storm drain lining", "pump station upgrade", "sidewalk",
             "water main", "levee survey", "signal retiming", "salt dome", "roof replacement"]  # fmt: skip
    FUNDS = ["General", "Water", "Sewer", "Roads", "Grants"]
    LONG = ", including design, permitting, utility relocation and construction oversight for phase {}"

    @dataclass
    class Row:
        cells: dict[str, str]  # column: value as printed in plain form; negatives as -1,234
        footnote: dict[str, str] = field(default_factory=dict)  # column: a footnote marker glued to the number
        corrected: dict[str, str] = field(default_factory=dict)  # column: the handwritten replacement

    def money(value: int) -> str:
        return f"{value:,}"

    def make_rows(rng: random.Random, n: int, amounts: list[str], wrap: bool = False) -> list[Row]:
        numbers = rng.sample(range(1000, 9999), n)
        rows = []
        for number in numbers:
            name = f"P-{number} {rng.choice(PLACES)} {rng.choice(WORKS)}"
            if wrap and rng.random() < 0.5:
                name += LONG.format(rng.randint(2, 4))
            cells = {"Project": name, "Fund": rng.choice(FUNDS)}
            for column in amounts:
                cells[column] = money(rng.randint(1_000, 950_000))
            if "Variance" in amounts:
                cells["Variance"] = money(rng.randint(-90_000, 250_000))
            rows.append(Row(cells))
        return rows

    return Row, make_rows, money


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Drawing a page

    A page is a list of blocks: a title, a paragraph, a figure, or a piece of a table. A table piece says which rows
    and which columns it shows, and how: with or without rules, a header or not, a two-level header, values drifting
    off their columns, subtotals, notation such as `(1,234)` and `—`, and handwritten corrections. Each failure mode
    below is just a different arrangement of these blocks.
    """)
    return


@app.cell
def _(Row, money):
    @dataclass
    class Piece:
        rows: list[Row]
        columns: list[str]
        header: bool = True
        rules: bool = True
        drift: float = 0.0  # how far values wander from their column, as a share of its width
        groups: dict[int, str] = field(default_factory=dict)  # a group row before row i
        spans: list[tuple[str, int]] = field(default_factory=list)  # a top header row: (text, columns spanned)
        subtotal_every: int = 0
        carried: str = ""  # "forward" at the end of the piece, "brought" at its start
        header_after: int = 0  # repeat the header after this many rows
        notation: bool = False
        merge_fund: bool = False  # print the fund once per run of equal funds
        lines: list | None = None  # draw exactly these lines instead (mode 2's cut mid-row)
        opening: dict[str, int] = field(default_factory=dict)  # running totals brought forward from a page before

    WIDTH, LEFT, LINE = 504.0, 54.0, 13.0

    def widths(columns: list[str]) -> list[float]:
        if columns[0] != "Project":
            return [WIDTH / len(columns)] * len(columns)
        return [190.0] + [(WIDTH - 190.0) / (len(columns) - 1)] * (len(columns) - 1)

    def printed(value: str, notation: bool) -> str:
        if not notation or not value or value == "n/a":
            return value
        if value == "0":
            return "—"
        return f"({value[1:]})" if value.startswith("-") else value

    def wrap(text: str, width: float, size: float) -> list[str]:
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if pdfmetrics.stringWidth(trial, "Helvetica", size) > width - 6 and line:
                lines.append(line)
                line = word
            else:
                line = trial
        return [*lines, line]

    def visual_lines(piece: Piece) -> list[tuple[str, object]]:
        """The piece as drawn lines: ("header", None), ("group", text), ("row", (row, label line, first?)), ..."""
        out: list[tuple[str, object]] = [("header", None)] if piece.header else []
        if piece.carried == "brought":
            out.append(("total", "Brought forward"))
        label_width = widths(piece.columns)[0]
        for i, row in enumerate(piece.rows):
            if i in piece.groups:
                out.append(("group", piece.groups[i]))
            if piece.header_after and i == piece.header_after:
                out.append(("header", None))
            label = wrap(row.cells["Project"], label_width, 8) if piece.columns[0] == "Project" else [""]
            out += [("row", (row, text, n == 0, i)) for n, text in enumerate(label)]
            if piece.subtotal_every and (i + 1) % piece.subtotal_every == 0:
                out.append(("total", "Subtotal"))
        if piece.carried == "forward":
            out.append(("total", "Carried forward"))
        return out

    def draw_piece(c: Canvas, y: float, piece: Piece, lines: list[tuple[str, object]], rng: random.Random) -> float:
        ws = widths(piece.columns)
        xs = [LEFT + sum(ws[:i]) for i in range(len(ws) + 1)]
        top = y + LINE - 3
        totals = {col: piece.opening.get(col, 0) for col in piece.columns}
        for kind, item in lines:
            if kind == "header":
                if piece.spans:
                    c.setFont("Helvetica-Bold", 8)
                    start = 0
                    for text, span in piece.spans:
                        c.drawCentredString((xs[start] + xs[start + span]) / 2, y, text)
                        if text and piece.rules:
                            c.line(xs[start] + 4, y - 3, xs[start + span] - 4, y - 3)
                        start += span
                    y -= LINE
                c.setFont("Helvetica-Bold", 8)
                for col, x0, x1 in zip(piece.columns, xs, xs[1:], strict=False):
                    c.drawCentredString((x0 + x1) / 2, y, col.split(" ")[-1] if piece.spans else col)
                if piece.rules:
                    c.line(LEFT, y - 4, LEFT + WIDTH, y - 4)
            elif kind == "group":
                c.setFont("Helvetica-Bold", 8)
                c.drawString(LEFT + 3, y, str(item))
            elif kind == "total":
                c.setFont("Helvetica-Oblique", 8)
                c.drawString(LEFT + 3, y, str(item))
                for col, x1 in zip(piece.columns[1:], xs[2:], strict=False):
                    if col != "Fund":
                        c.drawRightString(x1 - 3, y, money(totals.get(col, 0)))
            else:
                row, label, first, index = cast(tuple, item)
                c.setFont("Helvetica", 8)
                if piece.columns[0] == "Project":
                    c.drawString(LEFT + 3, y, label)
                for col, x0, x1 in zip(piece.columns, xs, xs[1:], strict=False):
                    if col == "Project" or not first:
                        continue
                    value = row.cells.get(col, "")
                    if col == "Fund":
                        previous = piece.rows[index - 1].cells["Fund"] if index else None
                        if not (piece.merge_fund and previous == value):
                            c.drawString(x0 + 3, y, value)
                        continue
                    shift = rng.uniform(-piece.drift, piece.drift) * (x1 - x0)
                    text = printed(value, piece.notation)
                    c.drawRightString(x1 - 3 + shift, y, text)
                    if col in row.footnote:
                        c.setFont("Helvetica", 5)
                        c.drawString(x1 - 2 + shift, y + 3, row.footnote[col])
                        c.setFont("Helvetica", 8)
                    if col in row.corrected:
                        c.line(x1 - 4 - pdfmetrics.stringWidth(text, "Helvetica", 8) + shift, y + 3, x1 - 2, y + 3)
                        c.setFont("Hand", 15)
                        c.drawRightString(x1 + 2, y + 6, row.corrected[col])
                        c.setFont("Helvetica", 8)
                    number = value.replace(",", "")
                    if number.lstrip("-").isdigit():
                        totals[col] = totals.get(col, 0) + int(number)
            y -= LINE
        if piece.rules:
            for x in xs:
                c.line(x, top, x, y + LINE - 4)
            c.line(LEFT, top, LEFT + WIDTH, top)
            c.line(LEFT, y + LINE - 4, LEFT + WIDTH, y + LINE - 4)
        return y - 8

    def draw_document(pages: list[list[object]], seed: int) -> bytes:
        rng, out = random.Random(seed), io.BytesIO()
        c = Canvas(out, pagesize=letter, invariant=1)
        for page in pages:
            y = 740.0
            for block in page:
                if isinstance(block, Piece):
                    y = draw_piece(c, y, block, block.lines or visual_lines(block), rng)
                elif isinstance(block, tuple) and block[0] == "figure":
                    c.rect(LEFT + 60, y - 200, WIDTH - 120, 190)
                    c.setFont("Helvetica-Oblique", 9)
                    c.drawCentredString(LEFT + WIDTH / 2, y - 215, block[1])
                    y -= 235
                else:
                    bold = isinstance(block, tuple)
                    text = block[1] if bold else str(block)
                    c.setFont("Helvetica-Bold" if bold else "Helvetica", 10 if bold else 9)
                    for line in wrap(text, WIDTH * (0.85 if bold else 0.92), 8):
                        c.drawString(LEFT, y, line)
                        y -= 13
                    y -= 6
            c.showPage()
        c.save()
        return out.getvalue()

    return Piece, draw_document, visual_lines


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scanning

    The K-1 spike's degrader (copied from `k1-extraction-review-queue/1_documents.py`): level 1 is an office scan,
    level 2 a bad fax. Mode 11 adds a page turned 90 degrees, a 4 degree skew, and a RECEIVED stamp over the table.
    """)
    return


@app.cell
def _():
    def degrade(img: Image.Image, rng: random.Random, level: int) -> Image.Image:
        """Make a page look scanned. Level 0 is a clean print, 1 an office scan, 2 a bad fax or phone photo."""
        if level == 0:
            return img
        angle = (rng.uniform(0.3, 0.9) if level == 1 else rng.uniform(1.0, 1.8)) * rng.choice([-1, 1])
        img = img.convert("L").rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=255)
        scale, bilinear = 0.75 if level == 1 else 0.5, Image.Resampling.BILINEAR
        img = img.resize((int(img.width * scale), int(img.height * scale)), bilinear).resize(img.size, bilinear)
        arr = np.asarray(img).astype(np.float32)
        arr += np.random.default_rng(rng.randint(0, 2**31)).normal(0, 10 if level == 1 else 22, arr.shape)
        if level == 2:
            arr = arr * 0.85 + 30  # grey, low-contrast background
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        img = img.filter(ImageFilter.GaussianBlur(0.6 if level == 1 else 1.1))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=55 if level == 1 else 30)
        return Image.open(out)

    def stamp(img: Image.Image, rng: random.Random) -> Image.Image:
        """A RECEIVED date stamp, dark and half see-through, over the middle of the table."""
        layer = Image.new("L", img.size, 0)
        draw, w = ImageDraw.Draw(layer), img.width
        x, y = int(w * rng.uniform(0.35, 0.5)), int(img.height * rng.uniform(0.2, 0.35))
        font = ImageFont.load_default(size=int(w * 0.045))
        draw.rectangle((x, y, x + int(w * 0.38), y + int(w * 0.16)), outline=255, width=int(w * 0.006))
        draw.text((x + w * 0.03, y + w * 0.02), "RECEIVED", fill=255, font=font)
        draw.text((x + w * 0.03, y + w * 0.09), "MAR 14 2026", fill=255, font=font)
        layer = layer.rotate(rng.uniform(-12, 12), center=(x, y))
        grey = img.convert("L")
        return Image.composite(Image.new("L", img.size, 70), grey, layer.point(lambda v: int(v * 0.75)))

    def scan(pdf: bytes, seed: int, level: int, effect: str = "") -> bytes:
        rng, pages = random.Random(seed), []
        for page in pdfium.PdfDocument(pdf):
            img = page.render(scale=200 / 72).to_pil()
            if effect == "stamp":
                img = stamp(img, rng)
            if effect == "skew":
                img = img.convert("L").rotate(4, resample=Image.Resampling.BICUBIC, fillcolor=255)
            img = degrade(img, rng, level)
            if effect == "rotate":
                img = img.rotate(90, expand=True)
            pages.append(img.convert("RGB"))
        out = io.BytesIO()
        pages[0].save(out, "PDF", resolution=200, save_all=True, append_images=pages[1:])
        return out.getvalue()

    return (scan,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The twelve failure modes

    Each builder returns the pages, the key's columns and rows, and what to ask for. Read them in order; each is a
    few lines. Variant `v` (0, 1, 2) changes the details within a mode.
    """)
    return


@app.cell
def _(Piece, make_rows):
    Q = ["Budget", "Q1", "Q2", "Q3", "Q4", "Variance"]
    BASIC = ["Project", "Fund", *Q]
    TITLE = ("title", "Harlow County capital projects, fiscal year 2024 (dollars). Table 3.")
    PROSE = (
        "The county's capital program funds roads, water, sewer and buildings. Amounts are expenditures recorded in "
        "the general ledger by quarter. Variances compare the adopted budget with spending to date."
    )

    def m1_break(rng: random.Random, v: int) -> tuple:
        rows = make_rows(rng, 70, Q)
        cut = 44 + v
        return [[TITLE, PROSE, Piece(rows[:cut], BASIC)], [Piece(rows[cut:], BASIC, header=False)]], BASIC, rows

    def m2_split_row(rng: random.Random, v: int) -> tuple:
        rows = make_rows(rng, 34, Q, wrap=True)
        pages = [[TITLE, PROSE, Piece(rows, BASIC)]]
        return pages, BASIC, rows  # the page break is placed by split_lines below

    def m3_wrong_page(rng: random.Random, v: int) -> tuple:
        rows = make_rows(rng, 40, Q)
        a, b = rows[:22], rows[22:]
        part_b = ("title", f"Table 3 (continued from page {2 if v == 1 else 1})")
        other = [("title", "Notes on the capital program"), PROSE * 3, ("figure", "Figure 2. Spending by fund")]
        if v == 0:
            pages = [[TITLE, PROSE, Piece(a, BASIC)], other, [part_b, Piece(b, BASIC)]]
        elif v == 1:
            pages = [[part_b, Piece(b, BASIC)], [TITLE, PROSE, Piece(a, BASIC)]]
        else:
            note = "Table 3 continues in Appendix A, page 4."
            pages = [[TITLE, PROSE, Piece(a, BASIC), note], other, [PROSE * 4], [("title", "Appendix A"), part_b,
                     Piece(b, BASIC)]]  # fmt: skip
        return pages, BASIC, rows

    def m4_wide(rng: random.Random, v: int) -> tuple:
        months = ["Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Total"]
        rows = make_rows(rng, 30, months)
        left, right = ["Project", *months[:6]], months[6:]
        right = ["Project", *right] if v == 0 else right
        return [[TITLE, PROSE, Piece(rows, left)], [Piece(rows, right)]], ["Project", *months], rows

    def m5_drift(rng: random.Random, v: int) -> tuple:
        rows = make_rows(rng, 40, Q)
        piece = Piece(rows, BASIC, rules=False, drift=[0.1, 0.18, 0.15][v])
        return [[TITLE, PROSE, piece]], BASIC, rows

    def m6_columns_change(rng: random.Random, v: int) -> tuple:
        columns = [*BASIC, "Encumbered"] if v == 2 else BASIC
        rows = make_rows(rng, 70, [*Q, "Encumbered"] if v == 2 else Q)
        first = BASIC
        second = [
            ["Project", "Fund", "Budget", "Q2", "Q1", "Q4", "Q3", "Variance"],
            ["Project", "Fund", "Budget", "Q1", "Q2", "Q3", "Variance"],
            [*BASIC, "Encumbered"],
        ][v]
        return [[TITLE, PROSE, Piece(rows[:44], first)], [Piece(rows[44:], second)]], columns, rows

    def m7_merged(rng: random.Random, v: int) -> tuple:
        amounts = ["FY23 Budget", "FY23 Spent", "FY24 Budget", "FY24 Spent"]
        rows = sorted(make_rows(rng, 36, amounts), key=lambda r: r.cells["Fund"])
        columns = ["Project", "Fund", *amounts]
        spans = [("", 2), ("Fiscal year 2023", 2), ("Fiscal year 2024", 2)]
        groups = {i: f"{r.cells['Fund']} fund" for i, r in enumerate(rows) if i == 0 or rows[i - 1].cells["Fund"]
                  != r.cells["Fund"]}  # fmt: skip
        piece = Piece(rows, columns, spans=spans, groups=groups if v != 1 else {}, merge_fund=v >= 1)
        return [[TITLE, PROSE, piece]], columns, rows

    def m8_subtotals(rng: random.Random, v: int) -> tuple:
        rows = make_rows(rng, 60, Q)
        a = Piece(rows[:40], BASIC, subtotal_every=10, carried="forward", header_after=20 if v == 1 else 0)
        opening = {c: sum(int(r.cells[c].replace(",", "")) for r in rows[:40]) for c in Q}
        b = Piece(rows[40:], BASIC, subtotal_every=10, carried="brought", opening=opening)
        return [[TITLE, a], [b]], BASIC, rows

    def m9_notation(rng: random.Random, v: int) -> tuple:
        rows = make_rows(rng, 40, Q)
        for r in rows:
            for col in Q[1:]:
                roll = rng.random()
                if roll < 0.12:
                    r.cells[col] = "0"
                elif roll < 0.17:
                    r.cells[col] = "n/a"
                elif roll < 0.22:
                    r.cells[col] = ""
                elif roll < 0.3:
                    r.footnote[col] = rng.choice("1234")
                elif roll < 0.4 and not r.cells[col].startswith("-"):
                    r.cells[col] = "-" + r.cells[col]
        note = "1 Restated. 2 Includes grant match. 3 Estimate. 4 Unaudited. n/a: not applicable. —: zero."
        return [[TITLE, PROSE, Piece(rows, BASIC, notation=True), note]], BASIC, rows

    def m10_near_duplicate(rng: random.Random, v: int) -> tuple:
        rows = make_rows(rng, 18, Q)
        decoy = [type(r)({**r.cells, **{c: f"{int(int(r.cells[c].replace(',', '')) * rng.uniform(0.8, 1.2)):,}"
                 for c in Q[:-1]}}) for r in rows]  # fmt: skip
        t23 = [("title", "Table 2. Capital projects, fiscal year 2023"), Piece(decoy, BASIC)]
        t24 = [("title", "Table 3. Capital projects, fiscal year 2024"), Piece(rows, BASIC)]
        pages = [[*t23, *t24], [*t24, *t23], [[PROSE, *t24], [*t23]]][v]
        return (pages if v == 2 else [pages]), BASIC, rows

    def m11_scan_damage(rng: random.Random, v: int) -> tuple:
        rows = make_rows(rng, 30, Q)
        return [[TITLE, PROSE, Piece(rows, BASIC)]], BASIC, rows

    def m12_corrections(rng: random.Random, v: int) -> tuple:
        rows = make_rows(rng, 30, Q)
        for r in rng.sample(rows, 6):
            col = rng.choice(Q[:-1])
            r.corrected[col] = f"{rng.randint(1_000, 950_000):,}"
        return [[TITLE, PROSE, Piece(rows, BASIC)]], BASIC, rows

    def m13_everything(rng: random.Random, v: int) -> tuple:
        rows = make_rows(rng, 44, Q, wrap=True)
        for r in rows:
            if rng.random() < 0.15:
                r.cells["Variance"] = "0"
        for r in rng.sample(rows, 4):
            r.corrected["Q2"] = f"{rng.randint(1_000, 950_000):,}"
        a = Piece(rows[:24], BASIC, rules=False, drift=0.15, notation=True, subtotal_every=10)
        b = Piece(rows[24:], BASIC, header=False, rules=False, drift=0.15, notation=True, subtotal_every=10)
        return [[TITLE, PROSE, a], [("figure", "Figure 2. Spending by fund")], [b]], BASIC, rows

    MODES = {  # name: (builder, scan level for variants 0, 1, 2, scan effect per variant)
        "1. Page break, no repeated header": (m1_break, [0, 0, 1], ["", "", ""]),
        "2. Row split across the break": (m2_split_row, [0, 0, 1], ["", "", ""]),
        "3. Continuation on the wrong page": (m3_wrong_page, [0, 0, 1], ["", "", ""]),
        "4. Wide table cut in half": (m4_wide, [0, 0, 1], ["", "", ""]),
        "5. Misaligned columns, no rules": (m5_drift, [0, 0, 1], ["", "", ""]),
        "6. Columns change between pages": (m6_columns_change, [0, 0, 1], ["", "", ""]),
        "7. Merged cells": (m7_merged, [0, 0, 1], ["", "", ""]),
        "8. Subtotals, carried forward, repeated header": (m8_subtotals, [0, 0, 1], ["", "", ""]),
        "9. Footnotes, (negatives), dashes, n/a": (m9_notation, [0, 0, 1], ["", "", ""]),
        "10. Near-duplicate tables": (m10_near_duplicate, [0, 0, 1], ["", "", ""]),
        "11. Scan damage": (m11_scan_damage, [1, 2, 1], ["rotate", "skew", "stamp"]),
        "12. Handwritten corrections": (m12_corrections, [0, 0, 1], ["", "", ""]),
        "13. Everything at once": (m13_everything, [1, 1, 2], ["", "", "stamp"]),
    }
    return (MODES,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Making the documents

    Mode 2 needs a wrapped row to fall across the page break, so its single table is cut by drawn lines, not rows:
    the first page holds as many lines as fit, which splits one row's description over two pages. The key for a
    column a page doesn't print (mode 6's dropped or added column) is empty for that page's rows.
    """)
    return


@app.cell
def _(MODES, Piece, draw_document, scan, visual_lines):
    def split_lines(pages: list[list[object]]) -> list[list[object]]:
        """Mode 2: cut the table at the first continuation line from 36 lines down, so a row spans the break."""
        piece = pages[0][-1]
        assert isinstance(piece, Piece)
        lines = visual_lines(piece)
        cut = next(i for i in range(36, len(lines)) if lines[i][0] == "row" and not lines[i][1][2])
        one = Piece(piece.rows, piece.columns, lines=lines[:cut])
        two = Piece(piece.rows, piece.columns, header=False, lines=lines[cut:])
        return [[*pages[0][:-1], one], [two]]

    def answer_key(pages: list[list[object]], columns: list[str], rows: list) -> list[list[object]]:
        """Each row's value in each column, or empty where no page prints that column for that row. A handwritten
        correction replaces the printed value, and a zero printed as a dash may also be read as empty."""
        printed: dict[int, set[str]] = {id(r): set() for r in rows}
        for block in (b for page in pages for b in page if isinstance(b, Piece)):
            for r in block.rows:
                if id(r) in printed:
                    printed[id(r)] |= set(block.columns)
        key = []
        for r in rows:
            values = [r.corrected.get(c, r.cells.get(c, "")) if c in printed[id(r)] else "" for c in columns]
            key.append([["0", ""] if v == "0" else v for v in values])
        return key

    documents = []
    for _mode, (_build, _levels, _effects) in MODES.items():
        for _v in range(3):
            _seed = 1000 * int(_mode.split(".")[0]) + _v
            _pages, _columns, _rows = _build(random.Random(_seed), _v)
            if _mode.startswith("2."):
                _pages = split_lines(_pages)
            _pdf = draw_document(_pages, _seed)
            if _levels[_v] or _effects[_v]:
                _pdf = scan(_pdf, _seed, _levels[_v], _effects[_v])
            _name = f"m{_mode.split('.')[0]:0>2}-v{_v}"
            (OUT / f"{_name}.pdf").write_bytes(_pdf)
            documents.append((_mode, _name, _columns, _rows, answer_key(_pages, _columns, _rows)))
    print(f"{len(documents)} documents written to {OUT}")
    return (documents,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Running the four pipelines

    The same four pipelines as notebook 1, from `pipelines.py`, each given the whole document (one to four pages).
    Every pipeline gets the same ask: table 3 by its title, and its columns in order.
    """)
    return


@app.cell
async def _(documents):
    TASKS = {
        name: Task(
            name=name,
            pdf=OUT / f"{name}.pdf",
            kind="table",
            ask=f"Table 3, Harlow County capital projects, fiscal year 2024. Columns: {'; '.join(columns)}",
            pages=tuple(range(1, len(pdfium.PdfDocument(OUT / f"{name}.pdf")) + 1)),
        )
        for _mode, name, columns, _rows, _key in documents
    }

    async def run_all(runner: Runner, jobs: list[tuple[str, str]]) -> dict[tuple[str, str], Result]:
        results = await asyncio.gather(*(PIPELINES[p](TASKS[n], runner) for n, p in jobs))
        return dict(zip(jobs, results, strict=True))

    flash = await run_all(Runner(OUT.parent), [(n, p) for n in TASKS for p in PIPELINES])
    for (_name, _pipeline), _r in flash.items():
        if _r.error:
            print(f"{_name}, {_pipeline}: {_r.error}")
    return TASKS, flash, run_all


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring

    Cells are scored as in notebook 1: **right**, **wrong** (a value that isn't the key's) or **missing**, and found
    rows that match no key row are **extra** (subtotals, the other year's table, header rows). For the handwritten
    corrections, each corrected cell is also sorted by which number a pipeline reported: the handwritten one, the
    struck-through printed one, both in one cell, or something else.
    """)
    return


@app.cell
def _(documents):
    KEYS = {name: (mode, rows, key) for mode, name, _columns, rows, key in documents}

    def corrections(found: list[list[str]], name: str) -> dict[str, int]:
        _mode, rows, _key = KEYS[name]
        columns = next(c for _m, n, c, _r, _k in documents if n == name)
        counts = {"handwritten": 0, "printed": 0, "both": 0, "other": 0}
        for r in rows:
            for col, new in r.corrected.items():
                match = next((f for f in found if f and same(f[0], r.cells["Project"])), [])
                i = columns.index(col)
                value = match[i] if i < len(match) else ""
                has_new = any(same(t, new) for t in value.split())
                has_old = any(same(t, r.cells[col]) for t in value.split())
                counts[
                    "both" if has_new and has_old else "handwritten" if has_new else "printed" if has_old else "other"
                ] += 1
        return counts

    def score(name: str, result: Result) -> dict[str, int]:
        _mode, _rows, key = KEYS[name]
        if result.output is None:
            cells = sum(len(k) for k in key)
            return {"cells": cells, "right": 0, "wrong": 0, "missing": cells, "extra_rows": 0} | corrections([], name)
        return score_table(result.output["rows"], key) | corrections(result.output["rows"], name)

    return KEYS, score


@app.cell
def _(KEYS, flash, score):
    def tally(results: dict[tuple[str, str], Result], names: list[str], pipeline: str) -> dict[str, float]:
        total: dict[str, float] = {"cells": 0, "failed": 0, "usd": 0, "seconds": 0, "pages": 0}
        for n in names:
            r = results[(n, pipeline)]
            if r.output is None:  # the call failed every attempt; counted, not scored
                total["failed"] += 1
                continue
            for k, v in score(n, r).items():
                total[k] = total.get(k, 0) + v
            for k, v in (("usd", r.usd), ("seconds", r.seconds + r.docling_seconds), ("pages", r.pages_read)):
                total[k] = total.get(k, 0) + v
        return total

    def cell_text(t: dict[str, float]) -> str:
        failed = f", {t['failed']:.0f} documents failed" if t["failed"] else ""
        if not t["cells"]:
            return f"not run{failed}"
        share = t["right"] / t["cells"]
        return f"{share:.0%} ({t['wrong']:.0f} wrong, {t['missing']:.0f} missing, {t['extra_rows']:.0f} extra{failed})"

    _modes = sorted({m for m, _r, _k in KEYS.values()}, key=lambda m: int(m.split(".")[0]))
    _lines = ["| Failure mode | " + " | ".join(PIPELINES) + " |", "|---" * (len(PIPELINES) + 1) + "|"]
    for _mode in _modes:
        _names = [n for n, (m, _r, _k) in KEYS.items() if m == _mode]
        _cells = [cell_text(tally(flash, _names, p)) for p in PIPELINES]
        _lines.append(f"| {_mode} | " + " | ".join(_cells) + " |")
    _lines += [
        "",
        "| Pipeline | Clean documents | Scanned documents | Cost per page | Seconds per page |",
        "|---|---|---|---|---|",
    ]
    for _p in PIPELINES:
        _clean = tally(
            flash, [n for n, (m, _r, _k) in KEYS.items() if not n.endswith("v2") and not m.startswith(("11", "13"))], _p
        )
        _scanned = tally(
            flash, [n for n, (m, _r, _k) in KEYS.items() if n.endswith("v2") or m.startswith(("11", "13"))], _p
        )
        _all = tally(flash, list(KEYS), _p)
        _lines.append(
            f"| {_p} | {cell_text(_clean)} | {cell_text(_scanned)} | ${_all['usd'] / max(_all['pages'], 1):.4f} "
            f"| {_all['seconds'] / max(_all['pages'], 1):.1f} |"
        )
    _fix = [
        "",
        "| Pipeline | Handwritten number only | Struck-through number only | Both in one cell | Other or missing |",
        "|---|---|---|---|---|",
    ]
    for _p in PIPELINES:
        _t = tally(flash, [n for n, (m, _r, _k) in KEYS.items() if m.startswith(("12", "13"))], _p)
        _fix.append(
            f"| {_p} | {_t.get('handwritten', 0):.0f} | {_t.get('printed', 0):.0f} | {_t.get('both', 0):.0f} "
            f"| {_t.get('other', 0):.0f} |"
        )
    broken_table = "\n".join(_lines + _fix)
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "broken_tables.md").write_text(broken_table + "\n")
    print(broken_table)
    mo.md("## Results, Gemini 3.8 Flash\n\n" + broken_table)
    return (tally,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Does a bigger model fix the failures?

    Every document where a Gemini pipeline got under 95% of cells right is read again by that pipeline on Gemini 4
    Argon.
    """)
    return


@app.cell
async def _(KEYS, TASKS, flash, run_all, score):
    def failed(name: str, pipeline: str) -> bool:
        s = score(name, flash[(name, pipeline)])
        return s["right"] / s["cells"] < 0.95

    failures = [(n, p) for n in TASKS for p in PIPELINES if "Gemini" in p and failed(n, p)]
    big = await run_all(Runner(OUT.parent, model=model_call.BIG), failures)
    _lines = ["| Document | Failure mode | Pipeline | Flash | Argon |", "|---|---|---|---|---|"]
    for _n, _p in failures:
        _f, _b = score(_n, flash[(_n, _p)]), score(_n, big[(_n, _p)])
        _flash = "failed" if flash[(_n, _p)].error else f"{_f['right']} of {_f['cells']} ({_f['wrong']} wrong)"
        _argon = "failed" if big[(_n, _p)].error else f"{_b['right']} of {_b['cells']} ({_b['wrong']} wrong)"
        _lines.append(f"| {_n} | {KEYS[_n][0]} | {_p} | {_flash} | {_argon} |")
    _usd = sum(r.usd for r in big.values())
    big_table = "\n".join(_lines) + f"\n\n{len(failures)} failure cases; Argon cost ${_usd:.2f} for them."
    (HERE / "results" / "broken_tables_bigger_model.md").write_text(big_table + "\n")
    print(big_table)
    mo.md("## Failure cases, Flash against Argon\n\n" + big_table)
    return (big,)


@app.cell
def _(big, flash, score):
    _rows = [
        {"model": m, "document": n, "pipeline": p, **score(n, r), "usd": r.usd, "seconds": r.seconds,
         "docling_seconds": r.docling_seconds, "error": r.error}
        for m, results in (("flash", flash), ("argon", big))
        for (n, p), r in results.items()
    ]  # fmt: skip
    (OUT / "results.json").write_text(json.dumps(_rows, indent=1))
    print(f"total model cost: ${sum(float(r['usd']) for r in _rows):.2f}")
    return


if __name__ == "__main__":
    app.run()
