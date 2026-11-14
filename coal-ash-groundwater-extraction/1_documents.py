import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import hashlib
    import json
    import os
    import random
    import re
    import time
    import urllib.error
    import urllib.parse
    import urllib.request
    from datetime import datetime
    from decimal import Decimal
    from pathlib import Path

    import marimo as mo
    import pdfplumber
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_raw

    HERE = Path(__file__).parent
    # PacifiCorp is the main sample (#188); CCR_UTILITY=aep runs the same steps on AEP's reports (#223), and
    # CCR_UTILITY=aep2022 on three of AEP's newer reports, whose lab pages hold several samples (#275).
    UTILITY = os.environ.get("CCR_UTILITY", "pacificorp")
    assert UTILITY in ("pacificorp", "aep", "aep2022"), f"unknown CCR_UTILITY {UTILITY}"
    OUT = Path(os.environ.get("CCR_OUTPUT_DIR", HERE / "output")) / ("" if UTILITY == "pacificorp" else UTILITY)
    PDFS = OUT / "pdfs"
    PAGES = OUT / "pages"
    SITE = "https://www.pacificorp.com" if UTILITY == "pacificorp" else "https://www.aep.com"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Coal ash groundwater reports: can two models turn them into data you can trust?

    **The question.** Since 2018, every US coal plant with an ash pond or ash landfill has to post an *Annual
    Groundwater Monitoring and Corrective Action Report* on its own website, as a PDF that can run to a thousand
    pages. The measurements inside (arsenic, boron, lithium and so on in each monitoring well, each sampling date)
    are what citizens, reporters and regulators need. The Environmental Integrity Project (EIP) typed the first
    year of them, 443 reports from 265 plants, into a spreadsheet by hand. It was last updated on 2019-04-30. Plants
    have posted a new report every year since.

    Our 990-EZ spike (`scanned-990ez-extraction/`) measured a method on tax forms: two independent vision models read
    every page, any field where they disagree goes to a person, every value keeps its page and box, and the error
    rate is published. This demo runs that method on the coal ash reports and measures **field error, review rate,
    and cost per page**, then estimates what extracting every report since 2018 would cost.

    **The documents.** We use PacifiCorp's reports for its five coal plants in Utah and Wyoming (Dave Johnston,
    Hunter, Huntington, Jim Bridger, Naughton). It lists every report on one page per plant, so the whole set can be
    counted and fetched by a script. The reports are public postings required by 40 CFR 257.107; we download them at
    run time and commit none of them.

    **The answer key.** Each report carries two copies of the same numbers. In the appendix are the laboratory's
    analytical reports, one page per well and sampling date. In the body is the consultant's results table, typed
    from those lab reports into a spreadsheet and printed as a born-digital table we can parse exactly. The models
    read the lab pages; the consultant's table is the key. That is the same set-up as the 990-EZ spike, where IRS
    staff typed the key from the same paper, and like that key it can be wrong, so we check doubtful fields on the
    page. We don't use EIP's database: it covers only the first year, its download needs a release form, and its
    terms bar commercial use.

    The demo is three notebooks, which hand their results on through files in `output/`:

    1. **This one** lists the reports, downloads a sample, finds the lab result pages and parses the answer key.
    2. **`2_extraction.py`** drafts and freezes the schema, then has two vision models read every page.
    3. **`3_results.py`** applies the review rule, scores everything, writes the dataset and sizes the whole job.
    """)
    return


@app.cell
def _():
    def fetch(url: str) -> bytes:
        """GET with three attempts and a browser-like user agent (the site rejects scripts without one)."""
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (fulton-ring ccr spike)"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    return response.read()
            except urllib.error.HTTPError as e:
                if e.code == 404 or attempt == 2:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
            time.sleep(5 * (attempt + 1))
        raise AssertionError("unreachable")

    return (fetch,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Every report the utility lists

    Each plant's compliance page links its CCR units' documents. We keep the links to annual groundwater reports.
    `3_results.py` uses this list to size the whole job.

    PacifiCorp has one page per plant with paths like `.../hunter/ccr-landfill/groundwater/annual...pdf`. AEP
    (the second utility, issue #223) has one page per plant at `aep.com/environment/ccr/<plant>/`, and names
    each report like `NE-LF-GWMonitoringCorrectiveActionRpt-01312021.pdf`: plant code, unit code, posting date.
    """)
    return


