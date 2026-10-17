"""Extract K-1 and brokerage 1099 values with a vision-language model, and check each one with a second reader.

This is the second pipeline in the demo. extract.py reads boxes with Tesseract and
rules; this one hands the page image to a vision-language model on OpenRouter and
checks what it says against a second, independent read of the same box. For every
document:

1. Docling (layout.py) finds the K-1 page (or the 1099 pages) and the supplemental
   statement pages, and turns the statements into Box / Description / Amount tables.
2. The model reads the page and returns a typed result through Pydantic AI: one
   Pydantic model per form, where every value carries what was printed, its
   bounding box and the model's own confidence.
3. Each box is located on the page by its printed label, and read a second time:
   from Docling's words on a born-digital page, and on a scan by Tesseract box by
   box after lining the page up with its blank IRS form (extract.py's reader),
   because Docling's OCR misses most of the small amounts on a scanned form.
4. A value goes to the review queue when:
   - the model says it isn't sure (confidence below 0.9);
   - the second read of the box the model named says something else, or nothing
     (the same digits with different punctuation count as agreeing);
   - the model gave no code letter for a row in a coded box;
   - the value isn't a well-formed amount, or the issuer put it on a statement;
   - a cross-check fails (the same ones as extract.py);
   - the second read finds a box or row the model didn't report.
5. For an amount on an attached statement, the model reads the statement page and
   its lines for that box are shown to the reviewer, each marked by whether
   Docling's table has the same code and amount. It stays in the queue.

Writes output/<model>/extracted.json in the same shape as extract.py, so
evaluate.py and report.py work on both. Never reads the answer keys.

    python extract_vlm.py openrouter:google/gemini-3.8-flash [--prompted] [--model-only] [file filter ...]

--model-only skips the second read and writes output/<model>-alone/: the model's
own answers, for scoring a model on its own and for pairing two models (pair.py).

The model is any Pydantic AI model string; the comparison in run.sh uses OpenRouter, which needs
OPENROUTER_API_KEY in the environment.
"""

import asyncio
import io
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Literal

import pypdfium2 as pdfium
from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent, PromptedOutput, capture_run_messages
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import infer_model
from pydantic_ai.settings import ModelSettings

from extract import Page as TemplatePage
from extract import (AMOUNT_AREA, B_COLS, BROKER_LINES, BROKER_ROWS, CODED_AREA, HEADER_LABELS, K1_1065, K1_LABELS,
                     LABEL_MIN, STOP_LABELS, bbox_of, code_of, coded_rows, find_label, group_lines, k1_1065_labels, k1_kind,
                     k1_year, parse_value)

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
LAYOUT = HERE / "output" / "layout"
PT = 300 / 72  # pixel units per PDF point, the same as extract.py so its label areas carry over
IMAGE_DPI = 200  # what the model sees
CONFIDENCE_MIN = 0.9
PARALLEL = 6
THINKING = "low"
PARTIAL_EXIT = 3  # some documents failed every retry; the rest are in the results


# ---------------------------------------------------------------- what the model returns

class Value(BaseModel):
    printed: str = Field(description="The value exactly as printed, keeping signs, parentheses, commas and decimals: "
                                     "'-27,942', '(18)', '1,629', '45,113.89', '-' for a printed dash, 'STMT', 'VARIOUS'.")
    bbox: list[int] = Field(description="Tight box around the printed value only (not its label or code letter): "
                                        "[x0, y0, x1, y1] in 0-1000 coordinates relative to the page image.")
    confidence: float = Field(ge=0, le=1, description="How sure you are that every character is read correctly, 0 to 1.")


class Row(BaseModel):
    # Required: when it was optional, several models left it out of every row.
    code: str = Field(description="For a coded box, the code printed to the left of the amount, as printed, "
                                  "including any asterisk ('A', 'AH*', '*'). An empty string for a box with no codes.")
    value: Value


def k1_model(form, boxes):
    """One Pydantic model per form, with the boxes that form has."""
    Box = Literal[tuple(boxes)]

    class K1Row(Row):
        box: Box = Field(description="The box number printed on the form, e.g. '1', '6a', '20'.")

    fields = {"__doc__": f"Schedule K-1 (Form {form}) as printed.",
              "tax_year": (int, Field(description="The tax year printed on the form.")),
              "payer_ein": (Value | None, Field(description="Part I item A: the employer identification number.")),
              "payer_name": (Value | None, Field(description="Part I item B: the name only, without the address lines.")),
              "boxes": (list[K1Row], Field(description="Every Part III box that has something printed in it. "
                                                       "A coded box gives one row per printed code line."))}
    return type(f"K1_{form}", (BaseModel,), {"__annotations__": {k: v[0] for k, v in fields.items() if k != "__doc__"},
                                            "__doc__": fields["__doc__"],
                                            **{k: v[1] for k, v in fields.items() if k != "__doc__"}})


K1_1065_ALL = list(K1_1065) + ["4", "16", "21"]
FORMS = {"1065": k1_model("1065", list(dict.fromkeys(K1_1065_ALL))),
         "1120S": k1_model("1120S", list(K1_LABELS["1120S"])),
         "1041": k1_model("1041", list(K1_LABELS["1041"]))}


