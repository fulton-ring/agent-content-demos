"""Draw the images behind hand_check.csv: each far campus on Esri World Imagery, wide and close.

Adapted from us-substations-verified/hand_check_chips.py. Run after distance.py, which writes the far campuses'
coordinates to data/far_campuses_private.csv. Left: about 20 km across, with 230 kV+ lines (yellow: OpenStreetMap,
cyan dashes: HIFLD 2023) and substations from us-substations-verified (red: 230 kV+, orange: 100-229 kV). Right:
about 4 km across the campus point (red ring), to look for a switchyard or substation under construction.
The images go to data/chips/ and are not committed, because the imagery is Esri's and they join campus and grid
coordinates. Usage: uv run hand_check_chips.py
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
TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
HALF_WORLD = 20037508.342789244


def tile_xy(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int((lon + 180) / 360 * n), int(y)


def fetch_tile(url: str, attempts: int = 4) -> bytes:
    """Fetch one tile, retrying a dropped connection up to `attempts` times with backoff."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (datacenter-substation-distance spike)"})
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
    far = pd.read_csv(DATA / "far_campuses_private.csv")
    raw = pd.read_parquet(DATA / "gmwid_us_power_line_230kv.parquet")
    osm = gpd.GeoSeries.from_wkb(raw["wkb"].map(bytes), crs=4326).to_crs(3857)
    hifld = gpd.read_parquet(DATA / "hifld_transmission_lines.parquet", columns=["VOLTAGE", "geometry"])
    hifld = hifld[hifld["VOLTAGE"] >= 230].to_crs(3857)
    subs = pd.read_csv(Path(__file__).parent.parent / "us-substations-verified/dataset/us_substations.csv")
    subs = subs[subs["max_kv"] >= 100]
    sub_points = gpd.GeoSeries.from_xy(subs["lon"], subs["lat"], crs=4326).to_crs(3857)
    chips = DATA / "chips"
    chips.mkdir(exist_ok=True)
    for number, row in enumerate(far.to_dict("records")):
        path = chips / f"{number:02d}.jpg"
        if path.exists():
            continue
        point = gpd.GeoSeries.from_xy([row["lon"]], [row["lat"]], crs=4326).to_crs(3857).iloc[0]
        fig, axes = plt.subplots(1, 2, figsize=(16, 8))
        for ax, (zoom, radius) in zip(axes, [(13, 2), (16, 2)], strict=True):
            image, extent = mosaic(row["lon"], row["lat"], zoom, radius)
            ax.imshow(image, extent=extent)
            window = point.buffer(extent[1] - extent[0])
            osm[osm.intersects(window)].plot(ax=ax, color="yellow", linewidth=1.5)
            hifld[hifld.intersects(window)].plot(ax=ax, color="cyan", linewidth=1, linestyle="--")
            near = sub_points[sub_points.intersects(window)]
            near_kv = subs.loc[near.index, "max_kv"]
            for chosen, colour in [(near[near_kv < 230], "orange"), (near[near_kv >= 230], "red")]:
                if not chosen.empty:
                    chosen.plot(ax=ax, marker="s", markersize=60, facecolor="none", edgecolor=colour, linewidth=2)
            ax.scatter([point.x], [point.y], s=400, facecolors="none", edgecolors="red", linewidths=2)
            ax.set_xlim(extent[0], extent[1])
            ax.set_ylim(extent[2], extent[3])
            ax.set_axis_off()
        fig.suptitle(f"{number:02d} {row['campus']}: {row['sub230_mi']:.1f} mi to nearest 230 kV+ substation")
        fig.tight_layout()
        fig.savefig(path, dpi=60)
        plt.close(fig)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
