import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
    # Which infrastructure facts exist only in the federal PDFs archived in 2020?

    [GovText](https://source.coop/govscape/eota-ocr) is the public-domain text of 9.02 million PDFs from the
    2020 End of Term crawl of government websites, each read twice: once from the text embedded in the file
    (pypdfium2) and once by an OCR model (olmOCR). [HIFLD Next](https://hifld.publicenvirodata.org) keeps the
    federal infrastructure layers planners use. The question: when a PDF talks about a dam, hospital or power
    plant in those layers, does it say things the layer doesn't hold, and how many of those things could only be
    read with OCR?

    The steps: pick three layers; query GovText for candidate PDFs; match facilities to pages; sample matched
    pages; have a model list each page's facts about the facility and compare them with the layer's record;
    check a sample by eye against the page images; say what failed.
    """
    )
    return (mo,)


@app.cell
def _():
    import io
    import json
    import os
    import re
    import tarfile
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import ahocorasick  # ty: ignore[import-not-found]  # compiled module with no type stubs
    import duckdb
    import pandas as pd
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    RUN_STARTED = time.time()
    GOVTEXT = os.environ.get(
        "GOVTEXT_BASE_URL",
        "https://s3.us-west-2.amazonaws.com/us-west-2.opendata.source.coop/govscape/eota-ocr",
    )
    HIFLD = os.environ.get("HIFLD_BASE_URL", "https://hifld.publicenvirodata.org/storage/hifld")
    DATA = Path(os.environ.get("DATA_DIR", "data"))
    OUT = Path(os.environ.get("OUTPUT_DIR", "outputs"))
    SEED = 212
    DOCS_TO_READ = int(os.environ.get("DOCS_TO_READ", "5000"))
    DOCS_PER_HOST = 25
    PAGES_PER_LAYER = 100
    DATA.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    (DATA / "text").mkdir(exist_ok=True)
    con = duckdb.connect()
    return (
        DATA,
        DOCS_PER_HOST,
        DOCS_TO_READ,
        GOVTEXT,
        HIFLD,
        OUT,
        PAGES_PER_LAYER,
        HTTPAdapter,
        Path,
        RUN_STARTED,
        Retry,
        SEED,
        ThreadPoolExecutor,
        ahocorasick,
        con,
        io,
        json,
        os,
        pd,
        re,
        requests,
        tarfile,
        time,
    )


@app.cell
def _(mo):
    mo.md(
        """
    ## 1. The layers

    Three HIFLD Next layers, read as GeoParquet over HTTPS: the National Inventory of Dams (92,366 dams),
    Hospitals (8,340) and Power Plants (16,317). We keep each layer's name, place and every descriptive
    attribute, because the comparison later asks whether a fact on the page is already in one of them.
    """
    )
    return


@app.cell
def _(HIFLD, con):
    LAYER_URLS = {
        name: f"{HIFLD}/{path}/{path}/{version}/geoparquet/{path}.parquet"
        for name, path, version in [
            ("dams", "national-inventory-of-dams-nid-1", "v1.0.0"),
            ("hospitals", "hospitals-3", "v1.1.0"),
            ("power_plants", "power-plants-1", "v1.0.0"),
        ]
    }
    DROP = {"geometry", "bbox", "OBJECTID", "id", "geom"}
    layers = {}
    for _name, _url in LAYER_URLS.items():
        _cols = [
            c for c in con.sql(f"DESCRIBE SELECT * FROM read_parquet('{_url}')").df()["column_name"] if c not in DROP
        ]
        _df = con.sql(f"SELECT {', '.join(_cols)} FROM read_parquet('{_url}')").df()
        assert len(_df) > 1000, f"{_name}: only {len(_df)} rows"
        layers[_name] = _df.reset_index(drop=True)
    {k: v.shape for k, v in layers.items()}
    return (layers,)


@app.cell
def _(mo):
    mo.md(
        """
    ## 2. Querying GovText

    GovText has no full-text index; it is one folder of files per PDF plus a provenance table,
    `cdx/complete_cdx.parquet`, with every URL each PDF was served from. So the query runs in two steps.
    First, DuckDB filters the 2020 rows of that table to PDFs whose URL mentions dams, levees, spillways,
    reservoirs, hospitals, power plants, generating stations, hydroelectric projects, hazard mitigation plans,
    emergency action plans or flood insurance studies. That is the pool of candidates. (Adobe CMS paths like
    `/content/dam/` and NOAA's `dam-migration` folder are excluded; they are not about dams.)
    """
    )
    return


@app.cell
def _(GOVTEXT, con):
    POOL_PATTERN = (
        r"(^|[^a-z])(dams?|dam safety|spillway|levees?|hazard mitigation|mitigation plan|emergency action plan|"
        r"flood insurance study|hospitals?|power plants?|generating station|power station|hydroelectric|reservoirs?)"
        r"([^a-z]|$)"
    )
    pool = con.sql(f"""
        SELECT digest AS pdf_id, min(url) AS url, regexp_extract(min(url), '//([^/:]+)', 1) AS host
        FROM (
            SELECT digest, url, lower(regexp_replace(replace(url, '%20', ' '), '[_+-]', ' ', 'g')) AS u
            FROM read_parquet('{GOVTEXT}/cdx/complete_cdx.parquet')
            WHERE filename LIKE '%EOT-2020%'
        )
        WHERE regexp_matches(u, '{POOL_PATTERN}')
          AND NOT regexp_matches(u, '/content/dam/|dam migration|pdg\\.lbl\\.gov')
        GROUP BY digest
        ORDER BY digest
    """).df()
    assert len(pool) > 5000, f"pool too small: {len(pool)}"
    print(f"Candidate PDFs: {len(pool):,} from {pool['host'].nunique():,} hosts")
    pool["host"].value_counts().head(10)
    return (pool,)


@app.cell
def _(mo):
    mo.md(
        """
    One host (Illinois Medicaid hospital cost reports) is a third of the pool, so the sample takes at most 25
    PDFs per host before drawing at random with a fixed seed. For each sampled PDF we download its two text
    renderings: `ocr_metadata/<id>/metadata.json` (the OCR text with page offsets) and
    `extracted_text/<id>.tar.gz` (the embedded text, one file per page). PDFs themselves are not downloaded here.
    """
    )
    return


@app.cell
def _(DOCS_PER_HOST, DOCS_TO_READ, SEED, pool):
    sample_docs = (
        pool.sample(frac=1, random_state=SEED)
        .groupby("host", sort=False)
        .head(DOCS_PER_HOST)
        .head(DOCS_TO_READ)
        .reset_index(drop=True)
    )
    print(f"Sampled {len(sample_docs):,} PDFs from {sample_docs['host'].nunique():,} hosts")
    return (sample_docs,)


@app.cell
def _(DATA, GOVTEXT, HTTPAdapter, Retry, ThreadPoolExecutor, io, json, requests, sample_docs, tarfile):
    # Bounded retries with backoff for dropped connections and 5xx answers.
    http = requests.Session()
    _retry = Retry(total=6, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    http.mount("https://", HTTPAdapter(max_retries=_retry, pool_maxsize=16))

    def fetch_text(pdf_id: str) -> dict:
        """Both renderings of one PDF as {"ocr": {page: text}, "embedded": {page: text}}, cached on disk."""
        cache = DATA / "text" / f"{pdf_id}.json"
        if cache.exists():
            return json.loads(cache.read_text())
        doc: dict = {"ocr": {}, "embedded": {}, "pages": 0, "is_table": {}}
        meta = http.get(f"{GOVTEXT}/ocr_metadata/{pdf_id}/metadata.json", timeout=120)
        emb = http.get(f"{GOVTEXT}/extracted_text/{pdf_id}.tar.gz", timeout=120)
        assert meta.status_code in (200, 404) and emb.status_code in (200, 404), f"{pdf_id}: HTTP error"
        if meta.status_code == 200:
            m = meta.json()
            doc["pages"] = m["metadata"]["pdf-total-pages"]
            for (start, end, page), table in zip(
                m["attributes"]["pdf_page_numbers"], m["attributes"]["is_table"], strict=True
            ):
                doc["ocr"][str(page)] = m["text"][start:end]
                doc["is_table"][str(page)] = table
        if emb.status_code == 200:
            with tarfile.open(fileobj=io.BytesIO(emb.content)) as tar:
                for member in tar.getmembers():
                    f = tar.extractfile(member)
                    if f is None or not member.name.endswith(".txt"):
                        continue
                    page = member.name.rsplit("_", 1)[1].removesuffix(".txt")
                    doc["embedded"][page] = f.read().decode("utf-8", errors="replace")
        cache.write_text(json.dumps(doc))
        return doc

    with ThreadPoolExecutor(max_workers=12) as _pool:
        texts = dict(zip(sample_docs["pdf_id"], _pool.map(fetch_text, sample_docs["pdf_id"]), strict=True))
    _pages = sum(len(set(d["ocr"]) | set(d["embedded"])) for d in texts.values())
    print(f"Read {len(texts):,} PDFs, {_pages:,} pages with text")
    return http, texts


@app.cell
def _(mo):
    mo.md(
        """
    ## 3. Matching facilities to pages

    Second step of the query: find layer facilities named on the downloaded pages. We search every page's OCR
    and embedded text for each facility's name with an Aho-Corasick automaton (one pass per page for all
    names at once), on lowercased text with punctuation removed and whole words only. A name alone is not
    enough, because "Memorial Hospital" or "Mill Pond Dam" appear many times in a layer. The rule:

    - Names must have at least two words and eight letters, and contain a word that says what the facility is
      (dam, dike, levee or reservoir for dams; hospital, medical, health, clinic or center for hospitals;
      plant, station, power, energy, generating, hydro, solar, wind, farm, project or facility for power
      plants). Without this, layer names that are also place names ("Grand Forks", "Mountain Lake") matched
      half the pages we looked at.
    - The page must also name the facility's state (the full name, or the two-letter code after a comma or
      before a ZIP code).
    - If more than one facility in the layer has that name, the page must also name its city (or county for
      dams), and exactly one of them must pass.
    - For dams, a National Inventory of Dams ID on the page (like `WY02950`) is a match on its own.
    """
    )
    return


@app.cell
def _(ahocorasick, layers, pd, re):
    STATES = {
        "AL": "alabama",
        "AK": "alaska",
        "AZ": "arizona",
        "AR": "arkansas",
        "CA": "california",
        "CO": "colorado",
        "CT": "connecticut",
        "DE": "delaware",
        "DC": "district of columbia",
        "FL": "florida",
        "GA": "georgia",
        "HI": "hawaii",
        "ID": "idaho",
        "IL": "illinois",
        "IN": "indiana",
        "IA": "iowa",
        "KS": "kansas",
        "KY": "kentucky",
        "LA": "louisiana",
        "ME": "maine",
        "MD": "maryland",
        "MA": "massachusetts",
        "MI": "michigan",
        "MN": "minnesota",
        "MS": "mississippi",
        "MO": "missouri",
        "MT": "montana",
        "NE": "nebraska",
        "NV": "nevada",
        "NH": "new hampshire",
        "NJ": "new jersey",
        "NM": "new mexico",
        "NY": "new york",
        "NC": "north carolina",
        "ND": "north dakota",
        "OH": "ohio",
        "OK": "oklahoma",
        "OR": "oregon",
        "PA": "pennsylvania",
        "RI": "rhode island",
        "SC": "south carolina",
        "SD": "south dakota",
        "TN": "tennessee",
        "TX": "texas",
        "UT": "utah",
        "VT": "vermont",
        "VA": "virginia",
        "WA": "washington",
        "WV": "west virginia",
        "WI": "wisconsin",
        "WY": "wyoming",
        "PR": "puerto rico",
        "GU": "guam",
    }
    CODE_OF_STATE = {v: k for k, v in STATES.items()}

    def norm(text: str) -> str:
        return " " + re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip() + " "

    # One row per (layer, facility): its matchable name, state code and city/county.
    _rows = []
    for _layer, _df in layers.items():
        _state = _df["STATE"].map(lambda s: CODE_OF_STATE.get(str(s).lower(), str(s).upper()))
        _place = _df["COUNTY"] if _layer != "dams" else _df["COUNTYSTAT"]
        _names = [_df["NAME"]] + ([_df["ALT_NAME"]] if "ALT_NAME" in _df else [])
        for _col in _names:
            _rows.append(
                pd.DataFrame(
                    {
                        "layer": _layer,
                        "row": _df.index,
                        "name": _col.map(norm),
                        "state": _state,
                        "city": _df["CITY"].map(norm),
                        "county": _place.map(norm),
                    }
                )
            )
    facilities = pd.concat(_rows, ignore_index=True)
    TYPE_WORDS = {
        "dams": r" (dam|dike|levee|reservoir) ",
        "hospitals": r" (hospital|medical|health|clinic|center|centre|infirmary) ",
        "power_plants": r" (plant|station|power|energy|generating|hydro|solar|wind|farm|project|facility|cogen) ",
    }
    _typed = pd.Series(False, index=facilities.index)
    for _layer, _pattern in TYPE_WORDS.items():
        _typed |= (facilities["layer"] == _layer) & facilities["name"].str.contains(_pattern.replace("(", "(?:"))
    facilities = facilities[
        _typed
        & (facilities["name"].str.split().str.len() >= 2)
        & (facilities["name"].str.replace(" ", "").str.len() >= 8)
        & ~facilities["name"].str.contains(" not available ")
    ].drop_duplicates()
    facilities["n_same_name"] = facilities.groupby(["layer", "name"])["row"].transform("nunique")

    automaton = ahocorasick.Automaton()
    for _name, _group in facilities.groupby("name"):
        automaton.add_word(_name, _group.index.to_list())
    automaton.make_automaton()
    NID_IDS = set(layers["dams"]["NIDID"].dropna())
    NID_ROW = dict(zip(layers["dams"]["NIDID"], layers["dams"].index, strict=True))
    print(f"{len(facilities):,} matchable names; {(facilities['n_same_name'] > 1).mean():.0%} shared by 2+ facilities")
    return CODE_OF_STATE, NID_IDS, NID_ROW, STATES, automaton, facilities, norm


@app.cell
def _(NID_IDS, NID_ROW, STATES, automaton, facilities, norm, pd, re, texts):
    def states_on_page(raw: str, normed: str) -> set[str]:
        found = {code for code, name in STATES.items() if f" {name} " in normed}
        pairs = re.findall(r",\s*([A-Z]{2})\b|\b([A-Z]{2})\s+\d{5}\b", raw)
        found |= {code for pair in pairs for code in pair if code in STATES}
        return found

    def match_page(raw: str) -> list[tuple[str, int, str]]:
        """(layer, row, how) for each facility this page names, by the rule above."""
        normed = norm(raw)
        hits = [("dams", NID_ROW[i], "NID ID") for i in set(re.findall(r"\b[A-Z]{2}\d{5}\b", raw)) & NID_IDS]
        candidates = {i for _, idxs in automaton.iter(normed) for i in idxs}
        if not candidates:
            return hits
        states = states_on_page(raw, normed)
        found = facilities.loc[list(candidates)]
        found = found[found["state"].isin(states)]
        for (layer, _name), group in found.groupby(["layer", "name"]):
            if group["n_same_name"].iloc[0] == 1:
                hits.append((layer, int(group["row"].iloc[0]), "name + state"))
                continue
            placed = group[[c in normed or k in normed for c, k in zip(group["city"], group["county"], strict=True)]]
            if placed["row"].nunique() == 1:
                hits.append((layer, int(placed["row"].iloc[0]), "name + state + city"))
        return hits

    _rows = []
    for _pdf_id, _doc in texts.items():
        for _page in sorted(set(_doc["ocr"]) | set(_doc["embedded"]), key=int):
            _raw = _doc["ocr"].get(_page, "") + "\n" + _doc["embedded"].get(_page, "")
            for _layer, _row, _how in set(match_page(_raw)):
                _rows.append({"pdf_id": _pdf_id, "page": int(_page), "layer": _layer, "row": _row, "how": _how})
    # Sorted, so the seeded sample below draws the same pages on every run.
    matches = (
        pd.DataFrame(_rows, columns=["pdf_id", "page", "layer", "row", "how"])
        .sort_values(["layer", "pdf_id", "page", "row"])
        .reset_index(drop=True)
    )
    match_summary = matches.groupby("layer").agg(
        facilities=("row", "nunique"), page_matches=("page", "size"), pdfs=("pdf_id", "nunique")
    )
    print(matches.groupby(["layer", "how"]).size())
    match_summary
    return match_summary, matches


@app.cell
def _(mo):
    mo.md(
        """
    ## 4. The sample of pages

    A few long PDFs carry most of the matches (one Texas dam list matches on 2,000 pages), so the sample takes at
    most two pages per PDF and two pages per facility, then up to 100 pages per layer, with a fixed seed.
    """
    )
    return


@app.cell
def _(PAGES_PER_LAYER, SEED, matches):
    page_sample = (
        matches.sample(frac=1, random_state=SEED)
        .groupby(["layer", "pdf_id"], sort=False)
        .head(2)
        .groupby(["layer", "row"], sort=False)
        .head(2)
        .groupby("layer", sort=False)
        .head(PAGES_PER_LAYER)
        .sort_values(["layer", "pdf_id", "page"])
        .reset_index(drop=True)
    )
    page_sample.groupby("layer").agg(pages=("page", "size"), pdfs=("pdf_id", "nunique"), facilities=("row", "nunique"))
    return (page_sample,)


@app.cell
def _(mo):
    mo.md(
        """
    ## 5. Listing the facts on each page

    A model reads each sampled page next to the facility's record in the layer and lists every fact the page
    states about that facility, each with the exact words it came from and whether the record already holds
    it (same value, a different value, or not at all). The answer is typed with Pydantic, so a malformed answer
    fails rather than being guessed at. The model reads the OCR text, or the embedded text when OCR recovered
    nothing. Answers are saved in `outputs/model_answers.jsonl`; a rerun uses them and only calls the model for
    pages it hasn't seen, so the numbers rerun with no key and no cost.
    """
    )
    return


@app.cell
def _():
    from typing import Literal

    from pydantic import BaseModel, Field

    FactType = Literal[
        "size or capacity",
        "condition or inspection",
        "hazard or risk",
        "event or incident",
        "operations or services",
        "finance or cost",
        "plan or project",
        "identity, owner or contact",
        "other",
    ]

    class Fact(BaseModel):
        statement: str = Field(description="The fact in one plain sentence.")
        fact_type: FactType
        quote: str = Field(
            description="The exact words on the page that state the fact, copied character for character, "
            "including the label or row heading that says what a number is (at least 4 words where possible)."
        )
        layer_status: Literal["same in layer", "different in layer", "not in layer"] = Field(
            description="Whether the facility's layer record holds this fact with the same value, holds the same "
            "attribute with a different value, or doesn't hold it."
        )
        layer_field: str | None = Field(description="The record's field that holds it, if any.")

    class PageFacts(BaseModel):
        about_facility: bool = Field(
            description="True if the page really refers to this facility, False if the name match is a coincidence."
        )
        facts: list[Fact] = Field(description="Every fact the page states about this facility; empty if none.")

    return (PageFacts,)


@app.cell
def _(OUT, PageFacts, ThreadPoolExecutor, json, layers, os, page_sample, requests, texts):
    from pydantic_ai import Agent
    from pydantic_ai.models.openrouter import OpenRouterModel
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    MODEL = os.environ.get("MODEL", "anthropic/claude-haiku-5.5")
    ANSWERS = OUT / "model_answers.jsonl"
    INSTRUCTIONS = (
        "You compare a page from a government PDF with one facility's record in a federal infrastructure layer. "
        "List every fact the page states about this specific facility: measurements, capacities, condition and "
        "inspection findings, hazards and risks, events, services, costs, plans, owners. Skip facts about other "
        "facilities and general statements. Copy each quote exactly from the page. Then say whether the record "
        "holds each fact. Count a fact as in the layer only if a record field holds that information."
    )

    def page_text(pdf_id: str, page: int) -> tuple[str, str]:
        doc = texts[pdf_id]
        ocr = doc["ocr"].get(str(page), "")
        return (ocr, "ocr") if ocr.strip() else (doc["embedded"].get(str(page), ""), "embedded")

    def record(layer: str, row: int) -> dict:
        rec = layers[layer].loc[row].to_dict()
        return {
            k: str(v) for k, v in rec.items() if v is not None and str(v) not in ("nan", "NOT AVAILABLE", "", "-999")
        }

    def key(r: dict) -> str:
        return f"{r['pdf_id']}|{r['page']}|{r['layer']}|{r['row']}|{MODEL}"

    _saved = {}
    if ANSWERS.exists():
        for _line in ANSWERS.read_text().splitlines():
            _a = json.loads(_line)
            _saved[_a["key"]] = _a
    _todo = [r for r in page_sample.to_dict("records") if key(r) not in _saved]
    print(f"{len(page_sample) - len(_todo)} saved answers, {len(_todo)} pages to send to {MODEL}")

    if _todo:
        assert os.environ.get("OPENROUTER_API_KEY"), "OPENROUTER_API_KEY is needed for pages without saved answers"
        agent = Agent(
            OpenRouterModel(MODEL, provider=OpenRouterProvider(api_key=os.environ["OPENROUTER_API_KEY"])),
            output_type=PageFacts,
            instructions=INSTRUCTIONS,
            retries=2,
        )

        def ask(r: dict) -> dict:
            text, source = page_text(r["pdf_id"], r["page"])
            prompt = (
                f"Layer: {r['layer']}\nRecord:\n{json.dumps(record(r['layer'], r['row']), indent=1)}\n\n"
                f"Page {r['page']} ({source} text):\n{text[:15000]}"
            )
            result = agent.run_sync(prompt)
            usage = result.usage
            facts_out = result.output
            assert isinstance(facts_out, PageFacts), "model answer did not validate"
            return {
                "key": key(r),
                **r,
                "model": MODEL,
                "source": source,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "answer": facts_out.model_dump(),
            }

        with ThreadPoolExecutor(max_workers=8) as _pool, ANSWERS.open("a") as _f:
            for _a in _pool.map(ask, _todo):
                _f.write(json.dumps(_a) + "\n")
                _saved[_a["key"]] = _a

    answers = [_saved[key(r)] for r in page_sample.to_dict("records")]
    _price = next(
        m["pricing"]
        for m in requests.get("https://openrouter.ai/api/v1/models", timeout=60).json()["data"]
        if m["id"] == MODEL
    )
    model_cost = sum(
        a["input_tokens"] * float(_price["prompt"]) + a["output_tokens"] * float(_price["completion"]) for a in answers
    )
    print(f"{len(answers)} answers; model cost ${model_cost:.2f} at today's OpenRouter price")
    return MODEL, answers, model_cost, page_text


@app.cell
def _(mo):
    mo.md(
        """
    ## 6. Which facts the layer lacks, and which needed OCR

    Each fact becomes a row. A fact needed OCR when its quote is in the OCR text and not in the embedded text
    (fuzzy match, after lowercasing and dropping punctuation and HTML tags, so table layout doesn't count as a
    difference). A page with no embedded text at all is the plain case of that.
    """
    )
    return


@app.cell
def _(OUT, answers, norm, pd, re, texts):
    from rapidfuzz import fuzz

    def found_in(quote: str, text: str) -> bool:
        q, t = norm(quote), norm(re.sub(r"<[^>]+>", " ", text))
        return bool(q.strip()) and bool(t.strip()) and fuzz.partial_ratio(q, t) >= 90

    _rows = []
    for _a in answers:
        _doc = texts[_a["pdf_id"]]
        _ocr, _emb = _doc["ocr"].get(str(_a["page"]), ""), _doc["embedded"].get(str(_a["page"]), "")
        if not _a["answer"]["about_facility"]:
            continue
        for _i, _f in enumerate(_a["answer"]["facts"]):
            _rows.append(
                {
                    "fact_id": f"{_a['pdf_id']}-{_a['page']}-{_a['layer']}-{_a['row']}-{_i}",
                    "pdf_id": _a["pdf_id"],
                    "page": _a["page"],
                    "layer": _a["layer"],
                    "row": _a["row"],
                    **_f,
                    "in_ocr": found_in(_f["quote"], _ocr),
                    "in_embedded": found_in(_f["quote"], _emb),
                    "page_has_embedded": bool(_emb.strip()),
                    "page_is_table": bool(_doc["is_table"].get(str(_a["page"]), False)),
                }
            )
    facts = pd.DataFrame(_rows)
    facts["ocr_only"] = facts["in_ocr"] & ~facts["in_embedded"]
    facts["quote_found"] = facts["in_ocr"] | facts["in_embedded"]
    facts.to_csv(OUT / "facts.csv", index=False)
    _pages = pd.DataFrame(
        [{"layer": a["layer"], "about": a["answer"]["about_facility"], "n": len(a["answer"]["facts"])} for a in answers]
    )
    page_stats = _pages.groupby("layer").agg(
        pages=("n", "size"), about_facility=("about", "mean"), facts_per_page=("n", "mean")
    )
    page_stats
    return facts, page_stats


@app.cell
def _(facts, pd):
    by_layer = facts.groupby("layer").agg(
        facts=("fact_id", "size"),
        not_in_layer=("layer_status", lambda s: (s == "not in layer").sum()),
        different_in_layer=("layer_status", lambda s: (s == "different in layer").sum()),
        same_in_layer=("layer_status", lambda s: (s == "same in layer").sum()),
    )
    _missing = facts[facts["layer_status"] == "not in layer"]
    by_layer["ocr_only_share_of_not_in_layer"] = _missing.groupby("layer")["ocr_only"].mean().round(3)
    by_type = pd.crosstab(_missing["fact_type"], _missing["layer"], margins=True, margins_name="all")
    print("Facts by layer:")
    print(by_layer.to_string())
    print("\nFacts the layer lacks, by type:")
    print(by_type.to_string())
    by_layer
    return by_layer, by_type


@app.cell
def _(mo):
    mo.md(
        """
    ## 7. Checking by eye against the page images

    GovText has no ground truth, and neither does the model. So we draw 60 of the facts the layer lacks (30
    that only the OCR text has, 30 that both texts have, fixed seed), download each PDF, render the page and
    compare it with the fact, the OCR text and the embedded text. For each fact we label: is the fact on the
    page, is it about the matched facility, is it substantive (an attribute or finding a dataset could hold,
    not just a mention in a list or a photo caption), is the OCR text of it right, is the embedded text of it
    right (or absent). The labels are in `hand_check_labels.csv`. They were made by the Claude worker that built this
    notebook, reading the rendered page images, not by a person; a founder can redo any row from the page
    image in `data/hand_check/`.
    """
    )
    return


@app.cell
def _(DATA, GOVTEXT, SEED, facts, http, norm, pd, re, texts):
    import pymupdf
    from rapidfuzz import fuzz as _fuzz

    _missing = facts[(facts["layer_status"] == "not in layer") & facts["quote_found"]]
    hand_sample = (
        pd.concat([g.sample(min(30, len(g)), random_state=SEED) for _, g in _missing.groupby("ocr_only")])
        .reset_index(drop=True)
        .assign(check_id=lambda d: d.index + 1)
    )

    def embedded_span(quote: str, text: str) -> str:
        """The stretch of embedded text that best matches the quote, for comparing with the image."""
        if not text.strip():
            return ""
        flat = re.sub(r"\s+", " ", text)
        al = _fuzz.partial_ratio_alignment(norm(quote).strip(), flat.lower())
        return flat[max(0, al.dest_start - 20) : al.dest_end + 20] if al and al.score >= 60 else ""

    _dir = DATA / "hand_check"
    _dir.mkdir(exist_ok=True)
    _sheet = []
    for _r in hand_sample.itertuples():
        _png = _dir / f"{_r.check_id:02d}.png"
        if not _png.exists():
            _pdf = http.get(f"{GOVTEXT}/pdfs/{_r.pdf_id}.pdf", timeout=300)
            assert _pdf.status_code == 200, f"{_r.pdf_id}: HTTP {_pdf.status_code}"
            with pymupdf.open(stream=_pdf.content, filetype="pdf") as _doc:
                _doc[_r.page - 1].get_pixmap(dpi=110).save(_png)
        _emb = embedded_span(_r.quote, texts[_r.pdf_id]["embedded"].get(str(_r.page), ""))
        _sheet.append(
            f"## {_r.check_id:02d} {_png.name} ({_r.layer}, page {_r.page}, ocr_only={_r.ocr_only})\n"
            f"- fact_id: {_r.fact_id}\n"
            f"- fact: {_r.statement}\n- OCR quote: {_r.quote!r}\n- embedded: {_emb!r}\n"
        )
    (_dir / "sheet.md").write_text("\n".join(_sheet))
    print(f"{len(hand_sample)} facts drawn; page images and a checking sheet in {_dir}/")
    return (hand_sample,)


@app.cell
def _(Path, hand_sample, pd):
    _path = Path("hand_check_labels.csv")
    assert _path.exists(), "hand_check_labels.csv is missing: label the facts in data/hand_check/sheet.md first"
    labels = pd.read_csv(_path).merge(
        hand_sample[["check_id", "fact_id", "ocr_only"]], on="check_id", suffixes=("", "_run")
    )
    assert (labels["fact_id"] == labels["fact_id_run"]).all() and len(labels) == len(hand_sample), (
        "labels don't match this run's hand-check sample"
    )
    _with_emb = labels[labels["embedded_correct"] != "absent"]
    _real = labels[(labels["fact_on_page"] == "yes") & (labels["about_facility"] == "yes")]
    hand = {
        "facts_checked": len(labels),
        "fact_on_page": round((labels["fact_on_page"] == "yes").mean(), 3),
        "about_facility": round((labels["about_facility"] == "yes").mean(), 3),
        "substantive": round((labels["substantive"] == "yes").mean(), 3),
        "real_and_substantive": round(((labels["substantive"] == "yes") & labels.index.isin(_real.index)).mean(), 3),
        "ocr_text_error_rate": round((labels["ocr_correct"] == "no").mean(), 3),
        "embedded_text_checked": len(_with_emb),
        "embedded_text_error_rate": round((_with_emb["embedded_correct"] == "no").mean(), 3),
        "embedded_text_absent": int((labels["embedded_correct"] == "absent").sum()),
        "ocr_only_facts_embedded_absent": int((labels["ocr_only"] & (labels["embedded_correct"] == "absent")).sum()),
        "ocr_only_facts_embedded_present": int((labels["ocr_only"] & (labels["embedded_correct"] != "absent")).sum()),
    }
    print(
        labels.groupby("ocr_only")[["fact_on_page", "about_facility", "substantive", "ocr_correct", "embedded_correct"]]
        .agg(lambda c: c.value_counts().to_dict())
        .to_string()
    )
    hand
    return (hand,)


@app.cell
def _(mo):
    mo.md("""## 8. Outputs""")
    return


@app.cell
def _(
    MODEL,
    OUT,
    RUN_STARTED,
    by_layer,
    by_type,
    facts,
    hand,
    json,
    match_summary,
    model_cost,
    page_stats,
    pool,
    sample_docs,
    texts,
    time,
):
    _missing = facts[facts["layer_status"] == "not in layer"]
    summary = {
        "candidate_pdfs_in_pool": len(pool),
        "pdfs_read": len(sample_docs),
        "pages_read": sum(len(set(d["ocr"]) | set(d["embedded"])) for d in texts.values()),
        "matches": match_summary.reset_index().to_dict("records"),
        "pages_sampled": page_stats.reset_index().to_dict("records"),
        "facts": by_layer.reset_index().to_dict("records"),
        "facts_not_in_layer": len(_missing),
        "facts_not_in_layer_per_page": round(len(_missing) / int(page_stats["pages"].sum()), 2),
        "facts_not_in_layer_by_type": by_type.reset_index().to_dict("records"),
        "ocr_only_share_of_not_in_layer": round(_missing["ocr_only"].mean(), 3),
        "ocr_only_share_of_not_in_layer_on_pages_without_embedded_text": round(
            (_missing["ocr_only"] & ~_missing["page_has_embedded"]).mean(), 3
        ),
        "quote_not_found_share": round(1 - facts["quote_found"].mean(), 3),
        "hand_check": hand,
        "model": MODEL,
        "model_cost_usd": round(model_cost, 2),
        "run_seconds": round(time.time() - RUN_STARTED),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return


if __name__ == "__main__":
    app.run()
