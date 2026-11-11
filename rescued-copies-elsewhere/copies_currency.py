import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # Can you tell whether a rescued copy is still current, from the copy alone?

    When an agency's portal goes dark, people keep using the rescued copies. The obvious way to check one is to
    compare it with the live original. That's exactly what you can't do once the original is gone. So the check has
    to run on signals that outlive the portal, and the copy has to carry enough metadata to run them.

    Two earlier spikes did the hard part on our own copies. `rescued-data-currency/` dated 25 copies of 20 federal
    climate datasets. `hifld-next-layer-currency/` dated all 330 HIFLD Next layers, and for 73 of them checked by
    hand whether the source agency had published something newer. This notebook asks two new questions:

    1. **What metadata did the rescue keep?** For 20 HIFLD layers, compare what the original data.gov record said
       with what the Data Rescue Project deposit on DataLumos and the HIFLD Next copy say.
    2. **Does the check carry over?** Run the same six-point checklist on copies held by others (DataLumos, Source
       Cooperative, Harvard's data.gov archive) and record which checks the copy alone can answer.

    Everything is read from public APIs at run time. Nothing is committed but the code and its outputs.
    """)
    return (mo,)


@app.cell
def _():
    import io
    import json
    import os
    import random
    import re
    import time
    import zipfile
    from collections import Counter
    from pathlib import Path

    import pandas as pd
    import requests

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("OUTPUT_DIR", HERE / "outputs"))
    OUT.mkdir(parents=True, exist_ok=True)
    HIFLD = os.environ.get("HIFLD_BASE_URL", "https://hifld.publicenvirodata.org")
    LAYER_CURRENCY_URL = os.environ.get(
        "LAYER_CURRENCY_URL",
        "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/main/"
        "hifld-next-layer-currency/outputs/layer_currency.csv",
    )
    HARVARD = os.environ.get("HARVARD_BASE_URL", "https://data.source.coop/harvard-lil/gov-data")
    DATACITE = os.environ.get("DATACITE_BASE_URL", "https://api.datacite.org")
    SOURCE_COOP = os.environ.get("SOURCE_COOP_BASE_URL", "https://source.coop")
    SEED = 206
    HIFLD_SAMPLE = 20
    PER_HOLDER = 6
    MAX_PAGES = 100
    MAX_DRAWS = 300
    STARTED = time.time()
    return (
        Counter,
        DATACITE,
        HARVARD,
        HIFLD,
        HIFLD_SAMPLE,
        LAYER_CURRENCY_URL,
        MAX_DRAWS,
        MAX_PAGES,
        OUT,
        PER_HOLDER,
        SEED,
        SOURCE_COOP,
        STARTED,
        io,
        json,
        pd,
        random,
        re,
        requests,
        time,
        zipfile,
    )


@app.cell
def _(requests, time):
    HEADERS = {"User-Agent": "rescued-copies-elsewhere/0.1 (+https://github.com/fulton-ring/agent-content-demos)"}
    MAX_TRIES = 3

    def get(url: str, params: dict | None = None) -> requests.Response:
        """GET with a fixed number of retries; raises on the last failure."""
        for attempt in range(1, MAX_TRIES + 1):
            try:
                response = requests.get(url, params=params, headers=HEADERS, timeout=90)
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt == MAX_TRIES:
                    raise
                time.sleep(2**attempt)
        raise AssertionError("unreachable")

    def probe(url: str) -> int:
        """HTTP status a script gets from a URL, or 0 if it can't connect. Never raises."""
        try:
            with requests.get(url, headers=HEADERS, timeout=30, stream=True, allow_redirects=True) as response:
                return response.status_code
        except requests.RequestException:
            return 0

    return get, probe


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## The checklist

    Six checks, each one a question a user can ask of any copy. For each copy and check we record whether the
    copy's **own structured metadata** answers it (`copy`), whether a person has to dig for it, by reading a README
    or description, downloading the files, or finding the publisher themselves (`hand`), or whether it can't be
    answered at all (`no`).

    | # | check | `copy` when the copy's metadata has... |
    |---|---|---|
    | 1 | upstream still publishing | a source URL in a field, and that URL still answers |
    | 2 | newest record date | a temporal-coverage field, or open files with declared date columns |
    | 3 | record count | a record or feature count |
    | 4 | source last-modified | the source's own last-modified date (not the copy's) |
    | 5 | update cadence | an update-frequency field |
    | 6 | vintage label | both the capture date and the source's date, so the copy says *as of when* |

    Check 1 is `no` when an earlier check established that no current public source exists (from #171).

    A copy's **currency can be checked from the copy** when checks 1 and 4 are both `copy`: you can fetch the
    source and compare its date with the date the copy recorded, with no person in the loop. It **can't be
    checked** when there is no upstream left, so the copy is a fixed snapshot. Everything else is **by hand**.

    "Structured" means a named field in the holder's API: STAC for HIFLD Next, DataCite for DataLumos (the DOI
    metadata DataLumos publishes), CKAN/DCAT-US for the data.gov record Harvard archived, and the product API for
    Source Cooperative. Text in a description or README counts only as `hand`, because a person has to read it.
    """)
    return


@app.cell
def _(re):
    URL = re.compile(r"https?://[^\s\"'<>)\]]+")
    DATE = re.compile(
        r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b|"
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (?:\d{1,2}, )?(?:19|20)\d{2}\b"
    )
    CADENCE = re.compile(
        r"(?i)\b(daily|weekly|monthly|quarterly|annual(?:ly)?|yearly|every \w+ (?:days|months|years))\b"
    )
    COUNT = re.compile(r"(?i)\b\d[\d,]{2,} (?:records|features|rows|facilities|structures|polygons|sites|points)\b")
    HOLDER_DOMAINS = ("datalumos.org", "source.coop", "publicenvirodata.org", "nrp-nautilus.io", "colab.research")

    def text_urls(text: str) -> list[str]:
        return [u.rstrip(".,;") for u in URL.findall(text) if not any(d in u for d in HOLDER_DOMAINS)]

    return CADENCE, COUNT, DATE, text_urls


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## The inputs

    - **#171's results**: `layer_currency.csv` from `main`, one row per HIFLD Next layer. For 73 layers it says
      whether the source agency still publishes the data (`by_vintage`).
    - **HIFLD Next's STAC catalog**: one collection per file and version; we keep the newest version per layer.
      Each links to the DataLumos deposit it was built from (`derived_from`).
    - **Harvard's data.gov archive** on Source Cooperative: `metadata.csv.zip` lists every data.gov record
      Harvard's Library Innovation Lab saved between November 2024 and February 2025, before HIFLD Open shut down
      on 26 August 2025. It is the archived original metadata for HIFLD layers that data.gov listed.
    """)
    return


