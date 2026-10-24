# Matching flash-flood warnings to the addresses at risk

On June 9, 2026, NWS Louisville's 10:22 AM flash flood warning (LMK FF.W.0021, 722 sq mi) covered Lanesville and Corydon, Indiana, but named only Louisville-area towns. This spike asks whether public terrain data could have turned that polygon into a ranked list of the buildings and road crossings likely to flood first. If it could, the places that actually flooded should land near the top.

**Short answer: sometimes, and which terrain product works depends on the town.**

- **Lanesville**, where the rain fell: the 1 m and 10 m HAND rankings catch about four times as many observed places in their top 25 and top 50 as random order would. That is still only 3 of 14 places in the top 25 of 473 candidates, and most misses are street and yard points away from any mapped creek.
- **Corydon**, downstream, where Little Indian Creek carried that runoff into downtown: NOAA's 10 m HAND puts 9 of 11 observed places in its top 25 of 1,531 candidates, against 0.4 expected at random. Our 1 m HAND puts none there. Its top 25 are houses on small unnamed channels, where NOAA's HAND reads about 30 m.
- **The gap is mostly the stream network, not the resolution.** The same 1 m HAND, measured only against the National Water Model streams that OWP's HAND uses, puts 5 of Corydon's 11 places in its top 25 and 10 in its top 100 (OWP: 9 and 10). In Lanesville it beats both other HAND rankings: 6 in the top 25 against 3, median rank 18 against 27 and 36.

Both answer keys are small. Lanesville has 11 distinct spots and Corydon 7, and Corydon's all lie within 350 m of each other downtown.

## How to run it

```bash
./run.sh            # needs uv; about 16 minutes and 1.6 GB of downloads and cached rasters the first time
```

`run.sh` runs `notebook.py` as a script once per town (`FFW_SITE=lanesville`, then `FFW_SITE=corydon`). To read it with its outputs, use `FFW_SITE=corydon uv run marimo edit notebook.py`. Downloads and intermediate rasters are cached in `$FFW_CACHE` (default `~/.cache/flash-flood-warning-addresses`). Results go to `results/<town>/`.

## Data (all public, downloaded at run time, nothing committed)

| Layer | Source |
|---|---|
| Warning polygon and text | IEM VTEC archive (`json/vtec_event.py`, `geojson/vtec_event.py`) |
| Answer key: survey points | NWS LMK flood survey KMZ, `flood_survey06092026.kmz`: 21 points, 12 in Lanesville and 9 in Corydon (locations and times, no depths) |
| Answer key: named places | IEM local storm reports and news (WLKY, WDRB, WAVE), geocoded to Indiana address points |
| Structures | FEMA/ORNL USA Structures feature service (production date 2020) |
| Address points | Indiana GIO `Address_Points_of_Indiana_2025` (released March 2025) |
| Town limits | Census TIGERweb places: Lanesville 1842048, Corydon 1815256 |
| Roads | Census TIGER/Line 2025 |
| Bridges and culverts | National Bridge Inventory, BTS NTAD (June 2025) |
| Streams | NHD High Resolution, HUC8 05140104 (2023). Both towns are in this HUC8, so they share one file. |
| Elevation | 3DEP 1 m DEM from the 2017 Indiana statewide QL2 lidar. The tiles are picked from the study box. |
| 10 m HAND | NOAA OWP HAND-FIM 4.9.9.0 (April 2026), CIROH public mirror, HUC8 05140104 |
| NWM streams | The same release's `nwm_subset_streams.gpkg`: the NHDPlus V2 streams OWP built its HAND on |

Every layer predates the storm.

**Named places.** Lanesville: the Methodist church (LSR), the school's track and ball field, and SR 62 at the Floyd County line (computed, since no closure point was reported). Corydon: The Alibi Bar and Hey Elmer Print and Design, both named by WDRB and WAVE as flooded downtown, and the Summit Springs subdivision from the LSR. MLS listings put Summit Springs on Crescent Hill Dr NE, just outside the town limits. The report doesn't say which houses flooded, so that place is all 83 address points on the street, and it counts as found if any of them is.

## What the notebook does

1. Counts structures, addresses and road segments inside the polygon and inside the town limits.
2. Computes 1 m HAND (height above nearest drainage) with WhiteboxTools: breach road embankments at stream crossings, breach depressions, `elevation_above_stream`. It runs the last step three times on the same conditioned DEM, against three networks: every kept NHD HR flowline, named creeks only (a GNIS name), and the NHD HR flowlines that run along OWP's NWM streams (at least 80% of the flowline within 60 m). The NWM lines themselves sit a median 11–15 m off the lidar channels, too far to burn into a 1 m DEM.
3. Scores every structure, by the lowest value under its footprint, and every road–stream crossing, by its road surface. It does this five ways: the three 1 m HANDs, OWP's 10 m HAND, and straight-line height above the nearest creek.
4. Takes an observed place's rank to be the best rank of any candidate within 30 m. It counts places in the top 25, 50 and 100, reports the median rank, and compares with the number expected from random order.
5. Labels each miss with a likely reason. It compares what each HAND ranking puts in its top 25, maps the result (`results/<town>/map.png`) and writes `results/<town>/summary.json`.

