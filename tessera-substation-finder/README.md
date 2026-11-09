# Can open satellite embeddings find the substations the public HIFLD map no longer has?

HIFLD Next has no public substation layer (DHS withdrew it in 2022, see [`hifld-grid-gaps/`](../hifld-grid-gaps/)), so
studies fall back on OpenStreetMap, which has gaps. We tested whether [TESSERA](https://github.com/ucam-eo/tessera)'s
free, CC0 10 m satellite embeddings can find substations in Tennessee (the TVA core) and New York, using OSM
substations as the answer key. Issue [#195](https://github.com/fulton-ring/agent-content-demos/issues/195).

**Short answer: they recognise substations, but they can't search for new ones yet.** A small CNN finds 76% of
held-out OSM substations (90% of those at 100 kV and above) while passing only about 1 in 100 random patches. But
when it scans whole tiles, only 8% of its detections are near an OSM substation. Of 20 of the others checked on aerial
photos, none was a substation. They were houses, farms, quarries, schools and factories. Of the 20 highest-scoring
places where a HIFLD Next line ends more than 1 km from any OSM substation, 1 was an unmapped switchyard and 2 were
hydro dams.

Everything is in one marimo notebook, [`substation_finder.py`](substation_finder.py).

## How to run

```bash
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/), about 10 GB of free disk and 8 GB of memory. With an empty `data/` it
range-reads about 46 GB from Source Cooperative. On a 4-CPU cloud machine the patch reads took 24 minutes and the
whole run about 50 minutes. Reruns reuse `data/` and take about 10 minutes, most of it CNN training and scanning on the
CPU. To read the notebook with its outputs: `uv run marimo edit substation_finder.py`.

## Data

All public, all downloaded at run time. Nothing downloaded is committed.

| Data | Copy used | Licence |
|---|---|---|
| TESSERA v1 annual embeddings, 2024, 128 bands at about 10 m | [Source Cooperative `tessera/tessera/npy/v1`](https://source.coop/tessera/tessera), HTTP range reads, no account | CC0 |
| OSM `power=substation` with `voltage` tags | [Overture Maps](https://docs.overturemaps.org/) `base/infrastructure`, release `2026-09-23.0` | ODbL |
| Transmission Lines | [HIFLD Next](https://hifld.publicenvirodata.org) GeoParquet `v1.0.0` | As published |
| State boundaries | Census 2024 cartographic boundaries, 1:500k | Public domain |
| Aerial photos for the hand check | NAIP 2021 to 2023 through [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/dataset/naip) | Public domain |

We used TESSERA v1 because the v2 beta store on Source Cooperative covers only part of both states for 2024.

## Method

- **Answer key:** 3,922 OSM substations (New York 2,461, Tennessee 1,461), classed by their highest voltage tag.
  230 kV+: 110 New York and 34 Tennessee. 100–229 kV: 757 and 682. Under 100 kV: 650 and 713. No voltage tag: 944 and 32.
- **Split:** both states are cut into 0.5° blocks, and a quarter of the blocks are held out. Every score below is on
  held-out blocks.
- **Samples:** a 40 × 40 pixel patch (400 m) around every substation. As many negative patches again, at random points
  more than 1 km from any OSM substation.
- **Models:** a logistic-regression probe on single pixels, and a 4-layer CNN on 32 × 32 crops (320 m). Each model's
  threshold lets 1% of validation negatives through.
- **Scan:** 48 random held-out 0.1° tiles (24 per state, about 4,700 km²). A detection is correct if an OSM substation
  is within 300 m.
- **Line ends:** both ends of every HIFLD Next line in the two states, kept where more than 1 km from any OSM
  substation. 502 places, 452 of them touching another line (taps). The CNN scores the best 320 m window in the 640 m
  around each.
- **Hand check:** NAIP chips of the 20 top-scoring line-end places (at least 500 m apart) and 20 random scan detections
  with no OSM substation within 300 m. The verdicts are in [`hand_check.csv`](hand_check.csv). It is keyed by a hash of
  each place, not its location, because the issue asks us not to publish a list of unmapped sites. The chips stay in
  `data/chips/`.

## Results

All numbers come from `outputs/`, written by the run.

**Held-out recall** (`outputs/heldout_recall.csv`), both states, at the 1%-false-positive threshold:

| Model | AUC | 230 kV+ (29) | 100–229 kV (341) | Under 100 kV (407) | No tag (204) | All (981) |
|---|---:|---:|---:|---:|---:|---:|
| Pixel probe | 0.958 | 0.59 | 0.38 | 0.22 | 0.07 | 0.26 |
| CNN | 0.983 | 0.90 | 0.90 | 0.68 | 0.69 | 0.76 |

The CNN is similar in both states: 75% in New York and 78% in Tennessee. Recall rises with fenced area, from 52%
under 500 m² to 90% from 2,000 m² up ([`recall_by_area.png`](outputs/recall_by_area.png)). That supports the
expectation that small distribution yards are harder, though even many of those were found.

**Scan of 48 held-out tiles** (`outputs/scan_precision_recall.csv`). These tiles hold 99 OSM substations: 1 at 230 kV+,
30 at 100–229 kV, 57 under 100 kV and 11 untagged.

| Model, cutoff | Detections | Within 300 m of OSM | Precision | Recall, all | 100–229 kV | Under 100 kV |
|---|---:|---:|---:|---:|---:|---:|
| Probe, 0.94 | 2,663 | 324 | 0.12 | 0.63 | 0.70 | 0.65 |
| CNN, 0.957 | 655 | 52 | 0.08 | 0.52 | 0.77 | 0.32 |
| CNN, 0.99 | 383 | 54 | 0.14 | 0.52 | 0.77 | 0.37 |

A detection has no voltage, so precision is overall only. The probe's higher precision comes from splitting each yard
into many small detections.

**Hand check** (`hand_check.csv`): of 20 scan detections with no OSM substation nearby, **0 were substations**. All 20
were ordinary land: homes, farms, quarries, schools, factories and forest. So precision against OSM is close to the
real precision. Of the 20 top line-end places, **1 was a substation** (a large switchyard with no OSM outline),
**2 were hydro dams**, 1 was unclear and 16 were something else. Most of those were commercial or industrial land.
In total the CNN flags 139 of the 502 line-end places (`outputs/line_end_flags.csv`).

**Cost:** $0, with no account or key. About 46 GB of range reads from an empty `data/`, 8.2 GB kept in `data/`, and
about 10 minutes of CPU per rerun on 4 cores (CNN training 2.5 minutes, tile scan 3 minutes). See
`outputs/summary.json`.

## What didn't work

- **Precision.** The random negatives are mostly forest and fields, so the CNN learned "developed land with hard
  surfaces". A useful scanner needs hard negatives such as industrial parks, quarries, parking lots and farmsteads.
- **Small test samples where it matters:** only 29 held-out substations at 230 kV+, and 1 among the scanned tiles.
- **Column-window reads.** A `.npy` row is contiguous, so a 40-pixel window needs one request per row. Through our
  connection that ran at about 200 requests a second. We read 40 whole rows per patch instead, which fetches 20 to 30
  times the bytes we keep. Source Cooperative ignored multi-range requests and returned the whole 130 MB file.
- **Line ends are mostly taps.** 452 of the 502 far ends touch another line, as `hifld-grid-gaps/` found nationally,
  so most of these places have no substation to find.

## What it doesn't show

- One year (2024), two states, one embedding model, and OSM as the answer key. OSM itself was partly backfilled from
  the old HIFLD layer.
- The hand check is 40 chips judged by the worker agent from photos, not a field visit.
- We didn't test hard negatives, larger patches or TESSERA v2. Those are the next things to try.

## What we looked at first

- **`geotessera` and Source Cooperative's `tessera.py` reader** (kerchunk plus xarray). Both read the same row-granular
  byte ranges. We use the published tile index (byte offsets, shapes and transforms) with plain `httpx` range
  requests, which keeps the read visible in the notebook.
- **`geoembeddings-facility-finder/`** for the overall design (classifier, held-out scan, NAIP hand check), and
  **`us-substations-verified/`** and **`hifld-grid-gaps/`** for the OSM and HIFLD Next line-end code.

The notebook is about 1,280 lines, of which about 1,100 are code. That is over the 1,000-line budget, mostly from
marimo's per-cell import and return lists and the aerial-chip drawing for the hand check.
