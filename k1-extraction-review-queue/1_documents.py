import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import hashlib
    import io
    import json
    import os
    import random
    import urllib.request
    from pathlib import Path
    from typing import Any

    import marimo as mo
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("K1_OUTPUT_DIR", HERE / "output"))
    SAMPLES = OUT / "samples"
    FORMS = OUT / "forms"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # K-1 extraction with a review queue

    **The question.** Can we show a tax preparer what our extraction would give them, on real sample documents,
    without them sending us any? The demo reads Schedule K-1s and brokerage 1099s, links every value to the box it
    came from, and sends anything it isn't sure of to a review queue. The number that matters is the **wrong value
    that gets accepted without review**, because a preparer never sees it.

    We compare five vision-language models (three open-weight) and two OCR models run on Modal's GPUs, on the same
    documents and answer keys. Each runs on its own, and two run as a pair that must agree.

    The demo is three notebooks, which hand their results on through files in `output/`:

    1. **This one** makes the 30 documents and their answer keys.
    2. **`2_extraction.py`** reads every document with every model and applies the review rules.
    3. **`3_results.py`** scores every run against the answer keys, shows the results and what didn't work, and
       builds the review screens.

    `./run.sh` runs the three as scripts, in order, and every number in them comes from that run.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The documents

    **Real K-1s.** Publicly traded partnerships publish sample K-1 packages for their unitholders: the issuer's real
    K-1 and its supplemental statements, made out to a placeholder investor. We use three, from Enviva Partners (2018,
    2021) and The Blackstone Group (2019). They cover three K-1 layouts (the form changed in 2019 and 2021). They have
    losses printed as `-27,942` and `(18)`, dashes for zero, coded boxes like `20 AH*`, country codes
    (`16 A VARIOUS`), and amounts that are only on an attached statement (`* STMT`). We download them from the
    issuers' sites and check their hashes, so the hand-keyed `real_answer_key.json` matches.
    """)
    return


@app.cell
def _():
    def download_checked(path: Path, url: str, sha: str) -> None:
        """Download url to path unless path already holds the file with this sha256. Stops if the file changed."""
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
            return
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        if (got := hashlib.sha256(data).hexdigest()) != sha:
            raise RuntimeError(f"{path.name}: the file at {url} has changed (sha256 {got})")
        path.write_bytes(data)

    # fmt: off
    REAL_K1S = {  # file: (source, sha256, the K-1's page number)
        "01-enviva-2018-k1.pdf": (
            "https://www.envivabiomass.com/wp-content/uploads/2019/09/Enviva_Sample_Tax_Package_10000_units.pdf",
            "0dcf2a2eacfa37866b5688d5f28c79c02f40004dc2ae39171816e33d629d2e1a", 2),
        "02-enviva-2021-k1.pdf": (
            "https://s28.q4cdn.com/898203682/files/doc_downloads/schedule_k-1s/2022/03/EVA-2021-Sample-K-1-1-000-Units.pdf",
            "8a99f85cce2208352676a7853be8e5d43c04ee9923694cdcc3ee8d10da6274e1", 2),
        "03-blackstone-2019-k1.pdf": (
            "https://s23.q4cdn.com/714267708/files/doc_downloads/2020/03/SAMPLESCHEDULE_K1_2019.pdf",
            "60a77e0c5d6e8685f18fd34cce2d09fcb2ff1a1d7c4bff9a32ef7e8fd1580414", 3),
    }
    # fmt: on
    SAMPLES.mkdir(parents=True, exist_ok=True)
    for _name, (_url, _sha, _page) in REAL_K1S.items():
        download_checked(SAMPLES / _name, _url, _sha)
    return REAL_K1S, download_checked


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Scanned copies.** Client documents often arrive as scans, so each real K-1 page is also printed and "scanned":
    rotated, downsampled, given noise and blur, and saved as a JPEG. Level 1 is an ordinary office scan, level 2 a
    fax or phone photo. The `a` scans were used while building the review rules. The `b` scans come from a different
    seed and were held out.
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

    def image_pdf(images: list[Image.Image], dpi: int = 200) -> bytes:
        out, rgb = io.BytesIO(), [i.convert("RGB") for i in images]
        rgb[0].save(out, "PDF", resolution=dpi, save_all=True, append_images=rgb[1:])
        return out.getvalue()

    return degrade, image_pdf


@app.cell
def _(REAL_K1S, degrade, image_pdf):
    # fmt: off
    REAL_SCANS = [("01-enviva-2018-k1.pdf", 1, "a"), ("02-enviva-2021-k1.pdf", 1, "a"),
                  ("02-enviva-2021-k1.pdf", 2, "a"), ("03-blackstone-2019-k1.pdf", 1, "a"),
                  ("01-enviva-2018-k1.pdf", 1, "b"), ("01-enviva-2018-k1.pdf", 2, "b"),
                  ("02-enviva-2021-k1.pdf", 1, "b"), ("03-blackstone-2019-k1.pdf", 1, "b"),
                  ("03-blackstone-2019-k1.pdf", 2, "b")]
    # fmt: on
    _rngs = {"a": random.Random(1065), "b": random.Random(1066)}
    scanned_copies = []
    for _src, _level, _set in REAL_SCANS:
        _page = pdfium.PdfDocument(SAMPLES / _src)[REAL_K1S[_src][2] - 1]
        _img = degrade(_page.render(scale=200 / 72).to_pil(), _rngs[_set], _level)
        scanned_copies.append(SAMPLES / _src.replace(".pdf", f"-scan{_level}{_set}.pdf"))
        scanned_copies[-1].write_bytes(image_pdf([_img]))
    return (scanned_copies,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Made-up K-1s and 1099s.** Real 1120-S and 1041 K-1s and real brokerage 1099s aren't published anywhere we can
    use, so we make them. We fill the blank 2025 IRS forms (downloaded from irs.gov's prior-year archive and
    hash-checked) with invented names and amounts. We also draw a made-up broker's consolidated 1099 with DIV, INT and
    1099-B summary and detail pages. EINs start with `00-`, a prefix the IRS doesn't assign. Every made-up document is
    image-only: a clean scan, an office scan or a bad scan. Documents `10` to `18` were used while building the rules.
    Documents `20` to `28` use a different seed and were held out.
    """)
    return


