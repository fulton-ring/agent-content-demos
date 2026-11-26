"""Small, tested equations used by the readable validation notebook."""

import numpy as np
import pandas as pd

BANDS = ("Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High")
SCENARIOS = ("MID_LOWER", "MID_HIGHER", "LATE_LOWER", "LATE_HIGHER")
VARIANTS = ("DRGT", "WFIR", "EXHT_L95", "EXHT_L99", "EXHT_N95", "EXHT_N99")


def names(labels: pd.Series) -> pd.Series:
    """Drop a display range without turning a missing rating into text."""
    return labels.astype("string").str.replace(r"\s*\(.*$", "", regex=True).str.strip()


def thresholds(values: pd.Series, labels: pd.Series) -> np.ndarray:
    """FRI §3.2: full baseline's maximum observed value in each of the first four bands."""
    band = names(labels)
    edges = np.array([values[band == name].max() for name in BANDS[:-1]], dtype=float)
    if not np.isfinite(edges).all() or not (np.diff(edges) > 0).all():
        raise ValueError("Baseline needs four finite, strictly increasing rating thresholds")
    return edges


def classify(values: pd.Series, edges: np.ndarray) -> pd.Series:
    """An exact upper boundary stays in its band; missing values stay missing."""
    if len(edges) != 4 or not np.isfinite(edges).all() or not (np.diff(edges) >= 0).all():
        raise ValueError("Expected four finite nondecreasing edges (HM quantile ties are allowed)")
    result = pd.Series(pd.NA, index=values.index, dtype="string")
    valid = values.notna()
    result.loc[valid] = np.array(BANDS)[np.searchsorted(edges, values.loc[valid], side="left")]
    return result


def projected_rating(values: pd.Series, baseline: pd.Series, edges: np.ndarray) -> pd.Series:
    """Preserve archived zero-loss/no-rating and unavailable-input statuses."""
    result = classify(values, edges)
    band = names(baseline)
    result.loc[band.isin(["No Expected Annual Losses", "No Rating"])] = "No Rating"
    result.loc[band.isin(["Insufficient Data", "Not Applicable"])] = "Not Applicable"
    return result


def risk_score(values: pd.Series) -> pd.Series:
    """Scenario-specific national mean rank, including zero ties, on a 0–100 scale."""
    return values.rank(method="average", pct=True) * 100


def display_score(values: pd.Series) -> pd.Series:
    """The archived numeric fields retain four significant digits, not two decimal places."""
    return values.map(lambda value: float(f"{value:.4g}") if pd.notna(value) else np.nan)


def relative_error(actual: pd.Series, reference: pd.Series) -> pd.Series:
    """Relative error only where reference is positive and both values are available."""
    return (actual - reference).abs() / reference.where(reference > 0)
