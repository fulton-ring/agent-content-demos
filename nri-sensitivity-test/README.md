# The sensitivity test FEMA didn't run on the National Risk Index

In the December 2025 release of the National Risk Index (v1.20), FEMA replaced the social
vulnerability input, CDC's Social Vulnerability Index (SVI), with the Census Bureau's Community
Resilience Estimates (CRE). GAO-26-107894 found that FEMA "did not evaluate the potential
changes to the composite risk scores." This spike runs that test. It holds v1.20 fixed, puts
v1.19's CDC SVI back in as the social vulnerability input, and measures how risk scores, ratings
and resilience-zone candidates change. It also splits the change users saw between v1.19 and
v1.20 into its causes.

Issue: [#49](https://github.com/fulton-ring/agent-content-demos/issues/49), a sub-issue of #45.

## Run it

```bash
./run.sh
```

This needs [uv](https://docs.astral.sh/uv/). It downloads about 175,000 rows from FEMA's public
ArcGIS layers (about 90 seconds; cached in `~/.cache/nri-sensitivity-test`, or set `NRI_CACHE`), runs
`notebook.py` as a script, and writes every table and the figure to `results/`. The whole run
takes about 11 minutes, cached or not, because FEMA's k-means rating runs many times. To read it with its outputs, use
`uv run marimo edit notebook.py`.

## Data

FEMA's ArcGIS Online account `FEMA_NationalRiskIndex`: "National Risk Index Census Tracts" and
"National Risk Index Counties" (v1.20, `NRI_VER` = December 2025), and the "(March 2023)" layers
of each (v1.19). Only attribute fields are downloaded, and nothing is committed. The method comes
from the v1.20 Technical Documentation (§3.1 risk, §3.2 ratings, §4.3 Community Risk Factor).

## What it found

All numbers are from `results/` after a clean run.

**1. We can rebuild FEMA's risk equation from its published inputs.** Risk = Expected Annual
Loss × Community Risk Factor (CRF). The CRF is the triangular(0.5, 1, 2) quantile of the
percentile of social vulnerability score ÷ resilience value. For v1.20 tracts our CRF ranks all
84,093 tracts in FEMA's order (Spearman 1.000) with a median difference of 0.0017. FEMA's
k-means rating method reproduces too. Run on FEMA's county values, it gives FEMA's rating for
100% of counties in both releases. On our rebuilt values, it misses one county in 3,135.

**2. At tract level, the two sources disagree a lot** (84,092 tracts matched, including
Connecticut's renumbered tracts):

| Tracts, swap only | |
|---|---|
| Social vulnerability score rank correlation, CDC SVI vs CRE | 0.526 |
| Top-fifth social vulnerability tracts under CDC SVI that stay top fifth under CRE | 47.4% |
| Composite risk rank correlation | 0.939 |
| Tracts changing composite risk quintile | 33.6% |
| Tracts changing risk rating band | 25.4% |
| Tracts tied at one CRE score (9.21) | 16.9% |

**3. At county level, the swap alone moves less than the release did** (3,135 counties rated in
both releases):

| Counties | Rank corr. | Change band | Move 2+ bands | Top-100 overlap |
|---|---|---|---|---|
| Swap only, built FEMA's v1.20 way | 0.980 | 340 (10.8%) | 0 | 93 |
| Swap only, summing tracts (the #45 scratch method) | 0.994 | 139 (4.4%) | 0 | 95 |
| Full v1.19 → v1.20, FEMA's published values | 0.864 | 812 (25.9%) | 8 | 67 |

**4. FEMA also changed how it builds county risk, and the documentation doesn't say so.** In
v1.19, county risk is the sum of tract risk, as §3.1 of the documentation says. In v1.20 it is
county loss × a CRF computed from the county's own social vulnerability and resilience. Summing
tracts misses FEMA's v1.20 county values by 9.9% at the median. The v1.20 documentation still
describes the tract sum.

**5. What moved county ratings between v1.19 and v1.20.** Rebuilding all 16 combinations of
old and new inputs reproduces FEMA's 812 county rating changes in total (812 = 812). Split with
Shapley values:

| Change | Share of the 812 |
|---|---|
| Hazard loss (EAL) updates | 75.1% |
| County aggregation method | 12.9% |
| Social vulnerability swap | 11.5% |
| Resilience input changes | 0.5% |

**6. Resilience-zone candidates change much more than county ratings.** The statutory screen is
high risk, top two fifths of social vulnerability and bottom two fifths of resilience. Under it,
2,203 of the 4,900 tracts that qualify with CDC SVI (45%) drop out with CRE, and 1,752 others
come in. FEMA's 2023 risk rule (top 50 nationally plus the top 1% per state, before its CEJST
filter) selects 866 tracts either way, but 303 of them (35%) are different tracts.

**What the swap did and didn't change.** It barely moved the county composite that most users
read: 93 of the top 100 counties stay, and no county moves two bands. Most of the 25% county
churn came from the hazard updates. But it reshuffled which tracts count as the most socially
vulnerable. Resilience zones are drawn from those tracts, and roughly a third to a half of the
candidates change.

## Against the preliminary numbers in the issue

| Preliminary (scratch, #45) | This notebook | Why |
|---|---|---|
| CRF median abs diff 0.003 | 0.0017 | Same method; Spearman 1.0 in both |
| 83,213 tracts | 84,092 | Connecticut's 879 tracts now matched on state + tract code |
| SV correlation 0.523; 47.3% stay top fifth; 33.6% change quintile | 0.526; 47.4%; 33.6% | Connecticut added |
| County swap: 0.994, 168 (5.4%) change band, 95/100 | 0.994, 139 (4.4%), 95/100 summing tracts; **0.980, 340 (10.8%), 93/100 the v1.20 way** | The scratch script summed tracts, which FEMA's v1.20 doesn't do. We couldn't recover why it found 168 rather than 139; its code wasn't kept |
| Full release: 0.872, 770 (24.6%) | 0.864, 812 (25.9% of 3,135) | Same aggregation cause. 812 is FEMA's own count; the issue's 25.2% divides it by 3,223 counties, including 88 unrated |

The headline that changes for the article: the swap alone moves **10.8%** of county ratings, not
5.4%. That is still well under the 25.9% from the whole release.

## What it doesn't show

- What a full release built with CDC SVI would look like, or which measure of social
  vulnerability is better. It swaps one input inside v1.20.
- An exact CRF for v1.20 tracts. FEMA's percentiles behave as if a few hundred unpublished units
  were in the ranking; the order matches but values differ slightly.
- Connecticut counties: its 2022 planning regions aren't the old counties, so it's in the tract
  results only.
- Actual resilience-zone designations. The CEJST filter FEMA used in 2023 isn't applied, and the
  law leaves room for geographic-balance choices.
- Whether 0.5–2 is the right range for the CRF. The swap's effect on counties is small mostly
  because that range caps it.

## What we looked at first

There is no FEMA code for the NRI, so the risk equation follows the Technical Documentation and
is checked against FEMA's own published values at every step. Ratings use scikit-learn's
`KMeans` with FEMA's documented parameters. Downloads use the ArcGIS REST query API directly.
