# Data dictionary: `output/batteries.csv` and `output/batteries.parquet`

One row per battery generator (EIA prime mover `BA`) in EIA-860M, September 2026: every operating and planned
battery at a US plant of at least 1 MW combined nameplate capacity, in the 50 states, DC and Puerto Rico. The CSV and
the GeoParquet hold the same rows; the GeoParquet adds a `geometry` point (WGS84, EPSG:4326) at EIA's coordinates.
`batteries.py` writes both. A plant with several battery generators has several rows with the same `eia_plant_id`.

| Column | Meaning |
|---|---|
| `eia_plant_id`, `eia_generator_id` | EIA plant code and generator ID; together they identify the generator |
| `plant_name`, `state`, `eia_county` | As EIA-860M lists them |
| `county_fips_2024`, `county_fips_2020` | County containing EIA's coordinates (the nearest county if the point is just offshore), on Census 2024 and 2020 shapes. They differ only in Connecticut |
| `balancing_authority` | EIA's balancing authority code |
| `stage` | `operating` (EIA-860M Operating sheet) or `planned` (Planned sheet) |
| `eia_status` | EIA's status code. Operating: `OP` operating, `SB` standby, `OA`/`OS` out of service. Planned: `P` planned, no approvals yet; `L` approvals pending; `T` approvals received; `U` under construction, up to half done; `V` under construction, over half done; `TS` built, not yet in commercial operation |
| `mw` | Nameplate power capacity (MW) |
| `mwh` | Nameplate energy capacity (MWh), operating batteries only; empty where EIA has none |
| `year_online`, `month_online` | When it started operating, or, for planned batteries, when EIA says it's planned to |
| `latitude`, `longitude` | EIA's plant coordinates |
| `in_hifld_next` | True if the battery or its plant is on HIFLD Next's Power Plants or Generating Units layer (match 1, 2 or 3 below) |
| `match` | `1 unit in Generating Units` (HIFLD unit ID `<plant code>-<generator id>`); `2 plant code in Power Plants` (the plant is there but this battery isn't listed); `3 HIFLD plant within 1 km` (no ID match, but a HIFLD plant within 1 km of EIA's coordinates); `4 missing from HIFLD Next` |
| `hifld_unit_status` | The unit's status in Generating Units where match 1 holds (HIFLD Next lists some batteries as planned, `P`/`U`/`V`/..., as of 2023) |
| `m_to_hifld_plant` | Distance in metres from EIA's coordinates to the nearest HIFLD Next power plant |
| `nri_hrcn_riskr`, `nri_hwav_riskr` | FEMA National Risk Index (December 2025) county risk rating for hurricane and heat wave: `Very High`, `Relatively High`, `Relatively Moderate`, `Relatively Low`, `Very Low`, `No Rating`, `Insufficient Data`, `Not Applicable` |
| `nri_hrcn_ealr`, `nri_hwav_ealr` | The same for NRI's expected annual loss rating |
| `nri_hurricane_high`, `nri_heat_high` | True where the risk rating is `Very High` or `Relatively High` |
| `fri_hurricane_hm` | Our open hurricane layer's central multiplier, mid-century higher warming (`MID_HIGHER`), from `fri-datasets-map/data/hurricane_by_county.csv`; empty for counties FEMA didn't rate for hurricane |
| `fri_heat_hm` | Our rebuilt extreme-heat multiplier (LOCA2, 95th percentile, `EXHT_L95`), `MID_HIGHER`, from `fri-datasets-map/data/multipliers_by_county.csv`; contiguous US only |
| `fri_hurricane_high`, `fri_heat_high` | True where the multiplier is in the top fifth of US counties (the cut-offs are printed in the notebook); an empty hurricane multiplier counts as not high |

A multiplier scales a county's NRI expected annual loss for the hazard to a projected mid-century loss: 1.5 means
half again. Our multipliers are reconstructions, not FEMA's withdrawn Future Risk Index values; see
[`fri-datasets-map/`](../fri-datasets-map/).

## Sources and licence

- EIA-860M and EIA-860 (US Energy Information Administration), HIFLD Next (preserved public HIFLD layers), FEMA's
  National Risk Index and Census shapes are US government works, not under copyright in the US.
- The FRI multipliers are Fulton Ring's, CC BY 4.0 (see `fri-datasets-map/data/DATA_DICTIONARY.md`).
- The queue tables (`output/queue_battery_by_state.csv`, and the queue row of `output/exposure_mapped_vs_missing.csv`)
  are derived from LBNL's *Queued Up* data file, CC BY 4.0: Lawrence Berkeley National Laboratory and GridTracker.
- This file is released under CC BY 4.0: reuse it with credit to Fulton Ring and a link to this folder.
