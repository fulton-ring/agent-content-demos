"""Helpers the three state notebooks share: fetching WSWC's leftovers and scoring a rebuild.

Each notebook keeps its own state-specific mapping in its cells. Only the parts that are
identical across states live here: downloading, the WaDE answer key, the field comparison,
the primary-use lookup and writing GeoParquet.
"""

import json
import os
import re
import time
from pathlib import Path

import gdown
import geopandas as gpd
import numpy as np
import pandas as pd
import requests

# WSWC's mapping repo, pinned to the last commit before WaDE went offline (2025-12-15).
GITHUB_RAW = (
    "https://raw.githubusercontent.com/WSWCWaterDataExchange/MappingStatesDataToWaDE2.0/"
    "d4a35fd39b3e899e9ccafbb771f51d96d2fbf4ce"
)
DATA_DIR = Path(os.environ.get("WADE_DATA_DIR", "data"))
OUT_DIR = Path(os.environ.get("WADE_OUT_DIR", "outputs"))
MAX_TRIES = 4

# Values WaDE used to mean "nothing here". A field counts as present only without these.
BLANKS = {"", "nan", "none", "wade blank", "wade_unspecified", "unspecified", "0", "0.0"}

# The allocation fields compared for every state. Location is scored separately.
FIELDS = [
    "AllocationOwner",
    "AllocationPriorityDate",
    "AllocationLegalStatusCV",
    "AllocationTypeCV",
    "AllocationFlow_CFS",
    "AllocationVolume_AF",
    "BeneficialUseCategory",
    "PrimaryBeneficialUseCategory",
    "IrrigatedAcreage",
]
NUMERIC = {"AllocationFlow_CFS", "AllocationVolume_AF", "IrrigatedAcreage"}


def fetch(url: str, dest: Path, keep: bool = False) -> Path:
    """Download url to dest with bounded retries. keep=True reuses an earlier download."""
    if keep and dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, MAX_TRIES + 1):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            return dest
        except requests.RequestException:
            if attempt == MAX_TRIES:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def drive_folder_from_readme(readme_path: str) -> str:
    """Read a WSWC state README on GitHub and return the Google Drive folder it points to."""
    r = requests.get(f"{GITHUB_RAW}/{readme_path}", timeout=60)
    r.raise_for_status()
    found = re.findall(r"https://drive\.google\.com/drive/folders/([\w-]+)", r.text)
    if not found:
        raise ValueError(f"No Drive folder link in {readme_path}")
    return found[0]


def drive_listing(folder_id: str) -> dict[str, str]:
    """List every file in a shared Drive folder as {path: file id}, without downloading."""
    files = gdown.download_folder(id=folder_id, skip_download=True, quiet=True)
    if not files:
        raise RuntimeError(f"Drive folder {folder_id} is empty or no longer shared")
    return {f.path: f.id for f in files if not isinstance(f, str)}


def drive_file(file_id: str, dest: Path) -> Path:
    """Download one Drive file, reusing it if already here (the archive is frozen)."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = gdown.download(id=file_id, output=str(dest), quiet=True)
    if out is None or not dest.exists():
        raise RuntimeError(f"Drive download failed for {file_id}")
    return dest


def wade_answer_key(state: str, listing: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """WaDE's last processed waterallocations.csv and sites.csv for one state, from Drive."""
    alloc = drive_file(
        listing["ProcessedInputData/waterallocations.csv"],
        DATA_DIR / state / "wade_waterallocations.csv",
    )
    sites = drive_file(listing["ProcessedInputData/sites.csv"], DATA_DIR / state / "wade_sites.csv")
    a = pd.read_csv(alloc, dtype=str, keep_default_na=False)
    s = pd.read_csv(sites, dtype=str, keep_default_na=False)
    return a, s


def wade_dropped(state: str, listing: dict[str, str]) -> pd.Series:
    """Rights WSWC's own error checks removed before loading WaDE, with the reason given.

    WSWC wrote these to ProcessedInputData/waterallocations_missing.csv.
    """
    path = drive_file(
        listing["ProcessedInputData/waterallocations_missing.csv"],
        DATA_DIR / state / "wade_waterallocations_missing.csv",
    )
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    return df.drop_duplicates("AllocationNativeID").set_index("AllocationNativeID")["ReasonRemoved"]


