# Can HIFLD Next facilities be matched to OpenStreetMap and Overture, so each gets a GERS ID?

[HIFLD Next](https://hifld.publicenvirodata.org) preserves the federal HIFLD layers, but its point layers have no
link to OpenStreetMap or [Overture Maps](https://overturemaps.org). This spike matches five of them to Overture
places and buildings (which carry [GERS IDs](https://docs.overturemaps.org/gers/)) and to OSM, then uses the match
to find HIFLD records that are wrong and facilities the open maps are missing. Issue
[#91](https://github.com/fulton-ring/agent-content-demos/issues/91).

Everything is in one marimo notebook, [`crosswalk.py`](crosswalk.py). `hand_check_chips.py` draws the imagery
behind the hand check.

## How to run it

```bash
./run.sh            # needs uv; first run ~30 min (mostly reading Overture buildings from S3), later runs ~1 min
./run.sh --chips    # also draws the 250 aerial-imagery chips behind hand_check.csv (data/chips/, not committed)
```

To read it as a notebook: `uv run marimo edit crosswalk.py`. It needs about 12 GB of free memory for the buildings
pass. Downloads go to `data/` (not committed); results to `output/`.

## The data

All public, fetched at run time.

| Source | What we use | Version |
|---|---|---|
| [HIFLD Next](https://hifld.publicenvirodata.org/api) | Hospitals v1.1.0; Fire and EMS Stations, Local Law Enforcement Locations, Public Schools, Power Plants v1.0.0. GeoParquet URLs found through its API (dataset → STAC versions → collection assets) | release `1704edb3` |
| [Overture Maps](https://docs.overturemaps.org/) | `places` by category, `base/infrastructure` power plants, `buildings` (ID, bounding box, source) | 2026-09-23.0 |
| OpenStreetMap | `amenity=hospital`, `amenity=fire_station` + `emergency=ambulance_station`, `amenity=police`, `amenity=school`, `power=plant`, through the [QLever](https://qlever.dev) SPARQL endpoint | planet of 2026-09-21 |

We keep the 50 states and DC (201,013 records). Overture places has no real power-plant category, so for power
plants the Overture side is `base/infrastructure` `class = plant`, which Overture takes from OSM.

## Method, briefly

- **Same kind, near, same name.** For each HIFLD record we take every same-kind Overture place and OSM feature
  within 2 km. OSM areas (campuses, school grounds, plant fences) are measured to their bounding box, so a point
  inside is 0 m away. Names are normalised (abbreviations expanded, generic words like "school" or "fire station"
  dropped, different numbers never match) and scored with rapidfuzz; 85+ is a name match.
- **Buildings.** The Overture building whose bounding box contains the point, or the nearest within 50 m. On
  Connecticut, where we read the real footprints, 1,863 of 1,899 points inside a box (98%) are inside the
  footprint and 1,885 (99%) within 10 m of it.
- **Hand check.** A seeded random sample of 50 *HIFLD-only* records per layer (no same-kind feature within 250 m on
  either side), each viewed on Esri imagery at two zooms and labelled in [`hand_check.csv`](hand_check.csv).

## Results (from one clean `./run.sh`)

**Match rates** (`output/match_rates.csv`, chart in `output/match_rates.png`), % of HIFLD records:

| Layer | Records | Overture ≤50 m | ≤250 m | name ≤250 m | OSM ≤50 m | ≤250 m | name ≤250 m | Building ≤50 m | HIFLD-only |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Hospitals | 8,254 | 68.3 | 86.3 | 68.3 | 84.3 | 87.4 | 69.9 | 96.4 | 405 |
| Fire and EMS stations | 51,930 | 55.6 | 59.2 | 52.9 | 53.9 | 56.2 | 42.6 | 98.7 | 12,264 |
| Local law enforcement | 23,299 | 52.6 | 63.8 | 55.2 | 37.8 | 44.8 | 36.6 | 99.2 | 6,479 |
| Public schools | 101,279 | 67.8 | 93.4 | 78.5 | 80.6 | 86.7 | 64.0 | 98.1 | 3,407 |
| Power plants | 16,251 | 54.1 | 57.2 | 49.1 | 62.5 | 65.7 | 56.0 | 47.8 | 5,558 |

**The crosswalk.** 151,339 of 201,013 records (75%) get a *high*-confidence match (a name match within 250 m on
at least one side), and 96–99% of the four building-type layers get an Overture building GERS ID (power plants 48%:
solar and wind farms aren't buildings). `output/crosswalk_hospitals.csv` is committed; the full
`output/crosswalk.csv.gz` (~20 MB) is written by the run.

**Hand check of HIFLD-only records** (`hand_check.csv`):

| Layer | Exists, unmatched | Misplaced | Closed | Not built | Unclear |
|---|---:|---:|---:|---:|---:|
| Hospitals | 23 | 3 | 15 | – | 9 |
| Fire and EMS stations | 28 | 3 | 0 | – | 19 |
| Local law enforcement | 15 | 2 | 2 | – | 31 |
| Public schools | 10 | 4 | 3 | – | 33 |
| Power plants | 16 | 3 | 11 | 9 | 11 |

**Estimates** (`output/stale_estimate.csv`): the hand-checked shares applied to each layer's HIFLD-only pool.

| Layer | Stale or misplaced HIFLD records (95% range) | Real facilities missing from both OSM and Overture |
|---|---|---:|
| Hospitals | 146 (98–202) | ~186 |
| Fire and EMS stations | 736 (253–1,989) | ~6,900 |
| Local law enforcement | 518 (204–1,221) | ~1,900 |
| Public schools | 477 (237–892) | ~680 |
| Power plants | 2,557 (1,832–3,313) | ~1,800 |

HIFLD's own status flags 946 power plants retired or cancelled and 404 hospitals closed (or closed in Overture),
all still in the layers (`output/trouble_flags.csv`). 1,162 schools, 1,466 police and 1,378 fire records have no
same-kind feature within 250 m but a name match 250 m–2 km away, a sign one side has the point in the wrong place.
`output/duplicate_pairs.csv` lists same-name records within 50 m of each other (112 hospital pairs, 358 school pairs).

**By facility type** (`output/match_by_type.csv`, `facility_type` in the crosswalk): not everything in a HIFLD
layer is what OSM or Overture calls that kind of facility. General acute care hospitals get a high-confidence
match 88% of the time and are HIFLD-only 3% of the time; military records 62% and 19% (many are base outpatient
clinics, "Medical Groups"), psychiatric 72% and 9%. Special-jurisdiction police (campus, transit, parks) are
HIFLD-only 63% of the time, against 25% for local police departments.

**The other direction** (`output/other_only.csv`): OSM has 4,572 fire stations, 2,739 police and 1,072 hospitals
with no HIFLD record nearby. Overture's counts are much larger (36,927 "hospitals") because its business listings
call clinics hospitals; see the notebook before using them.

**Run time:** see the last cell's output; a cold run from a clean checkout took 28 minutes, a cached one about a minute.

## What the spike shows

All three expectations hold. **Match rates differ sharply by layer**: hospitals and schools match 95–97% within
250 m, fire, police and power plants 66–76%. **The match finds stale HIFLD records**, most in power plants (about
2,600 records retired, cancelled, never built or misplaced) and hospitals (about 150, a third of the unmatched),
fewer elsewhere. **It finds facilities to contribute**: about 6,900 fire and EMS stations, 1,900 police
stations and 1,800 power plants exist on the ground but are in neither OSM nor Overture. Most unmatched fire and
police records are real stations the open maps lack, not HIFLD errors.

## What didn't work, and what this doesn't show

- **Overpass reset** again; QLever's SPARQL endpoint returned all of US OSM in under a minute per tag.
- **QLever is live, not pinned.** These numbers come from its 2026-09-21 OSM planet. When QLever moves to a newer
  planet, the HIFLD-only pools and the seeded hand-check sample will drift, and the estimates will still apply the
  labels in `hand_check.csv`. Re-label before trusting a rerun on a newer planet.
- **Reading Overture buildings is the cost.** The lower 48 is 180 million buildings, 24 GB. With 4 DuckDB threads
  it ran at 3 MB/s; with more threads than cores it ran at ~30 MB/s, but the first try ran out of memory, so it now
  goes in eight longitude strips. We read bounding boxes, not footprints (checked on CT above).
- **Centroids undercounted OSM.** Our first pass measured to OSM centroids: OSM ≤50 m was 51% for hospitals and 30%
  for power plants. Measuring to the area's bounding box raised them to 84% and 63%.
- **Unclear labels are high** for police (31/50) and schools (33/50): offices in larger buildings, online and
  alternative programs. The estimates count only clear labels, so they're floors. The labels were made by Claude
  subagents viewing every image; we spot-checked some. 14 of the 15 "closed" hospitals rest on HIFLD's own
  `CLOSED` status with the building still standing.
- **Wrong kind of facility.** HIFLD's `TYPE` is HIFLD's own label, so a nursing home or surgery centre filed as a
  hospital still says "hospital". Names flag a few (13 surgery centres); catching the rest needs an outside list
  such as CMS's Provider of Services file, which this spike doesn't use.
- **Matched isn't verified.** A record within 250 m can still be on the wrong building; we didn't sample matches.
- **Overture places categories are noisy** (clinics as hospitals, private schools as schools), so Overture-only
  counts are ceilings. OSM-only schools (52,418) include private schools, which HIFLD's layer leaves out.
- **We propose, we don't upload.** OSM's [import guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines)
  need community discussion and a documented plan before any bulk edit.

## Licences

HIFLD Next republishes US government data (public domain). Overture places are
[CDLA-Permissive 2.0](https://cdla.dev/permissive-2-0/); Overture buildings and infrastructure, and OSM, are
[ODbL 1.0](https://opendatacommons.org/licenses/odbl/). A crosswalk that includes OSM IDs, Overture building or
plant IDs, or distances measured to OSM shapes is, as in `us-substations-verified/`, a Derivative Database under
OSMF's guidelines, so the full `crosswalk.csv.gz` would be published as ODbL with "© OpenStreetMap contributors"
and Overture attribution. The committed slice `output/crosswalk_hospitals.csv` is such a file: it is ODbL 1.0,
© OpenStreetMap contributors and © Overture Maps Foundation, and anything built from it stays ODbL. The OSM names
and distances in `hand_check.csv` and `output/hand_check_sample.csv` come from the same sources. A file with only HIFLD ID → Overture *place* GERS ID, distance and name score could go
out under CDLA-Permissive 2.0 with attribution, no share-alike.

## What we looked at first

DuckDB's httpfs and spatial extensions for Overture (as in `hifld-grid-gaps/`), Overpass and then QLever for OSM,
GeoPandas' `dwithin` join, rapidfuzz for names and marimo for the notebook. We wrote no matcher beyond those.
