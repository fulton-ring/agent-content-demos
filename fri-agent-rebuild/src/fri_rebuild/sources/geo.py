"""County and tract boundaries, and area weights from the 0.25-degree NEX grid to them."""

import io
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely
from scipy import sparse

from fri_rebuild.paths import cache_path

COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip"
TRACT_URL = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_{state}_tract_500k.zip"
EQUAL_AREA = "EPSG:5070"
CELL = 0.25


def download_shapes(url: str, name: str) -> gpd.GeoDataFrame:
    target = cache_path("geo", f"{name}.parquet")
    if not target.exists():
        response = requests.get(url, timeout=300)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            shp = next(n for n in archive.namelist() if n.endswith(".shp"))
            folder = cache_path("geo", name, "x").parent
            archive.extractall(folder)
        gpd.read_file(folder / shp).to_parquet(target)
    return gpd.read_parquet(target)


def counties() -> gpd.GeoDataFrame:
    """2020 Census counties (the geography NRI v1.19 and the Future Risk Index use)."""
    shapes = download_shapes(COUNTY_URL, "counties_2020")
    return shapes.rename(columns={"GEOID": "fips"}).set_index("fips")[
        ["STATEFP", "NAME", "geometry"]
    ]


def tracts(state_fips: str) -> gpd.GeoDataFrame:
    """2020 Census tracts for one state."""
    shapes = download_shapes(TRACT_URL.format(state=state_fips), f"tracts_2020_{state_fips}")
    return shapes.rename(columns={"GEOID": "tract"}).set_index("tract")[["COUNTYFP", "geometry"]]


def cell_polygons(lat: np.ndarray, lon: np.ndarray) -> gpd.GeoDataFrame:
    """One polygon per grid cell, in row-major order of a (lat, lon) array."""
    lons = np.where(lon > 180, lon - 360, lon)
    grid_lat, grid_lon = np.meshgrid(lat, lons, indexing="ij")
    half = CELL / 2
    x, y = grid_lon.ravel(), grid_lat.ravel()
    cells = shapely.box(x - half, y - half, x + half, y + half)
    table = pd.DataFrame({"cell": np.arange(len(cells)), "geometry": cells})
    # geopandas ships no type stubs that agree with pandas-stubs' DataFrame overloads.
    return gpd.GeoDataFrame(table, geometry="geometry", crs="EPSG:4326")  # ty: ignore[no-matching-overload]


def area_weights(
    areas: gpd.GeoDataFrame, lat: np.ndarray, lon: np.ndarray, name: str
) -> tuple[sparse.csr_matrix, pd.Index]:
    """Sparse matrix of intersection areas (km^2), rows = areas, columns = grid cells."""
    target = cache_path("geo", f"weights_{name}.npz")
    ids_path = cache_path("geo", f"weights_{name}_ids.parquet")
    if not target.exists():
        cells = cell_polygons(lat, lon).to_crs(EQUAL_AREA)
        shapes = areas.to_crs(EQUAL_AREA).reset_index(names="area_id")
        pieces = gpd.overlay(shapes[["area_id", "geometry"]], cells, how="intersection")
        rows = pd.Index(shapes["area_id"])
        matrix = sparse.csr_matrix(
            (
                pieces.geometry.area.to_numpy() / 1e6,
                (rows.get_indexer(pieces["area_id"]), pieces["cell"].to_numpy()),
            ),
            shape=(len(rows), len(cells)),
        )
        sparse.save_npz(target, matrix)
        pd.DataFrame({"area_id": rows}).to_parquet(ids_path)
    ids = pd.Index(pd.read_parquet(ids_path)["area_id"])
    return sparse.csr_matrix(sparse.load_npz(target)), ids


def points(table: pd.DataFrame, lon: str = "lon", lat: str = "lat") -> gpd.GeoDataFrame:
    """A GeoDataFrame (EPSG:4326) of the table's rows placed at their lon/lat columns."""
    geometry = gpd.points_from_xy(table[lon].astype(float), table[lat].astype(float))
    # geopandas ships no type stubs that agree with pandas-stubs' DataFrame overloads.
    return gpd.GeoDataFrame(table, geometry=geometry, crs="EPSG:4326")  # ty: ignore[no-matching-overload]
