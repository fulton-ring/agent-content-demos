import numpy as np
import pytest
from scipy import sparse

from hurloss_rebuild import hazard
from hurloss_rebuild.hazard import Events


def part(rows: int, points: int = 3) -> Events:
    return Events(
        wind=sparse.csr_matrix(np.ones((rows, points))),
        frequency=np.full(rows, 0.001),
        category=np.zeros(rows, dtype=int),
        basin=np.array(["NA"] * rows),
        years=(1980, 2018),
    )


def test_stack_keeps_every_event_and_rate() -> None:
    stacked = hazard.stack([part(2), part(3)])
    assert stacked.wind.shape == (5, 3)
    assert stacked.frequency.sum() == pytest.approx(0.005)


def test_stack_refuses_different_points() -> None:
    with pytest.raises(ValueError):
        hazard.stack([part(2, points=3), part(2, points=4)])
