"""Variant of noaa_thresholds.py with NOAA's derived flood thresholds for every gauge.

NOAA's derived thresholds (Sweet et al. 2018) are minor = 0.04 GT + 0.50 m, moderate =
0.03 GT + 0.80 m and major = 0.04 GT + 1.17 m above MHHW, where GT is the great diurnal tide
range. CO-OPS publishes thresholds for 126 of the 187 gauges and they match this formula there,
apart from a few custom minor thresholds. Set THRESHOLD_SOURCE to "formula_missing" to use the
formula only for the 61 gauges without published thresholds.
"""

from pathlib import Path

from fri_rebuild.experiment import load_pipeline

base = load_pipeline(Path(__file__).with_name("noaa_thresholds.py"))
base.THRESHOLD_SOURCE = "formula"
gauge_factors = base.gauge_factors
