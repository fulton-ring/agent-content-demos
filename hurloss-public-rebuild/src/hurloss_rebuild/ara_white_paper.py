"""ARA's own published climate-conditioned landfall rates, through FEMA's Eq. 11.

Source: Applied Research Associates, "Incorporating Climate Change into a Hurricane Model"
(2022), Figure 1, "Frequency of landfalling events by region and intensity"
(https://www.ara.com/wp-content/uploads/ARA_ClimateChange_NatCatModels_WhitePaper.pdf).
The paper gives the rates only as bars, so the values below were read off the figure by eye
(about +/-0.003 storms/year). They are CESM RCP 8.5 runs for 2021 and 2050 against a reference
model built on 1900-2018 reanalysis. ARA scales its event weights by exactly these ratios, by
category and region, so they are the closest public view of what FEMA's input contains.
"""

from dataclasses import replace

import numpy as np
import pandas as pd

from hurloss_rebuild import fri_formula
from hurloss_rebuild.hazard import Events

# Landfalls per year, Cat 1..5: (reference, RCP 8.5 2021, RCP 8.5 2050).
FIGURE_1 = {
    "Gulf (TX-AL)": (
        (0.208, 0.188, 0.195, 0.126, 0.016),
        (0.209, 0.201, 0.203, 0.145, 0.024),
        (0.199, 0.196, 0.198, 0.139, 0.030),
    ),
    "Florida": (
        (0.198, 0.134, 0.178, 0.089, 0.028),
        (0.200, 0.136, 0.182, 0.095, 0.045),
        (0.190, 0.139, 0.186, 0.090, 0.057),
    ),
    "SE coast (GA-NC)": (
        (0.114, 0.100, 0.097, 0.028, 0.003),
        (0.111, 0.108, 0.107, 0.031, 0.004),
        (0.112, 0.113, 0.106, 0.034, 0.010),
    ),
    "NE coast (VA-ME)": (
        (0.061, 0.089, 0.082, 0.008, 0.000),
        (0.058, 0.102, 0.093, 0.010, 0.000),
        (0.056, 0.097, 0.086, 0.009, 0.000),
    ),
}
REGION_STATES = {
    "Gulf (TX-AL)": ("TX", "LA", "MS", "AL"),
    "Florida": ("FL",),
    "SE coast (GA-NC)": ("GA", "SC", "NC"),
    "NE coast (VA-ME)": ("VA", "DC", "MD", "DE", "PA", "NJ", "NY", "CT", "RI", "MA", "NH", "ME"),
}


def regional_ratios() -> pd.DataFrame:
    """Eq. 11 intensity ratios from Figure 1, per region."""
    rows = []
    for region, (reference, now, future) in FIGURE_1.items():
        weighted = [
            float(fri_formula.intensity(pd.Series(r).to_numpy())) for r in (reference, now, future)
        ]
        rows.append(
            {
                "region": region,
                "ratio_2050_vs_reference": weighted[2] / weighted[0],
                "ratio_2050_vs_2021": weighted[2] / weighted[1],
                "ratio_2021_vs_reference": weighted[1] / weighted[0],
            }
        )
    return pd.DataFrame(rows).set_index("region")


def compare_with_published(key: pd.DataFrame) -> pd.DataFrame:
    """ARA's regional ratios next to the median published MID_HIGHER multiplier in that region."""
    table = regional_ratios()
    hm = key["HRCN_MID_HIGHER_HM"]
    table["published_mid_higher_median"] = [
        hm[key["STATEABBRV"].isin(REGION_STATES[region]) & (hm > 0)].median()
        for region in table.index
    ]
    return table


def category_ratios(column: int) -> dict[str, np.ndarray]:
    """Per region, the Cat 1-5 landfall-rate ratio of scenario `column` (1=2021, 2=2050)."""
    ratios = {}
    for region, rows in FIGURE_1.items():
        reference = np.array(rows[0])
        scenario = np.array(rows[column])
        ratios[region] = np.divide(
            scenario, reference, out=np.ones_like(scenario), where=reference > 0
        )
    return ratios


def point_regions(point_county: pd.Series, county_state: pd.Series) -> np.ndarray:
    """The ARA region of each grid point ('' outside the four regions)."""
    region_of_state = {
        state: region for region, states in REGION_STATES.items() for state in states
    }
    first_county = point_county.groupby(level=0).first().sort_index()
    states = county_state.reindex(first_county.to_numpy()).to_numpy()
    return np.array([region_of_state.get(state, "") for state in states])


def condition(events: Events, regions: np.ndarray, column: int = 2) -> Events:
    """ARA's method on our event set: scale each event's rate by its region-category ratio.

    ARA uses each event's landfall region and category. Our proxy is the grid point where the
    event's wind peaks: its region, and the category of that peak wind. Events peaking below
    Cat 1 or outside the four regions keep their rate.
    """
    if regions.shape[0] != events.wind.shape[1]:
        raise ValueError("one region per grid point expected")
    ratios = category_ratios(column)
    peak_point = np.asarray(events.wind.argmax(axis=1)).ravel()
    peak_wind = np.asarray(events.wind.max(axis=1).toarray()).ravel()
    category = np.searchsorted(fri_formula.CATEGORY_FLOOR_MS, peak_wind, side="right") - 1
    scale = np.ones(events.wind.shape[0])
    for event in np.flatnonzero(category >= 0):
        region = regions[peak_point[event]]
        if region:
            scale[event] = ratios[region][category[event]]
    return replace(events, frequency=events.frequency * scale)
