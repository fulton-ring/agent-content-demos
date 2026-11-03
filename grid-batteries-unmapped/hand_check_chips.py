"""Draw the images behind hand_check.csv: each sampled plant on its newest NAIP photo and a recent Sentinel-2 scene.

Run after batteries.py, which writes output/hand_check_sample.csv. Each image is 1 km across, centred on EIA's
coordinates (the cross). Images go to screenshots/hand_check/. Usage: uv run hand_check_chips.py
"""

import io
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

HERE = Path(__file__).parent
OUT = Path(os.environ.get("BATTERIES_OUTPUT_DIR", HERE / "output"))
CHIPS = HERE / "screenshots" / "hand_check"
NAIP = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer"
PC = "https://planetarycomputer.microsoft.com/api"
HALF_WIDTH_M = 500
SENTINEL_WINDOW = "2026-04-01/2026-11-01"


def get(url: str, body: dict | None = None, attempts: int = 4) -> bytes:
    """GET (or POST JSON) with up to `attempts` tries and exponential backoff."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=120) as r:
                if r.status != 200:
                    raise RuntimeError(f"{url} returned HTTP {r.status}")
                return r.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def bbox(lat: float, lon: float) -> tuple[float, float, float, float]:
    dlat = HALF_WIDTH_M / 111_320
    dlon = HALF_WIDTH_M / (111_320 * math.cos(math.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def naip(box: tuple[float, float, float, float], lat: float, lon: float) -> tuple[str, np.ndarray]:
    """The newest NAIP photo over the point, with its acquisition date."""
    query = urllib.parse.urlencode(
        {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "where": "Category=1",
            "outFields": "Year,acquisition_date",
            "returnGeometry": "false",
            "f": "json",
        }
    )
    tiles = [f["attributes"] for f in json.loads(get(f"{NAIP}/query?{query}"))["features"]]
    assert tiles, f"no NAIP at {lat},{lon}"
    newest = max(tiles, key=lambda t: (t["Year"], t["acquisition_date"] or 0))
    rule = {"mosaicMethod": "esriMosaicAttribute", "sortField": "Year", "sortValue": "2100", "ascending": True}
    params = urllib.parse.urlencode(
        {
            "bbox": ",".join(map(str, box)),
            "bboxSR": 4326,
            "size": "500,500",
            "format": "png",
            "mosaicRule": json.dumps(rule),
            "f": "image",
        }
    )
    image = np.asarray(Image.open(io.BytesIO(get(f"{NAIP}/exportImage?{params}"))).convert("RGB"))
    date = pd.to_datetime(newest["acquisition_date"], unit="ms").strftime("%Y-%m-%d") if newest["acquisition_date"] else ""
    return f"NAIP {newest['Year']} {date}".strip(), image


def sentinel(box: tuple[float, float, float, float], lat: float, lon: float) -> tuple[str, np.ndarray]:
    """The most recent 2026 Sentinel-2 scene over the point with under 5% cloud (20%, then 50%, if there is none)."""
    items = []
    for cloud in (5, 20, 50):
        body = {
            "collections": ["sentinel-2-l2a"],
            "intersects": {"type": "Point", "coordinates": [lon, lat]},
            "datetime": SENTINEL_WINDOW,
            "query": {"eo:cloud_cover": {"lt": cloud}},
            "sortby": [{"field": "datetime", "direction": "desc"}],
            "limit": 1,
        }
        items = json.loads(get(f"{PC}/stac/v1/search", body))["features"]
        if items:
            break
    assert items, f"no Sentinel-2 scene at {lat},{lon}"
    item = items[0]
    params = urllib.parse.urlencode(
        {"collection": "sentinel-2-l2a", "item": item["id"], "assets": "visual", "asset_bidx": "visual|1,2,3"}
    )
    corners = ",".join(f"{v:.6f}" for v in box)
    png = get(f"{PC}/data/v1/item/bbox/{corners}/500x500.png?{params}")
    return f"Sentinel-2 {item['properties']['datetime'][:10]}", np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))


def main() -> None:
    sample = pd.read_csv(OUT / "hand_check_sample.csv")
    CHIPS.mkdir(parents=True, exist_ok=True)
    dates_path = OUT / "hand_check_imagery_dates.csv"
    done = pd.read_csv(dates_path).set_index("eia_plant_id", drop=False).to_dict("index") if dates_path.exists() else {}
    dates = []
    for row in sample.to_dict("records"):
        if (CHIPS / f"{row['eia_plant_id']}.jpg").exists() and row["eia_plant_id"] in done:
            dates.append(done[row["eia_plant_id"]])
            continue
        box = bbox(row["latitude"], row["longitude"])
        panels = [naip(box, row["latitude"], row["longitude"]), sentinel(box, row["latitude"], row["longitude"])]
        dates.append({"eia_plant_id": row["eia_plant_id"], "naip": panels[0][0], "sentinel2": panels[1][0]})
        fig, axes = plt.subplots(1, 2, figsize=(10, 5.4))
        for ax, (label, image) in zip(axes, panels, strict=True):
            ax.imshow(image)
            ax.plot([250], [250], marker="+", color="red", markersize=18, mew=1.5)
            ax.set_title(label, fontsize=10)
            ax.set_axis_off()
        fig.suptitle(
            f"{row['eia_plant_id']} {row['plant_name']} ({row['state']}), {row['mw']:.0f} MW, "
            f"online {row['year_online']}. 1 km across.",
            fontsize=10,
        )
        fig.text(0.5, 0.01, "NAIP: USDA FSA. Contains modified Copernicus Sentinel data 2026.", ha="center", fontsize=7)
        fig.tight_layout()
        fig.savefig(CHIPS / f"{row['eia_plant_id']}.jpg", dpi=80)
        plt.close(fig)
        pd.DataFrame(dates).to_csv(dates_path, index=False)
        print(row["eia_plant_id"], dates[-1]["naip"], dates[-1]["sentinel2"], flush=True)


if __name__ == "__main__":
    main()
