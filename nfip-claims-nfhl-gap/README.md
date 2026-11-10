# How many flood insurance claims can't FEMA's own flood maps place?

OpenFEMA removes the NFIP Community Layer on November 9, 2026. People map National Flood
Insurance Program (NFIP) claims by community by joining each claim's community ID (CID) to
that layer. The only other public source of NFIP community boundaries is FEMA's National
Flood Hazard Layer (NFHL). This spike joins every NFIP claim to both and asks how many claims
the NFHL can't place, and why.

**Answer: the NFHL can't place 4.4% of claims, and the gap is real, not bookkeeping.** About
98% of the claims it misses are in communities where the NFHL has no flood map at all, so a
county crosswalk recovers almost nothing. Mapping NFIP claims by community after November 9
needs the preserved Community Layer (HIFLD Next's copy, which this notebook reads).

## Run it

```bash
./run.sh
```

Needs [uv](https://docs.astral.sh/uv/) and internet access, no key or account. It runs
`notebook.py` (a [marimo](https://marimo.io) notebook) as a script and saves the output to
`results/last-run.txt`. A first run took 17 to 37 minutes in our runs, mostly the NFHL point checks;
a second run the same day reuses `data/` and takes seconds. `uv run marimo edit notebook.py`
opens the notebook with its tables.

## The data

All public, downloaded at run time into `data/` (not committed):

- **NFIP Redacted Claims v3** from the OpenFEMA API (`/api/open/v3/NfipClaims`), three
  columns. The bulk Parquet file returns HTTP 403 to scripts, so the notebook pages the API.
- **NFIP Community Layer**, Comprehensive and No Overlaps Whole, from
  [HIFLD Next](https://hifld.publicenvirodata.org/collections/openfema/datasets/nfip-community-boundaries)
  (GeoParquet, v1.0.0).
- **NFHL** from FEMA's MapServer: Political Jurisdictions (layer 22) attributes, plus point
  queries against layers 22 and 28 (Flood Hazard Zones).
- **NFIP Community Status Book** from OpenFEMA.

## Results (pull of 2026-11-10)

From `results/last-run.txt`, of 2,725,989 claims. Every number below is the same as the
first run on 2026-11-06, before OpenFEMA's removal date:

| Source | Claims placed | Share |
|---|---|---|
| Community Layer, Comprehensive | 2,708,418 | 99.36% |
| Community Layer, No Overlaps Whole | 2,697,033 | 98.94% |
| NFHL Political Jurisdictions | 2,607,263 | 95.64% |

These reproduce the earlier analysis (99.4%, 98.9%, 95.5%) closely.

**The gap.** The NFHL misses 118,726 claims. 15,218 of them carry retired or placeholder
CIDs (such as `999999`, or `125098` in Miami-Dade) that no source can place. The rest,
**103,460 claims in 1,617 real communities**, are the NFHL's own gap. The top four are the
hand-checked ones: Slidell, LA (9,935), St. Charles Parish, LA (7,603), Beaumont, TX (7,312)
and Port Arthur, TX (6,998). The earlier analysis said 106,335 claims in 1,756 communities;
we can't reproduce its exact filter because its scripts were lost.

**Why.** For each missing community, a point inside its Community Layer polygon, asked of
the NFHL:

| Cause | Communities | Claims | Share |
|---|---|---|---|
| No map: nothing in the NFHL at the point | 1,576 | 89,689 | 86.7% |
| No map: inside a political polygon, but no flood zone (Slidell) | 6 | 11,423 | 11.0% |
| No Community Layer polygon to check | 9 | 1,768 | 1.7% |
| Mapped under another community's CID | 18 | 471 | 0.5% |
| Mapped: flood zone, but no political polygon | 2 | 71 | 0.1% |
| Mapped under the county's or parish's CID | 6 | 38 | 0.0% |

1,118 of the 1,576 unmapped communities are in counties with nothing in the NFHL at all.
St. Charles Parish and Jefferson County, Texas (Beaumont, Port Arthur) are among them.

**County crosswalk.** 99,352 of the 103,460 claims carry a county code, but only 18,367 are
in a county whose own CID has an NFHL polygon, and 11,396 (mostly Slidell's) are in
communities that lie inside that polygon. Only **62 claims** land somewhere the NFHL actually
has a flood zone. The NFHL plus a crosswalk places 95.65% of claims, up from 95.64%.

**Status Book.** 2,921 of 22,791 participating communities (12.8%) have no NFHL polygon
under their CID: New York 603, Maine 435, Texas 281, Vermont 110, Minnesota 107. Full list
in `results/status-book-no-nfhl-by-state.csv`. (The earlier analysis said 3,141.)

**ArcGIS Online survived November 9.** Checked 2026-11-10, FEMA's ArcGIS Online copy (item
`4b712b99d43d41cb9328e94891520a63`, *NFIP Community Layer _flattened_ 2024v1*) is still
public, answers a count query with 29,898 features (the same as No Overlaps Whole and as on
2026-11-06) and returns rows with polygons. OpenFEMA's three `NfipCommunityLayer*` endpoints
are gone in substance: they still answer HTTP 200 and still report the old counts (51,943,
29,898, 37,918), but every query and bulk download returns zero rows. A script that checks
only the status code or the count would think they are up. See
`results/arcgis-online-check.json`.

**Run time:** 2,217 s for the full fresh run from a clean checkout on 2026-11-10 (earlier
runs took 1,050 and 1,598 s; the NFHL server's speed varies). That run's NFHL point checks
timed out for 4 communities (73 claims); `results/last-run.txt` is the same-day rerun on its
cached data, which retried them and took 16 s.

## Files

- `notebook.py`: the whole analysis, top to bottom.
- `handcheck.md`: what we found for Slidell, St. Charles Parish, Beaumont and Port Arthur.
- `results/gap-by-community.csv`: one row per CID the NFHL lacks, with claims, Status Book
  fields, the checked point, what the NFHL has there and the cause.
- `results/placement.csv`, `results/status-book-no-nfhl-by-state.csv`,
  `results/arcgis-online-check.json`, `results/last-run.txt`.

## What didn't work, and what this doesn't show

- **FIRM panels were the wrong test.** The first version asked whether a FIRM panel (layer 3)
  covered each point. Panel rectangles run over county lines and water, so 312 communities
  looked mapped by a neighbor's panel with no flood zone under it. Flood Hazard Zones
  (layer 28) are the test now.
- **One point per community.** A community partly on a digital map gets the answer for one
  spot in its largest piece. The 89,689 figure could hide a few partly mapped places.
- **FEMA's NFHL server drops connections.** Calls retry with backoff, results are cached in
  chunks, and a point that never answers is reported and retried on the next run.
- **Snapshots.** The NFHL changes as maps go effective (Buchanan County, MO has a map due
  11/13/26) and claims update monthly. The Community Layer is frozen at December 2024.
- **We looked first** for a published claims-to-NFHL crosswalk and found none. The match is
  a pandas `isin` on CIDs, and the cause check uses the NFHL's own REST query API.
