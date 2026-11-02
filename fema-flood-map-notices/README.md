# FEMA flood-map Notices to Congress as a dataset

Status: **step 1 done, build blocked.** See issue #180.

## Step 1: does the series exist as the card assumes?

Yes, but its rows are counties, not communities.

- **What it is.** "Notice to Congress: Monthly Update on Flood Mapping", required by Biggert-Waters 2012 / HFIAA 2014 (42 USC 4101b(d)(1)(G)–(H)). FEMA says it has been monthly since June 2014.
- **Format.** One PDF per month (about 12 pages), with a good text layer. Index pages: `https://www.fema.gov/flood-maps/guidance-reports/congress-notice/<year>`.
- **What's on fema.gov now.** Only the 2025 and 2026 year pages list documents (about 12 + 9 issues; August 2026 has a PDF but isn't on the 2026 list). The 2024 page lists none, and 2014–2023 aren't linked. Older issues would have to come from the Internet Archive.
- **Tables in each issue** (September 2026 example, about 70 rows in total):
  1. *Estimated Release of Preliminary Maps*: region, state, county, estimated preliminary month, community-meeting quarter, appeal-start quarter (about 40 rows).
  2. *Estimated Release of Revised Preliminary Maps*: region, state, county, estimated month (4 rows).
  3. *Actions Taken by FEMA* last month: region, state, county, action (Preliminary, Revised Preliminary, Appeal Start, LFD Issued, Maps Effective), date (30 rows).
  Tables run across pages, and the page footer gets merged into the last row of each page. That's the main extraction hazard.
- **Is it already data?** Not as a series. FEMA publishes current snapshots only:
  - Preliminary NFHL layer 0 (`hazards.fema.gov/.../PrelimPending/Prelim_NFHL/MapServer/0`): 826 study areas with `DFIRM_ID` and `PRELM_ISSUE_DATE`.
  - Pending NFHL layer 0: 291 areas with `EFF_DATE`.
  - OpenFEMA `NfipCommunityStatusBook`: the current effective map date per CID.

  None of these holds the forward schedule (estimated months and quarters), appeal-start dates or LFD dates, or any history once a map goes effective. The snapshots can serve as a free cross-check on extracted "Preliminary" and "Maps Effective" dates.

## Blocker

From this cloud session, `www.fema.gov/sites/default/files/...` PDFs return HTTP 403 from FEMA's CDN, even though `www.fema.gov/api/open` (OpenFEMA) and `hazards.fema.gov` work. The session's safety policy doesn't allow working around the block, for example by changing the user agent or fetching from the Internet Archive, so the pipeline can't be built or verified here. The decision is on issue #180.
