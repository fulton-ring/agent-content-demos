"""Download NEX-GDDP-CMIP6 daily files and keep only the CONUS box.

Each source file is one global year of one variable (about 250 MB, one gzip chunk per day),
so the whole file has to be read. We keep a CONUS lat/lon box as int16 hundredths and,
for drought, monthly means of every year.
"""

import re
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import h5py
import numpy as np
import requests

from fri_rebuild import http
from fri_rebuild.paths import cache_path

BUCKET = "https://nex-gddp-cmip6.s3.us-west-2.amazonaws.com"
MODEL = "MPI-ESM1-2-HR"
MEMBER = "r1i1p1f1"
LAT_RANGE = (24.0, 50.0)
LON_RANGE = (235.0, 294.0)
SCALE = 100.0
MISSING = np.iinfo(np.int16).min

HEAT_PERIODS = {
    "historical": range(1976, 2006),
    "ssp245": [*range(2036, 2066), *range(2070, 2100)],
    "ssp585": [*range(2036, 2066), *range(2070, 2100)],
}
MONTHLY_YEARS = {
    "historical": range(1950, 2015),
    "ssp245": range(2015, 2101),
    "ssp585": range(2015, 2101),
}
DAILY_VARIABLES = ("tasmin", "tasmax", "tas", "hurs")
MONTHLY_VARIABLES = ("tas", "pr")


@dataclass(frozen=True)
class Job:
    variable: str
    scenario: str
    year: int
    keep_daily: bool
    keep_monthly: bool


def list_versions(variable: str, scenario: str) -> dict[int, str]:
    """Map year to the newest file key for one variable and scenario."""
    prefix = f"NEX-GDDP-CMIP6/{MODEL}/{scenario}/{MEMBER}/{variable}/"
    keys: list[str] = []
    token = None
    while True:
        params = {"list-type": "2", "prefix": prefix}
        if token:
            params["continuation-token"] = token
        text = requests.get(BUCKET, params=params, timeout=60).text
        keys += re.findall(r"<Key>([^<]+)</Key>", text)
        match = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if not match:
            break
        token = match.group(1)
    newest: dict[int, tuple[str, str]] = {}
    for key in keys:
        found = re.search(r"_(\d{4})(?:_v(\d+\.\d+))?\.nc$", key)
        if not found:
            continue
        year, version = int(found.group(1)), found.group(2) or "0.0"
        if year not in newest or float(version) > float(newest[year][1]):
            newest[year] = (key, version)
    return {year: key for year, (key, _) in newest.items()}


def daily_path(variable: str, scenario: str, year: int) -> Path:
    return cache_path("nex", "daily", variable, scenario, f"{year}.npy")


def monthly_path(variable: str, scenario: str, year: int) -> Path:
    return cache_path("nex", "monthly", variable, scenario, f"{year}.npy")


def grid_path() -> Path:
    return cache_path("nex", "grid.npz")


def box_slices(lat: np.ndarray, lon: np.ndarray) -> tuple[slice, slice]:
    lat_idx = np.where((lat >= LAT_RANGE[0]) & (lat <= LAT_RANGE[1]))[0]
    lon_idx = np.where((lon >= LON_RANGE[0]) & (lon <= LON_RANGE[1]))[0]
    return slice(lat_idx[0], lat_idx[-1] + 1), slice(lon_idx[0], lon_idx[-1] + 1)


def monthly_means(daily: np.ndarray, year: int) -> np.ndarray:
    """Average daily values within each calendar month (handles 365/366-day years)."""
    days = np.arange(np.datetime64(f"{year}-01-01"), np.datetime64(f"{year + 1}-01-01"))
    days = days[: daily.shape[0]]
    months = days.astype("datetime64[M]").astype(int) % 12
    return np.stack([daily[months == m].mean(axis=0) for m in range(12)])


def fetch(url: str, handle: IO[bytes], attempts: int = 4) -> None:
    """Stream a file to `handle`, starting over if the connection drops midway."""
    for attempt in range(attempts):
        handle.seek(0)
        handle.truncate()
        try:
            with http.session().get(url, stream=True, timeout=300) as response:
                response.raise_for_status()
                for block in response.iter_content(chunk_size=8 << 20):
                    handle.write(block)
            handle.flush()
            return
        except requests.exceptions.RequestException:
            if attempt == attempts - 1:
                raise


def save_atomic(path: Path, array: np.ndarray) -> None:
    partial = path.with_name(path.stem + ".partial.npy")
    np.save(partial, array)
    partial.rename(path)


def process(job: Job, key: str) -> str:
    """Download one file, cut the CONUS box and write the cached arrays."""
    with tempfile.NamedTemporaryFile(suffix=".nc", dir=cache_path("nex", "tmp", "x").parent) as tmp:
        fetch(f"{BUCKET}/{key}", tmp)
        with h5py.File(tmp.name) as nc:
            lat, lon = nc["lat"][:], nc["lon"][:]
            rows, cols = box_slices(lat, lon)
            data = nc[job.variable][:, rows, cols].astype(np.float32)
            data[np.abs(data) > 1e10] = np.nan
            if not grid_path().exists():
                np.savez(grid_path(), lat=lat[rows], lon=lon[cols])
    if job.variable in ("tas", "tasmin", "tasmax"):
        data -= 273.15
    if job.variable == "pr":
        data *= 86400.0
    if job.keep_daily:
        scaled = np.where(np.isnan(data), MISSING, np.round(data * SCALE))
        save_atomic(daily_path(job.variable, job.scenario, job.year), scaled.astype(np.int16))
    if job.keep_monthly:
        save_atomic(
            monthly_path(job.variable, job.scenario, job.year), monthly_means(data, job.year)
        )
    return f"{job.variable} {job.scenario} {job.year}"


def plan_jobs() -> list[Job]:
    jobs: dict[tuple[str, str, int], Job] = {}
    for variable in DAILY_VARIABLES:
        for scenario, years in HEAT_PERIODS.items():
            for year in years:
                jobs[(variable, scenario, year)] = Job(variable, scenario, year, True, False)
    for variable in MONTHLY_VARIABLES:
        for scenario, years in MONTHLY_YEARS.items():
            for year in years:
                daily = (variable, scenario, year) in jobs
                jobs[(variable, scenario, year)] = Job(variable, scenario, year, daily, True)
    order = {"tasmin": 0, "tas": 1, "pr": 2, "hurs": 3, "tasmax": 4}
    return sorted(jobs.values(), key=lambda job: order[job.variable])


def is_done(job: Job) -> bool:
    daily_ok = not job.keep_daily or daily_path(job.variable, job.scenario, job.year).exists()
    monthly_ok = not job.keep_monthly or monthly_path(job.variable, job.scenario, job.year).exists()
    return daily_ok and monthly_ok


def download_all(workers: int = 8) -> None:
    """Fetch every file the hazards need, skipping ones already cached."""
    todo = [job for job in plan_jobs() if not is_done(job)]
    print(f"NEX-GDDP-CMIP6: {len(todo)} files to fetch")
    if not todo:
        return
    keys = {
        (variable, scenario): list_versions(variable, scenario)
        for variable, scenario in {(job.variable, job.scenario) for job in todo}
    }
    with ProcessPoolExecutor(workers) as pool:
        futures = [
            pool.submit(process, job, keys[(job.variable, job.scenario)][job.year]) for job in todo
        ]
        for count, future in enumerate(as_completed(futures), 1):
            print(f"[{count}/{len(todo)}] {future.result()}", flush=True)
