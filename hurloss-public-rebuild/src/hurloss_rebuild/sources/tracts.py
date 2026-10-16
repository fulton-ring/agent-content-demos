"""Census 2020 tract population centroids, and NRI tract hurricane loss (v1.19 and v1.20).

A tract's wind is computed at its population-weighted centre (Census "CenPop2020"), where its
people and most of its buildings are.
"""

import pandas as pd

from hurloss_rebuild import http
from hurloss_rebuild.paths import cache_path

CENTROIDS_URL = (
    "https://www2.census.gov/geo/docs/reference/cenpop2020/tract/CenPop2020_Mean_TR{state}.txt"
)
NRI_SERVICE = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/{layer}/FeatureServer/0/query"
NRI_LAYERS = {
    "v1_19": "National_Risk_Index_Census_Tracts_(March_2023)",
    "v1_20": "National_Risk_Index_Census_Tracts",
}
FIELDS = ("TRACTFIPS", "STCOFIPS", "NRI_VER", "HRCN_EALT", "HRCN_EXPT")
PAGE = 2000
MAX_PAGES = 20


def centroids(state_fips: str) -> pd.DataFrame:
    """Population-weighted tract centres for one state, indexed by 11-digit tract FIPS."""
    if len(state_fips) != 2 or not state_fips.isdigit():
        raise ValueError(f"state FIPS must be two digits: {state_fips}")
    path = http.download(
        CENTROIDS_URL.format(state=state_fips), cache_path("tracts", f"cenpop_{state_fips}.txt")
    )
    table = pd.read_csv(path, dtype={"STATEFP": str, "COUNTYFP": str, "TRACTCE": str})
    table.columns = [c.lstrip("﻿") for c in table.columns]
    table["tract"] = table["STATEFP"] + table["COUNTYFP"] + table["TRACTCE"]
    table = table.set_index("tract")[["POPULATION", "LATITUDE", "LONGITUDE"]]
    if table.empty or not table.index.is_unique:
        raise ValueError(f"bad tract centroid table for state {state_fips}")
    return table.rename(columns=str.lower)


def nri_page(layer: str, state_abbr: str, offset: int) -> list[dict[str, object]]:
    params = {
        "where": f"STATEABBRV='{state_abbr}'",
        "outFields": ",".join(FIELDS),
        "returnGeometry": "false",
        "resultOffset": offset,
        "resultRecordCount": PAGE,
        "orderByFields": "TRACTFIPS",
        "f": "json",
    }
    response = http.session().get(NRI_SERVICE.format(layer=layer), params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    if "features" not in payload:
        raise RuntimeError(f"NRI tract service returned no features: {payload}")
    return [feature["attributes"] for feature in payload["features"]]


def nri(version: str, state_abbr: str) -> pd.DataFrame:
    """NRI tract hurricane EAL and exposure for one state, indexed by tract FIPS."""
    target = cache_path("tracts", f"nri_{version}_{state_abbr}.parquet")
    if not target.exists():
        rows: list[dict[str, object]] = []
        for page in range(MAX_PAGES):
            batch = nri_page(NRI_LAYERS[version], state_abbr, page * PAGE)
            rows += batch
            if len(batch) < PAGE:
                break
        else:
            raise RuntimeError("NRI tract table has more pages than expected")
        pd.DataFrame(rows).to_parquet(target)
    table = pd.read_parquet(target).set_index("TRACTFIPS")
    if table.empty or not table.index.is_unique:
        raise RuntimeError(f"bad NRI {version} tract table for {state_abbr}")
    return table
