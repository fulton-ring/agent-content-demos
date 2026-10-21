# Can we map and record supply chain risk in NYC using FEMA's methodology?

FEMA's [Supply Chain Resilience Guide](https://www.fema.gov/sites/default/files/2020-07/supply-chain-resilience-guide.pdf)
(April 2019) asks emergency managers to map a supply chain's nodes, the infrastructure they depend on, and the hazards
on each. This spike does that row by row from public data for **Brooklyn**, first for electric power (issue
[#62](https://github.com/fulton-ring/agent-content-demos/issues/62)), then for the other lifelines. You add a parcel and
get the facilities upstream of it, the flood and NRI risk on each, and the public source for every link.

Two marimo notebooks, each read top to bottom: [`supply_chain_risk.py`](supply_chain_risk.py) for power, and
[`lifelines.py`](lifelines.py) for water, wastewater, gas, fuel, food and telecom (issue
[#63](https://github.com/fulton-ring/agent-content-demos/issues/63)). [`common.py`](common.py) holds the downloads,
source check and hazard lookups both use.

## How to run it

```bash
./run.sh                           # needs uv; downloads ~20 MB into data/ on the first run, then writes output/
PARCELS=my_parcels.csv ./run.sh    # your own parcels: CSV with name and bbl, or name, lat and lon; or a GeoJSON
```

To read them as notebooks: `uv run marimo edit supply_chain_risk.py`, then `lifelines.py`. A clean run takes 6 to 17
minutes (power 3 to 13, lifelines about 4), mostly retrying FEMA's flood map server, which drops about half its
connections. If it gives up, run it again: every answer is cached in `data/` as it arrives.

## The data

All public, downloaded at run time, not committed.

| Source | What we use |
|---|---|
| FEMA Supply Chain Resilience Guide (2019) | Phase 1 and 2 steps, turned into the schema |
| [Con Edison hosting capacity map](https://www.coned.com/en/business-partners/hosting-capacity) REST layers (DOE's hosting capacity atlas links here) | network load areas, network-supplied areas, overhead feeder segments tagged with their area substation |
| Con Edison 2012 network ranking, PSC exhibit IIP-8 | which area substation supplies each network |
| BQDM petition (2014), DPS-12 response (2023), Con Edison Local Transmission Plan (2025) | 138 kV supply links; capacity stressors |
| NYISO bulk power facility list, interconnection queue, 2026 Gold Book | 345 kV ties; where plants connect; deactivation notices |
| OpenStreetMap via [Overture](https://docs.overturemaps.org/) `base/infrastructure`, release 2026-09-23.0 | substation and plant footprints |
| FEMA National Flood Hazard Layer (effective), National Risk Index (census tracts) | hazards on each node |
| NYC MapPLUTO (Open Data `64uk-42ks`) | 275,864 Brooklyn tax lots; BBL lookup for parcels |
| Joint Utilities of NY 2024 reliability report | Con Edison's published Brooklyn counts |
| *Lifelines:* DEP drainage areas, NYS sewersheds (Hill and Larsen 2023), NYS gas utility territories (`i7nm-ih89`), Verizon copper retirement notices to the FCC (2016–2018) | which plant, gas utility and wire center serve each lot |
| *Lifelines:* NYC Facilities Database, HIFLD Next POL terminals (EIA), NYC GeoSearch, MapPLUTO outlines | plant, terminal, wire center and market sites |
| *Lifelines:* DEP tunnel EIS (2005), PSC Case 24-G-0248, FERC, DOE (2013), Columbia CGEP (2016), Food Flow study (2016), State Comptroller (2023), city Sandy report (2013) | the links and stressors above the first facility |

Links come from filings, so each notebook downloads them and checks that the quoted passage is in them
(`output/source_check.csv`): **38 passages verified, 0 not found.** The FEMA guide returned HTTP 403 from our network,
so its 7 quoted steps show as `unreachable`; we read it through a web reader instead.

## Results (run of 2026-10-19)

**The schema.** The guide's Phase 1 steps and Phase 2 questions become four tables: nodes, links (supplier, consumer,
status, source, passage), hazards per node, and sources with their checks. Phases 3 to 5 are meetings, so out of scope.

**Facilities and links mapped.** 21 named facilities (9 area substations, 6 transmission substations, 6 plants), 18
on the map. 32 links: area substation → network 13 documented; 138 kV hub → area substation 5 documented, 2 inferred;
345 kV ties 6 documented; plant → station 5 documented, 1 inferred. The 3 inferred links are Farragut → Plymouth St.,
Farragut → Water St. (both within 200 m of Farragut), and Brooklyn Navy Yard Cogen → Farragut.

**Lots matched.** Of 275,864 Brooklyn lots, 216,361 (78%) are in a network-supplied area, 51,989 (19%) within 500 ft
of an overhead feeder, 7,489 (2.7%) fall back to their load area's network (inferred), and 25 match nothing.

**Coverage against Con Edison's counts.** Its 2024 report lists 6 Brooklyn area substations, 11 network/load areas and
15 4 kV unit substations (transcribed by hand). The public map has 5 area substation sites, 12 network areas and 5 of
the 15 unit substations.

**Concentration (FEMA Phase 2).** The guide expects "seven or fewer sources" to carry 70 to 80% of flows. In
Brooklyn, **5 area substations serve 80% of lots**, on 4 sites. Two 138 kV hubs sit behind almost everything:
Greenwood (fed from Gowanus) is upstream of 60% of lots and Farragut of 39%. **Farragut and Gowanus are both in FEMA's
1% annual chance flood zone and inside the area Sandy flooded.**

**Sample parcel.** Brookdale University Hospital has 11 upstream facilities. Top is Farragut, the only 138 kV source
for its area substation, in an AE zone; then Brooklyn Navy Yard Cogen (AE, link inferred); then Brownsville No. 1,
outside the flood zone and documented to hit its capacity limit by summer 2028. Our hand check of all 11 rows
([`hand_check.csv`](hand_check.csv)): **8 correct, 1 wrong, 2 not checkable.** The wrong one is East 13th Street: not
on OpenStreetMap, so no flood rating, yet Sandy flooded it and cut power to about 220,000 customers (DOE, 2024).

Outputs: `output/upstream_risks.csv` (every sample parcel), `nodes.csv`, `parcels.csv`, `concentration.csv`,
`coverage.csv`, `source_check.csv`, `summary.json` and `map.png`.

![Brooklyn power dependencies](output/map.png)

## Other lifelines (`lifelines.py`, run of 2026-10-21)

Same tables and passage check (`output/lifeline_source_check.csv`): **57 passages verified, 0 not found**; 6 links
come from fields in the EIA terminal data and 3 are inferred. From `output/lifeline_coverage.csv`:

| Lifeline | Facilities (placed) | Links documented / inferred | Brooklyn lots matched to a serving facility |
|---|---:|---:|---|
| Power (from #62) | 21 (18) | 29 / 3 | 97.3% documented, 2.7% inferred |
| Wastewater | 6 (6) | 5 / 0 | **99.9% documented** (DEP drainage areas; the state's sewershed layer agrees on 99.1%) |
| Natural gas | 8 (1) | 8 / 0 | **99.9% to the utility** (National Grid NY), none to a gate or main |
| Telecom (Verizon wireline) | 17 (17) | 17 / 0 | **4.7% documented, 95.3% inferred** from the nearest documented lot |
| Water supply | 6 (0) | 6 / 0 | none: the whole borough shares one documented chain |
| Refined fuel | 11 (7) | 14 / 3 | none: documented only as far as "Brooklyn/Queens terminals" |
| Food | 3 (2) | 1 / 0 | none: Hunts Point's share is documented only citywide |

**Telecom is the surprise.** No wire-center boundary file is public, but Verizon's copper retirement notices list
14,760 Brooklyn addresses under the wire center that serves them. 88% match a tax lot, giving 13,016 seed lots,
and no lot is claimed by two wire centers. Giving each other lot the wire center of its nearest seed is right for
**96.5%** of seeds in held-out tax blocks; the nearest wire center building alone is right for 90.3%.

**Hazards.** On tax-lot footprints, 4 of Brooklyn's 5 treatment plants (Owls Head VE; Newtown Creek, 26th Ward,
Red Hook AE), all 7 Brooklyn fuel terminals, Greenpoint LNG and Hunts Point are in FEMA's 1% flood zone. No wire
center is. Coney Island's plant reads zone X, though DEP's 2013 resiliency plan rates its Sandy damage as major
(we read this in the plan; the notebook doesn't check it, as the PDF is 205 MB).

**Sample parcels** (`output/upstream_risks_all_lifelines.csv`, 190 rows). Brookdale Hospital adds to its 11 power
facilities the 26th Ward plant (AE), National Grid's three city gates and Greenpoint LNG (AE), the Rockaway Avenue
wire center, the water chain via Hillview and Tunnels 1 and 2, 7 fuel terminals (all AE or VE) and Hunts Point (AE).

**Lifelines with no public service-area link:** water supply (no shaft, pressure-zone or trunk-main areas; DEP's
own 2022 newsletter even contradicts its 2005 EIS on whether Tunnel 1 reaches Brooklyn); refined fuel (which
terminal supplies which station is commercial); food (the 2016 study says "no outlet has a single source"); gas
below the utility (which gate feeds which area); and telecom other than Verizon wireline (mobile, cable).

## What the spike shows

The method holds for power, and the gaps are where we expected. FEMA's steps map cleanly onto four tables. The
parcel-to-network step is fully public, because Con Edison publishes its network areas. Facility-to-facility links
are the weak part. No dataset has them: they come from a 14-year-old PSC exhibit, rate-case filings and NYISO's queue,
and three of them are guesses. NYISO's own line list (Gold Book Table VI-1) needs a login, and HIFLD's substation
layer has been restricted since 2022. Even so, the ranked list already finds the risk that matters for central
Brooklyn: everything rests on Farragut and Gowanus, and both are on the flooded waterfront.

The other lifelines split in two. Wastewater, gas (to the utility) and Verizon telecom can be matched to a parcel
from public data. Water supply, refined fuel and food can't: their sources name only the whole borough or city.

## What didn't work, and what this doesn't show

- **The links are dated.** The network-to-substation table is from 2012. Con Edison has moved load since (6 MW from
  Brownsville in 2023, 60 MW to Glendale in 2026), and Gateway Park will split Crown Heights and Richmond Hill in 2028.
- **3 of 21 facilities have no footprint** (Glendale, E. 13th St., Hudson in Jersey City), so they get no hazard
  rating. That is how the hand check missed a real Sandy flood.
- **Flood zones are FEMA's effective 2007 maps.** FEMA's 2015 preliminary maps put more of the waterfront in the 1% zone
  and aren't in NFHL's effective layer. A zone on any part of a footprint counts. For Farragut, Goethals and NYPA 23rd St
  that is the AE edge of the site, while the centre is in the 0.2% zone; all three were inside Sandy's flood.
- **Lots, not load**, since load per lot isn't public. **Distribution is a model**: the 500 ft feeder match and the
  load-area fallback are guesses for 59,478 lots. **No recovery times**, which the guide's resilience gap needs.
  **Upstream stops one hop out** on the meshed 345 kV grid. The NYISO queue, Con Edison's map and PLUTO are unversioned.
- **Lifelines: half the chain is unplaced.** Gate stations, pipelines, tunnels and reservoirs have no operator-published
  location, so they get no hazard rating.
- **Lifelines: inferences.** PIPE_IN says a terminal takes pipeline product but not from which pipeline (3 Buckeye
  links inferred). Telecom seeds are only the buildings Verizon moved to fiber in 2016–2018, and only Verizon wireline.
- Only Brooklyn. Citywide coverage and a graph database or app are sub-issues
  [#64](https://github.com/fulton-ring/agent-content-demos/issues/64) and
  [#65](https://github.com/fulton-ring/agent-content-demos/issues/65).

## What we looked at first

- [Seer.ai](https://www.seer.ai/), from the card: a commercial supply chain graph. It's paid and its data isn't
  public, so it can't back a reproducible demo; #65 compares a graph store against flat tables.
- A graph database: unnecessary at 34 nodes. NetworkX finds each parcel's ancestors, and pandas holds the tables.
- HIFLD substations (restricted since 2022) and NYISO Gold Book Table VI-1 (needs a myNYISO login): not usable.
- Overpass for OSM: it failed in the `hifld-grid-gaps` spike. Overture's versioned GeoParquet, read with DuckDB, works.
- For lifelines: HIFLD Next (no central offices; 1 Brooklyn cell tower; no Greenpoint LNG), FCC broadband data (login
  needed, and it names providers, not offices), commercial wire-center boundaries (licensed).
- GeoPandas does the spatial joins and pypdf/openpyxl read the documents. We wrote no matching logic beyond joins, a
  name crosswalk, a 500 ft nearest-feeder rule and the address parser for Verizon's notices.

The Python is about 2,300 lines (power 880, lifelines 1,190, shared helpers 230), over the 1,000-line budget
because #63 added six lifelines to #62's one, and the README is a little over 150 lines for the same reason. Most of
`lifelines.py` is the link and stressor tables, one quoted
passage per row, which the formatter spreads over several lines each.
