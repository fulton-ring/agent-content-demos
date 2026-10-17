"""Coastal flooding multipliers by census tract, built up from individual buildings. A pilot.

FEMA publishes coastal multipliers per county, and the recovered recipe shows each one is a mix
of tide-gauge factors, so every building in a county gets the same percentage change. This pilot
asks whether that matters: it gives each building its own change, sums buildings to tracts, and
applies the tract multiplier to NRI's own tract EAL (the economic side, which NRI refreshes).

For each building in the USACE National Structure Inventory (ground elevation from USGS 3DEP,
NAVD88; foundation height; structure and contents value):
- first-floor elevation above MHHW at the county's tide gauge (CO-OPS datums);
- expected annual damage today: the yearly highest water level drawn from the gauge's
  return-level curve (2022 Sea Level Rise Technical Report, the curve the FEMA recipe uses, same
  log-linear interpolation), damage from a depth-damage curve at the first floor. One damaging
  flood a year at most, the usual expected-annual-damage convention: annual exceedance
  probability = 1 - exp(-frequency);
- the same with the curve shifted up by the scenario's median relative sea level rise (1.0 m
  scenario for LOWER, 2.0 m for HIGHER; 2050 and 2100), as in the recipe.
Tract multiplier = sum of future damage / sum of today's damage over the tract's buildings.

Buildings whose first floor sits below today's 1-year water level are left out and counted: by
this model they flood every year already, and in Charleston they are mostly piers and port
structures in V zones, ground elevations taken over water, or buildings behind defences the
bathtub cannot see. Left in, they dominate tract damage and pin multipliers near 1.

This is a bathtub model at one gauge: no waves, no hydrologic connectivity, no seawalls or
pumps, no change in buildings. Like the what-if scenarios it is a scenario, not FEMA's number
or a forecast. Two variants show how much the damage model drives the result: a step curve
(any water at the first floor is a total loss) and ground level (foundation height ignored).

The notebook notebooks/charleston_pilot.py runs it for Charleston County, SC (county 45019,
gauge 8665530) and writes results/charleston/.
"""

import json

import numpy as np
import pandas as pd

from fri_rebuild import http
from fri_rebuild.coastal import forensics, recipe
from fri_rebuild.paths import cache_path
from fri_rebuild.scoring import answer_key
from fri_rebuild.sources import nri, tide_gauges

