import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import re
    import time
    from datetime import date
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import pandas as pd
    import requests

    return Path, date, json, mo, np, os, pd, re, requests, time


@app.cell
def _(mo):
    mo.md(r"""
    # How many large-load grid projects in PJM's planning slides are later withdrawn?

    Each month PJM's transmission owners present "supplemental" projects to PJM's planning committees:
    TEAC and the three subregional RTEP committees (West, Mid-Atlantic, South). Some are needs driven by
    one customer asking for a lot of power, such as ComEd's "Customer in DeKalb, 504 MW". The same decks
    later list some of those needs as withdrawn or cancelled.

    This notebook reads every supplemental deck from 2025 to now and pulls out each customer-load need. It
    follows each need number from deck to deck to count withdrawals, then checks whether the substations
    and lines the decks name are on the public map. The decks name no customer and no end use, so no
    request is labelled a data center here.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The decks

    PJM's committee pages fill their meeting-materials table from a form post
    (`/m/CommitteesAndGroups/RefreshMaterials`, the call the year drop-down makes). We ask it for every
    year from 2025, for all four committees. We keep each transmission owner's "supplemental projects"
    presentation and skip the annual local-plan spreadsheets. The PDFs are downloaded to `data/` and are
    not committed.
    """)
    return


@app.cell
def _(Path, date, os, pd, re, requests, time):
    DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
    OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "outputs"))
    START_YEAR = int(os.environ.get("START_YEAR", "2025"))
    (DATA_DIR / "decks").mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PJM = "https://www.pjm.com"
    HEADERS = {"User-Agent": "Mozilla/5.0 (research script)"}

    def fetch(url: str, path: Path, data: dict[str, str] | None = None) -> Path:
        """Download url (POSTing data if given) to path once; later runs reuse the file."""
        if path.exists():
            return path
        for attempt in range(4):
            if data is None:
                response = requests.get(url, headers=HEADERS, timeout=300)
            else:
                response = requests.post(url, headers=HEADERS, data=data, timeout=300)
            if response.ok:
                path.write_bytes(response.content)
                return path
            print(f"{url}: HTTP {response.status_code} (attempt {attempt + 1} of 4)")
            time.sleep(2**attempt)
        raise RuntimeError(f"Could not download {url}")

    COMMITTEES = {
        "teac": "{B9C8A4A2-1A71-491C-B59D-0C27E50E5D41}",
        "srrtep-w": "{0DA17CD1-30C4-431A-A3B3-4849C38A95F6}",
        "srrtep-ma": "{1434CC5E-5780-46C7-A196-18392AF547EA}",
        "srrtep-s": "{D0B20341-FB84-4228-B18F-B9C190739299}",
    }
    _links = set()
    for _committee, _id in COMMITTEES.items():
        for _year in range(START_YEAR, date.today().year + 1):
            _page = fetch(
                f"{PJM}/m/CommitteesAndGroups/RefreshMaterials",
                DATA_DIR / f"materials-{_committee}-{_year}.html",
                {"committeeId": _id, "searchTerm": "", "year": str(_year), "isAnnualMeeting": "false"},
            )
            _links |= set(re.findall(r'href="(/-/media/[^"]+\.pdf)"', _page.read_text(errors="ignore")))
    _rows = []
    for _link in sorted(_links):
        _m = re.search(r"/committees/([a-z-]+)/\d{4}/(\d{8})[^/]*/([^/]+)$", _link)
        if not _m or "supplemental" not in _m[3] or "local-plan" in _m[3]:
            continue
        _rows.append(
            {
                "deck": f"{_m[1]}__{_m[3]}".removesuffix(".pdf"),
                "committee": _m[1],
                "meeting": pd.Timestamp(_m[2]),
                "url": PJM + _link,
            }
        )
    decks = pd.DataFrame(_rows).sort_values(["meeting", "deck"]).reset_index(drop=True)
    for _row in decks.itertuples():
        fetch(_row.url, DATA_DIR / "decks" / f"{_row.deck}.pdf")
    decks[["deck", "committee", "meeting", "url"]].to_csv(OUTPUT_DIR / "decks.csv", index=False)
    print(
        f"{len(decks)} supplemental decks from {decks['meeting'].min():%Y-%m-%d} to "
        f"{decks['meeting'].max():%Y-%m-%d}: {decks['committee'].value_counts().to_dict()}"
    )
    return DATA_DIR, OUTPUT_DIR, decks, fetch


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Which slides to read

    The slides are text PDFs, so `pdfplumber` reads them without OCR. Sending all 4,600 pages to a
    model would cost money for nothing, so we pick pages with a plain rule:

    - a page that mentions a customer, a large load, a load request or a data center *and* a number of MW
      marks the need numbers on it as load needs; then every page in that deck naming one of those need
      numbers is kept, which picks up the solution slide with its substations and cost;
    - every page that mentions a withdrawal or cancellation is kept;
    - a withdrawal page with almost no text is a table pasted as a picture (FirstEnergy does this), so we
      render it and send the image.
    """)
    return


@app.cell
def _(DATA_DIR, decks, re):
    import pdfplumber

    NEED = re.compile(r"\b[A-Z][A-Za-z&]{1,8}-\s?20\d\d-\s?[A-Z0-9]{2,7}\b")
    LOADISH = re.compile(r"customer|large load|load request|data center", re.I)
    WITHDRAWN = re.compile(r"withdr|cancel", re.I)

    pages = {}
    for _deck in decks["deck"]:
        with pdfplumber.open(DATA_DIR / "decks" / f"{_deck}.pdf") as _pdf:
            pages[_deck] = [_p.extract_text() or "" for _p in _pdf.pages]

    selected = {}
    for _deck, _texts in pages.items():
        _load_needs = set()
        for _t in _texts:
            if LOADISH.search(_t) and re.search(r"\d\s?MW\b", _t):
                _load_needs |= set(NEED.findall(_t))
        _keep = []
        for _i, _t in enumerate(_texts):
            _withdrawal = bool(WITHDRAWN.search(_t)) and "Revision History" not in _t
            if _withdrawal or set(NEED.findall(_t)) & _load_needs:
                _keep.append((_i + 1, _withdrawal and len(_t) < 200))
        if _keep:
            selected[_deck] = _keep
    _n_pages = sum(len(_t) for _t in pages.values())
    _n_sel = sum(len(_k) for _k in selected.values())
    _n_img = sum(_img for _k in selected.values() for _, _img in _k)
    print(
        f"{_n_pages} pages in {len(pages)} decks; {_n_sel} pages from {len(selected)} decks go to the model "
        f"({_n_img} as images); {sum(1 for _t in pages.values() for _p in _t if len(_p) < 30)} pages have no text"
    )
    return pages, selected


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Extracting each need with a typed model call

    One call per deck, with that deck's selected pages. The model must answer in the `DeckNeeds` schema
    below, which Pydantic AI validates. The schema mirrors the fields the decks print: need number, area,
    MW by year, the lines cut into, the substations named, estimated cost, in-service date and the stage.
    `customer_load` is the model's call on whether the need is one customer asking for new or more load,
    rather than a utility delivery point, a generator or an equipment rebuild.

    Answers are saved in `outputs/extractions/`, one JSON file per deck, and committed. A rerun reuses them,
    so a reviewer can rescore everything without an API key. Delete a file to pay for that deck again.
    """)
    return


