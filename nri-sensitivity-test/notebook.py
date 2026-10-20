import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import itertools
    import json
    import logging
    import math
    import os
    from pathlib import Path

    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import requests
    from scipy import stats
    from sklearn.cluster import KMeans

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("nri")
    default_cache = Path.home() / ".cache" / "nri-sensitivity-test"
    cache = Path(os.environ.get("NRI_CACHE", default_cache))
    results = Path(os.environ.get("NRI_RESULTS", Path(mo.notebook_dir() or ".") / "results"))
    cache.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    return (
        KMeans,
        Path,
        cache,
        itertools,
        json,
        log,
        math,
        mo,
        np,
        pd,
        plt,
        requests,
        results,
        stats,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # The sensitivity test FEMA didn't run on the National Risk Index

    In December 2025 FEMA released version 1.20 of the National Risk Index (NRI). Among other
    changes, it replaced the index's social vulnerability input, CDC's Social Vulnerability Index
    (SVI), with the Census Bureau's Community Resilience Estimates (CRE). GAO-26-107894
    (September 2026) found that FEMA compared the two sources at the input level but "did not
    evaluate the potential changes to the composite risk scores."

    **The question:** if we hold everything else in v1.20 fixed and put v1.19's CDC SVI back as
    the social vulnerability input, how much do the composite risk scores and ratings move? And
    how much of the change between v1.19 and v1.20 that users see is due to the swap rather than
    the other updates in the release?

    Everything below is computed from FEMA's own public layers, downloaded when the notebook
    runs.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The data

    FEMA publishes both releases as feature layers on its ArcGIS Online account
    `FEMA_NationalRiskIndex`: the current layers (v1.20, December 2025) and the
    "(March 2023)" layers (v1.19). We download the tract and county tables for each, without
    geometry, and only the fields the risk equation uses:

    - `EAL_VALT`: Expected Annual Loss in dollars, summed over 18 hazards (the hazard part).
    - `SOVI_SCORE`: the social vulnerability score, a national percentile (CDC SVI in v1.19,
      Census CRE in v1.20; the field kept its name).
    - `RESL_VALUE`, `RESL_SCORE`: community resilience (a FEMA-modified version of the
      University of South Carolina's BRIC index, at county level; tracts inherit their county's).
    - `CRF_VALUE`, `RISK_VALUE`, `RISK_RATNG`: FEMA's published Community Risk Factor, risk in
      dollars and rating, which we use as the answer key.

    The download is cached in `NRI_CACHE` so a rerun doesn't fetch it again.
    """)
    return


@app.cell
def _(cache, log, pd, requests):
    base = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services"
    fields = [
        "STCOFIPS",
        "STATEABBRV",
        "POPULATION",
        "EAL_VALT",
        "SOVI_SCORE",
        "RESL_VALUE",
        "RESL_SCORE",
        "CRF_VALUE",
        "RISK_VALUE",
        "RISK_RATNG",
        "NRI_VER",
    ]
    layers = {
        "tracts_v120": ("National_Risk_Index_Census_Tracts", ["TRACTFIPS", *fields]),
        "tracts_v119": ("National_Risk_Index_Census_Tracts_(March_2023)", ["TRACTFIPS", *fields]),
        "counties_v120": ("National_Risk_Index_Counties", fields),
        "counties_v119": ("National_Risk_Index_Counties_(March_2023)", fields),
    }

    def download(service: str, columns: list[str]) -> pd.DataFrame:
        """Page through an ArcGIS feature layer's attribute table, 2,000 rows at a time."""
        url = f"{base}/{service}/FeatureServer/0/query"
        rows: list[dict] = []
        for _page in range(200):
            params = {
                "where": "1=1",
                "outFields": ",".join(columns),
                "returnGeometry": "false",
                "orderByFields": "OBJECTID",
                "resultOffset": len(rows),
                "resultRecordCount": 2000,
                "f": "json",
            }
            response = requests.get(url, params=params, timeout=120)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(f"{service}: {payload['error']}")
            rows += [feature["attributes"] for feature in payload["features"]]
            if not payload.get("exceededTransferLimit"):
                return pd.DataFrame(rows, columns=columns)
        raise RuntimeError(f"{service}: more than 200 pages")

    raw = {}
    for _name, (_service, _columns) in layers.items():
        _path = cache / f"{_name}.parquet"
        if not _path.exists():
            log.info("downloading %s", _service)
            download(_service, _columns).to_parquet(_path)
        raw[_name] = pd.read_parquet(_path)
        log.info("%s: %d rows, NRI_VER %s", _name, len(raw[_name]), raw[_name].NRI_VER.iloc[0])
    assert set(raw["tracts_v120"].NRI_VER.dropna()) == {"December 2025"}
    assert set(raw["tracts_v119"].NRI_VER.dropna()) == {"March 2023"}
    pd.DataFrame(
        {name: [len(df), df.NRI_VER.iloc[0]] for name, df in raw.items()},
        index=["rows", "NRI_VER"],
    )
    return (raw,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 1. Rebuild the Community Risk Factor from its inputs

    The v1.20 Technical Documentation (§4.3, Equation 3) says risk is
    `Expected Annual Loss × Community Risk Factor`. The Community Risk Factor (CRF) is built in
    three moves: divide the social vulnerability score by the community resilience value, take the
    national percentile of that ratio, and push the percentile through the inverse CDF of a
    triangular distribution with minimum 0.5, mode 1 and maximum 2. So the swap can scale a
    community's loss by at most a factor of four, between 0.5× and 2×.

    If we can rebuild FEMA's published CRF from the published inputs, we can trust the same
    function when we feed it a different social vulnerability input.
    """)
    return


@app.cell
def _(np, pd, raw, stats):
    def community_risk_factor(sv_score: pd.Series, resl_value: pd.Series) -> pd.Series:
        """Tech Doc Eq. 3: the triangular(0.5, 1, 2) quantile of the ratio's percentile."""
        ratio = sv_score / resl_value
        percentile = ratio.rank(pct=True)
        crf = stats.triang.ppf(percentile, c=(1 - 0.5) / (2 - 0.5), loc=0.5, scale=1.5)
        return pd.Series(crf, index=sv_score.index)

    def compare(label: str, ours: pd.Series, fema: pd.Series) -> dict:
        diff = (ours - fema).abs()
        return {
            "layer": label,
            "units": len(fema),
            "Spearman": stats.spearmanr(ours, fema).statistic,
            "median abs diff": float(np.median(diff)),
            "max abs diff": float(diff.max()),
        }

    _checks = []
    for _name in ["tracts_v120", "counties_v120", "tracts_v119", "counties_v119"]:
        _df = raw[_name].dropna(subset=["CRF_VALUE"])
        _ours = community_risk_factor(_df.SOVI_SCORE, _df.RESL_VALUE)
        _checks.append(compare(f"{_name}: CRF", _ours, _df.CRF_VALUE))
        _risk = _df.EAL_VALT * _df.CRF_VALUE
        _rel = ((_risk - _df.RISK_VALUE).abs() / _df.RISK_VALUE.clip(lower=1)).max()
        _checks[-1]["max rel diff, EAL x CRF vs RISK_VALUE"] = float(_rel)
    crf_checks = pd.DataFrame(_checks)
    crf_checks
    return community_risk_factor, crf_checks


@app.cell
def _(crf_checks, mo):
    _t20 = crf_checks.iloc[0]
    mo.md(rf"""
    **Result.** For v1.20 tracts the rebuilt CRF ranks every tract exactly as FEMA does
    (Spearman {_t20["Spearman"]:.4f}) and the median difference is
    {_t20["median abs diff"]:.4f} on a 0.5–2 scale. It is not exact: FEMA's percentiles behave
    as if a few hundred more units were in the ranking than the tracts it published with a
    CRF. We couldn't find out which, but the ordering is identical and the gap is far below
    anything that moves a rating. The same function rebuilds v1.19 tract CRFs almost exactly. In
    every layer, `RISK_VALUE` is exactly `EAL_VALT × CRF_VALUE`.

    The v1.19 county row is the exception, and it matters for Step 3.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 2. Swap the social vulnerability input at tract level

    Tracts are matched on their 11-digit FIPS code. Connecticut replaced its 8 counties with 9
    planning regions in 2022, so its tracts have new county codes in v1.20 but the same state
    and tract digits; we match those on state plus tract code. A tract is kept if both releases
    give it a social vulnerability score and a resilience value.

    Then we compute two versions of v1.20 tract risk, which differ only in the social
    vulnerability input:

    - **CRE (as published):** v1.20 hazards, v1.20 resilience, v1.20 social vulnerability.
    - **CDC SVI (swap):** v1.20 hazards, v1.20 resilience, v1.19 social vulnerability.
    """)
    return


@app.cell
def _(community_risk_factor, pd, raw):
    _keep = ["TRACTFIPS", "STCOFIPS", "STATEABBRV", "EAL_VALT", "SOVI_SCORE", "RESL_VALUE"]
    _v120 = raw["tracts_v120"][[*_keep, "RESL_SCORE"]].copy()
    _v119 = raw["tracts_v119"][_keep].copy()
    for _df in (_v120, _v119):
        _ct = _df.TRACTFIPS.str.startswith("09")
        _df["key"] = _df.TRACTFIPS.where(~_ct, "09" + _df.TRACTFIPS.str[5:])
    assert not _v120.key.duplicated().any() and not _v119.key.duplicated().any()
    tracts = _v120.merge(
        _v119.drop(columns=["TRACTFIPS", "STATEABBRV"]), on="key", suffixes=("", "_v119")
    ).rename(
        columns={
            "STCOFIPS": "county_v120",
            "STCOFIPS_v119": "county_v119",
            "EAL_VALT": "eal_v120",
            "EAL_VALT_v119": "eal_v119",
            "SOVI_SCORE": "sv_cre",
            "SOVI_SCORE_v119": "sv_cdc",
            "RESL_VALUE": "resl_v120",
            "RESL_VALUE_v119": "resl_v119",
            "RESL_SCORE": "resl_score_v120",
        }
    )
    tracts = tracts.dropna(subset=["sv_cre", "sv_cdc", "resl_v120", "resl_v119"]).reset_index(
        drop=True
    )
    tracts["risk_cre"] = tracts.eal_v120 * community_risk_factor(tracts.sv_cre, tracts.resl_v120)
    tracts["risk_cdc"] = tracts.eal_v120 * community_risk_factor(tracts.sv_cdc, tracts.resl_v120)
    pd.Series(
        {
            "tracts in v1.20": len(raw["tracts_v120"]),
            "matched tracts with both SV sources": len(tracts),
            "of which Connecticut": int((tracts.STATEABBRV == "CT").sum()),
        }
    )
    return (tracts,)


@app.cell
def _(mo):
    mo.md(r"""
    FEMA rates risk by k-means clustering (Technical Documentation §3.2): a cube root of the
    risk value, then scikit-learn `KMeans` with 5 clusters, `max_iter=500`, `n_init=20`,
    `tol=1e-15` and `random_state=42`, with clusters named Very Low to Very High in order of their
    centers. Social vulnerability and resilience ratings are plain quintiles of the score. We use
    the same k-means for every rating below and check it against FEMA's own ratings in Step 4.
    """)
    return


@app.cell
def _(KMeans, np, pd):
    bands = ["Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High"]

    def rate(risk_value: pd.Series) -> pd.Series:
        """FEMA's rating: k-means on the cube root of risk, bands 0 (Very Low) to 4 (Very High)."""
        x = np.cbrt(risk_value.to_numpy()).reshape(-1, 1)
        km = KMeans(n_clusters=5, max_iter=500, n_init=20, tol=1e-15, random_state=42).fit(x)
        rank_of_cluster = np.argsort(np.argsort(km.cluster_centers_.ravel()))
        return pd.Series(rank_of_cluster[km.labels_], index=risk_value.index)

    def quintile(values: pd.Series) -> pd.Series:
        """Quintile of a national percentile: 0 for the bottom fifth, 4 for the top fifth."""
        return np.ceil(values.rank(pct=True) * 5).clip(1, 5).astype(int) - 1

    return bands, quintile, rate


@app.cell
def _(pd, quintile, rate, stats, tracts):
    tracts["band_cre"] = rate(tracts.risk_cre)
    tracts["band_cdc"] = rate(tracts.risk_cdc)
    _sv_top_cdc = quintile(tracts.sv_cdc) == 4
    _sv_top_cre = quintile(tracts.sv_cre) == 4
    _band_moves = (tracts.band_cdc - tracts.band_cre).abs()
    tract_swap = pd.Series(
        {
            "tracts": len(tracts),
            "SV score rank correlation, CDC SVI vs CRE": stats.spearmanr(
                tracts.sv_cdc, tracts.sv_cre
            ).statistic,
            "share of CDC SVI top-fifth SV tracts still top fifth under CRE": (
                (_sv_top_cdc & _sv_top_cre).sum() / _sv_top_cdc.sum()
            ),
            "composite risk rank correlation": stats.spearmanr(
                tracts.risk_cdc, tracts.risk_cre
            ).statistic,
            "share changing composite risk quintile": (
                quintile(tracts.risk_cdc) != quintile(tracts.risk_cre)
            ).mean(),
            "share changing risk rating band (k-means)": (_band_moves > 0).mean(),
            "share moving 2+ rating bands": (_band_moves >= 2).mean(),
            "share of tracts tied at the most common CRE score": (
                tracts.sv_cre.round(6).value_counts().iloc[0] / len(tracts)
            ),
            "that CRE score": tracts.sv_cre.round(6).value_counts().index[0],
        }
    )
    tract_swap
    return (tract_swap,)


@app.cell
def _(mo, tract_swap):
    mo.md(rf"""
    **Result.** The two social vulnerability sources disagree a lot about tracts: their scores
    correlate at {tract_swap.iloc[1]:.3f}, and of the tracts CDC SVI puts in the most vulnerable
    fifth, only {tract_swap.iloc[2]:.1%} stay there under CRE. Because the CRF is capped between
    0.5 and 2 and hazard losses vary far more than that, the composite moves less: rank
    correlation {tract_swap.iloc[3]:.3f}, but {tract_swap.iloc[4]:.1%} of tracts still change
    composite quintile and {tract_swap.iloc[5]:.1%} change k-means rating band.

    The figure at the end shows one reason the sources disagree: under CRE,
    {tract_swap.iloc[7]:.1%} of tracts share a single score ({tract_swap.iloc[8]:.1f}), so CRE
    can't tell a large block of tracts apart that CDC SVI spreads across its whole range. FEMA's
    2022 working group rejected CRE for not providing "a distribution of social vulnerability
    values that reflected the differences of impacts across communities" (sources in issue #45).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 3. How FEMA builds county risk, and how that changed

    The Technical Documentation (§3.1) says county risk values "are calculated by summing the
    Values from their tracts." We tested that against both releases' county files, together with
    the alternative that the county gets its own CRF from county-level social vulnerability and
    resilience, as Step 1's v1.20 county row suggests.
    """)
    return


@app.cell
def _(np, pd, raw):
    def aggregation_check(version: str) -> dict:
        _t = raw[f"tracts_{version}"].dropna(subset=["CRF_VALUE"])
        _c = raw[f"counties_{version}"].dropna(subset=["RISK_VALUE"]).set_index("STCOFIPS")
        _g = _t.assign(w=_t.EAL_VALT * _t.CRF_VALUE).groupby("STCOFIPS")
        _sum_risk = _g.RISK_VALUE.sum().reindex(_c.index)
        _weighted_crf = (_g.w.sum() / _g.EAL_VALT.sum()).reindex(_c.index)
        _eal_sum = raw[f"tracts_{version}"].groupby("STCOFIPS").EAL_VALT.sum().reindex(_c.index)

        def _median_rel(x: pd.Series) -> float:
            return float(np.nanmedian((x - _c.RISK_VALUE).abs() / _c.RISK_VALUE))

        return {
            "release": version,
            "county EAL = sum of tract EAL": float(
                np.nanmedian((_eal_sum - _c.EAL_VALT).abs() / _c.EAL_VALT)
            ),
            "county risk = sum of tract risk": _median_rel(_sum_risk),
            "county risk = county EAL x EAL-weighted tract CRF": _median_rel(
                _c.EAL_VALT * _weighted_crf
            ),
            "county risk = county EAL x county CRF": _median_rel(_c.EAL_VALT * _c.CRF_VALUE),
        }

    aggregation = pd.DataFrame([aggregation_check("v119"), aggregation_check("v120")]).set_index(
        "release"
    )
    aggregation.T.rename_axis("median relative error vs FEMA's county RISK_VALUE")
    return (aggregation,)


@app.cell
def _(mo):
    mo.md(r"""
    **Result.** County Expected Annual Loss is the sum of tract loss in both releases. But county
    *risk* was built two different ways:

    - **v1.19:** county loss × the loss-weighted average of its tracts' CRFs. This is
      within rounding of summing tract risk (the two differ only where a tract has loss but no
      CRF), and it matches what the documentation says.
    - **v1.20:** county loss × a CRF computed directly from the county's own social vulnerability
      score and resilience value, ranked against other counties. Summing tract risk misses
      FEMA's v1.20 county values by the median error shown in the table.

    So v1.20 changed three things at once for counties: hazard losses, the social vulnerability
    source, and the aggregation method (resilience inputs also changed). The v1.20 documentation
    still describes the old aggregation. Our scratch analysis in #45 summed tracts, which is why
    its county numbers differ from the ones below. Here we build counties the v1.20 way, with
    each county's own social vulnerability score from each release (v1.19's county score is CDC
    SVI at county level).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 4. Check the ratings and swap the input at county level

    The county universe is every county rated in both releases, matched on FIPS code. That
    leaves out Connecticut, whose counties and planning regions are different areas. We first
    rebuild both releases' county risk from their inputs and rate them with k-means, and check
    the ratings against FEMA's.
    """)
    return


@app.cell
def _(bands, community_risk_factor, pd, raw, rate, tracts):
    _cols = ["STCOFIPS", "EAL_VALT", "SOVI_SCORE", "RESL_VALUE", "RISK_VALUE", "RISK_RATNG"]
    counties = (
        raw["counties_v120"][_cols]
        .merge(raw["counties_v119"][_cols], on="STCOFIPS", suffixes=("_v120", "_v119"))
        .query("RISK_RATNG_v120 in @bands and RISK_RATNG_v119 in @bands")
        .set_index("STCOFIPS")
    )
    _tr = tracts[tracts.county_v120.isin(counties.index)]
    assert (_tr.county_v120 == _tr.county_v119).all()

    def county_risk(eal: str, sv: str, resl: str, method: str) -> pd.Series:
        """County risk from one release's choice of each input and one aggregation method."""
        if method == "v120":
            crf = community_risk_factor(
                counties[f"SOVI_SCORE_{sv}"], counties[f"RESL_VALUE_{resl}"]
            )
            return counties[f"EAL_VALT_{eal}"] * crf
        sv_col = {"v119": "sv_cdc", "v120": "sv_cre"}[sv]
        tract_crf = community_risk_factor(_tr[sv_col], _tr[f"resl_{resl}"])
        weighted = (_tr[f"eal_{eal}"] * tract_crf).groupby(_tr.county_v120).sum()
        weight = _tr[f"eal_{eal}"].groupby(_tr.county_v120).sum()
        return counties[f"EAL_VALT_{eal}"] * (weighted / weight).reindex(counties.index)

    _code = {name: i for i, name in enumerate(bands)}
    fema_band = {v: counties[f"RISK_RATNG_{v}"].map(_code) for v in ("v119", "v120")}
    rebuilt = {v: county_risk(v, v, v, v) for v in ("v119", "v120")}
    _rows = []
    for _v in ("v119", "v120"):
        _rows.append(
            {
                "release": _v,
                "counties": len(counties),
                "median rel diff, rebuilt vs FEMA risk": float(
                    (
                        (rebuilt[_v] - counties[f"RISK_VALUE_{_v}"]).abs()
                        / counties[f"RISK_VALUE_{_v}"]
                    ).median()
                ),
                "k-means on FEMA's risk = FEMA rating": float(
                    (rate(counties[f"RISK_VALUE_{_v}"]) == fema_band[_v]).mean()
                ),
                "k-means on rebuilt risk = FEMA rating": float(
                    (rate(rebuilt[_v]) == fema_band[_v]).mean()
                ),
            }
        )
    rating_checks = pd.DataFrame(_rows).set_index("release")
    rating_checks
    return counties, county_risk, fema_band, rating_checks


@app.cell
def _(counties, county_risk, pd, rate, stats):
    def top_overlap(a: pd.Series, b: pd.Series, n: int) -> int:
        return len(set(a.nlargest(n).index) & set(b.nlargest(n).index))

    def change_stats(label: str, before: pd.Series, after: pd.Series) -> dict:
        band_before, band_after = rate(before), rate(after)
        moved = (band_after - band_before).abs()
        return {
            "comparison": label,
            "counties": len(before),
            "rank correlation": stats.spearmanr(before, after).statistic,
            "change band": int((moved > 0).sum()),
            "share changing band": float((moved > 0).mean()),
            "move 2+ bands": int((moved >= 2).sum()),
            "top-100 overlap": top_overlap(before, after, 100),
        }

    county_cre = county_risk("v120", "v120", "v120", "v120")
    county_cdc = county_risk("v120", "v119", "v120", "v120")
    county_changes = pd.DataFrame(
        [
            change_stats("SV swap only (v1.20, CDC SVI vs CRE)", county_cdc, county_cre),
            change_stats(
                "SV swap only, tracts summed (the #45 scratch method)",
                county_risk("v120", "v119", "v120", "v119"),
                county_risk("v120", "v120", "v120", "v119"),
            ),
            change_stats(
                "full release, rebuilt v1.19 vs rebuilt v1.20",
                county_risk("v119", "v119", "v119", "v119"),
                county_cre,
            ),
            change_stats(
                "full release, FEMA's published values",
                counties.RISK_VALUE_v119,
                counties.RISK_VALUE_v120,
            ),
        ]
    ).set_index("comparison")
    county_changes
    return (county_changes,)


@app.cell
def _(county_changes, fema_band, mo):
    _swap = county_changes.iloc[0]
    _summed = county_changes.iloc[1]
    _full = county_changes.iloc[3]
    _published = int((fema_band["v119"] != fema_band["v120"]).sum())
    mo.md(rf"""
    **Result.** At county level the swap alone moves the composite much less than the release did:
    rank correlation
    {_swap["rank correlation"]:.3f}, {_swap["change band"]:,} of {_swap["counties"]:,} counties
    ({_swap["share changing band"]:.1%}) change rating band, {_swap["move 2+ bands"]} move two or
    more bands, and {_swap["top-100 overlap"]} of the top 100 stay in the top 100. The release as a
    whole moved far more: rank correlation {_full["rank correlation"]:.3f}, with
    {_full["change band"]:,} counties ({_full["share changing band"]:.1%}) changing band when we
    re-rate FEMA's published values. FEMA's own published labels change for {_published:,} of
    these counties.

    Summing tracts instead, as our scratch analysis did, gives about half the change
    ({_summed["share changing band"]:.1%} changing band, rank correlation
    {_summed["rank correlation"]:.3f}).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 5. How much of the county churn is the swap?

    Four things changed between v1.19 and v1.20 county risk: hazard losses (EAL), the social
    vulnerability source (SV), the resilience inputs (RESL) and the aggregation method. We
    rebuild county risk for all 16 combinations of v1.19 and v1.20 choices, rate each with
    k-means, and count counties whose band differs from rebuilt v1.19.

    The four effects don't add up, because a county can be pushed across a band boundary by one
    change and back by another. So we split the total with Shapley values, which average each
    change's effect over every order in which the changes could have been made. The table also
    shows each change made alone from v1.19 and each change undone alone from v1.20.
    """)
    return


@app.cell
def _(county_risk, fema_band, itertools, math, pd, rate):
    factors = ["EAL", "SV", "RESL", "aggregation"]
    _base = rate(county_risk("v119", "v119", "v119", "v119"))
    churn = {}
    for _combo in itertools.product([False, True], repeat=4):
        _v = ["v120" if on else "v119" for on in _combo]
        churn[_combo] = int((rate(county_risk(*_v)) != _base).sum())
    _all = (True,) * 4
    _rows = []
    for _i, _factor in enumerate(factors):
        _shapley = 0.0
        for _combo in churn:
            if _combo[_i]:
                continue
            _with = tuple(on or j == _i for j, on in enumerate(_combo))
            _k = sum(_combo)
            _weight = math.factorial(_k) * math.factorial(3 - _k) / math.factorial(4)
            _shapley += _weight * (churn[_with] - churn[_combo])
        _alone = tuple(j == _i for j in range(4))
        _undone = tuple(j != _i for j in range(4))
        _rows.append(
            {
                "change": _factor,
                "made alone from v1.19": churn[_alone],
                "undone alone from v1.20": churn[_all] - churn[_undone],
                "Shapley share of churn (counties)": _shapley,
                "Shapley share of churn (%)": _shapley / churn[_all],
            }
        )
    decomposition = pd.DataFrame(_rows).set_index("change")
    decomposition.loc["total (all four)"] = [churn[_all], churn[_all], churn[_all], 1.0]
    assert abs(decomposition.iloc[:4, 2].sum() - churn[_all]) < 1e-6
    published_churn = int((fema_band["v119"] != fema_band["v120"]).sum())
    decomposition
    return decomposition, published_churn


@app.cell
def _(decomposition, mo, published_churn):
    _total = int(decomposition.loc["total (all four)"].iloc[0])
    _sv = decomposition.loc["SV"]
    _eal = decomposition.loc["EAL"]
    mo.md(rf"""
    **Result.** Rebuilt end to end, {_total:,} counties change band between v1.19 and v1.20
    (FEMA's published labels: {published_churn:,}). Hazard loss updates account for
    {_eal.iloc[3]:.0%} of that churn and the social vulnerability swap for {_sv.iloc[3]:.0%};
    the rest is resilience and aggregation, shown in the table.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 6. Community Disaster Resilience Zones

    Resilience zones are census tracts. The law (42 U.S.C. § 5136(d)) asks for tracts with high
    hazard risk, high social vulnerability and low community resilience. FEMA's 2023 designations
    took the 50 highest-risk tracts nationally plus the top 1% by risk in each state, then kept
    only tracts the Climate and Economic Justice Screening Tool (CEJST) called disadvantaged. We
    estimate two tract sets under each social vulnerability source, with v1.20 everything else:

    - **Statutory screen:** risk rated Relatively High or Very High, social vulnerability in the
      top two fifths, and resilience in the bottom two fifths.
    - **FEMA 2023 risk rule:** top 50 nationally plus the top 1% (rounded up) in each state, by
      risk value. We can't apply the CEJST filter: the tool was taken offline in 2025 and isn't
      in this notebook's sources, so this is the candidate pool before that filter.
    """)
    return


@app.cell
def _(np, pd, quintile, tracts):
    def statutory(risk_band: pd.Series, sv: pd.Series) -> pd.Series:
        return (risk_band >= 3) & (quintile(sv) >= 3) & (quintile(tracts.resl_score_v120) <= 1)

    def fema_2023(risk: pd.Series) -> pd.Series:
        top_national = risk.rank(ascending=False, method="first") <= 50
        state_rank = risk.groupby(tracts.STATEABBRV).rank(ascending=False, method="first")
        state_size = tracts.groupby("STATEABBRV").STATEABBRV.transform("size")
        return top_national | (state_rank <= np.ceil(state_size * 0.01))

    _rows = []
    for _rule, _cdc, _cre in [
        (
            "statutory screen",
            statutory(tracts.band_cdc, tracts.sv_cdc),
            statutory(tracts.band_cre, tracts.sv_cre),
        ),
        ("FEMA 2023 risk rule", fema_2023(tracts.risk_cdc), fema_2023(tracts.risk_cre)),
    ]:
        _rows.append(
            {
                "rule": _rule,
                "tracts under CDC SVI": int(_cdc.sum()),
                "tracts under CRE": int(_cre.sum()),
                "in both": int((_cdc & _cre).sum()),
                "drop out under CRE": int((_cdc & ~_cre).sum()),
                "enter under CRE": int((~_cdc & _cre).sum()),
                "share of CDC set that drops out": float((_cdc & ~_cre).sum() / _cdc.sum()),
            }
        )
    cdrz = pd.DataFrame(_rows).set_index("rule")
    cdrz
    return (cdrz,)


@app.cell
def _(cdrz, mo):
    _s = cdrz.loc["statutory screen"]
    _f = cdrz.loc["FEMA 2023 risk rule"]
    mo.md(rf"""
    **Result.** Under the statutory screen, {_s["drop out under CRE"]:,} of the
    {_s["tracts under CDC SVI"]:,} tracts that qualify with CDC SVI
    ({_s["share of CDC set that drops out"]:.0%}) no longer qualify with CRE, and
    {_s["enter under CRE"]:,} new ones do. FEMA's 2023 rule ranks on risk alone, which the swap
    moves less: {_f["drop out under CRE"]:,} of {_f["tracts under CDC SVI"]:,} candidate tracts
    change.
    """)
    return


@app.cell
def _(decomposition, plt, results, tracts):
    _fig, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(12, 4.8))
    _ax1.hexbin(tracts.sv_cdc, tracts.sv_cre, gridsize=50, cmap="Greys", mincnt=1, bins="log")
    _ax1.set_xlabel("v1.19 social vulnerability score (CDC SVI)")
    _ax1.set_ylabel("v1.20 social vulnerability score (Census CRE)")
    _ax1.set_title("Same tracts, two social vulnerability sources")
    _shares = decomposition.iloc[:4, 3] * 100
    _ax2.barh(_shares.index, _shares.values, color="#555")
    _ax2.set_xlabel("share of county rating changes, v1.19 to v1.20 (%)")
    _ax2.set_title("What moved county ratings (Shapley split)")
    _ax2.invert_yaxis()
    _fig.tight_layout()
    _fig.savefig(results / "sv_sources_and_churn.png", dpi=120)
    _fig
    return


@app.cell
def _(
    aggregation,
    cdrz,
    county_changes,
    crf_checks,
    decomposition,
    json,
    log,
    published_churn,
    rating_checks,
    results,
    tract_swap,
):
    crf_checks.to_csv(results / "crf_checks.csv", index=False)
    aggregation.to_csv(results / "county_aggregation_check.csv")
    rating_checks.to_csv(results / "rating_checks.csv")
    tract_swap.to_csv(results / "tract_swap.csv", header=["value"])
    county_changes.to_csv(results / "county_changes.csv")
    decomposition.to_csv(results / "churn_decomposition.csv")
    cdrz.to_csv(results / "cdrz_estimate.csv")
    _swap = county_changes.iloc[0]
    summary = {
        "tracts_matched": int(tract_swap["tracts"]),
        "tract_sv_rank_corr": round(float(tract_swap.iloc[1]), 3),
        "tract_sv_top_fifth_retained": round(float(tract_swap.iloc[2]), 3),
        "tract_risk_rank_corr": round(float(tract_swap.iloc[3]), 3),
        "tract_quintile_change_share": round(float(tract_swap.iloc[4]), 3),
        "counties": int(_swap["counties"]),
        "county_swap_rank_corr": round(float(_swap["rank correlation"]), 3),
        "county_swap_band_changes": int(_swap["change band"]),
        "county_swap_band_change_share": round(float(_swap["share changing band"]), 3),
        "county_swap_top100_overlap": int(_swap["top-100 overlap"]),
        "county_published_label_changes": published_churn,
        "churn_shapley_share": decomposition.iloc[:4, 3].round(3).to_dict(),
    }
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    log.info("summary: %s", json.dumps(summary))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this can't show, and what didn't work

    - **It holds v1.20 fixed and swaps one input.** It says what CDC SVI would have done inside
      v1.20, not what a full v1.19-style release would look like today, and not which social
      vulnerability measure is right.
    - **Our CRF is a hair off FEMA's for v1.20 tracts.** Same order and a small gap (Step 1),
      because FEMA's percentiles include a few hundred units it didn't publish. We couldn't
      identify them.
    - **County results use FEMA's v1.20 county method**, which we inferred from the data
      because the documentation describes the v1.19 one. Both are in the tables.
    - **Connecticut is in the tract results but not the county results**, because its 2022
      planning regions aren't the old counties.
    - **The resilience-zone estimate is a screen, not a designation.** It omits the CEJST filter
      FEMA used in 2023 and the geographic-balance judgment the law allows, and it uses tracts
      as of 2020.
    - **Ratings rest on k-means**, which can shift band boundaries when a few extreme values
      move. We use FEMA's documented parameters and check them against FEMA's ratings in Step 4.
    """)
    return


if __name__ == "__main__":
    app.run()