class BRow(BaseModel):
    proceeds: Value
    cost: Value
    wash: Value = Field(description="Wash sale loss disallowed")
    gain: Value = Field(description="Gain or loss")


class Brokerage1099(BaseModel):
    """The summary page of a consolidated brokerage Form 1099."""
    DIV_1a: Value | None = Field(None, description="1099-DIV 1a Total ordinary dividends")
    DIV_1b: Value | None = Field(None, description="1099-DIV 1b Qualified dividends")
    DIV_2a: Value | None = Field(None, description="1099-DIV 2a Total capital gain distributions")
    DIV_3: Value | None = Field(None, description="1099-DIV 3 Nondividend distributions")
    DIV_5: Value | None = Field(None, description="1099-DIV 5 Section 199A dividends")
    DIV_7: Value | None = Field(None, description="1099-DIV 7 Foreign tax paid")
    INT_1: Value | None = Field(None, description="1099-INT 1 Interest income")
    INT_3: Value | None = Field(None, description="1099-INT 3 Interest on U.S. Treasury obligations")
    INT_4: Value | None = Field(None, description="1099-INT 4 Federal income tax withheld")
    INT_8: Value | None = Field(None, description="1099-INT 8 Tax-exempt interest")
    B_A: BRow | None = Field(None, description="1099-B summary row: Short-term, basis reported (Box A)")
    B_D: BRow | None = Field(None, description="1099-B summary row: Long-term, basis reported (Box D)")


class StatementLine(BaseModel):
    code: str = Field(description="The box and code as the statement prints it, e.g. '20AH', '11A1'.")
    description: str
    printed: str = Field(description="The amount exactly as printed.")
    bbox: list[int] = Field(description="Tight box around the amount, [x0, y0, x1, y1] in 0-1000 page coordinates.")


class StatementLines(BaseModel):
    """Lines of a K-1 supplemental statement that belong to one box."""
    lines: list[StatementLine]


INSTRUCTIONS = """You read US tax documents for a tax preparer. Report only what is printed on the page.
Never compute, infer or fill in a value. Leave out boxes that are empty.
Bounding boxes are [x0, y0, x1, y1] in 0-1000 coordinates relative to the page image, tight around the printed value.
Set confidence below 0.9 for any value where a character is smudged, faint, cut off or ambiguous."""


# ---------------------------------------------------------------- pages from Docling

class LPage:
    """One page as Docling read it: its words in pixel units, grouped into lines."""

    def __init__(self, layout_page):
        self.index = layout_page["index"]
        self.size = (round(layout_page["width"] * PT), round(layout_page["height"] * PT))
        self.text_layer = not layout_page["ocr"]
        self.markdown = layout_page["markdown"]
        self.words = [{"text": w["text"], "conf": w["conf"], "x0": w["x0"] * PT, "y0": w["y0"] * PT,
                       "x1": w["x1"] * PT, "y1": w["y1"] * PT} for w in layout_page["words"]]
        self.lines = group_lines(self.words)
        self.text = " ".join(w["text"] for w in self.words)

    def to_px(self, bbox):
        W, H = self.size
        x0, y0, x1, y1 = bbox
        return (x0 * W / 1000, y0 * H / 1000, x1 * W / 1000, y1 * H / 1000)

    def words_in(self, box, pad=0):
        x0, y0, x1, y1 = box
        return [w for w in self.words if x0 - pad <= (w["x0"] + w["x1"]) / 2 <= x1 + pad
                and y0 - pad <= (w["y0"] + w["y1"]) / 2 <= y1 + pad]


def page_png(pdf_path, index, dpi=IMAGE_DPI):
    img = pdfium.PdfDocument(pdf_path)[index].render(scale=dpi / 72).to_pil().convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), img


class Reader:
    """The second, independent read of the page that every model value is checked against.

    On a born-digital page it is Docling's words, which come from the PDF's text layer.
    On a scanned K-1, Docling's OCR misses most of the values (it finds the text
    blocks of a form but not the small amounts inside the boxes), so the page is lined
    up with its blank IRS form and each box is OCR'd on its own with the form's own
    printing removed: the reader from extract.py. Box labels come from the same place.
    Coordinates are the page's own for a born-digital page and the straightened
    scan's for a scan; the review screen shows the matching image.
    """

    def __init__(self, page, tp=None):
        self.page, self.tp = page, tp
        self.labels = tp if tp else page  # what find_label searches
        self.size = page.size
        self.name = "Tesseract, box by box" if tp else "Docling"

    def words(self, area, coded=False):
        if self.tp:
            return self.tp.area_words(area, psm=6 if coded else 7)
        return self.page.words_in(area)

    def model_box(self, v):
        """The model's box for a value, in this reader's coordinates."""
        if len(v.bbox) != 4:
            return None
        x0, y0, x1, y1 = self.page.to_px(v.bbox)
        if not self.tp or abs(self.tp.angle) < 0.1:
            return (x0, y0, x1, y1)
        W, H = self.size
        c, s = math.cos(math.radians(self.tp.angle)), math.sin(math.radians(self.tp.angle))
        pts = []
        for x, y in ((x0, y0), (x1, y1)):
            dx, dy = x - W / 2, y - H / 2
            pts.append((dx * c + dy * s + W / 2, -dx * s + dy * c + H / 2))
        return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def field(page, key, label, value, raw, box_px, conf, reasons, **extra):
    W, H = page.size
    bb = [round(box_px[0] / W, 4), round(box_px[1] / H, 4), round(box_px[2] / W, 4), round(box_px[3] / H, 4)] if box_px else None
    return {"key": key, "label": label, "value": value, "raw": raw, "page": page.index, "bbox": bb,
            "confidence": round(conf * 100), "reasons": reasons, **extra}


