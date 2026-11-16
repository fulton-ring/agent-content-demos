import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import re
    import time
    import zipfile
    from pathlib import Path

    import httpx
    import marimo as mo
    import pandas as pd
    from rapidfuzz import fuzz, process

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("PLANT_DEPS_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("PLANT_DEPS_OUTPUT_DIR", HERE / "outputs"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    STAC = "https://hifld.publicenvirodata.org/stac/collections/"
    EIA_860 = "https://www.eia.gov/electricity/data/eia860/xls/eia8602025.zip"
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # How many US power plants have a recorded upstream dependency in public data?

    A power plant depends on things upstream of it: the grid it feeds, the balancing authority that
    dispatches it, the gas company or pipeline that fuels it, and the river or well that cools it. Reading
    research for [#210](https://github.com/fulton-ring/agent-content-demos/issues/210) found that
    [HIFLD Next](https://hifld.publicenvirodata.org) records almost none of these links. EIA's annual
    generator survey, [Form EIA-860](https://www.eia.gov/electricity/data/eia860/), asks every plant for
    them. This notebook measures both on the same plants:

    1. What share of operating US plants have each upstream dependency recorded in EIA-860?
    2. How much of that does HIFLD Next's power plant layer carry?
    3. Do the gas pipelines EIA-860 names line up with HIFLD Next's natural gas pipeline layer?

    We publish only national, fuel and state counts. EIA already publishes the plant-level fields; this
    notebook doesn't add a new asset-level dependency table.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The data

    | Source | What we use | Version |
    |---|---|---|
    | HIFLD Next | `power-plants-1`, `natural-gas-interstate-and-intrastate-pipelines` (STAC API) | v1.0.0 |
    | EIA-860 | Schedule 2 (plants), 3.1 (operable generators), file layout | 2025, released Sept 2026 |

    Everything is downloaded into `data/` on the first run and reused after that. Nothing is committed.
    """)
    return


@app.cell
def _():
    def fetch(url: str, name: str) -> Path:
        """Download url into DATA/name once; later runs reuse the copy."""
        path = DATA / name
        if path.exists():
            return path
        response = httpx.get(url, follow_redirects=True, timeout=600, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        path.write_bytes(response.content)
        return path

    def stac_collection(dataset: str) -> dict:
        response = httpx.get(f"{STAC}hifld%2F{dataset}%2F{dataset}%2Fv1.0.0", timeout=60)
        response.raise_for_status()
        return response.json()

    return fetch, stac_collection


@app.cell
def _(fetch, stac_collection):
    _started = time.perf_counter()
    collections = {
        name: stac_collection(name) for name in ["power-plants-1", "natural-gas-interstate-and-intrastate-pipelines"]
    }
    _paths = {}
    for _name, _collection in collections.items():
        _parquet = [a["href"] for a in _collection["assets"].values() if a["type"] == "application/vnd.apache.parquet"]
        assert len(_parquet) == 1, f"{_name}: expected one GeoParquet asset, found {len(_parquet)}"
        _paths[_name] = fetch(_parquet[0], f"{_name}.parquet")
    _eia_zip = fetch(EIA_860, "eia8602025.zip")
    with zipfile.ZipFile(_eia_zip) as _z:
        _z.extractall(DATA / "eia8602025")
    eia_dir = DATA / "eia8602025"
    hifld_plants = pd.read_parquet(_paths["power-plants-1"]).drop(columns=["geometry", "bbox"])
    hifld_pipes = pd.read_parquet(
        _paths["natural-gas-interstate-and-intrastate-pipelines"], columns=["TYPEPIPE", "Operator"]
    )
    download_seconds = time.perf_counter() - _started
    print(f"HIFLD plants: {len(hifld_plants):,}; pipeline segments: {len(hifld_pipes):,}; {download_seconds:.1f}s")
    return collections, download_seconds, eia_dir, hifld_pipes, hifld_plants


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Step 1: which dependency fields does EIA-860 actually have?

    We don't assume the field list from the reading research. EIA ships a field directory with the data
    (`LayoutY2025.xlsx`). We pull every Schedule 2 (plant) field that names something outside the plant
    that the plant relies on.
    """)
    return


@app.cell
def _(eia_dir):
    _layout = pd.read_excel(eia_dir / "LayoutY2025.xlsx", sheet_name="Field Directory", header=2)
    _layout = _layout.rename(columns=lambda c: str(c).replace("\n", " "))
    _pattern = "balancing authority|water source|transmission or distribution|grid voltage|natural gas ldc|pipeline"
    eia_dependency_fields = _layout[
        _layout["Field Name"].str.contains(_pattern, case=False, na=False)
        & (_layout["Form EIA-860 Schedule"].astype(str) == "2")
    ][["Field Name", "Form EIA-860 Line Number", "Description"]]
    eia_dependency_fields
    return (eia_dependency_fields,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    All the fields the reading research listed exist, on Schedule 2. The EIA-860 instructions add two
    rules that change how we count:

    - **Water source** (line 6): plants that use no water for cooling or hydro enter `NA`, and planned
      plants may enter `UNK`. So a blank or `NA` is "no water dependency recorded", not missing data.
    - **Gas LDC and pipelines** (lines 16a and 16b): only plants with an existing gas-fired generator
      answer. So we measure those two only over gas-burning plants.

    We group the fields into six dependency types: grid owner (transmission or distribution owner),
    balancing authority, grid voltage, gas LDC, gas pipeline, and water source.
    """)
    return


@app.cell
def _(eia_dir):
    _plants = pd.read_excel(eia_dir / "2___Plant_Y2025.xlsx", header=1, dtype=str)
    _plants = _plants[_plants["Plant Code"].str.fullmatch(r"\d+", na=False)]
    generators = pd.read_excel(eia_dir / "3_1_Generator_Y2025.xlsx", sheet_name="Operable", header=1, dtype=str)
    generators = generators[generators["Plant Code"].str.fullmatch(r"\d+", na=False)]
    generators["mw"] = pd.to_numeric(generators["Nameplate Capacity (MW)"], errors="coerce").fillna(0)
    eia_plants = _plants.set_index("Plant Code")
    print(f"EIA-860 plants: {len(eia_plants):,}; operable generators: {len(generators):,}")
    return eia_plants, generators


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Step 2: operating plants and their fuel

    The plant schedule lists every plant with an operable, proposed or retired generator. We keep plants
    with at least one generator in status `OP` (operating). A plant's fuel is the energy source of its
    largest operating generator by nameplate capacity, grouped into nine fuel types. A plant counts as
    gas-burning if any operating generator lists natural gas (`NG`) as any of its six energy sources.
    """)
    return


@app.cell
def _(eia_plants, generators):
    _fuel_groups = {
        "Natural gas": {"NG"},
        "Coal": {"BIT", "SUB", "LIG", "ANT", "RC", "WC", "SGC", "PC"},
        "Petroleum": {"DFO", "RFO", "KER", "JF", "WO", "PG"},
        "Nuclear": {"NUC"},
        "Hydro": {"WAT"},
        "Wind": {"WND"},
        "Solar": {"SUN"},
        "Battery storage": {"MWH"},
    }
    _op = generators[generators["Status"] == "OP"]
    _largest = _op.sort_values("mw", ascending=False).drop_duplicates("Plant Code").set_index("Plant Code")
    _sources = _op[[f"Energy Source {i}" for i in range(1, 7)]]
    _burns_gas = _op.loc[(_sources == "NG").any(axis=1), "Plant Code"].unique()

    operating = eia_plants.loc[eia_plants.index.isin(_largest.index)].copy()
    operating["fuel"] = "Other"
    for _group, _codes in _fuel_groups.items():
        operating.loc[_largest.loc[operating.index, "Energy Source 1"].isin(_codes).to_numpy(), "fuel"] = _group
    operating["burns_gas"] = operating.index.isin(_burns_gas)
    print(f"{len(operating):,} operating plants, {operating['burns_gas'].sum():,} burn natural gas")
    operating["fuel"].value_counts()
    return (operating,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Step 3: share of operating plants with each dependency recorded in EIA-860

    A field counts as recorded when it holds a real value. Blanks, `NA`, `UNK`, `None`, and the
    "Other - see pipeline notes" placeholders don't count. For pipelines, a plant counts if any of its
    three pipeline fields or its pipeline notes names one.
    """)
    return


@app.cell
def _(operating):
    def recorded(column: str) -> pd.Series:
        values = operating[column].fillna("").str.strip()
        placeholder = values.str.fullmatch(r"(?i)|n/?a|unk(nown)?|none|0|other\b.*", na=True)
        return ~placeholder

    _pipe_columns = [f"Natural Gas Pipeline Name {i}" for i in (1, 2, 3)] + ["Pipeline Notes"]
    eia_has = pd.DataFrame(
        {
            "Grid owner": recorded("Transmission or Distribution System Owner"),
            "Balancing authority": recorded("Balancing Authority Code"),
            "Grid voltage": recorded("Grid Voltage (kV)"),
            "Gas LDC": recorded("Natural Gas LDC Name"),
            "Gas pipeline": pd.concat([recorded(c) for c in _pipe_columns], axis=1).any(axis=1),
            "Water source": recorded("Name of Water Source"),
        },
        index=operating.index,
    )
    eia_has["Gas LDC or pipeline"] = eia_has["Gas LDC"] | eia_has["Gas pipeline"]
    return eia_has, recorded


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Step 4: what HIFLD Next's power plant layer carries

    HIFLD Next's power plant layer is built from EIA-860 and EIA-923 (its `SOURCE` column says so), but it
    keeps a different set of columns. We read its schema from the STAC collection and look for any column
    that could hold one of the six dependencies. The candidates are `SUB_1` and `SUB_2`, the names of the
    substations a plant connects to, which partly stand in for the grid connection, and `LINES`, a count of
    connected transmission lines that names none of them. `NGAS_USED` is the amount of gas burned, not who
    supplies it. No column names a balancing authority, a grid owner,
    a gas supplier or a water source.
    """)
    return


@app.cell
def _(collections):
    hifld_columns = [c["name"] for c in collections["power-plants-1"]["table:columns"] if not c["is_geometry"]]
    _pattern = re.compile("sub|balanc|owner|volt|gas|pipe|water|ldc|grid|trans|line", re.IGNORECASE)
    print(f"{len(hifld_columns)} HIFLD columns: {', '.join(hifld_columns)}")
    print(f"Columns that could hold a dependency: {[c for c in hifld_columns if _pattern.search(c)]}")
    return (hifld_columns,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    We join HIFLD Next to EIA-860's operating plants on the plant code. A HIFLD substation name counts as
    recorded unless it's `NOT AVAILABLE`, blank, or one of the `UNKNOWN…`/`TAP…` placeholders.
    """)
    return


@app.cell
def _(eia_has, eia_plants, hifld_plants, operating):
    _hifld = hifld_plants.drop_duplicates("PLANT_CODE").set_index("PLANT_CODE")
    _sub = _hifld["SUB_1"].fillna("").str.strip().str.upper()
    _hifld_sub = ~(_sub.isin(["", "NOT AVAILABLE"]) | _sub.str.startswith(("UNKNOWN", "TAP")))
    in_hifld = operating.index.isin(_hifld.index)
    hifld_has = pd.DataFrame(False, index=operating.index, columns=eia_has.columns)
    hifld_has.loc[in_hifld, "Grid owner"] = _hifld_sub.reindex(operating.index[in_hifld]).to_numpy()
    join_failures = {
        "EIA-860 operating plants": len(operating),
        "found in HIFLD Next by plant code": int(in_hifld.sum()),
        "EIA operating plants missing from HIFLD Next": int((~in_hifld).sum()),
        "HIFLD plants whose code isn't in EIA-860 2025 at all": int((~_hifld.index.isin(eia_plants.index)).sum()),
        "HIFLD plants marked OP that EIA lists as not operating": int(
            ((_hifld["STATUS"] == "OP") & ~_hifld.index.isin(operating.index)).sum()
        ),
    }
    pd.Series(join_failures)
    return hifld_has, in_hifld, join_failures


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The result: EIA-860 against HIFLD Next

    Shares are of all operating plants, except the gas rows, which are of gas-burning plants. HIFLD's
    "Grid owner" column is its substation name, the closest thing it has; it names a substation, not the
    company that owns the grid.
    """)
    return


@app.cell
def _(eia_has, hifld_has, in_hifld, operating):
    _gas_only = {"Gas LDC", "Gas pipeline", "Gas LDC or pipeline"}
    _rows = []
    for _dep in eia_has.columns:
        _base = operating["burns_gas"] if _dep in _gas_only else pd.Series(True, index=operating.index)
        _both = _base & in_hifld
        _rows.append(
            {
                "dependency": _dep,
                "plants": int(_base.sum()),
                "EIA-860 recorded": int(eia_has.loc[_base, _dep].sum()),
                "EIA-860 share": round(100 * eia_has.loc[_base, _dep].mean(), 1),
                "HIFLD Next recorded": int(hifld_has.loc[_base, _dep].sum()),
                "HIFLD Next share": round(100 * hifld_has.loc[_base, _dep].mean(), 1),
                "share of the same plants in HIFLD, EIA": round(100 * eia_has.loc[_both, _dep].mean(), 1),
            }
        )
    headline = pd.DataFrame(_rows)
    _all_electric = ["Grid owner", "Balancing authority", "Grid voltage"]
    any_grid = eia_has[_all_electric].all(axis=1).mean()
    headline.to_csv(OUT / "headline.csv", index=False)
    print(headline.to_string(index=False))
    print(
        f"\nOperating plants with grid owner, balancing authority and grid voltage all recorded: {100 * any_grid:.1f}%"
    )
    headline
    return any_grid, headline


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### By fuel

    The share of operating plants of each fuel type with each dependency recorded in EIA-860. Gas columns
    are over the plants of that fuel type that burn gas, so they're blank where no plant does.
    """)
    return


@app.cell
def _(eia_has, hifld_has, operating):
    _gas_cols = ["Gas LDC", "Gas pipeline"]
    _by_fuel = eia_has.drop(columns=_gas_cols + ["Gas LDC or pipeline"]).groupby(operating["fuel"]).mean() * 100
    _gas = (
        eia_has.loc[operating["burns_gas"], _gas_cols].groupby(operating.loc[operating["burns_gas"], "fuel"]).mean()
        * 100
    )
    by_fuel = _by_fuel.join(_gas).round(1)
    by_fuel.insert(0, "plants", operating["fuel"].value_counts())
    by_fuel.insert(1, "gas-burning", operating.groupby("fuel")["burns_gas"].sum())
    by_fuel["HIFLD substation"] = (hifld_has["Grid owner"].groupby(operating["fuel"]).mean() * 100).round(1)
    by_fuel = by_fuel.sort_values("plants", ascending=False)
    by_fuel.to_csv(OUT / "by_fuel.csv")
    print(by_fuel.to_string())
    by_fuel
    return (by_fuel,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### By state

    Grid owner and gas pipeline shares by state, with the HIFLD substation share alongside.
    """)
    return


@app.cell
def _(eia_has, hifld_has, operating):
    _gas = operating["burns_gas"]
    by_state = pd.DataFrame(
        {
            "plants": operating.groupby("State").size(),
            "EIA grid owner %": eia_has["Grid owner"].groupby(operating["State"]).mean() * 100,
            "HIFLD substation %": hifld_has["Grid owner"].groupby(operating["State"]).mean() * 100,
            "gas-burning plants": _gas.groupby(operating["State"]).sum(),
            "EIA gas LDC or pipeline %": eia_has.loc[_gas, "Gas LDC or pipeline"]
            .groupby(operating.loc[_gas, "State"])
            .mean()
            * 100,
        }
    ).round(1)
    by_state.to_csv(OUT / "by_state.csv")
    by_state.sort_values("plants", ascending=False).head(15)
    return (by_state,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Step 5: do EIA's pipeline names appear in HIFLD Next's pipeline layer?

    EIA-860 names the company that owns or operates each pipeline connected to a gas plant. HIFLD Next's
    natural gas pipeline layer has an `Operator` on each segment. If the two named pipelines the same way,
    a reader could join a gas plant to the pipeline map by name, a cross-sector link. HIFLD abbreviates
    heavily (`Transcontinental Gas PL`, `Florida Gas Trans Co`) where EIA spells names out
    (`TRANSCONTINENTAL GAS PIPELINE`, `FLORIDA GAS TRANSMISSION COMPANY`), so we normalize both sides first:
    upper case, no punctuation, common abbreviations expanded, and corporate suffixes dropped.

    We then match in three passes: an exact match on the normalized name; then a match on the *core* name,
    with generic words such as GAS, PIPELINE and TRANSMISSION removed, when exactly one HIFLD operator has
    that core; and for the rest a fuzzy match (rapidfuzz `token_sort_ratio` of at least 90) to the closest
    HIFLD operator. Every fuzzy match is
    printed below so it can be checked by eye.
    """)
    return


@app.cell
def _():
    _expand = {
        "TRANS": "TRANSMISSION",
        "TRANSM": "TRANSMISSION",
        "PL": "PIPELINE",
        "AM": "AMERICA",
        "NAT": "NATURAL",
        "PUB": "PUBLIC",
    }
    _drop = {
        "CO",
        "COMPANY",
        "LLC",
        "LP",
        "INC",
        "CORP",
        "CORPORATION",
        "INCORPORATED",
        "THE",
        "OF",
        "SYSTEM",
        "SYSTEMS",
        "SYS",
        "LTD",
        "US",
    }
    _generic = {
        "GAS",
        "NATURAL",
        "PIPELINE",
        "TRANSMISSION",
        "ENERGY",
        "INTRASTATE",
        "INTERSTATE",
        "TRANSPORTATION",
    }

    def normalize(name: str) -> str:
        name = re.sub(r"\bP\s*L\b|\bPIPE LINE\b", "PL", name.upper().replace("&", " AND "))
        tokens = re.sub(r"[^A-Z0-9 ]", " ", name).split()
        return " ".join(_expand.get(t, t) for t in tokens if t not in _drop)

    def core(normalized: str) -> str:
        return " ".join(t for t in normalized.split() if t not in _generic and t != "AND")

    return core, normalize


@app.cell
def _(core, eia_has, hifld_pipes, normalize, operating, recorded):
    _hifld_names = {normalize(n): n for n in hifld_pipes["Operator"].dropna().unique()}
    _hifld_cores = {}
    for _norm, _orig in _hifld_names.items():
        _hifld_cores.setdefault(core(_norm), []).append(_orig)
    _names = []
    for _col in [f"Natural Gas Pipeline Name {i}" for i in (1, 2, 3)]:
        _ok = recorded(_col) & operating["burns_gas"]
        _names.append(pd.DataFrame({"plant": operating.index[_ok], "eia_name": operating.loc[_ok, _col].str.strip()}))
    plant_pipes = pd.concat(_names, ignore_index=True)
    _unique = pd.DataFrame({"eia_name": plant_pipes["eia_name"].unique()})
    _unique["normalized"] = _unique["eia_name"].map(normalize)

    def best_hifld(name: str) -> tuple[str, str, float]:
        if name in _hifld_names:
            return "exact", _hifld_names[name], 100.0
        candidates = _hifld_cores.get(core(name), [])
        if core(name) and len(candidates) == 1:
            return "core", candidates[0], 100.0
        hit = process.extractOne(name, list(_hifld_names), scorer=fuzz.token_sort_ratio)
        assert hit is not None
        return ("fuzzy" if hit[1] >= 90 else "none"), _hifld_names[hit[0]], round(hit[1], 1)

    _unique[["match", "closest_hifld", "score"]] = pd.DataFrame(_unique["normalized"].map(best_hifld).tolist())
    pipe_names = _unique
    plant_pipes = plant_pipes.merge(pipe_names[["eia_name", "match"]], on="eia_name")
    _plants_naming = int(eia_has.loc[operating["burns_gas"], "Gas pipeline"].sum())
    _tiers = ["exact", "core", "fuzzy", "none"]
    _by_plant = plant_pipes.groupby("plant")["match"].agg(lambda m: min(m, key=_tiers.index))
    _plant_tiers = _by_plant.value_counts().to_dict()
    pipe_match = {
        "gas plants naming a pipeline company (fields 1-3 or notes)": _plants_naming,
        "gas plants naming one in fields 1-3": int(_by_plant.size),
        "of those, at least one name matches HIFLD exactly": int(_plant_tiers.get("exact", 0)),
        "of those, best match is on the core name": int(_plant_tiers.get("core", 0)),
        "of those, best match is fuzzy": int(_plant_tiers.get("fuzzy", 0)),
        "of those, no name matches": int(_plant_tiers.get("none", 0)),
        "distinct EIA pipeline names": len(pipe_names),
        "distinct names matched exactly": int((pipe_names["match"] == "exact").sum()),
        "distinct names matched on the core name": int((pipe_names["match"] == "core").sum()),
        "distinct names matched fuzzily": int((pipe_names["match"] == "fuzzy").sum()),
        "distinct names unmatched": int((pipe_names["match"] == "none").sum()),
        "distinct HIFLD operators": len(_hifld_names),
    }
    print(json.dumps(pipe_match, indent=2))
    pd.Series(pipe_match)
    return pipe_match, pipe_names, plant_pipes


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Every core-name and fuzzy match, to check by eye. A wrong one here means those counts are too
    generous.
    """)
    return


@app.cell
def _(pipe_names, plant_pipes):
    _plants_per_name = plant_pipes.groupby("eia_name")["plant"].nunique().rename("plants")
    pipe_names_out = pipe_names.join(_plants_per_name, on="eia_name").sort_values("plants", ascending=False)
    pipe_names_out.to_csv(OUT / "pipeline_name_matches.csv", index=False)
    _loose = pipe_names_out[pipe_names_out["match"].isin(["core", "fuzzy"])]
    print(_loose.to_string(index=False))
    _loose
    return (pipe_names_out,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Hand review: wrong fuzzy matches and why names don't match

    We checked every fuzzy match and the 25 unmatched names with the most plants by hand, and wrote the
    verdicts to `hand_review.csv`: each name, a verdict and a one-line note. The verdicts are:

    - **correct match** / **wrong match**: for fuzzy matches. Only correct ones count as matched.
    - **renamed or respelled**: the layer has the same pipeline under an older name, a parent company's
      name or a different spelling.
    - **gas utility**: the plant entered its local gas utility in the pipeline field. HIFLD's
      interstate and intrastate layer doesn't cover distribution utilities.
    - **midstream or storage**: a gathering, processing or storage company the layer doesn't cover.
    - **not in layer**: a transmission pipeline we couldn't find in the layer under any name.
    """)
    return


@app.cell
def _(pipe_names_out, plant_pipes):
    _review = pd.read_csv(HERE / "hand_review.csv")
    _reviewed = pipe_names_out.merge(_review, on="eia_name", how="left")
    _missing = _reviewed[(_reviewed["match"] == "fuzzy") & _reviewed["verdict"].isna()]
    assert _missing.empty, f"fuzzy matches without a hand verdict: {_missing['eia_name'].tolist()}"
    _reviewed["outcome"] = _reviewed["match"].map({"exact": "matched", "core": "matched"})
    _reviewed.loc[_reviewed["verdict"] == "correct match", "outcome"] = "matched"
    _reviewed["outcome"] = _reviewed["outcome"].fillna(_reviewed["verdict"]).fillna("not reviewed")
    _reviewed.loc[_reviewed["outcome"] == "wrong match", "outcome"] = "not in layer"

    _order = [
        "matched",
        "renamed or respelled",
        "gas utility",
        "midstream or storage",
        "not in layer",
        "not reviewed",
    ]
    _links = plant_pipes.merge(_reviewed[["eia_name", "outcome"]], on="eia_name")
    _by_plant = _links.groupby("plant")["outcome"].agg(lambda o: min(o, key=_order.index))
    pipe_outcomes = (
        pd.DataFrame(
            {
                "distinct names": _reviewed["outcome"].value_counts(),
                "gas plants (best outcome)": _by_plant.value_counts(),
            }
        )
        .reindex(_order)
        .fillna(0)
        .astype(int)
    )
    pipe_outcomes["share of plants %"] = (100 * pipe_outcomes["gas plants (best outcome)"] / _by_plant.size).round(1)
    pipe_outcomes.to_csv(OUT / "pipeline_outcomes.csv")
    print(pipe_outcomes.to_string())
    pipe_outcomes
    return (pipe_outcomes,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Run summary

    Every number in the README comes from `outputs/summary.json`, written here.
    """)
    return


@app.cell
def _(any_grid, download_seconds, headline, join_failures, pipe_match, pipe_outcomes):
    summary = {
        "headline": headline.to_dict(orient="records"),
        "all_three_grid_fields_share": round(100 * any_grid, 1),
        "join": join_failures,
        "pipeline_match": pipe_match,
        "pipeline_outcomes": pipe_outcomes.to_dict(orient="index"),
        "download_seconds": round(download_seconds, 1),
        "run_seconds": round(time.perf_counter() - RUN_STARTED, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Run time {summary['run_seconds']}s (downloads {summary['download_seconds']}s)")
    return (summary,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this doesn't show

    - **Recorded isn't verified.** EIA-860 holds what plant operators report. We count whether a field is
      filled in, not whether it's right.
    - **A name isn't a location.** EIA names a grid owner and a pipeline company, not the substation or
      the pipeline segment. Even a matched pipeline company only says which network, not where the plant
      taps it.
    - **Upstream only.** We don't count what depends on each plant, or second-order links (the gas
      pipeline's own power supply).
    - **Fuel is the largest generator's.** A plant with gas and solar counts under its larger unit.
    """)
    return


if __name__ == "__main__":
    app.run()
