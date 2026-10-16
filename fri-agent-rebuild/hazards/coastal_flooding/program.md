# Coastal flooding: rebuild FEMA's hazard multipliers

Goal: reproduce the county columns `CFLD_<scenario>_HM` of FEMA's Future Risk Index (MID/LATE x
LOWER/HIGHER) for coastal counties. You edit `pipeline.py`; nothing else.

## What FEMA's Technical Documentation (Dec 2024, Section 4) says

- Source: the Interagency Task Force on Sea Level Rise 2022 (Sweet et al. 2022). "The ITF
  leveraged NOAA's High Tide Flooding Probability set to determine the frequency of Minor,
  Moderate and Major Flooding events under a variety of climatological scenarios ... These data
  were provided for each of 187 NOAA Tidal Gauges."
- "The ITF provided high tide flooding probabilities based upon SLR scenarios for the mid-century
  (2050) and late-century (2100). These data were categorized by flooding severity level: Minor
  Flooding Events - 1 to 2 Year Floods (50-100% Annual Chance); Moderate - 10 to 50 Year Floods
  (2-10% Annual Chance); Major - 100 Year Floods (1% Annual Chance)."
- Scenarios: "The Future Risk Index currently presents results for the Intermediate and High SLR
  scenarios, which anticipate 1.0 meters and 2.5 meters in sea level rise respectively." (The 2022
  report's High scenario is 2.0 m by 2100; FEMA's table lists Intermediate High as 2.0 m and High
  as 2.5 m.) LOWER = Intermediate, HIGHER = High is our reading.
- Spatial processing: "Projected high tide flooding event frequencies provided for each of 187
  NOAA tidal gauges are spatially joined to the nearest National Risk Index counties ... a county
  would inherit the information of the closest tidal gauge, based purely on geographic distance."
- Equation 4: SubFAF = Projected CFLD sub-type frequency / Current CFLD sub-type frequency;
  SubProportion = CFLD sub-type EAL / CFLD total EAL. "To adjust frequencies for areas protected
  by levees, these areas are clipped out prior to sub-type frequency computation."
- Equation 5: PAL = EAL x HM, where HM = sum over sub-types of SubFAF x SubProportion.
- No floor at 1 is applied to coastal flooding in the published data (some HMs are exactly 0).

## What we know about the data you get

- `inputs.coastal_tables()`: NOAA tables (see the docstring in inputs.py).
  - `htf_decadal` has projected flood days per year for 110 stations (decades 2020-2100, all five
    2022 scenarios; minor values rounded to 5).
  - `htf_observed` has observed annual counts for 137 stations.
  - `extreme_water_levels` covers all 187 gauges FEMA cites, with return levels (m above MHHW)
    for 0.1- to 100-year return periods. Combined with `sea_level_projections` (cm of relative
    rise per decade and scenario) and `flood_thresholds`, it can produce frequencies for every
    gauge, including those without CO-OPS projections.
- `inputs.county_shapes()` (CONUS counties) and `inputs.baseline()` (NRI `CFLD_EALT`).
- NRI does not publish how a county's coastal flooding EAL splits into minor, moderate and major,
  so SubProportion has to be estimated from public data.
- Published HMs exist for 407 CONUS counties. 109 of them are exactly 0 in every scenario (Great
  Lakes counties and some inland Gulf counties); they are not scored. The rest range up to 22
  (mid-century lower) and 429 (late century). Scoring uses only counties with a published HM
  above 0.

## Open questions (numbered so agents can split them)

1. What is "current" frequency: observed recent counts (which years?), the 2020 decade of the
   projections, or return-period definitions (minor = 1-2 year flood, moderate = 10-50 year,
   major = 100 year)?
2. How should SubProportion be estimated: from current frequencies, from frequency times a
   severity weight, or from return periods?
3. Which gauges: the 110 with CO-OPS projections, or all 187 using the extreme water level
   curves plus sea level rise?
4. How to handle sub-types with zero current frequency (division by zero) and gauges with no data.
5. Anything else the log suggests: look at which states and columns have the largest errors.