@app.cell
def _(HARVARD, HIFLD, LAYER_CURRENCY_URL, MAX_PAGES, get, io, pd, zipfile):
    layers = pd.read_csv(io.StringIO(get(LAYER_CURRENCY_URL).text), dtype=str).fillna("")

    _url = f"{HIFLD}/stac/collections?limit=100"
    _collections = []
    for _page in range(MAX_PAGES):
        _body = get(_url).json()
        _collections += _body["collections"]
        _next = [link["href"] for link in _body["links"] if link["rel"] == "next"]
        if not _next:
            break
        _url = _next[0]
    else:
        raise RuntimeError(f"STAC catalog still paging after {MAX_PAGES} pages")

    def version_key(collection_id: str) -> tuple[int, ...]:
        return tuple(int(part) for part in collection_id.rsplit("/v", 1)[1].split("."))

    stac_by_layer = {}
    for _c in sorted(_collections, key=lambda c: version_key(c["id"])):
        stac_by_layer.setdefault(_c["id"].split("/")[1], {})[_c["id"].split("/")[2]] = _c

    with zipfile.ZipFile(io.BytesIO(get(f"{HARVARD}/metadata.csv.zip").content)) as _zip:
        harvard_index = pd.read_csv(_zip.open("metadata.csv"), dtype=str).fillna("")

    print(
        f"#171 layers: {len(layers)}; STAC collections: {len(_collections)} in {len(stac_by_layer)} layers; "
        f"Harvard data.gov records: {len(harvard_index)}"
    )
    return harvard_index, layers, stac_by_layer


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Part 1: what the HIFLD rescue kept

    We want layers where two things are known: whether the source still publishes (so check 1 has a true answer)
    and what the original metadata said. So the sample is drawn from the 73 layers #171 checked by hand, keeping
    those whose title matches a Department of Homeland Security record in Harvard's data.gov archive, then 20 of
    them at random with seed 206.
    """)
    return


@app.cell
def _(HIFLD_SAMPLE, SEED, harvard_index, layers, random, re):
    def norm(title: str) -> str:
        return re.sub(r"[^a-z0-9]", "", title.lower())

    _dhs = harvard_index[harvard_index["organization"].str.contains("Homeland Security")]
    harvard_by_title = {norm(t): p for t, p in zip(_dhs["title"], _dhs["metadata_path"], strict=True)}
    _all_matched = layers[layers["title"].map(norm).isin(harvard_by_title.keys())]
    _checked = layers[layers["by_vintage"] != ""]
    _eligible = _checked[_checked["title"].map(norm).isin(harvard_by_title.keys())]
    hifld_sample = _eligible.sample(n=HIFLD_SAMPLE, random_state=SEED).sort_values("layer").reset_index(drop=True)
    match_stats = {
        "layers": len(layers),
        "layers_with_archived_datagov_record": len(_all_matched),
        "checked_in_171": len(_checked),
        "checked_with_archived_record": len(_eligible),
    }
    print(match_stats)
    hifld_sample[["layer", "title", "agency", "by_vintage"]]
    return harvard_by_title, hifld_sample, match_stats, norm


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    For each sampled layer we read three metadata records:

    - **the original**: the data.gov record (DCAT-US fields as harvested from DHS) inside Harvard's bag;
    - **the Data Rescue Project deposit**: the DataCite record of the DataLumos project HIFLD Next links to;
    - **the HIFLD Next copy**: its STAC collection.

    and pull six fields from each: the source's issued date, its modified date, a source URL, a record count, a
    checksum, and a changelog or version label.
    """)
    return


