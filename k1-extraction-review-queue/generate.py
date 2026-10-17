"""Generate the made-up sample documents and their answer key.

The partnership K-1s in this demo are real issuers' published samples (see
fetch_real.py). Real 1120-S and 1041 K-1s and brokerage 1099s aren't published
anywhere we can use, so this script makes them: it fills blank 2025 IRS
Schedule K-1 forms (1120-S, 1041) and a made-up
brokerage consolidated 1099 with invented numbers, prints them flat (no form
fields), and turns some of them into degraded "scans". Every name, ID and
amount is made up. The answer key goes to answer_key.json; extract.py never
reads it.
"""

import io
import json
import random
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent
FORMS = HERE / "forms"
SAMPLES = HERE / "samples"
SEED = 2025

# Box spec per form: key -> (pdf field for the amount, pdf field for the code or None, label)
K1_1120S = {
    "1": ("f1_21", None, "Ordinary business income (loss)"),
    "2": ("f1_22", None, "Net rental real estate income (loss)"),
    "3": ("f1_23", None, "Other net rental income (loss)"),
    "4": ("f1_24", None, "Interest income"),
    "5a": ("f1_25", None, "Ordinary dividends"),
    "5b": ("f1_26", None, "Qualified dividends"),
    "6": ("f1_27", None, "Royalties"),
    "7": ("f1_28", None, "Net short-term capital gain (loss)"),
    "8a": ("f1_29", None, "Net long-term capital gain (loss)"),
    "9": ("f1_32", None, "Net section 1231 gain (loss)"),
    "11": ("f1_43", None, "Section 179 deduction"),
    "12": ("f1_45", "f1_44", "Other deductions"),
    "13": ("f1_61", "f1_60", "Credits"),
    "16": ("f1_81", "f1_80", "Items affecting shareholder basis"),
    "17": ("f1_91", "f1_90", "Other information"),
}
K1_1041 = {
    "1": ("f1_12", None, "Interest income"),
    "2a": ("f1_13", None, "Ordinary dividends"),
    "2b": ("f1_14", None, "Qualified dividends"),
    "3": ("f1_15", None, "Net short-term capital gain"),
    "4a": ("f1_16", None, "Net long-term capital gain"),
    "5": ("f1_19", None, "Other portfolio and nonbusiness income"),
    "6": ("f1_20", None, "Ordinary business income"),
    "7": ("f1_21", None, "Net rental real estate income"),
    "8": ("f1_22", None, "Other rental income"),
    "9": ("f1_24", "f1_23", "Directly apportioned deductions"),
    "10": ("f1_29", None, "Estate tax deduction"),
    "11": ("f1_31", "f1_30", "Final year deductions"),
    "13": ("f1_51", "f1_50", "Credits and credit recapture"),
    "14": ("f1_57", "f1_56", "Other information"),
}
HEADER = {
    "1120S": {"payer_ein": "f1_06", "payer_name": "f1_07", "recipient_tin": "f1_11", "recipient_name": "f1_12"},
    "1041": {"payer_ein": "f1_6", "payer_name": "f1_7", "recipient_tin": "f1_10", "recipient_name": "f1_11"},
}
FORM_FILES = {"1120S": "f1120ssk.pdf", "1041": "f1041sk1.pdf"}
BOXES = {"1120S": K1_1120S, "1041": K1_1041}

ENTITY_WORDS = ["Harbor", "Juniper", "Granite", "Meridian", "Alder", "Kestrel", "Sable", "Copper",
                "Lantern", "Willow", "Basalt", "Heron", "Quarry", "Tamarack", "Orchard", "Beacon"]
ENTITY_KINDS = {"1120S": ["Services Inc", "Builders Inc", "Logistics Inc"],
                "1041": ["Family Trust", "Residuary Trust", "Estate"]}
PEOPLE = ["Avery Sample", "Jordan Example", "Riley Placeholder", "Morgan Testcase", "Casey Specimen",
          "Taylor Fictional", "Quinn Madeup", "Drew Notreal"]
