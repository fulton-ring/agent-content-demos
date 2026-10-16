# A public hurricane layer for the Future Risk Index: method

This is how we compute county and census-tract hurricane hazard multipliers (HM) for FEMA's
four Future Risk Index scenarios without Applied Research Associates' (ARA) data, and why we
publish our own rather than reusing FEMA's. Every step is a published method or a published
dataset; the only choices we make are which of them to use, and each choice is listed below.

## Why not FEMA's published multipliers

FEMA's published hurricane multipliers are about 2.0 almost everywhere, and the evidence says
that level is not a climate signal. We can't reproduce it, and the people who made the input
don't support it.

1. **The level is uniform where the climate signal shouldn't be.**
   - In three of the four scenarios, 94-97% of counties FEMA covers sit between 1.9 and 2.1.
   - The medians are 1.995 (mid-century, lower warming), 2.011 (mid, higher), 1.973 (late,
     lower) and 2.190 (late, higher).
   - The level is the same in inland Vermont, the Florida Keys and Oklahoma.
   - Late century under lower warming comes out below mid-century under lower warming.
2. **ARA's own published numbers don't give it.** ARA's white paper (2022) publishes its
   climate-conditioned landfall rates by region and category. Through FEMA's own Equation 11
   they give 1.06-1.23 for 2050 under RCP 8.5. FEMA published 1.99-2.04 for the same regions and
   scenario.
3. **The published climate science doesn't give it.**
   - Knutson et al. (2020), the standard assessment, converted to FEMA's scenarios (Jewson
     2021), gives county medians of +3% to +16%.
   - STORM's four high-resolution climate models (2050, SSP5-8.5) give a median of +25%.
   - Only the 90th-percentile Knutson case for late century under RCP 8.5 reaches about 2.
4. **FEMA's numbers don't behave like FEMA's documented formula.**
   - Equation 12 is HM = max(1, projected / historical). It should give values near 1 with a
     pile-up at exactly 1.
   - The published values have no value between 1 and 1.26.
   - A model that adds 1 to the ratio fits FEMA's level within 2-4% on every public route. This
     is consistent with the projected frequencies having included the historical ones, but we
     can't confirm that without ARA's file.
5. **The pattern between counties doesn't follow any hurricane signal we could find.**
   - Rank correlation of FEMA's values with today's hurricane hazard is −0.22 to 0.31.
   - With every public climate route it is −0.19 to 0.18.
   - The largest values (up to the cap of 10) sit at the inland edge of ARA's coverage, where a
     few rare simulated storms decide the ratio.

The evidence is in `README.md` (the spike) and `results/`. FEMA's technical document says the
ARA file is available from FEMA-NRI@fema.dhs.gov. We have not seen it, and it may explain the
level. Until it does, we treat FEMA's hurricane multipliers as unexplained and don't reuse them.

## What the layer is

Projected annual loss = NRI hurricane expected annual loss (EAL) × hazard multiplier. This is
FEMA's FRI Equation 12. It has two parts, which we refresh separately:

- **The economic part:** NRI's hurricane EAL, by county or tract. It is refreshed whenever FEMA
  publishes a new NRI release (v1.19 in March 2023, v1.20 in December 2025). The FRI applied its
  multipliers to v1.19.
- **The climate part:** our multiplier. It is refreshed only when one of its inputs changes: a
  new STORM release, a new Knutson-style assessment, or new climate-model tracks such as RAFT.

## Method, step by step