## Results (from a clean run on 2026-10-24)

**Inside the warning:** 290,813 structures, 19,459 Indiana address points and 14,663 road segments. The Kentucky side, including Louisville, has no address points in this layer.

| | Lanesville town | Corydon town |
|---|---|---|
| Structures | 455 | 1,486 |
| Address points | 403 | 1,467 |
| Road segments | 65 | 186 |

**Where observed places land.** In the table, "No match" counts places with no structure or crossing within 30 m. "Random" is the number expected in the top *K* if the candidates were shuffled. Town rankings leave out the place outside the town limits: SR 62 for Lanesville, Summit Springs for Corydon.

| Scope | Ranking | Top 25 | Top 50 | Top 100 | No match | Median rank |
|---|---|---|---|---|---|---|
| Lanesville town (473 candidates, 14 places) | 1 m HAND | 3 | 6 | 6 | 4 | 36 |
| | 10 m OWP HAND | 3 | 6 | 8 | 4 | 27 |
| | Height above creek | 0 | 3 | 6 | 4 | 68 |
| | 1 m HAND, named creeks | 3 | 3 | 8 | 4 | 60 |
| | 1 m HAND, NWM streams | 6 | 6 | 8 | 4 | 18 |
| | *Random* | *0.7* | *1.4* | *2.7* | | |
| Lanesville area, 7 × 6.7 km (2,247 candidates, 15 places) | 1 m HAND | 0 | 2 | 3 | 5 | 121 |
| | 10 m OWP HAND | 3 | 3 | 6 | 5 | 87 |
| | Height above creek | 0 | 0 | 0 | 5 | 342 |
| | 1 m HAND, named creeks | 0 | 3 | 3 | 5 | 139 |
| | 1 m HAND, NWM streams | 3 | 6 | 6 | 5 | 37 |
| | *Random* | *0.2* | *0.3* | *0.6* | | |
| **Corydon town (1,531 candidates, 11 places)** | 1 m HAND | 0 | 1 | 5 | 1 | 118 |
| | 10 m OWP HAND | 9 | 9 | 10 | 1 | 8 |
| | Height above creek | 0 | 0 | 0 | 1 | 500 |
| | 1 m HAND, named creeks | 5 | 10 | 10 | 1 | 18.5 |
| | 1 m HAND, NWM streams | 5 | 9 | 10 | 1 | 24.5 |
| | *Random* | *0.4* | *0.7* | *1.4* | | |
| **Corydon area, 7 × 7.3 km (4,405 candidates, 12 places)** | 1 m HAND | 0 | 0 | 1 | 1 | 509 |
| | 10 m OWP HAND | 8 | 9 | 9 | 1 | 15 |
| | Height above creek | 0 | 0 | 0 | 1 | 1,173 |
| | 1 m HAND, named creeks | 5 | 5 | 10 | 1 | 51 |
| | 1 m HAND, NWM streams | 5 | 5 | 10 | 1 | 65 |
| | *Random* | *0.5* | *0.9* | *1.3* | | |

**What the town's 1 m HAND ranking misses, with the likely reason:**

| Reason | Lanesville (8 of 14) | Corydon (6 of 11) |
|---|---|---|
| No structure or crossing within 30 m (a street or yard point) | 4 | 1 |
| More than 100 m from a mapped stream | 2 | 1 (Hey Elmer, 115 m) |
| Within 100 m of a stream but too high above it to make the top 100 | 2 (3.6 m) | 4 (2.8–3.3 m) |
| In a closed depression of 0.3 m or more | 0 | 0 |

**Why the two HAND products disagree in Corydon.** Our 1 m HAND measures height above every kept NHD High Resolution flowline. In the Corydon box, 832 of 959 of those are unnamed. OWP measures height above the National Water Model's coarser network. Of the 1 m ranking's top 25 in Corydon, all 25 sit at 0 m (25 town candidates tie there), only 2 are nearest a named creek, and their median OWP HAND is 29.7 m. These are houses beside headwater channels on the hillsides. Of OWP's top 25, 18 are nearest a named creek (mostly Little Indian Creek), with a median 1 m HAND of 2.2 m. The water came down Little Indian Creek from Lanesville, so the product that measures height above that creek finds downtown. In Lanesville the two top 25s are closer: the 1 m ranking's has a median OWP HAND of 2.6 m, and the two rankings score about the same.

