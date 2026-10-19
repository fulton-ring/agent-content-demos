# Can we map and record supply chain risk in NYC using FEMA's methodology?

FEMA's [Supply Chain Resilience Guide](https://www.fema.gov/sites/default/files/2020-07/supply-chain-resilience-guide.pdf)
(April 2019) asks emergency managers to map a supply chain's nodes, the infrastructure they depend on, and the hazards
on each. This spike does that row by row from public data for one lifeline, **electric power in Brooklyn**. You add a
parcel and get a ranked list of the facilities upstream of it, the flood and NRI risk on each, and the public source
for every link. Issue [#62](https://github.com/fulton-ring/agent-content-demos/issues/62).

Everything is in one marimo notebook, [`supply_chain_risk.py`](supply_chain_risk.py), read top to bottom.

## How to run it

```bash
./run.sh                           # needs uv; downloads ~20 MB into data/ on the first run, then writes output/
PARCELS=my_parcels.csv ./run.sh    # your own parcels: CSV with name and bbl, or name, lat and lon; or a GeoJSON
```

To read it as a notebook: `uv run marimo edit supply_chain_risk.py`. The first run took 10 minutes from a clean
checkout, most of it retrying FEMA's flood map server, which drops about half its connections. If it still gives up, run
it again: every answer is cached in `data/` as it arrives. Later runs take about 35 seconds.

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

No public dataset says which substation serves which part of Brooklyn. The links come from utility and grid-operator
filings, so the notebook downloads each one and checks that the quoted passage is in it (`output/source_check.csv`):
**38 passages verified, 0 not found.** The FEMA guide itself returned HTTP 403 from our network, so its 7 quoted steps show
as `unreachable`. We read the guide's text through a web reader instead.

## Results (run of 2026-10-19)

**The schema.** The guide's five Phase 1 steps and two Phase 2 questions become four tables: nodes (parcels,
networks, substations, plants), links (supplier, consumer, status, source, passage), hazards per node, and the
sources with their checks. Phases 3 to 5 are meetings and exercises with the facility owners, so they're out of scope.

**Facilities and links mapped.** 21 named facilities: 9 area substations, 6 transmission substations and 6 plants;
18 are on the map. 32 links:

| Link type | Documented | Inferred |
|---|---:|---:|
| area substation → network (2012 PSC table) | 13 | 0 |
| transmission or 138 kV hub → area substation | 5 | 2 |
| 345 kV ties | 6 | 0 |
| plant → station | 5 | 1 |

The 3 inferred links are Farragut → Plymouth St., Farragut → Water St. (both sites sit within 200 m of Farragut), and
Brooklyn Navy Yard Cogen → Farragut.

**Lots matched.** Of 275,864 Brooklyn lots, 216,361 (78%) are inside a Con Edison network-supplied area, 51,989 (19%)
are within 500 ft of an overhead feeder, 7,489 (2.7%) fall back to their load area's network (inferred), and 25 match
nothing.

**Coverage against Con Edison's counts.** Con Edison's 2024 report lists 6 Brooklyn area substations, 11
network/load areas and 15 4 kV unit substations. The 2012 table names 7 area substations (Brownsville No. 1 and 2 share
a site, as do Bensonhurst No. 1 and 2). The public map has 5 area substation sites, 12 network areas (Richmond Hill
is counted under Queens in the report), and 5 of the 15 unit substations.

**Concentration (FEMA Phase 2).** The guide expects "seven or fewer sources" to carry 70 to 80% of flows. In
Brooklyn, **5 area substations serve 80% of lots**, on 4 sites. Two 138 kV hubs sit behind almost everything:
Greenwood (fed from Gowanus) is upstream of 60% of lots and Farragut of 39%. **Farragut and Gowanus are both in FEMA's
1% annual chance flood zone and inside the area Sandy flooded.**

