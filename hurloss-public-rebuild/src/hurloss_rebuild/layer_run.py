"""One command for the hurricane layer: our multipliers by county and tract, against FEMA's.

Run after `hurloss-run` (the spike), whose cached STORM sets the cross-check reuses. Writes to
`results/layer/` and logs to stdout.
"""

import logging
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

from hurloss_rebuild import (
    compare_fri,
    event_sets,
    figures,
    grid,
    layer,
    rebuild,
    tract_layer,
    validation,
)
from hurloss_rebuild.hazard import Events
from hurloss_rebuild.paths import results_dir
from hurloss_rebuild.run import Timer
from hurloss_rebuild.sources import answer_key, counties, ibtracs, nri, storm, tracts

LOG = logging.getLogger("hurloss.layer")
COUNTY_STEP = 0.25


def out(name: str) -> Path:
    folder = results_dir() / "layer"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def write(table: pd.DataFrame, name: str, index: bool = False) -> None:
    table.to_csv(out(name), index=index, float_format="%.6g")
    LOG.info("wrote %s (%d rows)", out(name), len(table))


def layer_files() -> int:
    """1,000-year STORM files behind the layer's present-day hazard (default: all ten)."""
    return event_sets.env_int("HURLOSS_LAYER_STORM_FILES", storm.FILES_PER_SET, 1, 10)


def tract_states() -> list[str]:
    states = os.environ.get("HURLOSS_TRACT_STATES", "12").split(",")
    return [state.strip() for state in states if state.strip()]


def storm_cross_check(points: grid.Grid, ours: pd.DataFrame) -> pd.DataFrame:
    """STORM's own 2050 SSP5-8.5 GCMs (the spike's cached sets) against our Knutson range."""
    files = event_sets.storm_files()
    present = event_sets.storm_set(None, points, f"grid{COUNTY_STEP:g}", files)
    futures = event_sets.storm_future(points, f"grid{COUNTY_STEP:g}", files)
    ensemble = rebuild.ensemble_ratio(present, futures, points.point_county)
    return compare_fri.storm_check(ours, ensemble)


def return_period_check(files: int) -> pd.DataFrame:
    """STORM and the observed record against NHC's published return periods."""
    observed = ibtracs.tracks(*event_sets.HISTORY)
    years = event_sets.HISTORY[1] - event_sets.HISTORY[0] + 1
    return validation.return_periods(
        validation.storm_fixes(files),
        files * storm.YEARS_PER_FILE,
        validation.best_track_fixes(observed),
        years,
    )


def state_abbreviation(shapes: gpd.GeoDataFrame, state_fips: str) -> str:
    codes = shapes.loc[shapes.index.str[:2] == state_fips, "STUSPS"].unique()
    if len(codes) != 1:
        raise ValueError(f"no single state for FIPS {state_fips}")
    return str(codes[0])


def tract_pilot(state_fips: str, abbr: str, files: int, county_hm: pd.DataFrame) -> pd.DataFrame:
    centroids = tracts.centroids(state_fips)
    points = grid.tract_points(centroids)
    events: Events = event_sets.storm_set(None, points, f"tracts{state_fips}", files)
    tract_hm = layer.multipliers(events, points.point_county)
    return tract_layer.tract_table(
        tract_hm, centroids, county_hm, tracts.nri("v1_19", abbr), tracts.nri("v1_20", abbr)
    )


def county_layer(
    points: grid.Grid, files: int, timer: Timer
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Multipliers from both open catalogues, and the combined layer."""
    tag = f"grid{COUNTY_STEP:g}"
    present = timer.run(
        f"STORM present, {files}k years", lambda: event_sets.storm_set(None, points, tag, files)
    )
    history = timer.run("historical event set", lambda: event_sets.historical(points, tag))
    catalogues = {
        "storm": layer.multipliers(present, points.point_county),
        "historical": layer.multipliers(history, points.point_county),
    }
    return layer.combine(catalogues), catalogues


def tract_projected_loss(shapes: gpd.GeoDataFrame, ours: pd.DataFrame) -> pd.DataFrame:
    """NRI v1.20 tract EAL x county multiplier, for every state with a county above HM = 1."""
    states = sorted(
        {state_abbreviation(shapes, fips[:2]) for fips in ours.index[~ours["no_cat1_wind"]]}
    )
    LOG.info("tract projected loss for %d states", len(states))
    return pd.concat([tract_layer.tract_loss(tracts.nri("v1_20", s), ours) for s in states])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    timer = Timer()
    files = layer_files()
    key = answer_key.conus(answer_key.load())
    shapes = counties.load()
    points = grid.build(shapes, COUNTY_STEP)
    ours, catalogues = county_layer(points, files, timer)
    write(ours, "county_multipliers.csv", index=True)
    write(validation.catalogue_agreement(catalogues), "check_catalogues.csv")
    comparison = compare_fri.by_county(ours, key, nri.counties()["HRCN_EALT"])
    write(comparison, "fri_comparison_by_county.csv", index=True)
    write(compare_fri.summary(comparison), "fri_comparison_summary.csv")
    write(
        timer.run("STORM cross-check", lambda: storm_cross_check(points, ours)), "storm_check.csv"
    )
    write(validation.places(comparison), "check_places.csv")
    write(
        timer.run("return periods", lambda: return_period_check(files)), "check_return_periods.csv"
    )
    figures.layer_maps(shapes, key, ours, out("map_fema_vs_ours.png"))
    figures.loss_maps(shapes, comparison, out("map_projected_loss.png"))
    loss = timer.run("tract projected loss", lambda: tract_projected_loss(shapes, ours))
    loss.to_csv(out("tract_projected_loss.csv.gz"), float_format="%.6g")
    LOG.info("wrote %s (%d rows)", out("tract_projected_loss.csv.gz"), len(loss))
    for state_fips in tract_states():
        abbr = state_abbreviation(shapes, state_fips)
        table = timer.run(
            f"tract wind pilot {abbr}", lambda s=state_fips, a=abbr: tract_pilot(s, a, files, ours)
        )
        write(table, f"tract_multipliers_{abbr}.csv", index=True)
        write(tract_layer.summary(table), f"tract_summary_{abbr}.csv")
        figures.tract_map(shapes, table, abbr, out(f"map_tracts_{abbr}.png"))
    write(pd.DataFrame(timer.rows), "timings.csv")


if __name__ == "__main__":
    main()
