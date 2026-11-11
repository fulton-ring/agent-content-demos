"""Fetch and decode NASA Black Marble night light from GIBS, shared by both notebooks.

NASA's LAADS archive serves Black Marble (VNP46A2 / VJ146A2) as HDF5 behind an Earthdata
login. NASA GIBS serves the same gap-filled, BRDF-corrected radiance as public PNG images,
colored with a published color map that has 180 radiance bins up to 38.2 nW/cm²/sr. We invert
that color map to get radiance back, and mask clouds with GIBS's VIIRS clear-sky confidence.
"""

import io
import os
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import geopandas as gpd
import httpx
import numpy as np
from PIL import Image

WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
COLORMAPS = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/"
RADIANCE_COLORMAP = "VIIRS_DayNightBand_At_Sensor_Radiance.xml"
CLEAR_COLORMAP = "VIIRS_Clear_Sky_Confidence.xml"
PIXELS_PER_DEGREE = 240  # Black Marble's native 15 arc-second grid
MAX_TRIES = 4


@dataclass(frozen=True)
class Grid:
    """A lon/lat box on Black Marble's 15 arc-second grid."""

    west: float
    south: float
    east: float
    north: float

    @property
    def shape(self) -> tuple[int, int]:
        height = round((self.north - self.south) * PIXELS_PER_DEGREE)
        width = round((self.east - self.west) * PIXELS_PER_DEGREE)
        return height, width


def cache_dir() -> Path:
    path = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def download(url: str, path: Path, params: dict[str, str] | None = None) -> Path:
    """Download url to path once, with bounded retries. Returns the cached path."""
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(MAX_TRIES):
        try:
            with httpx.stream(
                "GET", url, params=params, timeout=300, follow_redirects=True
            ) as response:
                response.raise_for_status()
                tmp = path.with_suffix(path.suffix + ".part")
                with open(tmp, "wb") as f:
                    f.writelines(response.iter_bytes(1 << 20))
            tmp.rename(path)
            return path
        except httpx.HTTPError:
            if attempt == MAX_TRIES - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def load_colormap(name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (rgb keys as int, lower bound, upper bound) for each data entry of a GIBS map."""
    text = download(COLORMAPS + name, cache_dir() / "colormaps" / name).read_text()
    entries = re.findall(
        r'<ColorMapEntry rgb="(\d+),(\d+),(\d+)"[^>]*? value="[\[(]([^"]*)[)\]]"', text
    )
    seen: dict[int, tuple[float, float]] = {}
    for r, g, b, bounds in entries:
        key = (int(r) << 16) | (int(g) << 8) | int(b)
        values = [float(v) for v in bounds.split(",")]
        if values[0] < 0:
            continue  # the no-data entry
        seen.setdefault(key, (values[0], values[-1]))
    assert len(seen) > 50, f"color map {name} parsed to only {len(seen)} entries"
    keys = np.array(sorted(seen))
    lows = np.array([seen[k][0] for k in keys])
    highs = np.array([seen[k][1] for k in keys])
    return keys, lows, highs


def fetch_png(layer: str, night: date, grid: Grid) -> np.ndarray:
    """One GIBS WMS image of the grid as an RGBA array, cached on disk."""
    height, width = grid.shape
    path = cache_dir() / "gibs" / layer / f"{night.isoformat()}_{grid.west}_{grid.south}.png"
    params = {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "VERSION": "1.3.0",
        "LAYERS": layer,
        "CRS": "EPSG:4326",
        "BBOX": f"{grid.south},{grid.west},{grid.north},{grid.east}",
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "FORMAT": "image/png",
        "TRANSPARENT": "TRUE",
        "TIME": night.isoformat(),
    }
    download(WMS, path, params)
    image = Image.open(io.BytesIO(path.read_bytes()))
    rgba = np.array(image.convert("RGBA"))
    assert rgba.shape[:2] == (height, width), f"{path} has shape {rgba.shape}"
    return rgba


def decode(rgba: np.ndarray, colormap: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    """Map each pixel's color back to the lower bound of its bin.

    No-data and unknown colors become NaN.
    """
    keys, lows, _ = colormap
    rgb = rgba[..., :3].astype(np.int64)
    flat = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
    index = np.clip(np.searchsorted(keys, flat), 0, len(keys) - 1)
    found = (keys[index] == flat) & (rgba[..., 3] > 0)
    return np.where(found, lows[index], np.nan)


def night_light(satellite: str, night: date, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """Radiance (nW/cm²/sr, lower bin edge) and clear-sky confidence (0-1) for one night."""
    radiance = decode(
        fetch_png(f"VIIRS_{satellite}_GapFilled_BRDF_Corrected_DayNightBand_Radiance", night, grid),
        load_colormap(RADIANCE_COLORMAP),
    )
    clear = decode(
        fetch_png(f"VIIRS_{satellite}_Clear_Sky_Confidence_Night", night, grid),
        load_colormap(CLEAR_COLORMAP),
    )
    return radiance, clear


CLEAR_CONFIDENCE = 0.95  # VIIRS cloud mask: at or above this a pixel counts as clear
LIT_RADIANCE = 5.0  # nW/cm²/sr: a pixel is "lit" if its usual brightness is at least this
DARK_RATIO = 0.5  # a lit pixel is "dark" on a night when it is below half its usual brightness
SATURATION = 38.2  # top bin of the GIBS color map; brighter pixels all decode to this


def nightly_stack(satellite: str, nights: list[date], grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """Radiance and clear-sky flags, one layer per night, as float32 and bool arrays."""
    assert len(nights) <= 120, "keep the window bounded"
    height, width = grid.shape
    radiance = np.full((len(nights), height, width), np.nan, dtype=np.float32)
    clear = np.zeros((len(nights), height, width), dtype=bool)
    for i, night in enumerate(nights):
        radiance[i], confidence = night_light(satellite, night, grid)
        clear[i] = confidence >= CLEAR_CONFIDENCE
    return radiance, clear


def usual_brightness(radiance: np.ndarray, clear: np.ndarray, min_nights: int = 3) -> np.ndarray:
    """Median radiance over the clear nights given, NaN where fewer than min_nights were clear."""
    masked = np.where(clear, radiance, np.nan)
    enough = clear.sum(axis=0) >= min_nights
    with np.errstate(all="ignore"):
        median = np.nanmedian(masked, axis=0)
    return np.where(enough, median, np.nan)


def dark_pixels(radiance: np.ndarray, usual: np.ndarray) -> np.ndarray:
    """True where a pixel is below half its usual brightness.

    A saturated usual value is only a lower bound, so half of 38.2 is used as the threshold
    there: anything below it is certainly below half the true usual brightness.
    """
    threshold = DARK_RATIO * np.minimum(usual, SATURATION)
    return radiance < threshold


def zone_index(zones: gpd.GeoDataFrame, grid: Grid) -> np.ndarray:
    """Rasterize zones onto the grid: each pixel holds its zone's row number, or -1."""
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds

    height, width = grid.shape
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, width, height)
    shapes = ((geom, i) for i, geom in enumerate(zones.geometry))
    return rasterize(shapes, out_shape=(height, width), transform=transform, fill=-1, dtype="int32")


