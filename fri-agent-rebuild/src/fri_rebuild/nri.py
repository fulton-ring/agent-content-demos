"""FEMA National Risk Index v1.19.0 (March 2023) tables, the baseline the Future Risk Index used.

FEMA no longer serves v1.19, and fema.gov blocks this environment; we use the snapshot of the NRI
data archive on Harvard Dataverse (doi:10.7910/DVN/JSQ8KZ, captured 2024-12-13).
"""

import pandas as pd
import requests

from fri_rebuild.paths import cache_path

DATAVERSE = "https://dataverse.harvard.edu/api/access/datafile"
TRACT_TABLE_ID = "10775728"
HAZARDS = ("CFLD", "DRGT", "HWAV", "WFIR", "HRCN")
TRACT_COLUMNS = [
    "TRACTFIPS",
    "STCOFIPS",
    "STATEABBRV",
    "COUNTY",
    "NRI_VER",
    "AREA",
    "POPULATION",
    "BUILDVALUE",
    *[f"{hazard}_{suffix}" for hazard in HAZARDS for suffix in ("EALT", "EALR", "AFREQ")],
]


def download(file_id: str, name: str) -> None:
    target = cache_path("nri", name)
    if target.exists():
        return
    partial = target.with_suffix(".partial")
    with requests.get(f"{DATAVERSE}/{file_id}", stream=True, timeout=600) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for block in response.iter_content(chunk_size=8 << 20):
                handle.write(block)
    partial.rename(target)


def tracts() -> pd.DataFrame:
    """Census tract EAL for the Future Risk hazards, indexed by 11-digit tract FIPS."""
    parquet = cache_path("nri", "tracts_v1_19.parquet")
    if not parquet.exists():
        download(TRACT_TABLE_ID, "NRI_Table_CensusTracts.csv")
        table = pd.read_csv(
            cache_path("nri", "NRI_Table_CensusTracts.csv"),
            usecols=TRACT_COLUMNS,
            dtype={"TRACTFIPS": str, "STCOFIPS": str},
        )
        table["TRACTFIPS"] = table["TRACTFIPS"].str.zfill(11)
        table["STCOFIPS"] = table["STCOFIPS"].str.zfill(5)
        table.to_parquet(parquet)
        cache_path("nri", "NRI_Table_CensusTracts.csv").unlink()
    return pd.read_parquet(parquet).set_index("TRACTFIPS")


if __name__ == "__main__":
    print(tracts()[["STCOFIPS", "NRI_VER", "HWAV_EALT"]].head())
