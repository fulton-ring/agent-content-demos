"""Helpers both notebooks share: downloads with retries, ArcGIS paging, a cache, source checks, hazards and parcels.

The steps that make the argument stay in the notebooks; this is only the plumbing they both call.
"""

import io
import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

import geopandas as gpd
import openpyxl
import pandas as pd
import requests
import shapely
from pypdf import PdfReader

HERE = Path(__file__).parent
DATA = Path(os.environ.get("SUPPLY_CHAIN_DATA_DIR", HERE / "data"))
OUT = Path(os.environ.get("SUPPLY_CHAIN_OUTPUT_DIR", HERE / "output"))
PARCELS = Path(os.environ.get("PARCELS", HERE / "sample_parcels.csv"))
DATA.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
# Distances are in New York State Plane Long Island (feet), the projection NYC's own data uses.
NY_FEET = "EPSG:2263"
FLOOD_RANK = {"VE": 4, "V": 4, "AE": 3, "A": 3, "AO": 3, "AH": 3, "X 0.2%": 2, "X": 1, "none": 0}
NRI_RATINGS = ["Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High"]


def get(url: str, params: dict | None = None, tries: int = 4) -> requests.Response:
    """GET with a fixed number of retries; FEMA's map server drops many connections from some networks."""
    last = "no attempt"
    for attempt in range(tries):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=(20, 180),
                headers={"User-Agent": "Mozilla/5.0 (nyc-supply-chain-risk spike)"},
            )
        except requests.RequestException as error:
            last = repr(error)
        else:
            if response.status_code == 200:
                return response
            last = f"HTTP {response.status_code}"
        time.sleep(min(2**attempt, 15))
    raise RuntimeError(f"{url} failed after {tries} tries: {last}")


def arcgis(layer: str, params: dict, page: int = 1000, max_pages: int = 100) -> gpd.GeoDataFrame:
    """All features from an ArcGIS REST layer query, paged, as WGS84 GeoJSON."""
    features: list[dict] = []
    for number in range(max_pages):
        query = {"where": "1=1", "outSR": 4326, "f": "geojson"} | params
        query |= {"resultOffset": number * page, "resultRecordCount": page}
        batch = get(f"{layer}/query", query).json()
        if "features" not in batch:
            raise RuntimeError(f"{layer} returned no features: {str(batch)[:300]}")
        features += batch["features"]
        if len(batch["features"]) < page:
            return gpd.GeoDataFrame.from_features(features, crs=4326)
    raise RuntimeError(f"{layer} has more than {max_pages * page} features")


def cached(name: str, load: Callable[[], pd.DataFrame]) -> gpd.GeoDataFrame:
    """Run load() once and keep its GeoDataFrame in DATA/name (GeoParquet) for later runs."""
    path = DATA / name
    if not path.exists():
        load().to_parquet(path)
    return gpd.read_parquet(path)


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def document_text(source: str, url: str) -> list[str] | None:
    """The document's text, normalised: one entry per spreadsheet row, or one for a whole PDF or page.
    None if it can't be downloaded from here."""
    path = DATA / f"doc-{source}"
    if not path.exists():
        try:
            path.write_bytes(get(url, tries=2).content)
        except RuntimeError as error:
            print(f"unreachable: {source}: {error}")
            return None
    raw = path.read_bytes()
    if raw.startswith(b"%PDF"):
        return [normalise(" ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages))]
    if raw.startswith(b"PK"):
        book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True)
        rows = (row for sheet in book.worksheets for row in sheet.iter_rows(values_only=True))
        return [normalise(" ".join(str(c) for c in row if c is not None)) for row in rows]
    return [normalise(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "replace")))]


def check_passage(lines: list[str] | None, source: str | float, passage: str) -> str:
    """verified, passage not found, unreachable or no source. A passage "a ... b" needs every part in one row."""
    if not isinstance(source, str):
        return "no source"
    if lines is None:
        return "unreachable"
    parts = [normalise(part) for part in passage.split(" ... ")]
    return "verified" if any(all(part in line for part in parts) for line in lines) else "passage not found"


def flood_zone(geometry: shapely.Geometry) -> str:
    """Worst NFHL flood zone touching the geometry: a site's footprint, or a parcel's point."""
    if geometry.geom_type == "Point":
        shape, kind = f"{geometry.x},{geometry.y}", "esriGeometryPoint"
    else:
        # Outer rings only, simplified to about 5 m so the query fits in a URL.
        parts = getattr(geometry.simplify(0.00005), "geoms", [geometry.simplify(0.00005)])
        rings = [[list(xy) for xy in part.exterior.coords] for part in parts if part.geom_type == "Polygon"]
        shape, kind = json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}}), "esriGeometryPolygon"
    reply = get(
        "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query",
        {
            "geometry": shape,
            "geometryType": kind,
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "FLD_ZONE,ZONE_SUBTY",
            "returnGeometry": "false",
            "f": "json",
        },
        tries=12,
    ).json()
    if "features" not in reply:
        raise RuntimeError(f"NFHL error: {str(reply)[:300]}")
    zones = ["none"]
    for feature in reply["features"]:
        zone, subtype = feature["attributes"]["FLD_ZONE"], feature["attributes"]["ZONE_SUBTY"] or ""
        zones.append("X 0.2%" if zone == "X" and "0.2" in subtype else zone)
    return max(zones, key=lambda z: FLOOD_RANK.get(z, 0))