@app.cell
def _(DATACITE, HARVARD, get, hifld_sample, json, stac_by_layer):
    def datacite(doi: str) -> dict:
        return get(f"{DATACITE}/dois/{doi}").json()["data"]["attributes"]

    def harvard_record(path: str) -> dict:
        return json.loads(get(f"{HARVARD}/{path}").content)

    def main_collection(layer: str) -> dict:
        files = stac_by_layer[layer]
        return files.get(layer) or next(iter(files.values()))

    def deposit_doi(collection: dict) -> str | None:
        hrefs = [link["href"] for link in collection["links"] if link["rel"] == "derived_from"]
        project = [h.split("/project/")[1].split("/")[0] for h in hrefs if "datalumos.org" in h]
        return f"10.3886/E{project[0]}V1" if project else None

    return datacite, deposit_doi, harvard_record, main_collection


@app.cell
def _(
    datacite,
    deposit_doi,
    harvard_by_title,
    harvard_record,
    hifld_sample,
    main_collection,
    norm,
):
    def dcat_extras(record: dict) -> dict:
        return {e["key"]: e["value"] for e in record["signed_metadata"]["data_gov_metadata"].get("extras", [])}

    def original_fields(record: dict) -> dict:
        ckan = record["signed_metadata"]["data_gov_metadata"]
        extras = dcat_extras(record)
        urls = [ckan.get("url"), extras.get("landingPage")] + [r.get("url") for r in ckan.get("resources", [])]
        return {
            "issued": extras.get("issued"),
            "modified": extras.get("modified"),
            "source URL": next((u for u in urls if u), None),
            "record count": None,
            "checksum": None,
            "changelog or version": ckan.get("version"),
        }

    def deposit_fields(attrs: dict) -> dict:
        dates = {d["dateType"]: d["date"] for d in attrs.get("dates", [])}
        related = [
            r["relatedIdentifier"]
            for r in attrs.get("relatedIdentifiers", [])
            if r.get("relatedIdentifierType") == "URL"
        ]
        return {
            # DataCite's "Issued" is the deposit's own year; the source's date, when kept, is the "Collected" date.
            "issued": None,
            "modified": (dates.get("Collected") or "").split("/")[-1] or None,
            "source URL": related[0] if related else None,
            "record count": attrs.get("sizes") or None,
            "checksum": None,
            "changelog or version": attrs.get("version"),
        }

    def stac_fields(c: dict) -> dict:
        dates = c.get("hifld:source_dates", {})
        checksums = [a.get("file:checksum") for a in c.get("assets", {}).values() if a.get("file:checksum")]
        return {
            "issued": dates.get("issued"),
            "modified": dates.get("modified"),
            "source URL": None,
            "record count": c.get("hifld:feature_count"),
            "checksum": checksums[0] if checksums else None,
            "changelog or version": c.get("hifld:source_version_description") or c["id"].rsplit("/", 1)[1],
        }

    hifld_records = []
    for _row in hifld_sample.itertuples():
        _collection = main_collection(_row.layer)
        _doi = deposit_doi(_collection)
        hifld_records.append(
            {
                "layer": _row.layer,
                "by_vintage": _row.by_vintage,
                "harvard": harvard_record(harvard_by_title[norm(_row.title)]),
                "doi": _doi,
                "deposit": datacite(_doi) if _doi else None,
                "stac": _collection,
            }
        )
    print(f"read {len(hifld_records)} layers: {sum(r['deposit'] is not None for r in hifld_records)} with a deposit")
    return dcat_extras, deposit_fields, hifld_records, original_fields, stac_fields


