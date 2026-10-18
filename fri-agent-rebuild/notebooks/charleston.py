import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import geopandas as gpd
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    from fri_rebuild import data, recipe

    args = mo.cli_args()
    fips = str(args.get("fips", "45019"))
    gauge = str(args.get("gauge", "8665530"))
    out = data.PROJECT_DIR / "results" / "charleston"
    out.mkdir(parents=True, exist_ok=True)
    return data, fips, gauge, gpd, mo, np, out, pd, plt, recipe


@app.cell
def _(mo):
    mo.md(r"""
    # Pilot: coastal multipliers by tract, built from buildings (Charleston County, SC)

    **The question.** FEMA's coastal multiplier is one number per county, so every building in
    a county gets the same percentage change. Would finer data change the answer? If so, the
    multiplier could be republished by census tract: NRI's tract EAL (the economic side,
    refreshed each release) times a tract multiplier (the climate side, which changes slowly).

    **The model.** A bathtub at one tide gauge: a scenario, not FEMA's method and not a forecast.
    Every building gets its own expected annual damage today and under each FRI scenario;
    buildings sum to tracts; a tract's multiplier is its future damage over today's.

    Another county: `uv run notebooks/charleston.py -- --fips <county> --gauge <station>`.
    Writes `results/charleston/`, tract aggregates only (no building records).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The buildings

    All buildings in the USACE National Structure Inventory for the county, with ground
    elevation (USGS 3DEP, NAVD88), foundation height, and structure plus contents value.
    First-floor height above high tide (MHHW) uses the gauge's CO-OPS datums.
    """)
    return


@app.cell
def _(data, fips, gauge, pd):
    _path = data.cache("nsi", f"structures_{fips}.parquet")
    if not _path.exists():
        _response = data.http().get(
            f"https://nsi.sec.usace.army.mil/nsiapi/structures?fips={fips}", timeout=600
        )
        _response.raise_for_status()
        _columns = ["fd_id", "cbfips", "grnd_elv_m", "found_ht", "val_struct", "val_cont"]
        pd.DataFrame(f["properties"] for f in _response.json()["features"])[_columns].to_parquet(
            _path
        )
    buildings = pd.read_parquet(_path)
    buildings["tract"] = buildings["cbfips"].str[:11]
    buildings["value"] = buildings["val_struct"] + buildings["val_cont"]
    _datums = {d["name"]: d["value"] for d in data.station(gauge, "datums")["datums"]}
    mhhw_above_navd88 = float(_datums["MHHW"]) - float(_datums["NAVD88"])
    {"buildings": len(buildings), "MHHW above NAVD88 (m)": mhhw_above_navd88}
    return buildings, mhhw_above_navd88


@app.cell
def _(mo):
    mo.md(r"""
    ## Water levels and damage

    - **Water levels** come from the gauge's 2022 return-level curve, the curve FEMA's recipe
      reads (`coastal.py`), shifted up by the same median sea level rise as the recipe.
    - **Damage**: the year's highest water drawn from that curve, with at most one damaging
      flood a year (annual probability = 1 − e^(−frequency)), and a generic depth-damage curve
      at the first floor (USACE EGM 04-01, one-story without basement). Only ratios of future to
      today's damage are used, so the curve's absolute level matters little.
    - **Two sensitivity variants**: `step` counts any water at the first floor as a total loss;
      `ground` ignores foundation height.
    - **Left out**: buildings whose first floor is below today's 1-year water level. In this
      model they flood every year already; in Charleston they are mostly piers and port
      structures, ground elevations taken over water, or buildings behind defences. A first
      version kept them: they dominated their tracts, pinned those multipliers near 1, and made
      the tract spread look three times wider than it is. That was a modelling artefact.
    """)
    return


