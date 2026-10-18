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
    import re
    import time
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from typing import Any, Literal

    import marimo as mo
    import modal
    import numpy as np
    import pdfplumber
    import pypdfium2 as pdfium
    from docling.datamodel import vlm_model_specs
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions, VlmPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.pipeline.vlm_pipeline import VlmPipeline
    from PIL import Image, ImageFilter
    from playwright.async_api import async_playwright
    from pydantic import AnyUrl, BaseModel, Field, TypeAdapter, create_model
    from pydantic_ai import Agent, BinaryContent, capture_run_messages
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models import infer_model
    from pydantic_ai.models.openrouter import OpenRouterModelSettings
    from pydantic_ai.settings import ModelSettings
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    import ocr_modal

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("K1_OUTPUT_DIR", HERE / "output"))
    SAMPLES, FORMS = OUT / "samples", OUT / "forms"
    Fields = list[dict[str, Any]]


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

    `./run.sh` runs this notebook as a script, and every number below comes from that run.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. The documents

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


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. Docling reads every page once

    Docling runs on CPU, with Tesseract for scanned pages, and gives us each page's text and a Markdown version with
    tables. We use it three ways. It finds the K-1 page or the 1099 summary page. It finds the supplemental statement
    pages and their Box / Description / Amount tables. And it counts the amounts printed on a page, which is an
    independent check on how many values a model should have read. The layout is saved under `output/layout/`, so it
    runs once.
    """)
    return


@app.cell
def _(FILES):
    def read_layout(converter: DocumentConverter, path: Path) -> dict[str, Any]:
        t0 = time.time()
        result = converter.convert(path)
        pages = []
        for page in result.pages:
            assert page.parsed_page is not None and page.size is not None, f"{path.name}: Docling parsed no page"
            cells = page.parsed_page.word_cells or page.parsed_page.textline_cells
            words = [(word, cell.from_ocr) for cell in cells for word in cell.text.split()]
            markdown = result.document.export_to_markdown(page_no=page.page_no)
            pages.append(
                {
                    "index": page.page_no - 1,
                    "width": page.size.width,
                    "height": page.size.height,
                    "ocr": any(ocr for _w, ocr in words),
                    "text": " ".join(w for w, _ocr in words),
                    "markdown": markdown,
                }
            )
        return {"file": path.name, "seconds": round(time.time() - t0, 1), "pages": pages}

    _options = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=TesseractCliOcrOptions(lang=["eng"]),
        do_table_structure=True,
        generate_parsed_pages=True,
    )
    _converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=_options)})
    (OUT / "layout").mkdir(exist_ok=True)
    layouts: dict[str, dict[str, Any]] = {}
    for _path in FILES:
        _saved = OUT / "layout" / f"{_path.stem}.json"
        if not _saved.exists():
            _saved.write_text(json.dumps(read_layout(_converter, _path)))
        layouts[_path.name] = json.loads(_saved.read_text())
    print(f"Docling: {sum(d['seconds'] for d in layouts.values()) / len(layouts):.1f} s per document")
    return (layouts,)


@app.cell
def _(FILES):
    # Every page is rendered once, before any model runs, so rendering doesn't hold up the model calls and their
    # timings: the 200-dpi image a model sees, and the 150-dpi image the review screen shows.
    (OUT / "pages").mkdir(exist_ok=True)
    for _path in FILES:
        for _i, _page in enumerate(pdfium.PdfDocument(_path)):
            _png = OUT / "pages" / f"{_path.stem}-p{_i + 1}.png"
            if not _png.exists():
                _page.render(scale=200 / 72).to_pil().convert("RGB").save(_png)
                _page.render(scale=150 / 72).to_pil().convert("L").save(_png.with_suffix(".jpg"), quality=72)

    def page_png(path: Path, index: int) -> bytes:
        return (OUT / "pages" / f"{path.stem}-p{index + 1}.png").read_bytes()

    def page_image(path: Path, index: int) -> str:
        """Where the review screen in a run's folder finds the page."""
        return f"../pages/{path.stem}-p{index + 1}.jpg"

    return page_image, page_png


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. What each model is asked for

    The K-1 page (or the 1099 summary page) goes to the model as an image at 200 dpi. Pydantic AI asks for a typed
    result: one Pydantic model per form, where every value carries what was printed, its bounding box and the model's
    own confidence. The boxes each form has, and their printed labels, are below; the labels go into the prompt. In a
    coded box the code letter is a required field: when it was optional, GLM and Qwen 3.8 27B left it out of every row.
    """)
    return


@app.cell
def _():
    # fmt: off
    # Part III of Schedule K-1 (Form 1065). "coded" boxes hold rows of a code letter and an amount.
    K1_1065 = {
        "1": ("Ordinary business income (loss)", "amount"), "2": ("Net rental real estate income (loss)", "amount"),
        "3": ("Other net rental income (loss)", "amount"), "4a": ("Guaranteed payments for services", "amount"),
        "4b": ("Guaranteed payments for capital", "amount"), "4c": ("Total guaranteed payments", "amount"),
        "5": ("Interest income", "amount"), "6a": ("Ordinary dividends", "amount"),
        "6b": ("Qualified dividends", "amount"), "6c": ("Dividend equivalents", "amount"), "7": ("Royalties", "amount"),
        "8": ("Net short-term capital gain (loss)", "amount"), "9a": ("Net long-term capital gain (loss)", "amount"),
        "9b": ("Collectibles (28%) gain (loss)", "amount"), "9c": ("Unrecaptured section 1250 gain", "amount"),
        "10": ("Net section 1231 gain (loss)", "amount"), "11": ("Other income (loss)", "coded"),
        "12": ("Section 179 deduction", "amount"), "13": ("Other deductions", "coded"),
        "14": ("Self-employment earnings (loss)", "coded"), "15": ("Credits", "coded"),
        "16": ("Foreign transactions", "coded"), "17": ("Alternative minimum tax (AMT) items", "coded"),
        "18": ("Tax-exempt income and", "coded"), "19": ("Distributions", "coded"),
        "20": ("Other information", "coded"), "21": ("Foreign taxes paid or accrued", "amount"),
    }
    K1_LABELS = {
        "1120S": {"1": ("Ordinary business income (loss)", "amount"),
                  "2": ("Net rental real estate income (loss)", "amount"),
                  "3": ("Other net rental income (loss)", "amount"), "4": ("Interest income", "amount"),
                  "5a": ("Ordinary dividends", "amount"), "5b": ("Qualified dividends", "amount"),
                  "6": ("Royalties", "amount"), "7": ("Net short-term capital gain (loss)", "amount"),
                  "8a": ("Net long-term capital gain (loss)", "amount"),
                  "9": ("Net section 1231 gain (loss)", "amount"), "11": ("Section 179 deduction", "amount"),
                  "12": ("Other deductions", "coded"), "13": ("Credits", "coded"),
                  "16": ("Items affecting shareholder basis", "coded"), "17": ("Other information", "coded")},
        "1041": {"1": ("Interest income", "amount"), "2a": ("Ordinary dividends", "amount"),
                 "2b": ("Qualified dividends", "amount"), "3": ("Net short-term capital gain", "amount"),
                 "4a": ("Net long-term capital gain", "amount"), "5": ("nonbusiness income", "amount"),
                 "6": ("Ordinary business income", "amount"), "7": ("Net rental real estate income", "amount"),
                 "8": ("Other rental income", "amount"), "9": ("Directly apportioned deductions", "coded"),
                 "10": ("Estate tax deduction", "amount"), "11": ("Final year deductions", "coded"),
                 "13": ("Credits and credit recapture", "coded"), "14": ("Other information", "coded")},
    }
    HEADER_LABELS = {
        "1065": ("Partnership's employer identification number",
                 "Partnership's name, address, city, state, and ZIP code"),
        "1120S": ("Corporation's employer identification number",
                  "Corporation's name, address, city, state, and ZIP code"),
        "1041": ("Estate's or trust's employer identification number", "Estate's or trust's name"),
    }
    BROKER_LINES = {"DIV 1a": "1a Total ordinary dividends", "DIV 1b": "1b Qualified dividends",
                    "DIV 2a": "2a Total capital gain distributions", "DIV 3": "3 Nondividend distributions",
                    "DIV 5": "5 Section 199A dividends", "DIV 7": "7 Foreign tax paid", "INT 1": "1 Interest income",
                    "INT 3": "3 Interest on U.S. Treasury obligations", "INT 4": "4 Federal income tax withheld",
                    "INT 8": "8 Tax-exempt interest"}
    BROKER_ROWS = {"A": "Short-term, basis reported (Box A)", "D": "Long-term, basis reported (Box D)"}
    B_COLS = ["proceeds", "cost", "wash", "gain"]
    # fmt: on

    def k1_labels(form: str, year: int) -> dict[str, tuple[str, str]]:
        """The boxes a form has. The 1065 K-1 changed: box 4 split into 4a to 4c after 2018, and in 2021 box 16
        became the Schedule K-3 checkbox and box 21 was added."""
        if form != "1065":
            return K1_LABELS[form]
        labels = dict(K1_1065)
        if year <= 2018:
            for k in ("4a", "4b", "4c"):
                del labels[k]
            labels["4"] = ("Guaranteed payments", "amount")
        del labels["21" if year <= 2020 else "16"]
        return labels

    return BROKER_LINES, BROKER_ROWS, B_COLS, HEADER_LABELS, K1_1065, K1_LABELS, k1_labels


@app.cell
def _(K1_1065, K1_LABELS):
    class Value(BaseModel):
        printed: str = Field(
            description="The value exactly as printed, keeping signs, parentheses, commas and decimals: "
            "'-27,942', '(18)', '1,629', '45,113.89', '-' for a printed dash, 'STMT', 'VARIOUS'."
        )
        bbox: list[int] = Field(
            description="Tight box around the printed value only (not its label or code letter): "
            "[x0, y0, x1, y1] in 0-1000 coordinates relative to the page image."
        )
        confidence: float = Field(
            ge=0, le=1, description="How sure you are that every character is read correctly, 0 to 1."
        )

    class Row(BaseModel):
        code: str = Field(
            description="For a coded box, the code printed to the left of the amount, as printed, "
            "including any asterisk ('A', 'AH*', '*'). An empty string for a box with no codes."
        )
        value: Value

    def k1_model(form: str, boxes: list[str]) -> type[BaseModel]:
        box = Field(description="The box number printed on the form, e.g. '1', '6a', '20'.")
        row = create_model("K1Row", __base__=Row, box=(Literal[tuple(boxes)], box))  # ty: ignore[invalid-type-form]
        return create_model(
            f"K1_{form}",
            __doc__=f"Schedule K-1 (Form {form}) as printed.",
            tax_year=(int, Field(description="The tax year printed on the form.")),
            payer_ein=(Value | None, Field(description="Part I item A: the employer identification number.")),
            payer_name=(Value | None, Field(description="Part I item B: the name only, without the address lines.")),
            boxes=(
                list[row],  # ty: ignore[invalid-type-form]
                Field(
                    description="Every Part III box that has something printed in it. "
                    "A coded box gives one row per printed code line."
                ),
            ),
        )

    K1_MODELS = {
        "1065": k1_model("1065", [*K1_1065, "4"]),
        "1120S": k1_model("1120S", list(K1_LABELS["1120S"])),
        "1041": k1_model("1041", list(K1_LABELS["1041"])),
    }

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

    FormQuestion = Literal[
        "Schedule K-1 (Form 1065)",
        "Schedule K-1 (Form 1120-S)",
        "Schedule K-1 (Form 1041)",
        "Consolidated brokerage Form 1099",
        "other",
    ]
    return Brokerage1099, FormQuestion, K1_MODELS, StatementLines


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Calling a model.** Each model is named by a Pydantic AI model string, such as
    `openrouter:google/gemini-3.8-flash`. A model from another provider is a different string and needs no code
    change. Models run at temperature 0, and thinking models at low effort: reading a form doesn't need long reasoning,
    and at the default they spent their whole 8,000-token output budget thinking. Each call gets six attempts, and
    Pydantic AI retries malformed output twice within each. **Every attempt is paid for and counted**, including one
    that failed after the model answered. The cost is the provider's own figure (OpenRouter reports it), or else
    Pydantic AI's price table. A response with no known cost is counted, and its document is left out of the average.

    Each answer is saved under `output/answers/`, with its cost and time. You can re-run the notebook, or open it in
    marimo, without calling the models again. Delete that folder for a fresh run.
    """)
    return