**Sample parcel.** For Brookdale University Hospital the list has 11 upstream facilities. Its top risk is Farragut,
the only 138 kV source for its area substation and in an AE zone. Next comes its area substation, Brownsville No. 1,
which is outside the flood zone and documented to hit its capacity limit by summer 2028. The 345 kV ties come after
the direct chain. We hand-checked all 11 rows against the source passage, the facility's location, FEMA's zone at the
site's centre and NYC's Sandy inundation map ([`hand_check.csv`](hand_check.csv)): **8 correct, 1 wrong, 2 not
checkable.** The wrong one is East 13th Street, a 345 kV tie to Farragut. It isn't on OpenStreetMap, so it gets no
flood rating, yet Sandy flooded it and cut power to about 220,000 customers (DOE case study, 2024).

Outputs: `output/upstream_risks.csv` (every sample parcel), `nodes.csv`, `parcels.csv`, `concentration.csv`,
`coverage.csv`, `source_check.csv`, `summary.json` and `map.png`.

![Brooklyn power dependencies](output/map.png)

## What the spike shows

The method holds for power, and the gaps are where we expected. FEMA's steps map cleanly onto four tables. The
parcel-to-network step is fully public, because Con Edison publishes its network areas. Facility-to-facility links
are the weak part. No dataset has them: they come from a 14-year-old PSC exhibit, rate-case filings and NYISO's queue,
and three of them are guesses. NYISO's own line list (Gold Book Table VI-1) needs a login, and HIFLD's substation
layer has been restricted since 2022. Even so, the ranked list already finds the risk that matters for central
Brooklyn: everything rests on Farragut and Gowanus, and both are on the flooded waterfront.

## What didn't work, and what this doesn't show

- **The links are dated.** The network-to-substation table is from 2012. Con Edison has moved load since (6 MW from
  Brownsville in 2023, 60 MW to Glendale in 2026), and Gateway Park will split Crown Heights and Richmond Hill in 2028.
- **3 of 21 facilities have no footprint** (Glendale, E. 13th St., Hudson in Jersey City), so they get no hazard
  rating. That is how the hand check missed a real Sandy flood.
- **Flood zones are FEMA's effective 2007 maps.** FEMA's 2015 preliminary maps put more of the waterfront in the 1% zone
  and aren't in NFHL's effective layer. A zone on any part of a footprint counts. For Farragut, Goethals and NYPA 23rd St
  that is the AE edge of the site, while the centre is in the 0.2% zone; all three were inside Sandy's flood.
- **Lots, not load.** Concentration counts tax lots, since load per lot isn't public. Con Edison publishes peak load per
  network (forecast file), which a later version could use.
- **Distribution is a model.** The 500 ft feeder match and the load-area fallback are guesses for 59,478 lots. Con
  Edison doesn't publish underground network feeders.
- **No recovery times.** The guide's resilience gap compares a utility's restoration time with a facility's backup
  power. Neither is public here.
- **Upstream stops one hop out** on the meshed 345 kV grid; past that every plant in the city is upstream of everything.
- The NYISO queue, Con Edison's map and PLUTO are unversioned, so later runs may shift slightly.
- Only power in Brooklyn. Other lifelines, citywide coverage and a graph database or app are sub-issues
  [#63](https://github.com/fulton-ring/agent-content-demos/issues/63),
  [#64](https://github.com/fulton-ring/agent-content-demos/issues/64) and
  [#65](https://github.com/fulton-ring/agent-content-demos/issues/65).

## What we looked at first

- [Seer.ai](https://www.seer.ai/), from the card: a commercial supply chain graph. It's paid and its data isn't
  public, so it can't back a reproducible demo; #65 compares a graph store against flat tables.
- A graph database: unnecessary at 34 nodes. NetworkX finds each parcel's ancestors, and pandas holds the tables.
- HIFLD substations (restricted since 2022) and NYISO Gold Book Table VI-1 (needs a myNYISO login): not usable.
- Overpass for OSM: it failed in the `hifld-grid-gaps` spike. Overture's versioned GeoParquet, read with DuckDB, works.
- GeoPandas does the spatial joins and pypdf/openpyxl read the documents. We wrote no matching logic beyond joins, a
  name crosswalk and a 500 ft nearest-feeder rule.

The notebook is about 1,060 lines, a little over the 1,000-line budget. About a fifth of that is the markdown that
explains each step, and the 32 links are written out as one row each so they can be read.
