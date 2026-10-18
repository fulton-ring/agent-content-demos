import numpy as np
import pandas as pd
import pytest
from scipy import sparse

import fri


def events(wind: list[list[float]], frequency: list[float], category: list[int]) -> fri.Events:
    return fri.Events(
        wind=sparse.csr_matrix(np.array(wind)),
        frequency=np.array(frequency),
        category=np.array(category),
        basin=np.array(["NA"] * len(frequency)),
        years=(1900, 2024),
    )


def test_intensity_counts_every_category_reached_with_doubling_weights() -> None:
    # A Cat 3 storm (52 m/s) reaches Cat 1, 2 and 3: 1 + 2 + 4 = 7 times its rate.
    one_point = pd.Series(["A"], index=[0])
    intensity = fri.county_intensity(events([[52.0]], [0.1], [3]), one_point)
    assert intensity["A"] == pytest.approx(0.7)


def test_county_mean_uses_points_shared_through_the_buffer() -> None:
    mapping = pd.Series(["A", "A", "B"], index=[0, 1, 1])
    means = fri.county_mean(np.array([1.0, 3.0]), mapping)
    assert means["A"] == 2.0
    assert means["B"] == 3.0


def test_ratio_is_blank_where_today_has_no_wind() -> None:
    today = pd.Series([2.0, 0.0], index=["a", "b"])
    result = fri.ratio(pd.Series([3.0, 5.0], index=["a", "b"]), today)
    assert result["a"] == pytest.approx(1.5)
    assert np.isnan(result["b"])


def test_frequency_only_hits_knutson_totals_and_keeps_winds() -> None:
    sample = events([[40.0], [60.0], [30.0]], [0.01, 0.01, 0.02], [2, 4, 0])
    scaled = fri.frequency_only(sample, "LATE_HIGHER")
    all_change = fri.knutson_percent("cat05", "LATE_HIGHER", "NA", sample.years) / 100
    strong_change = fri.knutson_percent("cat45", "LATE_HIGHER", "NA", sample.years) / 100
    assert scaled.frequency.sum() == pytest.approx(sample.frequency.sum() * (1 + all_change))
    assert scaled.frequency[1] == pytest.approx(0.01 * (1 + strong_change))
    np.testing.assert_array_equal(scaled.wind.toarray(), sample.wind.toarray())


def test_rating_bounds_reproduce_the_ratings_they_came_from() -> None:
    key = pd.DataFrame(
        {
            "HRCN_EALT": [1.0, 5.0, 10.0, 50.0, 100.0, 500.0],
            "HRCN_EALR": [
                "Very Low",
                "Relatively Low (1 - 5)",
                "Relatively Moderate",
                "Relatively High",
                "Very High",
                "Very High",
            ],
        }
    )
    rated = fri.rate(key["HRCN_EALT"], fri.rating_bounds(key))
    assert rated.tolist() == key["HRCN_EALR"].map(fri.rating_name).tolist()
