"""The wind points: a regular lat/lon grid over the hurricane-exposed CONUS, mapped to counties.

ARA's point set is not public. FEMA averaged all ARA points within 1 km of each county (FRI
Sec. 7.2). We use a regular grid, keep the points inside a 1 km county buffer, and give a county
with no grid point inside its buffer the nearest point, which FEMA's denser points would not need.
"""

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd

from hurloss_rebuild.sources.counties import EQUAL_AREA

SOUTH, NORTH = 24.0, 49.0
WEST, EAST = -107.0, -66.5
BUFFER_M = 1000.0


@dataclass(frozen=True)
class Grid:
    lat: np.ndarray
    lon: np.ndarray
    point_county: pd.Series  # index: point position, values: county FIPS


def regular_points(step: float) -> tuple[np.ndarray, np.ndarray]:
    if not 0.01 <= step <= 1.0:
        raise ValueError(f"grid step out of range: {step}")
    lat, lon = np.meshgrid(
        np.arange(SOUTH, NORTH, step), np.arange(WEST, EAST, step), indexing="ij"
    )
    return lat.ravel(), lon.ravel()


def build(counties: gpd.GeoDataFrame, step: float) -> Grid:
    """Grid points that fall within 1 km of a county in the box, and the county of each."""
    lat, lon = regular_points(step)
    # geopandas ships no type stubs that agree with pandas-stubs' DataFrame overloads.
    points = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lon, lat), crs="EPSG:4326")  # ty: ignore[no-matching-overload]
    points = points.to_crs(EQUAL_AREA)
    shapes = counties[["geometry"]].to_crs(EQUAL_AREA)
    in_box = shapes.cx[points.total_bounds[0] : points.total_bounds[2], :]
    buffered = in_box.assign(geometry=in_box.buffer(BUFFER_M)).reset_index(names="fips")
    inside = gpd.sjoin(points, buffered, predicate="within")[["fips"]]
    empty = buffered[~buffered["fips"].isin(inside["fips"])]
    nearest = gpd.sjoin_nearest(empty[["fips", "geometry"]], points)[["fips", "index_right"]]
    pairs = pd.concat(
        [
            pd.DataFrame({"point": inside.index.to_numpy(), "fips": inside["fips"].to_numpy()}),
            pd.DataFrame({"point": nearest["index_right"].to_numpy(), "fips": nearest["fips"]}),
        ]
    )
    used = np.sort(pairs["point"].unique())
    position = pd.Series(np.arange(len(used)), index=used)
    mapping = pd.Series(pairs["fips"].to_numpy(), index=position[pairs["point"]].to_numpy())
    return Grid(lat=lat[used], lon=lon[used], point_county=mapping)


def tract_points(centroids: pd.DataFrame) -> Grid:
    """One point per tract, at its population-weighted centre; `point_county` holds tract FIPS."""
    if centroids.empty:
        raise ValueError("no tract centroids")
    return Grid(
        lat=centroids["latitude"].to_numpy(dtype=float),
        lon=centroids["longitude"].to_numpy(dtype=float),
        point_county=pd.Series(centroids.index.to_numpy(), index=np.arange(len(centroids))),
    )
