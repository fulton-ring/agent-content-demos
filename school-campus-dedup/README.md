# Which co-located school records are one physical site?

Public school point layers often show several points on one campus: a high school and the small academies that
share its buildings, or a group of charter schools at one address. Anyone counting schools as *places* (say,
sensitive sites near a pollution source) wants them merged, but merging everything within some distance also
merges the school across the street. This spike measures how well distance, S2 cells, building footprints,
OpenStreetMap school grounds, aerial imagery and a decision model
([Jev](https://openrouter.ai/docs/guides/community/jev)) tell the two apart, against two published answer keys.

Everything is in one marimo notebook, [`campus_dedup.py`](campus_dedup.py).

## How to run it

```bash
export OPENROUTER_API_KEY=...   # Jev and the comparison chat model are called through OpenRouter
./run.sh                        # needs uv; first run ~30 min and ~$4 of model calls, later runs ~90 s and $0
```

To read it as a notebook: `uv run marimo edit campus_dedup.py`. Downloads and cached model answers go to `data/`
(not committed), results to `output/`. About 8 GB of free memory is enough.

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

A **candidate pair** is two records within 150 m of each other, or with the same street address in the same city.
The regions with a key are New York City (1,271 pairs, 1,142 with an answer) and Los Angeles County (327 pairs, 83
with an answer). Each key is split by a hash into a *tune* half, which sets thresholds, and a *test* half, which
scores them.

## Results (from one clean `./run.sh`)

**No record is a copy.** Every NCES ID in the layer appears once; each record is a separate school with its own
enrollment. Deduplication here means giving co-located records a shared `site_id`, not deleting rows.

**The problem is large.** Nationally 23,317 candidate pairs involve 27,783 records (27% of the layer). 14,026 pairs
share a street address, and in 3,556 of those the two points are more than 150 m apart.

**Distance alone is not safe** (`output/same_site_by_distance.csv`, NYC key). Of pairs 1–10 m apart, 18% are in
different buildings; of pairs 50–100 m apart, 27% are in the same building.

**S2 cells behave like a distance cut with edges** (`output/s2_split.csv`). Of pairs within 10 m of each
other, 19% fall in different level-18 cells (~38 m) and 68% in different level-20 cells (~10 m).

**Each signal on the NYC test half** (`output/triage.csv`). "Plain" means merge when the rule says yes. "Decided"
means the pairs a method merges or keeps apart automatically at thresholds set on the tune half for ≥97% precision.
The rest go to review.

| Method | Plain precision | Plain recall | Decided | Wrong among decided |
|---|---:|---:|---:|---:|
| Distance ≤ 50 m | 0.81 | 0.83 | 0% | – |
| Same S2 cell, level 18 | 0.83 | 0.52 | 0% | – |
| Same Overture building | 0.81 | 0.85 | 0% | – |
| Same OSM school grounds | 0.80 | 0.72 | 0% | – |
| Same street address | 0.99 | 0.91 | 58% | 2 of 317 |
| Geocoded addresses (any cut) | 0.97 | 0.93 | 61% | 7 of 330 |
| Jev, text | 0.81 | 0.89 | 62% | 9 of 340 |
| Jev, text + aerial image | 0.81 | 0.88 | 44% | 9 of 242 |
| **Jev, text + address geocodes** | 0.89 | 1.00 | **87%** | 7 of 475 |
| Gemini 3.8 Flash, text + image | 0.90 | 0.97 | 0% | – |

The geometry signals all trust HIFLD's point. In NYC, 11% of HIFLD points are more than 100 m from where the DOE
places the same school, so pairs on "the same building" are often schools on different streets. The address each
school reports is the strongest single signal. Jev given the independent address geocodes decides the most pairs,
and it is the only method that also keeps pairs apart with confidence (167 of the 475).

On the Los Angeles test half (48 pairs) the same Jev variant decides 63% with 1 error, and the geocode rule 77% with
1 error. That key is too small to rank them.

**Calibration** (`output/calibration.csv`, `output/calibration.png`, all keyed pairs).

| Model | Brier | ECE | AUC | Cost per pair |
|---|---:|---:|---:|---:|
| Jev, text | 0.148 | 0.152 | 0.907 | $0.00003 |
| Jev, text + image | 0.163 | 0.136 | 0.892 | $0.00010 |
| Jev, text + address geocodes | 0.062 | 0.066 | 0.981 | $0.00003 |
| Gemini 3.8 Flash, text + image | 0.099 | 0.087 | 0.933 | $0.0030 |

Jev ranks pairs well but its raw probabilities are not calibrated: with geocodes, pairs it scores 0.3–0.6 are the
same site only about 3–20% of the time. Its thresholds have to be tuned on a labelled sample, as
[TypeSafe's guidance](https://docs.typesafe.ai/confidence) says. Running the best variant on all 23,317 national
pairs would cost about $0.75 (`output/national_cost.csv`); the geocoder is free.

**Sites** (`output/school_sites.csv`, `output/site_summary.csv`). With the tuned thresholds, NYC's 1,868 records
become 1,434 sites; 158 pairs (236 records) are left for review. Los Angeles has 2,250 records and 2,139 sites, but
no keep-apart threshold could be set from its small key, so 190 pairs go to review.

## What didn't work, and what this doesn't show

- **The aerial image made Jev worse.** Image requests run in Jev's long-context mode, which TypeSafe says is less
  accurate. The imagery is also coarse at campus scale.
- **The chat model** ranked better than Jev on text or image (AUC 0.93) but below Jev with geocodes, at ~100× the
  cost per pair. Its stated probabilities cluster at a few values, so in NYC it never cleared 97% in either direction.
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
- **We didn't separate the geocode from the instruction.** The best Jev variant got both the geocoded distance and
  a sentence saying points are sometimes misplaced; which one did the work isn't tested.
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
