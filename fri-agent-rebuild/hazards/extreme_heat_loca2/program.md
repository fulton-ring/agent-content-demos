# Extreme heat (LOCA2): rebuild FEMA's LOCA2 hazard multipliers

Goal: reproduce the county columns `EXHT_L95_<scenario>_HM` and `EXHT_L99_<scenario>_HM` of
FEMA's Future Risk Index (MID/LATE x LOWER/HIGHER). LOWER is SSP2-4.5 and HIGHER is SSP5-8.5. You
edit `pipeline.py`; nothing else.

## What FEMA's Technical Documentation (Dec 2024, Section 6) says

- Source: LOCA2 (Localized Constructed Analogs v2), MPI-ESM1-2-HR, 6 km, SSP2-4.5 and SSP5-8.5,
  daily minimum temperature. Historical 1976-2005, mid-century 2036-2065, late 2070-2099.
- "Utilizing the daily minimum recorded temperatures, or tasmins, historical 95th and 99th
  percentiles are produced", from "historically observed daily minimum temperatures over a
  30-year period from 1976-2005 at a 6-km ... resolution ... before being aggregated at the
  county level."
- LOCA2 has no humidity, so instead of a heat index "a temperature value of 296.22 K was chosen as
  the LOCA2 threshold". Table 12 lists the LOCA2 thresholds as the 95th or 99th percentile and
  "Temperature > 296.22 K".
- "The projected number of extreme heat events is then calculated by summing the number of heat
  event-days that exceed both the nth percentile and the heat index threshold."
- HM = MAX(1, projected # of days with minimum temperature over nth percentile / historical # of
  days with minimum temperature over nth percentile).
- Spatial processing: NetCDFs converted to rasters in ArcGIS; a raster-vector intersect tool "uses
  the attributes of the raster cell to directly calculate the proportion of the cell value within
  each county."

## What we know about the data you get

- `inputs.loca2_histogram(scenario, period)`: for each LOCA2 cell that overlaps a CONUS county,
  the histogram of daily tasmin over the 30-year period in 0.1 deg C bins (-10 to 40 deg C, with
  open-ended bins below and above), plus a last row counting days with no data. Daily values are
  not available, so seasonal or calendar-window percentiles cannot be computed.
- `inputs.loca2_county_weights()`: sparse (counties x cells) intersection areas in km^2 and the
  FIPS index, in the same cell order.
- Published L95 multipliers range from 1.0 to 8.5 (late-century higher, median 2.4); more than
  half the counties sit at exactly 1.0 in the other three scenarios. L99 ranges from 1.0 to 36.

## What we learned from the NEX version of this hazard

With NEX data, dividing by the historical number of days over the percentile (without the
heat-index condition) beat dividing by days over both thresholds. The NEX rebuild still runs low
in the Northeast and, for the 99th percentile, in Oklahoma and Texas.

## Open questions (numbered so agents can split them)

1. Is the 296.22 K floor applied to the historical denominator too, or only to projected days?
2. Should the floor be applied per day (tasmin > max(percentile, 296.22 K)) or does "exceeds both"
   mean something else, e.g. comparing the cell's percentile itself with 296.22 K?
3. Order of operations: per-cell counts then county average (as now), per-cell ratios then county
   average, or county-average histograms first?
4. Why are so many published L95 values exactly 1 outside late-century higher? Which counties are
   floored, and what in the method makes them so?
5. Anything else the log suggests: look at which states and columns have the largest errors.