def model_reasons(v, kind, allow_text=False):
    """Reasons to review that come from the model's own answer."""
    _value, vkind = parse_value(v.printed)
    reasons = []
    if vkind == "unreadable" or (vkind == "text" and not allow_text):
        reasons.append(f"can't read '{v.printed}' as an amount")
    if vkind == "statement":
        reasons.append("amount is on the attached statement")
    if v.confidence < CONFIDENCE_MIN:
        reasons.append(f"the model's confidence is {v.confidence:.2f}")
    return reasons


def agrees(printed, second):
    """Whether the second read says the same as the model: the same value, or the same digits and sign (OCR often
    reads a comma as a period, and the model reads punctuation better)."""
    a, ka = parse_value(printed)
    b, kb = parse_value(second)
    if ka == kb == "text":
        return same_text(printed, second)
    if a is not None and a == b:
        return True
    digits = re.sub(r"\D", "", printed)
    neg = lambda t: bool(re.match(r"^\s*[(\-]", t))  # noqa: E731
    return bool(digits) and digits == re.sub(r"\D", "", second) and neg(printed) == neg(second)


def same_text(a, b):
    return re.sub(r"[^A-Z0-9]", "", (a or "").upper()) == re.sub(r"[^A-Z0-9]", "", (b or "").upper())


# ---------------------------------------------------------------- K-1

def k1_regions(lab, form, year):
    """Where each Part III box is on the page, from its printed label."""
    W = lab.size[0]
    labels = k1_1065_labels(year) if form == "1065" else K1_LABELS[form]
    found = {box: find_label(lab, label, x_min=W * 0.48, number=box) for box, (label, _k) in labels.items()}
    stops = [find_label(lab, s, x_min=W * 0.48) for s in STOP_LABELS]
    anchors = [bb for s, bb in list(found.values()) + stops if bb and s >= LABEL_MIN]
    regions = {}
    for box, (label, kind) in labels.items():
        score, bb = found[box]
        if not bb or score < LABEL_MIN:
            continue
        if kind == "amount":
            left, right, height = AMOUNT_AREA
            area = (bb[0] + left * PT, bb[3] + 1, bb[0] + right * PT, bb[1] + height * PT - 2)
        else:
            left, right, height = CODED_AREA
            x0, x1 = bb[0] + left * PT, bb[0] + right * PT
            below = [a[1] for a in anchors if a[0] < x1 and a[2] > x0 and a[1] > bb[3] + 4]
            area = (x0, bb[3] + 2, x1, min(below + [bb[1] + height * PT]) - 4)
        regions[box] = (area, kind, label)
    return labels, regions


def second_read(reader, regions):
    """The reader's rows in every box: (code, raw text, value, kind, words). Amount boxes have one row, code None."""
    rows = {}
    for b, (area, kind, _label) in regions.items():
        ws = reader.words(area, coded=kind == "coded")
        if kind == "coded":
            rows[b] = coded_rows(ws)
        else:
            raw = " ".join(w["text"] for w in ws)
            rows[b] = [(None, raw, *parse_value(raw), ws)] if ws else []
    return rows


