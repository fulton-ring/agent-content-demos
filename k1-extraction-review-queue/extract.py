"""Extract K-1 and brokerage 1099 values, with the page and box each one came from.

For every PDF in samples/: find the K-1 page (or the 1099 pages), get its words
(from the PDF's text layer when it has one; for a scan, by straightening it and
lining it up with the blank IRS form for that year), find each box by its
printed label, and read the value in that box (OCR on just that box for a
scan). Every value carries its page, its bounding box and a
confidence, and goes to the review queue when:

- OCR is unsure of it, or it doesn't read as an amount;
- its label couldn't be found;
- the issuer put it on an attached statement (STMT);
- it fails a cross-check (qualified dividends above ordinary dividends, a 1099-B
  summary that doesn't balance or doesn't match its detail page, and so on).

Writes output/extracted.json and one image per page under output/pages/.
Never reads the answer keys.
"""

import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pdfplumber
import pypdfium2 as pdfium
import pytesseract
from scipy import ndimage
from PIL import Image, ImageFilter, ImageOps

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
OUT = HERE / "output"
DPI = 300
PT = DPI / 72  # pixels per PDF point; all coordinates below are pixels at DPI
CONF_MIN = 80  # Tesseract word confidence below this sends a value to review
LABEL_MIN = 0.75  # how closely OCR text must match a printed label

# Part III labels as printed on Schedule K-1. "coded" boxes hold rows of code + amount.
K1_1065 = {
    "1": ("Ordinary business income (loss)", "amount"),
    "2": ("Net rental real estate income (loss)", "amount"),
    "3": ("Other net rental income (loss)", "amount"),
    "4a": ("Guaranteed payments for services", "amount"),
    "4b": ("Guaranteed payments for capital", "amount"),
    "4c": ("Total guaranteed payments", "amount"),
    "5": ("Interest income", "amount"),
    "6a": ("Ordinary dividends", "amount"),
    "6b": ("Qualified dividends", "amount"),
    "6c": ("Dividend equivalents", "amount"),
    "7": ("Royalties", "amount"),
    "8": ("Net short-term capital gain (loss)", "amount"),
    "9a": ("Net long-term capital gain (loss)", "amount"),
    "9b": ("Collectibles (28%) gain (loss)", "amount"),
    "9c": ("Unrecaptured section 1250 gain", "amount"),
    "10": ("Net section 1231 gain (loss)", "amount"),
    "11": ("Other income (loss)", "coded"),
    "12": ("Section 179 deduction", "amount"),
    "13": ("Other deductions", "coded"),
    "14": ("Self-employment earnings (loss)", "coded"),
    "15": ("Credits", "coded"),
    "16": ("Foreign transactions", "coded"),
    "17": ("Alternative minimum tax (AMT) items", "coded"),
    "18": ("Tax-exempt income and", "coded"),
    "19": ("Distributions", "coded"),
    "20": ("Other information", "coded"),
    "21": ("Foreign taxes paid or accrued", "amount"),
}


def k1_1065_labels(year):
    """The 1065 K-1 changed between years; drop the boxes a given year's form doesn't have."""
    labels = dict(K1_1065)
    if year <= 2018:
        for k in ("4a", "4b", "4c"):
            del labels[k]
        labels["4"] = ("Guaranteed payments", "amount")
    if year <= 2020:
        del labels["21"]
    else:
        del labels["16"]  # now just the Schedule K-3 checkbox
    return labels


K1_LABELS = {
    "1120S": {
        "1": ("Ordinary business income (loss)", "amount"),
        "2": ("Net rental real estate income (loss)", "amount"),
        "3": ("Other net rental income (loss)", "amount"),
        "4": ("Interest income", "amount"),
        "5a": ("Ordinary dividends", "amount"),
        "5b": ("Qualified dividends", "amount"),
        "6": ("Royalties", "amount"),
        "7": ("Net short-term capital gain (loss)", "amount"),
        "8a": ("Net long-term capital gain (loss)", "amount"),
        "9": ("Net section 1231 gain (loss)", "amount"),
        "11": ("Section 179 deduction", "amount"),
        "12": ("Other deductions", "coded"),
        "13": ("Credits", "coded"),
        "16": ("Items affecting shareholder basis", "coded"),
        "17": ("Other information", "coded"),
    },
    "1041": {
        "1": ("Interest income", "amount"),
        "2a": ("Ordinary dividends", "amount"),
        "2b": ("Qualified dividends", "amount"),
        "3": ("Net short-term capital gain", "amount"),
        "4a": ("Net long-term capital gain", "amount"),
        "5": ("nonbusiness income", "amount"),
        "6": ("Ordinary business income", "amount"),
        "7": ("Net rental real estate income", "amount"),
        "8": ("Other rental income", "amount"),
        "9": ("Directly apportioned deductions", "coded"),
        "10": ("Estate tax deduction", "amount"),
        "11": ("Final year deductions", "coded"),
        "13": ("Credits and credit recapture", "coded"),
        "14": ("Other information", "coded"),
    },
}
# Printed lines that end a coded box without being a box of their own.
STOP_LABELS = ["More than one activity for at-risk purposes", "See attached statement for additional information",
               "Schedule K-3 is attached if"]
