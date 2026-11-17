# How many HIFLD transmission lines can be tied to what utilities report spending on them?

Spike for [#297](https://github.com/fulton-ring/agent-content-demos/issues/297). We joined the HIFLD
Electric Power Transmission Lines layer, as preserved in [HIFLD Next](https://hifld.publicenvirodata.org), to
Lawrence Berkeley National Laboratory's new file linking FERC Form 1 line records to HIFLD
([OEDI 8742](https://data.openei.org/submissions/8742), CC BY 4.0). Then we measured how much of the public line
map gets a Form 1 record and how much of that carries a cost.

**Answer: the public line map can be costed for about one mile in six at 132 kV and up.** Form 1 records reach
nearly half of those miles. But three in four matched lines have no line-level cost, because most big utilities
report transmission cost only as a voltage subtotal or system total.

## Run it

```bash
./run.sh
```

You need [uv](https://docs.astral.sh/uv/). The first run downloads about 120 MB into `data/`. The run takes about
15 s after that, and it calls no paid services ($0). Everything is in one marimo notebook, `form1_costs.py`, which
reads top to bottom. To read it with its tables and map, run `uv run marimo edit form1_costs.py`. `run.sh` runs the
same notebook as a script, so the numbers below and in `output/` come from the code you see.

## Data (all public, downloaded at run time)

| Data | Source |
|---|---|
| Transmission Lines v1.0.0 (94,619 segments) | HIFLD Next GeoParquet |
| `ferc_eia_transmission_lines_public.csv` (13,084 rows) | LBNL, OEDI submission 8742, CC BY 4.0 |
| Electric Retail Service Territories v1.0.0, used for owner type | HIFLD Next GeoParquet |
| State boundaries, `cb_2023_us_state_20m` | US Census |
| Form 1 schedule 422 with subtotal and total rows, and FERC utility names | [PUDL](https://catalyst.coop/pudl/) nightly build, CC BY 4.0 |
| Form 1 instructions, pages 422-423 | [FERC blank Form 1](https://www.ferc.gov/sites/default/files/2020-04/form-1.pdf) |

## Results

From the run on 2026-11-17. `output/headline.json` holds every number.

**Match share.** "Form 1-covered" means investor-owned lines at 132 kV and up, the lines Form 1 is meant to list.
Miles are route miles of HIFLD segments, because HIFLD has no circuit count.

| HIFLD lines | Segments matched | Miles matched |
|---|---|---|
| Whole layer | 13.8% | 24.8% |
| 132 kV and up | 39.1% | 44.4% |
| Form 1-covered (investor-owned, 132 kV+) | 43.5% | 51.9% |

| Owner type (132 kV+) | Miles | Miles matched |
|---|---|---|
| Investor-owned | 186,121 | 51.9% |
| Owner not recorded in HIFLD | 59,565 | 53.2% |
| Federal (BPA, WAPA, TVA and others) | 30,271 | 6.0% |
| Co-op | 19,376 | 22.0% |
| Public power | 11,615 | 17.1% |

By state, the median match share is 50% of 132 kV+ miles. It runs from 0% in Wyoming and Colorado, and under 3% in
Utah, Washington and Idaho, up to 91% in Wisconsin. The western gap includes investor-owned miles. PacifiCorp files
Form 1, but only 2.8% of its 708 segments at 132 kV and up are matched. See `output/match_by_state_132kv.csv`.

**Cost coverage.** These are matched lines with `total_cost` above zero.

| Tier | Matched lines | With a cost |
|---|---|---|
| High | 2,580 | 25.7% |
| Medium | 9,570 | 24.4% |
| Low | 934 | 25.5% |
| All | 13,084 | 24.7% |

That leaves **15.6% of HIFLD's 132 kV+ miles with a Form 1 cost** (15.6% of Form 1-covered miles, and 5.0% if we
keep only high-confidence matches). Expenses are nearly always zero (1.7% of matches).

**Why costs are blank.** FERC's instructions let a line show no cost of its own only when its structures' cost is
reported on another line (column g), or when the line is leased. Only 949 of the 9,852 costless matches fit the
column-g case. The rest are explained by PUDL's full schedule. In 2024, 88% of costless matches (4,420 of 5,045
whose utility we found in PUDL) belong to a utility that put a nonzero cost on a subtotal or total row. 47 of 109
utilities gave no line a cost but did report a voltage or system total. ComEd, FPL, American Transmission Co and
Dominion are among them. 6 utilities reported no cost anywhere, Oncor and CenterPoint Houston among them. So the
money is reported, just not per line.

**Match quality.** 2,270 matches (17.3%) are length outliers, where the HIFLD segment is 4 or more times longer or
shorter than the length Form 1 reports. We hand-checked 20 of them (`hand_check.csv`): **8 were the wrong line**
(40%), which would mean about 900 wrong matches among the outliers alone. On matches where HIFLD names an owner,
20.7% name a different utility from the Form 1 filer. That figure is an upper bound, because it also counts renamed
utilities and HIFLD owner errors.

**Vintage.** All 13,084 LBNL IDs are in HIFLD Next. None has a vertex more than 1 m off the HIFLD Next line, and
none differs in length by more than 2%. The newest `SOURCEDATE` is 2024-09-26 on both sides. So LBNL used the
same HIFLD release that HIFLD Next preserved. 94 lines that have no voltage in HIFLD carry one in LBNL's file,
apparently filled in from Form 1. One trap: LBNL's column is named `GlobalID`, but it holds HIFLD's numeric `ID`
(`source_ID` in HIFLD Next). HIFLD Next has no GlobalID.

## Against the expectation

- **Holds:** a minority of HIFLD lines match (14% of segments, 44% of 132 kV+ miles). Federal lines are near zero
  (6% of miles). Most matches carry no cost (75%).
- **Doesn't hold as stated:** co-ops aren't near zero (22% of 132 kV+ miles). Against the lines Form 1 is meant
  to cover, the match share is about half, not a small minority.
- **Changes the story:** blank cost cells mostly mean the cost was reported in aggregate, not that it's missing.

## Outputs

- `output/map_form1_match.png`: 132 kV+ lines colored by no match, matched without cost, and matched with cost
- `output/match_*.csv`, `cost_by_tier.csv`, `respondent_cost_reporting_2024.csv`, `headline.json`
- `output/hand_check_sample.csv` is the 20 drawn outliers, and `hand_check.csv` holds our verdicts
- `output/hifld_lines_form1.parquet` is every HIFLD Next line with owner type, state, `match_tier` (`high`, `medium`,
  `low`, `none`) and the Form 1 fields. At 43 MB it isn't committed; `./run.sh` rebuilds it. Its Form 1 fields come
  from LBNL's dataset, CC BY 4.0.

## What it doesn't show

- **Circuit miles.** HIFLD has no circuit count.
- **Exact owner types.** Owners missing from the Retail Service Territories layer are typed by keyword or counted
  investor-owned by elimination. HIFLD's own owner field has errors. For example, Azusa Light & Power is listed on
  779 segments.
- **Partial lines.** LBNL ties each Form 1 line to a single HIFLD segment. HIFLD splits lines at taps, so the rest
  of a long line counts as unmatched, and a matched cost belongs to the whole line, not to the segment.
- **A full error rate.** The hand check is 20 outliers, judged from names and lengths without imagery. It says
  little about matches that look normal.
- **Footnotes.** We didn't read filing footnotes, which might explain individual blanks.

## What we looked at first

We used existing tools and data rather than writing a matcher. LBNL's file supplies the matching, HIFLD Next's
own service-territory layer supplies owner types, and PUDL supplies Form 1's totals rows. We first tried EIA-860's
utility file for owner type, but EIA's download blocked scripted access from our environment.
