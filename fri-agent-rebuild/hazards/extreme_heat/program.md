# Extreme heat: rebuild FEMA's NEX hazard multipliers

Goal: reproduce the county columns `EXHT_N95_<scenario>_HM` and `EXHT_N99_<scenario>_HM` of
FEMA's Future Risk Index (four scenarios each: MID/LATE x LOWER/HIGHER). LOWER is SSP2-4.5 and
HIGHER is SSP5-8.5. You edit `pipeline.py`; nothing else.

## What FEMA's Technical Documentation (Dec 2024, Section 6) says

- Source: NASA NEX-GDDP-CMIP6, model MPI-ESM1-2-HR, SSP2-4.5 and SSP5-8.5. Historical period
  1976-2005, mid-century 2036-2065, late-century 2070-2099.
- "Utilizing the daily minimum recorded temperatures, or tasmins, historical 95th and 99th
  percentiles are produced." The percentiles are "calculated using historically observed daily
  minimum temperatures over a 30-year period from 1976-2005 at a ... 30-arcsecond resolution for
  ... NEX, before being aggregated at the county level."
- "Daily average temperature projections and daily average relative humidity projections can be
  used to produce projected Heat Index Values." For NEX the event thresholds are: tasmin above the
  95th (or 99th) percentile observed, and heat index above 298 K (Lu and Romps 2022).
- "The projected number of extreme heat events is then calculated by summing the number of heat
  event-days that exceed both the nth percentile and the heat index threshold."
- "First the HM is produced by dividing the projected number of days by the historically observed
  number of days exceeding the nth percentile."
  HM = MAX(1, projected # of days with minimum temperature over nth percentile /
  historical # of days with minimum temperature over nth percentile).
- Spatial processing: NetCDFs converted to rasters in ArcGIS, then a "raster-vector intersect tool
  ... uses the attributes of the raster cell to directly calculate the proportion of the cell value
  within each county."
- The general HM floor: HM = MAX(1, anticipated / historical benchmark).

## What we know about the data you get

- `inputs.daily(variable, scenario, period)`: float32 (days, cells); `tasmin`, `tasmax`, `tas` in
  deg C, `hurs` in % (daily mean relative humidity). NaN where the cell has no land data. NEX files here are 0.25 degree (the
  documentation says 30 arcsec; FEMA probably used a different product or resampling).
- `inputs.county_weights()`: sparse (counties x cells) intersection areas in km^2, and the FIPS
  index. `inputs.cell_coordinates()` gives cell lat/lon.
- The published N95 multipliers range from 1.0 to 9.1 (late-century higher), N99 from 1.0 to 39.

## Open questions (numbered so agents can split them)

1. Is the historical denominator "days over the nth percentile" (about 5% or 1% of all days by
   construction) or "days over the percentile AND over the heat index threshold"?
2. Which heat index formula and which temperature go into it (daily mean `tas`, or `tasmin`)? Is
   the 298 K threshold applied to the heat index in Kelvin as written? Lu and Romps' extended heat
   index differs from the NWS Rothfusz regression.
3. Order of operations: count event days per cell and then area-average the counts per county, or
   average the temperatures per county first and then count? Or ratio per cell, then average?
4. Percentile definition: per cell over all days of the 30 years, or of warm-season days only, or
   per calendar day window? Strict or non-strict exceedance?
5. How should counties with zero historical event-days be handled (the published HM is never
   blank)?
6. Anything else the log suggests: look at which states and columns have the largest errors.

## Note from the person running the loop (added after round 4)

The loop stalled at a training metric of 0.207 for three rounds, so a person added two things:

- `tasmax` (daily maximum temperature) is now available. It was missing before only because we
  skipped downloading it; FEMA's text says "daily average temperature" for the heat index, but
  that has not been tested against alternatives.
- What the current best gets wrong, from training states only: N95 correlates at 0.97 and N99 at
  0.81. Multipliers are too low in the Northeast (NH, NY, VT, PA about 0.75-0.8x FEMA) and,
  for N99, in OK and AR (0.64x), and too high for N99 in KY, TN, VA (1.3-1.5x). The pattern
  points at how strict the heat index filter is in humid versus cooler places, and at how the
  99th percentile is defined.
