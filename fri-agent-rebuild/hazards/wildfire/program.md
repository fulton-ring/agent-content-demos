# Wildfire: rebuild FEMA's hazard multipliers

Goal: reproduce the county columns `WFIR_<scenario>_HM` of FEMA's Future Risk Index (MID/LATE x
LOWER/HIGHER). LOWER is SSP2-4.5 and HIGHER is SSP5-8.5. You edit `pipeline.py`; nothing else.

## What FEMA's Technical Documentation (Dec 2024, Section 8) says

- Source: NASA Earth Exchange GDDP-IMPACT Fire Weather Index (Canadian FWI System), "a MME which
  averages several distinct downscaled results", SSP2-4.5 and SSP5-8.5, "aggregated using yearly
  projections over 30-year periods": historical 1976-2005, mid 2036-2065, late 2070-2099.
- LANDFIRE 40 Scott and Burgan Fire Behavior Fuel Models (FBFM40), 30 m.
- "Area-weighted average FWI values are calculated for each Census block by intersecting the NEX
  FWI 25km raster layer with Census block polygon features. FWI values at higher geographic levels
  (i.e., County and Census tract) are also calculated using an area-weighted average of their
  underlying Census blocks."
- Equation 14: HM_WFIR,scenario = (FWI_scenario / FWI_historic) ^ gamma.
- "The coefficient gamma is a constant term (greater than 1) that captures the responsiveness of
  EAL to a proportional change in FWI. This coefficient is derived from a log-log linear regression
  of National Risk Index v1.19 County total EAL values from the lower 48 US States on historic FWI
  values with spatial fixed effects and the proportion of each fuel type present within each census
  block included as additional control variables. The value for gamma is obtained from the
  regression coefficient associated with historic FWI values using maximum likelihood estimation."
- "The PAL is then calculated at the Census block level for each scenario" (so a county's HM is
  an EAL-weighted average of block HMs, not necessarily the HM of the county-average FWI).

## What we know about the data you get

- `inputs.fwi(scenario, period, variable="FWI", ensemble="MME50")`: yearly values, shape
  (years, cells). The portal is missing a few years in each period (23-26 of 30 are present).
  Variables: FWI (annual mean of monthly FWI), FWI_P25/P50/P75/P95, FWI_N15/N30/N45 (days above
  15/30/45), FWI_NP95, FWI_Nmid, FFMC, DMC, DC, ISI, BUI. Ensembles: MME25, MME50, MME75.
- `inputs.county_fuel_shares()`: share of each FBFM40 fuel group per county (nonburnable, grass,
  grass_shrub, shrub, timber_understory, timber_litter, slash_blowdown).
- `inputs.baseline()`: NRI v1.19 county EAL per hazard (`WFIR_EALT`, `HWAV_EALT`, ...) and
  `STATEABBRV` for fixed effects. There is no all-hazard total EAL column; the sum over hazards
  of `*_EALT` is available only for the five Future Risk hazards.
- Published WFIR HMs range from 1.00 to 4.5 (late-century higher, median 2.5), never below 1.

## Open questions (numbered so agents can split them)

1. Which FWI statistic and which ensemble member (MME25/50/75) best matches "a MME which averages
   several distinct downscaled results"?
2. What is "County total EAL": wildfire EAL, or total EAL? Which spatial fixed effects (state,
   FEMA region, none)? How are fuel shares entered? What does this do to gamma (must be > 1)?
3. Aggregation order: ratio of county-mean FWI, or county average of cell-level HMs (closer to the
   block-level calculation)?
4. Does the HM need a floor at 1 or other treatment of decreases?
5. Anything else the log suggests: look at which states and columns have the largest errors.