STREETS = ["Example St", "Sample Ave", "Placeholder Rd", "Demo Blvd", "Testing Ln"]


def money(rng, lo, hi, allow_loss=False):
    v = rng.randint(lo, hi)
    if allow_loss and rng.random() < 0.3:
        v = -v
    return v


def fmt(v):
    return f"({abs(v):,})" if v < 0 else f"{v:,}"


def make_k1_values(rng, form):
    """Pick which boxes carry amounts on this K-1, and what they are."""
    vals = {}
    if form == "1120S":
        vals["1"] = money(rng, 1_000, 650_000, allow_loss=True)
        if rng.random() < 0.4:
            vals["2"] = money(rng, 500, 60_000, allow_loss=True)
        vals["4"] = money(rng, 10, 15_000)
        vals["5a"] = money(rng, 100, 40_000)
        vals["5b"] = rng.randint(0, vals["5a"])
        if rng.random() < 0.3:
            vals["6"] = money(rng, 100, 9_000)
        if rng.random() < 0.5:
            vals["7"] = money(rng, 100, 30_000, allow_loss=True)
        vals["8a"] = money(rng, 100, 120_000, allow_loss=True)
        if rng.random() < 0.4:
            vals["9"] = money(rng, 500, 70_000, allow_loss=True)
        if rng.random() < 0.4:
            vals["11"] = money(rng, 1_000, 25_000)
        if rng.random() < 0.5:
            vals["12"] = (rng.choice(["A", "B", "S"]), money(rng, 100, 15_000))
        if rng.random() < 0.3:
            vals["13"] = (rng.choice(["G", "P"]), money(rng, 100, 5_000))
        vals["16"] = ("D", money(rng, 1_000, 400_000))
        vals["17"] = ("V", money(rng, 1_000, 600_000))
    else:
        vals["1"] = money(rng, 10, 30_000)
        vals["2a"] = money(rng, 100, 80_000)
        vals["2b"] = rng.randint(0, vals["2a"])
        if rng.random() < 0.5:
            vals["3"] = money(rng, 100, 25_000)
        vals["4a"] = money(rng, 100, 150_000)
        if rng.random() < 0.3:
            vals["5"] = money(rng, 100, 12_000)
        if rng.random() < 0.3:
            vals["6"] = money(rng, 500, 60_000)
        if rng.random() < 0.3:
            vals["7"] = money(rng, 500, 40_000, allow_loss=True)
        if rng.random() < 0.4:
            vals["9"] = (rng.choice(["A", "B"]), money(rng, 100, 10_000))
        if rng.random() < 0.3:
            vals["11"] = (rng.choice(["A", "C", "D"]), money(rng, 100, 30_000))
        if rng.random() < 0.3:
            vals["13"] = (rng.choice(["A", "B"]), money(rng, 50, 2_000))
        vals["14"] = (rng.choice(["A", "I"]), money(rng, 100, 50_000))
    return vals


def make_header(rng, form):
    entity = f"{rng.choice(ENTITY_WORDS)} {rng.choice(ENTITY_WORDS)} {rng.choice(ENTITY_KINDS[form])}"
    person = rng.choice(PEOPLE)
    return {
        # 00- is not an EIN prefix the IRS assigns, so these cannot be real.
        "payer_ein": f"00-{rng.randint(1000000, 9999999)}",
        "payer_name": entity,
        "payer_address": f"{rng.randint(10, 999)} {rng.choice(STREETS)}, Anytown, NY 10000",
        "recipient_tin": f"XXX-XX-{rng.randint(1000, 9999)}",
        "recipient_name": person,
        "recipient_address": f"{rng.randint(10, 999)} {rng.choice(STREETS)}, Sampleville, CA 90000",
    }


def field_rects(pdf_path):
    rects = {}
    for annot in PdfReader(pdf_path).pages[0].get("/Annots", []):
        a = annot.get_object()
        if a.get("/Subtype") != "/Widget":
            continue
        t = a.get("/T") or a["/Parent"].get_object().get("/T")
        rects.setdefault(str(t).replace("[0]", ""), [float(x) for x in a["/Rect"]])
    return rects


