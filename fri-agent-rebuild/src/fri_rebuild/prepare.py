"""Download every input once into the cache (outside the repo). Safe to rerun.

Usage: uv run fri-prepare
"""

from fri_rebuild import inputs
from fri_rebuild.scoring import answer_key
from fri_rebuild.sources import fwi, geo, landfire, loca2, nex, nri, tide_gauges


def main() -> None:
    key = answer_key.conus(answer_key.load())
    print(f"answer key: {len(key)} CONUS counties")
    counties = geo.counties()
    nri.tracts()
    print("NRI v1.19 tract table: ok")
    nex.download_all()
    fwi.download_all()
    lat, lon = inputs.grid()
    geo.area_weights(counties.loc[key.index], lat, lon, "counties")
    landfire.fuel_shares(counties.loc[key.index], "counties")
    tide_gauges.tables()
    loca2.build_all()
    print("inputs ready")


if __name__ == "__main__":
    main()
