# Can an open flood layer beat FEMA's flood map at finding Harvey's damage?

FEMA's flood map (the NFHL, and its 1%-a-year Special Flood Hazard Area, the SFHA) is slow to update: Harris County's dates from 2007. This spike asks whether a layer built only from open terrain, hydrology and rainfall data ranks places by observed flood damage better than the SFHA does. The test is Harris County, Texas, in Hurricane Harvey (August 2017), at census block group level, the finest unit public damage data allows.

**Short answer: no.** No open layer we built beats the SFHA on any answer key.

- **Static open layers carry almost no signal.** Neither low height above the nearest stream (HAND) nor 3DEP depressions ranks block groups much better than chance. That holds at every cut-off we tried.
- **HAND works only once it is given the flow.** Driven by the National Water Model's simulated Harvey peaks, OWP's HAND flood map *ties* the SFHA on river claims and loses on the other keys. That is an event map drawn with hindsight flows, not a hazard map anyone had beforehand.
- **Its worst errors come from the flows.** NWM ran Buffalo Bayou below the Addicks and Barker dams at 12–18 times its gauged peak, because it doesn't hold water behind the dams.

## How to run it

```bash
./run.sh     # needs uv; first run about 1.5 hours and 1.9 GB of downloads (mostly OpenFEMA); 5–8 minutes after
```

`run.sh` runs `notebook.py` as a script, so every number below comes from code a reader can see. To read it with its outputs, run `uv run marimo edit notebook.py`. Downloads are cached in `$OFL_CACHE` (default `~/.cache/open-flood-layer-vs-nfhl`). Results go to `results/`.

## Data (all public, downloaded at run time, nothing committed)

| What | Source |
|---|---|
| Units | 2010 TIGER block groups, Harris County: 2,144 with land. TIGER 2020 block groups are used to crosswalk NFIP codes. |
| Buildings | USACE National Structure Inventory API, county 48201: 1,454,342 buildings, 1.96 M housing units |
| Baseline | FEMA NFHL county extract `48201C` from the Map Service Center (current; 26% of buildings sit on panels revised after Harvey) |
| HAND | NOAA OWP HAND-FIM 4.9.9.0, CIROH public mirror, 10 HUC8s; 10 m HAND, catchments and rating curves |
| Flows | NWM v3.0 retrospective on AWS: peak flow 25 Aug – 5 Sep 2017 for 3,430 reaches, checked against 47 USGS gauges |
| Depressions | USGS 3DEP 1/3 arc-second DEM; WhiteboxTools `depth_in_sink` |
| Rainfall | NOAA Atlas 14 PFDS, 100-year 24-hour depth at 12 points: 15.1–18.1 in |
| Answer key 1 | OpenFEMA `NfipClaims` v3, Harvey: 42,400 paid claims (cause 2 river 13,816; cause 4 rainfall 19,585). `NfipPolicies` v3: 237,383 policies in force on 25 Aug 2017. |
| Answer key 2 | OpenFEMA `IndividualsAndHouseholdsProgramValidRegistrations` v2, DR-4332: 449,326 registrations, 103,538 with `floodDamage` |

## Method

Every layer scores a block group by the **share of its NSI buildings it flags**:

1. **FEMA SFHA**, and SFHA plus the 0.2% zone.
2. **Low HAND**: the cut-off (3.12 m) is set so it flags exactly the SFHA's share of buildings (8.9%).
3. **HAND-FIM, Harvey flows**: each reach's Harvey peak flow, run through OWP's rating curve, gives a stage. A building is flagged if its HAND is at or below that stage (14.3% of buildings).
4. **3DEP depression ≥ 0.3 m** (0.6% of buildings). Atlas 14 varies too little across the county to rank depressions, so depth alone is used.
5. **HAND-FIM or depression**, and **low HAND or depression**.

The keys are paid claims per policy (all causes, river and rainfall), paid claims per NSI building, and IHP flood-damage registrations per housing unit. We score them with Spearman ρ and AUC for the worst-hit fifth of block groups, using 500 bootstrap resamples. Differences from the SFHA are paired on the same resamples.

## Results (from a clean run on 2026-10-23)

Spearman ρ / AUC per layer and key. ▼ means worse than the SFHA (the 95% interval of the paired difference is below zero); = means no detectable difference. No layer scored ▲. Per-policy keys cover the 1,639 block groups with at least 25 policies, the others 2,135–2,140 block groups.

