"""Take one hazard's final pipeline below the county: census tracts in one state.

The pipeline is rerun with tract weights instead of county weights, so each tract's multiplier
comes from the grid cells that overlap it. Tract projected annual loss = NRI v1.19 tract EAL x
tract HM. The roll-up check sums tract PAL back to counties and compares the implied county
multiplier with the pipeline's own county value and FEMA's published one.
"""

import numpy as np
import pandas as pd

from fri_rebuild import inputs
from fri_rebuild.pipeline import hazard_pipeline
from fri_rebuild.scoring import answer_key
from fri_rebuild.sources import nri

HAZARD_NRI = {"EXHT": "HWAV", "DRGT": "DRGT", "WFIR": "WFIR"}


def tract_table(hazard: str, column: str, state_fips: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tract multipliers with NRI tract EAL, and the same pipeline's county multipliers."""
    pipeline = hazard_pipeline(hazard)
    counties = pipeline.hazard_multipliers()
    tracts = pipeline.hazard_multipliers(inputs.tract_weights(state_fips))
    eal = nri.tracts()[f"{HAZARD_NRI[column[:4]]}_EALT"]
    table = tracts.join(eal.rename("EAL"), how="left")
    table["county"] = table.index.str[:5]
    return table, counties


def roll_up(table: pd.DataFrame, counties: pd.DataFrame, column: str) -> pd.DataFrame:
    """County HM implied by summing tract PAL, next to the county pipeline and FEMA."""
    key = answer_key.load()
    pal = (table["EAL"] * table[column]).groupby(table["county"]).sum()
    eal = table["EAL"].groupby(table["county"]).sum()
    return pd.DataFrame(
        {
            "tract_eal_sum": eal,
            "nri_county_eal": key[column[:4] + "_EALT"].reindex(eal.index),
            "rolled_up_hm": pal / eal.where(eal > 0),
            "county_pipeline_hm": counties[column].reindex(eal.index),
            "published_hm": key[column].reindex(eal.index),
            "tracts": table.groupby("county").size(),
        }
    )


def checks(table: pd.DataFrame, check: pd.DataFrame, column: str) -> dict[str, float]:
    """Coverage and consistency of the tract layer against counties."""
    covered = check.dropna(subset=["rolled_up_hm", "county_pipeline_hm"])
    published = covered.dropna(subset=["published_hm"])
    spread = table.groupby("county")[column].agg(lambda s: s.max() / s.min())
    eal_gap = (check["tract_eal_sum"] / check["nri_county_eal"] - 1).abs()
    rolled = (covered["rolled_up_hm"] / covered["county_pipeline_hm"] - 1).abs()
    ratio = (published["rolled_up_hm"] / published["published_hm"]).to_numpy()
    return {
        "tracts": len(table),
        "counties": table["county"].nunique(),
        "tracts_with_nri_eal": int(table["EAL"].notna().sum()),
        "tract_hm_min": table[column].min(),
        "tract_hm_max": table[column].max(),
        "median_within_county_max_over_min": spread.median(),
        "max_abs_tract_eal_sum_vs_county": eal_gap.max(),
        "rolled_up_vs_county_pipeline_median_abs": rolled.median(),
        "rolled_up_vs_county_pipeline_max_abs": rolled.max(),
        "rolled_up_vs_published_corr": published["rolled_up_hm"].corr(published["published_hm"]),
        "rolled_up_vs_published_median_ratio": float(np.exp(np.median(np.log(ratio)))),
        "county_pipeline_vs_published_corr": published["county_pipeline_hm"].corr(
            published["published_hm"]
        ),
    }
