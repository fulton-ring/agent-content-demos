import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import marimo as mo
    import numpy as np
    import pandas as pd
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    from common import ANSWERS_FILE, OUT, PAIRS_FILE, REGIONS, load_schools, thresholds

    # The method whose thresholds turn pairs into sites: the best one in notebook 3.
    SITE_METHOD = "jev_semantic"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 4. From pairs to sites

    The deliverable for anyone using the layer: every school record gets a `site_id`, shared with the records it is
    co-located with. **No record is deleted.** Co-located schools have separate students, so a count of people at a
    site sums their enrollment; a count of places counts site IDs.

    We use the best method from [3. Jev](3_jev.py), Jev with the pair described in words, with its thresholds from
    the tune half of each answer key. Every pair in the two regions, keyed or not, is merged, kept apart, or sent to
    review. Merged pairs are joined into sites (connected components).
    """)
    return


@app.cell
def _():
    pairs = pd.read_parquet(PAIRS_FILE).merge(pd.read_parquet(ANSWERS_FILE), on="pair_id")
    schools = load_schools()
    return pairs, schools


@app.cell
def _(pairs, schools):
    _rows, _regional, _decided = [], [], []
    for _region, _spec in REGIONS.items():
        _all = pairs[pairs["region"] == _region]
        _tune = _all[_all["truth"].notna() & (_all["half"] == "tune")]
        _merge_at, _apart_at = thresholds(_tune[SITE_METHOD], _tune["truth"])
        _decision = np.select(
            [_all[SITE_METHOD] >= _merge_at, _all[SITE_METHOD] <= _apart_at], ["merge", "keep apart"], "review"
        )
        _local = schools[schools["COUNTYFIPS"].isin(_spec.counties)][
            ["NCESID", "NAME", "ADDRESS", "CITY", "ENROLLMENT"]
        ]
        _index = pd.Series(range(len(_local)), index=_local["NCESID"])
        _merged = _all[_decision == "merge"]
        _graph = coo_matrix(
            (np.ones(len(_merged)), (_index[_merged["a_ncesid"]], _index[_merged["b_ncesid"]])),
            shape=(len(_local),) * 2,
        )
        _, _labels = connected_components(_graph, directed=False)
        _local = _local.assign(region=_region, site_id=[f"{_spec.osm_relation}-{s}" for s in _labels])
        _local["has_pair_to_review"] = _local["NCESID"].isin(
            set(_all.loc[_decision == "review", ["a_ncesid", "b_ncesid"]].to_numpy().ravel())
        )
        _regional.append(_local)
        _decided.append(_all.assign(decision=_decision))
        _rows.append(
            {
                "region": _region,
                "records": len(_local),
                "sites": _local["site_id"].nunique(),
                "pairs merged": int((_decision == "merge").sum()),
                "pairs kept apart": int((_decision == "keep apart").sum()),
                "pairs to review": int((_decision == "review").sum()),
                "records with a pair to review": int(_local["has_pair_to_review"].sum()),
                "merge at p ≥": _merge_at,
                "keep apart at p ≤": _apart_at,
            }
        )
    pd.concat(_regional, ignore_index=True).to_csv(OUT / "school_sites.csv", index=False)
    pd.concat(_decided, ignore_index=True).to_csv(OUT / "pairs.csv", index=False)
    site_summary = pd.DataFrame(_rows)
    site_summary.to_csv(OUT / "site_summary.csv", index=False)
    site_summary
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    `output/school_sites.csv` has one row per record with its `site_id`; `output/pairs.csv` has every pair with its
    evidence, every method's score and the decision. Los Angeles gets no keep-apart threshold: its tune half has too
    few separate-site pairs to reach 97%, so everything not merged goes to review there.

    ## What a national pass would cost

    The model cost per pair, times the national candidate pairs from notebook 1. The Census geocoder is free.
    """)
    return


@app.cell
def _():
    _national = int(pd.read_csv(OUT / "national_summary.csv", index_col=0).loc["all candidate pairs", "pairs"])
    national_cost = pd.read_csv(OUT / "model_runs.csv").set_index("method")[["pairs", "cost_usd"]]
    national_cost["usd_per_pair"] = (national_cost["cost_usd"] / national_cost["pairs"]).round(6)
    national_cost["usd_for_national_pairs"] = (national_cost["usd_per_pair"] * _national).round(2)
    national_cost.to_csv(OUT / "national_cost.csv")
    mo.vstack([mo.md(f"{_national:,} national candidate pairs."), national_cost])
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this shows, and what didn't work

    **In order of leverage:**

    1. **Decide what a duplicate is first.** No record in the layer is a copy; each is a separate school. Give
       co-located records a shared site ID, and keep them all.
    2. **Match on the address each school reports, not on its map point.** Every rule built on the point is right
       only about 80% of the time, because the points are often misplaced.
    3. **Add an independent location**: the Census geocode of the address, or a state school directory.
    4. **Ask Jev about the pairs a rule can't settle, described in words, without map points.** It is the only
       method here that also keeps pairs apart with confidence.
    5. **Tune its thresholds on a labelled sample, and send the middle band to a person.**
    6. **Drop closed schools first**, from a state directory: HIFLD still carries some that have closed.

    **What didn't work, or isn't shown:**

    - **The wording of Jev's state moves the result.** An earlier version of the words variant, which described a
      unit suffix ("-TRAILER 30") as "different streets", decided 98.5% of a slightly different test half;
      describing units properly gave about 90%. We stopped changing the wording once it was faithful, since keeping
      changes because they score better on the test half would be tuning to it.
    - **Jev's answers vary between runs**, and the thresholds of the weaker variants with them: rerun from scratch,
      Jev on records and flags went from 62% decided to 38%. Use more labelled pairs than this, and pin the version.
    - **The aerial image made Jev worse**, and the chat model cost about 100 times more for less.
    - **Some "errors" are the key's conventions**: New York gives a trailer, an annex, or a charter school on another
      floor its own building code. "Same campus" is looser, so true error rates are lower than counted.
    - **The 150 m radius misses big campuses**: a school with its own street number more than 150 m from its campus
      partners is never compared.
    - **The Los Angeles key is small** (48 test pairs): a check, not a measurement. Rural districts, where one building
      often holds several schools, are not measured at all.
    - **No OCR was needed**: every source is machine-readable.
    """)
    return


if __name__ == "__main__":
    app.run()