def zone_nights(
    zones: np.ndarray, lit: np.ndarray, clear: np.ndarray, dark: np.ndarray
) -> dict[str, np.ndarray]:
    """Per zone and night: lit pixels, clear lit pixels and dark clear lit pixels.

    Returns arrays shaped (nights, zones) plus the lit pixel count per zone.
    """
    n_zones = int(zones.max()) + 1
    assert n_zones > 0, "no zone falls on the grid"
    in_zone = (zones >= 0) & lit
    ids = zones[in_zone]
    lit_count = np.bincount(ids, minlength=n_zones)
    clear_count = np.stack([np.bincount(ids, c[in_zone], n_zones) for c in clear])
    dark_count = np.stack(
        [np.bincount(ids, (c & d)[in_zone], n_zones) for c, d in zip(clear, dark, strict=True)]
    )
    return {"lit": lit_count, "clear": clear_count, "dark": dark_count}


TERRITORIES_URL = (
    "https://hifld.publicenvirodata.org/storage/hifld/electric-retail-service-territories/"
    "electric-retail-service-territories/v1.0.0/geoparquet/"
    "electric-retail-service-territories.parquet"
)
CENSUS = "https://www2.census.gov/geo/tiger/GENZ2024/shp/"


def dte_territory() -> tuple[gpd.GeoDataFrame, float, float]:
    """The piece of HIFLD Next's DTE Electric polygon that contains Detroit.

    Returns that piece and the areas (km²) of the whole HIFLD polygon and of the piece.
    """
    from shapely.geometry import Point

    path = download(TERRITORIES_URL, cache_dir() / "territories.parquet")
    territories = gpd.read_parquet(path)
    dte = territories[territories["NAME"] == "DTE ELECTRIC COMPANY"].to_crs(4326)
    assert len(dte) == 1, "expected one DTE polygon"
    parts = dte.explode(index_parts=False).reset_index(drop=True)
    piece = parts[parts.contains(Point(-83.05, 42.33))].reset_index(drop=True)
    assert len(piece) == 1, "no DTE piece contains Detroit"
    whole_km2 = float(dte.to_crs(5070).area.sum() / 1e6)
    piece_km2 = float(piece.to_crs(5070).area.sum() / 1e6)
    return piece, whole_km2, piece_km2


def zones_inside(
    territory: gpd.GeoDataFrame, county_share: float = 0.10, tract_share: float = 0.50
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Michigan counties and tracts with enough of their area in the territory, clipped to it."""
    county_zip = download(
        CENSUS + "cb_2024_us_county_500k.zip", cache_dir() / "cb_2024_us_county_500k.zip"
    )
    tract_zip = download(
        CENSUS + "cb_2024_26_tract_500k.zip", cache_dir() / "cb_2024_26_tract_500k.zip"
    )
    shape = territory.geometry.iloc[0]

    def clip(zones: gpd.GeoDataFrame, min_share: float) -> gpd.GeoDataFrame:
        zones = zones.to_crs(4326)
        full_area = zones.to_crs(5070).area
        zones["geometry"] = zones.intersection(shape)
        share = zones.to_crs(5070).area / full_area
        return zones[share >= min_share].reset_index(drop=True)

    counties = clip(gpd.read_file(county_zip).query("STATEFP == '26'"), county_share)
    tracts = clip(gpd.read_file(tract_zip), tract_share)
    return counties[["GEOID", "NAME", "geometry"]], tracts[["GEOID", "NAMELSADCO", "geometry"]]


def grid_for(zones: gpd.GeoDataFrame) -> Grid:
    """The smallest Black Marble grid box covering the zones."""
    step = 1 / PIXELS_PER_DEGREE
    west, south, east, north = zones.total_bounds
    return Grid(
        round(west // step * step, 6),
        round(south // step * step, 6),
        round(-(-east // step) * step, 6),
        round(-(-north // step) * step, 6),
    )