@app.cell
def _(download_checked):
    BLANK_FORMS = {
        "1120S": ("f1120ssk--2025.pdf", "104ac7b1137cb78c9051d4e3424630dca233887f17928b311fef6fd578baacd0"),
        "1041": ("f1041sk1--2025.pdf", "d8d7b6eacabdf145474aee8385fcfeafe68bd2f69baaef52d9a8227ebcd45fc3"),
    }
    FORMS.mkdir(parents=True, exist_ok=True)
    for _name, _sha in BLANK_FORMS.values():
        download_checked(FORMS / _name, "https://www.irs.gov/pub/irs-prior/" + _name, _sha)

    # fmt: off
    # Each box: the PDF form field its amount is printed in, and the field for its code letter in a coded box.
    PDF_FIELDS = {
        "1120S": {"1": ("f1_21", None), "2": ("f1_22", None), "3": ("f1_23", None), "4": ("f1_24", None),
                  "5a": ("f1_25", None), "5b": ("f1_26", None), "6": ("f1_27", None), "7": ("f1_28", None),
                  "8a": ("f1_29", None), "9": ("f1_32", None), "11": ("f1_43", None), "12": ("f1_45", "f1_44"),
                  "13": ("f1_61", "f1_60"), "16": ("f1_81", "f1_80"), "17": ("f1_91", "f1_90")},
        "1041": {"1": ("f1_12", None), "2a": ("f1_13", None), "2b": ("f1_14", None), "3": ("f1_15", None),
                 "4a": ("f1_16", None), "5": ("f1_19", None), "6": ("f1_20", None), "7": ("f1_21", None),
                 "8": ("f1_22", None), "9": ("f1_24", "f1_23"), "10": ("f1_29", None), "11": ("f1_31", "f1_30"),
                 "13": ("f1_51", "f1_50"), "14": ("f1_57", "f1_56")},
    }
    HEADER_FIELDS = {"1120S": ("f1_06", "f1_07", "f1_11", "f1_12"), "1041": ("f1_6", "f1_7", "f1_10", "f1_11")}
    # Which boxes carry an amount: (box, chance it's filled, low, high, can be a loss, code letters to pick from).
    RECIPES = {
        "1120S": [("1", 1, 1_000, 650_000, True, ""), ("2", 0.4, 500, 60_000, True, ""),
                  ("4", 1, 10, 15_000, False, ""), ("5a", 1, 100, 40_000, False, ""), ("5b", 1, 0, 0, False, ""),
                  ("6", 0.3, 100, 9_000, False, ""), ("7", 0.5, 100, 30_000, True, ""),
                  ("8a", 1, 100, 120_000, True, ""), ("9", 0.4, 500, 70_000, True, ""),
                  ("11", 0.4, 1_000, 25_000, False, ""), ("12", 0.5, 100, 15_000, False, "ABS"),
                  ("13", 0.3, 100, 5_000, False, "GP"), ("16", 1, 1_000, 400_000, False, "D"),
                  ("17", 1, 1_000, 600_000, False, "V")],
        "1041": [("1", 1, 10, 30_000, False, ""), ("2a", 1, 100, 80_000, False, ""), ("2b", 1, 0, 0, False, ""),
                 ("3", 0.5, 100, 25_000, False, ""), ("4a", 1, 100, 150_000, False, ""),
                 ("5", 0.3, 100, 12_000, False, ""), ("6", 0.3, 500, 60_000, False, ""),
                 ("7", 0.3, 500, 40_000, True, ""), ("9", 0.4, 100, 10_000, False, "AB"),
                 ("11", 0.3, 100, 30_000, False, "ACD"), ("13", 0.3, 50, 2_000, False, "AB"),
                 ("14", 1, 100, 50_000, False, "AI")],
    }
    QUALIFIED_OF = {"5b": "5a", "2b": "2a"}  # qualified dividends are a part of ordinary dividends
    WORDS = ["Harbor", "Juniper", "Granite", "Meridian", "Alder", "Kestrel", "Sable", "Copper", "Lantern", "Willow",
             "Basalt", "Heron", "Quarry", "Tamarack", "Orchard", "Beacon"]
    KINDS = {"1120S": ["Services Inc", "Builders Inc", "Logistics Inc"],
             "1041": ["Family Trust", "Residuary Trust", "Estate"]}
    PEOPLE = ["Avery Sample", "Jordan Example", "Riley Placeholder", "Morgan Testcase", "Casey Specimen",
              "Taylor Fictional", "Quinn Madeup", "Drew Notreal"]
    STREETS = ["Example St", "Sample Ave", "Placeholder Rd", "Demo Blvd", "Testing Ln"]
    # fmt: on
    return BLANK_FORMS, HEADER_FIELDS, KINDS, PDF_FIELDS, PEOPLE, QUALIFIED_OF, RECIPES, STREETS, WORDS


