"""One command: download the public inputs, build the event sets, rebuild and score HRCN.

Writes CSV tables to the results folder and logs progress and timings to stdout.
"""

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from hurloss_rebuild import baseline, conditioning, event_sets, forensics, grid, rebuild
from hurloss_rebuild.hazard import Events
from hurloss_rebuild.paths import results_dir
from hurloss_rebuild.scoring import metrics
from hurloss_rebuild.sources import answer_key, counties, nri

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
    history: Events, present: Events, futures: list[Events], point_county: pd.Series
) -> dict[str, pd.DataFrame]:
    """Unfloored intensity ratios per county for each public conditioning route."""
    storm_ratio = rebuild.ensemble_ratio(present, futures, point_county)
    return {
        "knutson_frequency": rebuild.conditioned_ratios(
            history, point_county, conditioning.frequency_only
        ),
        "knutson_intensity": rebuild.conditioned_ratios(
            history, point_county, conditioning.intensity_and_frequency
        ),
        "storm_ssp585": pd.DataFrame({"MID_HIGHER": storm_ratio}),
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    timer = Timer()
    step = float(os.environ.get("HURLOSS_GRID_STEP", "0.25"))
    tag = f"grid{step:g}"
    key = answer_key.conus(timer.run("answer key", answer_key.load))
    write(forensics.level_summary(key), "answer_key_levels.csv")
    write(forensics.zero_with_losses(key), "answer_key_zero_with_losses.csv", index=True)
    shapes = timer.run("counties", counties.load)
    points = timer.run("grid", lambda: grid.build(shapes, step))
    LOG.info("%d grid points cover %d counties", points.lat.size, points.point_county.nunique())
    history = timer.run("historical event set", lambda: event_sets.historical(points, tag))
    present = timer.run("STORM present", lambda: event_sets.storm_set(None, points, tag))
    futures = timer.run("STORM future", lambda: event_sets.storm_future(points, tag))
    nri_table = timer.run("NRI v1.20", nri.counties)
    for label, events in (("historical", history), ("storm_present", present)):
        table = baseline.county_table(events, points.point_county, nri_table)
        write(table, f"baseline_{label}_by_county.csv", index=True)
        write(baseline.agreement(table).assign(event_set=label), f"baseline_{label}.csv")
    ratios = timer.run(
        "conditioning", lambda: physical_methods(history, present, futures, points.point_county)
    )
    tables = rebuilt_tables(ratios, key)
    scores, details = timer.run("scoring", lambda: score_all(tables, key))
    write(scores, "scores.csv")
    write(details, "scores_by_county.csv", index=True)
    write(pd.DataFrame(timer.rows), "timings.csv")


if __name__ == "__main__":
    main()
