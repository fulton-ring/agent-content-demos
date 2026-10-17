"""Census-tract choropleths shared by the notebooks."""

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

from fri_rebuild.sources import geo


def tract_map(values: pd.Series, state_fips: str, title: str, county: str | None = None) -> Figure:
    """Map tract values (indexed by 11-digit tract FIPS) for one state, or one county in it.

    A state map draws county boundaries; a county map outlines each tract instead.
    """
    shapes = geo.tracts(state_fips)
    if county is not None:
        shapes = shapes[shapes.index.str[:5] == county]
    shapes = gpd.GeoDataFrame(shapes.join(values.rename("value"))).to_crs(geo.EQUAL_AREA)
    fig, ax = plt.subplots(figsize=(10, 8))
    shapes.plot(
        column="value",
        ax=ax,
        cmap="YlOrRd",
        legend=True,
        linewidth=0.2 if county else 0,
        edgecolor="#666",
        legend_kwds={"label": "Hazard multiplier", "shrink": 0.6},
        missing_kwds={"color": "#ddd"},
    )
    if county is None:
        lines = geo.counties()
        lines = gpd.GeoSeries(lines.loc[lines["STATEFP"] == state_fips].geometry)
        lines.to_crs(geo.EQUAL_AREA).boundary.plot(ax=ax, color="#333", linewidth=0.4)
    ax.set_axis_off()
    ax.set_title(title)
    fig.tight_layout()
    return fig
