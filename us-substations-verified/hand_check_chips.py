"""Draw the images we labelled hand_check.csv from: each sampled derived substation on Esri World Imagery, at two zooms.

Adapted from hifld-grid-gaps/hand_check_chips.py. Run after verify.py (it writes outputs/hand_check_sample.csv).
HIFLD lines are yellow, OSM substations magenta, the sampled point a red ring. The images go to data/chips/ and
are not committed, because the imagery is Esri's. Usage: uv run hand_check_chips.py
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

DATA = Path(os.environ.get("DATA_DIR", "data"))
OUT = Path(os.environ.get("OUTPUT_DIR", "outputs"))
TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
HALF_WORLD = 20037508.342789244


def tile_xy(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int((lon + 180) / 360 * n), int(y)


def fetch_tile(url: str, attempts: int = 4) -> bytes:
    """Fetch one tile, retrying a dropped connection up to `attempts` times with backoff."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (us-substations-verified spike)"})
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
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            tile = Image.open(io.BytesIO(fetch_tile(TILES.format(z=zoom, x=cx + dx, y=cy + dy)))).convert("RGB")
            image.paste(tile, ((dx + radius) * 256, (dy + radius) * 256))
    span = 2 * HALF_WORLD / 2**zoom
    left = -HALF_WORLD + (cx - radius) * span
    top = HALF_WORLD - (cy - radius) * span
    return np.asarray(image), [left, left + size * span, top - size * span, top]


def main() -> None:
    sample = pd.read_csv(OUT / "hand_check_sample.csv")
    lines = gpd.read_parquet(DATA / "hifld-next-transmission-lines-v1.0.0.parquet").to_crs(3857)
    overture = next(DATA.glob("overture-substations-us-*.parquet"))
    raw = pd.read_parquet(overture)
    subs = gpd.GeoSeries.from_wkb(raw["wkb"], crs=4326).to_crs(3857)
    chips = DATA / "chips"
    chips.mkdir(exist_ok=True)
    for row in sample.to_dict("records"):
        if (chips / f"{row['id']}.jpg").exists():
            continue
        point = gpd.GeoSeries.from_xy([row["lon"]], [row["lat"]], crs=4326).to_crs(3857).iloc[0]
        fig, axes = plt.subplots(1, 2, figsize=(16, 8))
        for ax, (zoom, radius) in zip(axes, [(15, 2), (18, 1)], strict=True):
            image, extent = mosaic(row["lon"], row["lat"], zoom, radius)
            ax.imshow(image, extent=extent)
            window = point.buffer(extent[1] - extent[0])
            lines[lines.intersects(window)].plot(ax=ax, color="yellow", linewidth=1.2)
            near_subs = subs[subs.intersects(window)]
            if not near_subs.empty:
                near_subs.plot(ax=ax, facecolor="none", edgecolor="magenta", linewidth=2)
            ax.scatter([point.x], [point.y], s=300, facecolors="none", edgecolors="red", linewidths=2)
            ax.set_xlim(extent[0], extent[1])
            ax.set_ylim(extent[2], extent[3])
            ax.set_axis_off()
        fig.suptitle(
            f"{row['id']}: {row['name']}, {row['kv']:.0f} kV, {row['lines']} lines, "
            f"{row['m_to_osm']:.0f} m to nearest OSM substation"
        )
        fig.tight_layout()
        fig.savefig(chips / f"{row['id']}.jpg", dpi=60)
        plt.close(fig)
        print(f"wrote {chips}/{row['id']}.jpg")


if __name__ == "__main__":
    main()
