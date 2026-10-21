# Can we map and record supply chain risk in NYC using FEMA's methodology?

FEMA's [Supply Chain Resilience Guide](https://www.fema.gov/sites/default/files/2020-07/supply-chain-resilience-guide.pdf)
(April 2019) asks emergency managers to map a supply chain's nodes, the infrastructure they depend on, and the hazards
on each. This spike does that row by row from public data for one lifeline, electric power, in two marimo notebooks
that read top to bottom:

- [`supply_chain_risk.py`](supply_chain_risk.py), **Brooklyn** (issue [#62](https://github.com/fulton-ring/agent-content-demos/issues/62)):
  add a parcel and get a ranked list of the facilities upstream of it, the flood and NRI risk on each, and the
  public source for every link.
- [`citywide.py`](citywide.py), **all five boroughs** (issue [#64](https://github.com/fulton-ring/agent-content-demos/issues/64)):
  every tax lot traced to its network or feeder, area substation and first transmission station, with coverage
  against Con Edison's published counts. No hazards or parcel lists.

## How to run it

```bash
./run.sh                           # needs uv; runs both notebooks, writes output/ (Brooklyn) and output/citywide/
./run.sh citywide.py               # one notebook
PARCELS=my_parcels.csv ./run.sh supply_chain_risk.py   # your own parcels: CSV with name and bbl, or name, lat, lon
```

To read one as a notebook: `uv run marimo edit citywide.py`. Downloads (about 80 MB) are cached in `data/`.

- **Brooklyn** takes 3 to 13 minutes from a clean checkout, mostly retrying FEMA's flood map server, which drops
  about half its connections. If it gives up, run it again: answers are cached as they arrive.
- **Citywide** took CW_FIRST from a clean checkout and about CW_LATER after that.

## The data

All public, downloaded at run time, not committed. Every link that comes from a document carries the quoted passage,
and the notebooks download the document and check that the passage is in it (`source_check.csv`). Brooklyn: 38
passages verified; FEMA's guide returned HTTP 403, so its 7 quoted steps show as `unreachable`. Citywide: 78 of 78
verified.

| Source | What we use |
|---|---|
| [Con Edison hosting capacity map](https://www.coned.com/en/business-partners/hosting-capacity) REST layers (DOE's atlas links here) | network load areas, network-supplied areas, every overhead feeder segment tagged with its area substation |
| Con Edison network tables: 2012 ranking (PSC exhibit IIP-8); 2025 reliability report's power quality table | which area substation supplies each network, then and now |
| Con Edison filings: BQDM petition, rate-case testimony and exhibits (2013–2025), long-range transmission plans (2011, 2014, 2025) | 138 kV supply links, capacity stressors, planned network splits |
| NYISO: bulk power facility list, interconnection queue, Gold Books 2014 and 2026 | 345 and 138 kV ties, plant connections, deactivations. The 2014 edition is the last with Con Edison's line list; we found it as a copy in a Kentucky PSC case |
| PSEG Long Island 2023 transmission plan; NY DPS utility territories (data.ny.gov `awza-4vgu`) | the Rockaways, which LIPA serves, not Con Edison |
| OpenStreetMap via [Overture](https://docs.overturemaps.org/) `base/infrastructure`, release 2026-09-23.0 | substation and plant footprints |
| FEMA National Flood Hazard Layer (effective), National Risk Index (tracts) | hazards on each node (Brooklyn) |
| NYC MapPLUTO (Open Data `64uk-42ks`) | 857,347 NYC tax lots (275,864 in Brooklyn) |
| Joint Utilities of NY 2024 reliability report | Con Edison's published counts per borough |

## Results: Brooklyn (run of 2026-10-19)

- **The schema.** The guide's five Phase 1 steps and two Phase 2 questions become four tables: nodes, links
  (supplier, consumer, status, source, passage), hazards per node, and sources with their checks. Phases 3 to 5
  are meetings with facility owners, so they're out of scope.
- **Facilities and links.** 21 named facilities (9 area substations, 6 transmission substations, 6 plants); 18 are
  on the map. 32 links, 29 of them documented. The 3 inferred are Farragut → Plymouth St., Farragut → Water St. and
  Brooklyn Navy Yard Cogen → Farragut. (The citywide sources later document Farragut → Plymouth St.)
- **Lots matched.** Of 275,864 lots:
  - 216,361 (78%) are in a network-supplied area;
  - 51,989 (19%) are within 500 ft of an overhead feeder;
  - 7,489 (2.7%) fall back to their load area (inferred);
  - 25 match nothing.
- **Concentration (FEMA Phase 2).** The guide expects "seven or fewer sources" to carry 70 to 80% of flows. In
  Brooklyn, 5 area substations serve 80% of lots. Greenwood (fed from Gowanus) is upstream of 60% of lots and
  Farragut of 39%. **Farragut and Gowanus are both in FEMA's 1% annual chance flood zone and inside the area Sandy
  flooded.**
- **Sample parcel.** For Brookdale University Hospital the list has 11 upstream facilities, led by Farragut (the
  only 138 kV source for its area substation, in an AE zone).
  - **Hand check** ([`hand_check.csv`](hand_check.csv)): all 11 rows, against the source, the location, FEMA's zone
    and NYC's Sandy map. **8 correct, 1 wrong, 2 not checkable.**
  - **The wrong one** is East 13th Street, which isn't on OSM, so it gets no flood rating; Sandy flooded it.

![Brooklyn power dependencies](output/map.png)

## Results: citywide (run of RUN_DATE)

- **Network → area substation: all 76 load areas paired from a public table.**
  - The 2025 table names 50 NYC area substations. Counting each one in the borough where most of the lots it
    serves are gives 26 Manhattan, 6 Bronx, 6 Brooklyn, 7 Queens, 5 Staten Island. **That matches Con Edison's
    published counts exactly.**
  - Changes since 2012, found by comparing the two tables: three new networks (Freedom, Midtown West, Morgan);
    Randalls Island merged into West Bronx; Bowling Green moved from Trade Center to Seaport No. 1.
  - Eight planned splits onto five new area substations (2026–2035) are listed with their passages but not applied.
- **Area substation → transmission: 53 links, one per area substation (including LIPA's three in the Rockaways).**
  - 32 documented, 1 planned, 20 inferred.
  - Most of the inferred are stations that share a site and a name with a 138 kV station (Corona, Jamaica,
    Hellgate).
  - Plus 28 documented 138 and 345 kV ties.
- **Lots matched: LOTS_MATCHED of 857,347.**
  - 466,940 are in a network-supplied area.
  - 338,461 are within 500 ft of an overhead feeder. Staten Island's 33, 13 and 4 kV feeders are all in Con
    Edison's layer, tagged with its five area substations.
  - 37,783 fall back to their load area (inferred).
  - 13,804 in the Rockaways get the nearest of LIPA's three substations (inferred).
  - **359 match nothing:** 168 in Queens, 69 Staten Island, 55 Bronx, 42 Manhattan, 25 Brooklyn.
- **Documented end to end: 59.7% of lots** have both the lot-to-substation and the substation-to-transmission
  step sourced.
- **Concentration.** 15 area substations and **7 first-hop transmission stations serve 80% of the city's lots**.
  Greenwood 138 kV and Farragut alone are the first hop for 19% and 15%.
- **Coverage against published counts.** OSM places 35 of the 50 area substations, and 58 of the 130 4 kV unit
  substations the report counts outside Manhattan. Con Edison's map has 70 load areas where the report counts 64
  (the Bronx gives no count), because the map splits Fulton, Bowling Green and Richmond Hill into parts.

![NYC power dependencies](output/citywide/map.png)

## What the spike shows

The method holds for power, and it scales to the city. FEMA's steps map onto four tables. The lot-to-network step
is public everywhere Con Edison serves, because it publishes its network areas and overhead feeders. Con Edison's own
2025 reliability report pairs every network with its area substation, and its counts match. The weak part is the
step above the area substation. No dataset has it. It comes from rate-case testimony and a 2014 line list that
NYISO no longer publishes, and a third of it is inferred. Even so, the citywide chain finds the same concentration
that Brooklyn did: a few 138 kV stations, two of them on Brooklyn's flooded waterfront, sit first in line for a third
of the city's lots.

## What didn't work, and what this doesn't show

- **The transmission step is a third inferred** citywide (20 of 53). Con Edison's line list has been withheld since
  2015, NYISO's current one needs a login, and HIFLD's substation layer has been restricted since 2022.
- **The Rockaways are a guess at the substation level.** PSEG Long Island's feeder map needs a login.
- **5,739 Bronx lots sit on feeders tagged with Westchester stations** (Washington Street, Granite Hill). The
  report does count 19 Westchester feeders among the Bronx's, but we have no transmission link for them.
- **Footprints are incomplete.** OSM lacks a third of the area substations, so citywide hazards are left to a
  follow-up. In Brooklyn, 3 of 21 facilities have no footprint, which is how the hand check missed a real flood.
- **Flood zones are FEMA's effective 2007 maps**; the 2015 preliminary maps aren't in NFHL's effective layer. A zone
  on any part of a footprint counts.
- **Lots, not load.** Load per lot isn't public; Con Edison's network forecast file could weight a later version.
- **Distribution is a model.** The 500 ft feeder rule and the load-area fallback are guesses; underground network
  feeders aren't published.
- **No recovery times.** The guide's resilience gap needs restoration times and backup power; neither is public.
- **Upstream stops one hop out** on the meshed 345 kV grid; past that every plant is upstream of everything.
- Con Edison's map, the NYISO queue and PLUTO are unversioned, so later runs may shift slightly.
- Other lifelines and a graph database or app are sub-issues
  [#63](https://github.com/fulton-ring/agent-content-demos/issues/63) and
  [#65](https://github.com/fulton-ring/agent-content-demos/issues/65).

## What we looked at first

- [Seer.ai](https://www.seer.ai/), from the card: paid, and its data isn't public. #65 compares a graph store.
- A graph database: unnecessary at this size. NetworkX and pandas hold the tables.
- HIFLD substations, NYISO Gold Book Table VI-1 and PSEG Long Island's hosting capacity map: not public.
- Overpass for OSM failed in the `hifld-grid-gaps` spike; Overture's GeoParquet, read with DuckDB, works.
- GeoPandas does the joins, pypdf and openpyxl read the documents. Our own logic is joins, name rules and the
  500 ft feeder rule.

The notebooks are about 1,060 (Brooklyn) and 1,150 (citywide) lines, over the 1,000-line budget for one project.
About a fifth is markdown. The links are written out one per line so each can be read against its passage.
Section 1's document list and download helpers are repeated in the citywide notebook so it reads on its own.
