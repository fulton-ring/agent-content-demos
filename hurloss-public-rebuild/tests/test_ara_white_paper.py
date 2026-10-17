import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from hurloss_rebuild import ara_white_paper
from hurloss_rebuild.hazard import Events


def test_condition_scales_by_peak_region_and_category() -> None:
    # Event 0 peaks at Cat 5 (75 m/s) in Florida; event 1 peaks at Cat 1 inland (no region).
    events = Events(
        wind=sparse.csr_matrix(np.array([[75.0, 40.0], [0.0, 35.0]])),
        frequency=np.array([0.01, 0.02]),
        category=np.array([5, 1]),
        basin=np.array(["NA", "NA"]),
        years=(1900, 2024),
    )
    scaled = ara_white_paper.condition(events, np.array(["Florida", ""]))
    reference, _, future = ara_white_paper.FIGURE_1["Florida"]
    assert scaled.frequency[0] == pytest.approx(0.01 * future[4] / reference[4])
    assert scaled.frequency[1] == 0.02


def test_point_regions_follow_the_county_state() -> None:
    mapping = pd.Series(["12086", "39001", "39001"], index=[0, 1, 1])
    states = pd.Series({"12086": "FL", "39001": "OH"})
    assert ara_white_paper.point_regions(mapping, states).tolist() == ["Florida", ""]
