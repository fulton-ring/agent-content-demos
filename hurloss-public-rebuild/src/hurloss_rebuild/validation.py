"""Is the layer believable where people know hurricanes hit? Two checks.

1. Return periods. NHC publishes, for points on the coast, how often a hurricane (>= 64 kt) and a
   major hurricane (>= 96 kt) passes within 50 nautical miles (HURISK, data through 2010;
   https://www.nhc.noaa.gov/climo/). We compute the same statistic from STORM's 10,000 years and
   from the observed best tracks (IBTrACS/HURDAT2, 1900-2024), so the catalogue behind our
   multipliers can be checked against both.
2. Named places. Projected loss and rating for the counties people would check first, under
   FEMA's multiplier and ours.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from climada.hazard import TCTracks

from hurloss_rebuild.sources import storm

RADIUS_KM = 92.6  # 50 nautical miles
HURRICANE_KT = 64.0
MAJOR_KT = 96.0
MS_TO_KT = 1.943844
TEN_TO_ONE_MINUTE = 1 / 0.88  # STORM's own 10-minute to 1-minute factor (CLIMADA uses it too)
EARTH_KM = 6371.0


@dataclass(frozen=True)
class Site:
    name: str
    lat: float
    lon: float
    nhc_hurricane_years: float  # read off NHC's return-period maps (return_hurr.jpg)
    nhc_major_years: float  # read off return_mjrhurr.jpg


# NHC values are read by eye from NHC's two maps, matching circles to places in coastal order;
# a neighbouring circle can differ by one class.
SITES = (
    Site("Key West, FL", 24.56, -81.78, 8, 18),
    Site("Miami, FL", 25.77, -80.19, 6, 14),
    Site("West Palm Beach, FL", 26.71, -80.05, 8, 19),
    Site("Tampa, FL", 27.95, -82.46, 9, 29),
    Site("Jacksonville, FL", 30.33, -81.66, 10, 36),
    Site("Charleston, SC", 32.78, -79.93, 8, 22),
    Site("Myrtle Beach, SC", 33.69, -78.89, 8, 23),
    Site("Wilmington, NC", 34.21, -77.89, 6, 17),
    Site("Cape Hatteras, NC", 35.25, -75.53, 5, 16),
    Site("New Orleans, LA", 29.95, -90.07, 8, 25),
    Site("Galveston, TX", 29.30, -94.80, 11, 26),
    Site("Long Island, NY", 40.80, -72.80, 18, 70),
)


def distance_km(lat: np.ndarray, lon: np.ndarray, site: Site) -> np.ndarray:
    """Great-circle distance from each fix to the site."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat, lon, site.lat, site.lon))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_KM * np.arcsin(np.sqrt(a))


def storms_passing(fixes: pd.DataFrame, site: Site, threshold_kt: float) -> int:
    """Storms with a fix within 50 nm of the site at or above the threshold (1-minute kt)."""
    near = distance_km(fixes["lat"].to_numpy(), fixes["lon"].to_numpy(), site) <= RADIUS_KM
    strong = fixes["wind_kt"].to_numpy() >= threshold_kt
    return int(fixes.loc[near & strong, "storm"].nunique())