@app.cell
def _(fetch):
    all_reports = []
    if UTILITY == "pacificorp":
        PLANTS = ["dave-johnston", "hunter", "huntington", "jim-bridger", "naughton"]
        for _plant in PLANTS:
            _html = fetch(f"{SITE}/environment/environmental-applications-compliance/{_plant}.html").decode(
                "utf-8", "replace"
            )
            for _href in sorted(set(re.findall(r'href="([^"]*/groundwater/annual[^"]*\.pdf)"', _html))):
                _unit = _href.split("/ccr/")[1].split("/")[1]
                _years = re.findall(r"20[12]\d", urllib.parse.unquote(_href.rsplit("/", 1)[1]))
                all_reports.append(
                    {"plant": _plant, "unit": _unit, "url": SITE + _href, "year": _years[0] if _years else ""}
                )
    else:
        _index = fetch(f"{SITE}/environment/ccr").decode("utf-8", "replace")
        PLANTS = sorted(set(re.findall(r'href="/environment/ccr/([a-z]+)/"', _index)))
        for _plant in PLANTS:
            _html = fetch(f"{SITE}/environment/ccr/{_plant}/").decode("utf-8", "replace")
            _links = re.findall(
                r'href="([^"]*/([A-Z]+)-([A-Z0-9-]+)-GWMonitoringCorrectiveActionRpt-(\d+)v?\.pdf)"', _html
            )
            for _href, _code, _unit, _date in sorted(set(_links)):
                _year = _date[4:] if len(_date) == 8 else "20" + _date[4:6]
                all_reports.append({"plant": _plant, "unit": _unit.lower(), "url": SITE + _href, "year": _year})
    assert all_reports, "no report links found; the site layout may have changed"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "all_reports.json").write_text(json.dumps(all_reports, indent=1))
    print(
        f"{len(all_reports)} annual groundwater reports listed for "
        f"{len({(r['plant'], r['unit']) for r in all_reports})} CCR units at {len(PLANTS)} plants"
    )
    return (all_reports,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The sample

    A handful of reports, picked to cover both kinds of lab page we found:

    - **Scanned.** In the 2018 and 2019 Hunter and Huntington reports the lab's pages are images with no text layer:
      the lab's printout was scanned into the PDF.
    - **Born-digital.** From 2020 on, almost every lab page carries a text layer; what's left as images is mostly
      handwritten chain-of-custody forms. A born-digital page can still only be read by a person or a model unless
      someone writes a parser for that lab's layout, so we read those too, rendered as images, and report them apart.

    The file names don't follow one pattern, so the sample is a list of name fragments. Each file's sha256 is logged.

    **AEP.** We looked for a second utility with scanned lab pages and found none we could fetch by script
    (see the README): in AEP's, Alabama Power's and Georgia Power's reports the scans are custody forms and
    field sheets, and the lab pages are born-digital. Duke Energy's and TVA's sites refuse scripted requests.
    Most AEP reports leave the lab reports out; Northeastern (Oklahoma) and Welsh (Texas) include them. The AEP
    sample is four of those, covering two labs: AEP's Shreveport lab (2016 to 2019 samples) and AEP's Dolan lab
    (2020 samples, metals in µg/L).

    **AEP from 2022 on** (`CCR_UTILITY=aep2022`, issue #275). Three Northeastern reports posted in 2023 and
    2024 (landfill 2023 and 2024, bottom ash pond 2023), whose Dolan lab pages often print two or three samples a
    page. Only `4_multi_sample.py` reads them; this notebook downloads them and parses their answer key.
    """)
    return


@app.cell
def _(all_reports, fetch):
    SAMPLE = {
        "pacificorp": [
            "hunter/ccr-landfill/groundwater/annual-reports/2018",
            "hunter/ccr-landfill/groundwater/annual-reports/2019",
            "huntington/ccr-landfill/groundwater/annual-monitoring-corrective-action/2018",
            "huntington/ccr-landfill/groundwater/annual-monitoring-corrective-action/2019",
            "dave-johnston/ash-pond/groundwater/annual-reports/2022",
            "jim-bridger/landfill/groundwater/annual-groundwater-reports/2021",
            "naughton/fgd-pond-2/groundwater/annual-groundwater-reports/2022",
        ],
        "aep": [
            "NE-LF-GWMonitoringCorrectiveActionRpt-031220.pdf",
            "NE-BAP-GWMonitoringCorrectiveActionRpt-031320.pdf",
            "NE-BAP-GWMonitoringCorrectiveActionRpt-01312021.pdf",
            "WH-BASP-GWMonitoringCorrectiveActionRpt-013120.pdf",
        ],
        "aep2022": [
            "NE-LF-GWMonitoringCorrectiveActionRpt-01312023.pdf",
            "NE-LF-GWMonitoringCorrectiveActionRpt-01312024.pdf",
            "NE-BAP-GWMonitoringCorrectiveActionRpt-01312023.pdf",
        ],
    }[UTILITY]
    reports = []
    for _fragment in SAMPLE:
        _matches = [r for r in all_reports if _fragment in r["url"]]
        assert len(_matches) == 1, f"{_fragment} matches {len(_matches)} reports"
        _r = dict(_matches[0])
        _r["id"] = f"{_r['plant']}_{_r['unit']}_{_r['year']}"
        _path = PDFS / f"{_r['id']}.pdf"
        if not _path.exists():
            PDFS.mkdir(parents=True, exist_ok=True)
            _path.write_bytes(fetch(_r["url"]))
        _r["sha256"] = hashlib.sha256(_path.read_bytes()).hexdigest()
        _r["pages"] = len(pdfium.PdfDocument(_path))
        reports.append(_r)
        print(f"{_r['id']}: {_r['pages']} pages, sha256 {_r['sha256'][:16]}")
    return (reports,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Finding the lab result pages

    A report is mostly narrative, maps, statistics, field sheets, custody forms and quality-control pages. We want
    the pages where a lab reports one sample's results. First we sort every page into one of two kinds:

    - **scanned**: one picture covers most of the page. Some of these carry a text layer that someone added with
      OCR, full of misreads such as `HLF-lN` for `HLF-1N`, so a text layer doesn't make a page born-digital;
    - **born-digital**: everything else.

    A page is a candidate if its text names a client sample and at least three CCR constituents, and isn't the
    consultant's results table. A scanned page with no text layer at all is always a candidate: only a model can
    tell a lab page from a custody form there, so both models also say whether it is a lab result page.

    We read every scanned candidate and a seeded random 15 born-digital candidates per report (25 for AEP, whose
    lab pages are all born-digital), to keep within the budget.
    """)
    return


@app.cell
def _(reports):
    ANALYTES = [
        "Antimony",
        "Arsenic",
        "Barium",
        "Beryllium",
        "Boron",
        "Cadmium",
        "Calcium",
        "Chloride",
        "Chromium",
        "Cobalt",
        "Fluoride",
        "Lead",
        "Lithium",
        "Mercury",
        "Molybdenum",
        "Selenium",
        "Sulfate",
        "Thallium",
    ]
    BORN_DIGITAL_PER_REPORT, SEED = {"pacificorp": 15, "aep": 25, "aep2022": 25}[UTILITY], 2018
    # AEP's Dolan lab prints "Sample Number" where the others print "Sample ID".
    SAMPLE_WORDS = ("Sample ID",) if UTILITY == "pacificorp" else ("Sample ID", "Sample Number")

    def picture_share(page: pdfium.PdfPage) -> float:
        """The largest share of the page covered by one image."""
        width, height = page.get_size()
        shares = [0.0]
        for image in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE], max_depth=2):
            left, bottom, right, top = image.get_bounds()
            shares.append((right - left) * (top - bottom) / (width * height))
        return max(shares)

    pages = []
    for _r in reports:
        _doc = pdfium.PdfDocument(PDFS / f"{_r['id']}.pdf")
        _scanned, _digital = [], []
        for _i in range(len(_doc)):
            _text = _doc[_i].get_textpage().get_text_range()
            _is_scan = picture_share(_doc[_i]) > 0.5
            _lab_text = (
                any(w in _text for w in SAMPLE_WORDS)
                and sum(a in _text for a in ANALYTES) >= 3
                and "COLLECTION DATE" not in _text
            )
            if _is_scan and (_lab_text or len(_text.strip()) < 50):
                _scanned.append(_i)
            elif not _is_scan and _lab_text:
                _digital.append(_i)
        _picked = sorted(
            random.Random(f"{SEED}-{_r['id']}").sample(_digital, min(len(_digital), BORN_DIGITAL_PER_REPORT))
        )
        _r.update(scanned_candidates=len(_scanned), born_digital_candidates=len(_digital))
        for _i in _scanned + _picked:
            _key = f"{_r['id']}_p{_i + 1:04d}"
            _png = PAGES / f"{_key}.png"
            if not _png.exists():
                PAGES.mkdir(parents=True, exist_ok=True)
                _doc[_i].render(scale=150 / 72).to_pil().convert("L").save(_png)
            _kind = "scanned" if _i in _scanned else "born-digital"
            pages.append({"key": _key, "report": _r["id"], "page": _i + 1, "kind": _kind})
        print(f"{_r['id']}: {len(_scanned)} scanned candidates, {len(_digital)} born-digital, {len(_picked)} picked")
    print(
        f"{len(pages)} pages to read: {sum(p['kind'] == 'scanned' for p in pages)} scanned, "
        f"{sum(p['kind'] == 'born-digital' for p in pages)} born-digital"
    )
    return (pages,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The answer key: each report's results table

    The consultant's table lists every well, every sampling date since 2015 and every Appendix III and IV
    constituent, with the data-validation qualifier beside each value. It is born-digital, so `pdfplumber` reads its
    cells exactly. The one hard part is the well name, which is printed once per block of rows, centred, so it can
    land on any row of its block. We split the rows into blocks wherever the date goes back in time (each well's
    history starts again in 2015), and give a block its one well name. A block with no name or two names (where a
    replacement well such as `DJ-37R` carries on from `DJ-37`) is dropped from the key rather than guessed. Radium
    is left out too: the table combines radium-226 and -228, and the lab pages report them apart.
    """)
    return


@app.cell
def _(reports):
    SYMBOLS = {
        "B": "boron",
        "Ca": "calcium",
        "Cl": "chloride",
        "F": "fluoride",
        "pH": "ph",
        "SO4": "sulfate",
        "TDS": "tds",
        "Sb": "antimony",
        "As": "arsenic",
        "Ba": "barium",
        "Be": "beryllium",
        "Cd": "cadmium",
        "Cr": "chromium",
        "Co": "cobalt",
        "Pb": "lead",
        "Li": "lithium",
        "Hg": "mercury",
        "Mo": "molybdenum",
        "Se": "selenium",
        "Tl": "thallium",
    }

    def squash(cell: str | None) -> str:
        return re.sub(r"\s+", "", cell or "").translate(str.maketrans("\u2010\u2011\u2012\u2013", "----"))

    key_wet, wells_wet = [], {}
    for _r in reports if UTILITY == "pacificorp" else []:
        _rows = []
        with pdfplumber.open(PDFS / f"{_r['id']}.pdf") as _pdf:
            for _pno, _page in enumerate(_pdf.pages[:150]):
                _text = _page.extract_text() or ""
                if "SAMPLE ID" not in _text or "COLLECTION DATE" not in _text.upper():
                    continue
                for _table in _page.extract_tables():
                    _head = next(
                        (i for i, row in enumerate(_table) if row and squash(row[0]).upper() == "SAMPLEID"), None
                    )
                    if _head is None:
                        continue
                    _cols = [squash(c) for c in _table[_head]]
                    _date_col = [c.upper() for c in _cols].index("COLLECTIONDATE")
                    _analytes = {j: SYMBOLS[c] for j, c in enumerate(_cols) if c in SYMBOLS}
                    for _row in _table[_head + 1 :]:
                        _date = squash(_row[_date_col])
                        if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", _date):
                            continue
                        _when = datetime.strptime(_date, "%m/%d/%Y").date()
                        _values = {
                            a: (squash(_row[j]), squash(_row[j + 1]) if j + 1 < len(_row) else "")
                            for j, a in _analytes.items()
                            if j < len(_row)
                        }
                        _rows.append(
                            {"table_page": _pno + 1, "name": squash(_row[0]), "date": _when, "values": _values}
                        )
        _blocks: list[list[dict]] = []
        for _row in _rows:
            if not _blocks or _row["date"] < _blocks[-1][-1]["date"]:
                _blocks.append([])
            _blocks[-1].append(_row)
        wells_wet[_r["id"]] = sorted({str(row["name"]) for row in _rows if row["name"]})
        _dropped = 0
        for _block in _blocks:
            _names = [row["name"] for row in _block if row["name"]]
            if len(_names) != 1:
                _dropped += len(_block)
                continue
            for _row in _block:
                for _analyte, (_value, _q) in _row["values"].items():
                    if _value and not _value.startswith(("NS", "NM")):
                        key_wet.append(
                            {
                                "report": _r["id"],
                                "table_page": _row["table_page"],
                                "well": _names[0],
                                "date": _row["date"].isoformat(),
                                "analyte": _analyte,
                                "value": _value,
                                "qualifier": _q,
                            }
                        )
        _n = [k for k in key_wet if k["report"] == _r["id"]]
        print(
            f"{_r['id']}: {len(_n)} values in {len({(k['well'], k['date']) for k in _n})} samples; "
            f"{_dropped} of {len(_rows)} rows dropped (ambiguous well); {len(wells_wet[_r['id']])} wells"
        )
    return key_wet, squash, wells_wet


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### AEP's tables (Geosyntec)

    AEP's consultant prints one table per well, with the well in the title (`Table 1 - Groundwater Data Summary:
    MW-3D`), a units row under the header, and the qualifier in the same cell as the value (`2.12 J`, `< 0.02 U`).
    So the parser is different: the well comes from the title, the value and qualifier are split, and metals
    printed in µg/L are converted to mg/L, the unit the labs print. Everything after this cell is shared.
    """)
    return


