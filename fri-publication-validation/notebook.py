import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import ast
    import hashlib
    import json
    import os
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import requests
    from requests.adapters import HTTPAdapter
    from scipy import stats
    from sklearn.cluster import KMeans
    from urllib3.util.retry import Retry

    from validation import (
        BANDS,
        SCENARIOS,
        VARIANTS,
        classify,
        display_score,
        names,
        projected_rating,
        relative_error,
        risk_score,
        thresholds,
    )

    started = time.monotonic()
    project = Path(mo.notebook_dir() or ".").resolve()
    repo = project.parent
    cache = Path(os.environ.get("FRI_VALIDATION_CACHE", repo.parent / "fri-validation-cache"))
    results = Path(os.environ.get("FRI_VALIDATION_RESULTS", project / "results"))
    cache.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((project / "sources.json").read_text())
    return (
        BANDS,
        HTTPAdapter,
        KMeans,
        Retry,
        SCENARIOS,
        ThreadPoolExecutor,
        VARIANTS,
        ast,
        cache,
        classify,
        display_score,
        hashlib,
        json,
        manifest,
        mo,
        names,
        np,
        pd,
        plt,
        projected_rating,
        relative_error,
        repo,
        requests,
        results,
        risk_score,
        started,
        stats,
        thresholds,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can the FRI spikes support publishing updated county and tract data?

    **Question.** Independently validate the downstream equations, classifications and baseline
    assumptions for drought, wildfire, and all four extreme-heat variants. Issue [#118](https://github.com/fulton-ring/agent-content-demos/issues/118).

    **Design.** First use FEMA's archived multipliers, not the rebuilt ones, to isolate downstream
    correctness. Compare every published county field with an independently calculated result.
    Then rescore committed rebuilt multipliers, recompute the tract pilot's roll-up, and query
    both NRI releases to test aggregation and vulnerability changes. No existing scorer or
    sensitivity function is imported. Climate pipelines and model calls are not rerun.

    **Primary method.** December 2024 FRI Technical Document §3.1–3.2, Eq. 7–10 and 14:
    PAL = EAL × HM; projected risk = PAL × unchanged CRF; ratings use fixed baseline maxima.
    Hazard-multiplier ratings are percentile bands, not changes in risk-rating category.
    The document and datasheet are downloaded and SHA-256 checked; `sources.json` pins inputs.
    """)
    return


@app.cell
def _(
    HTTPAdapter,
    Retry,
    ThreadPoolExecutor,
    cache,
    hashlib,
    manifest,
    pd,
    repo,
    requests,
):
    session = requests.Session()
    session.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
        ),
    )

    def get_json(url: str, params: dict) -> dict:
        response = session.get(url, params=params, timeout=120)
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(f"ArcGIS error: {payload['error']}")
        return payload

    def load_layer(item: tuple[str, dict]) -> tuple[str, pd.DataFrame]:
        key, spec = item
        path = cache / f"{key}.parquet"
        if not path.exists():
            url = (
                "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
                f"{spec['service']}/FeatureServer/0/query"
            )
            count = get_json(url, {"f": "json", "where": "1=1", "returnCountOnly": "true"})["count"]
            if count != spec["rows"]:
                raise ValueError(f"{key}: source row count changed; version a new snapshot")
            records = []
            for offset in range(0, count, 2000):
                if offset >= 200_000:
                    raise ValueError("Layer exceeds this spike's bounded pagination budget")
                payload = get_json(
                    url,
                    {
                        "f": "json",
                        "where": "1=1",
                        "outFields": ",".join(spec["columns"]),
                        "returnGeometry": "false",
                        "orderByFields": "OBJECTID",
                        "resultOffset": offset,
                        "resultRecordCount": 2000,
                    },
                )
                records.extend(feature["attributes"] for feature in payload["features"])
            if len(records) != count:
                raise ValueError(f"{key}: incomplete pagination")
            table = pd.DataFrame(records, columns=spec["columns"]).sort_values("OBJECTID")
        else:
            table = pd.read_parquet(path)
        assert len(table) == spec["rows"] and table.OBJECTID.is_unique
        assert set(table.NRI_VER) == {spec["version"]}
        fingerprint = hashlib.sha256(
            table.sort_values("OBJECTID").to_csv(index=False, float_format="%.12g").encode()
        ).hexdigest()
        if fingerprint != spec["normalized_csv_sha256"]:
            raise ValueError(f"{key}: snapshot changed; review it as a new input version")
        if not path.exists():
            table.to_parquet(path, index=False)
        print(f"Validated {key}: {len(table):,} rows", flush=True)
        return key, table

    for _path, _sha in manifest["local_files"].items():
        assert hashlib.sha256((repo / _path).read_bytes()).hexdigest() == _sha, _path
    for _name, _spec in manifest["downloads"].items():
        _target = cache / _name
        if not _target.exists():
            _response = session.get(_spec["url"], timeout=120)
            _response.raise_for_status()
            _partial = _target.with_suffix(".partial")
            _partial.write_bytes(_response.content)
            assert hashlib.sha256(_partial.read_bytes()).hexdigest() == _spec["sha256"]
            _partial.replace(_target)
        assert hashlib.sha256(_target.read_bytes()).hexdigest() == _spec["sha256"], _name
    with ThreadPoolExecutor(max_workers=4) as _pool:
        raw = dict(_pool.map(load_layer, manifest["arcgis"].items()))
    master = pd.read_excel(cache / "master.xlsx", dtype={"STCOFIPS": str})
    master["STCOFIPS"] = master.STCOFIPS.str.zfill(5)
    assert len(master) == 3231 and master.STCOFIPS.is_unique
    master = master.set_index("STCOFIPS")
    for _key, _table in raw.items():
        _id = "TRACTFIPS" if _key.startswith("tracts") else "STCOFIPS"
        assert _table[_id].is_unique
    return master, raw


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Reproduce the archived downstream fields before changing any inputs

    Use a single, complete county baseline for EAL and risk rating thresholds. Exact upper
    boundaries stay in the lower band. Map “No Expected Annual Losses” to “No Rating” and
    “Insufficient Data” to “Not Applicable”; do not treat either as a low-risk observation.

    County projected risk is **baseline hazard RISKV × HM**. This retains that hazard's effective
    county CRF; substituting the county's composite CRF is a different calculation (tested below).
    Scores rank projected risk separately within each scenario, including zero-valued ties and
    excluding missing risk. The observed display rule is four significant digits.

    HM rating cutpoints pool the four scenarios within each hazard/heat variant. That pooling
    and the score precision are recovered from the archive, not specified clearly in the PDF.
    We therefore test them across every county and scenario, including the many heat HMs of 1.
    """)
    return


@app.cell
def _(
    BANDS,
    SCENARIOS,
    VARIANTS,
    classify,
    display_score,
    master,
    names,
    np,
    pd,
    projected_rating,
    results,
    risk_score,
    thresholds,
):
    downstream_rows, mismatch_rows, threshold_rows, status_rows = [], [], [], []
    for _variant in VARIANTS:
        _hazard = _variant[:4]
        _eal, _risk = master[f"{_hazard}_EALT"], master[f"{_hazard}_RISKV"]
        _eal_labels, _risk_labels = master[f"{_hazard}_EALR"], master[f"{_hazard}_RISKR"]
        _eal_edges = thresholds(_eal, _eal_labels)
        _risk_edges = thresholds(_risk, _risk_labels)
        _pooled = pd.concat([master[f"{_variant}_{s}_HM"] for s in SCENARIOS])
        _hm_edges = _pooled.quantile([0.2, 0.4, 0.6, 0.8]).to_numpy()
        for _kind, _edges in [("PALR", _eal_edges), ("PRISKR", _risk_edges), ("DELTAR", _hm_edges)]:
            for _band, _edge in zip(BANDS[:-1], _edges, strict=True):
                threshold_rows.append(
                    {"variant": _variant, "field": _kind, "band": _band, "upper_edge": float(_edge)}
                )
        for _scenario in SCENARIOS:
            _prefix = f"{_variant}_{_scenario}"
            _hm = master[f"{_prefix}_HM"]
            assert _hm.notna().all() and (_hm >= 1).all()
            _pal = _eal * _hm
            _projected_risk = _risk * _hm
            _predictions = {
                "PALR": projected_rating(_pal, _eal_labels, _eal_edges),
                "PRISKR": projected_rating(_projected_risk, _risk_labels, _risk_edges),
                "PRISKS": display_score(risk_score(_projected_risk)),
                "DELTAR": classify(_hm, _hm_edges),
            }
            for _field, _predicted in _predictions.items():
                _published = master[f"{_prefix}_{_field}"]
                _expected = _published if _field == "PRISKS" else names(_published)
                _same = (_predicted.eq(_expected) | (_predicted.isna() & _expected.isna())).fillna(
                    False
                )
                downstream_rows.append(
                    {
                        "variant": _variant,
                        "scenario": _scenario,
                        "field": _field,
                        "counties": len(master),
                        "published_nonnull": int(_expected.notna().sum()),
                        "matches_including_nulls": int(_same.sum()),
                        "mismatches": int((~_same).sum()),
                        "max_unrounded_score_error": float(
                            (risk_score(_projected_risk) - _published).abs().max()
                        )
                        if _field == "PRISKS"
                        else np.nan,
                    }
                )
                for _fips in master.index[~_same]:
                    mismatch_rows.append(
                        {
                            "fips": _fips,
                            "column": f"{_prefix}_{_field}",
                            "published": _expected.loc[_fips],
                            "calculated": _predicted.loc[_fips],
                        }
                    )
                if _field != "PRISKS":
                    for _status, _count in _expected[~_expected.isin(BANDS)].value_counts().items():
                        status_rows.append(
                            {
                                "variant": _variant,
                                "scenario": _scenario,
                                "field": _field,
                                "status": _status,
                                "count": _count,
                            }
                        )
    downstream = pd.DataFrame(downstream_rows)
    downstream.to_csv(results / "downstream_checks.csv", index=False)
    pd.DataFrame(mismatch_rows, columns=["fips", "column", "published", "calculated"]).to_csv(
        results / "downstream_mismatches.csv",
        index=False,
    )
    pd.DataFrame(threshold_rows).to_csv(results / "classification_thresholds.csv", index=False)
    pd.DataFrame(status_rows).to_csv(results / "special_statuses.csv", index=False)
    downstream.groupby("field")[["counties", "published_nonnull", "mismatches"]].sum()
    return (downstream,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Rescore the rebuilt multipliers against the actual archive

    The original scorer computes rating cutpoints inside each train/held-out subset. Here the
    reference is the complete baseline, and the target is FEMA's published PALR, not a second
    calculated classification. Keep the original state split; score only baseline-rated counties.
    We separately measure how often subset thresholds change a classification. Zero-loss statuses
    are excluded from this particular accuracy denominator; section 1 validates those statuses.
    This rescores committed results; it does not independently rerun the hazard grids.
    """)
    return


@app.cell
def _(
    BANDS,
    SCENARIOS,
    VARIANTS,
    classify,
    master,
    names,
    np,
    pd,
    repo,
    results,
    thresholds,
):
    rebuilt = pd.read_csv(
        repo / "fri-agent-rebuild/results/rebuild/county_hm.csv", dtype={"fips": str}
    )
    rebuilt = rebuilt.set_index("fips")
    _states = sorted(rebuilt.index.str[:2].unique())
    held_states = set(_states[1::4])
    rebuild_rows = []
    for _variant in VARIANTS:
        _hazard = _variant[:4]
        _base_names = names(master[f"{_hazard}_EALR"])
        _full_edges = thresholds(master[f"{_hazard}_EALT"], master[f"{_hazard}_EALR"])
        for _scenario in SCENARIOS:
            _column = f"{_variant}_{_scenario}_HM"
            for _subset in ["train", "held_out"]:
                _is_held = rebuilt.index.str[:2].isin(held_states)
                _ids = rebuilt.index[_is_held if _subset == "held_out" else ~_is_held]
                _eal = master.loc[_ids, f"{_hazard}_EALT"]
                _labels = master.loc[_ids, f"{_hazard}_EALR"]
                _published = names(master.loc[_ids, f"{_variant}_{_scenario}_PALR"])
                _valid = _base_names.loc[_ids].isin(BANDS)
                _hm = rebuilt.loc[_ids, _column]
                _calculated = classify(_eal * _hm.clip(lower=1), _full_edges)
                _subset_edges = thresholds(_eal, _labels)
                _subset_rating = classify(_eal * _hm.clip(lower=1), _subset_edges)
                _baseline_hm = master.loc[_ids, _column]
                _log_error = np.log(_hm) - np.log(_baseline_hm)
                rebuild_rows.append(
                    {
                        "variant": _variant,
                        "scenario": _scenario,
                        "subset": _subset,
                        "counties": len(_ids),
                        "baseline_rated": int(_valid.sum()),
                        "missing_hm": int(_hm.isna().sum()),
                        "raw_hm_below_one": int((_hm < 1).sum()),
                        "same_published_palr": float(
                            (_calculated[_valid] == _published[_valid]).mean()
                        ),
                        "subset_threshold_changes": int(
                            (_subset_rating[_valid] != _calculated[_valid]).sum()
                        ),
                        "pearson_hm": float(_hm.corr(_baseline_hm)),
                        "mean_abs_log_error": float(_log_error.abs().mean()),
                        "median_multiplier_ratio": float((_hm / _baseline_hm).median()),
                    }
                )
    rebuild_scores = pd.DataFrame(rebuild_rows)
    rebuild_scores.to_csv(results / "rebuilt_scores.csv", index=False)
    rebuild_scores[rebuild_scores.subset == "held_out"].groupby("variant")[
        ["same_published_palr", "mean_abs_log_error", "median_multiplier_ratio"]
    ].mean()
    return held_states, rebuild_scores


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Recompute the California tract roll-up from tract rows

    Check baseline conservation and projected-loss conservation separately. A county's projected
    loss from tracts is Σ(EAL_t × HM_t). Its effective HM is that sum / ΣEAL_t. The independently
    computed county HM is area-weighted, so equality is not guaranteed. Missing tract inputs
    must not be silently skipped by a sum. Reproduce the original available-row sums, but
    separately mark incomplete counties and require complete inputs for a publishable roll-up.
    """)
    return


@app.cell
def _(master, np, pd, plt, relative_error, repo, results):
    pilot = pd.read_csv(
        repo / "fri-agent-rebuild/results/tracts/DRGT_LATE_HIGHER_HM_06_tracts.csv",
        dtype={"area_id": str, "county": str},
    )
    assert pilot.area_id.is_unique and pilot.area_id.str.len().eq(11).all()
    assert (pilot.area_id.str[:5] == pilot.county).all()
    _incomplete = pilot[["EAL", "DRGT_LATE_HIGHER_HM"]].isna().any(axis=1)
    pilot.loc[_incomplete].to_csv(results / "tract_missing_inputs.csv", index=False)
    _group = pilot.assign(PAL=pilot.EAL * pilot.DRGT_LATE_HIGHER_HM).groupby("county")
    rollup = _group[["EAL", "PAL"]].sum(min_count=1)
    _saved = pd.read_csv(
        repo / "fri-agent-rebuild/results/tracts/DRGT_LATE_HIGHER_HM_06_rollup.csv",
        dtype={"county": str},
    ).set_index("county")
    rollup["missing_tract_rows"] = _incomplete.groupby(pilot.county).sum()
    rollup["complete_inputs"] = rollup.missing_tract_rows.eq(0)
    rollup["strict_tract_eal"] = rollup.EAL.where(rollup.complete_inputs)
    rollup["strict_tract_pal"] = rollup.PAL.where(rollup.complete_inputs)
    rollup["baseline_county_eal"] = master.loc[rollup.index, "DRGT_EALT"]
    rollup["effective_tract_hm"] = rollup.PAL / rollup.EAL.where(rollup.EAL > 0)
    rollup["county_pipeline_hm"] = _saved.county_pipeline_hm
    rollup["county_pipeline_pal"] = rollup.baseline_county_eal * rollup.county_pipeline_hm
    rollup["baseline_relative_error"] = relative_error(rollup.EAL, rollup.baseline_county_eal)
    rollup["projected_relative_error"] = relative_error(rollup.PAL, rollup.county_pipeline_pal)
    assert np.allclose(rollup.EAL, _saved.tract_eal_sum, rtol=1e-12, atol=1e-8)
    assert np.allclose(rollup.effective_tract_hm, _saved.rolled_up_hm, equal_nan=True)
    rollup.to_csv(results / "tract_rollup.csv")
    tract_summary = {
        "tracts": len(pilot),
        "counties": len(rollup),
        "positive_loss_counties": int((rollup.EAL > 0).sum()),
        "missing_tract_inputs": int(pilot[["EAL", "DRGT_LATE_HIGHER_HM"]].isna().any(axis=1).sum()),
        "incomplete_counties": int((~rollup.complete_inputs).sum()),
        "complete_positive_loss_counties": int((rollup.complete_inputs & rollup.EAL.gt(0)).sum()),
        "strict_median_projected_relative_error": float(
            rollup.loc[rollup.complete_inputs, "projected_relative_error"].median()
        ),
        "strict_max_projected_relative_error": float(
            rollup.loc[rollup.complete_inputs, "projected_relative_error"].max()
        ),
        "max_baseline_relative_error": float(rollup.baseline_relative_error.max()),
        "median_projected_relative_error": float(rollup.projected_relative_error.median()),
        "max_projected_relative_error": float(rollup.projected_relative_error.max()),
    }
    _figure, _axes = plt.subplots(1, 2, figsize=(10, 3.8))
    _axes[0].scatter(rollup.baseline_county_eal, rollup.EAL, s=14)
    _axes[0].set(
        xscale="symlog",
        yscale="symlog",
        xlabel="Archived county EAL ($/year)",
        ylabel="Sum of tract EAL ($/year)",
        title="Available-row baseline sums agree",
    )
    _axes[1].hist(
        rollup.loc[rollup.complete_inputs, "projected_relative_error"].dropna() * 100,
        bins=14,
        color="#ad581e",
    )
    _axes[1].set(
        xlabel="Absolute difference from county projection (%)",
        ylabel="Counties",
        title="Complete counties: different projection weights",
    )
    _figure.suptitle("California drought • late century, higher warming • committed tract pilot")
    _figure.tight_layout()
    _figure.savefig(results / "tract_rollup.png", dpi=150)
    _figure
    return (tract_summary,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Independently check baseline versions and aggregation against FEMA attributes

    Query March 2023 (v1.19) and December 2025 (v1.20) county and tract layers. Test the composite
    **and each target hazard**. Report positive-reference counts and errors, not just a single
    composite statistic. Validate the archive's EXHT-to-NRI-HWAV mapping separately.

    A critical distinction: v1.19's composite county CRF is not generally the effective CRF for
    an individual hazard, because tract loss weights differ by hazard. Retaining county hazard
    RISKV × HM reproduces the archive; county PAL × composite CRF generally does not.

    Do not interpret a near-zero median as exact agreement everywhere: the composite has
    v1.19 tract-sum exceptions. We save every exception separately. The three target hazards
    can be assessed independently of that composite finding.
    """)
    return


@app.cell
def _(master, np, pd, raw, relative_error, results):
    aggregation_rows, baseline_rows, baseline_exceptions, aggregation_exceptions = [], [], [], []
    for _version in ["v119", "v120"]:
        _county = raw[f"counties_{_version}"].set_index("STCOFIPS")
        _tract = raw[f"tracts_{_version}"]
        for _hazard in ["ALL", "DRGT", "WFIR", "HWAV"]:
            _eal_name, _risk_name = (
                ("EAL_VALT", "RISK_VALUE")
                if _hazard == "ALL"
                else (
                    f"{_hazard}_EALT",
                    f"{_hazard}_RISKV",
                )
            )
            _sum_eal = _tract.groupby("STCOFIPS")[_eal_name].sum(min_count=1).reindex(_county.index)
            _sum_risk = (
                _tract.groupby("STCOFIPS")[_risk_name].sum(min_count=1).reindex(_county.index)
            )
            for _method, _actual, _reference in [
                ("sum_tract_eal", _sum_eal, _county[_eal_name]),
                ("sum_tract_risk", _sum_risk, _county[_risk_name]),
                (
                    "county_eal_times_composite_crf",
                    _county[_eal_name] * _county.CRF_VALUE,
                    _county[_risk_name],
                ),
            ]:
                _error = relative_error(_actual, _reference)
                aggregation_rows.append(
                    {
                        "version": _version,
                        "hazard": _hazard,
                        "method": _method,
                        "positive_reference": int((_reference > 0).sum()),
                        "compared": int(_error.notna().sum()),
                        "median_relative_error": float(_error.median()),
                        "max_relative_error": float(_error.max()),
                        "count_above_1e_minus_8_relative": int((_error > 1e-8).sum()),
                        "tract_rows_missing_field": int(
                            _tract[_eal_name if _method == "sum_tract_eal" else _risk_name]
                            .isna()
                            .sum()
                        ),
                    }
                )
                if _version == "v119" and _method.startswith("sum_tract"):
                    for _fips in _error.index[_error > 1e-8]:
                        aggregation_exceptions.append(
                            {
                                "version": _version,
                                "hazard": _hazard,
                                "method": _method,
                                "fips": _fips,
                                "tract_sum": _actual.loc[_fips],
                                "county": _reference.loc[_fips],
                                "relative_error": _error.loc[_fips],
                            }
                        )
        if _version == "v119":
            for _archive_hazard, _nri_hazard in [
                ("DRGT", "DRGT"),
                ("WFIR", "WFIR"),
                ("EXHT", "HWAV"),
            ]:
                for _metric in ["EALT", "RISKV"]:
                    _archived = master[f"{_archive_hazard}_{_metric}"]
                    _source = _county[f"{_nri_hazard}_{_metric}"].reindex(master.index)
                    _error = relative_error(_source, _archived)
                    _close = pd.Series(
                        np.isclose(_source, _archived, rtol=1e-8, atol=1e-6, equal_nan=True),
                        index=master.index,
                    )
                    baseline_rows.append(
                        {
                            "archive_hazard": _archive_hazard,
                            "nri_hazard": _nri_hazard,
                            "metric": _metric,
                            "counties": len(master),
                            "outside_tolerance": int((~_close).sum()),
                            "max_relative_error": float(_error.max()),
                            "max_absolute_error": float((_source - _archived).abs().max()),
                        }
                    )
                    for _fips in master.index[~_close]:
                        baseline_exceptions.append(
                            {
                                "fips": _fips,
                                "hazard": _archive_hazard,
                                "metric": _metric,
                                "archive": _archived.loc[_fips],
                                "march_2023_service": _source.loc[_fips],
                                "relative_error": _error.loc[_fips],
                            }
                        )
    aggregation = pd.DataFrame(aggregation_rows)
    aggregation.to_csv(results / "baseline_aggregation.csv", index=False)
    pd.DataFrame(aggregation_exceptions).to_csv(
        results / "v119_aggregation_exceptions.csv", index=False
    )
    pd.DataFrame(baseline_rows).to_csv(results / "archive_baseline_checks.csv", index=False)
    pd.DataFrame(
        baseline_exceptions,
        columns=["fips", "hazard", "metric", "archive", "march_2023_service", "relative_error"],
    ).to_csv(results / "archive_baseline_exceptions.csv", index=False)
    aggregation[aggregation.method != "sum_tract_eal"]
    return (aggregation,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Repeat the key vulnerability-sensitivity checks, holding v1.20 fixed

    Match Connecticut tracts on state plus tract digits, not their changed county prefix. Reject
    duplicate match keys. Compare SVI/CRE input ranks and rerun the documented triangular-CRF
    calculation and cube-root k-means classifications. These are **composite NRI** results,
    not measured future-hazard sensitivities. County matching excludes Connecticut's changed
    county geography; no crosswalk is invented. Do not conflate refitted NRI clusters here with
    FRI's frozen-baseline rating bins in section 1.
    """)
    return


@app.cell
def _(BANDS, KMeans, np, pd, raw, results, stats):
    def crf(social: pd.Series, resilience: pd.Series) -> pd.Series:
        rank = (social / resilience).rank(method="average", pct=True)
        return pd.Series(stats.triang.ppf(rank, c=1 / 3, loc=0.5, scale=1.5), index=social.index)

    def clusters(values: pd.Series) -> pd.Series:
        model = KMeans(n_clusters=5, n_init=20, max_iter=500, tol=1e-15, random_state=42)
        labels = model.fit_predict(np.cbrt(values.to_numpy()).reshape(-1, 1))
        order = np.argsort(np.argsort(model.cluster_centers_.ravel()))
        return pd.Series(order[labels], index=values.index)

    _old, _new = raw["tracts_v119"].copy(), raw["tracts_v120"].copy()
    for _table in [_old, _new]:
        _table["key"] = _table.TRACTFIPS.where(
            ~_table.TRACTFIPS.str.startswith("09"),
            "09" + _table.TRACTFIPS.str[5:],
        )
        assert _table.key.is_unique
    _matched = _new.merge(_old, on="key", suffixes=("_new", "_old"), validate="one_to_one")
    _matched = _matched.dropna(
        subset=[
            "SOVI_SCORE_new",
            "SOVI_SCORE_old",
            "RESL_VALUE_new",
            "RESL_VALUE_old",
            "EAL_VALT_new",
        ]
    )
    _tract_new = _matched.EAL_VALT_new * crf(_matched.SOVI_SCORE_new, _matched.RESL_VALUE_new)
    _tract_swap = _matched.EAL_VALT_new * crf(_matched.SOVI_SCORE_old, _matched.RESL_VALUE_new)
    sensitivity_rows = [
        {
            "level": "tract",
            "units": len(_matched),
            "social_score_spearman": float(
                _matched.SOVI_SCORE_new.corr(_matched.SOVI_SCORE_old, method="spearman")
            ),
            "swap_rating_changes": int((clusters(_tract_new) != clusters(_tract_swap)).sum()),
            "full_release_rating_changes": np.nan,
        }
    ]
    _counties = raw["counties_v120"].merge(
        raw["counties_v119"], on="STCOFIPS", suffixes=("_new", "_old"), validate="one_to_one"
    )
    _counties = _counties[
        _counties.RISK_RATNG_new.isin(BANDS) & _counties.RISK_RATNG_old.isin(BANDS)
    ]
    _county_new = _counties.EAL_VALT_new * crf(_counties.SOVI_SCORE_new, _counties.RESL_VALUE_new)
    _county_swap = _counties.EAL_VALT_new * crf(_counties.SOVI_SCORE_old, _counties.RESL_VALUE_new)
    sensitivity_rows.append(
        {
            "level": "county",
            "units": len(_counties),
            "social_score_spearman": float(
                _counties.SOVI_SCORE_new.corr(_counties.SOVI_SCORE_old, method="spearman")
            ),
            "swap_rating_changes": int((clusters(_county_new) != clusters(_county_swap)).sum()),
            "full_release_rating_changes": int(
                (_counties.RISK_RATNG_new != _counties.RISK_RATNG_old).sum()
            ),
        }
    )
    sensitivity = pd.DataFrame(sensitivity_rows)
    sensitivity["swap_change_share"] = sensitivity.swap_rating_changes / sensitivity.units
    sensitivity.to_csv(results / "sensitivity_checks.csv", index=False)
    sensitivity
    return (sensitivity,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Coverage and publication gates

    The tract drought pilot has one state and one scenario. LOCA2's current multiplier function
    accepts no tract weights. Its input API describes 0.25° boxes around 1/16° cell centers,
    so the claimed 6 km source grid does not establish 6 km support in these outputs. A tract
    implementation needs a reviewed weighting method. Wildfire exposes an area-weight argument
    but fits its elasticity using baseline county EAL: changing the baseline can change its HM.

    **Release sequence:** reproduce the archive → choose a county/tract aggregation contract →
    generate and validate tract outputs → version newer EAL, vulnerability, resilience, geography,
    coefficients and classification references separately. “Updated” must say which changed.
    Keep PALR/PRISKR thresholds fixed within a methodology version; distinguish them from
    scenario-relative PRISKS and pooled-scenario HM ratings. A county score and tract score have
    different ranking populations and cannot be averaged or compared as identical measures.

    **Limits.** Published PAL and projected-risk dollar values are absent from the datasheet;
    rating/score agreement validates their observable consequences, not an unpublished answer key.
    No independent climate download/rebuild, full CRF-input reconstruction, or national tract
    generation,
    future socioeconomic model, Shapley decomposition or uncertainty ensemble is claimed here.
    Source-derived static capability checks do not validate a tract hazard calculation.
    """)
    return


@app.cell
def _(
    aggregation,
    ast,
    downstream,
    hashlib,
    held_states,
    json,
    manifest,
    pd,
    rebuild_scores,
    repo,
    results,
    sensitivity,
    started,
    time,
    tract_summary,
):
    capability_rows = []
    for _path in [
        "fri-agent-rebuild/hazards/extreme_heat_loca2/pipeline.py",
        "fri-agent-rebuild/hazards/wildfire/pipeline.py",
    ]:
        _tree = ast.parse((repo / _path).read_text())
        _fn = next(
            node
            for node in _tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "hazard_multipliers"
        )
        capability_rows.append(
            {
                "path": _path,
                "parameters": [arg.arg for arg in _fn.args.args],
                "accepts_area_weights": bool(_fn.args.args),
            }
        )
    pd.DataFrame(capability_rows).to_csv(results / "tract_capabilities.csv", index=False)
    summary = {
        "archived_counties": 3231,
        "variants": 6,
        "scenarios": 4,
        "downstream_comparisons": int(downstream.counties.sum()),
        "downstream_mismatches": int(downstream.mismatches.sum()),
        "nonnull_projected_score_comparisons": int(
            downstream.loc[downstream.field == "PRISKS", "published_nonnull"].sum()
        ),
        "max_unrounded_score_error": float(downstream.max_unrounded_score_error.max()),
        "subset_threshold_classification_changes": int(
            rebuild_scores.subset_threshold_changes.sum()
        ),
        "tract_pilot": tract_summary,
        "held_out_state_fips": sorted(held_states),
        "sensitivity": json.loads(sensitivity.to_json(orient="records", double_precision=15)),
        "county_aggregation": aggregation[aggregation.method == "sum_tract_risk"].to_dict(
            orient="records"
        ),
    }
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (results / "provenance.json").write_text(
        json.dumps(
            {
                "source_repository_commit": manifest["repository_commit"],
                "public_source_hashes": manifest,
                "sha256_of_sources_json": hashlib.sha256(
                    json.dumps(manifest, sort_keys=True).encode()
                ).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    elapsed = time.monotonic() - started
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Completed in {elapsed:.1f}s; no paid services or model calls.", flush=True)
    return


if __name__ == "__main__":
    app.run()
