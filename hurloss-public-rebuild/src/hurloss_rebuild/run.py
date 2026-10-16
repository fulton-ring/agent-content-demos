"""One command: download the public inputs, build the event sets, rebuild and score HRCN.

Writes CSV tables to the results folder and logs progress and timings to stdout.
"""

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from hurloss_rebuild import (
    ara_white_paper,
    baseline,
    conditioning,
    event_sets,
    figures,
    forensics,
    grid,
    rebuild,
)
from hurloss_rebuild.hazard import Events
from hurloss_rebuild.paths import results_dir
from hurloss_rebuild.scoring import metrics
from hurloss_rebuild.sources import answer_key, counties, nri, storm

LOG = logging.getLogger("hurloss")


class Timer:
    """Wall-clock seconds per named step, logged as each finishes."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def run[T](self, step: str, action: Callable[[], T]) -> T:
        start = time.perf_counter()
        result = action()
        seconds = time.perf_counter() - start
        self.rows.append({"step": step, "seconds": round(seconds, 1)})
        LOG.info("%s: %.1f s", step, seconds)
        return result


def write(table: pd.DataFrame, name: str, index: bool = False) -> Path:
    target = results_dir() / name
    table.to_csv(target, index=index, float_format="%.6g")
    LOG.info("wrote %s (%d rows)", target, len(table))
    return target


def physical_methods(
    history: Events,
    present: Events,
    futures: list[Events],
    point_county: pd.Series,
    regions: np.ndarray,
) -> dict[str, pd.DataFrame]:
    """Unfloored intensity ratios per county for each public conditioning route."""
    storm_ratio = rebuild.ensemble_ratio(present, futures, point_county)
    today = rebuild.county_intensity(history, point_county)
    ara = rebuild.county_intensity(ara_white_paper.condition(history, regions), point_county)
    return {
        "knutson_frequency": rebuild.conditioned_ratios(
            history, point_county, conditioning.frequency_only
        ),
        "knutson_intensity": rebuild.conditioned_ratios(
            history, point_county, conditioning.intensity_and_frequency
        ),
        "storm_ssp585": pd.DataFrame({"MID_HIGHER": storm_ratio}),
        "ara_figure_1": pd.DataFrame({"MID_HIGHER": rebuild.ratio(ara, today)}),
    }


def rebuilt_tables(ratios: dict[str, pd.DataFrame], key: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Each route through FEMA's documented formula, and through the two readings of the 2x."""
    tables = {
        "constant_1": forensics.constant(key, 1.0),
        "constant_2": forensics.constant(key, 2.0),
    }
    for name, table in ratios.items():
        clean = rebuild.drop_nonfinite(table)
        tables[name] = rebuild.as_fema(clean)
        tables[f"{name}_times_2"] = rebuild.doubled(clean)
        tables[f"{name}_plus_1"] = rebuild.plus_one(clean)
    return tables


def score_all(
    tables: dict[str, pd.DataFrame], key: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    scores, details = [], []
    for name, table in tables.items():
        result, detail = metrics.score(key, table, name)
        scores.append(result)
        details.append(detail)
    return pd.concat(scores, ignore_index=True), pd.concat(details)


def largest_differences(details: pd.DataFrame, per_group: int = 5) -> pd.DataFrame:
    """The held-out counties furthest from FEMA, per method and scenario."""
    held_out = details[details["subset"] == "held_out"].assign(miss=lambda t: t["log_error"].abs())
    ranked = held_out.sort_values("miss", ascending=False)
    return ranked.groupby(["method", "scenario"]).head(per_group).drop(columns="miss")


def draw(
    shapes: gpd.GeoDataFrame,
    key: pd.DataFrame,
    ratios: dict[str, pd.DataFrame],
    details: pd.DataFrame,
) -> None:
    published = {
        f"FEMA published, {s}": key[f"HRCN_{s}_HM"].where(lambda v: v > 0)
        for s in ("MID_HIGHER", "LATE_HIGHER")
    }
    rebuilt = {
        "Public: STORM SSP5-8.5 2050 ratio": ratios["storm_ssp585"]["MID_HIGHER"],
        "Public: Knutson frequency, late higher": ratios["knutson_frequency"]["LATE_HIGHER"],
    }
    figures.county_maps(shapes, published, results_dir() / "map_published.png", 1.0, 2.6)
    figures.county_maps(shapes, rebuilt, results_dir() / "map_rebuilt_ratio.png", 0.6, 1.6)
    pairs = [
        ("storm_ssp585", "MID_HIGHER"),
        ("ara_figure_1", "MID_HIGHER"),
        ("knutson_frequency", "LATE_HIGHER"),
        ("knutson_intensity", "LATE_HIGHER"),
    ]
    held_out = details[details["subset"] == "held_out"]
    figures.published_vs_rebuilt(held_out, pairs, results_dir() / "scatter_held_out.png")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    timer = Timer()
    step = float(os.environ.get("HURLOSS_GRID_STEP", "0.25"))
    tag = f"grid{step:g}"
    key = answer_key.conus(timer.run("answer key", answer_key.load))
    write(forensics.level_summary(key), "answer_key_levels.csv")
    write(forensics.zero_with_losses(key), "answer_key_zero_with_losses.csv", index=True)
    write(ara_white_paper.compare_with_published(key), "ara_white_paper.csv", index=True)
    shapes = timer.run("counties", counties.load)
    points = timer.run("grid", lambda: grid.build(shapes, step))
    LOG.info("%d grid points cover %d counties", points.lat.size, points.point_county.nunique())
    history = timer.run("historical event set", lambda: event_sets.historical(points, tag))
    files = event_sets.storm_files()
    present = timer.run("STORM present", lambda: event_sets.storm_set(None, points, tag, files))
    futures = timer.run("STORM future", lambda: event_sets.storm_future(points, tag, files))
    nri_table = timer.run("NRI v1.20", nri.counties)
    for label, events in (("historical", history), ("storm_present", present)):
        table = baseline.county_table(events, points.point_county, nri_table)
        write(table, f"baseline_{label}_by_county.csv", index=True)
        write(baseline.agreement(table).assign(event_set=label), f"baseline_{label}.csv")
    hazard_level = {
        "historical_intensity_today": rebuild.county_intensity(history, points.point_county),
        "storm_intensity_today": rebuild.county_intensity(present, points.point_county),
        "nri_v1_20_loss_ratio": nri_table["HRCN_EALT"] / nri_table["HRCN_EXPT"],
        "nri_v1_19_eal": key["HRCN_EALT"],
    }
    write(forensics.rank_against(key, hazard_level), "published_vs_hazard_level.csv")
    by_gcm = dict(zip(storm.FUTURE_ZIPS, futures, strict=True))
    write(rebuild.gcm_spread(present, by_gcm, points.point_county), "storm_gcm_ratios.csv")
    regions = ara_white_paper.point_regions(points.point_county, shapes["STUSPS"])
    ratios = timer.run(
        "conditioning",
        lambda: physical_methods(history, present, futures, points.point_county, regions),
    )
    tables = rebuilt_tables(ratios, key)
    scores, details = timer.run("scoring", lambda: score_all(tables, key))
    write(scores, "scores.csv")
    write(details, "scores_by_county.csv", index=True)
    write(largest_differences(details), "largest_differences.csv", index=True)
    draw(shapes, key, ratios, details)
    write(pd.DataFrame(timer.rows), "timings.csv")


if __name__ == "__main__":
    main()