@app.cell
def _(Counter, deposit_fields, hifld_records, original_fields, pd, stac_fields):
    FIELDS = ["issued", "modified", "source URL", "record count", "checksum", "changelog or version"]

    def compare(original: object, copy: object, is_date: bool) -> str:
        if original and copy:
            same = str(original)[:10] == str(copy)[:10] if is_date else True
            return "kept" if same else "changed"
        if original:
            return "lost"
        return "added" if copy else "in neither"

    _rows = []
    for _r in hifld_records:
        _orig = original_fields(_r["harvard"])
        _dep = deposit_fields(_r["deposit"]) if _r["deposit"] else dict.fromkeys(FIELDS)
        _stac = stac_fields(_r["stac"])
        for _f in FIELDS:
            _is_date = _f in ("issued", "modified")
            _rows.append(
                {
                    "layer": _r["layer"],
                    "field": _f,
                    "original": _orig[_f],
                    "DataLumos deposit": _dep[_f],
                    "HIFLD Next": _stac[_f],
                    "deposit vs original": compare(_orig[_f], _dep[_f], _is_date),
                    "HIFLD Next vs original": compare(_orig[_f], _stac[_f], _is_date),
                }
            )
    field_detail = pd.DataFrame(_rows)

    def tally(column: str) -> pd.DataFrame:
        counts = {f: Counter(field_detail.loc[field_detail["field"] == f, column]) for f in FIELDS}
        return pd.DataFrame(counts).T.fillna(0).astype(int)

    _original_has = (
        field_detail.assign(has=field_detail["deposit vs original"].isin(["kept", "changed", "lost"]))
        .groupby("field", sort=False)["has"]
        .sum()
    )
    _dates = field_detail[field_detail["field"] == "modified"]
    _both = _dates["DataLumos deposit"].notna() & _dates["HIFLD Next"].notna()
    copies_agree_on_date = {
        "both_have_a_source_date": int(_both.sum()),
        "same_date": int(
            (_dates["DataLumos deposit"].astype(str).str[:10] == _dates["HIFLD Next"].astype(str).str[:10]).sum()
        ),
        "original_distinct_modified_dates": int(_dates["original"].astype(str).str[:10].nunique()),
    }
    print(copies_agree_on_date)
    field_table = (
        pd.concat(
            [
                _original_has.rename("original has it"),
                tally("deposit vs original").add_prefix("DataLumos: "),
                tally("HIFLD Next vs original").add_prefix("HIFLD Next: "),
            ],
            axis=1,
        )
        .fillna(0)
        .astype(int)
    )
    field_table
    return FIELDS, copies_agree_on_date, field_detail, field_table


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Read the table per field across the 20 layers: how many original records had the field, then for each copy
    how many kept it (same value), changed it, lost it, or added it where the original had nothing. `in neither`
    means neither record had it. The full values are in `outputs/hifld_fields.csv`.

    **What it shows.** The rescue lost nothing, because the original data.gov records had almost nothing to lose:
    no source URL, no issued date, no record count, no checksum. Their one date, `modified`, is the moment DHS's
    catalog was harvested into data.gov, the same day for every layer (see `original_distinct_modified_dates`
    above), so it says nothing about the data. The copies *added* what currency checks need. HIFLD Next took the
    source's issued and modified dates from HIFLD's own inventory and added feature counts, file checksums and a
    version number. The DataLumos deposit kept a date in DataCite's `Collected` field (we count it as the
    deposit's source date) and a version number.

    **But the two copies disagree on the source's date** for most layers (`same_date` above). The depositor and
    the HIFLD inventory recorded different dates for the same data, and neither says which date it means. Neither
    copy keeps a link to the agency's own page, so check 1 has to start from scratch.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Part 2: copies held by others

    Six copies per holder:

    - **DataLumos**: seeded random draws (seed 206) of project numbers between the first 2025 deposit and the
      newest, keeping deposits that exist and aren't HIFLD Open layers (those are Part 1). Read through DataCite.
    - **Harvard's data.gov archive**: six records drawn with seed 206 from all 311,000-odd in `metadata.csv`.
    - **Source Cooperative**: it has no public listing API we could find, so six US federal mirrors found with the
      site's own search ("HIFLD", "federal", "census", "USGS"): the SeerAI HIFLD archive, CEJST (taken offline in
      January 2025), CDC's Social Vulnerability Index, PAD-US 3.0, the National Wetlands Inventory and USGS's
      Watershed Boundary Dataset. Read through the product API and each README.

    Plus the 20 HIFLD Next copies from Part 1, scored the same way.
    """)
    return


@app.cell
def _(DATACITE, MAX_DRAWS, PER_HOLDER, SEED, datacite, get, random, re, requests):
    def first_2025_project(sort: str) -> int:
        body = get(
            f"{DATACITE}/dois",
            params={
                "query": "url:*datalumos* AND created:[2025-01-01 TO *]",
                "sort": sort,
                "page[size]": 200,
                "fields[dois]": "created",
            },
        ).json()
        ids = [int(m.group(1)) for d in body["data"] if (m := re.fullmatch(r"10\.3886/e(\d+)v1", d["id"]))]
        assert ids, f"no plain DataLumos deposit DOIs in the first page sorted by {sort}"
        return ids[0]

    _low, _high = first_2025_project("created"), first_2025_project("-created")
    _rng = random.Random(SEED)
    datalumos_copies = []
    _draws = 0
    for _draws in range(1, MAX_DRAWS + 1):
        _doi = f"10.3886/E{_rng.randint(_low, _high)}V1"
        try:
            _attrs = datacite(_doi)
        except requests.HTTPError:
            continue
        if any(s.get("subject") == "HIFLD Open" for s in _attrs.get("subjects", [])):
            continue
        datalumos_copies.append({"doi": _doi, "attrs": _attrs})
        if len(datalumos_copies) == PER_HOLDER:
            break
    assert len(datalumos_copies) == PER_HOLDER, f"only {len(datalumos_copies)} deposits in {MAX_DRAWS} draws"
    print(f"DataLumos projects {_low}..{_high}: {PER_HOLDER} deposits found in {_draws} draws")
    return (datalumos_copies,)


@app.cell
def _(HARVARD, PER_HOLDER, SEED, SOURCE_COOP, get, harvard_index, harvard_record):
    _drawn = harvard_index.sample(n=PER_HOLDER, random_state=SEED)
    harvard_copies = [
        {"name": n, "record": harvard_record(p)} for n, p in zip(_drawn["name"], _drawn["metadata_path"], strict=True)
    ]

    SOURCE_COOP_PRODUCTS = [
        "seerai/hifld",
        "cboettig/justice40",
        "cboettig/social-vulnerability",
        "cboettig/pad-us-3",
        "giswqs/nwi",
        "cboettig/usgs-wbd",
    ]
    source_coop_copies = [
        {
            "product": p,
            "api": get(f"{SOURCE_COOP}/api/v1/products/{p}").json(),
            "readme": get(f"https://data.source.coop/{p}/README.md").text,
        }
        for p in SOURCE_COOP_PRODUCTS
    ]
    print([c["name"] for c in harvard_copies])
    return harvard_copies, source_coop_copies


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Putting every copy in one shape

    Each holder's metadata is mapped to the same fields. A field is filled only from a named field in the holder's
    API; the free text (description, README) goes in `text` and can only earn a `hand`. `data` says whether the
    copy's files are there and readable by a script (`open`), there but not readable by a script (`closed`), or
    not in the copy at all (`none`). We find that by asking for them.
    """)
    return


