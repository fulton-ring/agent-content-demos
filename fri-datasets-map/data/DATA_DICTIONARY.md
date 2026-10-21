# Data dictionary

County datasets comparing FEMA's Future Risk Index (FRI) hazard multipliers with Fulton Ring's
rebuilds. `datasets.py` writes every file here from the committed results of
`fri-agent-rebuild/` and `hurloss-public-rebuild/`, FEMA's master datasheet and two small
public downloads.

A **hazard multiplier (HM)** scales a county's NRI v1.19.0 expected annual loss (EAL) for a
hazard to a projected future loss. FEMA floors published multipliers at 1, except for coastal
flooding (which goes below 1) and a documented code of 0 for "no rating".

**Scenarios** (`scenario`, and the middle part of wide column names):

| Code | Meaning in the FRI |
|---|---|
| `MID_LOWER` | Mid-century (about 2050), lower warming (RCP 4.5 or SSP2-4.5, depending on the hazard's climate data) |
| `MID_HIGHER` | Mid-century, higher warming (RCP 8.5 or SSP5-8.5) |
| `LATE_LOWER` | Late century (about 2100), lower warming |
| `LATE_HIGHER` | Late century, higher warming |

**Hazards** (`hazard`, and the first part of wide column names):

| Code | Hazard | Our values come from |
|---|---|---|
| `DRGT` | Drought | `fri-agent-rebuild`, NEX-GDDP-CMIP6 |
| `WFIR` | Wildfire | `fri-agent-rebuild`, NASA's NEX-GDDP-CMIP6 fire weather index and LANDFIRE fuels |
| `EXHT_L95`, `EXHT_L99` | Extreme heat, LOCA2, 95th and 99th percentile thresholds | `fri-agent-rebuild`, LOCA2 |
| `EXHT_N95`, `EXHT_N99` | Extreme heat, NEX, 95th and 99th percentile thresholds | `fri-agent-rebuild`, NEX-GDDP-CMIP6 |
| `CFLD` | Coastal flooding | `fri-agent-rebuild`, NOAA high tide flooding projections (not a blind rebuild) |
| `HRCN` | Hurricane | `hurloss-public-rebuild`, our open layer (FEMA's method on open storm catalogues; not a rebuild of FEMA's values) |

Missing values are empty cells in CSV and nulls in Parquet. `fips` is the five-digit county
FIPS code as text.

## `multipliers_by_county.csv`

One row per county, hazard and scenario: 3,231 counties × 7 hazards × 4 scenarios.

| Column | Meaning |
|---|---|
| `fips`, `state`, `county` | County, as in FEMA's datasheet |
| `hazard`, `hazard_name` | Hazard code and name (above) |
| `scenario` | Scenario code (above) |
| `fema_hm` | FEMA's published multiplier. Empty where FEMA published none |
| `rebuilt_hm` | Our rebuilt multiplier. Contiguous US only (3,108 counties); empty elsewhere and where a pipeline left a county blank |
| `held_out` | `True` for the 12 held-out states (AZ, CT, GA, IA, ME, MN, NE, NM, OH, RI, TX, WA), whose scores the agents never saw; `False` for training states; empty outside the contiguous US |

## `coastal_flags.csv`

The 137 counties with coastal flood EAL > 0 in NRI v1.19.0 whose FEMA coastal multiplier is 0
in all four scenarios (120) or between 0 and 1 in at least one (17).

| Column | Meaning |
|---|---|
| `fips`, `state`, `county` | County |
| `cfld_eal_v1_19_0` | Coastal flood EAL in NRI v1.19.0 (USD a year), from FEMA's datasheet |
| `cfld_<scenario>_hm` | FEMA's coastal flooding multiplier per scenario |
| `flag` | `zero_all_scenarios` or `between_0_and_1` |
| `cfld_eal_v1_18_1` | Coastal flood EAL in NRI v1.18.1 (November 2021), from FEMA's `NRI_Counties_Prod_v1181_view` service; empty if none |
| `had_loss_v1_18_1` | Whether the county had coastal flood EAL > 0 in v1.18.1 (matched by FIPS) |

## `hurricane_by_county.csv`

One row per county and scenario for the 2,219 counties where FEMA published a hurricane
multiplier, from `hurloss-public-rebuild/results/layer/fri_comparison_by_county.csv`.

| Column | Meaning |
|---|---|
| `fips`, `state`, `county`, `scenario` | County and scenario |
| `fema_hm` | FEMA's published hurricane multiplier |
| `our_hm` | Our central multiplier: FEMA's Eq. 11-12 with no factor of 2, averaged over two storm catalogues (STORM and observed tracks), Knutson et al. (2020) changes, frequency only |
| `our_hm_low`, `our_hm_high` | Our range across both catalogues and every published Knutson percentile |
| `our_covered` | Whether our catalogues put Category 1+ wind on the county; where not, our values are the floor of 1 |
| `fema_within_our_range` | Whether FEMA's value lies between `our_hm_low` and `our_hm_high` |
| `fema_in_2_band` | Whether FEMA's value is between 1.9 and 2.1 |

## `baseline_scores.csv` and `baseline_by_column.csv`

The constant baseline: each column's median FEMA multiplier over training-state counties
(HM = 0 left out), given to every held-out county and scored with `fri_rebuild.scoring`.
`baseline_by_column.csv` has one row per FEMA column, with the scorer's metrics (`same_bin`:
share of counties whose projected loss lands in the same NRI rating bin as FEMA's; `log_mae`:
mean |ln(ours / FEMA's)|; Pearson and Spearman are blank or about 0 for a constant).
`baseline_scores.csv` averages them per hazard, puts the rebuild's held-out scores
(`fri-agent-rebuild/results/rebuild/headline.csv`) beside them, and checks them against the
figures the Draft job worked out by hand on 2026-10-19.

## `counties.parquet`

GeoParquet, one row per county (3,221 with Census 2020 shapes; American Samoa, Guam, the
Northern Mariana Islands and the US Virgin Islands have no shape in the source file and are
left out), in NAD83 (EPSG:4269). Columns:

- `fips` (index), `STATEABBRV`, `COUNTY`, `CFLD_EALT` (NRI v1.19.0 coastal flood EAL), `held_out`
- `<hazard>_<scenario>_FEMA_HM` and `<hazard>_<scenario>_REBUILT_HM` for the seven hazards in
  `multipliers_by_county.csv`
- `HRCN_<scenario>_FEMA_HM`, `HRCN_<scenario>_OUR_HM`, `HRCN_<scenario>_OUR_HM_LOW`,
  `HRCN_<scenario>_OUR_HM_HIGH`
- `cfld_flag`, `cfld_had_loss_v1_18_1` (from `coastal_flags.csv`; empty for other counties)
- `geometry`: Census 2020 cartographic boundary, 1:20,000,000

## Sources

- FEMA, *NRI Future Risk Master Datasheet* (12/05/2024), saved before the FRI was taken down in
  February 2025, from [fulton-ring/nri-future-risk](https://github.com/fulton-ring/nri-future-risk)
  at `c5cc0d6`.
- FEMA, NRI v1.18.1 counties,
  [`NRI_Counties_Prod_v1181_view`](https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/NRI_Counties_Prod_v1181_view/FeatureServer/0)
  on ArcGIS Online.
- US Census Bureau, 2020 cartographic boundary file `cb_2020_us_county_20m`.
- Our values: [`fri-agent-rebuild/`](../../fri-agent-rebuild/) and
  [`hurloss-public-rebuild/`](../../hurloss-public-rebuild/) in this repository, whose READMEs
  list their own inputs.

## Licence

- FEMA's and the Census Bureau's values are works of the US federal government and not under
  copyright in the US (17 U.S.C. § 105).
- Fulton Ring's rebuilt values, hurricane layer, flags and baseline scores are released under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): reuse them freely with credit to
  Fulton Ring and a link to this folder.
- The inputs behind our values keep their own terms, listed in each spike's README.