def k1_fields(reader, form, out, labels, regions):
    page, W = reader.page, reader.size[0]
    fields = []
    # Part I: the payer's EIN and name, compared with the reader's first line under each label.
    for key, label in zip(("payer_ein", "payer_name"), HEADER_LABELS[form]):
        v = getattr(out, key)
        score, bb = find_label(reader.labels, label, x_max=W * 0.5)
        second, sbox = "", None
        if bb and score >= LABEL_MIN:
            lines = group_lines(reader.words((bb[0] - 20 * PT, bb[3] + 1, bb[0] + 250 * PT, bb[3] + 26 * PT)))
            if lines:
                second, sbox = " ".join(w["text"] for w in lines[0]["words"]), bbox_of(lines[0]["words"])
        if v is None:
            fields.append(field(page, key, label, second or None, second, sbox, 0, ["the model didn't report it"]))
            continue
        name = v.printed.split("\n")[0].strip()
        reasons = [] if v.confidence >= CONFIDENCE_MIN else [f"the model's confidence is {v.confidence:.2f}"]
        if not second:
            reasons.append("the second read found nothing under the label")
        elif not same_text(name, second):
            reasons.append(f"the second read says '{second}'")
        fields.append(field(page, key, label, name, v.printed, sbox or reader.model_box(v), v.confidence, reasons))

    second = second_read(reader, regions)
    used = {b: set() for b in second}
    seen_keys = set()
    for r in out.boxes:
        label, kind = labels.get(r.box, (K1_1065.get(r.box, ("", ""))[0], "amount"))
        value, _vkind = parse_value(r.value.printed)
        reasons = model_reasons(r.value, kind, allow_text=kind == "coded" and r.box == "16")
        code = code_of(r.code.strip().replace(" ", "")) if kind == "coded" and (r.code or "").strip() else None
        box = None
        if r.box not in labels:
            reasons.append(f"Form {form} for this year has no box {r.box}")
        elif r.box not in regions:
            reasons.append(f"couldn't find the label for box {r.box} on the page")
        else:
            rows = second[r.box]
            free = [i for i in range(len(rows)) if i not in used[r.box]]
            if kind == "coded" and not code:
                same = [i for i in free if agrees(r.value.printed, rows[i][1])]
                code = rows[same[0]][0] if len(same) == 1 else "?"
                reasons.append(f"the model gave no code; the second read shows {code} with this amount" if code != "?"
                               else "the model gave no code for a row in a coded box")
            match = [i for i in free if rows[i][0] == code] if kind == "coded" else free[:1]
            if match:
                i = match[0]
                used[r.box].add(i)
                box = bbox_of(rows[i][4])
                if not agrees(r.value.printed, rows[i][1]):
                    reasons.append(f"the second read says '{rows[i][1]}'")
            elif kind == "coded":
                reasons.append(f"the second read doesn't find code {code} in box {r.box}")
            else:
                reasons.append(f"the second read finds box {r.box} empty")
        key = f"{r.box} {code}" if code else r.box
        if key in seen_keys:
            reasons.insert(0, f"{key} appears twice")
            key = f"{key} (again)"
        seen_keys.add(key)
        fields.append(field(page, key, f"{label}, code {code}" if code else label, value, r.value.printed,
                            box or reader.model_box(r.value), r.value.confidence, reasons))

    # Rows the reader sees that the model didn't report: a missed box or row.
    for b, rows in second.items():
        coded = regions[b][1] == "coded"
        for i, (code, raw, value, _kind, ws) in enumerate(rows):
            if i in used[b]:
                continue
            key = (f"{b} {code}" if code and code != "?" else f"{b} ?") if coded else b
            if key in seen_keys:
                key = f"{b} ?"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            label = regions[b][2]
            fields.append(field(page, key, f"{label}, code {code or '?'}" if coded else label, value, raw, bbox_of(ws), 0,
                                [f"the second read shows '{raw}' in box {b}, but the model didn't report it"]))

    k1_crosschecks(fields, form)
    return fields


def k1_crosschecks(fields, form):
    """The same cross-checks as extract.py: qualified dividends against ordinary, and 4a + 4b = 4c."""
    def get(k):
        return next((f for f in fields if f["key"] == k), None)

    total, part = {"1065": ("6a", "6b"), "1120S": ("5a", "5b"), "1041": ("2a", "2b")}[form]
    t, p = get(total), get(part)
    if t and p and isinstance(p["value"], (int, float)) and isinstance(t["value"], (int, float)) and p["value"] > t["value"]:
        for f in (t, p):
            f["reasons"].append(f"qualified dividends ({part}) exceed ordinary dividends ({total})")
    if p and isinstance(p["value"], (int, float)) and not t:
        p["reasons"].append(f"qualified dividends ({part}) present but ordinary dividends ({total}) blank")
    if form == "1065" and any(get(k) for k in ("4a", "4b", "4c")):
        a, b, c = [(get(k)["value"] if get(k) and isinstance(get(k)["value"], (int, float)) else 0) for k in ("4a", "4b", "4c")]
        if a + b != c:
            for k in ("4a", "4b", "4c"):
                if get(k):
                    get(k)["reasons"].append("4a + 4b doesn't equal 4c")


# ---------------------------------------------------------------- brokerage 1099

def detail_totals(dp):
    """Sum the detail page's lots by term, from Tesseract (the model doesn't see this page). As in extract.py."""
    totals, ok = {"A": [0.0] * 4, "D": [0.0] * 4}, True
    for line in dp.lines:
        ws = line["words"]
        if not ws or ws[0]["text"] not in ("A", "D") or ws[0]["x0"] > dp.size[0] * 0.15:
            continue
        nums = [w for w in dp.area_words((dp.size[0] * 0.4, line["y0"] - 6, dp.size[0] - 20, line["y1"] + 6))
                if re.search(r"\d", w["text"])]
        vals = [parse_value(w["text"]) for w in nums]
        if len(vals) != 4 or any(k != "amount" for _v, k in vals):
            ok = False
            continue
        for i, (v, _k) in enumerate(vals):
            totals[ws[0]["text"]][i] += v
    return totals, ok


