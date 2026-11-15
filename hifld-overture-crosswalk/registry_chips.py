"""Draw dated NAIP before/after chips for the registry hand-check sample (output/registry_hand_check_sample.csv).

Each chip is 300 m across, centred on the record, from the Planetary Computer's NAIP collection: the latest image
on the left and the earliest image from 2014 on, on the right, each stamped with its capture date. Chips go to
data/registry_chips/ (not committed); the imagery dates go to output/registry_chip_dates.csv.
"""

import io
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from PIL import Image, ImageDraw

from shared import DATA, OUT, USER_AGENT

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
CROP = "https://planetarycomputer.microsoft.com/api/data/v1/item/bbox/{box}/512x512.png"
HALF_WIDTH_M = 150
CHIPS = DATA / "registry_chips"


def get(url: str, body: dict | None = None) -> bytes:
    data = json.dumps(body).encode() if body else None
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=120) as r:
                if r.status != 200:
                    raise RuntimeError(f"{url} returned HTTP {r.status}")
                return r.read()
        except (TimeoutError, ConnectionError, urllib.error.URLError):
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def naip_items(lon: float, lat: float) -> list[dict]:
    """NAIP items covering the point, newest first."""
    body = {
        "collections": ["naip"],
        "intersects": {"type": "Point", "coordinates": [lon, lat]},
        "sortby": [{"field": "datetime", "direction": "desc"}],
        "limit": 20,
    }
    return json.loads(get(STAC, body))["features"]


def chip(item: dict, lon: float, lat: float) -> Image.Image:
    dlat = HALF_WIDTH_M / 110_540
    dlon = HALF_WIDTH_M / (111_320 * math.cos(math.radians(lat)))
    box = f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}"
    query = urllib.parse.urlencode(
        {"collection": "naip", "item": item["id"], "assets": "image", "asset_bidx": "image|1,2,3"}
    )
    image = Image.open(io.BytesIO(get(f"{CROP.format(box=box)}?{query}"))).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.line([(246, 256), (266, 256)], fill="red", width=2)
    draw.line([(256, 246), (256, 266)], fill="red", width=2)
    draw.rectangle([0, 0, 200, 18], fill="black")
    draw.text((4, 3), f"NAIP {item['properties']['datetime'][:10]}", fill="white")
    return image


def draw(row: pd.Series) -> dict:
    items = naip_items(row["lon"], row["lat"])
    if not items:
        return {"chip": "", "naip_latest": "", "naip_earliest": ""}
    latest = items[0]
    older = [i for i in items if "2014" <= i["properties"]["datetime"][:4] < latest["properties"]["datetime"][:4]]
    earliest = older[-1] if older else latest
    pair = Image.new("RGB", (1024, 512))
    pair.paste(chip(latest, row["lon"], row["lat"]), (0, 0))
    pair.paste(chip(earliest, row["lon"], row["lat"]), (512, 0))
    path = CHIPS / f"{row['n']:03d}_{row['slug']}_{row['list']}.png"
    pair.save(path)
    return {
        "chip": str(path.relative_to(DATA)),
        "naip_latest": latest["properties"]["datetime"][:10],
        "naip_earliest": earliest["properties"]["datetime"][:10],
    }


def main() -> None:
    sample = pd.read_csv(OUT / "registry_hand_check_sample.csv", dtype={"hifld_id": str, "registry_id": str})
    assert len(sample) > 0, "run registries.py first"
    sample = sample[sample["lon"].notna()].reset_index(drop=True)
    sample["n"] = sample.index
    sample["slug"] = sample["layer"].str.lower().str.replace(r"[^a-z]+", "-", regex=True)
    CHIPS.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        drawn = list(pool.map(draw, [row for _, row in sample.iterrows()]))
    dates = pd.concat([sample, pd.DataFrame(drawn)], axis=1)
    dates.drop(columns=["slug"]).to_csv(OUT / "registry_chip_dates.csv", index=False)
    print(f"{(dates['chip'] != '').sum()} of {len(dates)} chips drawn into {CHIPS}")
    print(dates.groupby("layer")["naip_latest"].agg(["min", "max"]))


if __name__ == "__main__":
    main()