@app.cell
def _():
    INSTRUCTIONS = "\n".join(
        [
            "You read US tax documents for a tax preparer. Report only what is printed on the page.",
            "Never compute, infer or fill in a value. Leave out boxes that are empty.",
            "Bounding boxes are [x0, y0, x1, y1] in 0-1000 coordinates relative to the page image, "
            "tight around the printed value.",
            "Set confidence below 0.9 for any value where a character is smudged, faint, cut off or ambiguous.",
        ]
    )
    ATTEMPTS = 6

    def response_cost(m: ModelResponse) -> float | None:
        if (m.provider_details or {}).get("cost") is not None:
            return float((m.provider_details or {})["cost"])
        try:
            return float(m.cost().total_price)
        except LookupError:
            return None

    class Runner:
        """One model: asks it for typed answers, counts the cost of every attempt, and saves each answer."""

        def __init__(self, model_name: str, answers: Path) -> None:
            self.model = infer_model(model_name)
            settings = {"temperature": 0, "max_tokens": 8000, "thinking": "low"}
            self.settings: ModelSettings = (
                OpenRouterModelSettings(**settings, openrouter_usage={"include": True})  # OpenRouter reports cost
                if model_name.startswith("openrouter:")
                else ModelSettings(**settings)
            )
            self.answers = answers
            answers.mkdir(parents=True, exist_ok=True)
            self.slots = asyncio.Semaphore(6)
            self.cost: dict[str, dict[str, float]] = {}

        def spent(self, doc: str) -> dict[str, float]:
            return self.cost.setdefault(doc, {"usd": 0.0, "cost_missing": 0, "failed_attempts": 0, "seconds": 0.0})

        async def ask(self, doc: str, call: str, output_type: Any, prompt: str, images: list[bytes]) -> Any:
            saved_path = self.answers / f"{Path(doc).stem}.json"
            saved = json.loads(saved_path.read_text()) if saved_path.exists() else {}
            adapter = TypeAdapter(output_type)
            if call not in saved:
                output, cost = await self.call(output_type, prompt, images)
                saved[call] = {"output": adapter.dump_python(output, mode="json"), "cost": cost}
                saved_path.write_text(json.dumps(saved, indent=1))
            for k, v in saved[call]["cost"].items():
                self.spent(doc)[k] += v
            return adapter.validate_python(saved[call]["output"])

        async def call(self, output_type: Any, prompt: str, images: list[bytes]) -> tuple[Any, dict[str, float]]:
            agent = Agent(
                self.model, output_type=output_type, instructions=INSTRUCTIONS, retries=2, model_settings=self.settings
            )
            parts = [prompt] + [BinaryContent(png, media_type="image/png") for png in images]
            cost = {"usd": 0.0, "cost_missing": 0, "failed_attempts": 0, "seconds": 0.0}
            async with self.slots:
                for attempt in range(ATTEMPTS):
                    t0, error = time.time(), None
                    with capture_run_messages() as messages:
                        try:
                            output = (await agent.run(parts)).output
                        except Exception as e:  # rate limits, network errors, malformed output after retries
                            error = e
                    for m in (m for m in messages if isinstance(m, ModelResponse)):
                        usd = response_cost(m)
                        cost["usd"] += usd or 0.0
                        cost["cost_missing"] += usd is None
                    cost["seconds"] += time.time() - t0
                    if error is None:
                        return output, cost
                    cost["failed_attempts"] += 1
                    if attempt == ATTEMPTS - 1:
                        raise error
                    print(f"  retrying after {type(error).__name__}: {str(error)[:120]}")
                    await asyncio.sleep(15 * (attempt + 1))
            raise AssertionError("unreachable")

    return (Runner,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. When a value goes to review

    A value goes to the review queue when:

    - the model's confidence is below 0.9;
    - the amount is on an attached statement (`STMT`);
    - it isn't a well-formed amount;
    - a coded row has no code letter;
    - the form has no such box, or the same box is reported twice;
    - or a cross-check fails: qualified dividends above ordinary dividends, 4a + 4b ≠ 4c, or a 1099-B row where
      proceeds − cost + wash sale ≠ gain.

    **The whole page goes to review** when the model read nothing on it, wasn't sure of any value it read, or read too
    few values for the amounts Docling sees printed on it (when there are at least 8). Without this, every box the
    model left out would count as an accepted blank. "Too few" depends on the form. A K-1 prints many amounts the
    schema doesn't ask for, such as the capital account, so a K-1 answer is near-empty only below a quarter of the
    printed amounts. A 1099 summary page prints only the 18 amounts the schema asks for, so there the line is three
    quarters. Docling sees 15 to 17 amounts on each made-up summary page, and a full answer has 16 to 18 values. In
    an earlier run, GLM's sparse answers had 4 to 8.
    """)
    return


@app.cell
def _(BROKER_LINES, BROKER_ROWS, B_COLS, HEADER_LABELS, K1_1065):
    AMOUNT = re.compile(r"^(\(|-)?\$?\d{1,3}(,\d{3})*(\.\d{2})?\)?$")
    CONFIDENCE_MIN = 0.9

    def parse_value(text: str) -> tuple[Any, str]:
        """(value, kind), where kind is amount, statement, text, blank or unreadable."""
        t = text.replace("$", "").replace(" ", "")
        if not t:
            return None, "blank"
        if t in ("-", "—", "–"):
            return 0, "amount"
        if t.upper() == "STMT":
            return "STMT", "statement"
        if AMOUNT.match(t):
            v = float(t.strip("()-").replace(",", ""))
            v = v if "." in t else int(v)
            return (-v if t[0] in "(-" else v), "amount"
        if re.fullmatch(r"[A-Z]{2,}", t):
            return t, "text"  # a country code in the foreign transactions box
        return None, "unreadable"

    def code_of(t: str) -> str:
        """Codes are capital letters; a model sometimes doubles a letter in the other case ("Cc")."""
        m = re.fullmatch(r"([A-Za-z])\1\*?", t, re.I)
        if m and len(t.rstrip("*")) == 2 and t[0] != t[1]:
            return m.group(1).upper() + ("*" if t.endswith("*") else "")
        return t.upper()

    def same_text(a: str | None, b: str | None) -> bool:
        return re.sub(r"[^A-Z0-9]", "", (a or "").upper()) == re.sub(r"[^A-Z0-9]", "", (b or "").upper())

    def agrees(a: str, b: str) -> bool:
        """Two readings say the same: the same value, or the same digits and sign."""
        (va, ka), (vb, kb) = parse_value(a), parse_value(b)
        if ka == kb == "text":
            return same_text(a, b)
        if va is not None and va == vb:
            return True
        digits = re.sub(r"\D", "", a)
        negative = [bool(re.match(r"^\s*[(\-]", t)) for t in (a, b)]
        return bool(digits) and digits == re.sub(r"\D", "", b) and negative[0] == negative[1]

    def value_reasons(v: Any, allow_text: bool) -> list[str]:
        kind, reasons = parse_value(v.printed)[1], []
        if kind == "unreadable" or (kind == "text" and not allow_text):
            reasons.append(f"can't read '{v.printed}' as an amount")
        if kind == "statement":
            reasons.append("amount is on the attached statement")
        if v.confidence < CONFIDENCE_MIN:
            reasons.append(f"the model's confidence is {v.confidence:.2f}")
        return reasons

    def answer_fields(form: str, labels: dict[str, tuple[str, str]], out: Any, page: int) -> Fields:
        """The model's answer as values, each with its reasons for review."""
        fields: Fields = []

        def add(key: str, label: str, v: Any, reasons: list[str]) -> None:
            payer = key.startswith("payer")
            if not payer:
                reasons += value_reasons(v, allow_text=key.startswith("16 "))
            elif v.confidence < CONFIDENCE_MIN:
                reasons.append(f"the model's confidence is {v.confidence:.2f}")
            if any(f["key"] == key for f in fields):
                reasons.insert(0, f"{key} appears twice")
                key = f"{key} (again)"
            value = v.printed.split("\n")[0].strip() if payer else parse_value(v.printed)[0]
            bbox = [round(b / 1000, 4) for b in v.bbox] if len(v.bbox) == 4 else None
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "value": value,
                    "raw": v.printed,
                    "page": page,
                    "bbox": bbox,
                    "confidence": round(v.confidence * 100),
                    "reasons": reasons,
                }
            )

        if form == "BROKER":
            for key, label in BROKER_LINES.items():
                if (v := getattr(out, key.replace(" ", "_"))) is not None:
                    add(key, label, v, [])
            for term, label in BROKER_ROWS.items():
                for col in B_COLS if (row := getattr(out, f"B_{term}")) is not None else []:
                    add(f"B {term} {col}", f"1099-B {label}: {col}", getattr(row, col), [])
            broker_crosschecks(fields)
            return fields
        for key, label in zip(("payer_ein", "payer_name"), HEADER_LABELS[form], strict=True):
            if getattr(out, key) is not None:
                add(key, label, getattr(out, key), [])
        for r in out.boxes:
            label, kind = labels.get(r.box, (K1_1065.get(r.box, ("", ""))[0], "amount"))
            reasons, key = ([] if r.box in labels else [f"Form {form} for this year has no box {r.box}"]), r.box
            if kind == "coded":
                code = code_of(r.code.strip().replace(" ", "")) if r.code.strip() else "?"
                reasons += ["the model gave no code for a row in a coded box"] if code == "?" else []
                key, label = f"{r.box} {code}", f"{label}, code {code}"
            add(key, label, r.value, reasons)
        k1_crosschecks(fields, form)
        return fields

    def number(fields: Fields, key: str) -> float | None:
        f = next((f for f in fields if f["key"] == key), None)
        return f["value"] if f and isinstance(f["value"], int | float) else None

    def flag(fields: Fields, keys: list[str], reason: str) -> None:
        for f in (f for f in fields if f["key"] in keys):
            f["reasons"].append(reason)

    def k1_crosschecks(fields: Fields, form: str) -> None:
        total, part = {"1065": ("6a", "6b"), "1120S": ("5a", "5b"), "1041": ("2a", "2b")}[form]
        t, p = number(fields, total), number(fields, part)
        if t is not None and p is not None and p > t:
            flag(fields, [total, part], f"qualified dividends ({part}) exceed ordinary dividends ({total})")
        if p is not None and not any(f["key"] == total for f in fields):
            flag(fields, [part], f"qualified dividends ({part}) present but ordinary dividends ({total}) blank")
        keys = ["4a", "4b", "4c"]
        if form == "1065" and any(f["key"] in keys for f in fields):
            a, b, c = (number(fields, k) or 0 for k in keys)
            if a + b != c:
                flag(fields, keys, "4a + 4b doesn't equal 4c")

    def broker_crosschecks(fields: Fields) -> None:
        a, q = number(fields, "DIV 1a"), number(fields, "DIV 1b")
        if a is not None and q is not None and q > a:
            flag(fields, ["DIV 1a", "DIV 1b"], "qualified dividends (1b) exceed ordinary dividends (1a)")
        for term in BROKER_ROWS:
            keys = [f"B {term} {c}" for c in B_COLS]
            vals = [number(fields, k) for k in keys]
            if None in vals:
                continue
            p, c, w, g = (v or 0.0 for v in vals)
            if abs(p - c + w - g) > 0.011:
                flag(fields, keys, "proceeds - cost + wash sale doesn't equal gain or loss")

    # An amount as printed: with a thousands comma or cents, so box numbers and years don't count. Zeros don't
    # count either, since an empty box can print as 0.00.
    PRINTED_AMOUNT = re.compile(r"^[($-]*(\d{1,3}(,\d{3})+(\.\d\d)?|\d+\.\d\d)\)?$")
    MIN_READ_SHARE = {"BROKER": 0.75, "K-1": 0.25}

    def page_review(page_text: str, fields: Fields, form: str) -> str | None:
        """Why the whole page should go to review, or None."""
        read = [f for f in fields if f["raw"] and not f["key"].startswith("payer") and f["key"] != "page"]
        if not read:
            return "the model read nothing on this page"
        printed = sum(1 for w in page_text.split() if PRINTED_AMOUNT.match(w) and re.search(r"[1-9]", w))
        if printed >= 8 and len(read) < printed * MIN_READ_SHARE["BROKER" if form == "BROKER" else "K-1"]:
            values = f"{len(read)} value" + ("" if len(read) == 1 else "s")
            return f"the model read only {values} on a page that shows about {printed} amounts"
        if all(f["reasons"] for f in read):
            return "the model wasn't sure of any value on this page, so a box it left out may not be blank"
        return None

    def whole_page(page: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "key": "page",
            "label": "The whole page",
            "value": None,
            "raw": "",
            "page": page["index"],
            "bbox": None,
            "confidence": 0,
            "reasons": [reason],
        }

    def finish(fields: Fields, page: dict[str, Any], form: str) -> str | None:
        """Add the whole-page check and set each value's status."""
        reason = page_review(page["text"], fields, form)
        if reason and not any(f["key"] == "page" for f in fields):
            fields.append(whole_page(page, reason))
        for f in fields:
            f["status"] = "review" if f["reasons"] else "accepted"
        return reason

    return agrees, answer_fields, finish, parse_value, same_text, whole_page


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. Reading a document

    For each document, we find the K-1 or 1099 page from Docling's text. On a bad scan Docling sometimes can't tell,
    so the model is asked which form it is. The model reads the page, and its answer becomes values with their reasons
    for review. For each `STMT` amount, the model reads the statement page and lists that box's lines. The reviewer
    sees those lines as a suggestion, each marked by whether Docling's table has the same code and amount. The value
    stays in the queue.
    """)
    return


@app.cell
def _(
    Brokerage1099,
    FormQuestion,
    K1_MODELS,
    StatementLines,
    answer_fields,
    finish,
    k1_labels,
    layouts,
    page_png,
    parse_value,
    page_image,
):
    FORM_ANSWERS = {
        "Schedule K-1 (Form 1065)": "1065",
        "Schedule K-1 (Form 1120-S)": "1120S",
        "Schedule K-1 (Form 1041)": "1041",
        "Consolidated brokerage Form 1099": "BROKER",
    }

    def k1_kind(text: str) -> str | None:
        t = re.sub(r"[^a-z0-9%()]", "", text.lower())
        for form, who in (("1120S", "shareholders"), ("1041", "beneficiarys"), ("1065", "partners")):
            if f"{who}shareofcurrentyear" in t:
                return form
        return None

    def find_form(pages: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any]]:
        for p in pages:
            if "consolidated form 1099" in p["text"].lower():
                return "BROKER", p
            if form := k1_kind(p["text"]):
                return form, p
        return None, pages[0]

    def calendar_year(text: str) -> int | None:
        m = re.search(r"calendar\s*year\s*(20\d\d)", text, re.I)
        return int(m.group(1)) if m else None

    def k1_prompt(form: str, intro: str = "") -> str:
        boxes = k1_labels(form, 2025).items()
        guide = "; ".join(f"{b} {label}" + (" (coded)" if kind == "coded" else "") for b, (label, kind) in boxes)
        return f"{intro}Read this Schedule K-1 (Form {form}). Part III boxes on this form include: {guide}."

    def statement_rows(markdown: str) -> list[tuple[str, str, str]]:
        """Box / Description / Amount rows from Docling's tables on a statement page."""
        rows = []
        for line in markdown.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and re.fullmatch(r"\d{1,2}[A-Z]{1,2}\d*", cells[0].replace(" ", "")):
                rows.append((cells[0].replace(" ", ""), cells[1], cells[-1]))
        return rows

    async def read_statements(runner: Any, path: Path, fields: Fields, pages: list[dict[str, Any]]) -> None:
        for f in (f for f in fields if f["value"] == "STMT"):
            box = f["key"].split(" ")[0]
            if not pages:
                f["reasons"] = ["amount is on an attached statement, but there's no statement page in the file"]
                continue
            hits = [
                p
                for p in pages
                if any(re.match(rf"{re.escape(box)}[A-Z]", r[0]) for r in statement_rows(p["markdown"]))
            ]
            sp = (hits or pages)[0]
            prompt = (
                f"This is a supplemental statement to a Schedule K-1. List every line that belongs to box {box} "
                f"(codes starting with {box}). Docling's reading of the page, for reference:\n\n{sp['markdown'][:6000]}"
            )
            lines = await runner.ask(
                path.name, f"statement {box}", StatementLines, prompt, [page_png(path, sp["index"])]
            )
            table = {code: amount for code, _d, amount in statement_rows(sp["markdown"])}
            f["reasons"] = [f"amount is on the attached statement (page {sp['index'] + 1})"]
            f["statement_page"], f["statement_lines"] = sp["index"], []
            for ln in lines.lines:
                value, code = parse_value(ln.printed)[0], ln.code.replace(" ", "").upper()
                bbox = [round(b / 1000, 4) for b in ln.bbox] if len(ln.bbox) == 4 else None
                agrees_with_docling = code in table and parse_value(table[code])[0] == value
                f["statement_lines"].append(
                    {
                        "code": ln.code,
                        "description": ln.description,
                        "printed": ln.printed,
                        "value": value,
                        "bbox": bbox,
                        "docling_agrees": agrees_with_docling,
                    }
                )

    async def read_document(runner: Any, path: Path) -> dict[str, Any] | None:
        layout = layouts[path.name]
        pages = layout["pages"]
        form, main = find_form(pages)
        if form is None:
            kind = await runner.ask(
                path.name, "form", FormQuestion, "Which tax form is this page?", [page_png(path, 0)]
            )
            form = FORM_ANSWERS.get(kind)
        if form is None:
            return None
        png, year = page_png(path, main["index"]), None
        if form == "BROKER":
            prompt = "Read the summary amounts on this consolidated brokerage 1099 page."
            fields = answer_fields(
                form, {}, await runner.ask(path.name, "extraction", Brokerage1099, prompt, [png]), main["index"]
            )
        else:
            prompt = k1_prompt(form) + (
                " In a coded box, report one row per printed line, with the code letter printed to the left of the "
                "amount on that line (every line in a coded box has one), including lines whose amount is a dash and "
                "lines coded '*' with STMT."
            )
            out = await runner.ask(path.name, "extraction", K1_MODELS[form], prompt, [png])
            year = calendar_year(main["text"]) or out.tax_year
            fields = answer_fields(form, k1_labels(form, year), out, main["index"])
            later = [p for p in pages if p["index"] > main["index"] and statement_rows(p["markdown"])]
            await read_statements(runner, path, fields, later)
        reason = finish(fields, main, form)
        shown = [main["index"]] + ([main["index"] + 1] if form == "BROKER" and len(pages) > main["index"] + 1 else [])
        shown += sorted({f["statement_page"] for f in fields if "statement_page" in f})
        spent = runner.spent(path.name)
        return {
            "file": path.name,
            "form": form,
            "year": year,
            "source": "OCR" if main["ocr"] else "text layer",
            "page_review": reason,
            "pages": {str(i): page_image(path, i) for i in shown},
            "docling_seconds": layout["seconds"],
            "model_seconds": round(spent["seconds"], 1),
            "seconds": round(layout["seconds"] + spent["seconds"], 1),
            "cost_usd": round(spent["usd"], 6),
            "cost_missing_responses": spent["cost_missing"],
            "failed_attempts": spent["failed_attempts"],
            "fields": fields,
        }

    return calendar_year, find_form, k1_kind, k1_prompt, read_document


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. Every model reads every document

    The five models run side by side, all through OpenRouter. A model that fails every attempt on some documents is
    scored on the rest, and its failed documents are listed. The run stops only if Gemini 3.8 Flash or Qwen 3.8 27B
    produce nothing, since the pair below needs both.
    """)
    return


@app.cell
async def _(FILES, Runner, read_document):
    MODELS = {
        "gemini-3.8-flash": "openrouter:google/gemini-3.8-flash",
        "qwen3.8-27b": "openrouter:qwen/qwen3.8-27b",
        "qwen3-vl-235b-a22b-instruct": "openrouter:qwen/qwen3-vl-235b-a22b-instruct",
        "glm-5.3-flash": "openrouter:z-ai/glm-5.3-flash",
        "gemma-4-31b-it": "openrouter:google/gemma-4-31b-it",
    }
    PAIR = ("gemini-3.8-flash", "qwen3.8-27b")

    async def read_all(name: str, model_name: str, read: Any, out_dir: Path) -> dict[str, Any]:
        """Run read(path) on every document. A document that fails is listed as failed, and doesn't stop the run."""

        async def one(path: Path) -> tuple[Path, dict[str, Any] | None, str]:
            try:
                doc = await read(path)
            except Exception as e:
                print(f"{name} {path.name}: failed: {type(e).__name__}: {str(e)[:200]}")
                return path, None, f"{type(e).__name__}: {str(e)[:200]}"
            if doc:
                n = sum(f["status"] == "review" for f in doc["fields"])
                print(f"{name} {path.name}: {len(doc['fields'])} values, {n} to review, ${doc['cost_usd']:.4f}")
            return path, doc, "no result"

        results = await asyncio.gather(*(one(p) for p in FILES))
        run = {
            "name": name,
            "model": model_name,
            "documents": [d for _p, d, _e in results if d],
            "failed_documents": [{"file": p.name, "error": e} for p, d, e in results if not d],
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "extracted.json").write_text(json.dumps(run, indent=1))
        return run

    async def read_with(name: str, model_name: str) -> dict[str, Any]:
        runner, out_dir = Runner(model_name, OUT / "answers" / name), OUT / f"{name}-alone"
        run = await read_all(name, model_name, lambda p: read_document(runner, p), out_dir)
        description = f"Read by {model_name} through OpenRouter, with no second read."
        return run | {"dir": out_dir, "label": f"{name}, alone", "description": description}

    model_runs = dict(zip(MODELS, await asyncio.gather(*(read_with(n, m) for n, m in MODELS.items())), strict=True))
    for _name in PAIR:
        if not model_runs[_name]["documents"]:
            raise RuntimeError(f"{_name} produced no results, and the pair needs it")
    model_runs = {k: r for k, r in model_runs.items() if r["documents"]}
    return MODELS, PAIR, model_runs, read_all


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 7. Two models that must agree

    Gemini 3.8 Flash's own confidence never flags anything: everything it sends to review is a STMT amount or a
    malformed one. So when it misreads a bad scan, nothing in its own answer catches it. A second, independent read
    can catch it. The pair combines the two models' saved answers, with no further calls. A value is accepted only
    when both models report the same box and code with the same amount, and neither has its own reason to send it to
    review. Anything only one reported, or that they read differently, goes to review. A pair costs the sum of its
    two models and takes as long as the slower one.
    """)
    return


@app.cell
def _(PAIR, agrees, model_runs, same_text):
    def combine(da: dict[str, Any], db: dict[str, Any], na: str, nb: str) -> dict[str, Any]:
        other_fields, fields = {f["key"]: f for f in db["fields"]}, []
        for fa in da["fields"]:
            f = dict(fa, reasons=list(fa["reasons"]))
            if (other := other_fields.pop(fa["key"], None)) is None:
                f["reasons"].append(f"only {na} reported it")
            else:
                f["reasons"] += [r for r in other["reasons"] if r not in f["reasons"]]
                payer = fa["key"].startswith("payer")
                if not (same_text(fa["value"], other["value"]) if payer else agrees(fa["raw"], other["raw"])):
                    f["reasons"].append(f"{nb} read '{other['raw']}'")
                f["confidence"] = min(fa["confidence"], other["confidence"])
            fields.append(f)
        fields += [dict(o, reasons=[*o["reasons"], f"only {nb} reported it"]) for o in other_fields.values()]
        for f in fields:
            f["status"] = "review" if f["reasons"] else "accepted"
        slower = max(da["model_seconds"], db["model_seconds"])
        return da | {
            "fields": fields,
            "page_review": da["page_review"] or db["page_review"],
            "cost_usd": round(da["cost_usd"] + db["cost_usd"], 6),
            "cost_missing_responses": da["cost_missing_responses"] + db["cost_missing_responses"],
            "failed_attempts": da["failed_attempts"] + db["failed_attempts"],
            "model_seconds": slower,
            "seconds": round(da["docling_seconds"] + slower, 1),
        }

    _a, _b = (model_runs[n] for n in PAIR)
    _docs_b = {d["file"]: d for d in _b["documents"]}
    _pair_docs = [combine(d, _docs_b[d["file"]], *PAIR) for d in _a["documents"] if d["file"] in _docs_b]
    _done = {d["file"] for d in _pair_docs}
    _failed = {f["file"]: f["error"] for r in (_a, _b) for f in r["failed_documents"]}
    _failed |= {d["file"]: "only one model read it" for r in (_a, _b) for d in r["documents"] if d["file"] not in _done}
    pair_run = {
        "name": "pair",
        "dir": OUT / f"pair-{PAIR[0]}+{PAIR[1]}",
        "label": f"{PAIR[0]} + {PAIR[1]}, must agree",
        "model": f"{_a['model']} checked by {_b['model']}",
        "documents": _pair_docs,
        "description": f"Read by {_a['model']} and {_b['model']} through OpenRouter. "
        "A value is accepted only when both models read the same thing.",
        "failed_documents": [{"file": f, "error": e} for f, e in sorted(_failed.items())],
    }
    return (pair_run,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 8. Reading text instead of the image: OCR models on Modal

    olmOCR 2 and granite-docling turn a page into text rather than filling a schema. So each is followed by a text
    model, Gemini 3.8 Flash, which fills the same typed schema from the OCR text with the same review rules and never
    sees the image. `ocr_modal.py` is the Modal app. A CPU container downloads both models' weights into a Modal
    Volume once, and the L4 GPU containers only read pages.

    - **olmOCR 2** (`allenai/olmOCR-2-7B-1025-FP8`) runs on vLLM with olmOCR's own prompt and 1288-pixel page
      images, and returns Markdown with HTML tables.
    - **granite-docling** (`ibm-granite/granite-docling-258M`) is served by vLLM behind an API key made for each run.
      Docling's VLM pipeline runs here and calls it, using Docling's own `GRANITEDOCLING_VLLM_API` preset with two
      changes. The preset asks the server to skip special tokens, but granite-docling's DocTags *are* special tokens,
      so Docling got nothing to parse. And a dense form needs more than the preset's 4,096 output tokens.

    The GPU cost is Modal's L4 list price ($0.000222 a second) for each page's GPU time. For granite-docling that time
    is each page's round trip to a server handling several pages at once, so it overstates its share. This section
    runs only when `MODAL_TOKEN_ID` is set. OCR results are saved under `output/ocr/`. The text model has no image to
    point into, so these runs' review screens don't highlight values on the page.
    """)
    return


