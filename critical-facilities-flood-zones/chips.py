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


def export(url: str, params: dict, attempts: int = 5) -> Image.Image:
    """Fetch one exported map image, with a bounded number of retries."""
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, timeout=120)
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("image/"):
                return Image.open(io.BytesIO(response.content)).convert("RGBA")
        except requests.RequestException as error:
            print(f"{url} attempt {attempt + 1}: {error}")
        time.sleep(2**attempt)
    raise RuntimeError(f"{url} failed {attempts} times")


def chip(lon: float, lat: float) -> Image.Image:
    """Imagery with the NFHL flood zones (layer 28) at 45% opacity and a ring on the point."""
    dlat = HALF_SIDE_M / 111_320
    dlon = dlat / math.cos(math.radians(lat))
    common = {
        "bbox": f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}",
        "bboxSR": "4326",
        "imageSR": "4326",
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
    for row in sample.itertuples():
        path = out / f"{row.facility_id}.jpg"
        if not path.exists():
            chip(float(row.lon), float(row.lat)).save(path, quality=85)
    print(f"{len(sample)} chips in {out} (600 m across, point at the centre)")


if __name__ == "__main__":
    main()