def broker_fields(reader, detail_page, out):
    """The second read is Tesseract here, as in extract.py. The brokerage 1099s are all scans; Docling's OCR found
    the summary amounts but dropped lots from the detail page, which the cross-check needs. Each amount is read on
    the line of its printed label."""
    page, W = reader.page, reader.size[0]
    fields, used = [], []
    for key, label in BROKER_LINES.items():
        v = getattr(out, key.replace(" ", "_"))
        score, bb = find_label(reader.labels, label, x_max=W * 0.5, exclude=used)
        ws = []
        if bb and score >= LABEL_MIN:
            used.append(bb)
            ws = [w for w in reader.words((W * 0.75, bb[1] - 6, W - 20, bb[3] + 6), coded=True) if re.search(r"\d", w["text"])]
        second = " ".join(w["text"] for w in ws)
        if v is None:
            fields.append(field(page, key, label, parse_value(second)[0] if ws else None, second,
                                bbox_of(ws) if ws else bb, 0, ["the model didn't report it"]))
            continue
        value, _k = parse_value(v.printed)
        reasons = model_reasons(v, "amount")
        if not bb or score < LABEL_MIN:
            reasons.append("couldn't find the line's label on the page")
        elif not ws:
            reasons.append("the second read finds no amount on the line")
        elif not agrees(v.printed, second):
            reasons.append(f"the second read says '{second}'")
        fields.append(field(page, key, label, value, v.printed, bbox_of(ws) if ws else reader.model_box(v), v.confidence, reasons))

    for term, label in BROKER_ROWS.items():
        row = getattr(out, f"B_{term}")
        score, bb = find_label(reader.labels, label, x_max=W * 0.5)
        ws = []
        if bb and score >= LABEL_MIN:
            ws = [w for w in reader.words((W * 0.38, bb[1] - 6, W - 20, bb[3] + 6), coded=True) if re.search(r"\d", w["text"])]
        for i, col in enumerate(B_COLS):
            v = getattr(row, col) if row else None
            w = ws[i] if len(ws) == 4 else None
            if v is None:
                fields.append(field(page, f"B {term} {col}", f"1099-B {label}: {col}", None, "", bb, 0, ["the model didn't report it"]))
                continue
            value, _k = parse_value(v.printed)
            reasons = model_reasons(v, "amount")
            if not bb or score < LABEL_MIN:
                reasons.append("couldn't find the row's label on the page")
            elif w is None:
                reasons.append(f"the second read finds {len(ws)} amounts on the row, not 4")
            elif not agrees(v.printed, w["text"]):
                reasons.append(f"the second read says '{w['text']}'")
            fields.append(field(page, f"B {term} {col}", f"1099-B {label}: {col}", value, v.printed,
                                bbox_of([w]) if w else reader.model_box(v), v.confidence, reasons))

    broker_crosschecks(fields, detail_page)
    return fields


def broker_crosschecks(fields, detail_page, check_detail=True):
    """1b within 1a, each 1099-B row balancing, and (with a read of the detail page) each row matching its lots."""
    def get(k):
        return next((f for f in fields if f["key"] == k), None)

    a, q = get("DIV 1a"), get("DIV 1b")
    if a and q and isinstance(a["value"], (int, float)) and isinstance(q["value"], (int, float)) and q["value"] > a["value"]:
        for f in (a, q):
            f["reasons"].append("qualified dividends (1b) exceed ordinary dividends (1a)")
    detail, detail_ok = detail_totals(detail_page) if detail_page else ({}, False)
    for term in BROKER_ROWS:
        row = [get(f"B {term} {c}") for c in B_COLS]
        if not all(row):
            continue
        vals = [f["value"] for f in row]
        if not all(isinstance(v, (int, float)) for v in vals):
            continue
        p, c, wsh, g = vals
        if abs(p - c + wsh - g) > 0.011:
            for f in row:
                f["reasons"].append("proceeds - cost + wash sale doesn't equal gain or loss")
        if not check_detail:
            continue
        for f, total in zip(row, detail.get(term, [None] * 4)):
            if not detail_ok:
                f["reasons"].append("couldn't read the detail page to check this total")
            elif abs(f["value"] - total) > 0.011:
                f["reasons"].append(f"doesn't match the detail page total ({total:,.2f})")


# ---------------------------------------------------------------- the model on its own

def model_fields(page, form, out, labels):
    """The model's answer as fields, with no second read: for scoring a model on its own, and for pairing two models
    (pair.py). Values still go to review for low confidence, STMT, a malformed amount, a missing code or a failed
    cross-check, which need nothing but the model's answer."""
    fields, seen = [], set()

    def add(key, label, v, reasons=()):
        if key.startswith("payer"):  # a name or EIN, not an amount
            reasons = list(reasons) + ([] if v.confidence >= CONFIDENCE_MIN else [f"the model's confidence is {v.confidence:.2f}"])
        else:
            reasons = list(reasons) + model_reasons(v, "amount", allow_text=key.startswith("16 "))
        if key in seen:
            reasons.insert(0, f"{key} appears twice")
            key = f"{key} (again)"
        seen.add(key)
        fields.append(field(page, key, label, parse_value(v.printed)[0] if not key.startswith("payer") else v.printed.split("\n")[0].strip(),
                            v.printed, page.to_px(v.bbox) if len(v.bbox) == 4 else None, v.confidence, reasons))

    if form == "BROKER":
        for key, label in BROKER_LINES.items():
            v = getattr(out, key.replace(" ", "_"))
            if v is not None:
                add(key, label, v)
        for term, label in BROKER_ROWS.items():
            row = getattr(out, f"B_{term}")
            for col in B_COLS:
                if row is not None:
                    add(f"B {term} {col}", f"1099-B {label}: {col}", getattr(row, col))
        broker_crosschecks(fields, None, check_detail=False)
        return fields
    for key, label in zip(("payer_ein", "payer_name"), HEADER_LABELS[form]):
        if getattr(out, key) is not None:
            add(key, label, getattr(out, key))
    for r in out.boxes:
        label, kind = labels.get(r.box, (K1_1065.get(r.box, ("", ""))[0], "amount"))
        reasons = [] if r.box in labels else [f"Form {form} for this year has no box {r.box}"]
        key = r.box
        if kind == "coded":
            code = code_of(r.code.strip().replace(" ", "")) if (r.code or "").strip() else "?"
            if code == "?":
                reasons.append("the model gave no code for a row in a coded box")
            key, label = f"{r.box} {code}", f"{label}, code {code}"
        add(key, label, r.value, reasons)
    k1_crosschecks(fields, form)
    return fields