def storm_fixes(files: int) -> pd.DataFrame:
    """STORM present-climate fixes: storm id, position, 1-minute wind in knots."""
    frames = []
    for index, path in enumerate(storm.fetch_all(None, files)):
        raw = pd.read_csv(path, header=None, usecols=[0, 2, 5, 6, 8])
        raw.columns = ["year", "tc", "lat", "lon", "wind_ms"]
        frames.append(
            pd.DataFrame(
                {
                    "storm": index * 10_000_000 + raw["year"] * 1000 + raw["tc"],
                    "lat": raw["lat"],
                    "lon": ((raw["lon"] + 180) % 360) - 180,
                    "wind_kt": raw["wind_ms"] * TEN_TO_ONE_MINUTE * MS_TO_KT,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def best_track_fixes(tracks: TCTracks) -> pd.DataFrame:
    """Observed fixes (US agency winds, 1-minute kt), one storm id per track."""
    frames = [
        pd.DataFrame(
            {
                "storm": number,
                "lat": track.lat.to_numpy(),
                "lon": track.lon.to_numpy(),
                "wind_kt": track.max_sustained_wind.to_numpy(),
            }
        )
        for number, track in enumerate(tracks.data)
    ]
    return pd.concat(frames, ignore_index=True)


def return_periods(
    storm_set: pd.DataFrame, storm_years: int, observed: pd.DataFrame, observed_years: int
) -> pd.DataFrame:
    """Years between hurricane and major-hurricane passages within 50 nm, three ways."""
    rows = []
    for site in SITES:
        row: dict[str, object] = {"site": site.name}
        for label, threshold in (("hurricane", HURRICANE_KT), ("major", MAJOR_KT)):
            modelled = storms_passing(storm_set, site, threshold)
            seen = storms_passing(observed, site, threshold)
            row[f"storm_{label}_years"] = storm_years / modelled if modelled else np.inf
            row[f"observed_{label}_years"] = observed_years / seen if seen else np.inf
            row[f"observed_{label}_count"] = seen
        row["nhc_hurricane_years"] = site.nhc_hurricane_years
        row["nhc_major_years"] = site.nhc_major_years
        rows.append(row)
    return pd.DataFrame(rows)


PLACES = {
    "12086": "Miami-Dade, FL",
    "12011": "Broward, FL",
    "12099": "Palm Beach, FL",
    "12087": "Monroe (Keys), FL",
    "12057": "Hillsborough (Tampa), FL",
    "45019": "Charleston, SC",
    "45051": "Horry (Myrtle Beach), SC",
    "45013": "Beaufort, SC",
    "37129": "New Hanover (Wilmington), NC",
    "37019": "Brunswick, NC",
    "37031": "Carteret, NC",
    "37055": "Dare (Outer Banks), NC",
    "22071": "Orleans, LA",
    "48201": "Harris (Houston), TX",
    "48167": "Galveston, TX",
}


def places(comparison: pd.DataFrame) -> pd.DataFrame:
    """Named counties: today's loss, FEMA's and our multiplier, projected loss, rating, rank."""
    table = comparison.copy()
    table["our_pal_rank_v1_20"] = table.groupby("scenario")["our_pal_v1_20"].rank(
        ascending=False, method="min"
    )
    table["fema_pal_rank"] = table.groupby("scenario")["fema_pal"].rank(
        ascending=False, method="min"
    )
    picked = table[table.index.isin(PLACES)].copy()
    picked.insert(0, "place", picked.index.map(PLACES))
    columns = [
        "place",
        "scenario",
        "eal_v1_19",
        "eal_v1_20",
        "fema_hm",
        "our_hm",
        "our_hm_low",
        "our_hm_high",
        "fema_rating",
        "our_rating_v1_19",
        "our_rating_v1_20",
        "fema_pal_rank",
        "our_pal_rank_v1_20",
    ]
    return picked[columns].sort_values(["scenario", "place"])


def catalogue_agreement(catalogues: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """How far the two hazard catalogues agree, per scenario, on counties both cover."""
    storm_hm, history_hm = catalogues["storm"], catalogues["historical"]
    both = ~storm_hm["no_cat1_wind"] & ~history_hm["no_cat1_wind"].reindex(storm_hm.index).fillna(
        True
    ).astype(bool)
    rows = []
    for scenario in ("MID_LOWER", "MID_HIGHER", "LATE_LOWER", "LATE_HIGHER"):
        a = storm_hm.loc[both, f"{scenario}_HM"]
        b = history_hm[f"{scenario}_HM"].reindex(a.index)
        rows.append(
            {
                "scenario": scenario,
                "counties_storm": int((~storm_hm["no_cat1_wind"]).sum()),
                "counties_historical": int((~history_hm["no_cat1_wind"]).sum()),
                "counties_both": int(both.sum()),
                "storm_median": a.median(),
                "historical_median": b.median(),
                "spearman": a.corr(b, method="spearman"),
                "median_abs_difference": (a - b).abs().median(),
            }
        )
    return pd.DataFrame(rows)
