"""Draw the images we labelled hand_check.csv from: each sampled HIFLD record on Esri World Imagery, at two zooms.

Run after crosswalk.py (it writes output/hand_check_sample.csv and data/candidates.parquet). The images go to
data/chips/ and are not committed, because the imagery is Esri's. Usage: uv run hand_check_chips.py
"""

import io
import math
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

HERE = Path(__file__).parent
DATA = Path(os.environ.get("CROSSWALK_DATA_DIR", HERE / "data"))
OUT = Path(os.environ.get("CROSSWALK_OUTPUT_DIR", HERE / "output"))
TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
HALF_WORLD = 20037508.342789244


def tile_xy(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int((lon + 180) / 360 * n), int(y)


def fetch_tile(url: str, attempts: int = 6) -> bytes:
    """Fetch one tile, retrying a dropped connection up to `attempts` times with backoff."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (hifld-overture-crosswalk spike)"})
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


def mosaic(lon: float, lat: float, zoom: int, radius: int) -> tuple[np.ndarray, list[float]]:
    """Fetch a (2*radius+1)^2 block of tiles around the point; return the image and its Web Mercator extent."""
    cx, cy = tile_xy(lon, lat, zoom)
    size = 2 * radius + 1
    image = Image.new("RGB", (256 * size, 256 * size))
    offsets = [(dx, dy) for dx in range(-radius, radius + 1) for dy in range(-radius, radius + 1)]
    urls = [TILES.format(z=zoom, x=cx + dx, y=cy + dy) for dx, dy in offsets]
    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        for (dx, dy), data in zip(offsets, pool.map(fetch_tile, urls), strict=True):
            tile = Image.open(io.BytesIO(data)).convert("RGB")
            image.paste(tile, ((dx + radius) * 256, (dy + radius) * 256))
    span = 2 * HALF_WORLD / 2**zoom
    left = -HALF_WORLD + (cx - radius) * span
    top = HALF_WORLD - (cy - radius) * span
    return np.asarray(image), [left, left + size * span, top - size * span, top]


def main() -> None:
    sample = pd.read_csv(OUT / "hand_check_sample.csv", dtype={"hifld_id": str})
    candidates = gpd.read_parquet(DATA / "candidates.parquet").to_crs(3857)
    chips = DATA / "chips"
    chips.mkdir(exist_ok=True)
    for row in sample.to_dict("records"):
        path = chips / f"{row['layer'].split()[0].lower()}-{row['hifld_id']}.jpg"
        if path.exists():
            continue
        point = gpd.GeoSeries(gpd.points_from_xy([row["lon"]], [row["lat"]]), crs=4326).to_crs(3857).iloc[0]
        same_kind = candidates[candidates["layer"] == row["layer"]]
        fig, axes = plt.subplots(1, 2, figsize=(16, 8))
        for ax, (zoom, radius) in zip(axes, [(15, 1), (18, 1)], strict=True):
            image, extent = mosaic(row["lon"], row["lat"], zoom, radius)
            ax.imshow(image, extent=extent)
            near = same_kind.cx[extent[0] : extent[1], extent[2] : extent[3]]
            for side, colour in [("Overture", "cyan"), ("OSM", "yellow")]:
                shapes = near[near["side"] == side]
                if len(shapes):
                    shapes.plot(ax=ax, facecolor="none", edgecolor=colour, color=colour, markersize=80, marker="^")
            ax.scatter([point.x], [point.y], s=300, facecolors="none", edgecolors="red", linewidths=2.5)
            ax.set_xlim(extent[0], extent[1])
            ax.set_ylim(extent[2], extent[3])
            ax.set_axis_off()
        fig.suptitle(
            f"{row['layer']} {row['hifld_id']}: {row['name']}, {row['address']}, {row['city']} {row['state']} "
            f"(status {row['status']}, source date {row['source_date']})\n"
            f"nearest same-kind Overture {row['overture_nearest_m']:.0f} m, OSM {row['osm_nearest_m']:.0f} m "
            f"(red circle = HIFLD, cyan = Overture, yellow = OSM)"
        )
        fig.tight_layout()
        fig.savefig(path, dpi=60)
        plt.close(fig)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
