"""Wind fields from tracks, with CLIMADA (Holland 2008 profile, 1-minute sustained wind at 10 m).

Every event set is cached as a CLIMADA hazard file named after what produced it, so reruns with
the same settings skip the wind computation.
"""

import logging
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
import pathos.pools
from climada.hazard import Centroids, TCTracks, TropCyclone
from scipy import sparse

from hurloss_rebuild.grid import EAST, NORTH, SOUTH, WEST, Grid
from hurloss_rebuild.paths import cache_path

LOG = logging.getLogger(__name__)
TIME_STEP_H = 1.0
BOX_MARGIN_DEG = 2.0


@dataclass(frozen=True)
class Events:
    """Peak wind per event and point, with each event's annual rate and metadata."""

    wind: sparse.csr_matrix  # events x points, m/s
    frequency: np.ndarray  # events per year
    category: np.ndarray  # Saffir-Simpson category of the track's lifetime peak (-1 = TD)
    basin: np.ndarray
    years: tuple[int, int]


def near_box(tracks: TCTracks) -> TCTracks:
    """Only tracks with a fix within the grid box (plus a margin) can put wind on a point."""
    kept = [
        track
        for track in tracks.data
        if (
            (track.lat > SOUTH - BOX_MARGIN_DEG)
            & (track.lat < NORTH + BOX_MARGIN_DEG)
            & (track.lon > WEST - BOX_MARGIN_DEG)
            & (track.lon < EAST + BOX_MARGIN_DEG)
        ).any()
    ]
    if not kept:
        raise RuntimeError("no track comes near the grid")
    return TCTracks(data=kept)


def workers() -> int:
    count = int(os.environ.get("HURLOSS_WORKERS", os.cpu_count() or 1))
    if count < 1:
        raise ValueError("HURLOSS_WORKERS must be at least 1")
    return count


@contextmanager
def process_pool() -> Generator[pathos.pools.ProcessPool]:
    pool = pathos.pools.ProcessPool(nodes=workers())
    try:
        yield pool
    finally:
        pool.close()
        pool.join()
        pool.clear()


def hourly(tracks: TCTracks, pool: pathos.pools.ProcessPool) -> TCTracks:
    """Resample tracks to the wind-field time step, in parallel."""
    tracks.equal_timestep(time_step_h=TIME_STEP_H, pool=pool)
    return tracks


def wind_fields(
    make_tracks: Callable[[pathos.pools.ProcessPool], TCTracks], grid: Grid, name: str
) -> TropCyclone:
    """CLIMADA wind fields on the grid points, cached under `name`.

    `make_tracks` builds hourly tracks; it only runs when the cache is empty.
    """
    target = cache_path("hazard", f"{name}.h5")
    if target.exists():
        return TropCyclone.from_hdf5(target)
    centroids = Centroids(lat=grid.lat, lon=grid.lon)
    with process_pool() as pool:
        tracks = make_tracks(pool)
        LOG.info("wind fields for %s: %d tracks on %d points", name, tracks.size, grid.lat.size)
        hazard = TropCyclone.from_tracks(
            tracks, centroids=centroids, pool=pool, ignore_distance_to_coast=True
        )
    hazard.pool = None
    partial = target.with_suffix(".partial.h5")
    hazard.write_hdf5(partial)
    partial.rename(target)
    return hazard


def events(hazard: TropCyclone, years: tuple[int, int], rate: float | None = None) -> Events:
    """Plain arrays from a CLIMADA hazard; `rate` overrides every event's annual frequency."""
    frequency = np.full(hazard.size, rate) if rate is not None else np.asarray(hazard.frequency)
    if frequency.shape[0] != hazard.intensity.shape[0]:
        raise ValueError("hazard frequency and intensity differ in length")
    return Events(
        wind=sparse.csr_matrix(hazard.intensity),
        frequency=frequency.astype(float),
        category=np.asarray(hazard.category),
        basin=np.asarray(hazard.basin),
        years=years,
    )
