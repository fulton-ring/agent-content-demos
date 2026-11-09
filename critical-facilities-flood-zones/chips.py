"""Draw the images behind hand_check.csv: each sampled facility on Esri World Imagery, with FEMA's
NFHL flood zones drawn over it and the facility point as a red ring.

Run after notebook.py (it writes results/spot_check_sample.csv). Images go to the cache folder,
not the repo, because the imagery is Esri's. Usage: uv run chips.py
"""

import io
import math
import os
import time
from pathlib import Path

import pandas as pd
import requests
from PIL import Image, ImageDraw

IMAGERY = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/export"
HALF_SIDE_M = 300
SIZE = 800
EARTH_R = 6_378_137


def export(url: str, params: dict, attempts: int = 5) -> Image.Image:
    """Fetch one exported map image, with a bounded number of retries."""
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, timeout=120)
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("image/"):
                return Image.open(io.BytesIO(response.content)).convert("RGBA")
            print(f"{url} attempt {attempt + 1}: {response.headers.get('content-type')}")
        except requests.RequestException as error:
            print(f"{url} attempt {attempt + 1}: {error}")
        time.sleep(2**attempt)
    raise RuntimeError(f"{url} failed {attempts} times")


def chip(lon: float, lat: float) -> Image.Image:
    """Imagery with the NFHL flood zones (layer 28) at 45% opacity and a ring on the point."""
    # Web Mercator, so pixels are square and the point is the centre of both images.
    x = math.radians(lon) * EARTH_R
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * EARTH_R
    half = HALF_SIDE_M / math.cos(math.radians(lat))  # Mercator metres per ground metre
    common = {
        "bbox": f"{x - half},{y - half},{x + half},{y + half}",
        "bboxSR": "3857",
        "imageSR": "3857",
        "size": f"{SIZE},{SIZE}",
        "f": "image",
    }
    base = export(IMAGERY, {**common, "format": "jpg"})
    zones = export(NFHL, {**common, "format": "png32", "transparent": "true", "layers": "show:28"})
    zones.putalpha(zones.getchannel("A").point(lambda a: int(a * 0.45)))
    image = Image.alpha_composite(base, zones)
    draw = ImageDraw.Draw(image)
    c, r = SIZE // 2, 14
    draw.ellipse([c - r, c - r, c + r, c + r], outline=(255, 0, 0, 255), width=4)
    return image.convert("RGB")


def main() -> None:
    here = Path(__file__).parent
    results = Path(os.environ.get("CFF_RESULTS", here / "results"))
    cache = Path(
        os.environ.get("CFF_CACHE", Path.home() / ".cache" / "critical-facilities-flood-zones")
    )
    out = cache / "chips"
    out.mkdir(parents=True, exist_ok=True)
    sample = pd.read_csv(results / "spot_check_sample.csv")
    assert {"facility_id", "lon", "lat"} <= set(sample.columns)
    for facility_id, lon, lat in zip(
        sample.facility_id.astype(str), sample.lon.tolist(), sample.lat.tolist(), strict=True
    ):
        path = out / f"{facility_id}.jpg"
        if not path.exists():
            chip(lon, lat).save(path, quality=85)
    print(f"{len(sample)} chips in {out} (600 m across, point at the centre)")


if __name__ == "__main__":
    main()
