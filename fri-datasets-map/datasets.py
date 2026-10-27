import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import warnings
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import pandas as pd
    from fri_rebuild import data, scoring

    here = Path(__file__).resolve().parent
    rebuild_results = here.parent / "fri-agent-rebuild" / "results"
    hurloss_results = here.parent / "hurloss-public-rebuild" / "results"
    out = here / "data"
    map_data = here / "map" / "data"
    out.mkdir(exist_ok=True)
    map_data.mkdir(parents=True, exist_ok=True)
    return (
        data,
        gpd,
        hurloss_results,
        json,
        map_data,
        mo,
        out,
        pd,
        rebuild_results,
        scoring,
        warnings,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # FEMA's frozen climate risk multipliers, as open county datasets

    **What this is.** FEMA's Future Risk Index (FRI, December 2024) multiplied each county's
    expected annual loss (EAL) by a *hazard multiplier* (HM) for five hazards and four futures:
    mid and late century, lower and higher warming. FEMA took the tool down in February 2025 and
    has told GAO it plans no update to the National Risk Index, so these are the last numbers
    anyone will get. Two spikes in this repo rebuilt them from public data:
    `fri-agent-rebuild/` (drought, wildfire, extreme heat, coastal flooding) and
    `hurloss-public-rebuild/` (hurricane). This notebook puts FEMA's values and ours side by
    side, county by county, as files anyone can download, and builds the data for the map in
    `map/`.

    **What it doesn't do.** It reruns nothing expensive. It reads the two spikes' committed
    `results/` folders, plus FEMA's master datasheet and two small public files (county
    boundaries and NRI v1.18.1's coastal losses), downloaded at run time.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## FEMA's numbers and ours

    FEMA's multipliers come from the master datasheet saved before the takedown
    ([fulton-ring/nri-future-risk](https://github.com/fulton-ring/nri-future-risk) at
    `c5cc0d6`), loaded with the rebuild's own loader. Ours come from
    `fri-agent-rebuild/results/rebuild/county_hm.csv`, which that spike's `run.sh` writes from
    each hazard's final pipeline. The held-out flag is the rebuild's split: every fourth state
    in FIPS order, which the agents never saw scores for.
    """)
    return


@app.cell
def _(data, pd, rebuild_results, scoring):
    key = data.answer_key()
    rebuilt = pd.read_csv(rebuild_results / "rebuild" / "county_hm.csv", dtype={"fips": str})
    rebuilt = rebuilt.set_index("fips")
    hazards = {
        "DRGT": "Drought",
        "WFIR": "Wildfire",
        "EXHT_L95": "Extreme heat, LOCA2, 95th percentile",
        "EXHT_L99": "Extreme heat, LOCA2, 99th percentile",
        "EXHT_N95": "Extreme heat, NEX, 95th percentile",
        "EXHT_N99": "Extreme heat, NEX, 99th percentile",
        "CFLD": "Coastal flooding",
    }
    columns = [f"{h}_{s}_HM" for h in hazards for s in scoring.SCENARIOS]
    assert set(columns) <= set(rebuilt.columns), "county_hm.csv is missing a column"
    assert rebuilt.index.isin(key.index).all(), "a rebuilt county is not in FEMA's datasheet"

    _split = scoring.split(data.conus(key).index)
    _fema = key[columns].stack(future_stack=True).rename("fema_hm")
    _ours = rebuilt[columns].stack(future_stack=True).rename("rebuilt_hm")
    multipliers = (
        pd.concat([_fema, _ours], axis=1)
        .rename_axis(["fips", "column"])
        .reset_index()
        .assign(
            hazard=lambda t: t["column"].str.rsplit("_", n=3).str[0],
            scenario=lambda t: t["column"].str.split("_").str[-3:-1].str.join("_"),
        )
    )
    multipliers = multipliers.assign(
        hazard_name=multipliers["hazard"].map(hazards),
        state=multipliers["fips"].map(key["STATEABBRV"]),
        county=multipliers["fips"].map(key["COUNTY"]),
        held_out=multipliers["fips"].map(_split.eq("held_out")),
    )[
        [
            "fips",
            "state",
            "county",
            "hazard",
            "hazard_name",
            "scenario",
            "fema_hm",
            "rebuilt_hm",
            "held_out",
        ]
    ]
    multipliers.groupby("hazard_name", sort=False).agg(
        counties=("fips", "nunique"),
        fema_values=("fema_hm", "count"),
        rebuilt_values=("rebuilt_hm", "count"),
    )
    return columns, hazards, key, multipliers, rebuilt


@app.cell
def _(mo):
    mo.md(r"""
    Every county FEMA published is a row, with blanks where FEMA published none (coastal
    flooding away from the coast) or where we rebuilt none. The rebuild covers the contiguous
    US only, so Alaska, Hawaii and the territories have FEMA's values and no rebuilt ones, and
    no held-out flag.

    ## The constant baseline

    A rebuild is only worth something if it beats a guess that knows nothing about the county.
    The guess here is one number per column: the median of FEMA's multipliers over the training
    states (counties FEMA published at HM = 0 left out, as the scorer leaves them out), given
    to every held-out county. It is scored with the rebuild's own scorer,
    `fri_rebuild.scoring`, and averaged over scenarios (and, for heat, both thresholds) the way
    the rebuild's `headline.csv` averages its own scores. The Draft job worked these out by hand
    on 2026-10-19; the last two columns check this code against those figures.
    """)
    return


@app.cell
def _(data, key, pd, rebuild_results, scoring, warnings):
    _groups = {
        "Drought": ["DRGT"],
        "Wildfire": ["WFIR"],
        "Extreme heat, LOCA2": ["EXHT_L95", "EXHT_L99"],
        "Extreme heat, NEX": ["EXHT_N95", "EXHT_N99"],
        "Coastal flooding": ["CFLD"],
    }
    _draft_job = {
        "Drought": (0.819, 0.443),
        "Wildfire": (0.931, 0.194),
        "Extreme heat, LOCA2": (0.794, 0.545),
        "Extreme heat, NEX": (0.841, 0.393),
        "Coastal flooding": (0.786, 0.605),
    }
    _conus = data.conus(key)
    _labels = scoring.split(_conus.index)
    _held_out = _conus[_labels == "held_out"]
    _rows = []
    for _name, _prefixes in _groups.items():
        for _column in [f"{p}_{s}_HM" for p in _prefixes for s in scoring.SCENARIOS]:
            _train = _conus.loc[_labels == "train", _column]
            _median = float(_train[_train > 0].median())
            _constant = pd.Series(_median, index=_held_out.index)
            # A constant has no correlation; the scorer's Pearson and Spearman warn and give NaN.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _metrics, _ = scoring.score_column(_held_out, _constant, _column)
            _rows.append({"hazard": _name, "column": _column, "train_median": _median} | _metrics)
    baseline_columns = pd.DataFrame(_rows)

    _headline = pd.read_csv(rebuild_results / "rebuild" / "headline.csv", index_col=[0, 1])
    _rebuilt = _headline.xs("held_out", level=1)
    baseline = (
        baseline_columns.groupby("hazard", sort=False)
        .agg(
            counties=("counties", "first"),
            baseline_same_bin=("same_bin", "mean"),
            baseline_log_mae=("log_mae", "mean"),
        )
        .assign(
            rebuilt_same_bin=_rebuilt["same_bin"],
            rebuilt_log_mae=_rebuilt["log_mae"],
            draft_job_same_bin=lambda t: t.index.map(lambda h: _draft_job[h][0]),
            draft_job_log_mae=lambda t: t.index.map(lambda h: _draft_job[h][1]),
        )
    )
    baseline = baseline.assign(
        matches_draft_job=(baseline["baseline_same_bin"].round(3) == baseline["draft_job_same_bin"])
        & (baseline["baseline_log_mae"].round(3) == baseline["draft_job_log_mae"])
    )
    baseline.round(3)
    return baseline, baseline_columns


@app.cell
def _(baseline, mo):
    _beaten = baseline[baseline["rebuilt_same_bin"] > baseline["baseline_same_bin"]].index
    _cfld = baseline.loc["Coastal flooding"]
    mo.md(f"""
    All five match the Draft job's figures: {int(baseline["matches_draft_job"].sum())} of
    {len(baseline)}. The rebuild beats the constant on {len(_beaten)} of {len(baseline)} hazards
    by same-bin share ({", ".join(_beaten)}). Coastal flooding is the exception: the constant gets
    {_cfld["baseline_same_bin"]:.1%} same bin against the rebuild's
    {_cfld["rebuilt_same_bin"]:.1%}, and a mean log error of {_cfld["baseline_log_mae"]:.3f}
    against the rebuild's {_cfld["rebuilt_log_mae"]:.3f}. So the coastal finding rests on the
    forensics below, not on the rebuild.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The coastal flags

    Two groups of counties stand out in FEMA's coastal flooding column, both counted on issue
    #42 from FEMA's own datasheet:

    - **120 counties** have coastal flood EAL > 0 in NRI v1.19.0 and a multiplier of exactly 0
      in all four scenarios, which wipes out their projected coastal loss.
    - **17 counties** have a multiplier between 0 and 1 in at least one scenario, so sea level
      rise *lowers* their projected loss. Coastal flooding is the only hazard whose column goes
      below 1.

    For each, we add whether the county already had coastal flood losses in the previous NRI
    release, v1.18.1 (November 2021), read from FEMA's own v1.18.1 county service on ArcGIS
    Online, which FEMA still serves.
    """)
    return


@app.cell
def _(data, json, key, pd):
    _url = (
        "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
        "NRI_Counties_Prod_v1181_view/FeatureServer/0/query"
        "?where=CFLD_EALT%3E0&outFields=STCOFIPS,CFLD_EALT&returnGeometry=false&f=json"
        "&resultRecordCount=2000"
    )
    _saved = data.download(_url, data.cache("datasets", "nri_v1_18_1_cfld.json"))
    _response = json.loads(_saved.read_text())
    assert "features" in _response and not _response.get("exceededTransferLimit"), _response
    _v1181 = pd.Series(
        {f["attributes"]["STCOFIPS"]: f["attributes"]["CFLD_EALT"] for f in _response["features"]}
    )

    _hm = key[[f"CFLD_{s}_HM" for s in ("MID_LOWER", "MID_HIGHER", "LATE_LOWER", "LATE_HIGHER")]]
    _has_loss = key["CFLD_EALT"] > 0
    _zero = _has_loss & (_hm == 0).all(axis=1)
    _below_one = _has_loss & ((_hm > 0) & (_hm < 1)).any(axis=1)
    _flags = key.loc[_zero | _below_one, ["STATEABBRV", "COUNTY", "CFLD_EALT", *_hm.columns]]
    coastal = (
        _flags.rename(columns=str.lower)
        .rename(columns={"stateabbrv": "state", "cfld_ealt": "cfld_eal_v1_19_0"})
        .rename_axis("fips")
        .reset_index()
    )
    coastal = coastal.assign(
        flag=coastal["fips"].map(lambda f: "zero_all_scenarios" if _zero[f] else "between_0_and_1"),
        cfld_eal_v1_18_1=coastal["fips"].map(_v1181),
        had_loss_v1_18_1=coastal["fips"].isin(_v1181.index),
    )
    pd.crosstab(coastal["flag"], coastal["had_loss_v1_18_1"], margins=True)
    return (coastal,)


@app.cell
def _(coastal, mo):
    _zero = coastal[coastal["flag"] == "zero_all_scenarios"]
    _in, _out = int(_zero["had_loss_v1_18_1"].sum()), int((~_zero["had_loss_v1_18_1"]).sum())
    mo.md(f"""
    **The split is {_out} / {_in}, not #42's 70 / 50.** Of the {len(_zero)} zeros, {_out}
    gained coastal flood loss only in v1.19.0 and {_in} had it in v1.18.1 too. Issue #42 used
    the same FEMA service and reported 70 and 50; its code isn't committed, so the one county
    can't be traced. The third-party v1.18.1 copy that `fri-agent-rebuild/notebooks/coastal.py`
    uses also gives {_in} for the states. Matching is by county FIPS, so a county whose code
    changed between releases counts as having no v1.18.1 loss. Either way, most zeros are
    counties that were new to coastal flooding in v1.19.0, and a large minority are not.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Hurricane: FEMA's multipliers next to our open layer

    FEMA's hurricane input (ARA's climate-conditioned HurLoss) isn't public, so
    `hurloss-public-rebuild/` built an open layer instead: FEMA's documented equations with no
    factor of 2, on two public storm catalogues, with Knutson et al.'s projected changes. Its
    range spans both catalogues and every published Knutson percentile. Its comparison table
    covers the 2,219 counties where FEMA rated hurricane loss today.

    That table floors FEMA's value at 1 for its own comparison, so it shows 1 where FEMA's
    datasheet has 0, the code FEMA uses for "No Rating" (`HRCN_<scenario>_DELTAR`). We take
    `fema_hm` straight from the datasheet instead, keep the table's value as `fema_hm_floored`,
    and flag the No Rating counties: between 614 and 640 of the 2,219, depending on the
    scenario. We also flag FEMA's ~2.0 band (1.9 to 2.1). Of the rated counties above 1,
    95-97% are in the band in three scenarios, and about a third in late century, higher
    warming, where FEMA's values spread upward.
    """)
    return


@app.cell
def _(hurloss_results, key, pd):
    _table = pd.read_csv(
        hurloss_results / "layer" / "fri_comparison_by_county.csv", dtype={"STCOFIPS": str}
    )
    hurricane = _table.rename(columns={"STCOFIPS": "fips", "fema_hm": "fema_hm_floored"})
    _scenarios = hurricane["scenario"].unique()
    _sheet = pd.DataFrame(
        {
            "fema_hm": key[[f"HRCN_{s}_HM" for s in _scenarios]]
            .set_axis(_scenarios, axis=1)
            .stack(),
            "fema_no_rating": key[[f"HRCN_{s}_DELTAR" for s in _scenarios]]
            .set_axis(_scenarios, axis=1)
            .stack()
            .eq("No Rating"),
        }
    ).rename_axis(["fips", "scenario"])
    hurricane = hurricane.join(_sheet, on=["fips", "scenario"], validate="one_to_one")
    assert (hurricane["fema_no_rating"] == (hurricane["fema_hm"] == 0)).all(), (
        "FEMA's 0 should mean No Rating, and only that"
    )
    _gap = (hurricane["fema_hm_floored"] - hurricane["fema_hm"].clip(lower=1)).abs()
    assert (_gap <= 5e-6 + 1e-12).all(), (
        "the hurloss table should differ from the datasheet only by the floor at 1"
        " and rounding to 5 decimals"
    )
    hurricane = hurricane.assign(
        fema_within_our_range=hurricane["fema_within_our_range"].where(
            ~hurricane["fema_no_rating"]
        ),
        fema_in_2_band=hurricane["fema_hm"].between(1.9, 2.1),
    )[
        [
            "fips",
            "state",
            "county",
            "scenario",
            "fema_hm",
            "fema_no_rating",
            "fema_hm_floored",
            "our_hm",
            "our_hm_low",
            "our_hm_high",
            "our_covered",
            "fema_within_our_range",
            "fema_in_2_band",
        ]
    ]
    assert hurricane["fips"].nunique() == 2219, "the comparison should cover 2,219 counties"
    hurricane.assign(
        above_1=hurricane["fema_hm"] > 1,
        in_band_above_1=hurricane["fema_in_2_band"].where(hurricane["fema_hm"] > 1),
    ).groupby("scenario", sort=False).agg(
        counties=("fips", "count"),
        fema_no_rating=("fema_no_rating", "sum"),
        fema_at_1=("fema_hm", lambda hm: (hm == 1).sum()),
        fema_above_1=("above_1", "sum"),
        fema_median_rated=("fema_hm", lambda hm: hm[hm > 0].median()),
        ours_median=("our_hm", "median"),
        fema_in_2_band_above_1=("in_band_above_1", "mean"),
        fema_within_our_range=("fema_within_our_range", "mean"),
    ).round(3)
    return (hurricane,)


@app.cell
def _(mo):
    mo.md(r"""
    ## The files

    Written to `data/`, described column by column in `data/DATA_DICTIONARY.md`:

    - `multipliers_by_county.csv`: FEMA's and our multipliers, one row per county, hazard and
      scenario.
    - `coastal_flags.csv`: the 120 zeros and 17 values below 1.
    - `hurricane_by_county.csv`: FEMA's hurricane multipliers next to our open layer.
    - `baseline_scores.csv` and `baseline_by_column.csv`: the constant baseline above.
    - `counties.parquet`: all of it, one row per county, with Census 2020 county shapes, as
      GeoParquet.
    """)
    return


@app.cell
def _(baseline, baseline_columns, coastal, hurricane, multipliers, out):
    multipliers.to_csv(out / "multipliers_by_county.csv", index=False)
    coastal.to_csv(out / "coastal_flags.csv", index=False)
    hurricane.to_csv(out / "hurricane_by_county.csv", index=False)
    baseline.to_csv(out / "baseline_scores.csv")
    baseline_columns.to_csv(out / "baseline_by_column.csv", index=False)
    return


@app.cell
def _(coastal, columns, data, gpd, hurricane, key, multipliers, out, pd):
    _shapes_url = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_20m.zip"
    shapes = data.census_shapes(_shapes_url, "counties_2020_20m").set_index("GEOID")
    _wide_hurricane = hurricane.pivot(
        index="fips", columns="scenario", values=["fema_hm", "our_hm", "our_hm_low", "our_hm_high"]
    )
    _wide_hurricane.columns = [f"HRCN_{s}_{v.upper()}" for v, s in _wide_hurricane.columns]
    _rebuilt = multipliers.pivot(index="fips", columns=["hazard", "scenario"], values="rebuilt_hm")
    _rebuilt.columns = [f"{h}_{s}_REBUILT_HM" for h, s in _rebuilt.columns]
    wide = pd.concat(
        [
            key[["STATEABBRV", "COUNTY", "CFLD_EALT"]],
            multipliers.drop_duplicates("fips").set_index("fips")["held_out"],
            key[columns].rename(columns=lambda c: c.replace("_HM", "_FEMA_HM")),
            _rebuilt,
            _wide_hurricane,
            coastal.set_index("fips")[["flag", "had_loss_v1_18_1"]].add_prefix("cfld_"),
        ],
        axis=1,
    ).rename_axis("fips")
    counties = gpd.GeoDataFrame(wide.join(shapes[["geometry"]], how="inner"), crs=shapes.crs)
    counties.to_parquet(out / "counties.parquet")
    _missing = wide.index.difference(counties.index)
    print(f"{len(counties)} counties with shapes; {len(_missing)} without: {list(_missing)}")
    return (counties,)


@app.cell
def _(mo):
    mo.md(r"""
    ## The map's data

    The map in `map/` reads one GeoJSON file: the same county shapes, coordinates rounded to
    four decimals (about 10 m), and per county only what the map draws. For each hazard and
    scenario, `v` holds `[FEMA, ours]`; hurricane adds our low and high. `flag` marks the
    coastal counties above, and `ho` the held-out ones.
    """)
    return


@app.cell
def _(coastal, counties, hazards, hurricane, json, map_data, multipliers, pd):
    def rounded(value: float) -> float | None:
        return None if pd.isna(value) else round(float(value), 3)

    _values: dict[str, dict[str, list]] = {}
    for _row in multipliers.itertuples():
        _values.setdefault(_row.fips, {})[f"{_row.hazard}_{_row.scenario}"] = [
            rounded(_row.fema_hm),
            rounded(_row.rebuilt_hm),
        ]
    for _row in hurricane.itertuples():
        _values.setdefault(_row.fips, {})[f"HRCN_{_row.scenario}"] = [
            rounded(_row.fema_hm),
            rounded(_row.our_hm),
            rounded(_row.our_hm_low),
            rounded(_row.our_hm_high),
        ]
    _flags = coastal.set_index("fips")["flag"]
    _geometry = json.loads(counties.geometry.set_precision(1e-4).to_json(drop_id=True))
    _features = []
    for _fips, _feature in zip(counties.index, _geometry["features"], strict=True):
        _feature["properties"] = {
            "fips": _fips,
            "name": f"{counties.at[_fips, 'COUNTY']}, {counties.at[_fips, 'STATEABBRV']}",
            "ho": counties.at[_fips, "held_out"] == True,  # noqa: E712 - blank outside CONUS
            "flag": _flags.get(_fips),
            "v": _values.get(_fips, {}),
        }
        _features.append(_feature)
    _meta = {"hazards": hazards | {"HRCN": "Hurricane"}}
    _collection = {"type": "FeatureCollection", "meta": _meta, "features": _features}
    _text = json.dumps(_collection, separators=(",", ":"))
    (map_data / "counties.geojson").write_text(_text)
    print(f"map/data/counties.geojson: {len(_features)} counties, {len(_text) / 1e6:.1f} MB")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **The rebuilt multipliers are a reconstruction, not FEMA's.** Drought, LOCA2 heat and
      wildfire are close; NEX heat's 99th percentile runs about 25% low, and coastal flooding
      gets the level roughly right and the ranking wrong (it loses to the constant baseline).
    - **Our hurricane layer isn't a rebuild of FEMA's.** It is FEMA's documented method on open
      inputs. Why FEMA's values sit near 2.0 is unknown, because ARA's file isn't public.
    - **The v1.18.1 split differs from #42 by one county** (above).
    - **Not here:** Alaska, Hawaii and the territories have no rebuilt values; no tract-level
      data (see the two spikes for that).
    """)
    return


if __name__ == "__main__":
    app.run()
