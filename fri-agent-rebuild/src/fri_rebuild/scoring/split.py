"""Fixed split of CONUS states into training states and held-out states.

Every fourth state in FIPS order, starting with the second, is held out. The agents only ever
see scores for training states; held-out scores are computed once, after the loop ends.
"""

import pandas as pd

HELD_OUT_EVERY = 4
HELD_OUT_OFFSET = 1


def held_out_states(states: pd.Series) -> list[str]:
    ordered = sorted(states.unique())
    return ordered[HELD_OUT_OFFSET::HELD_OUT_EVERY]


def label(table: pd.DataFrame) -> pd.Series:
    """'train' or 'held_out' for each county, from its state FIPS (first two digits)."""
    state = pd.Series(table.index.str[:2], index=table.index)
    held = set(held_out_states(state))
    return state.map(lambda s: "held_out" if s in held else "train")