@app.cell
def _():
    from typing import Literal

    from pydantic import BaseModel, Field

    class YearMW(BaseModel):
        year: int
        mw: float

    class LineCut(BaseModel):
        from_substation: str
        to_substation: str
        kv: float | None = None

    class Need(BaseModel):
        need_number: str = Field(description="As printed, e.g. ComEd-2025-009, DOM-2026-0012, PE-2025-007")
        stage: Literal["need", "solution", "withdrawn", "other"] = Field(
            description="need: a needs-meeting slide; solution: a proposed solution; withdrawn: the need or its "
            "project is withdrawn or cancelled on this deck; other: anything else (local plan, update)"
        )
        customer_load: bool = Field(
            description="True if the need is driven by one end-use customer (or a developer for one site) "
            "requesting new or increased load. A utility or co-op delivery-point request counts as True when the "
            "slide says it serves one customer, site or campus. False for general distribution load growth, "
            "transformer replacements, generators, Do No Harm follow-ups, reliability or equipment-condition needs."
        )
        area: str = Field(description="Town, county or area the slide names, e.g. 'DeKalb' or 'Loudoun County'")
        state: str | None = Field(description="Two-letter US state of the area, if you can tell")
        mw_by_year: list[YearMW] = Field(description="Every load figure with its year, e.g. 12 MW in 2029")
        ultimate_mw: float | None = Field(
            description="The ultimate or total load requested, in MW. 'In excess of 100 MW' gives 100. If no total "
            "is stated, the largest projected figure. Use the current figure where an old one is struck through."
        )
        estimated_cost_musd: float | None = Field(
            description="Total estimated transmission cost in $ millions. If the slide prints a total, use it. "
            "If it prints only component or phase costs, add them up. Never add a printed total to its own parts."
        )
        projected_in_service: str | None = Field(description="Projected or requested in-service date as printed")
        needs_meeting_date: str | None = Field(description="Date the need was (or is being) presented, as printed")
        solutions_meeting_date: str | None = Field(description="Date the solution was (or is being) presented")
        lines_cut_into: list[LineCut] = Field(description="Existing lines the solution cuts into or taps")
        existing_substations: list[str] = Field(
            description="Existing substations named as connection points or parents, without 'substation' or "
            "codes like (s3342.1). Exclude new substations and customer-owned substations."
        )
        new_substations: list[str] = Field(description="New substations the solution builds")

    class DeckNeeds(BaseModel):
        needs: list[Need] = Field(description="One entry per need number on these pages; empty if none")

    return DeckNeeds, Need


