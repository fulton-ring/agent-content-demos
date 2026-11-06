# Data dictionary: county grid-exposure index

`outputs/county_grid_exposure.csv` and `.parquet`, written by `grid_exposure.py` (`./run.sh`). One row per county
or county equivalent in the 50 states and DC (3,144 rows, Census 2024 boundaries). Counts only: the table has no
coordinates, names or lists of individual substations.

**Substations** are those derived from HIFLD Next Transmission Lines v1.0.0 line ends, as in
`us-substations-verified/` (taps dropped; voltage is the highest of the lines that end there). They miss about one
in six of OpenStreetMap's 230 kV+ substations (`outputs/coverage_gaps.csv`).

**Blank** means suppressed by the rule below, never "no data". A county with no substations has 0, not blank.

## Columns

| Column | Type | Meaning |
|---|---|---|
| `fips` | text | 5-digit county FIPS (Census 2024) |
| `county`, `state` | text | County name and two-letter state code |
| `few_substations` | true/false | The county has 1 or 2 substations of 230 kV+. If true, every count in the row is blank |
| `subs_230kv` | integer | Substations of 230 kV and up |
| `subs_345kv` | integer | Substations of 345 kV and up (a subset of `subs_230kv`) |
| `geomag_high_230kv` | integer | 230 kV+ substations whose nearest USGS survey site within 100 km has a once-per-century geoelectric field of 3 V/km or more |
| `geomag_low_230kv` | integer | ...whose nearest site within 100 km is below 3 V/km |
| `geomag_unrated_230kv` | integer | ...with no survey site within 100 km (all of AK and HI, much of the Southeast and Texas). Unrated is not low |
| `geomag_high_345kv`, `geomag_low_345kv`, `geomag_unrated_345kv` | integer | The same for 345 kV+ |
| `geomag_high_share_230kv`, `geomag_high_share_345kv` | number | `geomag_high_*` divided by the band's total (unrated included in the denominator) |
| `coastal_flood_rating` | text | FEMA Future Risk Index projected risk rating, coastal flooding, mid-century higher warming (`CFLD_MID_HIGHER_PRISKR`) |
| `wildfire_rating` | text | Same, wildfire (`WFIR_MID_HIGHER_PRISKR`) |
| `heat_rating` | text | Same, extreme heat, LOCA2 95th-percentile version (`EXHT_L95_MID_HIGHER_PRISKR`) |
| `hurricane_rating` | text | Same, hurricane (`HRCN_MID_HIGHER_PRISKR`) |
| `inland_flood_rating` | text | FEMA National Risk Index v1.20 (December 2025) county risk rating, inland flooding (`IFLD_RISKR`). Today, not projected: the FRI has no inland flood |
| `<hazard>_high_230kv`, `<hazard>_high_345kv` | integer | The band's count if the county's rating for the hazard is Relatively High or Very High, else 0. Hazards: `coastal_flood`, `inland_flood`, `flood` (either flood rating high), `wildfire`, `heat`, `hurricane` |

Ratings are FEMA's text: Very Low, Relatively Low, Relatively Moderate, Relatively High, Very High, plus No Rating,
Not Applicable (no exposure, such as coastal flood inland) and Insufficient Data. `no rating row` means the county
isn't in FEMA's file: Connecticut's nine planning regions, which replaced its counties in 2022, have no FRI row
(28 substations of 230 kV+); they do have NRI v1.20 inland flood ratings.

## The suppression rule

Every group of substations a reader can count from a row, directly or by subtracting one published number from
another, has 0 or at least 3 members. In order:

1. A county with 1 or 2 substations of 230 kV+ publishes only `few_substations = true`.
2. `subs_345kv` is published only if it and `subs_230kv - subs_345kv` are each 0 or 3+.
3. The 230 kV+ geomagnetic split is published only if its three classes are each 0 or 3+.
4. The 345 kV+ split is published only if `subs_345kv` is, its three classes are each 0 or 3+, and, if step 3 is
   published, the three 230-344 kV classes are each 0 or 3+.
5. `<hazard>_high_*` follows its band count.

A whole split is blanked, never one cell. `outputs/suppression_report.csv` counts the rows each step changed, and
`outputs/suppression_test.csv` records the test (every grouping derivable from each row checked against the true
counts; no count column with exactly one blank county, so national totals can't recover a blanked county).

## Sources and licence

- HIFLD Next Transmission Lines v1.0.0 (public domain, US government data preserved by PEDP).
- USGS geoelectric hazard: Lucas, Love, Kelbert, Bedrosian and Rigler (2020), *Space Weather* 18,
  [doi:10.1029/2019SW002329](https://doi.org/10.1029/2019SW002329), site values from the paper's
  [CSV at commit `856374c`](https://github.com/greglucas/GeoelectricHazardPaper2019/blob/856374c4aa0a96f149915712d5b7cc3e017d1507/code/geoelectric_100year.csv).
- FEMA NRI Future Risk Master Datasheet (12/05/2024), from `fulton-ring/nri-future-risk` at `c5cc0d6`; FEMA NRI
  v1.20 counties from FEMA's ArcGIS Online service; Census 2024 county boundaries. US federal works.
- The table itself is released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): credit Fulton Ring
  and link this folder. OpenStreetMap (via Overture) is used only to measure the coverage gap and is not in the
  table.
