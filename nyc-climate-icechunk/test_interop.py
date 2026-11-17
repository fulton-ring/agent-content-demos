import pandas as pd
import pytest

from interop import distance_km, hourly_depth


def test_missing_is_not_dry_and_end_is_exclusive() -> None:
    start = pd.Timestamp("2021-09-02T00:00Z")
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2021-09-02T00:01Z", "2021-09-02T02:00Z"]),
            "depth_proc_mm": [0.0, 99.0],
        }
    )
    result = hourly_depth(frame, start, 2)
    assert result.iloc[0].depth_max_mm == 0
    assert pd.isna(result.iloc[1].depth_max_mm)
    assert result.valid_readings.tolist() == [1, 0]


def test_duplicates_fail_instead_of_double_counting() -> None:
    start = pd.Timestamp("2021-09-02T00:00Z")
    frame = pd.DataFrame({"time": [start, start], "depth_proc_mm": [1.0, 2.0]})
    with pytest.raises(ValueError, match="Duplicate"):
        hourly_depth(frame, start, 1)


def test_dst_repeated_hour_stays_two_distinct_instants() -> None:
    utc = pd.date_range("2021-11-07T05:00Z", periods=2, freq="h")
    local = utc.tz_convert("America/New_York")
    assert local[0].hour == local[1].hour == 1
    assert local[1] - local[0] == pd.Timedelta(hours=1)
    assert local[0].utcoffset() != local[1].utcoffset()


def test_distance_uses_degrees_and_is_symmetric() -> None:
    assert distance_km(40.7, -74, 40.7, -74) == 0
    assert 110 < distance_km(40, -74, 41, -74) < 112
    assert distance_km(40, -74, 41, -73) == pytest.approx(distance_km(41, -73, 40, -74))