@app.cell
def _(BLANK_FORMS, HEADER_FIELDS, KINDS, PDF_FIELDS, PEOPLE, QUALIFIED_OF, RECIPES, STREETS, WORDS):
    def k1_values(rng: random.Random, form: str) -> dict[str, Any]:
        """Pick which boxes carry amounts on this K-1, and what they are."""
        values: dict[str, Any] = {}
        for box, chance, low, high, loss, codes in RECIPES[form]:
            if chance < 1 and rng.random() >= chance:
                continue
            code = rng.choice(codes) if len(codes) > 1 else codes
            if box in QUALIFIED_OF:
                amount = rng.randint(0, values[QUALIFIED_OF[box]])
            else:
                amount = rng.randint(low, high)
                amount = -amount if loss and rng.random() < 0.3 else amount
            values[box] = (code, amount) if code else amount
        return values

    def k1_header(rng: random.Random, form: str) -> list[str]:
        """Payer EIN, payer name and address, recipient TIN, recipient name and address."""
        entity = f"{rng.choice(WORDS)} {rng.choice(WORDS)} {rng.choice(KINDS[form])}"
        person = rng.choice(PEOPLE)
        return [
            f"00-{rng.randint(1000000, 9999999)}",
            entity,
            f"{rng.randint(10, 999)} {rng.choice(STREETS)}, Anytown, NY 10000",
            f"XXX-XX-{rng.randint(1000, 9999)}",
            person,
            f"{rng.randint(10, 999)} {rng.choice(STREETS)}, Sampleville, CA 90000",
        ]

    def print_k1(form: str, header: list[str], values: dict[str, Any]) -> bytes:
        """Print the values onto the blank form the way tax software does, and drop the form fields."""
        blank = FORMS / BLANK_FORMS[form][0]
        rects: dict[str, list[float]] = {}
        for annot in PdfReader(blank).pages[0].get("/Annots", []):
            if (a := annot.get_object()).get("/Subtype") == "/Widget":
                name = a.get("/T") or a["/Parent"].get_object().get("/T")
                rects.setdefault(str(name).replace("[0]", ""), [float(x) for x in a["/Rect"]])
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        c.setFont("Courier-Bold", 9.5)
        payer_ein, payer, recipient_tin, recipient = HEADER_FIELDS[form]
        for id_field, id_text, name_field, lines in (
            (payer_ein, header[0], payer, header[1:3]),
            (recipient_tin, header[3], recipient, header[4:6]),
        ):
            x0, y0, x1, _ = rects[id_field]
            c.drawCentredString((x0 + x1) / 2, y0 + 3, id_text)
            for i, line in enumerate(lines):
                c.drawString(rects[name_field][0] + 3, rects[name_field][3] - 10 - i * 11, line)
        for box, (amount_field, code_field) in PDF_FIELDS[form].items():
            if box not in values:
                continue
            code, amount = values[box] if code_field else ("", values[box])
            if code_field:
                c.drawCentredString((rects[code_field][0] + rects[code_field][2]) / 2, rects[amount_field][1] + 3, code)
            text = f"({abs(amount):,})" if amount < 0 else f"{amount:,}"
            c.drawRightString(rects[amount_field][2] - 3, rects[amount_field][1] + 3, text)
        c.save()
        page = PdfReader(blank).pages[0]
        if "/Annots" in page:
            del page["/Annots"]
        page.merge_page(PdfReader(buf).pages[0])
        writer, out = PdfWriter(), io.BytesIO()
        writer.add_page(page)
        writer.write(out)
        return out.getvalue()

    return k1_header, k1_values, print_k1


