"""Figures written next to the result tables."""

from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from hurloss_rebuild.sources.counties import EQUAL_AREA

MAP_BOUNDS = (-107.0, 24.0, -66.5, 49.0)


def county_maps(
    shapes: gpd.GeoDataFrame, panels: dict[str, pd.Series], target: Path, vmin: float, vmax: float
) -> Path:
    """One choropleth per panel, same colour scale, counties without a value in grey."""
    box = shapes.cx[MAP_BOUNDS[0] : MAP_BOUNDS[2], MAP_BOUNDS[1] : MAP_BOUNDS[3]]
    box = box[~box["STUSPS"].isin(["AK", "HI", "PR"])].to_crs(EQUAL_AREA)
    figure, axes = plt.subplots(1, len(panels), figsize=(6 * len(panels), 4.2), squeeze=False)
    for axis, (title, values) in zip(axes[0], panels.items(), strict=True):
        shaded = box.assign(value=values.reindex(box.index))
        shaded.plot(ax=axis, color="#dddddd", linewidth=0)
        shaded.dropna(subset=["value"]).plot(
            ax=axis, column="value", cmap="viridis", vmin=vmin, vmax=vmax, linewidth=0, legend=True
        )
        axis.set_title(title, fontsize=10)
        axis.set_axis_off()
    figure.tight_layout()
    figure.savefig(target, dpi=110)
    plt.close(figure)
    return target


def published_vs_rebuilt(details: pd.DataFrame, pairs: list[tuple[str, str]], target: Path) -> Path:
    """Scatter of published against rebuilt multipliers, one panel per (method, scenario)."""
    figure, axes = plt.subplots(1, len(pairs), figsize=(4 * len(pairs), 4), squeeze=False)
    for axis, (method, scenario) in zip(axes[0], pairs, strict=True):
        part = details[(details["method"] == method) & (details["scenario"] == scenario)]
        axis.scatter(part["rebuilt"], part["published"], s=4, alpha=0.4)
        axis.set_xlabel("rebuilt HM")
        axis.set_ylabel("published HM")
        axis.set_title(f"{method}\n{scenario}", fontsize=9)
        axis.set_ylim(0.9, 4)
        axis.set_xlim(0.9, 4)
    figure.tight_layout()
    figure.savefig(target, dpi=110)
    plt.close(figure)
    return target
