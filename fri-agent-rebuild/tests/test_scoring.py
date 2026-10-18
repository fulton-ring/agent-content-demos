import numpy as np
import pandas as pd

from fri_rebuild import scoring


def answer_key() -> pd.DataFrame:
    """Four counties in two states, with drought ratings and one HM column."""
    return pd.DataFrame(
        {
            "STATEABBRV": ["AA", "AA", "BB", "BB"],
            "COUNTY": ["a", "b", "c", "d"],
            "DRGT_EALT": [10.0, 100.0, 1000.0, 10000.0],
            "DRGT_EALR": [
                "Very Low (0 - 10)",
                "Relatively Low",
                "Relatively Moderate",
                "Very High",
            ],
            "DRGT_MID_LOWER_HM": [2.0, 0.0, 1.0, 4.0],
        },
        index=pd.Index(["01001", "01003", "02001", "02003"]),
    )


def test_bins_take_the_largest_eal_published_in_each_rating() -> None:
    thresholds = scoring.rating_thresholds(answer_key(), "DRGT")
    assert np.isnan(thresholds[3])  # no county is rated Relatively High
    losses = pd.Series([10.0, 11.0, 1000.0])
    assert list(scoring.rate(losses, thresholds[:3])) == [
        "Very Low",
        "Relatively Low",
        "Relatively Moderate",
    ]


def test_blank_counts_as_one_and_zero_published_is_skipped() -> None:
    key = answer_key()
    rebuilt = pd.Series([2.0, 5.0, np.nan, 4.0], index=key.index)
    metrics, detail = scoring.score_column(key, rebuilt, "DRGT_MID_LOWER_HM")
    assert metrics["counties"] == 3 and "01003" not in detail.index
    assert metrics["blank"] == 1 and detail.loc["02001", "rebuilt"] == 1.0
    assert metrics["log_mae"] == 0.0


def test_every_fourth_state_from_the_second_is_held_out() -> None:
    fips = pd.Index([f"{state:02d}001" for state in range(1, 10)])
    held_out = fips[scoring.split(fips) == "held_out"].str[:2]
    assert list(held_out) == ["02", "06"]