@app.cell
def _():
    ENGINES = {
        "olmocr": "olmOCR 2 (allenai/olmOCR-2-7B-1025-FP8)",
        "granite-docling": "granite-docling (ibm-granite/granite-docling-258M) in Docling's VLM pipeline",
    }
    L4_USD_PER_SECOND = 0.000222

    def granite_page(url: str, path: Path, index: int) -> dict[str, Any]:
        """One page through Docling's VLM pipeline, with granite-docling running on Modal."""
        spec = vlm_model_specs.GRANITEDOCLING_VLLM_API.model_copy(deep=True)
        spec.url = AnyUrl(f"{url}/v1/chat/completions")
        spec.headers = {"Authorization": f"Bearer {ocr_modal.API_KEY}"}
        spec.timeout = 600
        spec.params["skip_special_tokens"] = False
        spec.params["max_tokens"] = 7000  # what the server's 8,192-token context leaves after the page image
        options = VlmPipelineOptions(vlm_options=spec, enable_remote_services=True)
        pdf = PdfFormatOption(pipeline_cls=VlmPipeline, pipeline_options=options)
        t0 = time.time()
        result = DocumentConverter(format_options={InputFormat.PDF: pdf}).convert(
            path, page_range=(index + 1, index + 1)
        )
        return {"markdown": result.document.export_to_markdown(), "seconds": round(time.time() - t0, 1)}

    def ocr_pages(engine: str, jobs: dict[Path, int], page_png: Any) -> dict[str, dict[str, Any]]:
        """OCR each document's page on Modal, unless it was read before."""
        saved = OUT / "ocr" / engine
        saved.mkdir(parents=True, exist_ok=True)
        todo = [(p, i) for p, i in jobs.items() if not (saved / f"{p.stem}-p{i + 1}.json").exists()]
        if todo:
            print(f"{engine}: reading {len(todo)} pages on Modal")
            with modal.enable_output(), ocr_modal.app.run():
                ocr_modal.download.remote()
                if engine == "olmocr":
                    outs = ocr_modal.OlmOCR().ocr.remote([page_png(p, i) for p, i in todo])
                else:
                    url = ocr_modal.GraniteServer().serve.get_web_url()  # ty: ignore[call-non-callable]
                    assert url, "the granite-docling server has no URL"
                    with ThreadPoolExecutor(8) as pool:
                        outs = list(pool.map(lambda job: granite_page(url, *job), todo))
            for (p, i), out in zip(todo, outs, strict=True):
                (saved / f"{p.stem}-p{i + 1}.json").write_text(json.dumps(out))
        return {p.name: json.loads((saved / f"{p.stem}-p{i + 1}.json").read_text()) for p, i in jobs.items()}

    return ENGINES, L4_USD_PER_SECOND, ocr_pages