| Step | What we do | Source | Our choice and why |
|---|---|---|---|
| 1. Today's storms | 10,000 years of synthetic North Atlantic tracks resampled from IBTrACS 1980-2018 | STORM v4, Bloemendaal et al. (2020) *Sci. Data*, [doi:10.4121/12706085.v4](https://doi.org/10.4121/12706085.v4), CC0 | A synthetic catalogue reaches far more inland counties than 125 years of best tracks (1,189 against 948 counties with Cat 1 wind at 5,000 years), and it ranks NRI's county hurricane loss better (Spearman 0.92 against 0.76). |
| 2. Wind at each place | Peak 1-minute sustained wind at 10 m per storm, Holland (2008) profile, hourly track steps | CLIMADA 6.1 (`TropCyclone.from_tracks`, model `H08`), Aznar-Siguan & Bresch (2019) | CLIMADA's default. It is open terrain with no surface-roughness reduction, so only rankings and ratios carry over, not loss levels. |
| 3. Category frequencies | At each point, the annual frequency of wind reaching Saffir-Simpson Cat 1, 2, 3, 4 and 5 | Saffir-Simpson thresholds (64, 83, 96, 113 and 137 kt) | "Frequency of Category k" is read as wind reaching at least Category k. Counting each storm only in its peak band made no material difference. |
| 4. Intensity | Intensity = F1 + 2·F2 + 4·F3 + 8·F4 + 16·F5 | FRI technical document (FEMA 2024), Eq. 11 | FEMA's weights unchanged. |
| 5. Places | County: mean over 0.25° grid points within 1 km of the county (nearest point if none). Tract: the tract's population-weighted centre. | FRI Sec. 7.2. Census 2020 boundaries and CenPop2020 tract centroids. | FEMA's county rule, with a regular grid standing in for ARA's points, which aren't public. |
| 6. Scenarios | FEMA's lower and higher warming are RCP 4.5 and 8.5; mid and late century are 2050 and 2100 | FRI Table 5, Sec. 7.1 | As FEMA defines them. |
| 7. Climate change | Rescale each storm's rate by its peak category: Cat 4-5 by Knutson's Cat 4-5 frequency change, the rest so that all-storm frequency changes by Knutson's figure. Winds unchanged. | Knutson et al. (2020) *BAMS* [doi:10.1175/BAMS-D-18-0194.1](https://doi.org/10.1175/BAMS-D-18-0194.1); Jewson (2021) *JAMC* [doi:10.1175/JAMC-D-21-0102.1](https://doi.org/10.1175/JAMC-D-21-0102.1), which converts Knutson's +2 °C figures to any baseline, year and RCP; implemented in CLIMADA (`apply_climate_scenario_knu`) | Frequency only, as Jewson (2022, *SERRA*, [doi:10.1007/s00477-021-02142-6](https://doi.org/10.1007/s00477-021-02142-6)) recommends, because changing intensity as well can double count. The baseline is STORM's 1980-2018. |
| 8. Multiplier | HM = max(1, projected / today's intensity) | FRI Eq. 12 | As documented, with no factor of 2. A county or tract with no Cat 1 wind in 10,000 years gets HM = 1, which is how FEMA's own ratings treat its zeros. |
| 9. Range | Steps 7-8 repeated at each published Knutson percentile (5th/10th, 25th, 75th, 90th/95th); we report the median and the lowest and highest | Knutson et al. (2020); CLIMADA pairs the same percentile across variables | Shows how much the answer depends on which climate models are right. |
| 10. Cross-check | STORM's own 2050 SSP5-8.5 tracks from four high-resolution GCMs, through steps 2-4 and 8 | Bloemendaal et al. (2022) *Sci. Adv.*, [doi:10.4121/14237678.v2](https://doi.org/10.4121/14237678.v2) | An independent route from climate-model storms rather than an assessment. It covers one scenario only. |

Nothing here is fitted to FEMA's values or to NRI losses.

## What it doesn't do

- **Wind only, as in the FRI.** Storm surge and rain are not included.
- **No terrain, buildings or defences.** Those live in NRI's EAL, the economic part, which is
  computed with Hazus.
- **No climate-driven change in tracks.** Knutson gives basin-wide changes, so every place in
  the basin gets the same change per storm category. The local pattern comes only from which
  categories reach each place today.
- **The range is model spread, not total uncertainty.** It doesn't include the sampling noise
  of a 10,000-year catalogue in rarely hit counties, or the choice of wind model.
- **Late century has no simulated-track cross-check yet.** RAFT (late century, SSP5-8.5) is #24.

## Results

All numbers come from `./run.sh` (the `hurloss-layer` step) and are in `results/layer/`.

### Counties (`county_multipliers.csv`, `fri_comparison_summary.csv`)

1,241 counties get Cat 1 wind in 10,000 years of STORM; the rest get HM = 1. FEMA's
comparison set is the 2,219 CONUS counties with an NRI hurricane rating; FEMA's 0s count as 1.

| Scenario | FEMA, median | Ours, median (covered counties) | Ours, range of medians (Knutson low to high) | Counties where FEMA's value falls inside our range (covered) |
|---|---|---|---|---|
| Mid-century, lower (RCP 4.5, 2050) | 1.99 | 1.03 | 1.00-1.35 | 2.0% |
| Mid-century, higher (RCP 8.5, 2050) | 2.00 | 1.05 | 1.00-1.52 | 2.0% |
| Late century, lower (RCP 4.5, 2100) | 1.96 | 1.05 | 1.00-1.58 | 2.2% |
| Late century, higher (RCP 8.5, 2100) | 2.09 | 1.13 | 1.00-2.94 | 98.7% |

- **FEMA's values sit outside the whole range of published climate science in three of the four
  scenarios.** Even the most aggressive Knutson percentile tops out at 1.40, 1.60 and 1.67 in
  any county. Only late century under RCP 8.5, at its top percentile, reaches FEMA's level.
- **National projected loss** (counties with a rating, on FEMA's v1.19 baseline of $20.3B a year):

  | Scenario | FEMA | Ours | Ours on NRI v1.20 |
  |---|---|---|---|
  | Mid-century, lower | $40.6B | $20.8B | $12.6B |
  | Mid-century, higher | $41.0B | $21.0B | $12.7B |
  | Late century, lower | $40.5B | $21.1B | $12.7B |
  | Late century, higher | $45.5B | $22.5B | $13.6B |

  The drop from the v1.19 column to the v1.20 column is NRI's own update to today's losses. It
  is not our multiplier.
- **Ratings** (FEMA's fixed bins, same v1.19 baseline): 82-84% of counties keep FEMA's projected
  loss rating and 16-18% drop one bin. None drop two bins and none rise.
- **Pattern:** ours is highest where intense storms already make up a large share of the wind:
  south Florida, the Keys, the Gulf coast. It falls off inland and to the north. FEMA's is flat
  at about 2, with its largest values at the inland edge of its coverage (`map_fema_vs_ours.png`).

### Cross-check with STORM's climate-model storms (`storm_check.csv`)

For 2050 under SSP5-8.5, STORM's four high-resolution GCMs give a county median of 1.25,
against our central 1.05.

- 64% of counties fall inside our Knutson range and 36% above it.
- The two routes don't agree on which counties change most (Spearman 0.02).

The models agree that the change is far below FEMA's 2. They disagree on its size and where it
falls. That disagreement is real uncertainty, and the range should be published with the central
value.

### Census tracts: Florida pilot (`tract_multipliers_FL.csv`, `tract_summary_FL.csv`)

- **Coverage:** all 5,160 Florida tracts get Cat 1 wind. The multiplier runs from 1.02 to 1.04
  (5th-95th percentile) for mid-century lower and from 1.09 to 1.14 for late-century higher.
- **Variation inside a county is small.** The highest tract multiplier in a county is a median
  0.5% above the lowest (1.5% for late-century higher), and at most 3.4%.
- **Tracts add up to the county.** Projected loss summed over tracts (NRI v1.20 tract EAL × tract
  HM) is within 0.3% of the county figure.
- **Tract-level projected loss is technically sound, but nearly all of its detail comes from
  NRI's tract EAL, not from the multiplier.** NRI's tract hurricane EAL fell to a median 0.44
  of its v1.19 value in Florida's v1.20 release.

## Can we go below the county?

**Yes, to census tracts. Most of the value is in the economic part, and the climate part can
safely be the county value.**

- **What makes tracts possible:** parametric wind fields can be evaluated at any point, unlike
  the 25 km climate grids behind the other FRI hazards. So a tract multiplier is the same
  published method, evaluated at the tract's population centre.
- **Why the multiplier barely varies:** Knutson's changes are basin-wide, so within a county the
  multiplier only varies with the mix of storm categories that reach each tract, which changes
  over tens of kilometres. Florida shows 0.5-1.5% typical variation inside a county.
- **What to publish:** tract projected loss = NRI tract EAL × tract HM. Using the county HM
  instead would change the total by under 0.3%. Below tracts (block groups or buildings), the
  inputs would claim more precision than they have.
- **What would make the multiplier itself vary more:** climate-model storms (STORM's GCMs, RAFT)
  carry local changes in where storms go. But their four-model spread is larger than the local
  signal (Spearman 0.02 between routes), so we don't use them for the central value.

## Updating it

- **Each NRI release:** multiply the new county and tract EAL by the existing multipliers. A
  `hurloss-layer` rerun with cached inputs takes about a minute.
- **When an input changes** (a new STORM version, a new Knutson-style assessment, new
  climate-model tracks): rerun everything, about 2.5 hours on 4 cores. Publish both versions'
  multipliers so the change can be traced.
- **If FEMA releases ARA's file:** rerun the spike's comparison against it, and revisit the
  section on why we don't reuse FEMA's values.