@app.cell
async def _(DATA_DIR, DeckNeeds, OUTPUT_DIR, decks, json, os, pages, selected, time):
    import asyncio

    import pypdfium2
    from pydantic_ai import Agent, BinaryContent
    from pydantic_ai.models.openrouter import OpenRouterModel

    MODEL = os.environ.get("EXTRACTION_MODEL", "anthropic/claude-haiku-5.5")
    _dir = OUTPUT_DIR / "extractions"
    _dir.mkdir(exist_ok=True)
    _meeting = dict(zip(decks["deck"], decks["meeting"], strict=True))
    _instructions = (
        "You read PJM transmission-owner supplemental project slides and record every need number on them, "
        "following the schema. Copy numbers as printed; use null when a field isn't on these pages. A table "
        "of withdrawn needs gives one entry per row with stage 'withdrawn'. Never guess a customer's identity."
    )

    def prompt_for(deck: str) -> list[str | BinaryContent]:
        parts: list[str | BinaryContent] = [f"Deck: {deck}\nMeeting date: {_meeting[deck]:%m/%d/%Y}"]
        for number, as_image in selected[deck]:
            parts.append(f"--- page {number} ---\n{pages[deck][number - 1]}")
            if as_image:
                pdf = pypdfium2.PdfDocument(DATA_DIR / "decks" / f"{deck}.pdf")
                image = pdf[number - 1].render(scale=1.5).to_pil()
                path = DATA_DIR / f"{deck}-p{number}.png"
                image.save(path)
                parts.append(BinaryContent(data=path.read_bytes(), media_type="image/png"))
        return parts

    async def extract(deck: str, gate: asyncio.Semaphore) -> None:
        path = _dir / f"{deck}.json"
        page_list = [number for number, _ in selected[deck]]
        if path.exists() and json.loads(path.read_text())["pages"] == page_list:
            return
        assert os.environ.get("OPENROUTER_API_KEY"), f"No saved answer for {deck} and no OPENROUTER_API_KEY"
        agent: Agent[None, DeckNeeds] = Agent(
            OpenRouterModel(MODEL), output_type=DeckNeeds, instructions=_instructions, retries=3
        )
        async with gate:
            started = time.perf_counter()
            result = await agent.run(prompt_for(deck))
        record = {
            "deck": deck,
            "model": MODEL,
            "pages": page_list,
            "seconds": round(time.perf_counter() - started, 2),
            "cost_usd": float(result.usage.cost or 0),
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "needs": result.output.model_dump()["needs"],
        }
        path.write_text(json.dumps(record, indent=1))

    _gate = asyncio.Semaphore(8)
    _wall = time.perf_counter()
    await asyncio.gather(*(extract(_deck, _gate) for _deck in selected))
    extractions = [json.loads((_dir / f"{_deck}.json").read_text()) for _deck in selected]
    print(
        f"{len(extractions)} decks extracted with {sorted({_e['model'] for _e in extractions})}: "
        f"${sum(_e['cost_usd'] for _e in extractions):.2f}, "
        f"{sum(_e['input_tokens'] for _e in extractions):,} input and "
        f"{sum(_e['output_tokens'] for _e in extractions):,} output tokens, "
        f"{sum(_e['seconds'] for _e in extractions):.0f} s of model time "
        f"({time.perf_counter() - _wall:.0f} s wall clock this run)"
    )
    return (extractions,)