def flatten_k1(form, header, vals):
    """Print values onto the blank form the way tax software does, and drop the form fields."""
    blank = FORMS / FORM_FILES[form]
    rects = field_rects(blank)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Courier-Bold", 9.5)

    def right(field, text):
        x0, y0, x1, y1 = rects[field]
        c.drawRightString(x1 - 3, y0 + 3, text)

    def left_lines(field, lines):
        x0, y0, x1, y1 = rects[field]
        for i, line in enumerate(lines):
            c.drawString(x0 + 3, y1 - 10 - i * 11, line)

    h = HEADER[form]
    x0, y0, x1, y1 = rects[h["payer_ein"]]
    c.drawCentredString((x0 + x1) / 2, y0 + 3, header["payer_ein"])
    left_lines(h["payer_name"], [header["payer_name"], header["payer_address"]])
    x0, y0, x1, y1 = rects[h["recipient_tin"]]
    c.drawCentredString((x0 + x1) / 2, y0 + 3, header["recipient_tin"])
    left_lines(h["recipient_name"], [header["recipient_name"], header["recipient_address"]])

    for box, (amt_field, code_field, _label) in BOXES[form].items():
        if box not in vals:
            continue
        v = vals[box]
        if code_field:
            code, amount = v
            x0, y0, x1, y1 = rects[code_field]
            c.drawCentredString((x0 + x1) / 2, rects[amt_field][1] + 3, code)
            right(amt_field, fmt(amount))
        else:
            right(amt_field, fmt(v))
    c.save()
    overlay = PdfReader(buf).pages[0]

    reader = PdfReader(blank)
    writer = PdfWriter()
    page = reader.pages[0]
    if "/Annots" in page:
        del page["/Annots"]
    page.merge_page(overlay)
    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def make_brokerage(rng):
    """A made-up consolidated 1099 in the style brokerages send: DIV, INT, B summary, B detail."""
    person = rng.choice(PEOPLE)
    div = {"1a": rng.randint(500_00, 90_000_00) / 100}
    div["1b"] = round(div["1a"] * rng.uniform(0.4, 0.95), 2)
    div["2a"] = rng.randint(0, 12_000_00) / 100
    div["3"] = rng.randint(0, 2_000_00) / 100
    div["5"] = rng.randint(0, 3_000_00) / 100
    div["7"] = rng.randint(0, 900_00) / 100
    intr = {"1": rng.randint(10_00, 20_000_00) / 100, "3": rng.randint(0, 8_000_00) / 100,
            "4": 0.0, "8": rng.randint(0, 5_000_00) / 100}

    names = ["XYZ Index Fund", "Sample Corp", "Example Bond ETF", "Placeholder Inc", "Demo Holdings",
             "Fictional Energy", "Madeup Software", "Testcase Bank"]
    trades = []
    for _ in range(rng.randint(6, 10)):
        term = rng.choice(["A", "D"])  # A: short-term covered, D: long-term covered
        proceeds = rng.randint(1_000_00, 60_000_00) / 100
        cost = round(proceeds * rng.uniform(0.6, 1.3), 2)
        wash = round(max(0.0, cost - proceeds) * rng.choice([0, 0, 0, 0.5]), 2)
        trades.append({"term": term, "desc": f"{rng.randint(5, 900)} SH {rng.choice(names).upper()}",
                       "proceeds": proceeds, "cost": cost, "wash": wash,
                       "gain": round(proceeds - cost + wash, 2)})
    summary = {}
    for term in ["A", "D"]:
        rows = [t for t in trades if t["term"] == term]
        summary[term] = {k: round(sum(t[k] for t in rows), 2) for k in ["proceeds", "cost", "wash", "gain"]}

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    W, H = letter
    acct = f"XXXX-{rng.randint(1000, 9999)}"

    def head(title):
        c.setFont("Helvetica-Bold", 13)
        c.drawString(40, H - 50, "SAMPLE SECURITIES LLC")
        c.setFont("Helvetica", 9)
        c.drawString(40, H - 64, "100 Example Plaza, Anytown, NY 10000   (made-up broker for a demo)")
        c.drawRightString(W - 40, H - 50, "2025 Consolidated Form 1099")
        c.drawRightString(W - 40, H - 64, f"Account {acct}")
        c.drawString(40, H - 90, f"Recipient: {person}")
        c.drawString(40, H - 102, "Recipient TIN: XXX-XX-" + str(rng.randint(1000, 9999)))
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, H - 130, title)
        c.line(40, H - 135, W - 40, H - 135)

    def row(y, label, amount):
        c.setFont("Helvetica", 9.5)
        c.drawString(50, y, label)
        dots = "." * 60
        c.drawString(300, y, dots)
        c.setFont("Courier-Bold", 10)
        c.drawRightString(W - 50, y, f"{amount:,.2f}")

    head("Form 1099-DIV  Dividends and Distributions")
    y = H - 155
    for k, label in [("1a", "1a Total ordinary dividends"), ("1b", "1b Qualified dividends"),
                     ("2a", "2a Total capital gain distributions"), ("3", "3 Nondividend distributions"),
                     ("5", "5 Section 199A dividends"), ("7", "7 Foreign tax paid")]:
        row(y, label, div[k])
        y -= 18
    y -= 20
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Form 1099-INT  Interest Income")
    c.line(40, y - 5, W - 40, y - 5)
    y -= 25
    for k, label in [("1", "1 Interest income"), ("3", "3 Interest on U.S. Treasury obligations"),
                     ("4", "4 Federal income tax withheld"), ("8", "8 Tax-exempt interest")]:
        row(y, label, intr[k])
        y -= 18
    y -= 20
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Summary of Proceeds, Gains and Losses (Form 1099-B)")
    c.line(40, y - 5, W - 40, y - 5)
    y -= 22
    c.setFont("Helvetica-Bold", 8.5)
    cols = [320, 410, 490, W - 50]
    for x, t in zip(cols, ["Proceeds", "Cost basis", "Wash sale", "Gain or loss"]):
        c.drawRightString(x, y, t)
    y -= 16
    for term, label in [("A", "Short-term, basis reported (Box A)"), ("D", "Long-term, basis reported (Box D)")]:
        s = summary[term]
        c.setFont("Helvetica", 9.5)
        c.drawString(50, y, label)
        c.setFont("Courier-Bold", 10)
        for x, k in zip(cols, ["proceeds", "cost", "wash", "gain"]):
            c.drawRightString(x, y, f"{s[k]:,.2f}" if s[k] >= 0 else f"({abs(s[k]):,.2f})")
        y -= 18
    c.showPage()

    head("Form 1099-B  Proceeds From Broker Transactions (detail)")
    y = H - 160
    c.setFont("Helvetica-Bold", 8.5)
    dcols = [330, 400, 470, W - 50]
    c.drawString(50, y, "Term  Description")
    for x, t in zip(dcols, ["Proceeds", "Cost basis", "Wash sale", "Gain or loss"]):
        c.drawRightString(x, y, t)
    y -= 16
    for t in sorted(trades, key=lambda t: t["term"]):
        c.setFont("Helvetica", 9)
        c.drawString(50, y, f"{t['term']}     {t['desc']}")
        c.setFont("Courier", 9.5)
        for x, k in zip(dcols, ["proceeds", "cost", "wash", "gain"]):
            c.drawRightString(x, y, f"{t[k]:,.2f}" if t[k] >= 0 else f"({abs(t[k]):,.2f})")
        y -= 15
    c.showPage()
    c.save()

    truth = {f"DIV {k}": v for k, v in div.items()}
    truth.update({f"INT {k}": v for k, v in intr.items()})
    for term in ["A", "D"]:
        for k in ["proceeds", "cost", "wash", "gain"]:
            truth[f"B {term} {k}"] = summary[term][k]
    header = {"payer_name": "SAMPLE SECURITIES LLC", "recipient_name": person}
    return buf.getvalue(), truth, header


