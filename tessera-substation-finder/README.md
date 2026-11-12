# Can open satellite embeddings find the substations the public HIFLD map no longer has?

HIFLD Next has no public substation layer (DHS withdrew it in 2022, see [`hifld-grid-gaps/`](../hifld-grid-gaps/)), so
studies fall back on OpenStreetMap, which has gaps. We tested whether [TESSERA](https://github.com/ucam-eo/tessera)'s
free, CC0 10 m satellite embeddings can find substations in Tennessee (the TVA core) and New York, using OSM
substations as the answer key. Issue [#195](https://github.com/fulton-ring/agent-content-demos/issues/195); the
hard-negative retraining is [#247](https://github.com/fulton-ring/agent-content-demos/issues/247).

**Short answer: they recognise substations, but they can't search for new ones yet.** A small CNN finds 76% of
held-out OSM substations (90% of those at 100 kV and above) while passing only about 1 in 100 random patches. But
when it scans whole tiles, only 8% of its detections are near an OSM substation. Of 20 of the others checked on aerial
photos, none was a substation. They were houses, farms, quarries, schools and factories. Of the 20 highest-scoring
places where a HIFLD Next line ends more than 1 km from any OSM substation, 1 was an unmapped switchyard and 2 were
hydro dams.

**Hard negatives (#247) make it several times more precise at strict cutoffs, but not yet a scanner.** Retrained
with 3,426 patches of developed land and of its own mistakes, the CNN reaches 23% scan precision against OSM at a 0.90
cutoff and 37% at 0.97, still finding 90% and 87% of the 100–229 kV substations in the scan tiles. The first CNN
reaches 14% at best. At the threshold rule used before (1% of random patches), precision *falls* to 5%, because that
rule is calibrated on forest and fields, which the new model already rejects. Of 20 new "wrong" detections checked on
photos, none was a substation. The result also depends on which hard negatives are drawn (see What didn't work).

Everything is in one marimo notebook, [`substation_finder.py`](substation_finder.py).

## How to run

```bash
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/), about 20 GB of free disk and 14 GB of memory (a fresh run peaked at
12.8 GB). With an empty `data/` it range-reads 61.5 GB from Source Cooperative. From a clean checkout on a 4-CPU cloud
machine it took 42 minutes: 7.5 for the patch reads, 7 to read and scan the 48 tiles, 4.5 to mine 40 more tiles and 6.5
for the two CNNs. Reruns reuse `data/` and take about 30 minutes. To read the notebook with its outputs: `uv run marimo edit substation_finder.py`.

## Data

All public, all downloaded at run time. Nothing downloaded is committed.

| Data | Copy used | Licence |
|---|---|---|
| TESSERA v1 annual embeddings, 2024, 128 bands at about 10 m | [Source Cooperative `tessera/tessera/npy/v1`](https://source.coop/tessera/tessera), HTTP range reads, no account | CC0 |
| OSM `power=substation` with `voltage` tags | [Overture Maps](https://docs.overturemaps.org/) `base/infrastructure`, release `2026-09-23.0` | ODbL |
| Transmission Lines | [HIFLD Next](https://hifld.publicenvirodata.org) GeoParquet `v1.0.0` | As published |
| State boundaries | Census 2024 cartographic boundaries, 1:500k | Public domain |
| OSM land use (industrial, commercial, retail, works, quarry, landfill, farmyard, school, residential) | Overture `base/land_use`, same release | ODbL |
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
- **Hard negatives (section 10):** all more than 1 km from any OSM substation and in training blocks only. 2,236
  OSM land-use places (at most 150 per class and state, `power=*` excluded) and 1,190 detections scoring 0.5 or more
  from the first CNN on 40 random training-block tiles. The same CNN is retrained from scratch on the first
  model's samples plus these, with the same seed and the same threshold rule (1% of validation *random* negatives).
  The 806 land-use places inside the 48 held-out scan tiles are a second test.

## Results

All numbers come from `outputs/`, written by the run.

**Held-out recall** (`outputs/heldout_recall.csv`), both states, at the 1%-false-positive threshold:

| Model | AUC | 230 kV+ (29) | 100–229 kV (341) | Under 100 kV (407) | No tag (204) | All (981) |
|---|---:|---:|---:|---:|---:|---:|
| Pixel probe | 0.958 | 0.59 | 0.38 | 0.22 | 0.07 | 0.26 |
| CNN | 0.983 | 0.90 | 0.90 | 0.68 | 0.69 | 0.76 |

The CNN finds 75% in New York and 78% in Tennessee, more for bigger yards ([chart](outputs/recall_by_area.png)).

**Scan of 48 held-out tiles** (`outputs/scan_precision_recall.csv` and `hard_negatives_scan.csv`). These tiles hold 99
OSM substations: 1 at 230 kV+, 30 at 100–229 kV, 57 under 100 kV and 11 untagged. Recall is by voltage class; a
detection has no voltage, so precision is overall only. The probe splits each yard into many small detections.

| Model, cutoff | Detections | Within 300 m of OSM | Precision | 230 kV+ | 100–229 kV | Under 100 kV | All |
|---|---:|---:|---:|---:|---:|---:|---:|
| Probe, 0.94 (1% rule) | 2,663 | 324 | 0.122 | 1/1 | 0.70 | 0.65 | 0.63 |
| CNN, 0.957 (1% rule) | 655 | 52 | 0.079 | 1/1 | 0.77 | 0.32 | 0.52 |
| CNN, 0.99 | 383 | 54 | 0.141 | 0/1 | 0.77 | 0.37 | 0.52 |
| Hard-negative CNN, 0.276 (1% rule) | 1,178 | 59 | 0.050 | 1/1 | 0.90 | 0.37 | 0.55 |
| Hard-negative CNN, 0.90 | 247 | 56 | 0.227 | 0/1 | 0.90 | 0.46 | 0.56 |
| Hard-negative CNN, 0.97 | 137 | 51 | 0.372 | 0/1 | 0.87 | 0.39 | 0.51 |
| Hard-negative CNN, 0.99 | 72 | 38 | 0.528 | 0/1 | 0.70 | 0.23 | 0.35 |

**Hand check** (`hand_check.csv`): of 20 scan detections with no OSM substation nearby, **0 were substations**. All 20
were ordinary land: homes, farms, quarries, schools, factories and forest. So precision against OSM is close to the
real precision. Of the 20 top line-end places, **1 was a substation** (a large switchyard with no OSM outline),
**2 were hydro dams**, 1 was unclear and 16 were something else. Most of those were commercial or industrial land.
In total the CNN flags 139 of the 502 line-end places (`outputs/line_end_flags.csv`).

**Cost:** $0, with no account or key. 61.5 GB of range reads and 82 MB of other downloads from an empty `data/`,
16.3 GB kept in `data/`, and 42 minutes on 4 cores from a clean checkout (`outputs/summary_clean_checkout_run.json`,
written before the hand-check verdicts; `summary.json` is the rerun after them, with identical results).

**Hard negatives** (`outputs/hard_negatives_*.csv`). On held-out patches, at its own 1% rule, the retrained CNN finds
93% of 230 kV+ (first CNN 90%), 94% of 100–229 kV (90%), 67% under 100 kV (68%) and 78% overall (76%); AUC 0.975
against 0.983, passing 1.9% of held-out random patches (first CNN 1.3%). Developed places in the scan tiles flagged (`hard_negatives_land_use_flags.csv`): 31% → 20%, for
example retail 81% → 23% and industrial 74% → 57%. Hand check: of 20 random 1%-rule detections with no OSM substation
within 300 m, **0 were substations**: 12 farms, woods or rural homes, 5 commercial, industrial or school sites, 2
housing areas and a canal lock. `hand_check.csv` also holds 20 verdicts from an earlier run (also 0 substations).

## What didn't work

- **Precision, still.** Random negatives are mostly forest and fields, so the first CNN learned "developed land with
  hard surfaces". Hard negatives help only at cutoffs picked from a sweep on the test tiles, so 23–37% is optimistic,
  and even then a reviewer sees two to three wrong places for each right one. A threshold tuned on held-out hard
  negatives would be the fair test.
- **Unstable.** An earlier run with a different land-use draw (unsorted rows) scored 9.5% at its 1% rule and 24% at
  0.97 with 97% of 100–229 kV found, and cut developed-place flags to 6%. The Overture land-use query also returned
  31,689 to 31,783 places in different runs, which we haven't explained.
- **Memory.** Fresh runs first died at 13.9 GB; streaming reads into arrays and a memory-mapped training set fixed it.
- **Column-window reads.** A window needs one HTTP request per `.npy` row (about 200 a second here), and multi-range
  requests return the whole 130 MB file, so we read whole rows and fetch 20 to 30 times the bytes we keep.

## What it doesn't show

- One year (2024), two states, one embedding model, and OSM (partly backfilled from old HIFLD) as the answer key.
- The hand checks are photos judged by the worker agent, not field visits. Only 29 held-out substations are 230 kV+,
  and 1 in the scan tiles.
- We didn't test larger patches, a threshold tuned on held-out hard negatives, or TESSERA v2.
- The first CNN's numbers depend on floating-point order. Running this notebook gives exactly the published #195
  numbers, but one intermediate version gave 7.2% scan precision instead of 7.9% for the same model and data.

## What we looked at first

- **`geotessera` and Source Cooperative's `tessera.py` reader** read the same row-granular byte ranges; we use the
  published tile index with plain `httpx` range requests, which keeps the read visible in the notebook.
- **`geoembeddings-facility-finder/`** for the design, and **`us-substations-verified/`** and **`hifld-grid-gaps/`**
  for the OSM and HIFLD Next line-end code. Hard-negative mining is the standard detector-training technique.

The notebook is about 1,790 lines, over the 1,000-line budget: marimo boilerplate, chip drawing, the #247 section.