**Network or resolution? Mostly network.** Measuring the 1 m HAND against a coarser network moves it most of the way to OWP's result while keeping the 1 m DEM. The two coarse networks are a sixth to a quarter of the full one by length (Corydon: 28 km named, 32 km along NWM, 188 km in all; Lanesville: 26, 26 and 108 km).

| Town top 25 | 1 m HAND, all streams | 1 m, named creeks | 1 m, NWM streams | 10 m OWP |
|---|---|---|---|---|
| Corydon: also in OWP's top 25 | 3 | 15 | 14 | 25 |
| Corydon: median OWP HAND (m) | 29.7 | 1.8 | 1.8 | 1.5 |
| Lanesville: also in OWP's top 25 | 7 | 10 | 15 | 24 |

In Corydon, the 1 m HAND against NWM streams catches 5 places in its top 25 to OWP's 9, and both catch 10 in the top 100. The remaining top-25 gap could be the resolution or OWP's own DEM conditioning; this run can't separate the two. The two coarse networks score alike in Corydon, but not in Lanesville. There the Methodist church is 34 m from an unnamed channel that NWM includes and 214 m from Little Indian Creek, so the church and the two survey points beside it rank 60th against named creeks and 5th to 11th against NWM streams. Coarse networks leave more cells with no HAND, because their flow paths leave the DEM before reaching a stream: 108 of Corydon's 4,405 area candidates and 172 of Lanesville's 2,247, which rank last.

**Ties.** In Lanesville, ten town candidates tie at exactly 0 m in OWP's 10 m HAND, which is where the church and the creek-side cluster sit. In the area, 47 tie at 0 m and share rank 24, so OWP's 3 area places in the top 25 come entirely from that tie. In Corydon, only 1 town candidate sits at OWP's lowest value, so its 9 in the top 25 are not a tie effect.

**Road–stream crossings.**

| | Crossings | With an NBI bridge or culvert within 30 m | Blocked in the bare-earth DEM |
|---|---|---|---|
| Lanesville town | 17 | 3 | 5 |
| Lanesville area | 95 | 5 | 39 |
| Corydon town | 42 | 2 | 18 |
| Corydon area | 244 | 13 | 90 |

"Blocked" means road fill stands more than 1 m above the creek bed on both sides: a digital dam that a culvert would open. Most crossings have no inventoried structure, so there is no public record of how water gets under the road.

**Run time and cost:** 16 min from an empty cache on 4 cores (Lanesville 5 min 5 s, Corydon 10 min 25 s, including downloads). $0.

## What it doesn't show

- **Overall accuracy.** The answer key shows only where flooding was seen. A high-ranked building that didn't flood can't be told apart from one nobody surveyed.
- **A general result.** This is one event and two towns. Corydon's 11 town places are 7 spots in one downtown cluster, so its 9-of-11 is close to a single yes: downtown is the lowest ground beside Little Indian Creek.
- **Whether water reaches a place.** There is no rainfall, discharge or hydraulic model. HAND only orders places by height above a creek.
- **Exact locations for some places.** SR 62's closure point wasn't reported, so we use the TIGER county-line crossing. Summit Springs is the whole street, which makes it easier to find than a single house would be.

## What didn't work

- **pysheds.** It left pits after resolving flats, so 34% of Lanesville's study area and 13% of its town candidates got no HAND. We replaced it with WhiteboxTools' `whitebox-workflows` wheel; the standalone WhiteboxTools binary download is blocked here.
- **WhiteboxTools HAND** is still missing for some cells away from town: 75 of Lanesville's 2,247 area candidates and 27 of Corydon's 4,405 have no 1 m value and rank last.
- **OWP's own bucket** is Requester Pays. The CIROH mirror serves the same files anonymously. Release 4.9.9.0 stores HAND as int16 millimetres, which we checked against the 2024 float copy.
- **NHDPlus HR map service.** It timed out, so we used the NHD HR HU8 file. It has the same flowlines without stream order.
- **Storm report coordinates** are rounded to about 1 km, too coarse to score against. Named places are geocoded from their addresses instead.
- **Crossings at the DEM edge.** TIGER road segments run past the study box. Corydon had 6 crossings within 50 m of the DEM's edge, which are dropped. Lanesville had none.

## Before building

- We checked WhiteboxTools, pysheds, OWP's precomputed HAND and the NHDPlus HR services, and used the first that worked for each step.
- The only code written for this spike is the joins and the scoring.
