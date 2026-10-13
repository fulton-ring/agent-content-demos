"""Extract K-1 and brokerage 1099 values, with the page and box each one came from.

For every document in samples/: render each page, clean it up (deskew, denoise,
threshold), OCR it with Tesseract, find each box by its printed label, then OCR
the box's value area on its own. Every value carries its page, its bounding box
and a confidence. A value goes to the review queue when OCR is unsure of it, it
doesn't parse as an amount, its label couldn't be found, or it fails a
cross-check (qualified dividends above ordinary dividends, a 1099-B summary that
doesn't add up, and so on).

Writes output/extracted.json and one image per page under output/pages/.
Never reads answer_key.json.
"""

import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageFilter, ImageOps

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
OUT = HERE / "output"
DPI = 300
PT = DPI / 72  # pixels per PDF point
CONF_MIN = 80  # Tesseract word confidence below this sends a value to review

# Labels as printed on the 2025 forms. "coded" boxes hold one or more code + amount rows.
K1_LABELS = {
    "1065": {
        "1": ("Ordinary business income (loss)", "amount"),
        "2": ("Net rental real estate income (loss)", "amount"),
        "3": ("Other net rental income (loss)", "amount"),
        "4a": ("Guaranteed payments for services", "amount"),
        "4b": ("Guaranteed payments for capital", "amount"),
        "4c": ("Total guaranteed payments", "amount"),
        "5": ("Interest income", "amount"),
        "6a": ("Ordinary dividends", "amount"),
        "6b": ("Qualified dividends", "amount"),
        "7": ("Royalties", "amount"),
        "8": ("Net short-term capital gain (loss)", "amount"),
        "9a": ("Net long-term capital gain (loss)", "amount"),
        "10": ("Net section 1231 gain (loss)", "amount"),
        "12": ("Section 179 deduction", "amount"),
        "13": ("Other deductions", "coded"),
        "14": ("Self-employment earnings (loss)", "coded"),
        "19": ("Distributions", "coded"),
        "20": ("Other information", "coded"),
        "21": ("Foreign taxes paid or accrued", "amount"),
    },
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
# How far a box's value area reaches from its label, in PDF points: (left, right, height).
# A plain box is one 24pt row with the amount bottom-right; a coded box runs down
# until the next label in the same column.
AMOUNT_AREA = (-8, 118, 24)
CODED_AREA = (-30, 112, 120)

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

AMOUNT_RE = re.compile(r"^\(?-?\$?\d{1,3}(,\d{3})*(\.\d{2})?\)?$")


# ---------------------------------------------------------------- image cleanup

def deskew_angle(img):
    """Find the rotation that makes text rows line up, by maximising row-profile variance."""
    small = img.resize((img.width // 4, img.height // 4))
    arr = 255 - np.asarray(small, dtype=np.float32)
    best, best_score = 0.0, -1
    for a in np.arange(-2.5, 2.51, 0.1):
        rot = np.asarray(Image.fromarray(arr.astype(np.uint8)).rotate(a, resample=Image.BILINEAR), dtype=np.float32)
        score = np.var(rot.sum(axis=1))
        if score > best_score:
            best, best_score = float(a), score
    return round(best, 2)


def clean(img):
    g = ImageOps.grayscale(img)
    angle = deskew_angle(g)
    if abs(angle) >= 0.1:
        g = g.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    g = g.filter(ImageFilter.MedianFilter(3))
    g = ImageOps.autocontrast(g, cutoff=1)
    arr = np.asarray(g)
    # Otsu threshold
    hist = np.bincount(arr.ravel(), minlength=256).astype(np.float64)
    w = np.cumsum(hist)
    mu = np.cumsum(hist * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu[-1] * w / w[-1] - mu) ** 2 / (w * (w[-1] - w))
    t = int(np.nanargmax(between))
    return Image.fromarray(np.where(arr > t, 255, 0).astype(np.uint8)), angle


# ---------------------------------------------------------------- OCR helpers

def ocr_words(img, psm=11):
    d = pytesseract.image_to_data(img, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
    words = []
    for i, text in enumerate(d["text"]):
        if text.strip():
            words.append({"text": text.strip(), "conf": float(d["conf"][i]),
                          "x0": d["left"][i], "y0": d["top"][i],
                          "x1": d["left"][i] + d["width"][i], "y1": d["top"][i] + d["height"][i],
                          "key": (d["block_num"][i], d["par_num"][i], d["line_num"][i])})
    return words


def group_lines(words):
    """Group words into visual lines by vertical overlap (more robust than Tesseract's line ids in sparse mode)."""
    lines = []
    for w in sorted(words, key=lambda w: (w["y0"], w["x0"])):
        cy = (w["y0"] + w["y1"]) / 2
        for line in lines:
            if line["y0"] - 4 <= cy <= line["y1"] + 4 and abs(line["h"] - (w["y1"] - w["y0"])) < 30:
                line["words"].append(w)
                line["y0"] = min(line["y0"], w["y0"])
                line["y1"] = max(line["y1"], w["y1"])
                break
        else:
            lines.append({"words": [w], "y0": w["y0"], "y1": w["y1"], "h": w["y1"] - w["y0"]})
    for line in lines:
        line["words"].sort(key=lambda w: w["x0"])
    return lines


def norm(s):
    return re.sub(r"[^a-z0-9%()]", "", s.lower())


def find_label(lines, label, x_min=0, x_max=10**9, exclude=()):
    """Best run of consecutive words that reads like the label. Returns (score, bbox)."""
    target = norm(label)
    n = len(label.split())
    best = (0.0, None)
    for line in lines:
        ws = [w for w in line["words"] if x_min <= w["x0"] <= x_max]
        for size in {max(1, n - 1), n, n + 1}:
            for i in range(0, max(1, len(ws) - size + 1)):
                run = ws[i:i + size]
                if not run:
                    continue
                score = SequenceMatcher(None, norm(" ".join(w["text"] for w in run)), target).ratio()
                box = (run[0]["x0"], min(w["y0"] for w in run), run[-1]["x1"], max(w["y1"] for w in run))
                if box in exclude:
                    continue
                if score > best[0]:
                    best = (score, box)
    return best


def parse_amount(text):
    t = text.replace("$", "").replace(" ", "")
    if not t:
        return None, True
    if not AMOUNT_RE.match(t):
        return None, False
    neg = t.startswith("(") or t.startswith("-")
    v = float(t.strip("()-").replace(",", ""))
    if v.is_integer() and "." not in t:
        v = int(v)
    return (-v if neg else v), True


def read_area(img, box, psm=6):
    """OCR one area of the page on its own. Returns words with page coordinates."""
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    crop = img.crop((x0, y0, x1, y1))
    pad = ImageOps.expand(crop, border=20, fill=255)
    words = ocr_words(pad, psm=psm)
    for w in words:
        w["x0"] += x0 - 20
        w["x1"] += x0 - 20
        w["y0"] += y0 - 20
        w["y1"] += y0 - 20
    return words


def bbox_of(words):
    return [min(w["x0"] for w in words), min(w["y0"] for w in words),
            max(w["x1"] for w in words), max(w["y1"] for w in words)]


def field(key, label, value, raw, page, bbox, conf, reasons, size):
    W, H = size
    return {"key": key, "label": label, "value": value, "raw": raw, "page": page,
            "bbox": [round(bbox[0] / W, 4), round(bbox[1] / H, 4), round(bbox[2] / W, 4), round(bbox[3] / H, 4)] if bbox else None,
            "confidence": conf, "reasons": reasons}


# ---------------------------------------------------------------- K-1

def detect_form(lines):
    text = " ".join(w["text"] for line in lines for w in line["words"]).lower()
    if "consolidated form 1099" in text or "form 1099-div" in text:
        return "BROKER"
    if "1120-s" in text or "1120s" in text or "shareholder" in text:
        return "1120S"
    if "1041" in text or "beneficiary" in text:
        return "1041"
    if "1065" in text or "partner" in text:
        return "1065"
    return None


def extract_k1(form, img, lines):
    W, H = img.size
    fields = []
    labels = K1_LABELS[form]
    found = {}
    # Part III sits in the right half of the page.
    for box, (label, kind) in labels.items():
        score, bb = find_label(lines, label, x_min=W * 0.5)
        found[box] = (score, bb)
    label_tops = [(bb[0], bb[1]) for s, bb in found.values() if bb and s >= 0.75]

    for box, (label, kind) in labels.items():
        score, bb = found[box]
        if not bb or score < 0.75:
            fields.append(field(box, label, None, "", 0, None, 0, ["label not found"], img.size))
            continue
        if kind == "amount":
            left, right, height = AMOUNT_AREA
            area = (bb[0] + left * PT, bb[3] + 1, bb[0] + right * PT, bb[1] + height * PT - 2)
            words = [w for w in read_area(img, area, psm=7) if w["conf"] >= 0]
            raw = " ".join(w["text"] for w in words)
            reasons = []
            value, ok = parse_amount(raw)
            conf = min((w["conf"] for w in words), default=100.0)
            if not ok:
                reasons.append(f"can't read '{raw}' as an amount")
            elif words and conf < CONF_MIN:
                reasons.append(f"OCR confidence {conf:.0f}")
            fields.append(field(box, label, value, raw, 0, bbox_of(words) if words else area, round(conf), reasons, img.size))
        else:
            left, right, height = CODED_AREA
            # stop at the next label below in the same column
            below = [t for x, t in label_tops if abs(x - bb[0]) < 40 * PT and t > bb[3] + 4]
            bottom = min(below + [bb[1] + height * PT]) - 4
            area = (bb[0] + left * PT, bb[3] + 2, bb[0] + right * PT, bottom)
            words = [w for w in read_area(img, area, psm=6) if w["conf"] >= 0]
            for row in group_lines(words):
                ws = row["words"]
                text = " ".join(w["text"] for w in ws)
                m = re.match(r"^([A-Z]{1,2})\s+(\S+)$", text)
                conf = min(w["conf"] for w in ws)
                if m:
                    code = m.group(1)
                    value, ok = parse_amount(m.group(2))
                else:
                    code, value, ok = "?", None, False
                reasons = []
                if not ok:
                    reasons.append(f"can't read '{text}' as a code and amount")
                elif conf < CONF_MIN:
                    reasons.append(f"OCR confidence {conf:.0f}")
                fields.append(field(f"{box} {code}", f"{label}, code {code}", value, text, 0,
                                    bbox_of(ws), round(conf), reasons, img.size))

    def get(k):
        return next((f for f in fields if f["key"] == k), None)

    pairs = {"1065": [("6a", "6b")], "1120S": [("5a", "5b")], "1041": [("2a", "2b")]}[form]
    for total, part in pairs:
        t, p = get(total), get(part)
        if t and p and isinstance(t["value"], (int, float)) and isinstance(p["value"], (int, float)) and p["value"] > t["value"]:
            for f in (t, p):
                f["reasons"].append(f"qualified dividends ({part}) exceed ordinary dividends ({total})")
        if p and p["value"] is not None and t and t["value"] is None:
            p["reasons"].append(f"qualified dividends ({part}) present but ordinary dividends ({total}) blank")
    if form == "1065":
        a, b, c = get("4a"), get("4b"), get("4c")
        av, bv, cv = [(f["value"] or 0) if f else 0 for f in (a, b, c)]
        if (av or bv or cv) and av + bv != cv:
            for f in (a, b, c):
                if f:
                    f["reasons"].append("4a + 4b doesn't equal 4c")
    return fields


# ---------------------------------------------------------------- brokerage 1099

def amounts_on_line(img, line_box, x_min):
    words = read_area(img, (x_min, line_box[1] - 6, img.width - 20, line_box[3] + 6), psm=6)
    return [w for w in words if re.search(r"\d", w["text"])]


def extract_broker(pages):
    fields = []
    img, lines = pages[0]
    W, H = img.size
    used = []
    for key, label in BROKER_LINES.items():
        score, bb = find_label(lines, label, x_max=W * 0.5, exclude=used)
        if not bb or score < 0.75:
            fields.append(field(key, label, None, "", 0, None, 0, ["label not found"], img.size))
            continue
        used.append(bb)
        words = amounts_on_line(img, bb, W * 0.75)
        raw = " ".join(w["text"] for w in words)
        value, ok = parse_amount(raw)
        conf = min((w["conf"] for w in words), default=0.0)
        reasons = []
        if not words:
            reasons.append("no amount found on the line")
        elif not ok:
            reasons.append(f"can't read '{raw}' as an amount")
        elif conf < CONF_MIN:
            reasons.append(f"OCR confidence {conf:.0f}")
        fields.append(field(key, label, value, raw, 0, bbox_of(words) if words else bb, round(conf), reasons, img.size))

    for term, label in BROKER_ROWS.items():
        score, bb = find_label(lines, label, x_max=W * 0.5)
        if not bb or score < 0.75:
            for col in B_COLS:
                fields.append(field(f"B {term} {col}", f"1099-B {label}: {col}", None, "", 0, None, 0, ["label not found"], img.size))
            continue
        words = amounts_on_line(img, bb, W * 0.38)
        for i, col in enumerate(B_COLS):
            w = words[i] if i < len(words) and len(words) == 4 else None
            reasons = [] if len(words) == 4 else [f"expected 4 amounts on the row, read {len(words)}"]
            value, ok = parse_amount(w["text"]) if w else (None, False)
            if w and not ok:
                reasons.append(f"can't read '{w['text']}' as an amount")
            elif w and w["conf"] < CONF_MIN:
                reasons.append(f"OCR confidence {w['conf']:.0f}")
            fields.append(field(f"B {term} {col}", f"1099-B {label}: {col}", value, w["text"] if w else "", 0,
                                bbox_of([w]) if w else bb, round(w["conf"]) if w else 0, reasons, img.size))

    def get(k):
        return next(f for f in fields if f["key"] == k)

    a, q = get("DIV 1a"), get("DIV 1b")
    if a["value"] is not None and q["value"] is not None and q["value"] > a["value"]:
        for f in (a, q):
            f["reasons"].append("qualified dividends (1b) exceed ordinary dividends (1a)")
    # Each summary row must balance, and must equal the sum of the detail page.
    detail = {"A": [0.0] * 4, "D": [0.0] * 4}
    detail_ok = len(pages) > 1
    if detail_ok:
        dimg, dlines = pages[1]
        for line in dlines:
            ws = line["words"]
            if not ws or ws[0]["text"] not in ("A", "D") or ws[0]["x0"] > dimg.width * 0.15:
                continue
            nums = [w for w in read_area(dimg, (dimg.width * 0.4, line["y0"] - 6, dimg.width - 20, line["y1"] + 6), psm=6)
                    if re.search(r"\d", w["text"])]
            vals = [parse_amount(w["text"])[0] for w in nums]
            if len(vals) != 4 or any(v is None for v in vals):
                detail_ok = False
                continue
            for i, v in enumerate(vals):
                detail[ws[0]["text"]][i] += v
    for term in BROKER_ROWS:
        row = [get(f"B {term} {c}") for c in B_COLS]
        vals = [f["value"] for f in row]
        if None in vals:
            continue
        p, c, wsh, g = vals
        if abs(p - c + wsh - g) > 0.011:
            for f in row:
                f["reasons"].append("proceeds - cost + wash sale doesn't equal gain or loss")
        if detail_ok:
            for f, total in zip(row, detail[term]):
                if abs(f["value"] - total) > 0.011:
                    f["reasons"].append(f"doesn't match the detail page total ({total:,.2f})")
        else:
            for f in row:
                f["reasons"].append("couldn't read the detail page to check this total")
    return fields


# ---------------------------------------------------------------- main

def main():
    OUT.mkdir(exist_ok=True)
    (OUT / "pages").mkdir(exist_ok=True)
    docs = []
    files = sorted(SAMPLES.glob("*.pdf"))
    if len(sys.argv) > 1:
        files = [f for f in files if any(a in f.name for a in sys.argv[1:])]
    for path in files:
        t0 = time.time()
        pdf = pdfium.PdfDocument(path)
        pages, page_files, angles = [], [], []
        for i, page in enumerate(pdf):
            raw = page.render(scale=PT).to_pil()
            img, angle = clean(raw)
            angles.append(angle)
            lines = group_lines(ocr_words(img, psm=11))
            pages.append((img, lines))
            name = f"{path.stem}-p{i + 1}.jpg"
            # Show reviewers the page as it arrived (straightened so boxes line up).
            shown = ImageOps.grayscale(raw).rotate(angle, resample=Image.BICUBIC, fillcolor=255) if abs(angle) >= 0.1 else ImageOps.grayscale(raw)
            shown.resize((shown.width // 2, shown.height // 2)).save(OUT / "pages" / name, quality=70)
            page_files.append(f"pages/{name}")
        form = detect_form(pages[0][1])
        if form == "BROKER":
            fields = extract_broker(pages)
        elif form:
            fields = extract_k1(form, *pages[0])
        else:
            fields = []
        for f in fields:
            f["status"] = "review" if f["reasons"] else "accepted"
        elapsed = time.time() - t0
        docs.append({"file": path.name, "form": form, "pages": page_files, "deskew_degrees": angles,
                     "seconds": round(elapsed, 1), "fields": fields})
        n_review = sum(f["status"] == "review" for f in fields)
        print(f"{path.name:36s} {str(form):7s} {len(fields):3d} values, {n_review:2d} to review, {elapsed:5.1f}s")
    (OUT / "extracted.json").write_text(json.dumps({
        "tesseract": str(pytesseract.get_tesseract_version()), "dpi": DPI, "conf_min": CONF_MIN,
        "documents": docs}, indent=1))


if __name__ == "__main__":
    main()