def degrade(img, rng, level):
    """Make a page look scanned. level 0 = clean print, 1 = office scan, 2 = bad fax/phone photo."""
    if level == 0:
        return img
    angle = rng.uniform(0.3, 0.9) * rng.choice([-1, 1]) if level == 1 else rng.uniform(1.0, 1.8) * rng.choice([-1, 1])
    img = img.convert("L").rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
    scale = 0.75 if level == 1 else 0.5
    small = img.resize((int(img.width * scale), int(img.height * scale)), Image.BILINEAR)
    img = small.resize(img.size, Image.BILINEAR)
    arr = np.asarray(img).astype(np.float32)
    nprng = np.random.default_rng(rng.randint(0, 2**31))
    arr += nprng.normal(0, 10 if level == 1 else 22, arr.shape)
    if level == 2:
        arr = arr * 0.85 + 30  # grey, low-contrast background
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.6 if level == 1 else 1.1))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=55 if level == 1 else 30)
    return Image.open(out)


def image_pdf(images, dpi):
    out = io.BytesIO()
    images[0].convert("RGB").save(out, "PDF", resolution=dpi, save_all=True,
                                  append_images=[i.convert("RGB") for i in images[1:]])
    return out.getvalue()


def to_scan(pdf_bytes, rng, level, dpi=200):
    doc = pdfium.PdfDocument(pdf_bytes)
    pages = [degrade(p.render(scale=dpi / 72).to_pil(), rng, level) for p in doc]
    return image_pdf(pages, dpi)