def nri_tracts() -> gpd.GeoDataFrame:
    """National Risk Index ratings for the census tracts of NYC's five counties and Hudson County, NJ."""
    layer = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Census_Tracts/FeatureServer/0"
    counties = "'36005','36047','36061','36081','36085','34017'"
    return cached(
        "nri-tracts-nyc.parquet",
        lambda: arcgis(
            layer,
            {
                "where": f"STCOFIPS IN ({counties})",
                "outFields": "TRACTFIPS,RISK_SCORE,RISK_RATNG,CFLD_RISKR,HRCN_RISKR,HWAV_RISKR,NRI_VER",
            },
        ),
    )


def hazards(points: gpd.GeoDataFrame, name: str, tracts: gpd.GeoDataFrame) -> pd.DataFrame:
    """Flood zone and NRI ratings for each geometry; flood zones are cached in DATA/name."""
    path = DATA / name
    known = json.loads(path.read_text()) if path.exists() else {}
    for key, geometry in zip(points.index, points.geometry, strict=True):
        if str(key) not in known and geometry is not None:
            known[str(key)] = flood_zone(geometry)
            path.write_text(json.dumps(known, indent=1))  # saved as we go, so a rerun resumes here
    located = points[points.geometry.notna()]
    centres = gpd.GeoDataFrame(geometry=located.geometry.representative_point(), index=located.index, crs=4326)
    # Nearest tract within 1,000 ft, so piers and barges just off the tract shoreline still get a rating.
    tract = gpd.sjoin_nearest(centres.to_crs(NY_FEET), tracts.to_crs(NY_FEET), how="left", max_distance=1000)
    tract = tract[~tract.index.duplicated()].reindex(points.index)
    return pd.DataFrame(
        {
            "flood_zone": [known.get(str(k), "not located") for k in points.index],
            "nri_overall": tract["RISK_RATNG"],
            "nri_coastal_flood": tract["CFLD_RISKR"],
            "nri_hurricane": tract["HRCN_RISKR"],
            "nri_heat_wave": tract["HWAV_RISKR"],
            "nri_score": tract["RISK_SCORE"],
            "tract": tract["TRACTFIPS"],
        },
        index=points.index,
    )


def brooklyn_lots() -> gpd.GeoDataFrame:
    """Every Brooklyn tax lot in MapPLUTO as a point, with its BBL."""

    def download() -> gpd.GeoDataFrame:
        rows: list[dict] = []
        for page in range(20):
            batch = get(
                "https://data.cityofnewyork.us/resource/64uk-42ks.json",
                {
                    "$select": "bbl,latitude,longitude",
                    "$where": "borough='BK' AND latitude IS NOT NULL",
                    "$order": "bbl",
                    "$limit": 50000,
                    "$offset": page * 50000,
                },
            ).json()
            rows += batch
            if len(batch) < 50000:
                lots = pd.DataFrame(rows)
                lots["bbl"] = lots["bbl"].astype(float).astype("int64").astype(str)
                points = gpd.points_from_xy(lots["longitude"].astype(float), lots["latitude"].astype(float))
                return gpd.GeoDataFrame(lots[["bbl"]], geometry=points, crs=4326)
        raise RuntimeError("PLUTO returned more than 1,000,000 Brooklyn lots")

    return cached("pluto-brooklyn-lots.parquet", download)


def read_parcels(path: Path, lots: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """The user's parcels: a CSV with name and bbl or lat/lon, or a GeoJSON with a name property."""
    if path.suffix.lower() in {".geojson", ".json"}:
        shapes = gpd.read_file(path).to_crs(4326)
        return gpd.GeoDataFrame({"name": shapes["name"], "bbl": None}, geometry=shapes.geometry, crs=4326)
    table = pd.read_csv(path, dtype={"bbl": str})
    if "name" not in table or not ({"bbl"} <= set(table) or {"lat", "lon"} <= set(table)):
        raise ValueError(f"{path} needs a name column and bbl or lat/lon columns")
    by_bbl = lots.set_index("bbl").geometry
    geometry: list[shapely.Geometry | None] = []
    for row in table.to_dict(orient="records"):
        bbl, lat, lon = row.get("bbl"), row.get("lat"), row.get("lon")
        if isinstance(bbl, str) and bbl in by_bbl.index:
            geometry.append(by_bbl[bbl])
        elif isinstance(lat, float | int) and isinstance(lon, float | int) and pd.notna(lat) and pd.notna(lon):
            geometry.append(shapely.Point(float(lon), float(lat)))
        else:
            geometry.append(None)
    return gpd.GeoDataFrame({"name": table["name"], "bbl": table.get("bbl")}, geometry=geometry, crs=4326)
