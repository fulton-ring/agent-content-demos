"""The train/held-out split of #15: every fourth state in FIPS order, from the second, is held out.

Nothing here is fitted to the answer key, so "train" only labels the states #15's agents saw. We
report both subsets so the hurricane rows line up with the other hazards.
"""

import pandas as pd

HELD_OUT_EVERY = 4
HELD_OUT_OFFSET = 1


def held_out_states(state_fips: pd.Series) -> list[str]:
    ordered = sorted(state_fips.unique())
    return ordered[HELD_OUT_OFFSET::HELD_OUT_EVERY]


def label(index: pd.Index) -> pd.Series:
    """'train' or 'held_out' for each county FIPS, from its first two digits."""
    state = pd.Series(index.str[:2], index=index)
    held = set(held_out_states(state))
    return state.map(lambda s: "held_out" if s in held else "train")
