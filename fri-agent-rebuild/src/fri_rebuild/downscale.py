"""Take one hazard's final pipeline below the county: census tracts in one state.

The pipeline is rerun with tract weights instead of county weights, so each tract's multiplier
comes from the grid cells that overlap it. Tract projected annual loss = NRI v1.19 tract EAL x
tract HM. The roll-up check sums tract PAL back to counties and compares the implied county
multiplier with the pipeline's own county value and FEMA's published one.

Usage: python -m fri_rebuild.downscale <hazard folder> <column prefix> <state FIPS> <state abbr>
"""

import argparse

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from fri_rebuild import answer_key, geo, inputs, nri
from fri_rebuild.experiment import load_pipeline
from fri_rebuild.paths import HAZARDS_DIR, RESULTS_DIR

HAZARD_NRI = {"EXHT": "HWAV", "DRGT": "DRGT", "WFIR": "WFIR"}


def tract_table(
    hazard_folder: str, prefix: str, state_fips: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pipeline = load_pipeline(HAZARDS_DIR / hazard_folder / "pipeline.py")
    counties = pipeline.hazard_multipliers()
    inputs.use_tracts(state_fips)
    tracts = pipeline.hazard_multipliers()
    nri_hazard = HAZARD_NRI[prefix[:4]]
    eal = nri.tracts()[f"{nri_hazard}_EALT"]
    table = tracts.join(eal.rename("EAL"), how="left")
    table["county"] = table.index.str[:5]
    return table, counties


def roll_up(table: pd.DataFrame, counties: pd.DataFrame, column: str) -> pd.DataFrame:
    """County HM implied by summing tract PAL, next to the county pipeline and FEMA."""
    key = answer_key.load()
    pal = (table["EAL"] * table[column]).groupby(table["county"]).sum()
    eal = table["EAL"].groupby(table["county"]).sum()
    check = pd.DataFrame(
        {
            "tract_eal_sum": eal,
            "nri_county_eal": key[column[:4] + "_EALT"].reindex(eal.index),
            "rolled_up_hm": pal / eal.where(eal > 0),
            "county_pipeline_hm": counties[column].reindex(eal.index),
            "published_hm": key[column].reindex(eal.index),
            "tracts": table.groupby("county").size(),
        }
    )
    return check


def draw_map(table: pd.DataFrame, column: str, state_fips: str, title: str, path: str) -> None:
    shapes = geo.tracts(state_fips).join(table[column])
    county_lines = geo.counties()
    county_lines = county_lines[county_lines["STATEFP"] == state_fips]
    fig, ax = plt.subplots(figsize=(10, 8))
    shapes.to_crs(geo.EQUAL_AREA).plot(
        column=column,
        ax=ax,
        cmap="YlOrRd",
        legend=True,
        linewidth=0,
        legend_kwds={"label": "Hazard multiplier", "shrink": 0.6},
        missing_kwds={"color": "#ddd"},
    )
    gpd.GeoSeries(county_lines.geometry).to_crs(geo.EQUAL_AREA).boundary.plot(
        ax=ax, color="#333", linewidth=0.4
    )
    ax.set_axis_off()
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hazard_folder")
    parser.add_argument("column")
    parser.add_argument("state_fips")
    parser.add_argument("state_abbr")
    args = parser.parse_args()
    table, counties = tract_table(args.hazard_folder, args.column, args.state_fips)
    out = RESULTS_DIR / "tracts"
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / f"{args.column}_{args.state_abbr}_tracts.csv")
    check = roll_up(table, counties, args.column)
    check.to_csv(out / f"{args.column}_{args.state_abbr}_rollup.csv")
    covered = check.dropna(subset=["rolled_up_hm", "county_pipeline_hm"])
    spread = table.groupby("county")[args.column].agg(lambda s: s.max() / s.min())
    print("---")
    print(f"tracts: {len(table)} in {table['county'].nunique()} counties")
    print(f"tracts with NRI EAL: {table['EAL'].notna().sum()}")
    print(f"tract HM range: {table[args.column].min():.3f} - {table[args.column].max():.3f}")
    print(f"median within-county max/min tract HM: {spread.median():.3f}")
    eal_gap = (check["tract_eal_sum"] / check["nri_county_eal"] - 1).abs()
    print(f"max |tract EAL sum / county EAL - 1|: {eal_gap.max():.2e}")
    rel = (covered["rolled_up_hm"] / covered["county_pipeline_hm"] - 1).abs()
    print(f"rolled-up vs county pipeline HM: median |diff| {rel.median():.2%}, max {rel.max():.2%}")
    pub = covered.dropna(subset=["published_hm"])
    print(
        "rolled-up vs published HM: corr "
        f"{pub['rolled_up_hm'].corr(pub['published_hm']):.3f}, median ratio "
        f"{np.exp(np.median(np.log((pub['rolled_up_hm'] / pub['published_hm']).to_numpy()))):.3f}"
    )
    print(
        "county pipeline vs published HM: corr "
        f"{pub['county_pipeline_hm'].corr(pub['published_hm']):.3f}"
    )
    draw_map(
        table,
        args.column,
        args.state_fips,
        f"{args.column} by census tract, {args.state_abbr} (rebuilt)",
        str(out / f"{args.column}_{args.state_abbr}_tracts.png"),
    )


if __name__ == "__main__":
    main()
