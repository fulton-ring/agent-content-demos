"""The two public event sets: perturbed historical tracks, and STORM present/future climate."""

import logging
import os

import xarray as xr
from climada.hazard import TCTracks
from pathos.pools import ProcessPool

from hurloss_rebuild import hazard
from hurloss_rebuild.grid import Grid
from hurloss_rebuild.hazard import Events
from hurloss_rebuild.sources import ibtracs, storm

LOG = logging.getLogger(__name__)
HISTORY = (1900, 2024)
STORM_PRESENT_YEARS = (1980, 2018)
STORM_FUTURE_YEARS = (2015, 2050)
SEED = 8


def env_int(name: str, default: int, low: int, high: int) -> int:
    value = int(os.environ.get(name, default))
    if not low <= value <= high:
        raise ValueError(f"{name}={value} is outside {low}-{high}")
    return value


def historical(grid: Grid, tag: str) -> Events:
    """IBTrACS 1900-2024 plus CLIMADA's perturbed copies (random-walk tracks, land decay)."""
    copies = env_int("HURLOSS_SYNTHETIC_COPIES", 19, 0, 49)
    name = f"ibtracs_{HISTORY[0]}_{HISTORY[1]}_x{copies + 1}_{tag}"

    def make_tracks(pool: ProcessPool) -> TCTracks:
        tracks = hazard.hourly(hazard.near_box(ibtracs.tracks(*HISTORY)), pool)
        if copies:
            tracks.calc_perturbed_trajectories(
                nb_synth_tracks=copies, use_global_decay_params=True, seed=SEED, pool=pool
            )
        return tracks

    fields = hazard.wind_fields(make_tracks, grid, name)
    years = HISTORY[1] - HISTORY[0] + 1
    return hazard.events(fields, HISTORY, rate=1.0 / (years * (copies + 1)))


def west_negative(track: xr.Dataset) -> xr.Dataset:
    """STORM gives longitude as 0-360; the grid and IBTrACS use -180-180."""
    return track.assign_coords(lon=((track.lon + 180) % 360) - 180)


def storm_tracks(model: str | None, files: int, pool: ProcessPool) -> TCTracks:
    parts = [TCTracks.from_simulations_storm(storm.fetch(model, i)) for i in range(files)]
    tracks = TCTracks(data=[west_negative(track) for part in parts for track in part.data])
    return hazard.hourly(hazard.near_box(tracks), pool)


def storm_set(model: str | None, grid: Grid, tag: str) -> Events:
    """STORM North Atlantic tracks; `model` None is the present climate."""
    files = env_int("HURLOSS_STORM_FILES", 5, 1, storm.FILES_PER_SET)
    label = model or "present"
    name = f"storm_{label}_{files}k_{tag}"
    fields = hazard.wind_fields(lambda pool: storm_tracks(model, files, pool), grid, name)
    period = STORM_PRESENT_YEARS if model is None else STORM_FUTURE_YEARS
    events = hazard.events(fields, period, rate=1.0 / (files * storm.YEARS_PER_FILE))
    LOG.info("STORM %s: %d events near the grid", label, events.wind.shape[0])
    return events


def storm_future(grid: Grid, tag: str) -> list[Events]:
    """One event set per STORM future-climate GCM."""
    return [storm_set(model, grid, tag) for model in storm.FUTURE_ZIPS]
