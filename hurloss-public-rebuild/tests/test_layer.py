import numpy as np
import pandas as pd

from hurloss_rebuild import layer
from hurloss_rebuild.conditioning import PERCENTILES, SCENARIOS


def ratios(value_of: dict[str, float]) -> pd.DataFrame:
    rows = [
        {"unit": unit, "scenario": s.name, "percentile": p, "ratio": value_of[unit] * (1 + i / 10)}
        for unit in value_of
        for s in SCENARIOS
        for i, p in enumerate(PERCENTILES)
    ]
    return pd.DataFrame(rows)


def test_wide_floors_at_one_and_reports_the_percentile_range() -> None:
    today = pd.Series({"a": 0.2, "b": 0.0})
    table = layer.wide(ratios({"a": 0.9, "b": np.nan}), today)
    assert table.loc["a", "MID_LOWER_HM"] == 0.9 * 1.2
    assert table.loc["a", "MID_LOWER_HM_LOW"] == 1.0
    assert table.loc["a", "MID_LOWER_HM_HIGH"] == 0.9 * 1.4
    assert table.loc["b", "MID_LOWER_HM"] == 1.0
    assert bool(table.loc["b", "no_cat1_wind"])