HEADER_LABELS = {
    "1065": ("Partnership's employer identification number", "Partnership's name, address, city, state, and ZIP code"),
    "1120S": ("Corporation's employer identification number", "Corporation's name, address, city, state, and ZIP code"),
    "1041": ("Estate's or trust's employer identification number", "Estate's or trust's name"),
}
# How far a box's value area reaches from its label, in PDF points: (left, right, height).
AMOUNT_AREA = (-8, 118, 24)
CODED_AREA = (-22, 112, 200)

BROKER_LINES = {
    "DIV 1a": "1a Total ordinary dividends",
    "DIV 1b": "1b Qualified dividends",
    "DIV 2a": "2a Total capital gain distributions",
    "DIV 3": "3 Nondividend distributions",
    "DIV 5": "5 Section 199A dividends",
    "DIV 7": "7 Foreign tax paid",
    "INT 1": "1 Interest income",
    "INT 3": "3 Interest on U.S. Treasury obligations",
    "INT 4": "4 Federal income tax withheld",
    "INT 8": "8 Tax-exempt interest",
}
BROKER_ROWS = {"A": "Short-term, basis reported (Box A)", "D": "Long-term, basis reported (Box D)"}
B_COLS = ["proceeds", "cost", "wash", "gain"]

AMOUNT_RE = re.compile(r"^(\(|-)?\$?\d{1,3}(,\d{3})*(\.\d{2})?\)?$")
CODE_RE = re.compile(r"^([A-Z]{1,2}\*?|\*)$")


# ---------------------------------------------------------------- pages and words