@app.cell
def _(
    datalumos_copies,
    dcat_extras,
    harvard_copies,
    hifld_records,
    probe,
    source_coop_copies,
):
    def from_stac(r: dict) -> dict:
        c = r["stac"]
        date_cols = [col["name"] for col in c.get("table:columns", []) if "DATE" in col["name"].upper()]
        parquet = [a["href"] for a in c.get("assets", {}).values() if a["href"].endswith(".parquet")]
        return {
            "holder": "HIFLD Next",
            "copy": r["layer"],
            "source_url": None,
            "source_modified": c.get("hifld:source_dates", {}).get("modified"),
            "capture_date": None,
            "record_count": c.get("hifld:feature_count"),
            "cadence": None,
            "temporal": date_cols or None,
            "text": c.get("description", ""),
            "data": "open" if parquet and probe(parquet[0]) < 400 else "closed",
            "upstream_gone": r["by_vintage"] == "no current source",
        }

    def from_datacite(d: dict) -> dict:
        a = d["attrs"]
        dates = {x["dateType"]: x["date"] for x in a.get("dates", [])}
        related = [
            x["relatedIdentifier"] for x in a.get("relatedIdentifiers", []) if x.get("relatedIdentifierType") == "URL"
        ]
        return {
            "holder": "DataLumos",
            "copy": d["doi"],
            "source_url": related[0] if related else None,
            "source_modified": dates.get("Updated"),
            "capture_date": a.get("created"),
            "record_count": a.get("sizes") or None,
            "cadence": None,
            "temporal": dates.get("Collected") or dates.get("Coverage"),
            "text": " ".join(x.get("description", "") for x in a.get("descriptions", [])),
            "data": "open" if probe(a["url"]) < 400 else "closed",
            "upstream_gone": False,
        }

    def from_harvard(h: dict) -> dict:
        rec = h["record"]
        ckan = rec["signed_metadata"]["data_gov_metadata"]
        extras = dcat_extras(rec)
        urls = [ckan.get("url"), extras.get("landingPage")] + [x.get("url") for x in ckan.get("resources", [])]
        resource_urls = {x.get("url") for x in ckan.get("resources", [])}
        fetched = [
            t for t in rec["signed_metadata"].get("collection_tasks", []) if t["request"]["url"] in resource_urls
        ]
        source_url = next((u for u in urls if u), None)
        return {
            "holder": "Harvard data.gov archive",
            "copy": h["name"],
            "source_url": source_url,
            "source_modified": extras.get("modified"),
            "capture_date": rec["bag_info"].split("Bagging-Date:")[1].strip()[:10]
            if "Bagging-Date" in rec["bag_info"]
            else None,
            "record_count": None,
            "cadence": extras.get("accrualPeriodicity"),
            "temporal": extras.get("temporal"),
            "text": ckan.get("notes") or "",
            "data": "open" if any(t["response"].get("success") for t in fetched) else "none",
            "upstream_gone": False,
        }

    def from_source_coop(s: dict) -> dict:
        return {
            "holder": "Source Cooperative",
            "copy": s["product"],
            "source_url": None,
            "source_modified": None,
            "capture_date": s["api"].get("created_at"),
            "record_count": None,
            "cadence": None,
            "temporal": None,
            "text": (s["api"].get("description") or "") + "\n" + s["readme"],
            "data": "open",
            "upstream_gone": False,
        }

    copies = (
        [from_stac(r) for r in hifld_records]
        + [from_datacite(d) for d in datalumos_copies]
        + [from_harvard(h) for h in harvard_copies]
        + [from_source_coop(s) for s in source_coop_copies]
    )
    for _c in copies:
        _c["source_status"] = probe(_c["source_url"]) if _c["source_url"] else None
    print(
        f"{len(copies)} copies; a DataLumos landing page answers scripts with HTTP",
        probe(datalumos_copies[0]["attrs"]["url"]),
    )
    return (copies,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Scoring each copy

    The rules from the checklist table, applied to every copy the same way.
    """)
    return


@app.cell
def _(CADENCE, COUNT, DATE, copies, pd, text_urls):
    CHECKS = ["1 upstream", "2 newest record", "3 record count", "4 source modified", "5 cadence", "6 vintage label"]

    def score(c: dict) -> dict:
        text = c["text"]
        has_data = c["data"] in ("open", "closed")
        upstream = (
            "no" if c["upstream_gone"] else ("copy" if c["source_status"] and c["source_status"] < 400 else "hand")
        )
        newest = "copy" if c["temporal"] else ("hand" if has_data or DATE.search(text) else "no")
        count = "copy" if c["record_count"] else ("hand" if has_data or COUNT.search(text) else "no")
        modified = "copy" if c["source_modified"] else ("hand" if DATE.search(text) else "no")
        cadence = "copy" if c["cadence"] else ("hand" if CADENCE.search(text) else "no")
        vintage_parts = [bool(c["capture_date"]), bool(c["source_modified"] or c["temporal"])]
        vintage = "copy" if all(vintage_parts) else ("hand" if any(vintage_parts) or DATE.search(text) else "no")
        if c["upstream_gone"]:
            overall = "can't (fixed snapshot)"
        elif upstream == "copy" and modified == "copy":
            overall = "from the copy"
        else:
            overall = "by hand"
        return dict(
            zip(CHECKS, [upstream, newest, count, modified, cadence, vintage], strict=True),
            overall=overall,
            source_url_in_text=bool(text_urls(text)),
        )

    scores = pd.DataFrame(
        [
            {
                "holder": c["holder"],
                "copy": c["copy"],
                "data": c["data"],
                **score(c),
                "source_url": c["source_url"],
                "source_status": c["source_status"],
            }
            for c in copies
        ]
    )
    scores
    return CHECKS, scores


@app.cell
def _(CHECKS, pd, scores):
    HOLDERS = ["HIFLD Next", "DataLumos", "Source Cooperative", "Harvard data.gov archive"]

    def from_copy_counts(check: str) -> pd.Series:
        return scores.groupby("holder")[check].apply(
            lambda s: f"{(s == 'copy').sum()} / {(s == 'hand').sum()} / {(s == 'no').sum()}"
        )

    check_table = pd.DataFrame({check: from_copy_counts(check) for check in CHECKS}).reindex(HOLDERS)
    overall_table = (
        pd.crosstab(scores["holder"], scores["overall"], margins=True, margins_name="all copies")
        .reindex(HOLDERS + ["all copies"])
        .fillna(0)
        .astype(int)
    )
    check_table
    return HOLDERS, check_table, overall_table


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Each cell above reads `copy / hand / no`. And per holder, the share of copies whose currency can be checked
    from the copy, only by hand, or not at all:
    """)
    return


