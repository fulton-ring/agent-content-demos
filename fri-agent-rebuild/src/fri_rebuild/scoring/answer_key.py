"""FEMA's published Future Risk Index county values (the answer key).

The copy we use is the NRI Future Risk master datasheet that Fulton Ring downloaded before
FEMA removed the tool in February 2025, published in fulton-ring/nri-future-risk.
"""

import re

import numpy as np
import pandas as pd
import requests

from fri_rebuild.paths import cache_path

ANSWER_KEY_COMMIT = "c5cc0d6686832f809446fc6061a689eff71d09df"
ANSWER_KEY_URL = (
    f"https://raw.githubusercontent.com/fulton-ring/nri-future-risk/{ANSWER_KEY_COMMIT}"
    "/public/NRI_Future_Risk_Master_Datasheet_12052024.xlsx"
)
SCENARIOS = ("MID_LOWER", "MID_HIGHER", "LATE_LOWER", "LATE_HIGHER")
RATINGS = ("Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High")
CONUS_EXCLUDED = {"AK", "HI", "AS", "GU", "MP", "PR", "VI"}


def load() -> pd.DataFrame:
    """The master datasheet as a table indexed by 5-digit county FIPS."""
    parquet = cache_path("answer_key", "master_datasheet.parquet")
    if not parquet.exists():
        xlsx = cache_path("answer_key", "NRI_Future_Risk_Master_Datasheet_12052024.xlsx")
        if not xlsx.exists():
            response = requests.get(ANSWER_KEY_URL, timeout=120)
            response.raise_for_status()
            xlsx.write_bytes(response.content)
        table = pd.read_excel(xlsx)
        table["STCOFIPS"] = table["STCOFIPS"].astype(int).map("{:05d}".format)
        table.to_parquet(parquet)
    return pd.read_parquet(parquet).set_index("STCOFIPS")


def conus(table: pd.DataFrame) -> pd.DataFrame:
    return table[~table["STATEABBRV"].isin(CONUS_EXCLUDED)]


def rating_name(label: object) -> str | None:
    """'Relatively Low (10.9K - 241K)' -> 'Relatively Low'; None for no rating."""
    if not isinstance(label, str):
        return None
    name = re.sub(r"\s*\(.*\)$", "", label).strip()
    return name if name in RATINGS else None


def rating_thresholds(table: pd.DataFrame, hazard: str) -> np.ndarray:
    """Upper bound of each EAL rating: the largest EAL observed in that rating (FRI Sec. 3.2)."""
    names = table[f"{hazard}_EALR"].map(rating_name)
    eal = table[f"{hazard}_EALT"]
    return np.array([eal[names == rating].max() for rating in RATINGS[:-1]])


def rate(values: pd.Series, thresholds: np.ndarray) -> pd.Series:
    """Sort projected annual losses into the fixed NRI bins."""
    index = np.searchsorted(thresholds, values.to_numpy(), side="left")
    return pd.Series(np.array(RATINGS)[np.minimum(index, len(RATINGS) - 1)], index=values.index)
