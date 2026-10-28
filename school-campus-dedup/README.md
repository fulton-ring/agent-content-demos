# Which co-located school records are one physical site?

Public school point layers often show several points on one campus: a high school and the small academies that
share its buildings, or a group of charter schools at one address. Anyone counting schools as *places* (say,
sensitive sites near a pollution source) wants them merged, but merging everything within some distance also
merges the school across the street. This spike measures how well distance, S2 cells, building footprints,
OpenStreetMap school grounds, aerial imagery and a decision model
([Jev](https://openrouter.ai/docs/guides/community/jev)) tell the two apart, against two published answer keys.

## How to run it

Everything is in one marimo notebook, [`campus_dedup.py`](campus_dedup.py).

```bash
export OPENROUTER_API_KEY=...   # Jev and the comparison chat model are called through OpenRouter
./run.sh                        # needs uv; first run ~35 min and ~$4 of model calls, later runs ~2 min and $0
```

Read it as a notebook with `uv run marimo edit campus_dedup.py`. Downloads and cached model answers go to `data/`
(not committed), results to `output/`. It needs about 12 GB of memory (the Los Angeles footprints).

## The data

All public, fetched at run time.

| Source | What we use |
|---|---|
| [HIFLD Next](https://hifld.publicenvirodata.org) Public Schools (from NCES) | 101,279 records in the 50 states and DC, found through the portal's API |
| NCES Common Core of Data 2022–23, via the [Urban Institute Education Data API](https://educationdata.urban.org/documentation/) | state school IDs (to join the answer keys) and charter flags, NY and CA |
| [NYC DOE 2019–20 School Locations](https://data.cityofnewyork.us/d/wg9x-4ke6) | **answer key 1**: `primary_building_code` per school; same code = same building |
| [LAUSD School Campuses and Schools](https://maps.lacity.org/lahub/rest/services/LAUSD_Schools/MapServer) | **answer key 2**: the district's campus polygons and its own school points |
| [Overture Maps](https://docs.overturemaps.org/) buildings, release 2026-10-21.0 | footprints in each region's bounding box |
| OpenStreetMap `amenity=school` areas, via [QLever](https://qlever.dev) | school-ground outlines |
| [Census Bureau batch geocoder](https://geocoding.geo.census.gov/geocoder/) | each school's reported address, geocoded independently of its HIFLD point |
| [USGS National Map](https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer) imagery | an aerial chip of each pair, both points marked |

A **candidate pair** is two records within 150 m of each other, or with the same street address in the same city
(ignoring room, floor, annex or trailer). The regions with a key are New York City (1,283 pairs, 1,152 with an
answer) and Los Angeles County (327 pairs, 83 with an answer). Each key is split by a hash into a *tune* half,
which sets thresholds, and a *test* half, which scores them.

## Results (from one clean `./run.sh`)

**No record is a copy.** Every NCES ID in the layer appears once; each record is a separate school with its own
enrollment. Deduplication here means giving co-located records a shared `site_id`, not deleting rows.

**The problem is large.** Nationally 23,333 candidate pairs involve 27,789 records (27% of the layer). 14,111 pairs
share a street address, and in 3,572 of those the two points are more than 150 m apart.

**HIFLD's points are often off.** For NYC schools in both files, HIFLD's point is a median 29 m from the DOE's,
but the 90th percentile is 106 m and the 95th 485 m (`output/hifld_point_offset_nyc.csv`).

**So distance alone is not safe** (`output/same_site_by_distance.csv`, NYC key). Of pairs 1–10 m apart, 18% are in
different buildings; of pairs 50–100 m apart, 27% are in the same building.

**S2 cells behave like a distance cut with edges** (`output/s2_split.csv`). Of pairs within 10 m of each
other, 19% fall in different level-18 cells (~38 m) and 68% in different level-20 cells (~10 m).

**Each signal on the NYC test half** (549 pairs, `output/triage.csv`). "Plain" means merge when the rule says yes.
"Decided" means the pairs a method merges or keeps apart automatically at thresholds set on the tune half for ≥97%
precision; the rest go to review.

| Method | Plain precision | Plain recall | Decided | Wrong among decided |
|---|---:|---:|---:|---:|
| Distance ≤ 50 m | 0.81 | 0.82 | 0% | – |
| Same S2 cell, level 18 | 0.83 | 0.51 | 0% | – |
| Same Overture building | 0.81 | 0.84 | 0% | – |
| Same OSM school grounds | 0.80 | 0.71 | 0% | – |
| Same street address | 0.99 | 0.98 | 64% | 5 of 349 |
| Geocoded addresses (any cut) | 0.97 | 0.93 | 61% | 7 of 333 |
| Jev: records, point distance, footprint and grounds flags | 0.81 | 0.88 | 38% | 5 of 208 |
| Jev: the same + aerial image | 0.81 | 0.87 | 43% | 8 of 238 |
| Jev: the same + distance between address geocodes | 0.89 | 0.99 | 85% | 9 of 468 |
| **Jev: the pair described in words, no map points** | 0.94 | 0.99 | **91%** | 10 of 498 |
| Gemini 3.8 Flash: records, flags and image | 0.88 | 0.98 | 11% | 3 of 62 |

The geometry signals all trust HIFLD's point. Pairs whose points share a building are often schools on different
streets. The address each school reports is the strongest single signal, but a rule can only merge.

Jev does best when the pair is **described in words**. Each school gets its type, charter and virtual status,
district, website, Census-matched address, and the OSM school grounds its address falls in. The pair gets how the
addresses relate (identical, same address with a different unit, same street, different streets) and roughly how
far apart they geocode. It decides 91% of the test pairs, keeps 179 apart with 2 wrong, and merges 319 with 8 wrong.

On the Los Angeles test half (48 pairs), that variant decides 67% with 1 error, and the geocode rule 77% with
1 error. That key is too small to rank them.

**Calibration** (`output/calibration.csv`, `output/calibration.png`, all keyed pairs).

| Model | Brier | ECE | AUC | Cost per pair |
|---|---:|---:|---:|---:|
| Jev, records and flags | 0.152 | 0.158 | 0.905 | $0.00003 |
| Jev, + image | 0.168 | 0.143 | 0.888 | $0.00010 |
| Jev, + address geocodes | 0.063 | 0.059 | 0.976 | $0.00003 |
| Jev, described in words | 0.040 | 0.026 | 0.982 | $0.00003 |
| Gemini 3.8 Flash, + image | 0.099 | 0.085 | 0.933 | $0.0031 |

Jev's probabilities are only usable once thresholds are tuned. The words variant has the lowest ECE, but most of
its pairs sit near 0 or 1; in between it is not calibrated (pairs scored 0.3–0.6 are mostly different sites). Its
thresholds have to come from a labelled sample, as [TypeSafe's guidance](https://docs.typesafe.ai/confidence) says.
Running it on all 23,333 national pairs would cost about $0.82 (`output/national_cost.csv`); the geocoder is free.

**Sites** (`output/school_sites.csv`, `output/site_summary.csv`). With the tuned thresholds of the words variant,
NYC's 1,868 records become 1,417 sites, and 124 pairs (169 records) are left for review. Los Angeles has 2,250
records and 2,144 sites, but no keep-apart threshold could be set from its small key, so 191 pairs go to review.

## What didn't work, and what this doesn't show

- **The wording of Jev's state moves the result.** An earlier version of the words variant gave a unit suffix
  ("-TRAILER 30", "-12TH FL") as "different streets". It decided 98.5% of a slightly different test half.
  Describing units properly gave 90%: some pairs the key calls different (a trailer, an annex, a charter school
  with its own building code) now score about 0.98, which pushes the merge threshold above that band. We stopped
  changing the wording there, because each change we kept for scoring better would be tuning to the test set.
- **Jev's answers vary between runs, and weak variants' thresholds with them.** Rerun from scratch, the words
  variant decided 90.0% and then 91%; Jev on records and flags decided 62% and then 38%, because a few answers near
  its threshold moved the tuned cut. Pick thresholds from more labelled pairs than this, and pin the model version.
- **The aerial image made Jev worse.** Image requests run in Jev's long-context mode, which TypeSafe says is less
  accurate. The imagery is also coarse at campus scale.
- **The chat model** ranked better than Jev given the same flags (AUC 0.93) but worse than Jev described in words,
  at ~100× the cost per pair. Its stated probabilities cluster at a few values, so in NYC only 11% of pairs cleared
  97%. It was not given the words state.
- **Some "errors" are the key's conventions.** NYC gives a separate building code to a trailer, an annex, or a
  charter school on another floor of an office tower, even at the same street address. "Same campus" is looser
  than the key, so true error rates are lower than the table shows.
- **The NYC key is from 2019–20** and HIFLD's source from 2022–23. We drop schools whose house number changed;
  some other moves will remain.
- **The 150 m radius misses big campuses.** A school with its own street number more than 150 m from its campus
  partners is never compared. A campus polygon from OSM could widen the search there.
- **Closed schools stay in.** HIFLD carries records for schools that have since closed; nothing here detects that.
  A state directory (California's [CDE file](https://www.cde.ca.gov/ds/si/ds/pubschls.asp), for one) can.
- **The keyed regions are two big cities.** Rural districts, where one building often holds the elementary, middle
  and high school under separate IDs, are not measured.
- **We didn't separate the geocodes from the instruction** that map points are sometimes misplaced.
- **No OCR was needed.** Every source here is machine-readable.

## Licences

HIFLD Next and NCES data are US government works. NYC Open Data and LAUSD GIS are published for public use. Census
geocodes and USGS imagery are public domain. Overture buildings and OSM are
[ODbL 1.0](https://opendatacommons.org/licenses/odbl/): `output/pairs.csv` includes flags derived from them
(`same_building`, `same_osm_grounds`, building areas, OSM ground names), so it is ODbL, © OpenStreetMap contributors
and © Overture Maps Foundation. `output/school_sites.csv` holds only HIFLD fields and site IDs.

## What we looked at first

[Splink](https://moj-analytical-services.github.io/splink/) for probabilistic record linkage (suited to many noisy
fields; here the deciding evidence is spatial and comes from outside the records), Placekey (address-based, US POIs, needs an API key), and NCES's EDGE geocode
documentation (it derives points from the reported address, with no campus field). We used DuckDB's
`spatial` and community `geography` (S2) extensions, GeoPandas, rapidfuzz, the Census geocoder, OpenRouter's
Decisions API and marimo, and wrote no matcher beyond those.
