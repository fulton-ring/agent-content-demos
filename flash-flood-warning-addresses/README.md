# Matching flash-flood warnings to the addresses at risk

On June 9, 2026, NWS Louisville's 10:22 AM flash flood warning (LMK FF.W.0021, 722 sq mi) covered Lanesville, Indiana, but named only Louisville-area towns. This spike asks whether public terrain data could have turned that polygon into a ranked list of the buildings and road crossings likely to flood first. If it could, the places that actually flooded should land near the top.

**Short answer: not well enough to rely on.** Inside the town, terrain ranking catches about four times as many observed places in its top 25 and top 50 as random order would. But that is only 3 of 14 places in its top 25 of 473 candidates, and those 3 are two spots: a pair of survey points 21–27 m from the creek, and the Methodist church. In the 7 × 6.7 km area around the town (2,247 candidates), 1 m HAND puts none of 15 places in its top 25. Most misses are street and yard points away from any mapped creek. That is the rainfall-driven flooding NOAA says terrain maps don't represent.

## How to run it

```bash
./run.sh            # needs uv; about 5 minutes and 0.9 GB of downloads and cached rasters the first time
```

`run.sh` runs `notebook.py` as a script (`uv run notebook.py`). To read it with its outputs, use `uv run marimo edit notebook.py`. Downloads and intermediate rasters are cached in `$FFW_CACHE` (default `~/.cache/flash-flood-warning-addresses`). Results go to `results/`.

## Data (all public, downloaded at run time, nothing committed)

| Layer | Source |
|---|---|
| Warning polygon and text | IEM VTEC archive (`json/vtec_event.py`, `geojson/vtec_event.py`) |
| Answer key: survey points | NWS LMK flood survey KMZ, `flood_survey06092026.kmz` (locations and times, no depths) |
| Answer key: named places | IEM local storm reports and news (WLKY, WDRB), geocoded to Indiana address points |
| Structures | FEMA/ORNL USA Structures feature service (production date 2020) |
| Address points | Indiana GIO `Address_Points_of_Indiana_2025` (released March 2025) |
| Roads | Census TIGER/Line 2025 |
| Bridges and culverts | National Bridge Inventory, BTS NTAD (June 2025) |
| Streams | NHD High Resolution, HUC8 05140104 (2023) |
| Elevation | 3DEP 1 m DEM from the 2017 Indiana statewide QL2 lidar |
| 10 m HAND | NOAA OWP HAND-FIM 4.9.9.0 (April 2026), CIROH public mirror |

Every layer predates the storm.

## What the notebook does

1. Counts structures, addresses and road segments inside the polygon and inside Lanesville's town limits.
2. Computes 1 m HAND (height above nearest drainage) with WhiteboxTools: breach road embankments at stream crossings, breach depressions, `elevation_above_stream`.
3. Scores every structure, by the lowest value under its footprint, and every road–stream crossing, by its road surface. It does this three ways: 1 m HAND, OWP's 10 m HAND, and straight-line height above the nearest creek.
4. Takes an observed place's rank to be the best rank of any candidate within 30 m. It counts places in the top 25, 50 and 100, reports the median rank, and compares with the number expected from random order.
5. Labels each miss with a likely reason, maps the result (`results/map.png`) and writes `results/summary.json`.

## Results (from a clean run on 2026-10-20)

**Inside the warning:**

