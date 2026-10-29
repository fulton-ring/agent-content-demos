"""What the four notebooks share: settings, downloads, address handling, candidate pairs and scoring.

Everything that runs once lives in the notebooks, next to its output. This module holds only what two or more of
them need.
"""

import http.client
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA = Path(os.environ.get("CAMPUS_DATA_DIR", HERE / "data"))
OUT = Path(os.environ.get("CAMPUS_OUTPUT_DIR", HERE / "output"))
DATA.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

# The pair table built by 1_pairs.py and the model answers from 3_jev.py, handed to the later notebooks.
PAIRS_FILE = DATA / "pairs.parquet"
ANSWERS_FILE = DATA / "answers.parquet"

# US National Atlas Equal Area: one metric projection for all 50 states, so distances are in metres everywhere.
METRIC = "EPSG:9311"
# A pair is a candidate if its two points are this close, or if the two records give the same street address.
NEAR_M = 150
# Precision we ask of an automatic decision, in both directions (merge, keep apart).
TARGET_PRECISION = 0.97


@dataclass(frozen=True)
class Region:
    state_fips: int
    counties: list[str]
    osm_relation: int
    bbox: tuple[float, float, float, float]


# The two regions with a published answer key.
REGIONS = {
    "New York City": Region(36, ["36005", "36047", "36061", "36081", "36085"], 175905, (-74.26, 40.49, -73.69, 40.92)),
    "Los Angeles County": Region(6, ["06037"], 396479, (-118.95, 33.30, -117.64, 34.83)),
}


def fetch_bytes(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 900) -> bytes:
    """GET (or POST data) with up to four tries and a growing pause between them."""
    _headers = {"User-Agent": "school-campus-dedup spike", **(headers or {})}
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, data=data, headers=_headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"{url} returned HTTP {response.status}")
                return response.read()
        except (OSError, RuntimeError, http.client.HTTPException):
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def cached(name: str, url: str, data: bytes | None = None, headers: dict | None = None) -> Path:
    """Download once into DATA/name; later runs reuse the copy."""
    path = DATA / name
    if not path.exists():
        path.write_bytes(fetch_bytes(url, data, headers))
    return path


def load_schools() -> gpd.GeoDataFrame:
    """HIFLD Next Public Schools, 50 states and DC, in metres. 1_pairs.py downloads the file first."""
    raw = gpd.read_parquet(DATA / "public-schools.parquet")
    schools = raw[~raw["STATE"].isin(["PR", "GU", "VI", "AS", "MP", "PW", "FM", "MH"])]
    return schools.to_crs(METRIC).reset_index(drop=True)


# Where a room, floor, annex or trailer starts: "26 BROADWAY-12TH FL", "3740 BAYCHESTER AVE ANNEX".
UNIT_MARKER = (
    r"\s(?:-?RM|ROOM|STE|SUITE|UNIT|BLDG|FL|FLOOR|ANNEX|TRAILER|LOWER|UPPER)\b|#|-(?=[A-Z]|\d+(?:ST|ND|RD|TH)\b)"
)
STREET_TYPES = {"ST", "STREET", "AVE", "AVENUE", "BLVD", "BOULEVARD", "RD", "ROAD", "DR", "DRIVE", "PL", "PLACE"}
STREET_TYPES |= {"WAY", "LN", "LANE"}


def address_unit(address: str) -> str:
    """The room, floor, annex or trailer part of an address, or '' if there is none."""
    parts = re.split(f"({UNIT_MARKER})", str(address).upper(), maxsplit=1)
    return "".join(parts[1:]).strip(" -#") if len(parts) > 1 else ""


def normalise_address(address: str) -> str:
    """House number and street, upper case, without punctuation, units or street-type words."""
    text = re.split(UNIT_MARKER, re.sub(r"[.,]", " ", str(address).upper()))[0]
    return " ".join(w for w in text.split() if w not in STREET_TYPES)


def candidate_pairs(frame: gpd.GeoDataFrame) -> pd.DataFrame:
    """Index pairs (i < j) of records within NEAR_M metres or with the same normalised address and city."""
    near = gpd.sjoin(frame[["geometry"]], frame[["geometry"]], predicate="dwithin", distance=NEAR_M)
    near = pd.DataFrame({"i": near.index, "j": near["index_right"].to_numpy()})
    key = frame["ADDRESS"].map(normalise_address) + "|" + frame["CITY"].str.upper()
    by_key = pd.DataFrame({"key": key, "i": frame.index})
    same = by_key.merge(by_key, on="key", suffixes=("", "_b")).rename(columns={"i_b": "j"})[["i", "j"]]
    pairs = pd.concat([near, same]).query("i < j").drop_duplicates().reset_index(drop=True)
    points = frame.geometry
    pairs["distance_m"] = points.iloc[pairs["i"]].distance(points.iloc[pairs["j"]], align=False).to_numpy()
    pairs["same_address"] = key.iloc[pairs["i"]].to_numpy() == key.iloc[pairs["j"]].to_numpy()
    return pairs


def thresholds(score: pd.Series, truth: pd.Series) -> tuple[float, float]:
    """(merge_at, apart_at) meeting TARGET_PRECISION on these pairs, each over at least 10 pairs.

    inf / -inf when no threshold qualifies, so nothing is decided automatically in that direction.
    """
    assert len(score) == len(truth), "score and truth must line up"
    merge_at, apart_at = np.inf, -np.inf
    for t in np.unique(score):
        above, below = truth[score >= t], truth[score <= t]
        if merge_at == np.inf and len(above) >= 10 and above.mean() >= TARGET_PRECISION:
            merge_at = t
        if len(below) >= 10 and 1 - below.mean() >= TARGET_PRECISION:
            apart_at = t
    return merge_at, apart_at


def triage(scored: pd.DataFrame, scores: dict[str, str], plain_cut: dict[str, float]) -> pd.DataFrame:
    """For each region and method: thresholds from the tune half, counted on the test half.

    `scores` maps a method's label to its column; `plain_cut` gives the plain yes/no cut for a column (default 0.5).
    """
    rows = []
    for region in REGIONS:
        known = scored[(scored["region"] == region) & scored["truth"].notna()]
        tune, test = known[known["half"] == "tune"], known[known["half"] == "test"]
        for label, column in scores.items():
            merge_at, apart_at = thresholds(tune[column].astype(float), tune["truth"])
            s, y = test[column].astype(float), test["truth"]
            merge = s >= merge_at
            apart = (s <= apart_at) & ~merge
            said_yes = s >= plain_cut.get(column, 0.5)
            rows.append(
                {
                    "region": region,
                    "method": label,
                    "test pairs": len(test),
                    "merged": int(merge.sum()),
                    "merged wrongly": int((merge & (y == 0)).sum()),
                    "kept apart": int(apart.sum()),
                    "kept apart wrongly": int((apart & (y == 1)).sum()),
                    "to review": int((~merge & ~apart).sum()),
                    "decided %": round(100 * (merge | apart).mean(), 1),
                    "plain precision": round(float(y[said_yes].mean()), 3),
                    "plain recall": round(float(said_yes[y == 1].mean()), 3),
                }
            )
    return pd.DataFrame(rows)