@app.cell
def _(buildings, gauge, mhhw_above_navd88, np, recipe):
    _row, _levels, _periods = recipe.curve(gauge)
    one_year_level = float(np.interp(0.0, np.log(_periods), _levels))
    _water = np.arange(-3.0, 12.0, 0.005)  # m above MHHW
    _shifts = {"today": 0.0} | {
        c[5:-3]: r for c, r in zip(recipe.COLUMNS, recipe.rises(_row), strict=True)
    }
    _feet = 0.3048
    _depth_ft = np.array([-2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
    _damage_pct = np.array(
        [
            0,
            2.5,
            13.4,
            23.3,
            32.1,
            40.1,
            47.1,
            53.2,
            58.6,
            63.2,
            67.2,
            70.5,
            73.2,
            75.4,
            77.2,
            78.5,
            79.5,
            80.2,
            80.7,
        ]
    )
    _floor_grid = np.arange(-4.0, 30.0, 0.01)
    damage = buildings[["tract", "value"]].copy()
    for _variant, _floor, _model in (
        ("curve", True, "curve"),
        ("step", True, "step"),
        ("ground", False, "curve"),
    ):
        _elevation = (
            buildings["grnd_elv_m"]
            + (buildings["found_ht"] * _feet if _floor else 0)
            - mhhw_above_navd88
        )
        damage[f"{_variant}_floods_yearly"] = _elevation < one_year_level
        for _scenario, _shift in _shifts.items():
            _exceedance = np.array(
                [recipe.frequency(w - _shift, _levels, _periods) for w in _water]
            )
            _probability = 1 - np.exp(-_exceedance)
            _band = (
                _probability[:-1] - _probability[1:]
            )  # the year's highest water lands in this band
            _depth = (_water[:-1] + _water[1:])[None, :] / 2 - _floor_grid[:, None]
            _fraction = (
                (_depth >= 0).astype(float)
                if _model == "step"
                else np.interp(_depth / _feet, _depth_ft, _damage_pct / 100, left=0.0)
            )
            _per_value = np.interp(_elevation, _floor_grid, _fraction @ _band)
            damage[f"{_variant}_{_scenario}"] = (buildings["value"] * _per_value).where(
                _elevation >= one_year_level, 0.0
            )
    _left_out = damage["curve_floods_yearly"]
    {
        "today's 1-year water level (m above MHHW)": one_year_level,
        "buildings left out (flood every year)": int(_left_out.sum()),
        "their value ($M)": damage.loc[_left_out, "value"].sum() / 1e6,
        "modelled damage today, whole county ($M/yr)": damage["curve_today"].sum() / 1e6,
    }
    return (damage,)


@app.cell
def _(data, damage, fips, out, pd, recipe):
    _nri = data.nri_tracts()
    _sums = (
        damage.drop(columns=[c for c in damage if c.endswith("floods_yearly")])
        .groupby("tract")
        .sum()
    )
    tracts = pd.DataFrame({"nri_eal": _nri.loc[_nri["STCOFIPS"] == fips, "CFLD_EALT"]})
    tracts["buildings"] = damage.groupby("tract").size()
    for _variant in ("curve", "step", "ground"):
        tracts[f"{_variant}_modelled_eal"] = _sums[f"{_variant}_today"]
        for _scenario in (c[5:-3] for c in recipe.COLUMNS):
            _today = _sums[f"{_variant}_today"]
            tracts[f"{_variant}_{_scenario}_hm"] = _sums[f"{_variant}_{_scenario}"] / _today.where(
                _today > 0
            )
            tracts[f"{_variant}_{_scenario}_pal"] = tracts["nri_eal"] * tracts[
                f"{_variant}_{_scenario}_hm"
            ].clip(lower=1)
    tracts.to_csv(out / f"tracts_{fips}.csv")
    _present = tracts["nri_eal"].fillna(0) > 0
    {
        "tracts with NRI coastal EAL": int(_present.sum()),
        "modelled damage today / NRI coastal EAL": tracts["curve_modelled_eal"].sum()
        / tracts["nri_eal"].sum(),
        "rank correlation, modelled damage vs NRI EAL": tracts.loc[_present, "nri_eal"].corr(
            tracts.loc[_present, "curve_modelled_eal"], method="spearman"
        ),
    }
    return (tracts,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Results

    County and tract multipliers by scenario, for each variant, next to FEMA's published county
    multiplier and the recipe's gauge factors. Rows are ranges across tracts; `pal` is
    projected annual loss, NRI tract EAL × tract HM.
    """)
    return


@app.cell
def _(damage, data, fips, gauge, out, pd, recipe, tracts):
    _key = data.answer_key().loc[fips]
    _factors = recipe.gauge_factors(gauge)
    _eal = tracts["nri_eal"].fillna(0)
    _rows = {}
    for _i, _column in enumerate(recipe.COLUMNS):
        _scenario, _published = _column[5:-3], float(_key[_column])
        _row = {
            "FEMA county HM": _published,
            "recipe factors (minor, moderate, major)": ", ".join(
                f"{f:.2f}" for f in _factors[:, _i]
            ),
            "FEMA county PAL ($M/yr)": float(_key["CFLD_EALT"]) * max(1.0, _published) / 1e6,
        }
        for _variant in ("curve", "step", "ground"):
            _hm, _pal = tracts[f"{_variant}_{_scenario}_hm"], tracts[f"{_variant}_{_scenario}_pal"]
            _county = damage[f"{_variant}_{_scenario}"].sum() / damage[f"{_variant}_today"].sum()
            _covered = _hm.notna() & (_eal > 0)
            _ratio = _hm[_covered] / _published
            _row |= {
                f"{_variant}: county HM": _county,
                f"{_variant}: tract HM min-max": f"{_hm.min():.2f}-{_hm.max():.2f}",
                f"{_variant}: tract vs own county": f"{_hm.min() / _county:.2f}"
                f"-{_hm.max() / _county:.2f}",
                f"{_variant}: tracts > 2x from FEMA": int(((_ratio > 2) | (_ratio < 0.5)).sum()),
                f"{_variant}: sum of tract PAL ($M/yr)": _pal.sum() / 1e6,
                f"{_variant}: PAL rank vs one county HM (Spearman)": _pal[_covered].corr(
                    _eal[_covered], method="spearman"
                ),
            }
        _rows[_scenario] = _row
    summary = pd.DataFrame(_rows)
    summary.to_csv(out / f"summary_{fips}.csv")
    summary
    return


@app.cell
def _(fips, gpd, data, out, plt, tracts):
    _shapes = data.tracts(fips[:2]).loc[lambda t: t.index.str[:5] == fips]
    _shapes = gpd.GeoDataFrame(_shapes.join(tracts["curve_MID_LOWER_hm"])).to_crs(data.EQUAL_AREA)
    _fig, _ax = plt.subplots(figsize=(10, 8))
    _shapes.plot(
        column="curve_MID_LOWER_hm",
        ax=_ax,
        cmap="YlOrRd",
        legend=True,
        linewidth=0.2,
        edgecolor="#666",
        missing_kwds={"color": "#ddd"},
        legend_kwds={"label": "Hazard multiplier", "shrink": 0.6},
    )
    _ax.set_axis_off()
    _ax.set_title("Coastal flooding multiplier by tract, mid-century lower (building-level pilot)")
    _fig.tight_layout()
    _fig.savefig(out / f"tracts_{fips}_mid_lower.png", dpi=130)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What it shows

    **Mid-century (the only horizon we'd stand behind), inside the county the multiplier varies
    about ±30-50%, not by multiples.** The lowest tracts are of two kinds: inland tracts toward
    Summerville and Ladson, which only the rarest floods reach (rare floods grow more slowly as
    the sea rises), and the lowest-lying ones, the tip of the peninsula and the Neck, which in
    this model already flood almost every year. The highest sit in between (Isle of Palms,
    Kiawah, Mount Pleasant, West Ashley): their buildings are reached by today's 5-50 year
    floods, which become several times more frequent. **This pattern depends on the convention
    of one damaging flood a year.** FEMA's recipe counts flood days, capped at 10 a year; under
    that convention the lowest tracts would score highest. That would need settling before
    anything is published.

    **The economic side drives where the losses are.** A tract multiplier instead of one county
    value barely reorders tracts by projected loss (rank correlation about 0.98-0.99). The
    building model's own damage ranks tracts much as NRI does, but in dollars it is about 260
    times NRI's coastal EAL: NRI multiplies flooded developed area by an empirical loss ratio,
    while the pilot applies a full depth-damage curve to every building and ignores defences.
    Only its ratios are used.

    **Late century the bathtub breaks down, as FEMA's method does.** By 2100 the 1.2-2.1 m
    rises put much of the county below today's yearly water levels, and tract multipliers
    spread to tens or hundreds. Those figures show the method's limit, not a loss estimate.

    **Building level vs tract level.** Building data is useful for computing a tract
    multiplier, because it shows where buildings sit relative to the water. Publishing below
    the tract would claim precision the inputs don't have: one tide gauge for the county, a 10 m
    elevation model, modelled foundation heights, and no flow paths or defences.

    ## What it doesn't cover

    Local differences in water level (tidal amplification up the rivers, surge and waves on the
    open coast); hydrologic connectivity, i.e. whether low ground is actually connected to the
    water (NOAA's sea level rise inundation layers handle it and are the next refinement);
    defences such as the Battery seawall and drainage tunnels; other Charleston-area gauges.

    Where FEMA's method handles hydrology (NRI Data Version and Update Documentation, December
    2025): **the NRI baseline carries the local detail.** Its high-tide sub-types intersect
    NOAA's flood-probability rasters with each census block's developed area, and its 1% and
    0.2% sub-types use FEMA's flood maps, which include surge and waves. **The FRI multiplier
    carries almost none**: each county takes its nearest gauge by distance alone. So a tract
    multiplier applied to NRI's tract EAL keeps the spatial hydrology NRI refreshes; the
    building model adds a little more inside the county, up to the limits of one gauge.
    """)
    return


if __name__ == "__main__":
    app.run()