@app.cell
def _(overall_table):
    overall_table
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **What it shows.** The only copies that pass are Harvard's data.gov records whose DCAT-US metadata names the
    source (USGS data-release DOIs, a Census file URL) and its `modified` date. Those happen to be one-off
    releases that are unlikely to change. No HIFLD Next, DataLumos or Source Cooperative copy passes, for the same
    reason: none has a source link in a field. HIFLD Next has the richest record-level metadata (feature counts,
    source dates, declared date columns) but no source link and no capture date. Source Cooperative has
    everything only in its READMEs, which a person has to read. DataLumos pages answer scripts with HTTP 403, so
    even its files are by hand.

    The checks that fail everywhere are **cadence** (no copy in any holder has an update-frequency field, though
    DCAT-US defines one, `accrualPeriodicity`) and **a source link**. Those are the two fields a publisher saving a copy should add.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## HIFLD layers with no upstream, restated

    From #171's hand checks of 73 layers: the layers with no current public source are the ones that can only ever
    be fixed snapshots.
    """)
    return


@app.cell
def _(layers):
    _checked = layers[layers["by_vintage"] != ""]
    _gone = _checked[_checked["by_vintage"] == "no current source"]
    no_upstream = {
        "checked": len(_checked),
        "no_current_source": len(_gone),
        "share": round(len(_gone) / len(_checked), 3),
        "climate_risk_checked": int((_checked["group"] == "climate risk").sum()),
        "climate_risk_no_source": int((_gone["group"] == "climate risk").sum()),
    }
    print(no_upstream)
    _gone[["layer", "agency", "current_source"]]
    return (no_upstream,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## What dataindex.us and ALFRED track

    From their own pages, read on 2026-11-11.

    **[dataindex.us](https://dataindex.us/about-us)** is "dedicated to monitoring changes in federal datasets".
    Its [Data Checkup](https://dataindex.us/collections) covers 117 named collections (ACS, BRFSS, AQI and the
    like), each with a risk rating that people assign on six dimensions (levels from "No Known Issue" to "Gone"),
    with citations, updated "quarterly, with additional ad hoc updates"
    ([newsletter](https://dataindex.us/newsletter/article/03771180-a973-4f2c-8f6b-a73ba52896b2)). It also tracks
    OMB information collection requests and grant terminations. The same article says "URL tracking wasn't
    sufficient". Its pages publish no file versions, record counts, last-modified dates or checksums, and HIFLD
    is not one of its collections. It tells you a collection is at risk, not whether a given copy is behind.

    **[ALFRED](https://alfred.stlouisfed.org/help)** is "a collection of vintage versions of U.S. economic data":
    every revision of every FRED series, each value with its
    [real-time period](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html), added "typically within
    one business day". That is the vintage label this checklist asks for, done properly. But it covers only
    numeric time series in FRED: no geospatial layers, no microdata, and no record of whether a source site is
    still live.

    Neither can tell you whether a HIFLD layer copy or a DataLumos deposit is behind its source.
    """)
    return


