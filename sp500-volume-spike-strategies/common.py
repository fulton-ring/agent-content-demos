"""Code shared by both backtest notebooks."""

import numpy as np
import pandas as pd

BOOTSTRAPS = 2000
SEED = 7


def summarize(trades: pd.DataFrame, column: str = "ret") -> dict[str, float]:
    """Headline numbers. The 95% interval resamples whole months, because events cluster."""
    x = trades[column].to_numpy()
    n = len(x)
    if n < 5:
        return {"n": n}
    wins, losses = x[x > 0].sum(), -x[x < 0].sum()
    month = trades["entry_date"].dt.to_period("M").astype(str).to_numpy()
    _, inverse = np.unique(month, return_inverse=True)
    sums = np.bincount(inverse, weights=x)
    counts = np.bincount(inverse).astype(float)
    draws = np.random.default_rng(SEED).integers(0, len(sums), size=(BOOTSTRAPS, len(sums)))
    boot = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    return {
        "n": n,
        "win_rate": float((x > 0).mean()),
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "profit_factor": float(wins / losses) if losses > 0 else float("inf"),
        "ci_low": float(np.percentile(boot, 2.5)),
        "ci_high": float(np.percentile(boot, 97.5)),
    }
