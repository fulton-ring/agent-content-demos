"""Exit and re-entry gate with separate thresholds, shared by the notebooks."""

import pandas as pd


def hysteresis_gate(
    level: pd.Series, exit_above: float, reenter_at_or_below: float
) -> pd.Series:
    """Return 1.0 while invested and 0.0 while in cash, applied from the next day.

    Starts invested. Moves to cash when `level` is above `exit_above`, and back when it is at or
    below `reenter_at_or_below`. Days with no reading keep the previous state.
    """
    assert reenter_at_or_below <= exit_above, (
        "re-entry must not be above the exit level"
    )
    in_cash = False
    states = []
    for value in level.to_numpy():
        if pd.notna(value):
            if not in_cash and value > exit_above:
                in_cash = True
            elif in_cash and value <= reenter_at_or_below:
                in_cash = False
        states.append(0.0 if in_cash else 1.0)
    gate = pd.Series(states, index=level.index)
    return pd.concat(
        [pd.Series([1.0]), gate.iloc[:-1].reset_index(drop=True)]
    ).set_axis(level.index)
