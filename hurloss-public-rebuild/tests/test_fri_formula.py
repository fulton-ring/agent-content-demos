import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from hurloss_rebuild import fri_formula


def wind(rows: list[list[float]]) -> sparse.csr_matrix:
    return sparse.csr_matrix(np.array(rows))


def test_exceedance_counts_every_category_reached() -> None:
    # One Cat 3 event (52 m/s) at point 0, one Cat 1 event (35 m/s) at point 1.
    frequencies = fri_formula.category_frequencies(
        wind([[52.0, 0.0], [0.0, 35.0]]), np.array([0.1, 0.2])
    )
    np.testing.assert_allclose(frequencies[0], [0.1, 0.1, 0.1, 0, 0])
    np.testing.assert_allclose(frequencies[1], [0.2, 0, 0, 0, 0])


def test_banded_counts_only_the_peak_category() -> None:
    frequencies = fri_formula.category_frequencies(wind([[52.0]]), np.array([0.1]), banded=True)
    np.testing.assert_allclose(frequencies[0], [0, 0, 0.1, 0, 0])


def test_intensity_doubles_weight_per_category() -> None:
    assert fri_formula.intensity(np.eye(5)).tolist() == [1, 2, 4, 8, 16]


def test_multiplier_floors_at_one_and_blanks_zero_history() -> None:
    historical = pd.Series([2.0, 2.0, 0.0], index=["a", "b", "c"])
    projected = pd.Series([3.0, 1.0, 5.0], index=["a", "b", "c"])
    result = fri_formula.hazard_multiplier(projected, historical)
    assert result["a"] == pytest.approx(1.5)
    assert result["b"] == 1.0
    assert np.isnan(result["c"])


def test_county_mean_uses_points_shared_through_the_buffer() -> None:
    mapping = pd.Series(["A", "A", "B"], index=[0, 1, 1])
    means = fri_formula.county_mean(np.array([1.0, 3.0]), mapping)
    assert means["A"] == 2.0
    assert means["B"] == 3.0


def test_rejects_mismatched_event_rates() -> None:
    with pytest.raises(ValueError):
        fri_formula.category_frequencies(wind([[40.0]]), np.array([0.1, 0.2]))