@app.cell
def _(PEOPLE):
    def print_brokerage(rng: random.Random) -> tuple[bytes, dict[str, float]]:
        """A made-up consolidated 1099 in the style brokerages send: DIV, INT, a 1099-B summary, and the B detail."""
        person = rng.choice(PEOPLE)
        div = {"1a": rng.randint(500_00, 90_000_00) / 100}
        div["1b"] = round(div["1a"] * rng.uniform(0.4, 0.95), 2)
        for k, high in (("2a", 12_000_00), ("3", 2_000_00), ("5", 3_000_00), ("7", 900_00)):
            div[k] = rng.randint(0, high) / 100
        intr = {"1": rng.randint(10_00, 20_000_00) / 100, "3": rng.randint(0, 8_000_00) / 100}
        intr |= {"4": 0.0, "8": rng.randint(0, 5_000_00) / 100}
        names = [
            "XYZ Index Fund",
            "Sample Corp",
            "Example Bond ETF",
            "Placeholder Inc",
            "Demo Holdings",
            "Fictional Energy",
            "Madeup Software",
            "Testcase Bank",
        ]
        trades: list[dict[str, Any]] = []
        for _ in range(rng.randint(6, 10)):
            term = rng.choice(["A", "D"])  # A: short-term covered, D: long-term covered
            proceeds = rng.randint(1_000_00, 60_000_00) / 100
            cost = round(proceeds * rng.uniform(0.6, 1.3), 2)
            wash = round(max(0.0, cost - proceeds) * rng.choice([0, 0, 0, 0.5]), 2)
            desc = f"{rng.randint(5, 900)} SH {rng.choice(names).upper()}"
            trades.append(
                {
                    "term": term,
                    "desc": desc,
                    "proceeds": proceeds,
                    "cost": cost,
                    "wash": wash,
                    "gain": round(proceeds - cost + wash, 2),
                }
            )
        cols = ["proceeds", "cost", "wash", "gain"]
        summary = {t: {k: round(sum(x[k] for x in trades if x["term"] == t), 2) for k in cols} for t in "AD"}
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        W, H = letter
        account = f"XXXX-{rng.randint(1000, 9999)}"

        def section(y: float, title: str) -> None:
            c.setFont("Helvetica-Bold", 11)
            c.drawString(40, y, title)
            c.line(40, y - 5, W - 40, y - 5)

        def heading(title: str) -> None:
            c.setFont("Helvetica-Bold", 13)
            c.drawString(40, H - 50, "SAMPLE SECURITIES LLC")
            c.setFont("Helvetica", 9)
            c.drawString(40, H - 64, "100 Example Plaza, Anytown, NY 10000   (made-up broker for a demo)")
            c.drawRightString(W - 40, H - 50, "2025 Consolidated Form 1099")
            c.drawRightString(W - 40, H - 64, f"Account {account}")
            c.drawString(40, H - 90, f"Recipient: {person}")
            c.drawString(40, H - 102, "Recipient TIN: XXX-XX-" + str(rng.randint(1000, 9999)))
            section(H - 130, title)

        def line_items(y: float, items: list[tuple[str, float]]) -> float:
            for label, amount in items:
                c.setFont("Helvetica", 9.5)
                c.drawString(50, y, label)
                c.drawString(300, y, "." * 60)
                c.setFont("Courier-Bold", 10)
                c.drawRightString(W - 50, y, f"{amount:,.2f}")
                y -= 18
            return y

        def amounts_table(y: float, xs: list[float], rows: list[tuple[str, dict[str, Any]]], fonts: tuple) -> None:
            c.setFont("Helvetica-Bold", 8.5)
            for x, title in zip(xs, ["Proceeds", "Cost basis", "Wash sale", "Gain or loss"], strict=True):
                c.drawRightString(x, y, title)
            y -= 16
            for label, row in rows:
                c.setFont(*fonts[0])
                c.drawString(50, y, label)
                c.setFont(*fonts[1])
                for x, k in zip(xs, cols, strict=True):
                    c.drawRightString(x, y, f"{row[k]:,.2f}" if row[k] >= 0 else f"({abs(row[k]):,.2f})")
                y -= fonts[2]

        heading("Form 1099-DIV  Dividends and Distributions")
        labels = [
            "1a Total ordinary dividends",
            "1b Qualified dividends",
            "2a Total capital gain distributions",
            "3 Nondividend distributions",
            "5 Section 199A dividends",
            "7 Foreign tax paid",
        ]
        y = line_items(H - 155, list(zip(labels, div.values(), strict=True))) - 20
        section(y, "Form 1099-INT  Interest Income")
        labels = [
            "1 Interest income",
            "3 Interest on U.S. Treasury obligations",
            "4 Federal income tax withheld",
            "8 Tax-exempt interest",
        ]
        y = line_items(y - 25, list(zip(labels, intr.values(), strict=True))) - 20
        section(y, "Summary of Proceeds, Gains and Losses (Form 1099-B)")
        rows = [
            ("Short-term, basis reported (Box A)", summary["A"]),
            ("Long-term, basis reported (Box D)", summary["D"]),
        ]
        amounts_table(y - 22, [320, 410, 490, W - 50], rows, (("Helvetica", 9.5), ("Courier-Bold", 10), 18))
        c.showPage()
        heading("Form 1099-B  Proceeds From Broker Transactions (detail)")
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(50, H - 160, "Term  Description")
        rows = [(f"{t['term']}     {t['desc']}", t) for t in sorted(trades, key=lambda t: t["term"])]
        amounts_table(H - 160, [330, 400, 470, W - 50], rows, (("Helvetica", 9), ("Courier", 9.5), 15))
        c.showPage()
        c.save()
        truth = {f"DIV {k}": v for k, v in div.items()} | {f"INT {k}": v for k, v in intr.items()}
        return buf.getvalue(), truth | {f"B {t} {k}": summary[t][k] for t in "AD" for k in cols}

    return (print_brokerage,)