@app.cell
def _(Need, decks, extractions, pd, re):
    def need_key(number: str) -> str:
        """One spelling per need number: no spaces, upper case, 'COMED-2025-009'."""
        return re.sub(r"\s+", "", number).upper()

    _meeting = dict(zip(decks["deck"], decks["meeting"], strict=True))
    _rows = []
    for _e in extractions:
        for _n in _e["needs"]:
            _need = Need.model_validate(_n)
            _rows.append(
                {
                    **_need.model_dump(),
                    "key": need_key(_need.need_number),
                    "owner": need_key(_need.need_number).split("-")[0],
                    "deck": _e["deck"],
                    "meeting": _meeting[_e["deck"]],
                }
            )
    records = pd.DataFrame(_rows)
    print(
        f"{len(records)} need mentions, {records['key'].nunique()} distinct need numbers, "
        f"{records.loc[records['customer_load'], 'key'].nunique()} of them customer-load needs"
    )
    return need_key, records


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. How good is the extraction?

    `hand_keyed.csv` holds needs keyed by hand from the slides, in two samples drawn *before* any model
    answer was looked at:

    - **random**: 30 (deck, need number) pairs drawn at random from the selected pages (seed 234). One, a
      Dominion "Do No Harm" slide covering several needs at once, was dropped as too ambiguous to key.
    - **withdrawal**: 8 withdrawal or cancellation slides drawn at random (seed 2342), because the random
      sample happened to contain none and withdrawals are what this spike counts.

    `n/a` means the slide doesn't settle the field, so it isn't scored. Numbers must match exactly. The
    area is right if one cleaned name contains the other (case, punctuation, "County" and state dropped;
    `|` separates names that are equally right). Substations are right if every keyed existing substation
    is among those the model named, counting the ends of lines cut into.
    """)
    return


@app.cell
def _(OUTPUT_DIR, need_key, pd, re, records):
    hand = pd.read_csv("hand_keyed.csv", dtype=str, keep_default_na=False)

    def clean(text: object) -> str:
        text = re.sub(r",\s*[A-Z]{2}$", "", str(text).strip().upper())
        return re.sub(r"[^A-Z]", "", re.sub(r"\b(COUNTY|AREA|SUBSTATION|SWITCH|SW)\b", "", text))

    def same(field: str, keyed: str, got: pd.Series) -> bool:
        value = got[field]
        if field in ("ultimate_mw", "estimated_cost_musd"):
            return (keyed == "" and pd.isna(value)) or (keyed != "" and pd.notna(value) and float(keyed) == value)
        if field == "customer_load":
            return keyed.lower() == str(value).lower()
        if field == "area":
            return any(clean(k) in clean(value) or clean(value) in clean(k) for k in keyed.split("|") if clean(value))
        if field == "existing_substations":
            named = list(value) + [n for c in got["lines_cut_into"] for n in (c["from_substation"], c["to_substation"])]
            return {clean(s) for s in keyed.split(";")} <= {clean(s) for s in named}
        return keyed == value

    _fields = ["stage", "customer_load", "area", "ultimate_mw", "estimated_cost_musd", "existing_substations"]
    _scores = []
    for _row in hand.itertuples():
        _mine = records[records["deck"] == _row.deck]
        _got = _mine[_mine["key"] == need_key(_row.need_number)]
        if _got.empty:
            _got = _mine[_mine["key"].str.startswith(need_key(_row.need_number))]
        for _f in _fields:
            _keyed = getattr(_row, _f)
            if _keyed == "n/a":
                continue
            _ok = not _got.empty and same(_f, _keyed, _got.iloc[0])
            _scores.append(
                {
                    "sample": _row.sample,
                    "deck": _row.deck,
                    "need": _row.need_number,
                    "field": _f,
                    "keyed": _keyed,
                    "got": None if _got.empty else _got.iloc[0][_f],
                    "right": _ok,
                }
            )
    hand_scores = pd.DataFrame(_scores)
    hand_scores.to_csv(OUTPUT_DIR / "hand_check_scores.csv", index=False)
    accuracy = hand_scores.groupby("field", sort=False)["right"].agg(["sum", "count"])
    accuracy["accuracy %"] = (100 * accuracy["sum"] / accuracy["count"]).round(1)
    print(
        f"{len(hand)} hand-keyed needs, {len(hand_scores)} field checks, {hand_scores['right'].mean():.1%} right "
        f"(random sample {hand_scores.loc[hand_scores['sample'] == 'random', 'right'].mean():.1%}, "
        f"withdrawal sample {hand_scores.loc[hand_scores['sample'] == 'withdrawal', 'right'].mean():.1%})"
    )
    accuracy
    return (hand_scores,)


@app.cell
def _(hand_scores):
    hand_scores[~hand_scores["right"]]
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Following each need from deck to deck

    A need number keeps its number from the needs meeting through the solution meeting. So for each
    customer-load need we take the date it was first presented (its needs-meeting date, or the first deck
    it appears in) and the first deck that lists it as withdrawn or cancelled. MW is the ultimate load;
    cost is the estimated transmission cost of the proposed solution, which only needs that reached a
    solution have.

    A **large load** here is a customer-load need of 100 MW or more. Smaller customer needs are counted
    too, in the table at the end of this step.
    """)
    return


