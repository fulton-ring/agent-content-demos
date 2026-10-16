"""FEMA's published Future Risk Index county values (the answer key).

The copy is the NRI Future Risk master datasheet Fulton Ring downloaded before FEMA removed the
tool in February 2025, published in fulton-ring/nri-future-risk. Same file and commit as #15.
"""

import pandas as pd

from hurloss_rebuild import http
from hurloss_rebuild.paths import cache_path

ANSWER_KEY_COMMIT = "c5cc0d6686832f809446fc6061a689eff71d09df"
ANSWER_KEY_URL = (
    f"https://raw.githubusercontent.com/fulton-ring/nri-future-risk/{ANSWER_KEY_COMMIT}"
    "/public/NRI_Future_Risk_Master_Datasheet_12052024.xlsx"
)
CONUS_EXCLUDED = frozenset({"AK", "HI", "AS", "GU", "MP", "PR", "VI"})
KEPT_COLUMNS = ("STCOFIPS", "STATEABBRV", "COUNTY", "HRCN_EALT", "HRCN_EALR")


def load() -> pd.DataFrame:
    """Hurricane columns of the master datasheet, indexed by 5-digit county FIPS."""
    parquet = cache_path("answer_key", "hurricane.parquet")
    if not parquet.exists():
        xlsx = http.download(
            ANSWER_KEY_URL, cache_path("answer_key", "NRI_Future_Risk_Master_Datasheet.xlsx")
        )
        table = pd.read_excel(xlsx)
        table["STCOFIPS"] = table["STCOFIPS"].astype(int).map("{:05d}".format)
        hurricane = [c for c in table.columns if c.startswith("HRCN_") and c not in KEPT_COLUMNS]
        table[[*KEPT_COLUMNS, *hurricane]].to_parquet(parquet)
    table = pd.read_parquet(parquet).set_index("STCOFIPS")
    if not table.index.is_unique:
        raise ValueError("answer key has duplicate county FIPS")
    return table


def conus(table: pd.DataFrame) -> pd.DataFrame:
    return table[~table["STATEABBRV"].isin(CONUS_EXCLUDED)]
