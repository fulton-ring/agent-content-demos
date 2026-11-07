import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import hashlib
    import io
    import os
    import urllib.request
    from pathlib import Path

    import marimo as mo
    import pandas as pd

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("VA_OUTPUT_DIR", HERE / "output"))
    # The Better Data Center Project CSV, pinned to the commit we score against (2026-03-04).
    CSV_COMMIT = "9a494e26fe09f59bad0ad02549934bc8b1fbce6d"
    CSV_URL = f"https://raw.githubusercontent.com/jsbangsund/data-center-generator-permits/{CSV_COMMIT}/data/air_permits_VA.csv"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Can a vision model rebuild Virginia's data-center generator dataset from the air permits?

    **The question.** The Better Data Center Project read Virginia DEQ's air permits for data centers by hand and
    published one CSV of generator rows, current through 12/31/2025 (CC-BY-4.0, by John Bangsund and Catherine
    Casomar). Can our extraction pipeline read the same permits as accurately, and then extend the file with the
    permits DEQ issued in 2026?

    **This notebook** loads that CSV, the answer key, and says which of its fields we score and why.
    """)
    return


@app.cell
def _():
    with urllib.request.urlopen(CSV_URL, timeout=60) as response:
        assert response.status == 200, f"CSV download failed: HTTP {response.status}"
        raw = response.read()
    print(f"CSV {len(raw):,} bytes, sha256 {hashlib.sha256(raw).hexdigest()[:16]}")
    # Row 1 holds the authors' running totals (10,684 units, 27,407 MW); the header is row 2.
    key = pd.read_csv(io.BytesIO(raw), skiprows=1, dtype=str, keep_default_na=False)
    key = key.loc[:, [c for c in key.columns if not c.startswith("Unnamed")]]
    assert len(key) == 821, f"expected 821 equipment rows, got {len(key)}"
    print(f"{len(key)} equipment rows, {key['reg_no'].nunique()} permit registrations, {len(key.columns)} columns")
    return (key,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What we score

    The issue names the fields printed in the permit: unit count, kWe, make, model, NOx, PM and operating hours.
    NOx and PM appear twice in the CSV, as g/kWh and lb/hr; both are printed limits, so we score both.
    Tier is out of scope: the authors call it a "best guess" from limits, dates and controls, not a printed value.
    """)
    return


@app.cell
def _(key):
    scored = [
        "quantity",
        "capacity_kWe",
        "manufacturer",
        "model",
        "NOx_g_per_kWh",
        "NOx_lb_per_hr",
        "PM_g_per_kWh",
        "PM_lb_per_hr",
        "operating_hr_per_year",
    ]
    fill = pd.DataFrame(
        {
            "filled": [(key[c].str.strip() != "").sum() for c in scored],
            "blank": [(key[c].str.strip() == "").sum() for c in scored],
        },
        index=scored,
    )
    print(fill.to_string())
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The key isn't ground truth

    The authors flag 51 rows in `possible_issues`. Every disagreement between our reading and the CSV gets checked
    against the PDF, and these flags tell us where to expect the CSV to be unsure.
    """)
    return


@app.cell
def _(key):
    flagged = key[key["possible_issues"].str.strip() != ""]
    print(f"{len(flagged)} rows flagged, across {flagged['reg_no'].nunique()} permits")
    print(flagged["possible_issues"].str.slice(0, 100).value_counts().head(8).to_string())
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Permit age

    Accuracy is split by when the permit document was issued, since 20 years of DEQ templates differ.
    """)
    return


@app.cell
def _(key):
    year = pd.to_datetime(key["latest_permit_date"], format="%m/%d/%Y").dt.year
    bands = ["2000-2014", "2015-2019", "2020-2022", "2023-2025"]
    band = pd.cut(year, bins=[1999, 2014, 2019, 2022, 2025], labels=bands)
    by_band = (
        key.assign(band=band).groupby("band", observed=True).agg(rows=("reg_no", "size"), permits=("reg_no", "nunique"))
    )
    OUT.mkdir(parents=True, exist_ok=True)
    key.to_csv(OUT / "answer_key.csv", index=False)
    print(by_band.to_string())
    return


if __name__ == "__main__":
    app.run()
