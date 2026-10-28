"""STORM's master loop (its MASTER.py) for one 1,000-year chunk, run in a worker process.

It lives in a module, not a notebook cell, because a process pool can only start functions it
can import. `code` is the folder holding STORM's patched modules and their input files.
"""

import importlib
import random
import sys
import time
from pathlib import Path

import numpy as np


def run_chunk(code: Path, seed: int, years: int, target: Path) -> float:
    """Simulate `years` North Atlantic years with `seed`, write STORM's text format, return s."""
    if years < 1:
        raise ValueError(f"years must be positive, not {years}")
    if str(code) not in sys.path:
        sys.path.insert(0, str(code))
    # STORM's modules exist only in `code`, downloaded at run time.
    basins = importlib.import_module("SELECT_BASIN").Basins_WMO
    starting_point = importlib.import_module("SAMPLE_STARTING_POINT").Startingpoint
    movement = importlib.import_module("SAMPLE_TC_MOVEMENT").TC_movement
    pressure = importlib.import_module("SAMPLE_TC_PRESSURE").TC_pressure

    start = time.perf_counter()
    # STORM draws from both of Python's generators, so both are seeded.
    random.seed(seed)
    np.random.seed(seed)
    rows: list[list[float]] = []
    for year in range(years):
        storms, months, *_ = basins("NA")
        if storms > 0:
            lon, lat = starting_point(storms, months, "NA")
            lats, lons, landfall = movement(lon, lat, "NA")
            rows = pressure("NA", lats, lons, landfall, year, storms, months, rows)
    if not rows:
        raise RuntimeError(f"seed {seed} produced no storms")
    partial = target.with_suffix(".partial")
    np.savetxt(partial, np.array(rows), fmt="%5s", delimiter=",")
    partial.rename(target)
    return time.perf_counter() - start
