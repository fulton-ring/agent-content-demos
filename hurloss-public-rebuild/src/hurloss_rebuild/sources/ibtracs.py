"""NOAA IBTrACS v04r01, North Atlantic file, US agency (HURDAT2) values, read with CLIMADA."""

from climada.hazard import TCTracks

from hurloss_rebuild import http
from hurloss_rebuild.paths import cache_path

IBTRACS_URL = (
    "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/"
    "v04r01/access/netcdf/IBTrACS.NA.v04r01.nc"
)


def tracks(first_year: int, last_year: int) -> TCTracks:
    """Best tracks with at least one fix in the North Atlantic, `first_year`-`last_year`."""
    path = http.download(IBTRACS_URL, cache_path("ibtracs", "IBTrACS.NA.v04r01.nc"))
    loaded = TCTracks.from_ibtracs_netcdf(
        provider="usa",
        basin="NA",
        year_range=(first_year, last_year),
        estimate_missing=True,
        file_name=str(path),
    )
    if loaded.size == 0:
        raise RuntimeError("IBTrACS returned no tracks")
    return loaded
