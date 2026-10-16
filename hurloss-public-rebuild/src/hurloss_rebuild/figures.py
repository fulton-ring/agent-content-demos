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


def layer_maps(
    shapes: gpd.GeoDataFrame, key: pd.DataFrame, ours: pd.DataFrame, target: Path
) -> Path:
    """FEMA's published multipliers next to ours, mid- and late-century under higher warming."""
    panels = {}
    for scenario in ("MID_HIGHER", "LATE_HIGHER"):
        published = key[f"HRCN_{scenario}_HM"]
        panels[f"FEMA, {scenario}"] = published.where(published > 0)
        panels[f"Ours (Knutson median), {scenario}"] = ours[f"{scenario}_HM"]
    return county_maps(shapes, panels, target, 1.0, 2.2)


def tract_map(shapes: gpd.GeoDataFrame, table: pd.DataFrame, state: str, target: Path) -> Path:
    """Tract multipliers (late century, higher) as points over the state's counties."""
    outline = shapes[shapes["STUSPS"] == state].to_crs(EQUAL_AREA)
    geometry = gpd.points_from_xy(table["longitude"], table["latitude"])
    # geopandas ships no type stubs that agree with pandas-stubs' DataFrame overloads.
    points = gpd.GeoDataFrame(table[["LATE_HIGHER_HM"]], geometry=geometry, crs="EPSG:4326")  # ty: ignore[no-matching-overload]
    points = points.to_crs(EQUAL_AREA)
    figure, axis = plt.subplots(figsize=(7, 7))
    outline.boundary.plot(ax=axis, color="#999999", linewidth=0.4)
    points.plot(ax=axis, column="LATE_HIGHER_HM", cmap="viridis", markersize=3, legend=True)
    axis.set_title(f"Tract HM, late century higher (Knutson median), {state}", fontsize=10)
    axis.set_axis_off()
    figure.tight_layout()
    figure.savefig(target, dpi=110)
    plt.close(figure)
    return target
