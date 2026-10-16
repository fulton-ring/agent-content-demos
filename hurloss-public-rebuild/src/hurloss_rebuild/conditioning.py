"""Climate conditioning of an event set for FEMA's four Future Risk scenarios.

FEMA's hurricane scenarios come from ARA runs under RCP 4.5 ("lower") and RCP 8.5 ("higher") for
2050 ("mid") and 2100 ("late") (FRI Table 5, Sec. 7.1). The public stand-in is Knutson et al.
(2020) as converted to any baseline and year by Jewson (2021), shipped with CLIMADA.
"""

from dataclasses import dataclass, replace

import numpy as np
from climada.hazard.tc_clim_change import get_knutson_scaling_factor
from scipy import sparse

from hurloss_rebuild.hazard import Events


@dataclass(frozen=True)
class Scenario:
    name: str
    rcp: str
    year: int


SCENARIOS = (
    Scenario("MID_LOWER", "4.5", 2050),
    Scenario("MID_HIGHER", "8.5", 2050),
    Scenario("LATE_LOWER", "4.5", 2100),
    Scenario("LATE_HIGHER", "8.5", 2100),
)
# Knutson et al. (2020) report these percentiles of model spread: 5th/95th for all-storm
# frequency and 10th/90th for Cat 4-5 frequency and intensity, paired as CLIMADA pairs them.
PERCENTILES = ("5/10", "25", "50", "75", "90/95")
CENTRAL = "50"


def knutson_percent(
    variable: str,
    scenario: Scenario,
    basin: str,
    years: tuple[int, int],
    percentile: str = CENTRAL,
) -> float:
    """Knutson/Jewson % change in `variable` for one basin, relative to `years`."""
    if percentile not in PERCENTILES:
        raise ValueError(f"unknown Knutson percentile: {percentile}")
    table = get_knutson_scaling_factor(
        variable=variable, percentile=percentile, basin=basin, baseline=years, yearly_steps=5
    )
    return float(table.loc[scenario.year, scenario.rcp])


def frequency_only(events: Events, scenario: Scenario, percentile: str = CENTRAL) -> Events:
    """Jewson's recommended use: rescale event rates by peak category, winds unchanged.

    Cat 4-5 events take Knutson's Cat 4-5 frequency change; the rest take whatever keeps the
    all-storm frequency change right (the same arithmetic as CLIMADA's
    `TropCyclone.apply_climate_scenario_knu`).
    """
    frequency = events.frequency.copy()
    strong = np.isin(events.category, [4, 5])
    for basin in np.unique(events.basin):
        in_basin = events.basin == basin
        all_change = knutson_percent("cat05", scenario, str(basin), events.years, percentile)
        strong_change = knutson_percent("cat45", scenario, str(basin), events.years, percentile)
        all_change, strong_change = all_change / 100, strong_change / 100
        weak_total = frequency[in_basin & ~strong].sum()
        strong_total = frequency[in_basin & strong].sum()
        if weak_total <= 0:
            raise ValueError(f"no Cat 0-3 events in basin {basin}")
        weak_change = (all_change * (weak_total + strong_total) - strong_change * strong_total) / (
            weak_total
        )
        frequency[in_basin & strong] *= 1 + strong_change
        frequency[in_basin & ~strong] *= 1 + weak_change
    if np.any(frequency < 0):
        raise ValueError("climate scaling made a frequency negative")
    return replace(events, frequency=frequency)


def intensity_and_frequency(events: Events, scenario: Scenario) -> Events:
    """Scale every wind by Knutson's mean-intensity change and every rate by the all-storm one.

    The variant Jewson warns can double count, kept because ARA's own runs change storm
    intensity as well as frequency (its white paper, Sec. 2).
    """
    frequency = events.frequency.copy()
    speed = np.ones(events.wind.shape[0])
    for basin in np.unique(events.basin):
        rows = events.basin == basin
        speed[rows] = 1 + knutson_percent("intensity", scenario, str(basin), events.years) / 100
        frequency[rows] *= 1 + knutson_percent("cat05", scenario, str(basin), events.years) / 100
    wind = sparse.csr_matrix(events.wind.multiply(speed[:, None]))
    return replace(events, wind=wind, frequency=frequency)