NSI_API = "https://nsi.sec.usace.army.mil/nsiapi/structures?fips={fips}"
DATUM_API = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{gauge}/datums.json"
FEET = 0.3048
# USACE EGM 04-01, one-story residential without basement, structure damage (% of value) by
# depth of water above the first floor (ft). Applied to structure plus contents value: a generic
# curve, since only the ratio of future to today's damage is used.
DEPTH_FT = np.array([-2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
DAMAGE_PCT = np.array(
    [0, 2.5, 13.4, 23.3, 32.1, 40.1, 47.1, 53.2, 58.6, 63.2, 67.2, 70.5, 73.2, 75.4, 77.2, 78.5,
     79.5, 80.2, 80.7]
)  # fmt: skip
VARIANTS = {
    "curve": ("first floor", "depth-damage"),
    "step": ("first floor", "step"),
    "ground": ("ground", "depth-damage"),
}
LEVELS = np.arange(-3.0, 12.0, 0.005)  # water levels, m above MHHW


def structures(fips: str) -> pd.DataFrame:
    path = cache_path("nsi", f"structures_{fips}.parquet")
    if not path.exists():
        response = http.session().get(NSI_API.format(fips=fips), timeout=600)
        response.raise_for_status()
        features = json.loads(response.content)["features"]
        table = pd.DataFrame([feature["properties"] for feature in features])
        table[["fd_id", "cbfips", "x", "y", "grnd_elv_m", "found_ht", "val_struct", "val_cont",
               "firmzone", "st_damcat"]].to_parquet(path)  # fmt: skip
    return pd.read_parquet(path)


def mhhw_above_navd88(gauge: str) -> float:
    datums = http.session().get(DATUM_API.format(gauge=gauge) + "?units=metric", timeout=120)
    datums.raise_for_status()
    values = {d["name"]: d["value"] for d in datums.json()["datums"]}
    return float(values["MHHW"]) - float(values["NAVD88"])


def damage(depth_m: np.ndarray, model: str) -> np.ndarray:
    if model == "step":
        return (depth_m >= 0).astype(float)
    return np.interp(depth_m / FEET, DEPTH_FT, DAMAGE_PCT / 100, left=0.0)


def damage_by_elevation(exceedance: np.ndarray, elevations: np.ndarray, model: str) -> np.ndarray:
    """Expected annual damage (fraction of value) for each first-floor elevation above MHHW.

    `exceedance` is the annual frequency each of LEVELS is reached; the probability that the
    year's highest water lands between two levels is the difference in annual exceedance
    probability, and that band does the damage of its midpoint.
    """
    probability = 1 - np.exp(-exceedance)
    band = probability[:-1] - probability[1:]
    middle = (LEVELS[:-1] + LEVELS[1:]) / 2
    return np.array(
        [band @ damage(middle - elevation, model) for elevation in elevations]
        # the top level's own exceedance is negligible (above the 100 000-year level)
    )


def gauge_curve(gauge: str) -> tuple[pd.Series, np.ndarray, np.ndarray]:
    curves = tide_gauges.tables()["extreme_water_levels"]
    row = curves[curves["St"].astype(str) == gauge].iloc[0]
    columns, periods = forensics.return_periods(curves)
    return row, np.maximum.accumulate(row[columns].to_numpy(float)), periods


def exceedance_curves(gauge: str) -> dict[str, np.ndarray]:
    """Annual exceedance frequency of LEVELS today and under each FRI scenario."""
    row, levels, periods = gauge_curve(gauge)
    rise = recipe.rises(row)
    scenarios = {"today": 0.0}
    for (scenario, year), value in rise.items():
        period = "MID" if year == 2050 else "LATE"
        name = "LOWER" if scenario.startswith("1.0") else "HIGHER"
        scenarios[f"{period}_{name}"] = value
    return {
        name: np.array([recipe.frequency(level - shift, levels, periods) for level in LEVELS])
        for name, shift in scenarios.items()
    }


def building_damage(fips: str, gauge: str) -> pd.DataFrame:
    """Expected annual damage ($) per building, today and per scenario, for each variant."""
    curves = exceedance_curves(gauge)
    buildings = structures(fips)
    mhhw = mhhw_above_navd88(gauge)
    _, levels, periods = gauge_curve(gauge)
    one_year = float(np.interp(0.0, np.log(periods), levels))
    value = buildings["val_struct"] + buildings["val_cont"]
    table = buildings[["fd_id", "cbfips", "x", "y", "firmzone", "st_damcat"]].copy()
    table["tract"] = table["cbfips"].str[:11]
    table["value"] = value
    grid = np.arange(-4.0, 30.0, 0.01)
    for variant, (floor, model) in VARIANTS.items():
        height = buildings["found_ht"] * FEET if floor == "first floor" else 0.0
        elevation = buildings["grnd_elv_m"] + height - mhhw
        table[f"{variant}_floods_yearly"] = elevation < one_year
        if variant == "curve":
            table["floor_above_mhhw_m"] = elevation
        for scenario, exceedance in curves.items():
            per_value = damage_by_elevation(exceedance, grid, model)
            dollars = value * np.interp(elevation, grid, per_value)
            table[f"{variant}_{scenario}"] = dollars.where(elevation >= one_year, 0.0)
    return table


def tract_multipliers(buildings: pd.DataFrame, fips: str) -> pd.DataFrame:
    """Tract HM per variant and scenario, with NRI v1.19 tract EAL and projected annual loss."""
    tracts = nri.tracts()
    tracts = tracts[tracts["STCOFIPS"] == fips]
    sums = buildings.drop(columns=["fd_id", "cbfips", "x", "y", "firmzone", "st_damcat"])
    sums = sums.groupby("tract").sum()
    table = pd.DataFrame(index=tracts.index)
    table["nri_eal"] = tracts["CFLD_EALT"]
    table["buildings"] = buildings.groupby("tract").size()
    table["value"] = sums["value"]
    for variant in VARIANTS:
        today = sums[f"{variant}_today"]
        table[f"{variant}_modelled_eal"] = today
        for column in forensics.COLUMNS:
            scenario = column.removeprefix("CFLD_").removesuffix("_HM")
            hm = sums[f"{variant}_{scenario}"] / today.where(today > 0)
            table[f"{variant}_{scenario}_hm"] = hm
            table[f"{variant}_{scenario}_pal"] = table["nri_eal"] * hm.clip(lower=1)
    return table


def summary(table: pd.DataFrame, buildings: pd.DataFrame, fips: str, gauge: str) -> pd.DataFrame:
    """County roll-ups next to FEMA's published county HM and the recipe's gauge factors."""
    key = answer_key.load().loc[fips].to_dict()
    gauge_factors = recipe.gauge_factors(gauge)
    assert gauge_factors is not None, f"no return-level curve for gauge {gauge}"
    eal = table["nri_eal"].fillna(0)
    rows = []
    for index, column in enumerate(forensics.COLUMNS):
        scenario = column.removeprefix("CFLD_").removesuffix("_HM")
        published = float(key[column])
        row: dict[str, object] = {
            "scenario": scenario,
            "published_county_hm": published,
            "recipe_minor": gauge_factors[0, index],
            "recipe_moderate": gauge_factors[1, index],
            "recipe_major": gauge_factors[2, index],
            "county_pal_published_usd_m": float(key["CFLD_EALT"]) * max(1.0, published) / 1e6,
        }
        for variant in VARIANTS:
            hm = table[f"{variant}_{scenario}_hm"]
            pal = table[f"{variant}_{scenario}_pal"]
            covered = hm.notna() & (eal > 0)
            ratio = hm[covered] / published
            county_hm = (
                buildings[f"{variant}_{scenario}"].sum() / buildings[f"{variant}_today"].sum()
            )
            row[f"{variant}_county_hm"] = county_hm
            row[f"{variant}_tract_vs_own_county_min"] = hm.min() / county_hm
            row[f"{variant}_tract_vs_own_county_max"] = hm.max() / county_hm
            # Does a tract HM reorder tracts, compared with one county HM for all of them?
            row[f"{variant}_pal_rank_corr_vs_county_hm"] = pal[covered].corr(
                eal[covered], method="spearman"
            )
            row[f"{variant}_tract_hm_min"] = hm.min()
            row[f"{variant}_tract_hm_median"] = hm.median()
            row[f"{variant}_tract_hm_max"] = hm.max()
            row[f"{variant}_tracts_off_2x"] = int(((ratio > 2) | (ratio < 0.5)).sum())
            row[f"{variant}_tract_pal_sum_usd_m"] = pal.sum() / 1e6
            row[f"{variant}_top10pct_tract_pal_share"] = (
                pal.nlargest(max(1, len(pal) // 10)).sum() / pal.sum()
            )
        rows.append(row)
    return pd.DataFrame(rows)


def diagnostics(buildings: pd.DataFrame, table: pd.DataFrame) -> dict[str, float]:
    """Checks on the building model: what was left out, and how it compares with NRI."""
    yearly = buildings["curve_floods_yearly"]
    present = table["nri_eal"].fillna(0) > 0
    modelled = table["curve_modelled_eal"].fillna(0)
    rank = table.loc[present, ["nri_eal", "curve_modelled_eal"]].corr(method="spearman")
    return {
        "buildings": len(buildings),
        "left_out_floods_yearly": int(yearly.sum()),
        "left_out_value_usd_m": buildings.loc[yearly, "value"].sum() / 1e6,
        "left_out_ground_variant": int(buildings["ground_floods_yearly"].sum()),
        "modelled_damage_today_usd_m": buildings["curve_today"].sum() / 1e6,
        "nri_county_eal_usd_m": table["nri_eal"].sum() / 1e6,
        "tracts_with_nri_eal": int(present.sum()),
        "tracts_with_nri_eal_but_no_modelled_damage": int((present & (modelled == 0)).sum()),
        "rank_corr_nri_eal_vs_modelled_damage": float(rank.to_numpy()[0, 1]),
    }
