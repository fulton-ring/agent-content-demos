import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import marimo as mo
    import pandas as pd

    from common import OUT, PAIRS_FILE, triage


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 2. How well do simple rules decide which records share a site?

    The obvious fixes for co-located school records are rules: merge every pair closer than some distance, or in the
    same S2 cell, or in the same building footprint, or at the same address. This notebook scores each rule against
    the two answer keys built in [1. Pairs](1_pairs.py) (New York City building codes, Los Angeles Unified campuses).
    """)
    return


@app.cell
def _():
    pairs = pd.read_parquet(PAIRS_FILE)
    known = pairs.dropna(subset=["truth"])
    known.groupby("region").agg(pairs=("pair_id", "size"), same_site=("truth", "sum"))
    return known, pairs


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Distance

    The share of pairs that the keys say really share a site, by how far apart HIFLD's two points are. Pairs more
    than 150 m apart are only candidates because they give the same street address.
    """)
    return


@app.cell
def _(known):
    by_distance = (
        known.groupby(["region", pd.cut(known["distance_m"], [-1, 1, 10, 25, 50, 100, 150, 1e6])], observed=True)[
            "truth"
        ]
        .agg(pairs="size", share_same_site="mean")
        .round(2)
        .unstack(0)
    )
    by_distance.to_csv(OUT / "same_site_by_distance.csv")
    by_distance
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    No distance is safe in both directions: some pairs a few metres apart are separate schools, and some pairs 50–100
    m apart share a building. One reason is that HIFLD's points are often misplaced (see the offsets in notebook 1).

    ## S2 cells

    Matching by "same S2 cell at level L" is a distance cut whose edges fall on a fixed grid. For pairs whose points
    are within 10 m of each other, this is the share that land in different cells at each level.
    """)
    return


@app.cell
def _(pairs):
    _close = pairs[pairs["distance_m"] <= 10]
    s2_split = pd.DataFrame(
        {
            "level": range(14, 23),
            "cell edge (m, approx.)": [600, 300, 150, 75, 38, 19, 10, 5, 2.4],
            "pairs ≤10 m apart split into two cells %": [
                round(100 * float((_close["s2_shared_level"] < _l).mean()), 1) for _l in range(14, 23)
            ],
        }
    )
    s2_split.to_csv(OUT / "s2_split.csv", index=False)
    s2_split
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Every rule, scored the same way

    Each rule gives a pair a score: 0 or 1 for yes/no rules, closeness for distances, the shared level for S2. On the
    *tune* half of each key we pick two thresholds: the lowest score above which at least 97% of pairs really share a
    site (**merge automatically**), and the highest below which at least 97% really don't (**keep apart
    automatically**). Everything between goes to **review**. Then we count on the *test* half.

    "Plain precision" and "plain recall" read the rule as a simple yes/no (merge when it says yes; 25 m for the
    distances, level 18 for S2).
    """)
    return


@app.cell
def _(pairs):
    rules = pairs.assign(
        near_10m=(pairs["distance_m"] <= 10).astype(float),
        near_50m=(pairs["distance_m"] <= 50).astype(float),
        closeness=-pairs["distance_m"],
        # A pair with an address the Census can't place gets the worst score, so this rule never merges it.
        geocoded_closeness=-pairs["geocoded_distance_m"].fillna(1e6),
        s2_18=(pairs["s2_shared_level"] >= 18).astype(float),
        s2_20=(pairs["s2_shared_level"] >= 20).astype(float),
        signals=(pairs[["same_address", "same_building", "same_osm_grounds"]].sum(axis=1) + (pairs["distance_m"] <= 25))
        / 4,
    )
    rule_triage = triage(
        rules,
        {
            "distance ≤ 10 m": "near_10m",
            "distance ≤ 50 m": "near_50m",
            "distance (any cut)": "closeness",
            "same S2 cell, level 18 (~38 m)": "s2_18",
            "same S2 cell, level 20 (~10 m)": "s2_20",
            "S2 shared level (any level)": "s2_shared_level",
            "same Overture building": "same_building",
            "same OSM school grounds": "same_osm_grounds",
            "count of the four signals": "signals",
            "same street address": "same_address",
            "geocoded addresses (any cut)": "geocoded_closeness",
        },
        {"closeness": -25, "geocoded_closeness": -25, "s2_shared_level": 18},
    )
    rule_triage.to_csv(OUT / "triage_rules.csv", index=False)
    rule_triage
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this shows

    - **Every rule built on HIFLD's point is right only about 80% of the time**: distance, S2 cells, a shared
      Overture building and shared OSM grounds all trust the point, and some points sit on the wrong building. None
      of them reaches 97% precision in either direction, so none can decide a pair on its own.
    - **The street address each school reports is the strongest single signal.** Two matching addresses are the same
      site about 99% of the time in New York. Geocoding the addresses independently (Census) helps too.
    - **But a rule can only merge.** Neither address rule can say "these two are separate" with confidence, so every
      pair it doesn't merge still needs a look. That is what [3. Jev](3_jev.py) tries.
    """)
    return


if __name__ == "__main__":
    app.run()
