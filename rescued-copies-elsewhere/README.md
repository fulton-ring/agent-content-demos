# Can you tell whether a rescued copy is still current, from the copy alone?

When an agency's portal goes dark, the usual advice is to compare a rescued copy with the live original. That
fails exactly when you need it. This spike writes the check as a six-point checklist that doesn't need the
original. It asks two things: what metadata the HIFLD rescue kept, and whether the checklist works on copies
held by DataLumos, Source Cooperative and Harvard's data.gov archive. Issue: #206.

It builds on `rescued-data-currency/` (#110) and `hifld-next-layer-currency/` (#171), and changes neither.
Everything is in one [marimo](https://marimo.io) notebook, [`copies_currency.py`](copies_currency.py), which reads
top to bottom: the checklist, the inputs, Part 1 (HIFLD metadata kept or lost), Part 2 (copies held by others),
the scores, the #171 restatement, and what dataindex.us and ALFRED cover.

## Run it

```bash
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/) and internet access, and no key or account. It takes about 3 to 4
minutes and writes:

- `outputs/hifld_fields.csv`: for each of the 20 HIFLD layers, six metadata fields as the original data.gov
  record, the DataLumos deposit and HIFLD Next each have them;
- `outputs/copy_scores.csv`: one row per copy (38): each check scored `copy`, `hand` or `no`, and the verdict;
- `outputs/summary.json`: every number below;
- `outputs/last-run.txt`: the printed output.

`uv run marimo edit copies_currency.py` opens it with its tables.

## The checklist

| # | check | the copy answers it itself when its metadata has... |
|---|---|---|
| 1 | upstream still publishing | a source URL in a field, and the URL still answers |
| 2 | newest record date | a temporal-coverage field, or open files with declared date columns |
| 3 | record count | a record or feature count |
| 4 | source last-modified | the source's own last-modified date, not the copy's |
| 5 | update cadence | an update-frequency field |
| 6 | vintage label | both the capture date and the source's date |

A copy can be **checked from the copy** when checks 1 and 4 both pass: a script can fetch the source and compare
dates. It **can't be checked** when no upstream is left (#171's hand checks). Everything else is **by hand**. Text
in a description or README counts only as "by hand", because a person has to read it.

## Where the data comes from

All public, read at run time: #171's `layer_currency.csv` from `main`; HIFLD Next's
[STAC API](https://hifld.publicenvirodata.org/stac); [DataCite's API](https://api.datacite.org) for DataLumos
deposits (the DOI metadata DataLumos registers; DataLumos's own pages return 403 to scripts);
[Harvard LIL's data.gov archive](https://source.coop/harvard-lil/gov-data) on Source Cooperative, which saved every
data.gov record between November 2024 and February 2025; and Source Cooperative's product API and READMEs.

**Samples.** HIFLD: 20 layers drawn with seed 206 from the 36 that #171 checked by hand *and* that have an
archived data.gov record (185 of the 330 layers have one). DataLumos: 6 deposits drawn with seed 206 by project
number, leaving out HIFLD Open deposits. Harvard: 6 records drawn with seed 206. Source Cooperative has no public
listing API we could find, so it gets 6 US federal mirrors from the site's search: the SeerAI HIFLD archive,
CEJST, CDC's SVI, PAD-US 3.0, the National Wetlands Inventory and USGS's Watershed Boundary Dataset.

## Results

From the run of 2026-11-11 (`./run.sh`; numbers from `outputs/summary.json`). Cost $0.

**Copies scored:** 38. That's 20 in HIFLD Next, 6 in DataLumos, 6 in Source Cooperative and 6 in Harvard's
data.gov archive.

**Whether currency can be checked:**

| holder | from the copy | by hand | can't (fixed snapshot) |
|---|---|---|---|
| HIFLD Next | 0 of 20 | 14 | 6 |
| DataLumos | 0 of 6 | 6 | 0 |
| Source Cooperative | 0 of 6 | 6 | 0 |
| Harvard data.gov archive | 4 of 6 | 2 | 0 |
| **all** | **4 of 38 (11%)** | **28 (74%)** | **6 (16%)** |

The 4 that pass are data.gov records of USGS data releases, which name a DOI and a `modified` date. Those are
one-off releases that are unlikely to change. No HIFLD Next, DataLumos or Source Cooperative copy keeps a source
link in a field.

**Per check, `copy / hand / no`:**

| holder | 1 upstream | 2 newest record | 3 count | 4 source modified | 5 cadence | 6 vintage |
|---|---|---|---|---|---|---|
| HIFLD Next | 0/14/6 | 10/10/0 | 20/0/0 | 20/0/0 | 0/0/20 | 0/20/0 |
| DataLumos | 0/6/0 | 4/2/0 | 0/6/0 | 0/4/2 | 0/1/5 | 4/2/0 |
| Source Cooperative | 0/6/0 | 0/6/0 | 0/6/0 | 0/3/3 | 0/0/6 | 0/6/0 |
| Harvard | 5/1/0 | 0/6/0 | 0/5/1 | 4/1/1 | 0/2/4 | 4/2/0 |

None of the 38 copies has a cadence field.

**HIFLD metadata kept vs the original (20 layers), counted per field.** The original data.gov records had a
`modified` date (20 of 20) and nothing else: no issued date, source URL, record count, checksum or version (0 of
20 each). Their `modified` date is the same for all 20 (2022-10-24, the day DHS's catalog was harvested), so it
dates the catalog, not the data.

| field | original | DataLumos deposit | HIFLD Next |
|---|---|---|---|
| issued | 0 | 0 | added 20 |
| modified / source date | 20 | changed 20 | changed 20 |
| source URL | 0 | 0 | 0 |
| record count | 0 | 0 | added 20 |
| checksum | 0 | 0 | added 20 (its own files) |
| version | 0 | added 20 (`v1`) | added 20 (`v1.0.0`) |

So the rescue lost nothing, because the original had nothing to lose. HIFLD Next added most of what a check needs.
But the deposit and HIFLD Next agree on the source's date for only **4 of 20** layers, and neither says which date
it means.

**HIFLD layers with no upstream (#171):** 14 of the 73 checked layers (19%) have no current public source, and 11
of those are among the 33 climate-risk layers. Those can only be labeled fixed snapshots.

**dataindex.us and ALFRED, from their own pages.** dataindex.us rates 117 named federal collections for risk, done
by people every quarter. It records no versions, counts, dates or checksums, and doesn't cover HIFLD. ALFRED keeps
every vintage of every FRED economic series, which is the vintage label done properly, but only for numeric time
series. Neither can say whether a HIFLD layer copy or a DataLumos deposit is behind its source. Quotes and links
are in the notebook.

**Verdict on the argument.** Mostly right. Only 4 of 38 copies can be checked without a person, and those are the
ones that least need it. But it isn't that rescues *lost* the metadata. For HIFLD the original record never had
it, and the copies added counts, source dates and checksums. What every holder still lacks is a source link and a
cadence in a field, and a capture date next to the source's date. Those are the three fields to ask publishers to
keep.

## What didn't work, and what it doesn't show

- **The Wayback Machine wasn't reachable from our sandbox**, so the notebook doesn't query it, and HIFLD Open's own item pages (a richer original
  than data.gov's record) couldn't be read. data.gov's archived record stands in as the original.
- **DataLumos returns 403 to scripts**, so its files and pages count as "by hand". We read its metadata through
  DataCite instead.
- **We count DataCite's `Collected` date as the deposit's source date.** DataCite defines `Collected` as when the
  content was collected, and depositors seem to use it for the source's date. It isn't labeled either way.
- **Small samples**, and Source Cooperative's six were picked from search results, not drawn at random. Harvard's
  random draw is mostly small research datasets, not the at-risk data people rescued.
- **"From the copy" means a script can start the check**, not that it can judge it. A newer date at the source
  doesn't always mean newer data (see #171's two calls).
- **Text is scored by regex.** A date or URL in a README earns "by hand". We don't check that it's the right one.
- **We looked for an existing tool first.** dataindex.us and ALFRED don't cover this (above). STAC, DataCite and
  DCAT-US each define the fields. The gap is which ones holders fill in, so the code is field lookups.
