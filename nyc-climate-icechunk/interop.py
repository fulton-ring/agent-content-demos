import time
from collections.abc import Mapping

import numpy as np
import pandas as pd
import requests


def download(
    url: str, params: Mapping[str, str | int] | None = None, cap: int = 5_000_000
) -> tuple[bytes, dict[str, float | int]]:
    started = time.perf_counter()
    for attempt in range(2):
        try:
            with requests.get(
                url,
                params=params,
                timeout=(10, 60),
                stream=True,
                headers={"User-Agent": "nyc-climate-icechunk research spike"},
            ) as response:
                response.raise_for_status()
                body = bytearray()
                for block in response.iter_content(65536):
                    body.extend(block)
                    if len(body) > cap:
                        raise ValueError("Response exceeds the configured download cap")
                return bytes(body), {
                    "http_status": response.status_code,
                    "body_bytes": len(body),
                    "seconds": round(time.perf_counter() - started, 3),
                }
        except requests.RequestException:
            if attempt == 1:
                raise
            time.sleep(1)
    raise AssertionError("Download retry bound exhausted")


def hourly_depth(frame: pd.DataFrame, start: pd.Timestamp, hours: int) -> pd.DataFrame:
    index = pd.date_range(start, periods=hours, freq="h")
    observed = frame.loc[
        (frame.time >= start) & (frame.time < start + pd.Timedelta(hours=hours))
    ].set_index("time")
    if not observed.index.is_unique:
        raise ValueError("Duplicate sensor timestamps must be resolved before joining")
    grouped = observed.depth_proc_mm.resample("h", origin=start)
    return pd.DataFrame(
        {
            "depth_max_mm": grouped.max().reindex(index),
            "valid_readings": grouped.count().reindex(index, fill_value=0),
        }
    ).rename_axis("interval_start")


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = np.radians([lat1, lat2])
    dp, dl = np.radians([lat2 - lat1, lon2 - lon1])
    a = np.sin(dp / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dl / 2) ** 2
    return float(6371 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a)))
