"""2020 Census county boundaries (the geography NRI v1.19 and the Future Risk Index use)."""

import zipfile

import geopandas as gpd

from hurloss_rebuild import http
from hurloss_rebuild.paths import cache_path

COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip"
EQUAL_AREA = "EPSG:5070"


def load() -> gpd.GeoDataFrame:
    """County polygons indexed by 5-digit FIPS, in EPSG:4326."""
    target = cache_path("geo", "counties_2020.parquet")
    if not target.exists():
        archive = http.download(COUNTY_URL, cache_path("geo", "cb_2020_us_county_500k.zip"))
        folder = cache_path("geo", "counties_2020", "x").parent
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(folder)
        gpd.read_file(next(folder.glob("*.shp"))).to_parquet(target)
    shapes = gpd.read_parquet(target).rename(columns={"GEOID": "fips"}).set_index("fips")
    return shapes[["STUSPS", "NAME", "geometry"]].to_crs("EPSG:4326")
