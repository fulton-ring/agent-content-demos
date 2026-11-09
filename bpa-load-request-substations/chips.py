"""Draw the aerial-imagery chips we hand-checked each requested substation on.

Each chip is Esri World Imagery around the substation's location in hand_check.csv, with every point from
the two sources drawn on top: HIFLD Next derived substations (red x) and us-substations-verified rows that
come from OpenStreetMap only (cyan +). Chips are grouped six to a sheet in data/chips/ and are not committed,
because the imagery is Esri's. Run after substations.py has downloaded the inputs: uv run chips.py
"""

import io
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

HERE = Path(__file__).parent
DATA = Path(os.environ.get("DATA_DIR", HERE / "data"))
HAND_CHECK = Path(os.environ.get("HAND_CHECK", HERE / "hand_check.csv"))
TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
HALF_WORLD = 20037508.342789244
ZOOM = 16
RADIUS = 1  # tiles either side of the centre tile: 3 x 3 tiles, about 1.2 km across at 46 degrees north


def tile_xy(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int((lon + 180) / 360 * n), int(y)


def fetch_tile(url: str, attempts: int = 4) -> bytes:
    """Fetch one tile, retrying a dropped connection up to `attempts` times with backoff."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (bpa-load-request-substations spike)"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise RuntimeError(f"{url} returned HTTP {response.status}")
                return response.read()
        except urllib.error.URLError:
            if attempt == attempts - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def mosaic(lon: float, lat: float) -> tuple[np.ndarray, list[float]]:
    """Fetch the block of tiles around the point; return the image and its Web Mercator extent."""
    cx, cy = tile_xy(lon, lat, ZOOM)
    size = 2 * RADIUS + 1
    image = Image.new("RGB", (256 * size, 256 * size))
    for dx in range(-RADIUS, RADIUS + 1):
        for dy in range(-RADIUS, RADIUS + 1):
            tile = Image.open(io.BytesIO(fetch_tile(TILES.format(z=ZOOM, x=cx + dx, y=cy + dy)))).convert("RGB")
            image.paste(tile, ((dx + RADIUS) * 256, (dy + RADIUS) * 256))
    span = 2 * HALF_WORLD / 2**ZOOM
    left = -HALF_WORLD + (cx - RADIUS) * span
    top = HALF_WORLD - (cy - RADIUS) * span
    return np.asarray(image), [left, left + size * span, top - size * span, top]


def draw_points(ax: plt.Axes, points: gpd.GeoDataFrame, extent: list[float], marker: str, color: str) -> None:
    left, right, bottom, top = extent
    inside = points.cx[left:right, bottom:top]
    ax.scatter(inside.geometry.x, inside.geometry.y, marker=marker, s=90, c=color, linewidths=2)
    for row in inside.itertuples():
        ax.annotate(str(row.name)[:22], (row.geometry.x, row.geometry.y), color=color, fontsize=7,
                    xytext=(4, 4), textcoords="offset points")


def main() -> None:
    checks = pd.read_csv(HAND_CHECK).dropna(subset=["lat", "lon"]).drop_duplicates("key")
    hifld = pd.read_csv(DATA / "us_substations_hifld_only.csv")
    hifld = gpd.GeoDataFrame(hifld, geometry=gpd.points_from_xy(hifld.lon, hifld.lat), crs=4326).to_crs(3857)
    verified = gpd.read_parquet(DATA / "us_substations.parquet")
    osm_only = verified[verified["source"] == "osm"].to_crs(3857)
    chips = DATA / "chips"
    chips.mkdir(parents=True, exist_ok=True)
    rows = checks.to_dict("records")
    for sheet in range(0, len(rows), 6):
        path = chips / f"sheet_{sheet // 6:02d}.jpg"
        if path.exists():
            continue
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        for ax, row in zip(axes.flat, rows[sheet : sheet + 6], strict=False):
            image, extent = mosaic(row["lon"], row["lat"])
            ax.imshow(image, extent=extent)
            draw_points(ax, hifld, extent, "x", "red")
            draw_points(ax, osm_only, extent, "+", "cyan")
            centre = gpd.GeoSeries(gpd.points_from_xy([row["lon"]], [row["lat"]]), crs=4326).to_crs(3857).iloc[0]
            ax.scatter([centre.x], [centre.y], marker="o", s=200, facecolors="none", edgecolors="yellow")
            ax.set_title(row["key"], fontsize=11)
            ax.set_axis_off()
        for ax in axes.flat[len(rows[sheet : sheet + 6]) :]:
            ax.set_axis_off()
        fig.tight_layout()
        fig.savefig(path, dpi=60)
        plt.close(fig)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
