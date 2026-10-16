"""Tide-gauge data for coastal flooding: high-tide-flooding (HTF) frequencies and sea level rise.

Sources, all NOAA:
- CO-OPS decadal HTF projections (minor/moderate/major flood days per year, 2020-2100, for the
  2022 Interagency Task Force scenarios), 110 gauges.
- CO-OPS observed annual flood counts by meteorological year (May-April), 137 gauges.
- The 2022 Sea Level Rise Technical Report data files: extreme water level return levels for the
  187 gauges FEMA cites, and relative sea level projections per gauge and 1-degree grid.
- CO-OPS flood thresholds (NOAA minor/moderate/major) and MHHW datum per gauge.
"""

import io
import zipfile

import pandas as pd

from fri_rebuild import http
from fri_rebuild.paths import cache_path

HTF_API = "https://api.tidesandcurrents.noaa.gov/dpapi/prod/webapi/htf"
STATION_API = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations"
REPORT_ZIP = (
    "https://cdn.oceanservice.noaa.gov/oceanserviceprod/hazards/sealevelrise/"
    "Sea_Level_Rise_Datasets_2022.zip"
)
EWL_FILE = "SLR_TF U.S. Extreme Water Levels_Final-tide-gauges.csv"
SLR_FILE = "SLR_TF U.S. Sea Level Projections.csv"
SEVERITIES = ("minor", "moderate", "major")


def get_json(url: str) -> dict:
    response = http.session().get(url, timeout=120)
    response.raise_for_status()
    return response.json()


def report_table(name: str) -> pd.DataFrame:
    """One CSV from the 2022 report zip, with its citation preamble skipped."""
    raw = cache_path("coastal", "Sea_Level_Rise_Datasets_2022.zip")
    if not raw.exists():
        response = http.session().get(REPORT_ZIP, timeout=300)
        response.raise_for_status()
        raw.write_bytes(response.content)
    with zipfile.ZipFile(raw) as archive:
        member = next(n for n in archive.namelist() if n.endswith(name))
        text = archive.read(member).decode("latin-1")
    lines = text.splitlines()
    header = next(
        i for i, line in enumerate(lines) if line.startswith(("EWL_GridNum", "PSMSL Site"))
    )
    return pd.read_csv(io.StringIO("\n".join(lines[header:])), low_memory=False)


def decadal_projections() -> pd.DataFrame:
    """Long table: station, lat, lon, decade, severity, scenario, flood days per year."""
    rows = []
    for record in get_json(f"{HTF_API}/htf_projection_decadal.json")["DecadalProjection"]:
        for severity in SEVERITIES:
            for entry in record[severity]:
                for scenario in ("low", "intLow", "intermediate", "intHigh", "high"):
                    rows.append(
                        {
                            "station": str(entry["stnId"]),
                            "lat": entry["lat"],
                            "lon": entry["lon"],
                            "decade": int(entry["decade"]),
                            "severity": severity,
                            "scenario": scenario,
                            "days": entry[scenario],
                        }
                    )
    return pd.DataFrame(rows)


def observed_counts() -> pd.DataFrame:
    """Observed flood days per meteorological year (May-April) and severity."""
    records = get_json(f"{HTF_API}/htf_annual.json")["AnnualFloodCount"]
    table = pd.DataFrame(records).rename(
        columns={
            "stnId": "station",
            "minCount": "minor",
            "modCount": "moderate",
            "majCount": "major",
            "nanCount": "missing_days",
        }
    )
    table["station"] = table["station"].astype(str)
    return table[["station", "lat", "lon", "year", *SEVERITIES, "missing_days"]]


def flood_thresholds(stations: list[str]) -> pd.DataFrame:
    """NOAA minor/moderate/major flood thresholds in metres above MHHW per station."""
    rows = []
    for station in stations:
        try:
            levels = get_json(f"{STATION_API}/{station}/floodlevels.json?units=metric")
            datums = get_json(f"{STATION_API}/{station}/datums.json?units=metric")
        except Exception:  # noqa: BLE001 - stations without published levels stay blank
            rows.append({"station": station})
            continue
        mhhw = next((d["value"] for d in datums.get("datums", []) if d["name"] == "MHHW"), None)
        row: dict[str, object] = {"station": station}
        for severity in SEVERITIES:
            value = levels.get(f"nos_{severity}")
            row[f"{severity}_m_above_mhhw"] = (
                None if value is None or mhhw is None else float(value) - float(mhhw)
            )
        rows.append(row)
    return pd.DataFrame(rows)


def tidal_datums(stations: list[str]) -> pd.DataFrame:
    """Great diurnal tide range (GT) and MHHW per station, in metres, from CO-OPS datums."""
    rows = []
    for station in stations:
        try:
            datums = get_json(f"{STATION_API}/{station}/datums.json?units=metric")
        except Exception:  # noqa: BLE001 - stations without published datums stay blank
            rows.append({"station": station})
            continue
        values = {d["name"]: d["value"] for d in datums.get("datums", [])}
        rows.append({"station": station, "gt_m": values.get("GT"), "mhhw_m": values.get("MHHW")})
    return pd.DataFrame(rows)


def tables() -> dict[str, pd.DataFrame]:
    """All coastal tables, cached as parquet."""
    builders = {
        "extreme_water_levels": lambda: report_table(EWL_FILE),
        "sea_level_projections": lambda: report_table(SLR_FILE),
        "htf_decadal": decadal_projections,
        "htf_observed": observed_counts,
    }
    result = {}
    for name, build in builders.items():
        path = cache_path("coastal", f"{name}.parquet")
        if not path.exists():
            table = build()
            table.columns = [str(c) for c in table.columns]
            table.to_parquet(path)
        result[name] = pd.read_parquet(path)
    path = cache_path("coastal", "flood_thresholds.parquet")
    if not path.exists():
        stations = sorted(
            {str(s) for s in result["extreme_water_levels"]["St"].dropna()}
            | set(result["htf_decadal"]["station"])
        )
        flood_thresholds(stations).to_parquet(path)
    result["flood_thresholds"] = pd.read_parquet(path)
    path = cache_path("coastal", "tidal_datums.parquet")
    if not path.exists():
        stations = sorted(str(s) for s in result["extreme_water_levels"]["St"].dropna())
        tidal_datums(stations).to_parquet(path)
    result["tidal_datums"] = pd.read_parquet(path)
    return result
