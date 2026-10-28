# Matching flash-flood warnings to the addresses at risk

On June 9, 2026, NWS Louisville's 10:22 AM flash flood warning (LMK FF.W.0021, 722 sq mi) covered Lanesville and Corydon, Indiana, but named only Louisville-area towns. This spike asks whether public terrain data could have turned that polygon into a ranked list of the buildings and road crossings likely to flood first. If it could, the places that actually flooded should land near the top.

**Short answer: sometimes. Which terrain product works depends on the town, and on the building inventory.**

- **Lanesville**, where the rain fell: every HAND ranking catches more observed places than random order. The 1 m HAND measured against National Water Model streams does best in the top 25, with 6 of 14 places in its top 25 of 535 candidates (0.8 expected at random) and a median rank of 21. Most misses are street and yard points or spots well above any mapped creek.
- **Corydon**, downstream, where Little Indian Creek carried that runoff into downtown: NOAA's 10 m HAND and the 1 m HAND on a coarse network each put 4 of 11 observed places in their top 25 of 1,748 candidates, against 0.3 expected at random. In the top 100 the coarse-network 1 m HAND catches 10 and OWP's 6. Our 1 m HAND on every mapped stream puts none in its top 25. Its top 25 are houses on small unnamed channels, where NOAA's HAND reads about 29 m.
- **The stream network matters more than the resolution.** Against every NHD High Resolution flowline, the 1 m HAND catches the fewest places in the top 100 of any HAND ranking in both towns. Against named creeks or NWM streams, the same 1 m DEM does about as well as OWP's 10 m product: better in Corydon's top 100, and better in Lanesville's top 25 against NWM streams.
- **The building layer moves the answer.** With USA Structures' 2023 Indiana release, which our earlier runs got from the live service, OWP's HAND put 9 of Corydon's 11 places in its top 25. With the 2025 release it puts 4. Two block-sized downtown footprints in the older release carried six of the nine survey points (see "What didn't work").

Both answer keys are small. Lanesville has 11 distinct spots and Corydon 7, and Corydon's all lie within 350 m of each other downtown.

## How to run it

```bash
./run.sh            # needs uv; about 18 to 21 minutes (with the first uv install) and 3.3 GB of downloads and cached rasters the first time
```

`run.sh` runs `notebook.py` as a script once per town (`FFW_SITE=lanesville`, then `FFW_SITE=corydon`). To read it with its outputs, use `FFW_SITE=corydon uv run marimo edit notebook.py`. Downloads and intermediate rasters are cached in `$FFW_CACHE` (default `~/.cache/flash-flood-warning-addresses`). Results go to `results/<town>/`.

## Data (all public, downloaded at run time, nothing committed)

| Layer | Source |
|---|---|
| Warning polygon and text | IEM VTEC archive (`json/vtec_event.py`, `geojson/vtec_event.py`) |
| Answer key: survey points | NWS LMK flood survey KMZ, `flood_survey06092026.kmz`: 21 points, 12 in Lanesville and 9 in Corydon (locations and times, no depths) |
| Answer key: named places | IEM local storm reports and news (WLKY, WDRB, WAVE), geocoded to Indiana address points |
| Structures | FEMA/ORNL USA Structures state files on the public `fema-femadata` bucket: Indiana `Deliverable20250913IN.zip` (released September 13, 2025; production dates 2020 and 2025) for the study areas, plus Kentucky `Deliverable20250606KY.zip` (June 6, 2025) for the whole-warning count. The notebook checks each file's SHA-256 and stops if it changed. |
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
2. Computes 1 m HAND (height above nearest drainage) with WhiteboxTools: breach road embankments at stream crossings, breach depressions, `elevation_above_stream`. It runs the last step three times on the same conditioned DEM, against three networks: every kept NHD HR flowline, named creeks only (a GNIS name), and the NHD HR flowlines that run along OWP's NWM streams (at least 80% of the flowline within 60 m). The NWM lines themselves are drawn from a coarser map and sit well off the lidar channels, too far to burn into a 1 m DEM.
3. Scores every structure, by the lowest value under its footprint, and every road–stream crossing, by its road surface. It does this five ways: the three 1 m HANDs, OWP's 10 m HAND, and straight-line height above the nearest creek.
4. Takes an observed place's rank to be the best rank of any candidate within 30 m. It counts places in the top 25, 50 and 100, reports the median rank, and compares with the number expected from random order.
5. Labels each miss with a likely reason. It compares what each HAND ranking puts in its top 25, maps the result (`results/<town>/map.png`) and writes `results/<town>/summary.json`.

## Results (from two clean runs on 2026-10-28, byte-identical except run time)