@app.cell
def _(
    FIELDS,
    HOLDERS,
    OUT,
    copies_agree_on_date,
    STARTED,
    check_table,
    field_detail,
    field_table,
    json,
    match_stats,
    no_upstream,
    overall_table,
    scores,
    time,
):
    field_detail.to_csv(OUT / "hifld_fields.csv", index=False)
    scores.to_csv(OUT / "copy_scores.csv", index=False)
    summary = {
        "date_run": time.strftime("%Y-%m-%d"),
        "hifld_matching": match_stats,
        "hifld_fields": {f: field_table.loc[f].to_dict() for f in FIELDS},
        "hifld_source_dates": copies_agree_on_date,
        "checks_copy_hand_no": check_table.to_dict(orient="index"),
        "overall": {h: overall_table.loc[h].to_dict() for h in HOLDERS + ["all copies"]},
        "no_upstream_171": no_upstream,
        "seconds": round(time.time() - STARTED, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(field_table.to_string())
    print(check_table.to_string())
    print(overall_table.to_string())
    print(json.dumps({"seconds": summary["seconds"]}))
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - **"From the copy" means the check can start without a person, not that it's finished.** A live source URL
      and a recorded date let a script compare dates. Whether the source's newer date means newer *data* is still
      a judgment (see #171's two calls).
    - **Small samples.** 20 HIFLD layers and six copies per holder. The Source Cooperative six were picked from
      search results, not drawn at random.
    - **Text counts as `hand` by a regex.** A date or a URL in a README earns a `hand`; we don't check it's the
      right date. A copy whose README states its source date clearly is still `hand`, because a script can't
      rely on it.
    - **We read metadata, not files.** Record dates inside the files are only scored as possible (`hand`) where
      the files are there, except HIFLD Next's declared date columns, which #171 read with DuckDB.
    - **The original HIFLD Open item pages** (ArcGIS Hub) would be a richer original than data.gov's record, but
      the Wayback Machine wasn't reachable from our sandbox, so data.gov's archived record stands in.
    """)
    return


if __name__ == "__main__":
    app.run()
