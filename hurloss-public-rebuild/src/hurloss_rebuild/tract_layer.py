"""Below the county: the same multipliers at census tracts, and how they roll back up.

Hurricane wind fields are parametric, so wind can be computed at any point. The tract layer is
the county method evaluated at each tract's population-weighted centre instead of averaged over
grid points. Projected loss is NRI's tract hurricane EAL times the tract multiplier.
"""

import pandas as pd

from hurloss_rebuild.conditioning import SCENARIOS


def tract_table(
    tract_hm: pd.DataFrame,
    centroids: pd.DataFrame,
    county_hm: pd.DataFrame,
    nri_v1_19: pd.DataFrame,
    nri_v1_20: pd.DataFrame,
) -> pd.DataFrame:
    """One row per tract: its multipliers, its county's, and NRI tract EAL in both releases."""
    table = tract_hm.join(centroids[["population", "latitude", "longitude"]])
    table["county"] = table.index.str[:5]
    table["eal_v1_19"] = nri_v1_19["HRCN_EALT"].reindex(table.index)
    table["eal_v1_20"] = nri_v1_20["HRCN_EALT"].reindex(table.index)
    for scenario in SCENARIOS:
        column = f"{scenario.name}_HM"
        table[f"county_{column}"] = county_hm[column].reindex(table["county"]).to_numpy()
    return table


def summary(table: pd.DataFrame) -> pd.DataFrame:
    """Per scenario: spread inside counties, agreement with the county layer, and the roll-up."""
    rows = []
    for scenario in SCENARIOS:
        tract = f"{scenario.name}_HM"
        county = f"county_{tract}"
        spread = table.groupby("county")[tract].agg(["min", "max"])
        spread = spread[spread["min"] > 0]
        valid = table.dropna(subset=["eal_v1_20", county])
        tract_pal = (valid["eal_v1_20"] * valid[tract]).sum()
        county_pal = (valid["eal_v1_20"] * valid[county]).sum()
        rows.append(
            {
                "scenario": scenario.name,
                "tracts": len(table),
                "tracts_no_cat1_wind": int(table["no_cat1_wind"].sum()),
                "tract_hm_median": table[tract].median(),
                "tract_hm_p05": table[tract].quantile(0.05),
                "tract_hm_p95": table[tract].quantile(0.95),
                "within_county_max_over_min_median": (spread["max"] / spread["min"]).median(),
                "within_county_max_over_min_max": (spread["max"] / spread["min"]).max(),
                "spearman_tract_vs_county": table[tract].corr(table[county], method="spearman"),
                "rollup_tract_pal_over_county_pal": tract_pal / county_pal,
                "tract_eal_v1_20_over_v1_19_median": (
                    valid["eal_v1_20"] / valid["eal_v1_19"].where(valid["eal_v1_19"] > 0)
                ).median(),
            }
        )
    return pd.DataFrame(rows)


def tract_loss(nri_v1_20: pd.DataFrame, county_hm: pd.DataFrame) -> pd.DataFrame:
    """Tract projected loss: NRI v1.20 tract hurricane EAL x its county's multiplier and range.

    The Florida pilot shows tract-level wind changes the multiplier by 0.5-1.5% inside a county,
    less than the disagreement between hazard catalogues, so the climate part stays at county
    level and the tract detail comes from NRI.
    """
    table = pd.DataFrame(index=nri_v1_20.index)
    table["county"] = nri_v1_20["STCOFIPS"].astype(str).str.zfill(5)
    table["eal_v1_20"] = nri_v1_20["HRCN_EALT"]
    for scenario in SCENARIOS:
        for suffix in ("HM", "HM_LOW", "HM_HIGH"):
            column = f"{scenario.name}_{suffix}"
            hm = county_hm[column].reindex(table["county"]).fillna(1.0).to_numpy()
            table[column] = hm
        table[f"{scenario.name}_PAL"] = table["eal_v1_20"] * table[f"{scenario.name}_HM"]
    return table
