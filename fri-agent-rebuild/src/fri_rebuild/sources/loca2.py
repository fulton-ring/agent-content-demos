"""Reduce LOCA2 daily minimum temperature (MPI-ESM1-2-HR, 1/16 degree) to per-cell histograms.

LOCA2 ships multi-decade files of 9-22 GB, one gzip chunk per day. We read only the days of the
FRI periods over HTTP and keep, for every grid cell that overlaps a CONUS county, a histogram of
daily tasmin in 0.1 deg C bins per 30-year period. Percentiles and counts of days above any
threshold come straight from these histograms, at about 0.4 GB per period instead of 10 GB of
raw values.
"""

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import fsspec
import h5py
import numpy as np
import pandas as pd
from scipy import sparse

from fri_rebuild.paths import cache_path
from fri_rebuild.scoring import answer_key
from fri_rebuild.sources import geo

BASE = "https://cirrus.ucsd.edu/~pierce/LOCA2/NAmer/MPI-ESM1-2-HR/0p0625deg/r1i1p1f1"
FILES = {
    "historical": ["1950-2014"],
    "ssp245": ["2015-2044", "2045-2074", "2075-2100"],
    "ssp585": ["2015-2044", "2045-2074", "2075-2100"],
}
PERIODS = {"historical": (1976, 2005), "MID": (2036, 2065), "LATE": (2070, 2099)}
BIN_WIDTH = 0.1
LOWEST = -10.0
HIGHEST = 40.0
# Bin 0 holds everything below LOWEST and the last value bin everything at or above HIGHEST.
EDGES = np.concatenate([[-np.inf], np.arange(LOWEST, HIGHEST + BIN_WIDTH / 2, BIN_WIDTH), [np.inf]])
VALUE_BINS = len(EDGES) - 1
# One extra row after the value bins counts days with no data (ocean or masked cells).
MISSING_ROW = VALUE_BINS
WORKERS = 4
# Days per piece. A finished piece is saved, so an interrupted run loses at most the pieces in
# flight (50-110 minutes of reading each on 4 cores in October 2026), at about 220 MB of disk
# per saved piece.
PIECE_DAYS = 3 * 365


@dataclass(frozen=True)
class Slice:
    scenario: str
    span: str
    first_day: int
    last_day: int


def url(scenario: str, span: str) -> str:
    return (
        f"{BASE}/{scenario}/tasmin/tasmin.MPI-ESM1-2-HR.{scenario}.r1i1p1f1.{span}"
        ".LOCA_16thdeg_v20220413.nc"
    )


def open_remote(scenario: str, span: str) -> h5py.File:
    handle = fsspec.open(url(scenario, span), block_size=64 << 20, cache_type="readahead").open()
    return h5py.File(handle)


def grid() -> tuple[np.ndarray, np.ndarray]:
    target = cache_path("loca2", "grid.npz")
    if not target.exists():
        with open_remote("historical", "1950-2014") as nc:
            np.savez(target, lat=nc["lat"][:], lon=nc["lon"][:])
    data = np.load(target)
    return data["lat"], data["lon"]


def county_weights() -> tuple[np.ndarray, sparse.csr_matrix, pd.Index]:
    """Cells that overlap a CONUS county (flat indices) and county x cell intersection areas."""
    key = answer_key.conus(answer_key.load())
    lat, lon = grid()
    weights, fips = geo.area_weights(geo.counties().loc[key.index], lat, lon, "counties_loca2")
    cells = np.flatnonzero(np.asarray(weights.sum(axis=0)).ravel() > 0)
    return cells, sparse.csr_matrix(weights[:, cells]), fips


def day_slices(scenario: str, period: str) -> list[Slice]:
    """Split a period's days into contiguous pieces of about PIECE_DAYS, each inside one file."""
    first, last = PERIODS[period]
    run = "historical" if period == "historical" else scenario
    pieces = []
    for span in FILES[run]:
        start_year, end_year = (int(y) for y in span.split("-"))
        lo, hi = max(first, start_year), min(last, end_year)
        if lo > hi:
            continue
        origin = np.datetime64(f"{start_year}-01-01")
        begin = int((np.datetime64(f"{lo}-01-01") - origin).astype(int))
        end = int((np.datetime64(f"{hi + 1}-01-01") - origin).astype(int))
        count = max(1, round((end - begin) / PIECE_DAYS))
        bounds = np.linspace(begin, end, count + 1).astype(int)
        pieces += [
            Slice(run, span, int(a), int(b)) for a, b in zip(bounds[:-1], bounds[1:], strict=True)
        ]
    return pieces


def read_days(piece: Slice, start: int, stop: int, attempts: int = 5) -> np.ndarray:
    """Days [start, stop) of one source file, reopening the connection if a read is cut off."""
    for attempt in range(attempts):
        try:
            with open_remote(piece.scenario, piece.span) as nc:
                return nc["tasmin"][start:stop]
        except (OSError, aiohttp.ClientError):
            if attempt == attempts - 1:
                raise
    raise RuntimeError("unreachable")


def histogram_slice(piece: Slice, cells: np.ndarray, out_name: str) -> str:
    """Histogram of tasmin (deg C) for one run of days, written to a partial file."""
    target = cache_path("loca2", "partial", out_name)
    if target.exists():
        return str(target)
    counts = np.zeros((VALUE_BINS + 1, len(cells)), dtype=np.uint16)
    columns = np.arange(len(cells))
    batch = 60
    for start in range(piece.first_day, piece.last_day, batch):
        block = read_days(piece, start, min(start + batch, piece.last_day))
        block = block.reshape(block.shape[0], -1)[:, cells] - 273.15
        for day in block:
            bins = np.searchsorted(EDGES, day, side="right") - 1
            bins = np.where(np.isfinite(day) & (np.abs(day) < 1e10), bins, MISSING_ROW)
            counts[bins, columns] += 1
    partial = target.with_name(target.stem + ".tmp.npy")
    np.save(partial, counts)
    partial.rename(target)
    return str(target)


def histogram_path(scenario: str, period: str) -> Path:
    return cache_path("loca2", "hist", f"{scenario}_{period}.npy")


def build(scenario: str, period: str, cells: np.ndarray) -> None:
    target = histogram_path(scenario, period)
    if target.exists():
        return
    pieces = day_slices(scenario, period)
    with ProcessPoolExecutor(WORKERS) as pool:
        partials = list(
            pool.map(
                histogram_slice,
                pieces,
                [cells] * len(pieces),
                [f"{scenario}_{period}_{i}.npy" for i in range(len(pieces))],
            )
        )
    total = sum(np.load(p).astype(np.uint32) for p in partials)
    np.save(target, np.asarray(total, dtype=np.uint16))
    for path in partials:
        cache_path("loca2", "partial", path.rsplit("/", 1)[-1]).unlink()
    print(f"LOCA2 {scenario} {period}: {int(total[:, 0].sum())} days", flush=True)


def build_all() -> None:
    cells, _, _ = county_weights()
    build("historical", "historical", cells)
    for scenario in ("ssp245", "ssp585"):
        for period in ("MID", "LATE"):
            build(scenario, period, cells)