| | Whole warning | Lanesville town |
|---|---|---|
| Structures | 290,813 | 455 |
| Address points (Indiana only; the Kentucky side, including Louisville, isn't covered) | 19,459 | 403 |
| Road segments | 14,663 | 65 |

**Answer key.** The KMZ has 13 points tagged `Lanesville2026`. 12 are in Lanesville, and one is in Corydon, which we drop. We add 3 named places: the Methodist church, the school's track and ball field, and SR 62 at the Floyd County line. That gives 15 places at 11 distinct spots, 14 of them inside the town.

**Where observed places land.** In the table, "No match" counts places with no structure or crossing within 30 m. "Random" is the number expected in the top *K* if the candidates were shuffled.

| Scope | Ranking | Top 25 | Top 50 | Top 100 | No match | Median rank |
|---|---|---|---|---|---|---|
| Town (473 candidates, 14 places) | 1 m HAND | 3 | 6 | 6 | 4 | 36 |
| | 10 m OWP HAND | 3 | 6 | 8 | 4 | 27 |
| | Height above creek | 0 | 3 | 6 | 4 | 68 |
| | *Random* | *0.7* | *1.4* | *2.7* | | |
| Area (2,247 candidates, 15 places) | 1 m HAND | 0 | 2 | 3 | 5 | 121 |
| | 10 m OWP HAND | 3 | 3 | 6 | 5 | 87 |
| | Height above creek | 0 | 0 | 0 | 5 | 342 |
| | *Random* | *0.2* | *0.3* | *0.6* | | |

**What the town's 1 m HAND ranking misses (8 of 14 places), with the likely reason:**

- 4 have no structure or crossing within 30 m. They are survey points in streets and yards, so no building or crossing list can contain them.
- 2 are more than 100 m from any mapped stream: the school track and ball field, and a survey point 129 m from a creek. They rank 199th and 201st, about 7 m above their drainage.
- 2 are within 100 m of a stream but 3.6 m above it. They rank 113th and 115th, so the water rose that far or came another way.

None of the misses sits in a closed depression of 0.3 m or more, so the ponding explanation isn't supported here. 8 of the 12 survey points are within 6 m of a road centerline (`results/observed_places.csv`), including all 4 with no candidate. What the surveyors marked most was water in the streets, which a list of buildings can't hold.

**Ties.** Ten town candidates have exactly 0 m in OWP's 10 m HAND, which is where the church and the creek-side cluster sit. They share rank 5.5, so the 10 m ranking's lead at the top comes from cells too coarse to separate them. In the area ranking, 47 candidates tie at 0 m and share rank 24, so the 10 m ranking's 3 area places in the top 25 come entirely from that tie. The church ranks exactly 25th by 1 m HAND, so the town's top-50 count is the sturdier figure.

**Road–stream crossings.**

| | Crossings | With an NBI bridge or culvert within 30 m | Blocked in the bare-earth DEM |
|---|---|---|---|
| Lanesville town | 17 | 3 | 5 |
| 7 × 6.7 km area | 95 | 5 | 39 |

"Blocked" means road fill stands more than 1 m above the creek bed on both sides. That is a digital dam, which a culvert would open. Only 5 of the area's 95 crossings have an inventoried structure, so for the other 90 there is no public record of how water gets under the road.

**Run time and cost:** 4 min 50 s from an empty cache on 4 cores. $0.

## What it doesn't show

- **Overall accuracy.** The answer key shows only where flooding was seen. A high-ranked building that didn't flood can't be told apart from one nobody surveyed.
- **A general result.** This is one event, one town and 11 distinct spots. The counts are small enough that one cluster of survey points moves the totals by three.
- **Whether water reaches a place.** There is no rainfall, discharge or hydraulic model. HAND only orders places by height above a creek.
- **SR 62's real closure point.** It wasn't reported. We use the TIGER county-line crossing, which has no candidate within 30 m.

## What didn't work

- **pysheds.** It left pits after resolving flats, so 34% of the area and 13% of the town's candidates got no HAND. We replaced it with WhiteboxTools' `whitebox-workflows` wheel; the standalone WhiteboxTools binary download is blocked here.
- **WhiteboxTools HAND** is still missing for 23% of the study area's cells (none in town). 75 of the area's 2,247 candidates have no 1 m value and rank last.
- **OWP's own bucket** is Requester Pays. The CIROH mirror serves the same files anonymously. Release 4.9.9.0 stores HAND as int16 millimetres, which we checked against the 2024 float copy.
- **NHDPlus HR map service.** It timed out, so we used the NHD HR HU8 file. It has the same flowlines without stream order.
- **Storm report coordinates** are rounded to about 1 km, too coarse to score against. Named places are geocoded from their addresses instead.

## Before building

- We checked WhiteboxTools, pysheds, OWP's precomputed HAND and the NHDPlus HR services, and used the first that worked for each step.
- The only code written for this spike is the joins and the scoring.
