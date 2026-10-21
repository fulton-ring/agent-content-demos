# Are the substations we derived from HIFLD Next real?

Spike for [issue #76](https://github.com/fulton-ring/agent-content-demos/issues/76). HIFLD Next has no substations
layer, so the [county spike](../county-bans-substations/) derived 45,779 substations from the ends of its
transmission lines. Two drafts were paused until those were checked. We check them against OpenStreetMap,
re-run the county headline on substations both sources agree on, publish the combined dataset and build a map.

**Short answer: they hold up, and so does the headline.** 97% of the derived 230 kV+ substations have an
OpenStreetMap substation within 1 km. On OSM-confirmed substations, restricted counties hold a 230 kV+
substation 59.3% of the time against 50.2% (within-state odds ratio 1.56). On OpenStreetMap's own 230 kV+
substations, it's 62.3% against 52.6% (odds ratio 1.63). The gap doesn't depend on our derivation.

## Run it

```bash
./run.sh            # needs uv; first run downloads ~70 MB into data/ (about 6 minutes, most of it Overture)
./run.sh --chips    # also draws the aerial-imagery chips behind hand_check.csv (data/chips/, not committed)
```

Later runs take about 25 seconds. To read the notebook with its output next to each step:
`uv run marimo edit verify.py`. `run.sh` writes `outputs/` (tables and the log), `dataset/` and the map's
data files in `map/`.

## Data (all public, downloaded at run time)

| Input | Source | Version |
|---|---|---|
| Derived substations | [HIFLD Next](https://hifld.publicenvirodata.org/) Transmission Lines, rebuilt exactly as in `county-bans-substations/` | v1.0.0 |
| OSM substations | [Overture Maps](https://docs.overturemaps.org/) `base/infrastructure`, `class = substation`, with OSM's `voltage` tag from `source_tags` | release 2026-09-23.0 |
| Restrictions | Sabin Center, *Opposition to Renewable Energy Facilities in the United States*, restriction-data CSV | September 2026 edition |
| Counties | Census 2024 cartographic boundaries, 1:500k | 2024 |

OSM records voltages in volts, separated by `;` when a substation has several (`345000;138000`). We take the
highest. 56,067 of the 72,782 OSM substations in the 50 states and DC have a voltage tag, and 6,780 are 230 kV+.
Most OSM substations are mapped as areas, so a derived point inside the fence is distance 0.

## Results (from one clean `./run.sh`)

**Derived → OSM.** How many derived substations have an OSM substation nearby (`outputs/match_rates.csv`):

| Derived set | Substations | OSM within 250 m | OSM within 1 km | Unconfirmed (> 1 km) |
|---|---:|---:|---:|---:|
| all | 45,779 | 90.9% | 94.2% | 2,652 |
| 230 kV+ | 6,469 | 94.2% | **97.2%** | 180 |
| 345 kV+ | 2,269 | 95.2% | 98.6% | 31 |

**OSM → derived.** How many OSM substations the derived set misses:

| OSM set | Substations | No derived substation within 250 m | ...within 1 km | No HIFLD line end of any kind within 1 km |
|---|---:|---:|---:|---:|
| 230 kV+ | 6,780 | 19.6% | **16.2%** | 14.2% |
| 345 kV+ | 2,617 | 25.6% | 22.1% | 21.6% |
| 115–229 kV | 23,232 | 24.2% | 20.6% | 12.2% |
| all | 72,782 | 41.0% | 35.5% | 27.2% |

The derived set misses about one in six OSM 230 kV+ substations, mostly ones no HIFLD line ends at (the last
column). The HIFLD lines layer is older than OSM and leaves out some lines (see `hifld-grid-gaps/`).

**Hand check.** We labelled a random 50 (seed 76) of the 180 derived 230 kV+ points with no OSM substation
within 1 km on Esri aerial imagery ([`hand_check.csv`](hand_check.csv), one line each on what we saw):

| Label | Points | What it is |
|---|---:|---|
| substation | 7 | a switchyard OSM hasn't mapped, including two 500 kV yards (Anderson, TN; Pleasant Hill, MS) |
| plant | 13 | a power plant's switchyard or powerhouse, mostly hydro dams (Grand Coulee, Bath County) |
| tap | 15 | the line branches, turns or continues as another segment; no yard |
| error | 13 | nothing there: 7 lines ending in wind farm fields, 1 at the demolished Breed plant, the rest in empty land |
| unclear | 2 | a building compound with no visible switchyard |

So 40% of the unconfirmed points are real grid nodes and 56% aren't. Scaled to all 180, about 100 of the 6,469
derived 230 kV+ substations (1.6%) aren't substations: too few to move the headline, and set (a) below drops
all 180 anyway.

**The county headline**, holds a 230 kV+ substation, main restriction definition, 432 restricted against
2,712 unrestricted counties (`outputs/headline_rerun.csv`):

| Substations | Restricted | Unrestricted | Odds ratio (Fisher p) | Within-state odds ratio (95% CI), CMH p |
|---|---:|---:|---|---|
| derived 230 kV+ (original) | 59.3% | 50.4% | 1.43 (0.0007) | 1.55 (1.23–1.95), 0.0002 |
| (a) derived 230 kV+ with OSM within 1 km | 59.3% | 50.2% | 1.44 (0.0005) | 1.56 (1.24–1.97), 0.0001 |
| (b) OSM 230 kV+ | 62.3% | 52.6% | 1.49 (0.0002) | 1.63 (1.29–2.05), 0.00003 |
| either derived or OSM 230 kV+ | 64.4% | 54.6% | 1.50 (0.0002) | 1.67 (1.32–2.12), 0.00002 |

The headline doesn't change materially. The share of counties holding one rises with OSM, because OSM has
more 230 kV+ substations, but the gap between restricted and unrestricted counties stays about 9–10 points.

## The dataset

`dataset/us_substations.parquet` (GeoParquet) and `.csv`: 71,625 substations, 43,127 in both sources,
2,652 derived only and 25,846 OSM only. Each row has id, name, highest voltage (and each source's), source,
match distance, county FIPS, state and the county's restriction flag. Columns and licences are in
[`DATA_DICTIONARY.md`](DATA_DICTIONARY.md).

**Licence:** the combined file is **ODbL 1.0**, because it contains OSM features merged with HIFLD's, which
OSMF's Collective Database and Horizontal Layers guidelines treat as a Derivative Database. HIFLD's data is
public domain, so that's allowed; share-alike only means the file and anything built from it stay ODbL.
`dataset/us_substations_hifld_only.csv` has the 45,779 derived substations with no OSM-derived field, and is
public domain.

## The map

[`map/index.html`](map/index.html) is a static MapLibre page: counties shaded by restriction, substations
coloured by voltage (230 kV and up shown first; a menu shows all), filters by source, and a popup with name,
voltage and source. The URL keeps the view (`#zoom/lat/lon`), so an article can link straight to a place.
The basemap is OpenFreeMap (free, no key). Screenshot: `map_screenshot.png`.

**Map URL.** GitHub Pages isn't switched on for this repo, so there's no clean public URL yet. Today the map
opens at [raw.githack.com](https://raw.githack.com/fulton-ring/agent-content-demos/spike/us-substations-verified/us-substations-verified/map/index.html)
after a "one more step" click-through, which rules it out for embedding. Once a founder turns on Pages
(Settings → Pages → Deploy from a branch → `main`, `/ (root)`) and this PR merges, the map is at
`https://fulton-ring.github.io/agent-content-demos/us-substations-verified/map/`, with no build step. Locally:
`cd map && python3 -m http.server`, then open <http://localhost:8000>.

We chose a static page over a HIFLD Next layer because HIFLD Next has no substations layer to link to, and a
page in this repo shows the derived/OSM source of each point, which is the thing this spike checked.

## What didn't work or was changed

- **Overture with three bounding boxes (lower 48, Alaska, Hawaii) stalled** for over 20 minutes: DuckDB
  can't skip row groups with an `OR` of ranges. One box from the Aleutians to Maine takes about 5 minutes,
  and Canada and Mexico are dropped by the county join.
- **A first map was 18 MB.** Compact GeoJSON (short keys, 1 m coordinates, counties simplified to 500 m) brought
  it to about 12 MB, 1.8 MB gzipped. Vector tiles (PMTiles) would be smaller but need a build step.
- **Matching is by distance only**, not by name: HIFLD names are placeholders for half the derived points, and
  OSM names are often missing. A derived point within 1 km of an OSM substation could be a tap beside it.

## What this doesn't show

- **OSM isn't ground truth.** It's volunteer-mapped; the hand check is the only ground truth here, and it
  covers 50 points.
- **Spare capacity, or cause.** As in the county spike: a substation isn't room on the grid, and nothing here
  says why counties restrict.
- **Sabin Center terms.** Its site gives no licence for the restriction data. We publish only a yes/no flag per
  county with a citation, and ask on the issue whether to get written permission.

## What we looked at first

Overture's GeoParquet (OSM with tags, versioned) over Overpass, which failed in `hifld-grid-gaps/`. GeoPandas'
nearest join for matching, statsmodels for the CMH test, and MapLibre GL with OpenFreeMap tiles for the map,
rather than a kepler.gl export or a HIFLD Next layer (none exists). OSMF's
licence guidelines for the ODbL question. It's one marimo notebook, `verify.py`, plus `hand_check_chips.py`
(adapted from `hifld-grid-gaps/`) for the imagery.
