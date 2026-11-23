"""Archive the eWRIMS Water Rights LIST before the State Water Board removes it.

Downloads, from data.ca.gov:
- the discontinued eWRIMS "California Water Rights LIST" CSV and its two data dictionaries,
- this week's CalWATRS Participants and Geospatial tables and their data dictionaries,

records where each file came from, the portal's dates and a SHA-256 checksum in
outputs/archive_manifest.json, and saves the eWRIMS list as GeoParquet (one row per right,
a point at its listed point of diversion). Raw files go to data/ and are not committed.

Run: uv run archive.py
"""

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

CKAN = os.environ.get("CKAN_API", "https://data.ca.gov/api/3/action")
DATA_DIR = Path(os.environ.get("CROSSWALK_DATA_DIR", "data"))
OUT_DIR = Path(os.environ.get("CROSSWALK_OUT_DIR", "outputs"))
MAX_TRIES = 4
DATASETS = {
    "ewrims_list": "water-rights",
    "calwatrs_participants": "calwatrs-participants",
    "calwatrs_geospatial": "calwatrs-geospatial",
}


def get(url: str, **kwargs: object) -> requests.Response:
    """GET with a bounded number of retries and exponential backoff."""
    for attempt in range(1, MAX_TRIES + 1):
        try:
            r = requests.get(url, timeout=300, **kwargs)  # type: ignore[arg-type]
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == MAX_TRIES:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_dataset(key: str, package_id: str) -> dict:
    """Download every resource of one data.ca.gov dataset and describe it for the manifest."""
    package = get(f"{CKAN}/package_show", params={"id": package_id}).json()["result"]
    files = []
    for res in package["resources"]:
        url = res["url"]
        dest = DATA_DIR / key / url.rsplit("/", 1)[-1]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(get(url).content)
        assert dest.stat().st_size > 0, f"empty download: {url}"
        files.append(
            {
                "name": res["name"],
                "url": url,
                "path": str(dest),
                "bytes": dest.stat().st_size,
                "sha256": sha256(dest),
                "portal_resource_last_modified": res["last_modified"],
            }
        )
    return {
        "dataset": package["title"],
        "page": f"https://data.ca.gov/dataset/{package_id}",
        "license": package["license_title"],
        "portal_metadata_modified": package["metadata_modified"],
        "portal_created": package["metadata_created"],
        "files": files,
    }


started = time.perf_counter()
fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
manifest = {"fetched_at": fetched_at, "datasets": {}}
for key, package_id in DATASETS.items():
    manifest["datasets"][key] = archive_dataset(key, package_id)
    print(f"downloaded {key}: {len(manifest['datasets'][key]['files'])} files")

# The eWRIMS list as GeoParquet. Every column is kept as text, exactly as published, so the
# archive is lossless; only the point geometry is parsed from LATITUDE and LONGITUDE (NAD83).
ewrims_csv = next(
    Path(f["path"])
    for f in manifest["datasets"]["ewrims_list"]["files"]
    if f["path"].endswith(".csv")
)
ewrims = pd.read_csv(ewrims_csv, dtype=str, encoding="utf-8-sig", keep_default_na=False)
assert "APPLICATION_NUMBER" in ewrims.columns, "eWRIMS list changed shape"
lat = pd.to_numeric(ewrims["LATITUDE"], errors="coerce")
lon = pd.to_numeric(ewrims["LONGITUDE"], errors="coerce")
archive = gpd.GeoDataFrame(ewrims, geometry=gpd.points_from_xy(lon, lat), crs=4269)
OUT_DIR.mkdir(parents=True, exist_ok=True)
parquet = OUT_DIR / "ewrims_water_rights_list.parquet"
archive.to_parquet(parquet)
manifest["ewrims_geoparquet"] = {
    "path": str(parquet),
    "rows": len(archive),
    "columns": len(ewrims.columns),
    "rows_with_point": int(lat.notna().sum()),
    "sha256": sha256(parquet),
}
manifest["run_seconds"] = round(time.perf_counter() - started, 1)
(OUT_DIR / "archive_manifest.json").write_text(json.dumps(manifest, indent=2))
print(json.dumps(manifest["ewrims_geoparquet"], indent=2))
print(f"archive done in {manifest['run_seconds']} s")