def main():
    SAMPLES.mkdir(exist_ok=True)
    for old in SAMPLES.glob("*-madeup-*.pdf"):
        old.unlink()
    # (form, scan level) for each sample document. Level 0 is a clean print run through
    # a scanner at 200 dpi; 1 is an ordinary office scan; 2 is a bad fax or phone photo.
    plan = [("1120S", 0), ("1120S", 1), ("1120S", 2),
            ("1041", 0), ("1041", 1), ("1041", 2),
            ("BROKER", 0), ("BROKER", 1), ("BROKER", 2)]
    # Documents 10-18 were used while tuning the extractor; 20-28 come from a different
    # seed and were held out, so their results show how it does on documents it wasn't tuned on.
    key = {}
    for start, seed in ((10, SEED), (20, SEED + 1)):
        rng = random.Random(seed)
        make_set(plan, start, rng, key)
    (HERE / "answer_key.json").write_text(json.dumps(key, indent=1))
    print(f"generated {len(key)} made-up documents in {SAMPLES.relative_to(HERE)}/")


def make_set(plan, start, rng, key):
    for i, (form, level) in enumerate(plan, start):
        if form == "BROKER":
            pdf, truth, header = make_brokerage(rng)
            name = f"{i:02d}-madeup-brokerage-1099.pdf"
        else:
            header = make_header(rng, form)
            vals = make_k1_values(rng, form)
            pdf = flatten_k1(form, header, vals)
            # Plain boxes are keyed by box number (None when blank). Coded boxes are keyed
            # by box and code, like "20 Z", and only appear when the K-1 carries them.
            truth = {}
            for box, (_f, code_field, _l) in BOXES[form].items():
                v = vals.get(box)
                if code_field:
                    if v is not None:
                        truth[f"{box} {v[0]}"] = v[1]
                else:
                    truth[box] = v
            name = f"{i:02d}-madeup-k1-{form.lower()}.pdf"
        (SAMPLES / name).write_bytes(to_scan(pdf, rng, level))
        key[name] = {"form": form, "scan_level": level,
                     "header": {k: v for k, v in header.items() if k in ("payer_name", "payer_ein", "recipient_name")},
                     "fields": truth}


if __name__ == "__main__":
    main()