# ---------------------------------------------------------------- statements

def statement_rows(page):
    """Box / Description / Amount rows from Docling's tables on a statement page."""
    rows = []
    for line in page.markdown.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.fullmatch(r"\d{1,2}[A-Z]{1,2}\d*", cells[0].replace(" ", "")):
            rows.append((cells[0].replace(" ", ""), cells[1], cells[-1]))
    return rows


def statement_page_for(pages, box):
    """The statement page whose Box column has rows for this box, from Docling's tables. Plain lookup: a package has
    a handful of statement pages, so there's nothing for a retrieval index to do."""
    hits = [p for p in pages if any(re.match(rf"{re.escape(box)}[A-Z]", code) for code, _d, _a in statement_rows(p))]
    return hits[0] if hits else (pages[0] if pages else None)


# ---------------------------------------------------------------- running it

def response_cost(m):
    """One model response's cost in dollars: the provider's own figure when it reports one (OpenRouter puts it in
    provider_details), else Pydantic AI's price table. None when neither knows it."""
    if (m.provider_details or {}).get("cost") is not None:
        return float(m.provider_details["cost"])
    try:
        return float(m.cost().total_price)
    except LookupError:
        return None


class Runner:
    def __init__(self, model_name, prompted=False):
        # Any Pydantic AI model string works: "openrouter:google/gemini-3.8-flash", "google-gla:...", "anthropic:...".
        # Reading a form doesn't need long reasoning, so thinking models run at low effort, through Pydantic AI's
        # provider-neutral thinking setting; models that don't reason ignore it.
        self.model = infer_model(model_name)
        self.settings = ModelSettings(temperature=0, max_tokens=8000, thinking=THINKING)
        if model_name.startswith("openrouter:"):
            self.settings["openrouter_usage"] = {"include": True}  # OpenRouter reports each call's cost
        self.sem = asyncio.Semaphore(PARALLEL)
        self.prompted = prompted
        self.cost = {}

    async def ask(self, doc, output_type, prompt, images):
        # Typed output goes through a forced tool call by default. Some thinking models' providers refuse a forced
        # tool call; --prompted puts the schema in the prompt and validates the JSON that comes back.
        agent = Agent(self.model, output_type=PromptedOutput(output_type) if self.prompted else output_type,
                      instructions=INSTRUCTIONS, retries=2, model_settings=self.settings)
        parts = [prompt] + [BinaryContent(png, media_type="image/png") for png in images]
        c = self.cost.setdefault(doc, {"usd": 0.0, "cost_missing": 0, "input_tokens": 0, "output_tokens": 0,
                                       "calls": 0, "failed_attempts": 0, "seconds": 0.0})
        async with self.sem:
            for attempt in range(6):
                t0 = time.time()
                # Every attempt is paid for, including one that fails after the model answered (output cut off at the
                # token limit, or malformed after Pydantic AI's own retries), so count the responses of each.
                with capture_run_messages() as messages:
                    try:
                        r = await agent.run(parts)
                        error = None
                    except Exception as e:  # rate limits, network errors, malformed output after retries
                        error = e
                for m in messages:
                    if isinstance(m, ModelResponse):
                        usd = response_cost(m)
                        if usd is None:
                            c["cost_missing"] += 1
                        else:
                            c["usd"] += usd
                        c["input_tokens"] += m.usage.input_tokens
                        c["output_tokens"] += m.usage.output_tokens
                c["calls"] += 1
                c["seconds"] += time.time() - t0
                if error is None:
                    break
                c["failed_attempts"] += 1
                if attempt == 5:
                    raise error
                print(f"  {doc}: retrying after {type(error).__name__}: {str(error)[:120]}")
                await asyncio.sleep(15 * (attempt + 1))
        return r.output