@app.cell
def _(PDF_FIELDS, REAL_K1S, degrade, image_pdf, k1_header, k1_values, print_brokerage, print_k1, scanned_copies):
    # (form, scan level) of each made-up document: 0 is a clean print through a scanner, 1 an office scan, 2 a bad scan.
    _plan = [("1120S", 0), ("1120S", 1), ("1120S", 2), ("1041", 0), ("1041", 1), ("1041", 2)]
    _plan += [("BROKER", 0), ("BROKER", 1), ("BROKER", 2)]
    made_up_key: dict[str, Any] = {}
    for _start, _seed in ((10, 2025), (20, 2026)):
        _rng = random.Random(_seed)
        for _i, (_form, _level) in enumerate(_plan, _start):
            if _form == "BROKER":
                _pdf, _truth = print_brokerage(_rng)
                _name, _header = f"{_i:02d}-madeup-brokerage-1099.pdf", {"payer_name": "SAMPLE SECURITIES LLC"}
            else:
                _head = k1_header(_rng, _form)
                _values = k1_values(_rng, _form)
                _pdf = print_k1(_form, _head, _values)
                # Plain boxes are keyed by box number (None when blank); coded rows by box and code, like "13 G".
                _truth = {}
                for _box, (_f, _code_field) in PDF_FIELDS[_form].items():
                    if not _code_field:
                        _truth[_box] = _values.get(_box)
                    elif _box in _values:
                        _truth[f"{_box} {_values[_box][0]}"] = _values[_box][1]
                _name, _header = (
                    f"{_i:02d}-madeup-k1-{_form.lower()}.pdf",
                    {"payer_ein": _head[0], "payer_name": _head[1]},
                )
            _pages = [degrade(p.render(scale=200 / 72).to_pil(), _rng, _level) for p in pdfium.PdfDocument(_pdf)]
            (SAMPLES / _name).write_bytes(image_pdf(_pages))
            made_up_key[_name] = {"form": _form, "scan_level": _level, "header": _header, "fields": _truth}
    (OUT / "answer_key.json").write_text(json.dumps(made_up_key, indent=1))
    FILES = sorted([SAMPLES / n for n in REAL_K1S] + scanned_copies + [SAMPLES / n for n in made_up_key])
    print(f"{len(FILES)} documents in {SAMPLES}")
    return FILES, made_up_key


if __name__ == "__main__":
    app.run()
