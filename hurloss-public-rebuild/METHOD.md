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

LAYER_RESULTS_PLACEHOLDER
