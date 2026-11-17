from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from gridded_core import hourly_rain, native_subset, round_trip


def fixture_grid(source: str) -> xr.Dataset:
    half_hour = source == "imerg"
    times = pd.date_range(
        "2021-09-02", periods=4 if half_hour else 2, freq="30min" if half_hour else "1h"
    )
    if not half_hour:
        times += pd.Timedelta(hours=1)
    values = np.full((len(times), 2, 2), 1 / 3600, dtype=np.float32)
    values[:, 1, 0] = np.nan
    variable = "total_precipitation" if source == "era5" else "precipitation_surface"
    if source == "era5":
        values *= 3.6
    return xr.Dataset(
        {
            variable: (
                ("time", "latitude", "longitude"),
                values,
                {"units": "m" if source == "era5" else "kg m-2 s-1"},
            )
        },
        coords={
            "time": times,
            "latitude": [40.7, 40.6],
            "longitude": [286.0, 286.25] if source == "era5" else [-74.0, -73.75],
        },
    )


@pytest.mark.parametrize("source", ["mrms", "imerg", "era5"])
def test_units_and_window_boundaries(source: str) -> None:
    table = hourly_rain(fixture_grid(source), source)
    np.testing.assert_allclose(table.precipitation_mm, [1, 1], rtol=1e-6)
    assert list(table.interval_start) == list(
        pd.date_range("2021-09-02", periods=2, freq="1h", tz="UTC")
    )
    assert table.interval_end.iloc[-1] == pd.Timestamp("2021-09-02T02:00Z")


def test_missing_half_hour_does_not_become_zero() -> None:
    grid = fixture_grid("imerg")
    grid.precipitation_surface.values[0, 0, 0] = np.nan
    assert np.isnan(hourly_rain(grid, "imerg").precipitation_mm.iloc[0])


@pytest.mark.parametrize("source", ["mrms", "imerg", "era5"])
def test_native_coordinates_and_round_trip(tmp_path: Path, source: str) -> None:
    grid = fixture_grid(source)
    selected = native_subset(grid, (40.59, 40.71, -74.1, -73.7))
    xr.testing.assert_identical(grid, selected)
    result = round_trip(selected, tmp_path / source, source)
    assert result["round_trip_identical"] is True


def test_wrong_units_rejected() -> None:
    grid = fixture_grid("mrms")
    grid.precipitation_surface.attrs["units"] = "mm/hour"
    with pytest.raises(ValueError):
        hourly_rain(grid, "mrms")
