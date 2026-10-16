"""What FEMA's published hurricane multipliers look like, read straight from the answer key.

This part reads the answer key on purpose. It is not a rebuild; it says what any rebuild has to
reproduce, and gives the trivial baselines a rebuild has to beat.
"""

import numpy as np
import pandas as pd

from hurloss_rebuild.conditioning import SCENARIOS

NEAR_TWO = (1.9, 2.1)
CAP = 10.0


def level_summary(key: pd.DataFrame) -> pd.DataFrame:
    """Per scenario: how many counties have a value, its spread, and the share near 2."""
    rows = []
    for scenario in SCENARIOS:
        hm = key[f"HRCN_{scenario.name}_HM"]
        positive = hm[hm > 0]
        quantiles = np.percentile(positive, [5, 25, 50, 75, 95])
        rows.append(
            {
                "scenario": scenario.name,
                "counties": len(hm),
                "zero": int((hm == 0).sum()),
                "below_one": int(((hm > 0) & (hm < 1)).sum()),
                "at_cap_10": int((hm == CAP).sum()),
                "share_near_2": float(positive.between(*NEAR_TWO).mean()),
                "p05": quantiles[0],
                "p25": quantiles[1],
                "median": quantiles[2],
                "p75": quantiles[3],
                "p95": quantiles[4],
            }
        )
    return pd.DataFrame(rows)


def zero_with_losses(key: pd.DataFrame) -> pd.DataFrame:
    """Counties with hurricane EAL today but a published multiplier of 0 (no ARA point)."""
    zero = (key["HRCN_MID_LOWER_HM"] == 0) & (key["HRCN_EALT"] > 0)
    return (
        key[zero]
        .groupby("STATEABBRV")
        .agg(counties=("HRCN_EALT", "size"), eal_total=("HRCN_EALT", "sum"))
    )


def constant(key: pd.DataFrame, value: float) -> pd.DataFrame:
    """A rebuild that gives every county the same multiplier, as a baseline to beat."""
    return pd.DataFrame({s.name: value for s in SCENARIOS}, index=key.index)


def published_signal(key: pd.DataFrame) -> pd.DataFrame:
    """FEMA's value with the level of 2 taken out, two ways: HM / 2 and HM - 1.

    If FEMA's ratio carries a stray factor of two, HM / 2 is the climate signal; if the
    projected intensity included the historical one, HM - 1 is.
    """
    columns = {}
    for scenario in SCENARIOS:
        hm = key[f"HRCN_{scenario.name}_HM"].where(lambda v: v > 0)
        columns[f"{scenario.name}_half"] = hm / 2
        columns[f"{scenario.name}_minus_one"] = hm - 1
    return pd.DataFrame(columns)