@app.cell
async def _(
    Brokerage1099,
    ENGINES,
    FILES,
    K1_MODELS,
    L4_USD_PER_SECOND,
    MODELS,
    Runner,
    answer_fields,
    calendar_year,
    find_form,
    finish,
    k1_kind,
    k1_labels,
    k1_prompt,
    layouts,
    ocr_pages,
    page_png,
    read_all,
    page_image,
    whole_page,
):
    def form_of(text: str) -> str | None:
        """The form, from the OCR text: the Part III heading, or the form named in the title."""
        if "consolidated form 1099" in text.lower() or "1099-div" in text.lower():
            return "BROKER"
        if form := k1_kind(text):
            return form
        m = re.search(r"Schedule K-1\s*\(Form (1065|1120-?S|1041)\)", text[:600], re.I)
        return m.group(1).upper().replace("-", "") if m else None

    async def read_ocr_text(runner: Any, engine: str, path: Path, ocr: dict[str, Any]) -> dict[str, Any]:
        page = find_form(layouts[path.name]["pages"])[1]
        text = re.sub(r"\A---\n.*?\n---\n", "", ocr["markdown"], flags=re.S).strip()  # without olmOCR's front matter
        note = (
            f"Below is the text of one page of a tax document, as read by an OCR model ({ENGINES[engine]}). "
            "You don't have the image, so set every bbox to [0, 0, 0, 0]. Set confidence below 0.9 where the text "
            "looks garbled or a value is ambiguous.\n\n"
        )
        form, year = form_of(text), None
        if form == "BROKER":
            prompt = note + "Read the summary amounts of this consolidated brokerage 1099.\n\n" + text
            fields = answer_fields(
                form, {}, await runner.ask(path.name, "extraction", Brokerage1099, prompt, []), page["index"]
            )
        elif form:
            coded = " In a coded box, report one row per printed line with its code letter, including lines whose "
            prompt = k1_prompt(form, note) + coded + "amount is a dash and lines coded '*' with STMT.\n\n" + text
            out = await runner.ask(path.name, "extraction", K1_MODELS[form], prompt, [])
            year = calendar_year(text) or out.tax_year
            fields = answer_fields(form, k1_labels(form, year), out, page["index"])
        else:
            fields = [whole_page(page, "couldn't tell from the OCR text which form this is")]
        reason = finish(fields, page, form or "")
        for f in fields:
            f["bbox"] = None
        spent, gpu = runner.spent(path.name), ocr["seconds"]
        return {
            "file": path.name,
            "form": form,
            "year": year,
            "source": f"{engine} OCR",
            "page_review": reason,
            "pages": {str(page["index"]): page_image(path, page["index"])},
            "docling_seconds": 0.0,
            "ocr_seconds": gpu,
            "model_seconds": round(spent["seconds"], 1),
            "seconds": round(gpu + spent["seconds"], 1),
            "cost_usd": round(spent["usd"] + gpu * L4_USD_PER_SECOND, 6),
            "failed_attempts": spent["failed_attempts"],
            "cost_missing_responses": spent["cost_missing"],
            "fields": fields,
        }

    async def read_with_ocr(engine: str) -> dict[str, Any]:
        model_name, name = MODELS["gemini-3.8-flash"], f"{engine}+gemini-3.8-flash"
        ocr = await asyncio.to_thread(
            ocr_pages, engine, {p: find_form(layouts[p.name]["pages"])[1]["index"] for p in FILES}, page_png
        )
        runner, out_dir = Runner(model_name, OUT / "answers" / name), OUT / name
        run = await read_all(name, model_name, lambda p: read_ocr_text(runner, engine, p, ocr[p.name]), out_dir)
        description = f"Read by {ENGINES[engine]} on Modal; {model_name} filled the form from its text."
        return run | {
            "dir": out_dir,
            "label": f"{engine} OCR + gemini-3.8-flash on the text",
            "description": description,
        }

    ocr_runs: dict[str, dict[str, Any]] = {}
    if os.environ.get("MODAL_TOKEN_ID"):
        for _engine in ENGINES:  # one after the other: ephemeral runs of the Modal app share the server's URL
            if (_run := await read_with_ocr(_engine))["documents"]:
                ocr_runs[_engine] = _run
    else:
        print("MODAL_TOKEN_ID isn't set, so the OCR models didn't run.")
    return (ocr_runs,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 9. Scoring against the answer keys

    No extractor reads the answer keys; this step scores every run afterwards. The real K-1s are scored against the
    hand-keyed `real_answer_key.json`, and a scan against its original's key. The made-up documents are scored against
    the key the generator wrote. **Boxes** means every box on the key plus every value a run reported, so reading
    something in an empty box, or reporting a box twice, is an error. A box the run never reported counts as an
    accepted blank, unless the whole page went to review. It also counts as in review if a row of the same coded box,
    with the same letter or no letter, went to review. The **held-out set** is the 14 documents whose scans and values
    use seeds not used while building the rules.

    Statement lines are checked separately, against the issuer's own text layer, because the keys stop at `STMT`.
    """)
    return


@app.cell
def _(made_up_key, parse_value):
    answer_keys = {k: v for k, v in json.loads((HERE / "real_answer_key.json").read_text()).items() if k[0] != "_"}
    answer_keys |= made_up_key

    def same(a: Any, b: Any) -> bool:
        if isinstance(a, int | float) and isinstance(b, int | float):
            return abs(a - b) < 0.005
        if isinstance(a, str) and isinstance(b, str):
            return re.sub(r"[^A-Z0-9]", "", a.upper()) == re.sub(r"[^A-Z0-9]", "", b.upper())
        return a is None and b is None

    def score_document(doc: dict[str, Any]) -> list[dict[str, Any]]:
        """One row per box: whether the run got it right, and whether it was accepted. Marks each value too."""
        key = answer_keys[re.sub(r"-scan\d[ab]\.pdf$", ".pdf", doc["file"])]
        truth = dict(key["fields"])
        if doc["form"] != "BROKER":
            truth |= {k: v for k, v in key["header"].items() if k in ("payer_ein", "payer_name")}
        got = {f["key"]: f for f in doc["fields"] if f["key"] != "page"}
        scan = re.search(r"-scan(\d)[ab]\.pdf$", doc["file"])
        levels = {"original": "born-digital", 0: "clean scan", 1: "office scan", 2: "bad scan"}
        level = {"1": "office scan", "2": "bad scan"}[scan.group(1)] if scan else levels[key["scan_level"]]
        group = "real" if doc["file"][:2] in ("01", "02", "03") else "made-up"
        held_out = doc["file"].startswith("2") or bool(re.search(r"-scan\db\.pdf$", doc["file"]))
        source = f"{'held out' if held_out else 'tuning'} / {group} / {level}"
        rows = []
        for k in sorted(set(truth) | set(got)):
            f, expected = got.get(k), truth.get(k)
            correct = same(f["value"] if f else None, expected) and (f is None or k in truth)
            status = f["status"] if f else ("review" if doc["page_review"] else "accepted")
            box, letter = k.split(" ")[0], k.split(" ")[1].rstrip("*") if " " in k else None
            if (
                f is None
                and letter
                and any(
                    g["status"] == "review" and g["key"].split(" (")[0].rstrip("*") in (f"{box} ?", f"{box} {letter}")
                    for g in doc["fields"]
                )
            ):
                status = "review"
            if f is not None:
                f["correct"], f["expected"] = correct, expected
            rows.append(
                {
                    "file": doc["file"],
                    "key": k,
                    "correct": correct,
                    "status": status,
                    "source": source,
                    "statement": expected == "STMT",
                }
            )
        return rows

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        accepted = [r for r in rows if r["status"] == "accepted"]
        review = [r for r in rows if r["status"] == "review"]
        wrong = [r for r in rows if not r["correct"]]
        silent = [r for r in wrong if r["status"] == "accepted"]
        return {
            "documents": len({r["file"] for r in rows}),
            "boxes_checked": len(rows),
            "correct": len(rows) - len(wrong),
            "accepted": len(accepted),
            "accepted_correct": sum(r["correct"] for r in accepted),
            "sent_to_review": len(review),
            "review_because_statement": sum(r["statement"] for r in review),
            "wrong": len(wrong),
            "wrong_caught_by_review": len(wrong) - len(silent),
            "silent_errors": len(silent),
            "silent_error_boxes": [f"{r['file']} box {r['key']}" for r in silent],
        }

    def statement_check(docs: list[dict[str, Any]]) -> dict[str, int] | None:
        """Each statement line a model read, against the line with that code on the issuer's own statement."""
        read = right = missed = 0
        for doc in docs:
            fields = [f for f in doc["fields"] if "statement_lines" in f]
            if not fields:
                continue
            with pdfplumber.open(SAMPLES / doc["file"]) as pdf:
                text = [ln for pg in pdf.pages for ln in (pg.extract_text() or "").splitlines()]
            for f in fields:
                box = f["key"].split(" ")[0]
                printed = {ln.split()[0]: ln.split()[-1] for ln in text if re.match(rf"^{box}[A-Z]{{1,2}}\d*\s", ln)}
                lines = {ln["code"].replace(" ", "").upper(): ln for ln in f["statement_lines"]}
                missed, read = missed + len(set(printed) - set(lines)), read + len(lines)
                right += sum(c in printed and parse_value(printed[c])[0] == ln["value"] for c, ln in lines.items())
        return {"lines_read": read, "right": right, "lines_missed": missed} if read or missed else None

    def score(run: dict[str, Any]) -> dict[str, Any]:
        docs = run["documents"]
        rows = [r for d in docs for r in score_document(d)]
        known = [d["cost_usd"] for d in docs if not d["cost_missing_responses"]]
        per_doc = {
            f"{k}_per_document": round(sum(d.get(k, 0) for d in docs) / len(docs), 1)
            for k in ("seconds", "model_seconds", "ocr_seconds")
        }
        sources = sorted({r["source"] for r in rows}, reverse=True)
        return {
            "all": summarize(rows),
            "held_out_set": summarize([r for r in rows if r["source"].startswith("held")]),
            "by_source": {s: summarize([r for r in rows if r["source"] == s]) for s in sources},
            "cost_usd_per_document": round(sum(known) / len(known), 5) if known else None,
            "cost_usd_total": round(sum(d["cost_usd"] for d in docs), 4),
            "cost_unknown_documents": [d["file"] for d in docs if d["cost_missing_responses"]],
            "failed_attempts": sum(d["failed_attempts"] for d in docs),
            "failed_documents": [f["file"] for f in run["failed_documents"]],
            "statement_lines": statement_check(docs),
            **per_doc,
        }

    return (score,)


@app.cell
def _(model_runs, ocr_runs, pair_run, score):
    runs = [*model_runs.values(), *ocr_runs.values(), pair_run]
    _lines = [
        "| Pipeline | Values right | Accepted without review | Wrong but accepted | Sent to review (STMT) "
        "| Cost per document | Model time per document | Failed documents |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _run in runs:
        _run["metrics"] = _m = score(_run)
        _run["dir"].mkdir(parents=True, exist_ok=True)
        (_run["dir"] / "metrics.json").write_text(json.dumps(_m, indent=1))
        _a = _m["all"]
        _cost = "unknown" if _m["cost_usd_per_document"] is None else f"${_m['cost_usd_per_document']:.4f}"
        _gpu = f"{_m['ocr_seconds_per_document']} s GPU + " if _m["ocr_seconds_per_document"] else ""
        _lines.append(
            f"| {_run['label']} | {_a['correct']} of {_a['boxes_checked']} | {_a['accepted']} "
            f"| {_a['silent_errors']} | {_a['sent_to_review']} ({_a['review_because_statement']}) | {_cost} "
            f"| {_gpu}{_m['model_seconds_per_document']} s | {len(_m['failed_documents'])} |"
        )
    results_table = "\n".join(_lines)
    print(results_table)
    return results_table, runs


@app.cell
def _(results_table):
    mo.md(
        '## 10. Results\n\n"Wrong but accepted" counts wrong values that were accepted, and boxes on the key that a '
        "run never reported, since a missed row reads as a blank box. A run that failed some documents is scored on "
        "the rest, so it isn't comparable box for box. Model time leaves out Docling's layout pass, which adds its own "
        "seconds per document on CPU to every vision-model row.\n\n" + results_table
    )
    return


@app.cell
def _(runs):
    _out = [
        "# Pipelines compared",
        "",
        "Same documents and answer keys. A silent error is a wrong value accepted "
        "without review. Written by notebook.py.",
        "",
    ]
    for _source in ["held_out_set", *runs[0]["metrics"]["by_source"]]:
        _out += [
            f"## {_source.replace('_', ' ')}",
            "",
            "| Pipeline | Boxes | Accepted (right) | Sent to review | Silent errors |",
            "|---|---|---|---|---|",
        ]
        for _run in runs:
            if _s := _run["metrics"].get(_source) or _run["metrics"]["by_source"].get(_source):
                _out.append(
                    f"| {_run['label']} | {_s['boxes_checked']} | {_s['accepted']} ({_s['accepted_correct']}) "
                    f"| {_s['sent_to_review']} | {_s['silent_errors']} |"
                )
        _out.append("")
    for _run in runs:
        _m, _st = _run["metrics"], _run["metrics"]["statement_lines"]
        _stmt = (
            f"Statement lines: {_st['right']} of {_st['lines_read']} right, {_st['lines_missed']} missed. "
            if _st
            else ""
        )
        _out += [
            f"**{_run['label']}**: ${_m['cost_usd_total']:.2f} in all, {_m['failed_attempts']} failed attempts. "
            f"{_stmt}Failed documents: {', '.join(_m['failed_documents']) or 'none'}. "
            f"Unknown cost: {', '.join(_m['cost_unknown_documents']) or 'none'}. "
            f"Silent errors: {'; '.join(_m['all']['silent_error_boxes']) or 'none'}.",
            "",
        ]
    comparison = "\n".join(_out)
    (OUT / "comparison.md").write_text(comparison)
    print(f"Total cost of this run: ${sum(r['metrics']['cost_usd_total'] for r in runs if r['name'] != 'pair'):.2f}")
    mo.md(comparison)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 11. The review screen

    Each run gets a review screen, `output/<run>/index.html`. Clicking a value highlights its box on the page, and a
    STMT value opens the statement page. The queue shows each flagged box cropped from the page, with its reason, and
    lets a person correct or confirm it. Corrections stay in the browser and export to CSV. With `K1_SCREENSHOTS=1`
    (`./run.sh --screenshots`), Playwright saves `screenshots/` from Gemini 3.8 Flash's screen.
    """)
    return


@app.cell
def _(runs):
    _template = (HERE / "review_screen.html").read_text()
    for _run in runs:
        _docs = sorted(_run["documents"], key=lambda d: (d["file"][:2], "-scan" in d["file"], d["file"]))
        _data = json.dumps({"description": _run["description"], "documents": _docs})
        _html = _template.replace("__DATA__", _data).replace("__METRICS__", json.dumps(_run["metrics"]))
        (_run["dir"] / "index.html").write_text(_html)
    review_screen = OUT / "gemini-3.8-flash-alone" / "index.html"
    return (review_screen,)


@app.cell
async def _(review_screen):
    # The async API, because marimo runs the notebook inside an event loop.
    if os.environ.get("K1_SCREENSHOTS") == "1":
        _shots, _errors = HERE / "screenshots", []
        _shots.mkdir(exist_ok=True)
        async with async_playwright() as _p:
            _browser = await _p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH"))
            _page = await _browser.new_page(viewport={"width": 1440, "height": 900})
            _page.on("pageerror", lambda e: _errors.append(str(e)))
            await _page.goto(review_screen.resolve().as_uri())
            await _page.evaluate("localStorage.clear()")
            await _page.reload()
            await _page.wait_for_timeout(1500)

            async def _step(selector: str, wait: int = 900, shot: str = "") -> None:
                await _page.click(selector)
                await _page.wait_for_timeout(wait)
                if shot:
                    await _page.screenshot(path=_shots / shot)

            _doc, _box = ".docs a:has(small:text-matches('^{}'))", "tr.v:has(td:text-is('{}'))"
            await _step(_doc.format("02-enviva-2021-k1.pdf"), 700)
            await _step(_box.format("1"), shot="1-value-linked-to-box.png")  # every value points at its box
            await _step(_box.format("20 *"), shot="2-statement-sent-to-review.png")  # a STMT amount goes to review
            await _step("#otherpage", 1200, "3-attached-statement.png")
            await _step(_doc.format("03-blackstone-2019-k1-scan1a.pdf"), 700)
            await _step(_box.format("16 B"), shot="4-scanned-copy.png")
            await _step("#t-queue", 1200)
            await _page.locator(".item", has=_page.locator(".stmt")).first.scroll_into_view_if_needed()
            await _page.wait_for_timeout(800)
            await _page.screenshot(path=_shots / "5-review-queue.png")
            await _page.check("#showkey")
            await _step("#t-values", 500)
            await _step(_doc.format("03-blackstone-2019-k1-scan2b.pdf"), 700)
            await _step(_box.format("6b"), shot="6-answer-key.png")  # every value against the hand-keyed answer key
            await _browser.close()
        if _errors:
            raise RuntimeError(f"the review screen raised errors: {_errors}")
        print(f"screenshots saved from {review_screen}")
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 12. What didn't work, and what this doesn't show

    **What didn't work.**

    - **Tesseract and rules.** The first versions of this demo read the forms with Tesseract OCR. They straightened
      a scan, lined it up with its blank IRS form, whited out the form's own printing, and OCR'd each box on its
      own. On the held-out set this accepted 182 of 321 boxes, with 2 silent errors, and sent 43% to review.
      Checking Qwen3-VL 235B box by box against Tesseract accepted 236, with no silent errors, and sent 28% to
      review, much of it because Tesseract couldn't read a box the model had read right. Gemini 3.8 Flash on its own
      beats both, so that code was removed. It is in the repository's history, in `extract.py` at commit `0fff276`.
    - **Docling's own OCR as a check on scans.** It picked up 26% of the values on the scanned K-1s.
    - **olmOCR 2** reads the characters well, but it lays a K-1's two columns of boxes out as one HTML table. Once
      the form is text, the box an amount belongs to is easy to lose. The text model put amounts one box off, filed
      coded rows under the wrong box (`20 V` as `13 V`), and missed rows. A vision model reading the image sees the
      grid.
    - **granite-docling can't read these forms.** On most pages Docling gets nothing usable back, and they go to
      review whole. Where it returns text, it often repeats one token until it runs out of output. A repetition
      penalty didn't help, and Docling's own Transformers pipeline on a Modal GPU gave the same result at 257 seconds
      a page.
    - **GLM 5.3 Flash** can fail every attempt on the made-up 1099s, with Pydantic AI's `Exceeded maximum output
      retries`: its answer never fits the schema. When it does answer, it often reads only part of the page. The
      three-quarter page check above was added after it read 4 to 8 values on five summary pages and got past the
      quarter line. And when it's asked which form a scan is, it often names the wrong one, mostly "Form 1065" for a
      made-up 1120-S or 1041. It then reads the page with that form's boxes, and nothing in the review rules notices.
    - **Gemma 4 31B** shifts amounts into neighbouring boxes, misreads names and skips coded rows. It sometimes runs
      out of its 8,000 output tokens. Across runs, between a third and 43% of what it accepted was wrong.

    **What it doesn't show.**

    - **This is not our production extraction**, and a prospect who sends real documents will see different numbers.
    - **The scans are simulated.** Real scans have staples, handwriting, stamps, other scales and colour backgrounds.
    - **The sample is small**: three real K-1s, all Form 1065. There are no real 1120-S, 1041 or brokerage 1099s.
    - **Model answers vary from run to run** at temperature 0, and the open models' answers vary a lot (see the
      README).
    - **A model that skips one section of a 1099 can get through.** The page check catches an answer that skips the
      1099-B rows, or DIV and INT together. It doesn't catch one that skips only DIV (12 values left) or only INT
      (14), and it can't catch values put in the wrong box.
    - **A failed document isn't in the review queue.** In production it would go to a person whole.
    """)
    return


if __name__ == "__main__":
    app.run()
