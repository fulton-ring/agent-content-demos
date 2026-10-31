# An OpenStreetMap contribution of the substations OSM is missing (prepared, not submitted)

Spike for [issue #170](https://github.com/fulton-ring/agent-content-demos/issues/170). `us-substations-verified/`
found 180 places where HIFLD Next's 230 kV+ lines end but OpenStreetMap had no substation within 1 km. This folder
turns them into a package a founder can review and hand to the OSM community. **Nothing was posted or edited:**
no OSM edits, no forum post, no MapRoulette challenge, no contact with any utility or agency. The drafts say DRAFT.

**Short answer.**

- None of the 180 has been mapped since September.
- Imagery shows a real yard at **10 distinct places** (12 points). 29 points are unclear and 139 have no yard.
- That gives **36 MapRoulette tasks** once duplicates and two points the records rule out are dropped.
- Names come out sparse on purpose: 3 of the 10 yards get a proposed name, 8 an operator, 9 a voltage.
- A near-identical attempt in March 2026 was reverted by the OSM community, so the package is built to go through
  forum review first. See [`rules.md`](rules.md).

## Run it

```bash
./run.sh            # needs uv; first run ~30 min (one Overpass query per point to a slow public mirror)
./run.sh --chips    # also redraws the Esri imagery chips and imagery dates (data/chips/, not committed)
```

Read the notebook with its output: `uv run marimo edit contribution.py`. Later runs reuse `data/` (about a minute); delete `data/overpass/` to re-check OSM.

## What's here

| File | What it is |
|---|---|
| `contribution.py` | The marimo notebook: OSM re-check, HIFLD/EIA joins, labels, tags, outputs |
| `chips.py` | Draws the imagery chips we labelled from and looks up each chip's Esri imagery date |
| `imagery_labels.csv`, `imagery_dates.csv` | Hand labels for all 180 points (with a rough outline when a yard is visible); Esri's date and source per point |
| `records_lookup.csv`, `records_search_log.csv` | Values found in other public records (URL plus quote), and the timed search per point |
| `outputs/substations_package.csv` | One row per point: OSM status and check time, imagery verdict and date, proposed tags with sources and confidence |
| `outputs/maproulette_tasks.geojson` | 36 tasks in MapRoulette's line-by-line format |
| `outputs/newly_public.csv` | Exactly what would go on the map, for the security decision |
| `drafts/` | Forum post, OSM US note, MapRoulette challenge text, all DRAFT |
| `rules.md` | What OSM's rules require here, with quotes and links |

## Data (all public)

| Input | Source |
|---|---|
| The 180 points and the earlier 50 labels | `us-substations-verified/dataset/us_substations.csv` and `hand_check.csv`, read from `main` |
| Current OSM | Overpass API ([maps.mail.ru mirror](https://maps.mail.ru/osm/tools/overpass/); overpass-api.de was unreachable from here), data as of 2026-10-31 17:38–18:53 UTC |
| Line names, owners, voltages | [HIFLD Next](https://hifld.publicenvirodata.org/) Transmission Lines v1.0.0 (US federal, public domain) |
| Power plants | [EIA-860M](https://www.eia.gov/electricity/data/eia860m/), September 2026 |
| Imagery | Esri World Imagery, which OSM allows for tracing. No Google. |
| Other records | ISO queue studies, PUC orders, TVA, BLM and FERC pages, each URL in `records_lookup.csv` |

`outputs/substations_package.csv` contains OSM ids and names, so it is ODbL 1.0 (© OpenStreetMap contributors).
## Results (from one clean `./run.sh`, `outputs/run_log.txt`)

**OSM re-check.** 0 of 180 points now have an OSM substation within 1 km. A control point, a derived substation OSM
does have, returns its substation, so the query works. 67 points have an OSM *power plant* within 1 km.

**Imagery** (Esri, dated 2018-03 to 2026-05, median 2025-05):

| Label | Points | Yard visible |
|---|---:|---|
| substation | 6 | 6 yes |
| plant (lines end at a power plant) | 51 | 6 yes, 22 unclear, 23 no |
| tap (line continues or branches) | 52 | 1 unclear, 51 no |
| error (wind farm field, empty land) | 55 | 55 no |
| unclear | 16 | 6 unclear, 10 no |

Real grid nodes (substation or plant) are 57 of 180 (32%), against 40% in the earlier sample of 50.

- **Duplicates:** Pleasant Hill, Croydon and Plum Point each appear twice, 200 m apart, as two line ends in one yard. The notebook merges points within 600 m.
- **Dropped by the records:** Breed, IN (AEP decommissioned it) and a NYSEG line junction in NY.

**Agreement with the earlier hand check.** On the same 50 points, labelled blind by a different labeller:

- Same label on **45 of 50**.
- Same "real grid node or not" call on **48 of 50**.
- Disagreements:
  - two earlier "substation" now "plant": a wind farm and a solar farm collector yard (still yards, so still tasks);
  - two earlier "substation" now "tap": 48542 in NY, where the records also find no substation, and 7128, left as a tap;
  - Breed, earlier "error", now "unclear". The records say the yard was decommissioned.

**Names, operators and voltages** for the 10 confirmed yards:

| Field | Proposed | High confidence (two sources agree) | Not proposed |
|---|---:|---:|---|
| name | 3 (Anderson, Lowmoor, Pleasant Hill) | 2 | plant yards (HIFLD/EIA give the plant's name); HIFLD placeholders |
| operator | 8 | 5 | records contradict HIFLD at Desert View and Birds Landing (unclear points) |
| voltage | 9 | 5 | Carvers Creek: PJM study says 115 kV, HIFLD 230 kV |

- **HIFLD (public domain):** a usable name for 27 of 180 points, an owner for 153, a voltage for all 180.
- **Other records search:** 17 points, one search each, found values for 11. The 35 values come from:
  - federal pages (TVA, BLM, FERC Federal Register): 9;
  - EIA: 3;
  - ISO queue studies: 10;
  - PUC orders: 9;
  - utility reports: 3;
  - other: 1.
- **Licence:** only the 12 federal values are public domain (`osm_ok = yes`). The other 23 are kept as corroboration and never proposed, because OSM's Legal FAQ wants written permission for non-public-domain sources.

**Time per point for the records search: median 1.0 minute, 17 minutes for 17 points.**

A Claude agent searched the web, with timestamps before and after each point. A person checking each value against
its source would add a few minutes; at that rate all 2,652 unconfirmed derived substations would take about two days.

## What becomes newly public

`outputs/newly_public.csv` lists the 36 yards, by state and voltage:

- **Voltage:** 5 at 500 kV, 1 at 345 kV, 30 at 230 kV.
- **States:** 19, led by CA (7) and VA (4).
- **What's new:** HIFLD's lines already end at these coordinates in a public federal dataset. Mapping them in OSM adds:
  - that a yard really is there;
  - its fence outline;
  - its voltage;
  - for 3 yards, a name. Nothing inside the fence: the instructions forbid it.
- **Decision for the founders:** whether that is acceptable. The five 500 kV yards are Anderson (TN), Pleasant Hill (MS), Bath County (VA, a pumped-storage plant), Plum Point (AR) and a plant in AZ.

## The rules, in short (details in `rules.md`)

- **Not an import:** it's hand mapping from imagery with MapRoulette hints. Nothing is copied in bulk, so neither
  the Import Guidelines nor the Automated Edits code of conduct strictly applies. But no OSM page says so.
- **The precedent:** in March 2026 the community reverted PowerGEM's similar uploads and asked for the Organised
  Editing Guidelines. We're a company too, and we built HIFLD Next, so the drafts disclose both. They also ask in
  the existing forum thread before anything goes live, and offer to write an organised-editing page.
- **Licence:** HIFLD lines are public domain (data.gov; the OSM wiki's HIFLD page). Points and outlines are our own
  observations on Esri imagery, which Esri permits. Names from utility, ISO or state documents aren't proposed.

## What didn't work or was changed

- **Overpass:** overpass-api.de and three mirrors were unreachable; ohsome's data stops in July 2026. maps.mail.ru
  timed out (504) on one query for all 180 points; one query per point with retries works, at ~30 s each.
- **Names:**
  - The first rule (the name all lines share) lost Anderson, because a line passing within 200 m names other places.
  - A plain majority then picked the far end's name ("Harmony Village", "Doubs").
  - The final rule counts placeholders too and needs a strict winner, so a single line gives no name.
- **Records:** EIA's "Enterprise Energy Facility" sits 0.6 km away but in the wrong county. We dropped it.

## What this doesn't show

- **Labels:** made by Claude subagents looking at one Esri chip per point, not by a person on the ground. The 48 of 50
  agreement is with the earlier spike's labels, not with ground truth. Imagery is up to 8 years old.
- **Outlines:** rough boxes read off a 100 m grid. Mappers draw the real fence, so these are for review only.
- **Time per point:** agent time, not person time, over only the 17 likeliest points, not all 180.
- **Screenshots:** none. The chips are Esri imagery and stay in `data/chips/`, as in `us-substations-verified/`.

## What we looked at first

Overpass (the standard live-OSM query) with ohsome as a fallback (too stale); MapRoulette's own line-by-line
GeoJSON format; Esri's World Imagery `identify` endpoint for dates; the OSM wiki and forum for the rules. The chip
drawing is adapted from `us-substations-verified/hand_check_chips.py`.
