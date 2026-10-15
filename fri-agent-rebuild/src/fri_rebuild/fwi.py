"""Download NASA NEX-GDDP-CMIP6 Fire Weather Index (GDDP-IMPACT portal) for the CONUS box.

Yearly multi-model-ensemble files (MME25/MME50/MME75: the 25th, 50th and 75th percentile across
models), one global 0.25-degree grid per year. Some years are missing on the portal (the request
fails); those are skipped and the README reports how many years each period has.
"""

from concurrent.futures import ThreadPoolExecutor

import h5py
import numpy as np

from fri_rebuild import http, nex
from fri_rebuild.paths import cache_path

BASE = "https://data.nas.nasa.gov/gddpimpact/FWI/Yearly/MME"
ENSEMBLES = ("MME25", "MME50", "MME75")
YEARS = {
    "historical": range(1976, 2006),
    "ssp245": [*range(2036, 2066), *range(2070, 2100)],
    "ssp585": [*range(2036, 2066), *range(2070, 2100)],
}


def year_path(ensemble: str, scenario: str, year: int):  # noqa: ANN201 - Path
    return cache_path("fwi", ensemble, scenario, f"{year}.npz")


def missing_path(ensemble: str, scenario: str, year: int):  # noqa: ANN201 - Path
    return cache_path("fwi", ensemble, scenario, f"{year}.missing")


def fetch(ensemble: str, scenario: str, year: int) -> str:
    target = year_path(ensemble, scenario, year)
    if target.exists() or missing_path(ensemble, scenario, year).exists():
        return "cached"
    url = f"{BASE}/{ensemble}_{scenario}_fwi_metrics_yearly_{year}.nc"
    response = http.session().get(url, timeout=300)
    if response.status_code != 200:
        missing_path(ensemble, scenario, year).write_text(str(response.status_code))
        return f"missing {response.status_code}"
    raw = cache_path("fwi", "tmp", f"{ensemble}_{scenario}_{year}.nc")
    raw.write_bytes(response.content)
    with h5py.File(raw) as nc:
        rows, cols = nex.box_slices(nc["lat"][:], nc["lon"][:])
        arrays = {
            name: nc[name][rows, cols].astype(np.float32)
            for name in nc
            if name not in ("lat", "lon") and nc[name].ndim == 2
        }
    for values in arrays.values():
        values[np.abs(values) > 1e10] = np.nan
    np.savez(target, **arrays)
    raw.unlink()
    return "ok"


def download_all(workers: int = 3) -> None:
    jobs = [
        (ensemble, scenario, year)
        for ensemble in ENSEMBLES
        for scenario, years in YEARS.items()
        for year in years
    ]
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda job: fetch(*job), jobs))
    missing = sum(r.startswith("missing") for r in results)
    print(f"FWI: {len(jobs)} files, {missing} missing on the portal")


if __name__ == "__main__":
    download_all()
