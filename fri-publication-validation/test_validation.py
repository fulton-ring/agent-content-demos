"""Boundary and missing-data cases that can silently mislead a publication."""

import numpy as np
import pandas as pd
import pytest

from validation import classify, display_score, projected_rating, risk_score, thresholds


def test_upper_bounds_overflow_and_missing() -> None:
    values = pd.Series([1.0, 1.0001, 4.0, 100.0, np.nan])
    result = classify(values, np.array([1.0, 2.0, 3.0, 4.0]))
    assert result.iloc[:4].tolist() == [
        "Very Low",
        "Relatively Low",
        "Relatively High",
        "Very High",
    ]
    assert pd.isna(result.iloc[4])


def test_statuses_do_not_become_low_risk() -> None:
    baseline = pd.Series(
        ["No Expected Annual Losses", "No Rating", "Insufficient Data", "Very Low"]
    )
    result = projected_rating(pd.Series([0.0, 0.0, np.nan, 1.0]), baseline, np.arange(1.0, 5.0))
    assert result.tolist() == ["No Rating", "No Rating", "Not Applicable", "Very Low"]


def test_zero_ties_stay_in_ranking_missing_does_not() -> None:
    result = risk_score(pd.Series([0.0, 0.0, 100.0, np.nan]))
    assert result.iloc[:3].tolist() == [50.0, 50.0, 100.0]
    assert pd.isna(result.iloc[3])
    assert display_score(pd.Series([7.397391, 86.7345, np.nan])).iloc[:2].tolist() == [7.397, 86.73]


def test_heat_floor_quantile_ties() -> None:
    result = classify(pd.Series([1.0, 1.01, 3.0]), np.array([1.0, 1.0, 1.3, 2.59]))
    assert result.tolist() == ["Very Low", "Relatively Moderate", "Very High"]


def test_thresholds_require_a_complete_reference() -> None:
    with pytest.raises(ValueError, match="Baseline needs"):
        thresholds(pd.Series([1.0, 2.0]), pd.Series(["Very Low", "Relatively Low"]))