**Inside the warning:** 295,109 structures, 19,459 Indiana address points and 14,663 road segments. The Kentucky side, including Louisville, has no address points in this layer.

| | Lanesville town | Corydon town |
|---|---|---|
| Structures | 517 | 1,703 |
| Address points | 403 | 1,467 |
| Road segments | 65 | 186 |

**Where observed places land.** In the table, "No match" counts places with no structure or crossing within 30 m. "Random" is the number expected in the top *K* if the candidates were shuffled. Town rankings leave out the place outside the town limits: SR 62 for Lanesville, Summit Springs for Corydon.

| Scope | Ranking | Top 25 | Top 50 | Top 100 | No match | Median rank |
|---|---|---|---|---|---|---|
| **Lanesville town (535 candidates, 14 places)** | 1 m HAND | 2 | 6 | 7 | 2 | 45 |
| | 10 m OWP HAND | 3 | 7 | 11 | 2 | 33 |
| | Height above creek | 2 | 3 | 7 | 2 | 78 |
| | 1 m HAND, named creeks | 4 | 4 | 10 | 2 | 65 |
| | 1 m HAND, NWM streams | 6 | 7 | 10 | 2 | 21 |
| | *Random* | *0.8* | *1.6* | *3.1* | | |
| Lanesville area, 7 × 6.7 km (2,567 candidates, 15 places) | 1 m HAND | 0 | 2 | 3 | 3 | 152.5 |
| | 10 m OWP HAND | 3 | 3 | 6 | 3 | 100 |
| | Height above creek | 0 | 0 | 0 | 3 | 383 |
| | 1 m HAND, named creeks | 3 | 4 | 4 | 3 | 142 |
| | 1 m HAND, NWM streams | 3 | 6 | 7 | 3 | 47 |
| | *Random* | *0.2* | *0.3* | *0.7* | | |
| **Corydon town (1,748 candidates, 11 places)** | 1 m HAND | 0 | 1 | 4 | 1 | 199 |
| | 10 m OWP HAND | 4 | 4 | 6 | 1 | 81.5 |
| | Height above creek | 0 | 0 | 0 | 1 | 726.5 |
| | 1 m HAND, named creeks | 4 | 5 | 10 | 1 | 45.5 |
| | 1 m HAND, NWM streams | 4 | 5 | 10 | 1 | 56.5 |
| | *Random* | *0.3* | *0.6* | *1.2* | | |
| Corydon area, 7 × 7.3 km (5,121 candidates, 12 places) | 1 m HAND | 0 | 0 | 1 | 1 | 1,173 |
| | 10 m OWP HAND | 4 | 4 | 5 | 1 | 145 |
| | Height above creek | 0 | 0 | 0 | 1 | 2,262 |
| | 1 m HAND, named creeks | 4 | 4 | 7 | 1 | 90 |
| | 1 m HAND, NWM streams | 4 | 4 | 5 | 1 | 103 |
| | *Random* | *0.5* | *0.8* | *1.3* | | |

**What the town's 1 m HAND ranking misses, with the likely reason:**

| Reason | Lanesville (7 of 14) | Corydon (7 of 11) |
|---|---|---|
| No structure or crossing within 30 m (a street or yard point) | 2 | 1 |
| More than 100 m from a mapped stream | 2 | 1 (Hey Elmer, 115 m) |
| Within 100 m of a stream but too high above it to make the top 100 | 3 (3.6–4.7 m) | 5 (2.7–3.5 m) |
| In a closed depression of 0.3 m or more | 0 | 0 |

**Why the two HAND products disagree in Corydon.** Our 1 m HAND measures height above every kept NHD High Resolution flowline. In the Corydon box, 832 of 959 of those are unnamed. OWP measures height above the National Water Model's coarser network. The 1 m ranking's town top 25 holds 29 candidates, because 29 tie at 0 m. Only 2 of them are nearest a named creek, and their median OWP HAND is 29.1 m: houses beside headwater channels on the hillsides. Of OWP's top 25, 21 are nearest a named creek (mostly Little Indian Creek), with a median 1 m HAND of 1.9 m. The water came down Little Indian Creek from Lanesville, so a ranking that measures height above that creek finds downtown. In Lanesville the 1 m ranking's top 25 has a median OWP HAND of 3.5 m.

**Network or resolution? Mostly network.** Measuring the 1 m HAND against a coarser network moves it most of the way to OWP's picks while keeping the 1 m DEM. The two coarse networks are a sixth to a quarter of the full one by length (Corydon: 28 km named, 32 km along NWM, 188 km in all; Lanesville: 26, 26 and 108 km).