@app.cell
def _(OUTPUT_DIR, pd, records):
    def latest(series: pd.Series) -> object:
        values = series.dropna()
        return values.iloc[-1] if len(values) else None

    _cust = records[records.groupby("key")["customer_load"].transform("any")].sort_values("meeting")
    _cust = _cust.assign(
        needs_date=pd.to_datetime(_cust["needs_meeting_date"], errors="coerce", format="mixed"),
        is_withdrawn=_cust["stage"].eq("withdrawn"),
    )
    needs = _cust.groupby("key").agg(
        owner=("owner", "first"),
        area=("area", "first"),
        state=("state", latest),
        first_deck=("meeting", "min"),
        needs_date=("needs_date", "min"),
    )
    needs["presented"] = needs[["first_deck", "needs_date"]].min(axis=1)
    needs["ultimate_mw"] = _cust.groupby("key")["ultimate_mw"].max()
    needs["cost_musd"] = _cust.groupby("key")["estimated_cost_musd"].agg(latest)
    needs["solution_shown"] = _cust.groupby("key")["stage"].agg(lambda s: s.eq("solution").any())
    needs["withdrawn_on"] = _cust[_cust["is_withdrawn"]].groupby("key")["meeting"].min()
    needs["withdrawn"] = needs["withdrawn_on"].notna()
    needs["months_to_withdrawal"] = ((needs["withdrawn_on"] - needs["presented"]).dt.days / 30.44).round(1)
    needs["large"] = needs["ultimate_mw"].fillna(0) >= 100
    needs.to_csv(OUTPUT_DIR / "customer_load_needs.csv")
    print(
        f"{len(needs)} customer-load needs, {int(needs['large'].sum())} of them 100 MW or more; "
        f"{int(needs['withdrawn'].sum())} withdrawn ({int((needs['withdrawn'] & needs['large']).sum())} large)"
    )
    return (needs,)


@app.cell
def _(OUTPUT_DIR, needs, pd):
    def by_owner(frame: pd.DataFrame) -> pd.DataFrame:
        gone = frame[frame["withdrawn"]]
        table = pd.DataFrame(
            {
                "requests": frame.groupby("owner").size(),
                "withdrawn": gone.groupby("owner").size(),
                "GW": frame.groupby("owner")["ultimate_mw"].sum() / 1000,
                "GW withdrawn": gone.groupby("owner")["ultimate_mw"].sum() / 1000,
                "cost $M": frame.groupby("owner")["cost_musd"].sum(),
                "cost $M withdrawn": gone.groupby("owner")["cost_musd"].sum(),
            }
        ).fillna(0)
        table.loc["All"] = table.sum()
        table["% requests withdrawn"] = 100 * table["withdrawn"] / table["requests"]
        table["% GW withdrawn"] = 100 * table["GW withdrawn"] / table["GW"].where(table["GW"] > 0)
        table["% cost withdrawn"] = 100 * table["cost $M withdrawn"] / table["cost $M"].where(table["cost $M"] > 0)
        return table.round(1).sort_values("requests", ascending=False)

    large_table = by_owner(needs[needs["large"]])
    large_table.to_csv(OUTPUT_DIR / "large_load_by_owner.csv")
    by_owner(needs).to_csv(OUTPUT_DIR / "customer_load_by_owner.csv")
    large_table
    return (large_table,)


@app.cell
def _(mo, needs):
    _large = needs[needs["large"]]
    _gone = _large[_large["withdrawn"]]
    _since = _large[_large["presented"] >= "2025-01-01"]
    mo.md(f"""
    **Time to withdrawal** (large loads): median {_gone["months_to_withdrawal"].median():.1f} months from first
    presentation, range {_gone["months_to_withdrawal"].min():.1f} to {_gone["months_to_withdrawal"].max():.1f};
    {int(_gone["solution_shown"].sum())} of the {len(_gone)} withdrawn had a solution presented first.

    **Cohort first presented in 2025 or later:** {len(_since)} large-load needs, {int(_since["withdrawn"].sum())}
    withdrawn ({100 * _since["withdrawn"].mean():.0f}%). The rest of the {len(_large)} were first presented
    before 2025 and still appear in 2025-26 decks.

    **Not yet resolved:** {int((~_large["withdrawn"] & ~_large["solution_shown"]).sum())} large-load needs have
    been presented but have no solution and no withdrawal in any deck so far.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Withdrawn, or resubmitted under a new number?

    A withdrawal isn't a dropout if the same request comes back under a new need number. For each withdrawn
    need we look at the owner's other customer-load needs presented after it (and numbered in the same year
    or later) that were not themselves
    withdrawn (if the replacement was withdrawn too, the load still left):

    - **resubmission**: the two name the same *new* substation (Dominion names each new delivery
      substation, such as Hera or Demeter, so a returning request would most likely keep its name), or the
      same area and a common existing substation. A common existing substation alone isn't enough: hubs
      like ComEd's Keslinger serve several unrelated requests.
    - **possible resubmission**: same area and MW within 25%, but no common substation. This is weak: many
      Dominion requests read "a data center campus in Prince William County... 300 MW", and one town can
      hold several customers (ComEd has two DeKalb needs).
    """)
    return