@app.cell
def _(reports, squash):
    NAMES = {
        "boron": "boron",
        "calcium": "calcium",
        "chloride": "chloride",
        "fluoride": "fluoride",
        "ph": "ph",
        "sulfate": "sulfate",
        "totaldissolvedsolids": "tds",
        "antimony": "antimony",
        "arsenic": "arsenic",
        "barium": "barium",
        "beryllium": "beryllium",
        "cadmium": "cadmium",
        "chromium": "chromium",
        "cobalt": "cobalt",
        "lead": "lead",
        "lithium": "lithium",
        "mercury": "mercury",
        "molybdenum": "molybdenum",
        "selenium": "selenium",
        "thallium": "thallium",
    }
    key_geosyntec, wells_geosyntec = [], {}
    for _r in reports if UTILITY != "pacificorp" else []:
        _n0 = len(key_geosyntec)
        wells_geosyntec[_r["id"]] = set()
        with pdfplumber.open(PDFS / f"{_r['id']}.pdf") as _pdf:
            for _pno, _page in enumerate(_pdf.pages[:150]):
                _title = re.search(r"Groundwater Data Summary:\s*(\S+)", _page.extract_text() or "")
                if not _title:
                    continue
                _well = squash(_title.group(1))
                wells_geosyntec[_r["id"]].add(_well)
                for _table in _page.extract_tables():
                    _head = next((i for i, row in enumerate(_table) if squash(row[0]) == "CollectionDate"), None)
                    if _head is None:
                        continue
                    _cols = {j: NAMES.get(squash(c).lower()) for j, c in enumerate(_table[_head])}
                    _units = [squash(u) for u in _table[_head + 1]]
                    for _row in _table[_head + 2 :]:
                        _date = squash(_row[0])
                        if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", _date):
                            continue
                        for _j, _analyte in _cols.items():
                            _cell = re.fullmatch(r"(<?)([\d.,]+)([A-Z*]*)", squash(_row[_j]))
                            if _analyte is None or _cell is None:
                                continue
                            _value = _cell.group(2).replace(",", "")
                            if _units[_j] in ("µg/L", "ug/L"):
                                _value = str(Decimal(_value) / 1000)
                            key_geosyntec.append(
                                {
                                    "report": _r["id"],
                                    "table_page": _pno + 1,
                                    "well": _well,
                                    "date": datetime.strptime(_date, "%m/%d/%Y").date().isoformat(),
                                    "analyte": _analyte,
                                    "value": _cell.group(1) + _value,
                                    "qualifier": _cell.group(3),
                                }
                            )
        _n = key_geosyntec[_n0:]
        print(
            f"{_r['id']}: {len(_n)} values in {len({(k['well'], k['date']) for k in _n})} samples; "
            f"{len(wells_geosyntec[_r['id']])} wells"
        )
    return key_geosyntec, wells_geosyntec


@app.cell
def _(key_geosyntec, key_wet, pages, reports, wells_geosyntec, wells_wet):
    key = key_wet + key_geosyntec
    for _r in reports:
        # The report's own well list, used by the page-level well check in 3_results.py.
        _r["wells"] = sorted(wells_wet.get(_r["id"], []) or wells_geosyntec.get(_r["id"], []))
    (OUT / "reports.json").write_text(json.dumps(reports, indent=1))
    (OUT / "pages.json").write_text(json.dumps(pages, indent=1))
    (OUT / "key.json").write_text(json.dumps(key, indent=1))
    print(f"wrote {len(reports)} reports, {len(pages)} pages and {len(key)} answer-key values to {OUT}")
    return


if __name__ == "__main__":
    app.run()