async def process(runner, path, out_dir):
    layout = json.loads((LAYOUT / (path.stem + ".json")).read_text())
    pages = [LPage(p) for p in layout["pages"]]
    doc = path.name
    raw = {}
    form, year, main, fields, stmts = None, None, None, [], []
    for p in pages:
        if "consolidated form 1099" in p.text.lower():
            form, main = "BROKER", p
            break
        if k1_kind(p.text):
            form, main = k1_kind(p.text), p
            break
    tp = None
    if not runner.model_only and (form is None or (form != "BROKER" and not main.text_layer)):
        # A scanned K-1: line it up with the blank IRS forms for its box labels. The best fit also gives the form
        # and year when Docling's OCR couldn't make out the title.
        cand = main or pages[0]
        tp = TemplatePage(path, cand.index)
        if tp.template:
            (form, year), main = tp.template, cand
        else:
            tp = None
    if form is None:
        # Still unknown (a bad scan of a brokerage statement): ask the model which form it is.
        png, _ = page_png(path, 0)
        kind = await runner.ask(doc, Literal["Schedule K-1 (Form 1065)", "Schedule K-1 (Form 1120-S)",
                                             "Schedule K-1 (Form 1041)", "Consolidated brokerage Form 1099", "other"],
                                "Which tax form is this page?", [png])
        form = {"Schedule K-1 (Form 1065)": "1065", "Schedule K-1 (Form 1120-S)": "1120S",
                "Schedule K-1 (Form 1041)": "1041", "Consolidated brokerage Form 1099": "BROKER"}.get(kind)
        main = pages[0]
        raw["form_question"] = kind
    if form is None:
        return None
    png, img = page_png(path, main.index)
    if form == "BROKER":
        out = await runner.ask(doc, Brokerage1099, "Read the summary amounts on this consolidated brokerage 1099 page.", [png])
        raw["extraction"] = out.model_dump()
        if runner.model_only:
            fields = model_fields(main, form, out, {})
        else:
            tp = TemplatePage(path, main.index)  # no blank form fits a brokerage statement, so this OCRs the whole page
            detail = TemplatePage(path, main.index + 1) if len(pages) > main.index + 1 else None
            fields = broker_fields(Reader(main, tp), detail, out)
    else:
        names = k1_1065_labels(2025) if form == "1065" else K1_LABELS[form]
        guide = "; ".join(f"{b} {label}" + (" (coded)" if k == "coded" else "") for b, (label, k) in names.items())
        out = await runner.ask(doc, FORMS[form], f"Read this Schedule K-1 (Form {form}). Part III boxes on this form "
                                                 f"include: {guide}. In a coded box, report one row per printed line, "
                                                 "with the code letter printed to the left of the amount on that line "
                                                 "(every line in a coded box has one), including lines whose amount "
                                                 "is a dash and lines coded '*' with STMT.",
                               [png])
        raw["extraction"] = out.model_dump()
        if tp is None:
            year = k1_year(main) if re.search(r"calendar\s*year\s*20\d\d", main.text, re.I) else out.tax_year
        if runner.model_only:
            fields = model_fields(main, form, out, k1_1065_labels(year) if form == "1065" else K1_LABELS[form])
        else:
            reader = Reader(main, tp)
            labels, regions = k1_regions(reader.labels, form, year)
            fields = k1_fields(reader, form, out, labels, regions)
        stmts = [p for p in pages if p.index > main.index and statement_rows(p)]
        # Amounts on a statement: the model reads the statement page and suggests the lines for that box.
        for f in fields:
            if f["value"] != "STMT":
                continue
            box = f["key"].split(" ")[0]
            sp = statement_page_for(stmts, box)
            if sp is None:
                f["reasons"] = ["amount is on an attached statement, but there's no statement page in the file"]
                continue
            spng, _ = page_png(path, sp.index)
            lines = await runner.ask(doc, StatementLines,
                                     f"This is a supplemental statement to a Schedule K-1. List every line that belongs "
                                     f"to box {box} (codes starting with {box}). Docling's reading of the page, for "
                                     f"reference:\n\n{sp.markdown[:6000]}", [spng])
            raw.setdefault("statements", {})[box] = lines.model_dump()
            f["reasons"] = [f"amount is on the attached statement (page {sp.index + 1})"]
            f["statement_page"] = sp.index
            table = {code: amount for code, _d, amount in statement_rows(sp)}
            f["statement_lines"] = []
            for ln in lines.lines:
                bx = sp.to_px(ln.bbox) if len(ln.bbox) == 4 else None
                code = ln.code.replace(" ", "").upper()
                f["statement_lines"].append({
                    "code": ln.code, "description": ln.description, "printed": ln.printed,
                    "value": parse_value(ln.printed)[0],
                    "bbox": [round(bx[0] / sp.size[0], 4), round(bx[1] / sp.size[1], 4), round(bx[2] / sp.size[0], 4),
                             round(bx[3] / sp.size[1], 4)] if bx else None,
                    # Docling's table has the same code with the same amount
                    "docling_agrees": code in table and parse_value(table[code])[0] == parse_value(ln.printed)[0]})
            if table:
                missing = [c for c in table if c.startswith(box) and re.match(rf"{box}[A-Z]", c)
                           and c not in {ln.code.replace(" ", "").upper() for ln in lines.lines}]
                f["statement_lines_missed"] = missing
    # A model can return a valid but empty or near-empty answer. Every box it leaves out would read as blank, so
    # the whole page goes to review instead.
    page_review = near_empty(main, fields, form)
    if page_review:
        fields.append(field(main, "page", "The whole page", None, "", None, 0, [page_review]))
    for f in fields:
        f["status"] = "review" if f["reasons"] else "accepted"
    # Page images for the review screen, at the size report.py expects.
    page_files = {}
    show = [main.index] + ([main.index + 1] if form == "BROKER" and len(pages) > main.index + 1 else [])
    show += sorted({f["statement_page"] for f in fields if "statement_page" in f})
    for i in show:
        name = f"{path.stem}-p{i + 1}.jpg"
        # A scanned K-1's boxes are in the straightened image's coordinates, so show that image.
        im = (tp.shown if tp else img) if i == main.index else page_png(path, i)[1]
        im.resize((pages[i].size[0] // 2, pages[i].size[1] // 2)).convert("L").save(out_dir / "pages" / name, quality=72)
        page_files[str(i)] = f"pages/{name}"
    (out_dir / "raw" / (path.stem + ".json")).write_text(json.dumps(raw, indent=1))
    c = runner.cost.get(doc, {})
    return {"file": doc, "form": form, "year": year, "source": "text layer" if main.text_layer else "OCR",
            "page_review": page_review,
            "second_read": "none" if runner.model_only else ("Tesseract, box by box" if tp else "Docling"),
            "pages": page_files, "seconds": round(layout["seconds"] + c.get("seconds", 0), 1),
            "docling_seconds": layout["seconds"], "model_seconds": round(c.get("seconds", 0), 1),
            "cost_usd": round(c.get("usd", 0), 6), "cost_missing_responses": c.get("cost_missing", 0),
            "input_tokens": c.get("input_tokens", 0), "output_tokens": c.get("output_tokens", 0),
            "model_calls": c.get("calls", 0), "failed_attempts": c.get("failed_attempts", 0), "fields": fields}


# An amount as printed: with a thousands comma or cents, so box numbers, years and form numbers don't count. Zero
# amounts don't count either, since an empty box can print as 0.00.
AMOUNT_WORD = re.compile(r"^[($-]*(\d{1,3}(,\d{3})+(\.\d\d)?|\d+\.\d\d)\)?$")


# The share of the amounts Docling sees printed on a page that a model must read for its answer to count as more
# than near-empty. A K-1 prints many amounts the schema doesn't ask for (capital account, liabilities, statement
# references), so only a much shorter answer is suspect there. A brokerage summary page prints only the 18 amounts
# the schema asks for, so an answer missing whole sections (GLM 5.3 Flash reading only the 8 1099-B amounts of
# about 16) is near-empty too.
BROKER_MIN_READ_SHARE = 0.75
K1_MIN_READ_SHARE = 0.25


def near_empty(page, fields, form):
    """Why the whole page should go to review, or None. Docling's words give an independent count of the amounts
    printed on the page, so an answer with far fewer values than that is treated like an empty one."""
    read = [f for f in fields if f["raw"] and not f["key"].startswith("payer") and f["key"] != "page"]
    if not read:
        return "the model read nothing on this page"
    printed = sum(1 for w in page.words if AMOUNT_WORD.match(w["text"]) and re.search(r"[1-9]", w["text"]))
    share = BROKER_MIN_READ_SHARE if form == "BROKER" else K1_MIN_READ_SHARE
    if printed >= 8 and len(read) < printed * share:
        n = f"{len(read)} value" + ("" if len(read) == 1 else "s")
        return f"the model read only {n} on a page that shows about {printed} amounts"
    if all(f["reasons"] for f in read):
        return "the model wasn't sure of any value on this page, so a box it left out may not be blank"
    return None


def slug(model_name):
    return re.sub(r"[^a-z0-9.]+", "-", model_name.split(":", 1)[-1].split("/")[-1].lower())


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prompted = "--prompted" in sys.argv
    model_only = "--model-only" in sys.argv
    model_name = args[0]
    out_dir = HERE / "output" / (slug(model_name) + ("-alone" if "--model-only" in sys.argv else ""))
    (out_dir / "pages").mkdir(parents=True, exist_ok=True)
    (out_dir / "raw").mkdir(exist_ok=True)
    files = sorted(SAMPLES.glob("*.pdf"))
    if len(args) > 1:
        files = [f for f in files if any(a in f.name for a in args[1:])]
    runner = Runner(model_name, prompted)
    runner.model_only = model_only
    failures = {}

    async def one(path):
        try:
            d = await process(runner, path, out_dir)
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"{path.name}: failed: {error}")
            failures[path.name] = error
            return None
        if d:
            n_review = sum(f["status"] == "review" for f in d["fields"])
            print(f"{path.name:38s} {str(d['form']):6s} {len(d['fields']):3d} values, {n_review:2d} to review, "
                  f"${d['cost_usd']:.4f}, {d['model_seconds']:5.1f}s model")
        return d

    results = await asyncio.gather(*(one(p) for p in files))
    docs = sorted((d for d in results if d), key=lambda d: d["file"])
    failed = [{"file": name, "error": failures.get(name, "no result")} for name in
              (p.name for p, d in zip(files, results) if not d)]
    (out_dir / "extracted.json").write_text(json.dumps({
        "pipeline": "vision-language model alone" if model_only else "Docling + vision-language model", "model": model_name, "thinking": THINKING,
        "confidence_min": CONFIDENCE_MIN,
        "image_dpi": IMAGE_DPI, "documents": docs, "failed_documents": failed}, indent=1))
    total = sum(d["cost_usd"] for d in docs)
    missing = sum(d["cost_missing_responses"] for d in docs)
    print(f"{model_name}: {len(docs)} documents, ${total:.4f} in all, ${total / max(1, len(docs)):.4f} per document"
          + (f", plus {missing} responses with no known cost" if missing else ""))
    if not docs:
        sys.exit(f"{model_name}: every document failed, so there are no results")
    if failed:
        # The run is scored on the documents that finished; the failed ones are listed in extracted.json and every
        # report, so a model that can't read some documents doesn't look better than it is. run.sh reads this exit
        # code as "partial results" rather than as a crash.
        print(f"{model_name}: {len(failed)} documents failed every retry: {', '.join(f['file'] for f in failed)}")
        sys.exit(PARTIAL_EXIT)


if __name__ == "__main__":
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    asyncio.run(main())
