import numpy as np
import pytest
from scipy import sparse

from hurloss_rebuild import conditioning
from hurloss_rebuild.hazard import Events

SCENARIO = conditioning.SCENARIOS[3]


def sample_events() -> Events:
    return Events(
        wind=sparse.csr_matrix(np.array([[40.0], [60.0], [30.0]])),
        frequency=np.array([0.01, 0.01, 0.02]),
        category=np.array([2, 4, 0]),
        basin=np.array(["NA", "NA", "NA"]),
        years=(1900, 2024),
    )


def test_frequency_only_hits_knutson_totals() -> None:
    events = sample_events()
    scaled = conditioning.frequency_only(events, SCENARIO)
    all_change = conditioning.knutson_percent("cat05", SCENARIO, "NA", events.years) / 100
    strong_change = conditioning.knutson_percent("cat45", SCENARIO, "NA", events.years) / 100
    assert scaled.frequency.sum() == pytest.approx(events.frequency.sum() * (1 + all_change))
    assert scaled.frequency[1] == pytest.approx(0.01 * (1 + strong_change))
    np.testing.assert_array_equal(scaled.wind.toarray(), events.wind.toarray())


def test_intensity_variant_scales_every_wind_by_the_same_factor() -> None:
    events = sample_events()
    scaled = conditioning.intensity_and_frequency(events, SCENARIO)
    factor = scaled.wind.toarray() / events.wind.toarray()
    assert np.allclose(factor, factor[0, 0])
    assert factor[0, 0] > 1
