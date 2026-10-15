"""LANDFIRE LF2022 40 Scott and Burgan fuel models (FBFM40), resampled to 500 m.

The 30 m national raster is a 3.4 GB download, so we ask LANDFIRE's ImageServer for a
nearest-neighbour 500 m export in tiles. County (or tract) fuel shares come from counting the
500 m pixels that fall in each polygon.
"""

import io

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio import features
from rasterio.transform import from_origin

from fri_rebuild.paths import cache_path

SERVICE = (
    "https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2022/LF2022_FBFM40_CONUS/ImageServer"
)
CRS = "EPSG:5070"
BOUNDS = (-2362395.0, 221265.0, 2327655.0, 3267405.0)
PIXEL = 500.0
TILES = (2, 2)
# Fuel model groups by FBFM40 code range (Scott and Burgan 2005).
GROUPS = {
    "nonburnable": range(91, 100),
    "grass": range(101, 110),
    "grass_shrub": range(121, 125),
    "shrub": range(141, 150),
    "timber_understory": range(161, 166),
    "timber_litter": range(181, 190),
    "slash_blowdown": range(201, 205),
}


def mosaic() -> tuple[np.ndarray, rasterio.Affine]:
    """The 500 m FBFM40 grid over CONUS (0 outside CONUS) and its transform."""
    target = cache_path("landfire", "fbfm40_lf2022_500m.npy")
    left, bottom, right, top = BOUNDS
    width = int(np.ceil((right - left) / PIXEL))
    height = int(np.ceil((top - bottom) / PIXEL))
    transform = from_origin(left, top, PIXEL, PIXEL)
    if not target.exists():
        grid = np.zeros((height, width), dtype=np.uint8)
        col_edges = np.linspace(0, width, TILES[0] + 1).astype(int)
        row_edges = np.linspace(0, height, TILES[1] + 1).astype(int)
        for r0, r1 in zip(row_edges[:-1], row_edges[1:], strict=True):
            for c0, c1 in zip(col_edges[:-1], col_edges[1:], strict=True):
                grid[r0:r1, c0:c1] = export_tile(
                    left + c0 * PIXEL, top - r1 * PIXEL, c1 - c0, r1 - r0
                )
        np.save(target, grid)
    return np.load(target), transform


def export_tile(x0: float, y0: float, width: int, height: int) -> np.ndarray:
    params = {
        "bbox": f"{x0},{y0},{x0 + width * PIXEL},{y0 + height * PIXEL}",
        "bboxSR": "5070",
        "imageSR": "5070",
        "size": f"{width},{height}",
        "format": "tiff",
        "pixelType": "U8",
        "interpolation": "RSP_NearestNeighbor",
        "f": "image",
    }
    response = requests.get(f"{SERVICE}/exportImage", params=params, timeout=600)
    response.raise_for_status()
    with rasterio.open(io.BytesIO(response.content)) as tile:
        data = tile.read(1)
    if data.shape != (height, width):
        raise ValueError(f"tile came back {data.shape}, expected {(height, width)}")
    return data


def fuel_shares(areas: gpd.GeoDataFrame, name: str) -> pd.DataFrame:
    """Share of each fuel group's pixels in every polygon (rows sum to 1 where covered)."""
    target = cache_path("landfire", f"shares_{name}.parquet")
    if not target.exists():
        grid, transform = mosaic()
        shapes = areas.to_crs(CRS)
        labels = features.rasterize(
            zip(shapes.geometry, range(1, len(shapes) + 1), strict=True),
            out_shape=grid.shape,
            transform=transform,
            fill=0,
            dtype=np.int32,
        )
        group_of_code = np.zeros(256, dtype=np.int8) - 1
        for index, codes in enumerate(GROUPS.values()):
            group_of_code[list(codes)] = index
        groups = group_of_code[grid]
        keep = (labels > 0) & (groups >= 0)
        counts = np.zeros((len(shapes) + 1, len(GROUPS)))
        np.add.at(counts, (labels[keep], groups[keep]), 1)
        counts = counts[1:]
        totals = counts.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore"):
            shares = pd.DataFrame(counts / totals, index=areas.index, columns=list(GROUPS))
        shares.to_parquet(target)
    return pd.read_parquet(target)


if __name__ == "__main__":
    from fri_rebuild import answer_key, geo

    key = answer_key.conus(answer_key.load())
    print(fuel_shares(geo.counties().loc[key.index], "counties").describe().round(3))
