"""Draw the images we labelled hand_check.csv from: each sampled line end on Esri World Imagery, at two zooms.

Run after grid_gaps.py (it writes output/hand_check_sample.csv). The images go to data/chips/ and are not
committed, because the imagery is Esri's. Usage: uv run hand_check_chips.py
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
DATA = Path(os.environ.get("GRID_GAPS_DATA_DIR", HERE / "data"))
OUT = Path(os.environ.get("GRID_GAPS_OUTPUT_DIR", HERE / "output"))
TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
HALF_WORLD = 20037508.342789244


def tile_xy(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int((lon + 180) / 360 * n), int(y)


def fetch_tile(url: str, attempts: int = 4) -> bytes:
    """Fetch one tile, retrying a dropped connection up to `attempts` times with backoff."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (hifld-grid-gaps spike)"})
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
    lines = gpd.read_parquet(DATA / "transmission-lines.parquet").to_crs(3857)
    plants = gpd.read_parquet(DATA / "power-plants.parquet").to_crs(3857)
    overture = next(DATA.glob("overture-substations-*.parquet"))
    raw = pd.read_parquet(overture)
    subs = gpd.GeoDataFrame(raw[["id"]], geometry=gpd.GeoSeries.from_wkb(raw["wkb"]), crs=4326).to_crs(3857)
    chips = DATA / "chips"
    chips.mkdir(exist_ok=True)
    for row in sample.to_dict("records"):
        if (chips / f"{row['end_index']}.jpg").exists():
            continue
        point = gpd.GeoSeries(gpd.points_from_xy([row["lon"]], [row["lat"]]), crs=4326).to_crs(3857).iloc[0]
        fig, axes = plt.subplots(1, 2, figsize=(16, 8))
        for ax, (zoom, radius) in zip(axes, [(14, 2), (17, 1)], strict=True):
            image, extent = mosaic(row["lon"], row["lat"], zoom, radius)
            ax.imshow(image, extent=extent)
            window = gpd.GeoSeries([point.buffer(extent[1] - extent[0])], crs=3857)
            near_lines = lines[lines.intersects(window.iloc[0])]
            near_lines.plot(ax=ax, color="yellow", linewidth=1.2)
            near_lines[near_lines["source_ID"].astype(str) == str(row["line_id"])].plot(
                ax=ax, color="cyan", linewidth=2
            )
            subs[subs.intersects(window.iloc[0])].plot(ax=ax, facecolor="none", edgecolor="magenta", linewidth=2)
            plants[plants.intersects(window.iloc[0])].plot(ax=ax, color="lime", markersize=60, marker="s")
            ax.scatter(
                [point.x],
                [point.y],
                s=200,
                facecolors="none",
                edgecolors="red",
                linewidths=2,
            )
            ax.set_xlim(extent[0], extent[1])
            ax.set_ylim(extent[2], extent[3])
            ax.set_axis_off()
        fig.suptitle(
            f"end {row['end_index']}: line {row['line_id']} end {row['end']}, {row['voltage']} kV, "
            f"attr {row['sub_attr']}, "
            f"{row['m_to_substation']:.0f} m to substation, {row['m_to_plant']:.0f} m to plant, "
            f"touches other line: {row['touches_other_line']}"
        )
        fig.tight_layout()
        fig.savefig(chips / f"{row['end_index']}.jpg", dpi=60)
        plt.close(fig)
        print(f"wrote {chips}/{row['end_index']}.jpg")


if __name__ == "__main__":
    main()