def extra_rights(rebuilt: pd.DataFrame, wade: pd.DataFrame, dropped: pd.Series) -> dict:
    """Split the rebuild's rights that WaDE didn't have into ones WSWC's checks dropped and new."""
    extra = rebuilt.index.difference(wade.index)
    was_dropped = extra.isin(dropped.index)
    reasons = dropped.reindex(extra[was_dropped]).str.split(",").str[0].value_counts()
    return {
        "not_in_wade": int(len(extra)),
        "dropped_by_wade_checks": int(was_dropped.sum()),
        "top_drop_reasons": {k: int(v) for k, v in reasons.head(3).items()},
        "new_or_unexplained": int((~was_dropped).sum()),
    }


def wade_first_site_coords(alloc: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    """Latitude and longitude of the first site WaDE listed for each right."""
    first = alloc["SiteUUID"].str.split(",").str[0].str.strip()
    coords = sites.set_index("SiteUUID")[["Latitude", "Longitude"]]
    out = coords.reindex(first.to_numpy())
    out.index = alloc["AllocationNativeID"].to_numpy()
    return out.apply(pd.to_numeric, errors="coerce")


def is_blank(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(BLANKS)


def _norm_text(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip()


def _norm_set(s: pd.Series) -> pd.Series:
    return s.astype(str).map(
        lambda v: ",".join(sorted({t.strip().lower() for t in str(v).split(",") if t.strip()}))
    )


def _agree(field: str, wade: pd.Series, rebuilt: pd.Series) -> pd.Series:
    if field in NUMERIC:
        w = pd.to_numeric(wade, errors="coerce")
        r = pd.to_numeric(rebuilt, errors="coerce")
        return (w - r).abs() <= np.maximum(0.01, 0.01 * w.abs())
    if field == "AllocationPriorityDate":
        w = pd.to_datetime(wade, errors="coerce", format="mixed")
        r = pd.to_datetime(rebuilt, errors="coerce", format="mixed")
        return w.dt.date == r.dt.date
    if field == "BeneficialUseCategory":
        return _norm_set(wade) == _norm_set(rebuilt)
    return _norm_text(wade) == _norm_text(rebuilt)


def compare_fields(wade: pd.DataFrame, rebuilt: pd.DataFrame) -> pd.DataFrame:
    """For rights in both tables, how often each field WaDE filled in comes back the same.

    Both frames are indexed by AllocationNativeID. A field WaDE left blank for this state
    is reported as "blank in WaDE" rather than scored.
    """
    both = wade.index.intersection(rebuilt.index)
    w, r = wade.loc[both], rebuilt.loc[both]
    rows = []
    for field in FIELDS:
        has = ~is_blank(w[field]) if field in w else pd.Series(False, index=both)
        n = int(has.sum())
        if n == 0:
            rows.append(
                {"field": field, "wade_filled": 0, "same_value": None, "status": "blank in WaDE"}
            )
            continue
        if field not in r or is_blank(r[field])[has].all():
            rows.append(
                {"field": field, "wade_filled": n, "same_value": 0.0, "status": "no source column"}
            )
            continue
        same = float(_agree(field, w.loc[has, field], r.loc[has, field]).mean())
        status = "comes back" if same >= 0.95 else "partly" if same >= 0.5 else "differs"
        rows.append(
            {"field": field, "wade_filled": n, "same_value": round(same, 3), "status": status}
        )
    return pd.DataFrame(rows)


def location_agreement(wade_xy: pd.DataFrame, rebuilt: gpd.GeoDataFrame, metres: float) -> float:
    """Share of matched rights whose rebuilt point is within `metres` of WaDE's first site."""
    both = wade_xy.dropna().index.intersection(rebuilt.index)
    xy = wade_xy.loc[both]
    w = gpd.GeoSeries.from_xy(xy["Longitude"], xy["Latitude"], index=both, crs=4326).to_crs(5070)
    r = rebuilt.loc[both].geometry.to_crs(5070)
    return round(float((w.distance(r) <= metres).mean()), 3)


def primary_use_lookup() -> tuple[dict[str, str], dict[str, str]]:
    """WSWC's hand-built native-term -> WaDE-category table and its two-use tie-breaker.

    The spreadsheet is the hand harmonization: 523 native beneficial-use names, each
    assigned a WaDE category by WSWC staff. The pairs dict is copied from
    5_CustomFunctions/AssignPrimaryUseCategory/AssignPrimaryUseCategoryFile.py.
    """
    path = fetch(
        f"{GITHUB_RAW}/5_CustomFunctions/AssignPrimaryUseCategory/PrimaryBenUseInput.xlsx",
        DATA_DIR / "PrimaryBenUseInput.xlsx",
        keep=True,
    )
    df = pd.read_excel(path).fillna("")
    terms = dict(zip(df["Name"].astype(str).str.lower().str.strip(), df["WaDEname"], strict=True))
    pairs = {
        "Agriculture Irrigation,Aquaculture": "Agriculture Irrigation",
        "Agriculture Irrigation,Commercial/Industrial": "Agriculture Irrigation",
        "Agriculture Irrigation,Domestic": "Agriculture Irrigation",
        "Agriculture Irrigation,Livestock": "Agriculture Irrigation",
        "Agriculture Irrigation,Other": "Agriculture Irrigation",
        "Agriculture Irrigation,Public Supply": "Agriculture Irrigation",
        "Agriculture Irrigation,Recreation": "Agriculture Irrigation",
        "Agriculture Irrigation,Unspecified": "Agriculture Irrigation",
        "Aquaculture,Recreation": "Recreation",
        "Commercial/Industrial,Domestic": "Commercial/Industrial",
        "Commercial/Industrial,Livestock": "Commercial/Industrial",
        "Domestic,Fire": "Domestic",
        "Domestic,Livestock": "Livestock",
        "Domestic,Municipal Irrigation": "Municipal Irrigation",
        "Domestic,Other": "Domestic",
        "Domestic,Public Supply": "Public Supply",
        "Domestic,Unspecified": "Domestic",
        "Fire,Livestock": "Livestock",
        "In-stream Flow,Unspecified": "In-stream Flow",
        "Livestock,Municipal Irrigation": "Municipal Irrigation",
        "Livestock,Other": "Livestock",
        "Livestock,Unspecified": "Livestock",
        "Public Supply,Unspecified": "Public Supply",
        "Reservoir Storage,Unspecified": "Reservoir Storage",
    }
    return terms, pairs


def primary_use(uses: pd.Series, terms: dict[str, str], pairs: dict[str, str]) -> pd.Series:
    """WSWC's primary-use rule. Returns "" where a native term isn't in the hand-built table.

    WSWC's own function raises KeyError on an unknown term, so a new term stopped the
    pipeline until someone added a row to the spreadsheet by hand.
    """

    def one(value: str) -> str:
        names = sorted(t.strip().lower() for t in str(value).split(",") if t.strip())
        if not names or any(n not in terms for n in names):
            return ""
        wade = sorted(terms[n] for n in names)
        if len(wade) == 2:
            return pairs.get(",".join(wade), wade[0])
        return wade[0]

    return uses.map(one)


def unknown_use_terms(uses: pd.Series, terms: dict[str, str]) -> pd.Series:
    """Native beneficial-use terms missing from WSWC's table, with how many rights use each."""
    exploded = uses.astype(str).str.split(",").explode().str.strip().str.lower()
    exploded = exploded[exploded != ""]
    return exploded[~exploded.isin(terms.keys())].value_counts()


def write_geoparquet(rights: gpd.GeoDataFrame, state: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{state}_water_rights.parquet"
    rights.reset_index().to_parquet(path)
    return path


def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame rows as dicts with NaN turned into None, so the JSON stays valid."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def save_summary(state: str, summary: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{state}_summary.json"
    path.write_text(json.dumps(summary, indent=2, default=str))
    return path