def deskew_angle(img):
    """Find the rotation that makes text rows line up, by maximising row-profile variance."""
    small = img.resize((img.width // 4, img.height // 4))
    inv = Image.fromarray(255 - np.asarray(small))
    best, best_score = 0.0, -1.0
    for a in np.arange(-2.5, 2.51, 0.1):
        score = float(np.var(np.asarray(inv.rotate(a, resample=Image.BILINEAR), dtype=np.float32).sum(axis=1)))
        if score > best_score:
            best, best_score = float(a), score
    return round(best, 2)


def ocr_words(img, psm=11):
    d = pytesseract.image_to_data(img, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
    # Drop marks that are only punctuation (bits of rules and box edges); keep "*" and "-".
    return [{"text": t.strip(), "conf": float(d["conf"][i]), "x0": d["left"][i], "y0": d["top"][i],
             "x1": d["left"][i] + d["width"][i], "y1": d["top"][i] + d["height"][i]}
            for i, t in enumerate(d["text"])
            if float(d["conf"][i]) >= 0 and (re.search(r"[A-Za-z0-9]", t) or t.strip() in ("*", "-"))]


# Blank IRS forms the K-1s are printed on. Issuers' tax software reproduces these
# layouts, so a scanned K-1 lines up with its blank form after a small shift.
TEMPLATES = {
    ("1065", 2018): "f1065sk1--2018.pdf",
    ("1065", 2019): "f1065sk1--2019.pdf",
    ("1065", 2021): "f1065sk1--2021.pdf",
    ("1065", 2025): "f1065sk1.pdf",
    ("1120S", 2025): "f1120ssk.pdf",
    ("1041", 2025): "f1041sk1.pdf",
}
UNREAD_MAX = 30  # pixels of unexplained ink a box may hold before it goes to review
MIN_SPECK = 25  # ink blobs smaller than this many pixels are scan noise, not marks
TEMPLATE_MIN = 0.6  # correlation needed to call a page a match for a blank form
_templates = {}


def templates():
    """Each blank form as a small inverted image (for matching) plus its words in pixels."""
    if not _templates:
        for key, name in TEMPLATES.items():
            path = HERE / "forms" / name
            gray = ImageOps.grayscale(pdfium.PdfDocument(path)[0].render(scale=PT).to_pil())
            with pdfplumber.open(path) as pdf:
                words = [{"text": w["text"], "conf": 100.0, "x0": w["x0"] * PT, "y0": w["top"] * PT,
                          "x1": w["x1"] * PT, "y1": w["bottom"] * PT} for w in pdf.pages[0].extract_words()]
            # Everything printed on the blank form, slightly thickened so it still covers
            # the issuer's reproduction of it after alignment.
            ink = gray.point(lambda v: 0 if v < 200 else 255).filter(ImageFilter.MinFilter(7))
            _templates[key] = (small_inverted(gray), words, ink)
    return _templates


def small_inverted(gray, f=4):
    return 255 - np.asarray(gray.resize((gray.width // f, gray.height // f), Image.BILINEAR), dtype=np.float32)


def register(page_small, tmpl_small, f=4):
    """Shift (dx, dy) in full-size pixels that lines the blank form up with the page, and how well it fits."""
    h, w = min(page_small.shape[0], tmpl_small.shape[0]), min(page_small.shape[1], tmpl_small.shape[1])
    a, b = page_small[:h, :w], tmpl_small[:h, :w]
    cross = np.fft.fft2(a) * np.conj(np.fft.fft2(b))
    r = np.fft.ifft2(cross / (np.abs(cross) + 1e-9)).real
    dy, dx = np.unravel_index(np.argmax(r), r.shape)
    dy, dx = int(dy - h if dy > h / 2 else dy), int(dx - w if dx > w / 2 else dx)
    shifted = np.roll(np.roll(b, dy, axis=0), dx, axis=1)
    return dx * f, dy * f, float(np.corrcoef(a.ravel(), shifted.ravel())[0, 1])


class Page:
    """One page: an image to show, words with pixel boxes, and a way to read any area of it.

    Born-digital pages use the PDF's text layer. Scanned pages are straightened and
    matched against the blank IRS forms; when one fits, the box labels come from the
    blank form (shifted onto the page) and each box is read by OCR on its own. A
    scanned page that matches no blank form (a brokerage statement) is OCR'd whole.
    """

    def __init__(self, pdf_path, index):
        self.index = index
        self.template = None
        raw = pdfium.PdfDocument(pdf_path)[index].render(scale=PT).to_pil()
        with pdfplumber.open(pdf_path) as pdf:
            words = pdf.pages[index].extract_words()
        self.text_layer = sum(len(w["text"]) for w in words) > 200
        gray = ImageOps.grayscale(raw)
        self.size = gray.size
        if self.text_layer:
            self.angle = 0.0
            self.shown = self.ocr_img = gray
            self.words = [{"text": w["text"], "conf": 100.0, "x0": w["x0"] * PT, "y0": w["top"] * PT,
                           "x1": w["x1"] * PT, "y1": w["bottom"] * PT} for w in words]
        else:
            self.angle = deskew_angle(gray)
            if abs(self.angle) >= 0.1:
                gray = gray.rotate(self.angle, resample=Image.BICUBIC, fillcolor=255)
            self.shown = self.ocr_img = gray
            mine = small_inverted(gray)
            fits = sorted(((register(mine, t[0]), key) for key, t in templates().items()), key=lambda r: -r[0][2])
            (dx, dy, score), key = fits[0]
            if score >= TEMPLATE_MIN:
                self.template, self.template_fit, self.shift = key, round(score, 3), (dx, dy)
                self.words = [dict(w, x0=w["x0"] + dx, x1=w["x1"] + dx, y0=w["y0"] + dy, y1=w["y1"] + dy)
                              for w in templates()[key][1]]
                # Form dropout: white out the blank form's own printing so OCR sees only
                # what the issuer filled in.
                ink = Image.new("L", gray.size, 255)
                ink.paste(templates()[key][2], (dx, dy))
                self.ocr_img = Image.fromarray(np.where(np.asarray(ink) == 0, 255, np.asarray(gray)).astype(np.uint8))
            else:
                self.words = ocr_words(gray)
        self.lines = group_lines(self.words)
        self.text = " ".join(w["text"] for w in self.words)

    def ink(self):
        """Binary ink mask of the dropped-out page: smoothed, thresholded, specks removed."""
        if not hasattr(self, "_ink"):
            g = np.asarray(self.ocr_img.filter(ImageFilter.MedianFilter(3)), dtype=np.uint8)
            hist = np.bincount(g.ravel(), minlength=256).astype(np.float64)
            w, mu = np.cumsum(hist), np.cumsum(hist * np.arange(256))
            with np.errstate(divide="ignore", invalid="ignore"):
                between = (mu[-1] * w / w[-1] - mu) ** 2 / (w * (w[-1] - w))
            ink = g < int(np.nanargmax(between))  # Otsu threshold
            labels, n = ndimage.label(ink)
            sizes = ndimage.sum(ink, labels, range(1, n + 1))
            keep = []
            for i, (sl, size) in enumerate(zip(ndimage.find_objects(labels), sizes), 1):
                h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
                rule = (h > 60 and w < 12) or (w > 120 and h < 12)  # leftover form rules, not characters
                if size >= MIN_SPECK and not rule:
                    keep.append(i)
            self._ink = np.isin(labels, keep)
        return self._ink

    def area_words(self, box, psm=6, second=False):
        """Words inside an area: filtered from the text layer, or OCR of that area on its own.

        The first OCR pass reads the cleaned ink mask; the second (second=True) reads the
        grey dropped-out image at a larger scale, as an independent check.
        """
        x0, y0, x1, y1 = [int(v) for v in box]
        if self.text_layer:
            return [w for w in self.words
                    if x0 <= (w["x0"] + w["x1"]) / 2 <= x1 and y0 <= (w["y0"] + w["y1"]) / 2 <= y1]
        x0, y0 = max(0, x0), max(0, y0)
        ink = self.ink()[y0:y1, x0:x1]
        self.last_unread = 0
        if not ink.any():
            return []
        k = 3 if second else 2
        img = self.ocr_img.crop((x0, y0, x1, y1)) if second else Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
        img = ImageOps.expand(img.resize((img.width * k, img.height * k), Image.LANCZOS), border=30, fill=255)
        words = ocr_words(img, psm=psm)
        for w in words:
            w["x0"] = x0 + (w["x0"] - 30) / k
            w["x1"] = x0 + (w["x1"] - 30) / k
            w["y0"] = y0 + (w["y0"] - 30) / k
            w["y1"] = y0 + (w["y1"] - 30) / k
        if second:
            return words
        # Ink that no word accounts for (a minus sign OCR skipped, a faint digit) is a reason to look.
        left = ink.copy()
        for w in words:
            left[max(0, int(w["y0"] - y0) - 2):int(w["y1"] - y0) + 2, max(0, int(w["x0"] - x0) - 2):int(w["x1"] - x0) + 2] = False
        self.last_unread = int(left.sum())
        return words


def group_lines(words):
    """Group words into visual lines by vertical overlap."""
    lines = []
    for w in sorted(words, key=lambda w: (w["y0"], w["x0"])):
        cy = (w["y0"] + w["y1"]) / 2
        for line in lines:
            if line["y0"] - 4 <= cy <= line["y1"] + 4:
                line["words"].append(w)
                line["y0"], line["y1"] = min(line["y0"], w["y0"]), max(line["y1"], w["y1"])
                break
        else:
            lines.append({"words": [w], "y0": w["y0"], "y1": w["y1"]})
    for line in lines:
        line["words"].sort(key=lambda w: w["x0"])
    return lines


def norm(s):
    return re.sub(r"[^a-z0-9%()]", "", s.lower().replace("’", "'"))


def find_label(page, label, x_min=0, x_max=10**9, exclude=(), number=None):
    """Best run of consecutive words on one line that reads like the label: (score, bbox).

    With a box number, the run must also start with that number ("15 Credits"), so a
    short label can't match the same word elsewhere on the page. The bbox returned
    covers the label words only.
    """
    target = norm(label)
    n = len(label.split())
    best = (0.0, None)
    for line in page.lines:
        ws = [w for w in line["words"] if x_min <= w["x0"] <= x_max]
        for size in {max(1, n - 1), n, n + 1}:
            for i in range(0, max(1, len(ws) - size + 1)):
                run = ws[i:i + size]
                if not run:
                    continue
                if number is not None:
                    if i == 0 or norm(ws[i - 1]["text"]) != norm(number):
                        continue
                box = (run[0]["x0"], min(w["y0"] for w in run), run[-1]["x1"], max(w["y1"] for w in run))
                if box in exclude:
                    continue
                score = SequenceMatcher(None, norm(" ".join(w["text"] for w in run)), target).ratio()
                if score > best[0]:
                    best = (score, box)
    return best


def parse_value(text):
    """Returns (value, kind): kind is amount, statement, text, blank or unreadable."""
    t = text.replace("$", "").replace(" ", "")
    if not t:
        return None, "blank"
    if t in ("-", "—", "–"):
        return 0, "amount"
    if t.upper() == "STMT":
        return "STMT", "statement"
    if AMOUNT_RE.match(t):
        neg = t.startswith("(") or t.startswith("-")
        v = float(t.strip("()-").replace(",", ""))
        if "." not in t:
            v = int(v)
        return (-v if neg else v), "amount"
    if re.fullmatch(r"[A-Z]{2,}", t):
        return t, "text"  # e.g. a country code in the foreign transactions box
    return None, "unreadable"


def bbox_of(words):
    return [min(w["x0"] for w in words), min(w["y0"] for w in words),
            max(w["x1"] for w in words), max(w["y1"] for w in words)]


def make_field(page, key, label, value, raw, bbox, conf, reasons):
    W, H = page.size
    return {"key": key, "label": label, "value": value, "raw": raw, "page": page.index,
            "bbox": [round(bbox[0] / W, 4), round(bbox[1] / H, 4), round(bbox[2] / W, 4), round(bbox[3] / H, 4)] if bbox else None,
            "confidence": round(conf), "reasons": reasons}


def judge(kind, raw, conf, ocr):
    if kind == "unreadable":
        return [f"can't read '{raw}' as an amount"]
    if kind == "statement":
        return ["amount is on the attached statement"]
    if ocr and kind != "blank" and conf < CONF_MIN:
        return [f"OCR confidence {conf:.0f}"]
    return []


# ---------------------------------------------------------------- K-1

def k1_kind(text):
    t = norm(text)
    if "shareholdersshareofcurrentyear" in t:
        return "1120S"
    if "beneficiarysshareofcurrentyear" in t:
        return "1041"
    if "partnersshareofcurrentyear" in t:
        return "1065"
    return None


def k1_year(page):
    m = re.search(r"calendar\s*year\s*(20\d\d)", page.text, re.I) or re.search(r"\(Form\s*1065\)\s*(20\d\d)", page.text)
    return int(m.group(1)) if m else 2025


def extract_header(page, form):
    """Payer EIN and name: the line under each label in Part I."""
    fields = []
    W = page.size[0]
    for key, label in zip(("payer_ein", "payer_name"), HEADER_LABELS[form]):
        score, bb = find_label(page, label, x_max=W * 0.5)
        if not bb or score < LABEL_MIN:
            fields.append(make_field(page, key, label, None, "", None, 0, ["label not found"]))
            continue
        area = (bb[0] - 20 * PT, bb[3] + 1, bb[0] + 250 * PT, bb[3] + 26 * PT)
        words = page.area_words(area, psm=7)
        rows = group_lines(words)
        ws = rows[0]["words"] if rows else []
        raw = " ".join(w["text"] for w in ws)
        conf = min((w["conf"] for w in ws), default=0)
        reasons = [] if ws else ["nothing found under the label"]
        if ws and not page.text_layer and conf < CONF_MIN:
            reasons.append(f"OCR confidence {conf:.0f}")
        fields.append(make_field(page, key, label, raw or None, raw, bbox_of(ws) if ws else area, conf, reasons))
    return fields


def coded_rows(words):
    """Rows of a coded box as (code, raw amount, value, kind, words).

    A row that is only a code joins the row after it (OCR sometimes splits them), and
    a bare STMT is the "*" row: issuers print "* STMT" when the detail is attached.
    """
    rows = [r["words"] for r in group_lines(words)]
    rows = [ws for ws in rows if not re.fullmatch(r"[a-z ,.()]+", " ".join(w["text"] for w in ws))]  # 2nd line of a label
    out, i = [], 0
    while i < len(rows):
        ws = rows[i]
        if (len(ws) == 1 and is_code(ws[0]["text"]) and i + 1 < len(rows) and not is_code(rows[i + 1][0]["text"])
                and rows[i + 1][0]["y0"] - ws[0]["y1"] < 6 * PT):
            ws = ws + rows[i + 1]
            i += 1
        i += 1
        if len(ws) == 1 and ws[0]["text"].upper() == "STMT":
            out.append(("*", "STMT", "STMT", "statement", ws))
        elif len(ws) >= 2 and is_code(ws[0]["text"]):
            raw = " ".join(w["text"] for w in ws[1:])
            value, kind = parse_value(raw)
            out.append((code_of(ws[0]["text"]), raw, value, kind, ws))
        else:
            out.append(("?", " ".join(w["text"] for w in ws), None, "unreadable", ws))
    return out


def is_code(t):
    return bool(CODE_RE.match(t)) or bool(re.fullmatch(r"([A-Za-z])\1?\*?", t, re.I))


def code_of(t):
    """Codes are capital letters; OCR sometimes doubles a letter in the other case ("Cc")."""
    m = re.fullmatch(r"([A-Za-z])\1\*?", t, re.I)
    return (m.group(1).upper() + ("*" if t.endswith("*") else "")) if m and len(t.rstrip("*")) == 2 and t[0] != t[1] else t.upper()


def extract_k1(page, form, year):
    W = page.size[0]
    labels = k1_1065_labels(year) if form == "1065" else K1_LABELS[form]
    found = {box: find_label(page, label, x_min=W * 0.48, number=box) for box, (label, _k) in labels.items()}
    stops = [find_label(page, s, x_min=W * 0.48) for s in STOP_LABELS]
    anchors = [bb for s, bb in list(found.values()) + stops if bb and s >= LABEL_MIN]
    ocr = not page.text_layer
    fields = extract_header(page, form)

    for box, (label, kind) in labels.items():
        score, bb = found[box]
        if not bb or score < LABEL_MIN:
            fields.append(make_field(page, box, label, None, "", None, 0, ["label not found"]))
            continue
        if kind == "amount":
            left, right, height = AMOUNT_AREA
            area = (bb[0] + left * PT, bb[3] + 1, bb[0] + right * PT, bb[1] + height * PT - 2)
            words = page.area_words(area, psm=7)
            unread = getattr(page, "last_unread", 0)
            raw = " ".join(w["text"] for w in words)
            value, vkind = parse_value(raw)
            conf = min((w["conf"] for w in words), default=100.0)
            reasons = judge(vkind, raw, conf, ocr)
            if ocr and not reasons:
                raw2 = " ".join(w["text"] for w in page.area_words(area, psm=7, second=True))
                if parse_value(raw2)[0] != value:
                    reasons.append(f"a second OCR pass read '{raw2}'")
            if unread > UNREAD_MAX and not reasons:
                reasons.append("marks in the box that OCR didn't read")
            fields.append(make_field(page, box, label, value, raw, bbox_of(words) if words else area, conf, reasons))
            continue
        # A coded box runs down to the next label in the same column.
        left, right, height = CODED_AREA
        x0, x1 = bb[0] + left * PT, bb[0] + right * PT
        below = [a[1] for a in anchors if a[0] < x1 and a[2] > x0 and a[1] > bb[3] + 4]
        bottom = min(below + [bb[1] + height * PT]) - 4
        area = (x0, bb[3] + 2, x1, bottom)
        rows = coded_rows(page.area_words(area, psm=6))
        unread = getattr(page, "last_unread", 0)
        second = {code: value for code, _r, value, _k, _w in coded_rows(page.area_words(area, psm=6, second=True))} if ocr else None
        first = len(fields)
        seen = set()
        for code, raw, value, vkind, ws in rows:
            conf = min(w["conf"] for w in ws)
            text = " ".join(w["text"] for w in ws)
            if code == "?":
                reasons = [f"can't read '{text}' as a code and amount"]
            else:
                reasons = judge(vkind, raw, conf, ocr)
                if second is not None and not reasons and second.get(code, "missing") != value:
                    reasons.append("a second OCR pass read this row differently")
            key = f"{box} {code}"
            if key in seen and code != "?":
                key = f"{box} {code} (again)"
                reasons = [f"code {code} appears twice in box {box}"] + reasons
            seen.add(key)
            fields.append(make_field(page, key, f"{label}, code {code}", value, text, bbox_of(ws), conf, reasons))
        if unread > UNREAD_MAX:
            if len(fields) == first:
                fields.append(make_field(page, f"{box} ?", f"{label}, code ?", None, "", area, 0,
                                         ["marks in the box that OCR didn't read"]))
            for f in fields[first:]:
                if not f["reasons"]:
                    f["reasons"].append("marks in the box that OCR didn't read")

    def get(k):
        return next((f for f in fields if f["key"] == k), None)

    total, part = {"1065": ("6a", "6b"), "1120S": ("5a", "5b"), "1041": ("2a", "2b")}[form]
    t, p = get(total), get(part)
    if t and p and isinstance(p["value"], (int, float)):
        if t["value"] is None:
            p["reasons"].append(f"qualified dividends ({part}) present but ordinary dividends ({total}) blank")
        elif isinstance(t["value"], (int, float)) and p["value"] > t["value"]:
            for f in (t, p):
                f["reasons"].append(f"qualified dividends ({part}) exceed ordinary dividends ({total})")
    if form == "1065" and get("4c"):
        a, b, c = [(get(k)["value"] or 0) if get(k) and isinstance(get(k)["value"], (int, float)) else 0 for k in ("4a", "4b", "4c")]
        if a + b != c:
            for k in ("4a", "4b", "4c"):
                get(k)["reasons"].append("4a + 4b doesn't equal 4c")
    return fields


# ---------------------------------------------------------------- brokerage 1099

def extract_broker(pages):
    page = pages[0]
    W = page.size[0]
    ocr = not page.text_layer
    fields, used = [], []
    for key, label in BROKER_LINES.items():
        score, bb = find_label(page, label, x_max=W * 0.5, exclude=used)
        if not bb or score < LABEL_MIN:
            fields.append(make_field(page, key, label, None, "", None, 0, ["label not found"]))
            continue
        used.append(bb)
        area = (W * 0.75, bb[1] - 6, W - 20, bb[3] + 6)
        words = [w for w in page.area_words(area) if re.search(r"\d", w["text"])]
        raw = " ".join(w["text"] for w in words)
        value, vkind = parse_value(raw)
        conf = min((w["conf"] for w in words), default=0.0)
        reasons = ["no amount found on the line"] if not words else judge(vkind, raw, conf, ocr)
        if ocr and not reasons:
            raw2 = " ".join(w["text"] for w in page.area_words(area, second=True) if re.search(r"\d", w["text"]))
            if parse_value(raw2)[0] != value:
                reasons.append(f"a second OCR pass read '{raw2}'")
        fields.append(make_field(page, key, label, value, raw, bbox_of(words) if words else bb, conf, reasons))

    for term, label in BROKER_ROWS.items():
        score, bb = find_label(page, label, x_max=W * 0.5)
        if not bb or score < LABEL_MIN:
            for col in B_COLS:
                fields.append(make_field(page, f"B {term} {col}", f"1099-B {label}: {col}", None, "", None, 0, ["label not found"]))
            continue
        area = (W * 0.38, bb[1] - 6, W - 20, bb[3] + 6)
        words = [w for w in page.area_words(area) if re.search(r"\d", w["text"])]
        second = [parse_value(w["text"])[0] for w in page.area_words(area, second=True) if re.search(r"\d", w["text"])] if ocr else None
        for i, col in enumerate(B_COLS):
            w = words[i] if len(words) == 4 else None
            if w:
                value, vkind = parse_value(w["text"])
                reasons = judge(vkind, w["text"], w["conf"], ocr)
                if second is not None and not reasons and (len(second) != 4 or second[i] != value):
                    reasons.append("a second OCR pass read this row differently")
            else:
                value, reasons = None, [f"expected 4 amounts on the row, read {len(words)}"]
            fields.append(make_field(page, f"B {term} {col}", f"1099-B {label}: {col}", value, w["text"] if w else "",
                                     bbox_of([w]) if w else bb, w["conf"] if w else 0, reasons))

    def get(k):
        return next(f for f in fields if f["key"] == k)

    a, q = get("DIV 1a"), get("DIV 1b")
    if isinstance(a["value"], (int, float)) and isinstance(q["value"], (int, float)) and q["value"] > a["value"]:
        for f in (a, q):
            f["reasons"].append("qualified dividends (1b) exceed ordinary dividends (1a)")
    # Each summary row must balance, and must equal the sum of the detail page.
    detail, detail_ok = {"A": [0.0] * 4, "D": [0.0] * 4}, len(pages) > 1
    if detail_ok:
        dp = pages[1]
        for line in dp.lines:
            ws = line["words"]
            if not ws or ws[0]["text"] not in ("A", "D") or ws[0]["x0"] > dp.size[0] * 0.15:
                continue
            nums = [w for w in dp.area_words((dp.size[0] * 0.4, line["y0"] - 6, dp.size[0] - 20, line["y1"] + 6))
                    if re.search(r"\d", w["text"])]
            vals = [parse_value(w["text"]) for w in nums]
            if len(vals) != 4 or any(k != "amount" for _v, k in vals):
                detail_ok = False
                continue
            for i, (v, _k) in enumerate(vals):
                detail[ws[0]["text"]][i] += v
    for term in BROKER_ROWS:
        row = [get(f"B {term} {c}") for c in B_COLS]
        vals = [f["value"] for f in row]
        if not all(isinstance(v, (int, float)) for v in vals):
            continue
        p, c, wsh, g = vals
        if abs(p - c + wsh - g) > 0.011:
            for f in row:
                f["reasons"].append("proceeds - cost + wash sale doesn't equal gain or loss")
        for f, total in zip(row, detail[term]):
            if not detail_ok:
                f["reasons"].append("couldn't read the detail page to check this total")
            elif abs(f["value"] - total) > 0.011:
                f["reasons"].append(f"doesn't match the detail page total ({total:,.2f})")
    return fields


# ---------------------------------------------------------------- main

def process(path):
    n_pages = len(pdfium.PdfDocument(path))
    pages = {}

    def page(i):
        if i not in pages:
            pages[i] = Page(path, i)
        return pages[i]

    form, fields, year, k1_index, statement_pages = None, [], None, None, []
    for i in range(n_pages):
        p = page(i)
        if "consolidated form 1099" in p.text.lower():
            form = "BROKER"
            fields = extract_broker([p] + ([page(i + 1)] if i + 1 < n_pages else []))
            break
        kind, kyear = p.template if p.template else (k1_kind(p.text), None)
        if kind and k1_index is None:
            form, year, k1_index = kind, kyear or k1_year(p), i
            fields = extract_k1(p, kind, year)
        elif k1_index is not None and "supplemental" in p.text.lower():
            statement_pages.append(i)
    for f in fields:
        if statement_pages and f["value"] == "STMT":
            f["reasons"] = [f"amount is on the attached statement (page {statement_pages[0] + 1})"]
            f["statement_page"] = statement_pages[0]
        f["status"] = "review" if f["reasons"] else "accepted"
    return form, year, pages, fields, k1_index, statement_pages


def main():
    (OUT / "pages").mkdir(parents=True, exist_ok=True)
    files = sorted(SAMPLES.glob("*.pdf"))
    if len(sys.argv) > 1:
        files = [f for f in files if any(a in f.name for a in sys.argv[1:])]
    docs = []
    for path in files:
        t0 = time.time()
        form, year, pages, fields, k1_index, statement_pages = process(path)
        elapsed = time.time() - t0
        page_files = {}
        for i, p in sorted(pages.items()):
            if i != k1_index and i not in statement_pages[:1] and form != "BROKER":
                continue
            name = f"{path.stem}-p{i + 1}.jpg"
            p.shown.resize((p.size[0] // 2, p.size[1] // 2)).convert("L").save(OUT / "pages" / name, quality=72)
            page_files[i] = f"pages/{name}"
        main_page = pages[k1_index if k1_index is not None else 0]
        docs.append({"file": path.name, "form": form, "year": year,
                     "source": "text layer" if main_page.text_layer else "OCR",
                     "blank_form": TEMPLATES[main_page.template] if main_page.template else None,
                     "blank_form_fit": getattr(main_page, "template_fit", None),
                     "deskew_degrees": main_page.angle,
                     "pages": {str(k): v for k, v in page_files.items()}, "seconds": round(elapsed, 1), "fields": fields})
        n_review = sum(f["status"] == "review" for f in fields)
        print(f"{path.name:38s} {str(form):6s} {docs[-1]['source']:10s} {len(fields):3d} values, {n_review:2d} to review, {elapsed:5.1f}s")
    (OUT / "extracted.json").write_text(json.dumps({
        "tesseract": str(pytesseract.get_tesseract_version()).split()[0], "dpi": DPI, "conf_min": CONF_MIN,
        "documents": docs}, indent=1))


if __name__ == "__main__":
    main()
