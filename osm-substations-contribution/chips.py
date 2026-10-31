"""Draw the Esri World Imagery chips we label imagery_labels.csv from, and look up each chip's imagery date.

Adapted from us-substations-verified/hand_check_chips.py. Run after contribution.py, which writes
data/points_to_label.csv. Each chip has two panels: a ~3 km overview (zoom 15) and a ~1.2 km detail (zoom 17)
with a grid in metres east and north of the point, so a labeller can give a rough outline of the yard.
HIFLD lines are yellow, current OSM substations magenta crosses, OSM plants cyan crosses, the point a red ring.
Images go to data/chips/ and are not committed, because the imagery is Esri's. The imagery date for each point
comes from Esri's World Imagery metadata (the identify endpoint) and goes to data/imagery_dates.csv.
Usage: uv run chips.py
"""

import io
import json
import math
import os
import time
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from PIL import Image

DATA = Path(os.environ.get("DATA_DIR", "data"))
SERVICE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer"
HALF_WORLD = 20037508.342789244
HEADERS = {"User-Agent": "fulton-ring osm-substations-contribution spike"}


def get(url: str, params: dict[str, str] | None = None, attempts: int = 4) -> requests.Response:
    """GET with a bounded number of retries and exponential backoff."""
    for attempt in range(attempts):
        response = requests.get(url, params=params, headers=HEADERS, timeout=60)
        if response.status_code == 200:
            return response
        time.sleep(2**attempt)
    response.raise_for_status()
    raise RuntimeError(f"{url} returned HTTP {response.status_code}")


def tile_xy(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int((lon + 180) / 360 * n), int(y)


def mosaic(lon: float, lat: float, zoom: int, radius: int) -> tuple[np.ndarray, list[float]]:
    """A (2*radius+1)^2 block of tiles around the point, and its Web Mercator extent."""
    cx, cy = tile_xy(lon, lat, zoom)
    size = 2 * radius + 1
    image = Image.new("RGB", (256 * size, 256 * size))
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            tile = get(f"{SERVICE}/tile/{zoom}/{cy + dy}/{cx + dx}").content
            image.paste(Image.open(io.BytesIO(tile)).convert("RGB"), ((dx + radius) * 256, (dy + radius) * 256))
    span = 2 * HALF_WORLD / 2**zoom
    left = -HALF_WORLD + (cx - radius) * span
    top = HALF_WORLD - (cy - radius) * span
    return np.asarray(image), [left, left + size * span, top - size * span, top]


def imagery_date(lon: float, lat: float) -> dict[str, str]:
    """Source, date and resolution of the World Imagery tile at zoom 17 over the point."""
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "sr": "4326",
        "layers": "all:0",
        "tolerance": "1",
        "mapExtent": f"{lon - 0.005},{lat - 0.005},{lon + 0.005},{lat + 0.005}",
        "imageDisplay": "1280,1280,96",
        "returnGeometry": "false",
        "f": "json",
    }
    results = get(f"{SERVICE}/identify", params).json().get("results", [])
    if not results:
        return {"imagery_date": "", "imagery_source": "", "imagery_resolution_m": ""}
    attrs = results[0]["attributes"]
    raw = str(attrs.get("DATE (YYYYMMDD)", ""))
    date = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if raw[:8].isdigit() else ""
    return {
        "imagery_date": date,
        "imagery_source": f"Esri World Imagery: {attrs.get('SOURCE', '')} {attrs.get('DESCRIPTION', '')}".strip(),
        "imagery_resolution_m": str(attrs.get("RESOLUTION (M)", "")),
    }


def osm_features() -> gpd.GeoDataFrame:
    elements = [e for f in sorted((DATA / "overpass").glob("*.json")) for e in json.loads(f.read_text())["elements"]]
    rows = [(e.get("tags", {}).get("power"), e.get("center", e)) for e in elements]
    return gpd.GeoDataFrame(
        {"power": [p for p, _ in rows]},
        geometry=gpd.points_from_xy([c["lon"] for _, c in rows], [c["lat"] for _, c in rows]),
        crs=4326,
    ).to_crs(3857)


def draw(row: dict[str, str | float], lines: gpd.GeoDataFrame, osm: gpd.GeoDataFrame, path: Path) -> None:
    lon, lat = float(row["lon"]), float(row["lat"])
    point = gpd.GeoSeries.from_xy([lon], [lat], crs=4326).to_crs(3857).iloc[0]
    ground = math.cos(math.radians(lat))  # Web Mercator metres to ground metres
    fig, axes = plt.subplots(1, 2, figsize=(18, 9))
    for ax, (zoom, radius) in zip(axes, [(15, 1), (17, 2)], strict=True):
        image, ext = mosaic(lon, lat, zoom, radius)
        # Axes in ground metres east and north of the point.
        to_m = [
            (ext[0] - point.x) * ground,
            (ext[1] - point.x) * ground,
            (ext[2] - point.y) * ground,
            (ext[3] - point.y) * ground,
        ]
        ax.imshow(image, extent=to_m)
        window = point.buffer(ext[1] - ext[0])
        for geom in lines[lines.intersects(window)].geometry:
            parts = getattr(geom, "geoms", [geom])
            for part in parts:
                xs, ys = part.xy
                ax.plot((np.array(xs) - point.x) * ground, (np.array(ys) - point.y) * ground, color="yellow", lw=1)
        near = osm[osm.intersects(window)]
        for kind, colour in [("substation", "magenta"), ("plant", "cyan")]:
            pts = near[near["power"] == kind]
            ax.scatter(
                (pts.geometry.x - point.x) * ground,
                (pts.geometry.y - point.y) * ground,
                marker="x",
                s=200,
                c=colour,
                lw=3,
            )
        ax.scatter([0], [0], s=400, facecolors="none", edgecolors="red", linewidths=2)
        if zoom == 17:
            ax.set_xticks(np.arange(-600, 601, 100))
            ax.set_yticks(np.arange(-600, 601, 100))
            ax.grid(color="white", alpha=0.35, lw=0.6)
            ax.tick_params(labelsize=7)
        else:
            ax.set_axis_off()
        ax.set_xlim(to_m[0], to_m[1])
        ax.set_ylim(to_m[2], to_m[3])
    fig.suptitle(f"{row['id']}  {row['name']}  HIFLD {row['hifld_kv']:.0f} kV  {row['state']}", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=80)
    plt.close(fig)


def main() -> None:
    points = pd.read_csv(DATA / "points_to_label.csv")
    lines = gpd.read_parquet(DATA / "hifld-next-transmission-lines-v1.0.0.parquet").to_crs(3857)
    osm = osm_features()
    chips = DATA / "chips"
    chips.mkdir(exist_ok=True)
    dates_path = DATA / "imagery_dates.csv"
    dates = pd.read_csv(dates_path, dtype=str) if dates_path.exists() else pd.DataFrame(columns=["id"])
    new_dates = []
    for row in points.to_dict("records"):
        path = chips / f"{row['id']}.jpg"
        if not path.exists():
            draw(row, lines, osm, path)
            print(f"wrote {path}")
        if row["id"] not in set(dates["id"]):
            new_dates.append({"id": row["id"], **imagery_date(float(row["lon"]), float(row["lat"]))})
    if new_dates:
        pd.concat([dates, pd.DataFrame(new_dates)]).to_csv(dates_path, index=False)
    print(f"{len(points)} chips in {chips}; imagery dates in {dates_path}")


if __name__ == "__main__":
    main()
