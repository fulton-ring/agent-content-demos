"""The safe reader is what stands between a downloaded STORM pickle and arbitrary code."""

import os
import pickle
from pathlib import Path

import numpy as np
import pytest

from common import read_pickled_npy


def test_reads_a_storm_style_dict(tmp_path: Path) -> None:
    path = tmp_path / "coefficients.npy"
    np.save(path, np.array({1: [1.5, 2.5], 2: np.arange(3.0)}, dtype=object), allow_pickle=True)
    data = read_pickled_npy(path)
    assert data[1] == [1.5, 2.5]
    assert np.array_equal(data[2], np.arange(3.0))


class _Payload:
    def __reduce__(self) -> tuple:
        return (os.system, ("echo pwned",))


def test_refuses_a_pickle_that_would_run_code(tmp_path: Path) -> None:
    path = tmp_path / "evil.npy"
    np.save(path, np.array({"x": _Payload()}, dtype=object), allow_pickle=True)
    with pytest.raises(pickle.UnpicklingError):
        read_pickled_npy(path)