| Town top 25 | 1 m HAND, all streams | 1 m, named creeks | 1 m, NWM streams | 10 m OWP |
|---|---|---|---|---|
| Corydon: also in OWP's top 25 | 2 | 16 | 15 | 25 |
| Corydon: median OWP HAND (m) | 29.1 | 1.7 | 1.7 | 1.5 |
| Lanesville: also in OWP's top 25 | 6 | 7 | 12 | 25 |

In Corydon, the 1 m HAND against either coarse network ties OWP in the top 25 (4 places each) and beats it in the top 100 (10 against 6). In Lanesville the NWM network beats named creeks: the Methodist church is 33 m from an unnamed channel that NWM includes and about 200 m from Little Indian Creek (measured by hand, not printed by the notebook), so the church and the two survey points beside it rank 65th against named creeks and 5th to 12th against NWM streams. Coarse networks leave more cells with no HAND, because their flow paths leave the DEM before reaching a stream: 140 of Corydon's 5,121 area candidates and 195 of Lanesville's 2,567, which rank last.

**Ties.** In Lanesville, nine town candidates tie at OWP's lowest value, which is where the church and the creek-side cluster sit. In the area, 47 tie there, so OWP's 3 area places in the top 25 come from that tie. In Corydon, only 1 town candidate sits at OWP's lowest value.

**Road–stream crossings.**

| | Crossings | With an NBI bridge or culvert within 30 m | Blocked in the bare-earth DEM |
|---|---|---|---|
| Lanesville town | 17 | 3 | 5 |
| Lanesville area | 95 | 5 | 39 |
| Corydon town | 42 | 2 | 18 |
| Corydon area | 244 | 13 | 90 |

"Blocked" means road fill stands more than 1 m above the creek bed on both sides: a digital dam that a culvert would open. Most crossings have no inventoried structure, so there is no public record of how water gets under the road.

**Run time and cost:** 17 to 19 min from an empty cache on 4 cores (Lanesville 6.5 to 7.3 min, Corydon 10.1 to 11.2 min, including downloads). $0.

## What it doesn't show

- **Overall accuracy.** The answer key shows only where flooding was seen. A high-ranked building that didn't flood can't be told apart from one nobody surveyed.
- **A general result.** This is one event and two towns. Corydon's 11 town places are 7 spots in one downtown cluster, so each ranking's count there moves in steps of several places at once, as the change between structure releases shows.
- **Whether water reaches a place.** There is no rainfall, discharge or hydraulic model. HAND only orders places by height above a creek.
- **Exact locations for some places.** SR 62's closure point wasn't reported, so we use the TIGER county-line crossing. Summit Springs is the whole street, which makes it easier to find than a single house would be.

## What didn't work

- **The live USA Structures service.** The first runs queried FEMA/ORNL's `USA_Structures_View` feature service. Between October 24 and 28, 2026 it swapped Indiana's 2023 release (2020 production) for the 2025 one, adding about 41,000 structures inside the warning, and every result changed. Corydon's OWP top 25 went from 9 of 11 places to 4. In the 2023 release, two downtown footprints of about 1,700 m² each reached the low ground by the creek and sat within 30 m of six of the nine survey points. The 2025 release draws the buildings there smaller and differently. Its Kentucky footprints now include ones produced in February 2026, too close to the storm to know they show the town as it stood. We now read the dated state files and check their hashes. The 2025 Indiana file gives the same counts in both study boxes as the service did on October 28. The other inputs (address points, NBI bridges, TIGERweb boundaries and IEM warnings) are still read from live services and aren't hash-pinned; they didn't change between the October 28 runs.
- **pysheds.** It left pits after resolving flats, so 34% of Lanesville's study area and 13% of its town candidates got no HAND. We replaced it with WhiteboxTools' `whitebox-workflows` wheel; the standalone WhiteboxTools binary download is blocked here.
- **WhiteboxTools HAND** is still missing for some cells away from town: 88 of Lanesville's 2,567 area candidates and 36 of Corydon's 5,121 have no 1 m value and rank last.
- **OWP's own bucket** is Requester Pays. The CIROH mirror serves the same files anonymously. Release 4.9.9.0 stores HAND as int16 millimetres, which we checked against the 2024 float copy.
- **NHDPlus HR map service.** It timed out, so we used the NHD HR HU8 file. It has the same flowlines without stream order.
- **Storm report coordinates** are rounded to about 1 km, too coarse to score against. Named places are geocoded from their addresses instead.
- **Crossings at the DEM edge.** TIGER road segments run past the study box. Corydon had 6 crossings within 50 m of the DEM's edge, which are dropped. Lanesville had none.

## Before building

- We checked WhiteboxTools, pysheds, OWP's precomputed HAND and the NHDPlus HR services, and used the first that worked for each step.
- The only code written for this spike is the joins and the scoring.
