# Do data centers in the same metro share the same flood zones and risk scores?

Cloud redundancy assumes one building fails while the next keeps running. This spike asks
whether reported US data-center sites in the same metro sit in the same FEMA flood zone and score
alike on FEMA's National Risk Index (NRI) and our Future Risk Index (FRI) rebuild, so that one
flood or storm could hit them together. Issue
[#174](https://github.com/fulton-ring/agent-content-demos/issues/174),
[proposal card](https://app.notion.com/p/3fccc69045cb81c49f68fcd4366d6cb6).

**Short answer: yes for the regional indices, mostly no for flood zones.**

- **Regional scores cluster hard by metro.** The metro explains 59–62% of the variance in NRI
  scores and 92–96% in FRI multipliers, against 7–20% when metro labels are shuffled.
- **Flood zones match, but mostly because almost nothing is in a floodplain.** 92% of
  clustered sites share a flood class and NRI tract rating with another site in their metro.
  Shuffled metros already give 82%, because 84% of all sites are in FEMA's minimal-hazard zone X.
- **The metros where it matters are few.** Phoenix (44 of 47 sites in SFHA or shaded X) and
  San Jose (37 of 43, and 41 in a high-NRI tract) are where the clustered sites share a
  *flood* hazard. The biggest cluster, the DC metro around Ashburn (237 sites), is all zone X
  and low NRI.

## Run it

```bash
./run.sh
```

Needs [uv](https://docs.astral.sh/uv/) and a full checkout of this repo (it reads the FRI files
in `../fri-datasets-map/data/`). It runs `notebook.py` as a script and writes everything to
`results/`. From an empty cache it takes about 11 minutes, most of it about 13,000 point queries
to FEMA's services. Downloads are cached in `~/.cache/data-center-metro-hazard` (or set
`DCH_CACHE`). To read the notebook with its outputs: `uv run marimo edit notebook.py`.

## Data (all public, read at run time, nothing downloaded is committed)

| What | Source |
|---|---|
| Sites | OpenStreetMap features tagged `telecom=data_center` that intersect the US (relation 148838), from the public [QLever](https://qlever.dev/osm-planet) SPARQL endpoint, planet file of 2026-09-21. ODbL. Ways and relations reduced to centroids. |
| Metros | Census TIGER 2024 CBSA boundaries (metro and micro areas) |
| Flood zones | FEMA NFHL live service, layer 28 (Flood Hazard Zones), point queries |
| NRI | FEMA NRI v1.20 (December 2025) tract layer (point queries) and county layer, ArcGIS Online |
| FRI | Our rebuild, `fri-datasets-map/data/`: late century, higher warming; coastal flooding, hurricane (central), extreme heat (LOCA2 95th) |

**Why OSM.** HIFLD Next has no data-center layer. PNNL's IM3 Open Source Data Center Atlas
(DOI [10.57931/3017294](https://doi.org/10.57931/3017294), ODbL) is built from the same OSM tag,
but its MSD-LIVE record lists only a placeholder file and its access endpoint returned 403 to us.
OSM locations are crowd-mapped, mostly building or campus outlines traced from imagery (1,642
ways, 10 relations, 130 single points); no operator confirms them. The public Overpass servers
refused or timed out from our environment, and ohsome's extraction endpoint returned 403.

## Method

1. 1,782 OSM features. Features within 150 m of each other are merged (a campus and its
   buildings), keeping the largest footprint: **1,275 sites**.
2. 1,254 sites fall in **164 CBSAs**; **1,176 sites in 86 CBSAs** have at least one other site.
   These clustered sites are what we compare.
3. Each site gets an NFHL flood class: **SFHA** (zones A, V), **shaded X** (moderate: 0.2%
   floodplain, behind levees, shallow 1%), **minimal** (unshaded X), **D**, or **not mapped**.
   The highest hazard wins where polygons meet. It also gets its tract's NRI rating and score,
   its county's NRI rating and score, and its county's FRI multipliers.
4. **Share sharing:** the share of clustered sites with another site in the same metro that
   matches. The **chance** column shuffles metro labels 200 times, keeping metro sizes.
5. **Within against between:** all site pairs, same metro against different metros, with
   η² (variance explained by metro) against 200 shuffles.
6. **Location error:** each site moved 250 m north, east, south and west.

## Results (clean run, 2026-11-01)

Flood classes of the 1,275 sites: minimal 1,076 (84%), shaded X 116, not mapped 37, SFHA 28,
D 18.

| Clustered sites that share with another site in their metro | Sites | Share | Chance | Chance 95th pct |
|---|---|---|---|---|
| Flood class + NRI county rating | 1,176 | 96.2% | 83.9% | 85.5% |
| Flood class + NRI tract rating | 1,176 | 92.0% | 81.8% | 83.3% |
| Flood class + NRI tract rating, partner 1 km+ away | 1,176 | 85.7% | 81.4% | 82.7% |
| Flood class + NRI tract rating, without the DC metro | 939 | 90.1% | 79.7% | 81.5% |
| SFHA or shaded X sites, partner in the same class | 144 | 87.5% | 75.8% | 81.2% |
| SFHA sites, partner also SFHA | 28 | 71.4% | 51.9% | 71.4% |

| Same metro vs different metros | Same metro | Same metro, other county | Different metros | η² (chance) |
|---|---|---|---|---|
| Flood class matches | 93.7% | 93.2% | 70.0% | |
| NRI tract rating matches | 50.8% | 47.7% | 25.0% | |
| NRI county rating matches | 56.1% | 12.0% | 22.1% | |
| NRI tract score, mean gap | 16.7 | 20.0 | 34.5 | 0.62 (0.07) |
| NRI county score, mean gap | 7.1 | 14.1 | 15.8 | 0.59 (0.07) |
| FRI coastal flood, mean gap | 0.94 | 1.81 | 32.4 | 0.92 (0.20) |
| FRI hurricane, mean gap | 0.009 | 0.018 | 0.093 | 0.96 (0.10) |
| FRI extreme heat, mean gap | 0.34 | 0.67 | 1.93 | 0.96 (0.07) |

No shuffle reached the real η² for any score. Pairs are dominated by the DC metro (237 of 1,176
clustered sites). The county NRI rating matches within a metro only when the two sites share a
county: across counties in one metro it matches less often (12%) than across metros (22%).

**Metros with the most sites in a floodplain** (SFHA or shaded X): Phoenix 44 of 47, San Jose 37
of 43, Las Vegas 14 of 22, Omaha 8 of 29, New York 7 of 62, Dallas–Fort Worth 7 of 54.
**Most sites in a Very or Relatively High NRI tract:** San Jose 41, New York 24, Dallas–Fort
Worth 23, San Antonio 19, Phoenix 15, Moses Lake 14. Full table: `results/metros.csv`; chart:
`results/metros.png`.

**Location sensitivity.** Moving a site 250 m changes its flood class for 19.5% of sites (at one
or more of four moves; 7.5% of single moves), its tract for 30.7% and its NRI tract rating for
19.5%. 163 sites (12.8%) not in the SFHA have SFHA 250 m away.

**Run time and cost.** 11 minutes from an empty cache (10 min 49 s on 2026-11-01: 8 minutes of
FEMA point queries, 2 minutes of shuffles); about 2.5 minutes cached. $0: every source is free.

## What it doesn't show

- **Shared scores are not shared outages.** Most sites are outside mapped floodplains, operators
  build above flood elevation, and the NFHL is today's map, not a forecast.
- **The OSM list is incomplete and uneven.** Mappers have drawn Ashburn in detail and other
  metros barely. Sites can be small server rooms. QLever updates its planet file, so a later run
  can find a slightly different list.
- **County indices can't tell sites in one county apart.** The FRI and county NRI agreement
  inside a metro is mostly the county; the tract NRI and flood class are the site-level tests.
- **No conflict or geopolitical scoring**, by design.

## Files

- `notebook.py`: the whole analysis, a [marimo](https://marimo.io) notebook
- `results/sites.csv`: one row per site (source, metro, flood class and zone, NRI tract and
  county ratings and scores, FRI values)
  — derived from OpenStreetMap, © OpenStreetMap contributors, available under the
  [ODbL](https://opendatacommons.org/licenses/odbl/1-0/)
- `results/metros.csv`, `results/within_between.csv`, `results/location_sensitivity.csv`,
  `results/headline.json`, `results/metros.png`