@app.cell
def _(OUTPUT_DIR, needs, pd, re, records):
    def place(text: object) -> str:
        return re.sub(r"[^A-Z]", "", re.sub(r"\b(COUNTY|AREA|CITY OF|SUBSTATION|STATION)\b", "", str(text).upper()))

    def names_by_need(column: str) -> pd.Series:
        named = records[["key", column]].explode(column).dropna()
        return named.assign(sub=named[column].map(place)).groupby("key")["sub"].agg(set)

    _new, _old = names_by_need("new_substations"), names_by_need("existing_substations")
    _pairs = []
    for _key, _w in needs[needs["withdrawn"]].iterrows():
        _later = needs[
            (needs["owner"] == _w["owner"])
            & (needs.index != _key)
            & (needs["presented"] > _w["presented"])
            & (needs.index.str.split("-").str[1] >= _key.split("-")[1])
            & ~needs["withdrawn"]
        ]
        for _other, _o in _later.iterrows():
            _same_area = place(_o["area"]) == place(_w["area"])
            _shared = sorted(_new.get(_key, set()) & _new.get(_other, set()))
            if _same_area:
                _shared += sorted(_old.get(_key, set()) & _old.get(_other, set()))
            _mw_close = bool(
                pd.notna(_w["ultimate_mw"])
                and pd.notna(_o["ultimate_mw"])
                and abs(_o["ultimate_mw"] - _w["ultimate_mw"]) <= 0.25 * _w["ultimate_mw"]
            )
            if not _shared and not (_same_area and _mw_close):
                continue
            _pairs.append(
                {
                    "withdrawn": _key,
                    "later": _other,
                    "area then": _w["area"],
                    "area later": _o["area"],
                    "MW then": _w["ultimate_mw"],
                    "MW later": _o["ultimate_mw"],
                    "common substation": "; ".join(_shared),
                    "resubmission": bool(_shared),
                }
            )
    _columns = ["withdrawn", "later", "area then", "area later", "MW then", "MW later", "common substation"]
    resubmissions = pd.DataFrame(_pairs, columns=[*_columns, "resubmission"])
    resubmissions.to_csv(OUTPUT_DIR / "resubmissions.csv", index=False)
    _large = set(needs.index[needs["large"]])
    _sure = set(resubmissions.loc[resubmissions["resubmission"], "withdrawn"])
    _maybe = set(resubmissions["withdrawn"]) - _sure
    print(
        f"{int(needs['withdrawn'].sum())} withdrawn customer-load needs: {len(_sure)} resubmitted under a new "
        f"number ({len(_sure & _large)} large), {len(_maybe)} more possibly ({len(_maybe & _large)} large)"
    )
    resubmissions
    return (resubmissions,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Are the named substations and lines on the public map?

    New substations (Coal City, Rowell, Hiawatha) aren't built, so no map can have them. We test only the
    existing ones the decks name as parents or as ends of a line being cut into. We reuse the method from
    `bpa-load-request-substations/` (#190): normalise the name, then look for the same name in the same state.

    - **HIFLD Next** has no substations layer, so as in #190 we use `us_substations_hifld_only.csv`: the
      substations derived from HIFLD Next line ends, with HIFLD's own `SUB_1`/`SUB_2` names.
    - **us-substations-verified** adds OpenStreetMap substations that HIFLD lacks.
    - **HIFLD Next transmission lines**: a line the decks say is cut into (for example "Dresden to Pontiac
      Midpoint 345 kV") counts as found if a HIFLD line has those two names as its `SUB_1` and `SUB_2`.

    The joined table (need, substation, coordinates) stays in `data/` and isn't committed; founders decide
    whether to publish it. Only counts and a county-level map are in `outputs/`.
    """)
    return


@app.cell
def _(DATA_DIR, fetch):
    import geopandas as gpd

    # The verified dataset as published on main (pinned to the commit that last changed it).
    _repo = "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/a9bdd882a5be0743ce80feb486bc05f1e9f44243"
    _hifld = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    hifld_subs_path = fetch(
        f"{_repo}/us-substations-verified/dataset/us_substations_hifld_only.csv", DATA_DIR / "hifld_only.csv"
    )
    verified_path = fetch(
        f"{_repo}/us-substations-verified/dataset/us_substations.parquet", DATA_DIR / "us_substations.parquet"
    )
    lines_path = fetch(
        f"{_hifld}/transmission-lines-1/transmission-lines-1/v1.0.0/geoparquet/transmission-lines-1.parquet",
        DATA_DIR / "transmission-lines.parquet",
    )
    counties_path = fetch(
        "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_20m.zip", DATA_DIR / "counties.zip"
    )
    return counties_path, gpd, hifld_subs_path, lines_path, verified_path


@app.cell
def _(gpd, hifld_subs_path, lines_path, needs, np, pd, re, records, verified_path):
    def norm(name: object) -> str:
        """Upper-case letters only, without words any substation name might carry."""
        text = re.sub(r"\(.*?\)|\b\d+\s?KV\b", " ", str(name).upper())
        text = re.sub(r"\b(SUBSTATION|SUB|STATION|SS|ENERGY CENTER|E\s?C|SWITCHING|SWITCHYARD|TSS)\b", " ", text)
        return re.sub(r"[^A-Z]", "", text)

    _hifld = pd.read_csv(hifld_subs_path, dtype={"fips": str})
    _verified_geo = gpd.read_parquet(verified_path)
    _verified = pd.DataFrame(_verified_geo.drop(columns="geometry")).assign(
        lon=_verified_geo.geometry.x, lat=_verified_geo.geometry.y
    )
    _sources = {"HIFLD Next": _hifld, "us-substations-verified": _verified}
    for _s in _sources.values():
        _s["key"] = _s["name"].map(norm)
    PJM_STATES = ["IL", "IN", "OH", "MI", "KY", "TN", "WV", "VA", "NC", "MD", "DE", "DC", "PA", "NJ"]

    _lines = pd.read_parquet(lines_path, columns=["SUB_1", "SUB_2"])
    _line_pairs = {frozenset((norm(a), norm(b))) for a, b in zip(_lines["SUB_1"], _lines["SUB_2"], strict=True)}

    _mine = records[records["key"].isin(needs.index) & ~records["stage"].eq("withdrawn")]
    _sub_rows, _line_rows = [], []
    for _r in _mine.itertuples():
        _state = needs.loc[_r.key, "state"]
        _states = [_state] if isinstance(_state, str) and len(_state) == 2 else PJM_STATES
        _named = list(_r.existing_substations) + [
            n for _c in _r.lines_cut_into for n in (_c["from_substation"], _c["to_substation"])
        ]
        for _name in dict.fromkeys(_named):
            _row = {"key": _r.key, "substation": _name, "norm": norm(_name)}
            for _label, _s in _sources.items():
                _hit = _s[(_s["key"] == _row["norm"]) & _s["state"].isin(_states)]
                _row[_label] = len(_hit) > 0
                _row[f"{_label} fips"] = _hit["fips"].iloc[0] if len(_hit) else None
                _row[f"{_label} lat"] = _hit["lat"].iloc[0] if len(_hit) else np.nan
                _row[f"{_label} lon"] = _hit["lon"].iloc[0] if len(_hit) else np.nan
            _sub_rows.append(_row)
        for _c in _r.lines_cut_into:
            _pair = frozenset((norm(_c["from_substation"]), norm(_c["to_substation"])))
            _line_rows.append(
                {
                    "key": _r.key,
                    "line": f"{_c['from_substation']} - {_c['to_substation']}",
                    "HIFLD Next line": _pair in _line_pairs,
                }
            )
    sub_matches = pd.DataFrame(_sub_rows).drop_duplicates(["key", "norm"])
    line_matches = pd.DataFrame(_line_rows).drop_duplicates(["key", "line"])
    return line_matches, sub_matches


@app.cell
def _(DATA_DIR, OUTPUT_DIR, line_matches, mo, needs, pd, sub_matches):
    sub_matches.to_csv(DATA_DIR / "substation_matches_with_coordinates.csv", index=False)
    _distinct = sub_matches.drop_duplicates("norm")
    _large = sub_matches[sub_matches["key"].isin(needs.index[needs["large"]])].drop_duplicates("norm")
    _lines = line_matches.drop_duplicates("line")
    map_coverage = pd.DataFrame(
        {
            "named (all customer-load needs)": [len(_distinct)] * 2,
            "found": [int(_distinct["HIFLD Next"].sum()), int(_distinct["us-substations-verified"].sum())],
            "named (large loads)": [len(_large)] * 2,
            "found (large)": [int(_large["HIFLD Next"].sum()), int(_large["us-substations-verified"].sum())],
        },
        index=["HIFLD Next", "us-substations-verified"],
    )
    map_coverage["% found"] = (100 * map_coverage["found"] / map_coverage["named (all customer-load needs)"]).round(1)
    map_coverage["% found (large)"] = (100 * map_coverage["found (large)"] / map_coverage["named (large loads)"]).round(
        1
    )
    map_coverage.to_csv(OUTPUT_DIR / "map_coverage.csv")
    _misses = _distinct.loc[~_distinct["us-substations-verified"], "substation"].head(25).tolist()
    print(
        f"Large-load needs name {len(_large)} existing substations: {int(_large['HIFLD Next'].sum())} in HIFLD Next, "
        f"{int(_large['us-substations-verified'].sum())} in us-substations-verified; {len(_lines)} lines cut into, "
        f"{int(_lines['HIFLD Next line'].sum())} found as a HIFLD Next line"
    )
    mo.vstack(
        [
            map_coverage,
            mo.md(
                f"Lines cut into: {len(_lines)} distinct, {int(_lines['HIFLD Next line'].sum())} "
                f"({100 * _lines['HIFLD Next line'].mean():.0f}%) found as a HIFLD Next line with both end names.\n\n"
                f"Some names neither source has under that name: {', '.join(map(str, _misses))}"
            ),
        ]
    )
    return (map_coverage,)


@app.cell
def _(mo):
    mo.md(r"""
    ### Where the requested MW sits

    Each large-load need is placed in the county of the first named parent substation found in
    us-substations-verified, and its ultimate MW is summed by county. Needs with no substation found
    aren't on the map. Withdrawn needs are shown on the right.
    """)
    return


@app.cell
def _(OUTPUT_DIR, counties_path, gpd, needs, pd, sub_matches):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _first = sub_matches.dropna(subset=["us-substations-verified fips"]).drop_duplicates("key")
    _placed = needs[needs["large"]].join(_first.set_index("key")["us-substations-verified fips"], how="inner")
    _placed = _placed.rename(columns={"us-substations-verified fips": "fips"})
    county_mw = _placed.groupby("fips").agg(
        requests=("ultimate_mw", "size"),
        GW=("ultimate_mw", lambda s: s.sum() / 1000),
        withdrawn=("withdrawn", "sum"),
        GW_withdrawn=("ultimate_mw", lambda s: s[_placed.loc[s.index, "withdrawn"]].sum() / 1000),
    )
    _counties = gpd.read_file(f"zip://{counties_path}")
    _counties = _counties[
        _counties["STUSPS"].isin(["IL", "IN", "OH", "MI", "KY", "TN", "WV", "VA", "NC", "MD", "DE", "DC", "PA", "NJ"])
    ].to_crs("EPSG:5070")
    _shown = _counties.merge(county_mw, left_on="GEOID", right_index=True, how="left")
    county_mw.join(_counties.set_index("GEOID")[["NAME", "STUSPS"]]).to_csv(OUTPUT_DIR / "large_load_gw_by_county.csv")
    _fig, _axes = plt.subplots(1, 2, figsize=(14, 6))
    for _ax, _col, _title in zip(
        _axes, ["GW", "GW_withdrawn"], ["Large-load GW requested", "Large-load GW withdrawn"], strict=True
    ):
        _counties.plot(ax=_ax, color="#eeeeee", edgecolor="white", linewidth=0.2)
        _shown[_shown[_col] > 0].plot(ax=_ax, column=_col, cmap="Oranges", legend=True, edgecolor="grey", linewidth=0.2)
        _ax.set_title(_title)
        _ax.set_axis_off()
    _fig.suptitle(f"PJM supplemental-project decks, {pd.Timestamp(needs['first_deck'].min()):%b %Y} to now, by county")
    _fig.tight_layout()
    _fig.savefig(OUTPUT_DIR / "large_load_map.png", dpi=150)
    _fig
    return (county_mw,)


@app.cell
def _(county_mw, extractions, large_table, map_coverage, mo, needs, resubmissions):
    _all = large_table.loc["All"]
    _large_keys = set(needs.index[needs["large"]])
    _back_large = len(set(resubmissions.loc[resubmissions["resubmission"], "withdrawn"]) & _large_keys)
    _maybe_large = len(set(resubmissions["withdrawn"]) & _large_keys) - _back_large
    _top = county_mw.sort_values("GW", ascending=False).head(3)
    mo.md(f"""
    ## Result

    Of **{int(_all["requests"])} large-load requests** (customer needs of 100 MW or more) in PJM's
    supplemental-project decks since January 2025, **{int(_all["withdrawn"])} ({_all["% requests withdrawn"]:.0f}%)
    were withdrawn**: {_all["GW withdrawn"]:.1f} of {_all["GW"]:.1f} GW requested
    ({_all["% GW withdrawn"]:.0f}%), and ${_all["cost $M withdrawn"]:,.0f}M of ${_all["cost $M"]:,.0f}M in
    estimated transmission cost ({_all["% cost withdrawn"]:.0f}%). {_back_large} of the withdrawn large-load
    needs came back under a new number with the same substation, and {_maybe_large} more possibly did.

    Of the existing substations those needs name, {map_coverage.loc["HIFLD Next", "% found (large)"]:.0f}%
    are in HIFLD Next and {map_coverage.loc["us-substations-verified", "% found (large)"]:.0f}% in
    us-substations-verified. The counties with the most requested MW hold {_top["GW"].sum():.1f} GW between them.

    Extraction cost ${sum(e["cost_usd"] for e in extractions):.2f}.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show, and what didn't work

    - **Only what the owners chose to present.** The decks cover projects under PJM's M-3 process. Loads
      served at distribution voltage, or through other processes, never appear.
    - **A withdrawal has to be on a slide.** A need that quietly never comes back counts as pending, not
      withdrawn. Most owners list withdrawals; some only drop a need from the next deck.
    - **Owners withdraw needs for different reasons.** ComEd and PECO say "withdraw need"; Dominion and
      APS list "cancellations", which can mean the need was folded into another project. We don't
      separate a customer walking away from a utility reshaping its plan.
    - **The 100 MW line is ours.** PJM has no large-load definition in these decks.
    - **Name matching is exact after clean-up.** A substation spelled differently on the slide and the
      map counts as missing; the list of misses above shows which.
    """)
    return


if __name__ == "__main__":
    app.run()
