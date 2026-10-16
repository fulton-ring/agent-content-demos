"""NRI v1.20 (December 2025) county hurricane fields, from FEMA's ArcGIS feature service.

The baseline check compares today's modelled hurricane hazard with these, before any climate
conditioning. (FEMA applied its multipliers to v1.19; fema.gov's v1.19 download is blocked here,
and v1.20 is the release that stays online.)
"""

import pandas as pd

from hurloss_rebuild import http
from hurloss_rebuild.paths import cache_path

FEATURE_SERVICE = (
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
    "National_Risk_Index_Counties/FeatureServer/0/query"
)
FIELDS = ("STCOFIPS", "NRI_VER", "BUILDVALUE", "HRCN_AFREQ", "HRCN_EXPT", "HRCN_EALT", "HRCN_EALB")
PAGE = 2000
MAX_PAGES = 5


def fetch_page(offset: int) -> list[dict[str, object]]:
    params = {
        "where": "1=1",
        "outFields": ",".join(FIELDS),
        "returnGeometry": "false",
        "resultOffset": offset,
        "resultRecordCount": PAGE,
        "f": "json",
    }
    response = http.session().get(FEATURE_SERVICE, params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    if "features" not in payload:
        raise RuntimeError(f"NRI feature service returned no features: {payload}")
    return [feature["attributes"] for feature in payload["features"]]


def counties() -> pd.DataFrame:
    """County hurricane EAL, exposure and annual frequency, indexed by 5-digit FIPS."""
    target = cache_path("nri", "nri_v1_20_counties_hurricane.parquet")
    if not target.exists():
        rows: list[dict[str, object]] = []
        for page in range(MAX_PAGES):
            batch = fetch_page(page * PAGE)
            rows += batch
            if len(batch) < PAGE:
                break
        else:
            raise RuntimeError("NRI county table has more pages than expected")
        pd.DataFrame(rows).to_parquet(target)
    table = pd.read_parquet(target).set_index("STCOFIPS")
    if len(table) < 3000:
        raise RuntimeError(f"NRI county table is short: {len(table)} rows")
    return table
