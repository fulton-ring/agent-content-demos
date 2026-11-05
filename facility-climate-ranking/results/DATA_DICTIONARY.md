# Data dictionary

`notebook.py` writes one CSV and one GeoParquet (EPSG:4326 points) per layer:
`hospitals`, `power_plants` and `wastewater`. One row per active facility that landed in a
census tract NRI scores. Facilities left out are counted in `join_report.csv`.

**Licence and sources.** HIFLD Next (public domain US government data), FEMA's National Risk
Index v1.20 (public domain), FEMA's Future Risk Index multipliers and Fulton Ring's rebuild
(`fri-datasets-map/`, see its data dictionary), FEMA's NFHL (hospitals only). Tract and county
scores describe an area, not the building. Read the README's "What it doesn't show" before you
use a rank.

## Columns

| Column | Meaning |
|---|---|
| `layer` | `hospitals`, `power_plants` or `wastewater` |
| `facility_id` | HIFLD `source_ID` (hospitals), EIA `PLANT_CODE` (power plants), `NPDES_ID` (wastewater) |
| `name`, `city`, `state` | As in the HIFLD layer |
| `kind` | Hospital `TYPE`, power plant `PRIM_FUEL` (EIA fuel code), wastewater major/minor status |
| `tract_fips` | 2020 census tract (11 digits) that holds the point, from Census cartographic boundaries |
| `county_fips` | The tract's county as NRI records it (Connecticut keeps its eight pre-2022 counties) |
| `county_fips_hifld` | The county FIPS the HIFLD layer carries, for comparison |
| `RISK_RATNG` | NRI composite risk rating of the tract |
| `lat`, `lon` | The HIFLD point |

Then, for each hazard: inland flood (`IFLD`, prefix `inland_flood`), coastal flood (`CFLD`,
`coastal_flood`), hurricane (`HRCN`, `hurricane`), wildfire (`WFIR`, `wildfire`) and heat wave
(`HWAV`, `heat_wave`):

| Column | Meaning |
|---|---|
| `<CODE>_RISKR` | NRI tract risk rating for the hazard (Very Low to Very High, or No Rating, Insufficient Data, Not Applicable) |
| `<CODE>_EALT` | NRI tract expected annual loss for the hazard, all consequences, USD a year |
| `<hazard>_rate` | What we rank on: the NRI tract annualized loss rate for buildings (`<CODE>_ALRB`), or for population for heat wave (`HWAV_ALRP`). Empty where zero or missing |
| `<hazard>_rank_today` | Rank within the layer by `<hazard>_rate`, 1 = highest; ties broken by `facility_id`. Empty if unranked |
| `<hazard>_top_decile` | Whether `<hazard>_rank_today` is in the top 10% of ranked facilities in the layer |
| `<CODE>_fema_LATE_HIGHER` | FEMA's FRI multiplier for the county, late century, higher warming. Empty where FEMA has none or "No Rating" (not for inland flood) |
| `<CODE>_rebuilt_LATE_HIGHER` | Our rebuild's multiplier (for heat, the LOCA2 95th-percentile version; for hurricane, our open layer's central value) |
| `<hazard>_rank_fema_LATE_HIGHER`, `<hazard>_rank_rebuilt_LATE_HIGHER` | Rank by `<hazard>_rate` × the multiplier; a missing multiplier counts as 1 |

Hospitals only:

| Column | Meaning |
|---|---|
| `nfhl_flood_class` | FEMA NFHL flood zone class at the point: `SFHA` (zones A, V), `shaded X`, `minimal`, `D`, `open water`, `not mapped`; the highest hazard wins where polygons meet |
| `nfhl_zone` | The NFHL `FLD_ZONE` value behind the class |

## Summary files

| File | What |
|---|---|
| `join_report.csv` | Facilities per layer by join status |
| `top100_overlap.csv` | Per layer, hazard, multiplier source and scenario: how many of today's top 100 stay in the top 100 |
| `top_facilities.csv` | Top five per layer and hazard today |
| `known_flood_places.csv` | Share in the flood top decile, all facilities against those in known flood counties and tracts |
| `known_hospitals_check.csv` | `known_hospitals.csv` with whether each hospital ranks in the top decile |
| `hospitals_tract_vs_sfha.csv` | Hospitals by tract flood rating (higher of inland and coastal) and NFHL class |
| `headline.json` | The headline numbers and the run time |