| Layer | Claims / policy | River claims / policy | Rain claims / policy | Claims / building | IHP flood / unit |
|---|---|---|---|---|---|
| **FEMA SFHA** | **0.38 / 0.71** | **0.35 / 0.71** | **0.34 / 0.68** | **0.45 / 0.77** | **0.34 / 0.69** |
| FEMA SFHA + 0.2% | 0.37 / 0.70 = | 0.35 / 0.70 = | 0.35 / 0.68 = | 0.44 / 0.78 = | 0.34 / 0.70 = |
| OWP low HAND (SFHA's share) | 0.00 / 0.48 ▼ | 0.02 / 0.50 ▼ | 0.00 / 0.47 ▼ | 0.03 / 0.50 ▼ | 0.02 / 0.50 ▼ |
| OWP HAND-FIM, Harvey flows | 0.29 / 0.68 ▼ | 0.33 / 0.72 = | 0.25 / 0.63 ▼ | 0.33 / 0.72 ▼ | 0.19 / 0.65 ▼ |
| 3DEP depression ≥ 0.3 m | 0.12 / 0.53 ▼ | 0.12 / 0.54 ▼ | 0.11 / 0.53 ▼ | 0.07 / 0.54 ▼ | 0.03 / 0.52 ▼ |
| HAND-FIM or depression | 0.31 / 0.69 ▼ | 0.35 / 0.73 = | 0.27 / 0.64 ▼ | 0.34 / 0.74 ▼ | 0.19 / 0.66 ▼ |

The closest result: on river claims, HAND-FIM or depression minus the SFHA is ρ −0.01 (−0.05 to +0.05) and AUC +0.02 (−0.02 to +0.06). The SFHA's own intervals are about ±0.04 on ρ. Full table with intervals: `results/scores.csv`. Chart: `results/scores.png`. Maps: `results/maps.png`.

**Cut-off sweep** (`results/sensitivity.csv`). Static HAND at 0.5–3 m gives ρ of −0.02 to 0.04 against both per-building keys. Only HAND ≤ 8 m, which flags 59% of buildings, reaches 0.20–0.25. Depressions of any depth reach 0.14 against IHP and 0.02 against claims. The SFHA scores 0.45 and 0.34.

**NWM flows vs gauges** (`results/nwm_vs_usgs.csv`). Across 47 gauged reaches, NWM's median Harvey peak is 1.71× the observed peak. Only 51% are within a factor of 2. Buffalo Bayou below Addicks/Barker runs 11.8–17.9× high, and Vince Bayou 0.16×.

**Where layers go most wrong** (`results/worst_block_groups.csv`, IHP key; the reasons are our reading of locations and the gauge table):

- *SFHA misses:* heavily damaged block groups with no SFHA. They sit near the Addicks reservoir pool (29.84, −95.63, where 46% of buildings fall in a ≥ 0.3 m depression), in east Houston (29.84, −95.20 to −95.27) and along Clear Creek (29.52–29.54, −95.18). None is a 1% riverine floodplain.
- *SFHA false alarms:* mostly SFHA block groups with insured, little-damaged homes, such as 29.71, −95.44, with 289 policies and 2 claims.
- *HAND-FIM false alarms:* the Buffalo Bayou corridor (29.75–29.78, −95.48 to −95.50), fully flagged because NWM's flows there are 12× too high.
- *HAND-FIM misses:* south-east block groups (29.59–29.65, −95.20 to −95.23) near Vince and Berry Bayous, where NWM under-ran the flows.

**Run time and cost:** 5–8 minutes with a warm cache on a 4-CPU machine. From an empty cache, the clean-checkout run took about 1.5 hours across three restarts (two FEMA connection failures and one container restart), and resumed from the cache each time. Most of that time went on about 430 OpenFEMA queries, some of which take 70 seconds a page, plus the 1.3 GB NSI GeoJSON. Cache: 1.9 GB. Cost: $0, since every source is free and nothing uses a paid service.

## Refresh speed

| Layer | How fast it could refresh |
|---|---|
| FEMA NFHL | Countywide restudy every 10–20 years, plus letters of map revision. Harris County's MAAPnext preliminary data came out in February 2026, and effective maps are not expected before 2028. |
| OWP HAND | New HAND-FIM releases each year (4.9.9.0 in April 2026), built from 3DEP and the NWM hydrofabric with OWP's open pipeline |
| NWM flows | Operational analysis and forecasts every hour, which the NWS flood inundation maps already use. This spike uses the retrospective. |
| 3DEP depressions | Whenever new lidar reaches 3DEP. Recomputing for the county took about a minute here. |
| Atlas 14 | Texas volume 2018; Atlas 15 is in progress |

## What it doesn't show

- **No lot- or parcel-level claim follows.** Everything here is block-group shares and rates.
- **Answer-key biases.** NFIP policies cluster in the SFHA because of the mandatory-purchase rule, and take-up outside it is low, which favours the SFHA on per-policy keys. IHP counts registrations, not measured damage. People had to apply, renters register, and insured owners often don't.
- **Vintage mismatches.** The NFHL, NSI (2022), 3DEP (republished 2026) and HAND are all current, not August 2017. 17% of claims and 19% of policies carry 2020 block-group codes, which we crosswalk to 2010 through NSI buildings.
- **Harvey exceeded the 1% event** across much of the county. A 1% map is not expected to contain it, so these are rankings, not hit rates.
- **One event, one county.** A second event (Imelda 2019 or Tax Day 2016) is split off as #111.
- **No 1%-flow HAND map.** OWP's recurrence flows sit in a requester-pays bucket, and the retrospective archive is too big to fit 100-year flows from in this spike.

## What we looked at first

We reused the OWP HAND handling from `flash-flood-warning-addresses/`. We used OpenFEMA, NWM Zarr, WhiteboxTools, geopandas and rasterio rather than writing our own. FEMA's NFHL map service dropped large pages, so we use the county extract from the Map Service Center. OpenFEMA times out on deep pages and `$inlinecount`, so queries go one day (IHP) or three days (policies) at a time.
