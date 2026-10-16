"""Baseline recipe: the 2022 report's return-level curve and median relative sea level rise.

For each sub-type (minor = 1-2 year, moderate = 10-50 year, major = 100 year floods), today's
flood levels are read off the gauge's return-level curve. Each scenario lowers them by the
gauge's median relative sea level rise (1.0 m scenario for LOWER, 2.0 m for HIGHER; 2050 and
2100), and the new annual frequency is read off the same curve, capped at the shortest return
period in the table (0.1 year). The factor is the mean new frequency over the mean old one.
"""

import numpy as np

from fri_rebuild.coastal import forensics


def gauge_factors(gauge: str) -> np.ndarray | None:
    return forensics.report_factors(gauge, cap=True)
