# Drought: rebuild FEMA's hazard multipliers

Goal: reproduce the county columns `DRGT_<scenario>_HM` of FEMA's Future Risk Index (MID/LATE x
LOWER/HIGHER). LOWER is SSP2-4.5 and HIGHER is SSP5-8.5. You edit `pipeline.py`; nothing else.

## What FEMA's Technical Documentation (Dec 2024, Section 5) says

- Source: NASA NEX-GDDP-CMIP6, MPI-ESM1-2-HR, SSP2-4.5 and SSP5-8.5, "daily precipitation and
  average temperature". Historical 1985-2014, mid-century 2036-2065, late-century 2070-2099.
- "Monthly SPEI values are obtained by using the 'SPEI' R package with a scale factor of 3 months.
  The Thornthwaite method is used to calculate daily potential evapotranspiration (PET) values using
  monthly mean temperature projections and computing a daily average within each month. SPEI
  values are then computed using 'SPEI' package in R using a log-logarithmic distribution function
  with a 60-year reference period. ... a reference period from January 1950 to December 2010 was
  used to calibrate the parameters of the model."
- Footnote: "monthly PET values were divided by the number of days in each month ... to obtain
  daily average PET values. These daily averages were used to compute daily water balance."
- "A threshold of SPEI <= -1.6 (Extreme Drought per the US Drought Monitor) was selected ... If an
  SPEI value for a given month were to fall below this threshold, each day within the month was
  considered a drought event-day. ... a drought event rate for each location is computed for each
  future risk scenario by dividing total drought event days by the number of days in each 30-year
  scenario."
- "the drought event rate values for each future climate scenario are divided by the historical
  drought event rate value ... a table with HM values for each future climate scenario is converted
  into 0.25x0.25-degree polygon grid. For each future scenario, county level HM values are
  calculated using an area weighted average by intersecting the 0.25x0.25-degree polygon grid with
  county boundaries." Also: "All calculations are performed at the Census tract level and
  aggregated up."
- General floor: HM = MAX(1, anticipated / historical benchmark).

## What we know about the data you get

- `inputs.monthly(variable, scenario)`: monthly means (tas deg C, pr mm/day) 1950-2100, shape
  (months, cells); historical run joined to the scenario run at 2015. NaN over water.
- `inputs.county_weights()`, `inputs.cell_coordinates()` as in the other hazards.
- Published DRGT HMs range from 1.0 to 17.2 (late-century higher, median 5.2) and are never
  blank. 0.3% of counties sit at exactly 1.0 in late-century higher.

## Open questions (numbered so agents can split them)

1. How should cells with zero historical drought days be handled (ratio is infinite)? Drop them
   from the county average, cap them, or add a small rate?
2. Floor first and then average (MAX(1, cell HM) per cell), or average and then floor?
3. Thornthwaite details: the heat index from the calibration period, the whole series, or each
   year; daylight-hours formula; daily-average PET as in the footnote vs monthly totals.
4. SPEI fit details: the R package's log-logistic is the 3-parameter generalized logistic fitted
   by unbiased probability-weighted moments; check edge cases (the 'SPEI' package fixes the
   probability of the lowest values, and handles zero-variance months).
5. Is the event rate the share of drought days, or the count of drought months, or something
   else? Does the ratio of averages vs. average of ratios matter?
6. Anything else the log suggests: look at which states and columns have the largest errors.
