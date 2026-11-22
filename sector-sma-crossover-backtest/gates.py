"""Exit and re-entry gates shared by the notebooks."""

import pandas as pd


def conditional_gate(exit_signal: pd.Series, reenter_signal: pd.Series) -> pd.Series:
    """Return 1.0 while invested and 0.0 while in cash, applied from the next day.

    Starts invested. While invested, an exit signal that is True moves to cash. While in cash, a
    re-entry signal that is True moves back. Missing readings count as False and keep the state.
    """
    exits = exit_signal.fillna(False).to_numpy(dtype=bool)
    reenters = reenter_signal.fillna(False).to_numpy(dtype=bool)
    in_cash = False
    states = []
    for exit_now, reenter_now in zip(exits, reenters, strict=True):
        if not in_cash and exit_now:
            in_cash = True
        elif in_cash and reenter_now:
            in_cash = False
        states.append(0.0 if in_cash else 1.0)
    gate = pd.Series(states, index=exit_signal.index)
    return pd.concat(
        [pd.Series([1.0]), gate.iloc[:-1].reset_index(drop=True)]
    ).set_axis(exit_signal.index)


def hysteresis_gate(
    level: pd.Series, exit_above: float, reenter_at_or_below: float
) -> pd.Series:
    """Exit when `level` is above `exit_above`; re-enter when it is at or below the lower level."""
    assert reenter_at_or_below <= exit_above, (
        "re-entry must not be above the exit level"
    )
    return conditional_gate(level > exit_above, level <= reenter_at_or_below)
