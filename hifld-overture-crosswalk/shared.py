"""Code both notebooks use: downloads, HIFLD Next layers, OSM through QLever, Overture through DuckDB, name matching."""

import http.client
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
from rapidfuzz import fuzz

HERE = Path(__file__).parent
DATA = Path(os.environ.get("CROSSWALK_DATA_DIR", HERE / "data"))
OUT = Path(os.environ.get("CROSSWALK_OUTPUT_DIR", HERE / "output"))
HIFLD_API = "https://hifld.publicenvirodata.org/api/collections/hifld/datasets"
OVERTURE_RELEASE = "2026-09-23.0"
OVERTURE = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
QLEVER = "https://qlever.dev/api/osm-planet"
# US National Atlas Equal Area: one metric projection for all 50 states, so distances are in metres everywhere.
METRIC = "EPSG:9311"
STATES = [
    *"AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY".split(),
    *"NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split(),
]
# Boxes for the lower 48, Alaska (west of the antimeridian is skipped) and Hawaii.
US_BOXES = [(-125.0, 24.4, -66.8, 49.5), (-180.0, 51.0, -129.0, 71.6), (-161.0, 18.8, -154.7, 22.4)]
USER_AGENT = "hifld-overture-crosswalk spike"

LAYERS = pd.DataFrame(
    [
        (
            "Hospitals",
            "hospitals-3",
            "v1.1.0",
            "source_ID",
            ["hospital", "emergency_department"],
            [("amenity", "hospital")],
        ),
        (
            "Fire and EMS stations",
            "fire-and-emergency-medical-service-ems-stations",
            "v1.0.0",
            "PERMANENT_",
            ["fire_station", "ambulance_or_ems_service"],
            [("amenity", "fire_station"), ("emergency", "ambulance_station")],
        ),
        (
            "Local law enforcement",
            "local-law-enforcement-locations",
            "v1.0.0",
            "source_ID",
            ["police_station"],
            [("amenity", "police")],
        ),
        (
            "Public schools",
            "public-schools",
            "v1.0.0",
            "NCESID",
            ["elementary_school", "middle_school", "high_school", "school", "public_school"],
            [("amenity", "school")],
        ),
        ("Power plants", "power-plants-1", "v1.0.0", "PLANT_CODE", ["infrastructure:plant"], [("power", "plant")]),
    ],
    columns=["layer", "slug", "version", "id_column", "overture_categories", "osm_tags"],
).set_index("layer")


def _get(url: str, timeout: int, data: bytes | None = None, accept: str | None = None) -> bytes:
    """GET (or POST data) with up to 4 tries: long downloads through a proxy are sometimes cut off mid-transfer."""
    headers = {"User-Agent": USER_AGENT, **({"Accept": accept} if accept else {})}
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"{url} returned HTTP {response.status}")
                return response.read()
        except (http.client.IncompleteRead, ConnectionError, TimeoutError) as error:
            if attempt == 3:
                raise
            print(f"{url}: {error!r}, retrying", flush=True)
            time.sleep(10 * 2**attempt)
    raise AssertionError("unreachable")


def fetch_json(url: str) -> dict:
    return json.loads(_get(url, 120))


def fetch(url: str, name: str) -> Path:
    """Download url into DATA/name once; later runs reuse the copy."""
    path = DATA / name
    if path.exists():
        return path
    DATA.mkdir(parents=True, exist_ok=True)
    Path(f"{path}.part").write_bytes(_get(url, 900))
    Path(f"{path}.part").rename(path)
    return path


def hifld_files() -> pd.DataFrame:
    """Follow HIFLD Next's STAC links (dataset → versions → collection) to each layer's GeoParquet and download it."""
    rows = []
    for layer, spec in LAYERS.iterrows():
        dataset = fetch_json(f"{HIFLD_API}/{spec['slug']}")
        versions = fetch_json(next(link["href"] for link in dataset["links"] if link["rel"] == "child"))
        collection_url = next(
            link["href"]
            for link in versions["links"]
            if link["rel"] == "child" and f"/{spec['version']}/" in link["href"]
        )
        collection = fetch_json(collection_url)
        url = next(a["href"] for k, a in collection["assets"].items() if k.startswith("geoparquet"))
        release = re.search(r"releases/([0-9a-f]{8})", collection_url)
        rows.append((layer, url, release.group(1) if release else "", fetch(url, f"{spec['slug']}.parquet")))
    return pd.DataFrame(rows, columns=["layer", "url", "release", "path"]).set_index("layer")


def read_hifld(files: pd.DataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Every record of the five layers with the columns both notebooks use; returns (all, 50 states + DC)."""
    frames = []
    for layer, spec in LAYERS.iterrows():
        raw = gpd.read_parquet(files.loc[layer, "path"])
        frame = gpd.GeoDataFrame(
            {
                "layer": layer,
                "hifld_id": raw[spec["id_column"]].astype(str),
                "name": raw["NAME"].astype(str),
                "address": raw["ADDRESS"].astype(str),
                "city": raw["CITY"].astype(str),
                "state": raw["STATE"],
                "zip": raw.get("ZIP", raw.get("ZIPCODE", pd.Series("", index=raw.index))).astype(str).str[:5],
                "status": raw["STATUS"].astype(str) if "STATUS" in raw else "",
                "facility_type": raw["TYPE"].astype(str) if "TYPE" in raw else "",
                "source_date": raw.get("SOURCEDATE", raw.get("SOURCE_DATE", raw.get("LOADDATE"))).astype(str).str[:10],
            },
            geometry=raw.geometry,
            crs=raw.crs,
        ).to_crs(4326)
        frames.append(frame)
    every = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326)
    hifld = every[every["state"].isin(STATES)].reset_index(drop=True)
    # Public Schools' TYPE is the NCES school-type code.
    school_types = {"1": "REGULAR", "2": "SPECIAL EDUCATION", "3": "CAREER AND TECHNICAL", "4": "ALTERNATIVE"}
    schools = hifld["layer"] == "Public schools"
    hifld.loc[schools, "facility_type"] = hifld.loc[schools, "facility_type"].map(school_types)
    hifld["lon"] = hifld.geometry.x
    hifld["lat"] = hifld.geometry.y
    return every, hifld


def qlever_tsv(key: str, value: str, path: Path) -> pd.DataFrame:
    """Every OSM node, way and relation in the US (relation 148838) tagged key=value: ID, name, centroid, bounding box.

    The answer is saved to path, so later runs reuse the same planet.
    """
    if not path.exists():
        query = f"""
            PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
            PREFIX ogc: <http://www.opengis.net/rdf#>
            PREFIX osmrel: <https://www.openstreetmap.org/relation/>
            PREFIX geo: <http://www.opengis.net/ont/geosparql#>
            PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
            SELECT ?osm ?name ?centroid ?xmin ?ymin ?xmax ?ymax WHERE {{
              osmrel:148838 ogc:sfContains ?osm . ?osm osmkey:{key} "{value}" .
              ?osm geo:hasGeometry/geo:asWKT ?wkt . BIND(geof:centroid(?wkt) AS ?centroid)
              BIND(geof:minX(?wkt) AS ?xmin) BIND(geof:minY(?wkt) AS ?ymin)
              BIND(geof:maxX(?wkt) AS ?xmax) BIND(geof:maxY(?wkt) AS ?ymax)
              OPTIONAL {{ ?osm osmkey:name ?name }}
            }} ORDER BY ?osm"""
        # QLever's public endpoint closes a response after about 5 MB, so we read it in pages of 20,000 rows.
        pages = []
        for page in range(50):
            body = urllib.parse.urlencode({"query": f"{query} LIMIT 20000 OFFSET {page * 20000}"}).encode()
            lines = _get(QLEVER, 900, data=body, accept="text/tab-separated-values").decode().splitlines()
            pages.append(lines if page == 0 else lines[1:])
            if len(lines) - 1 < 20000:
                break
        else:
            raise RuntimeError(f"OSM {key}={value}: more than 50 pages")
        path.write_text("\n".join(line for lines in pages for line in lines) + "\n")
    tsv = pd.read_csv(path, sep="\t", quoting=3, dtype=str)
    xy = tsv["?centroid"].str.extract(r"POINT\(([-\d.]+) ([-\d.]+)\)").astype(float)
    return pd.DataFrame(
        {
            "osm_id": tsv["?osm"].str.extract(r"org/(\w+/\d+)>")[0],
            "name": tsv["?name"].str.strip('"').str.replace(r'"\^\^.*$', "", regex=True),
            "lon": xy[0],
            "lat": xy[1],
            **{c: pd.to_numeric(tsv[f"?{c}"]) for c in ["xmin", "ymin", "xmax", "ymax"]},
        }
    ).dropna(subset=["lon"])


def overture_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    # An empty key makes DuckDB read the public bucket anonymously instead of using any AWS credentials around.
    con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
    # Reading S3 is bound by request latency, not CPU, so more threads than cores means more reads in flight.
    con.sql("SET threads = 10")
    con.sql("SET memory_limit = '4GB'")
    con.sql("SET preserve_insertion_order = false")
    return con


def box_filter(box: tuple[float, float, float, float]) -> str:
    xmin, ymin, xmax, ymax = box
    return f"bbox.xmin > {xmin} AND bbox.xmax < {xmax} AND bbox.ymin > {ymin} AND bbox.ymax < {ymax}"


_ABBREVIATIONS = {
    "elem": "elementary",
    "el": "elementary",
    "sch": "school",
    "schl": "school",
    "hs": "high school",
    "ms": "middle school",
    "es": "elementary school",
    "jr": "junior",
    "sr": "senior",
    "ctr": "center",
    "cntr": "center",
    "hosp": "hospital",
    "med": "medical",
    "reg": "regional",
    "mem": "memorial",
    "dept": "department",
    "pd": "police department",
    "fd": "fire department",
    "vfd": "volunteer fire department",
    "co": "county",
    "twp": "township",
    "mt": "mount",
    "ft": "fort",
    "intl": "international",
    "acad": "academy",
}
_GENERIC = set(
    "the of and at school schools academy public "
    "hospital hospitals medical center centre health healthcare clinic regional general memorial community "
    "fire station stations department dept volunteer rescue ems emergency services service company district "
    "police sheriff sheriffs office county city town township village borough state law enforcement agency "
    "power plant generating station energy solar farm wind project facility llc inc".split()
)

Name = tuple[str, str, frozenset[str]]


def normalise(name: str) -> Name:
    """Return (full normalised name, its distinctive words, the numbers in it)."""
    text = re.sub(r"[^a-z0-9 ]+", " ", str(name).lower().replace("&", " and "))
    words = re.sub(r"\b([hm]) s\b", r"\1s", text).split()  # "h s" -> "hs"
    words = " ".join(_ABBREVIATIONS.get(w, w) for w in words).split()
    distinctive = [w for w in words if w not in _GENERIC and not w.isdigit()]
    return " ".join(words), " ".join(distinctive), frozenset(w for w in words if w.isdigit())


def name_score(a: Name, b: Name) -> float:
    """0-100: token-set ratio of the distinctive words; 0 when both names carry numbers and none are shared."""
    if not a[0] or not b[0]:
        return 0.0
    if a[2] and b[2] and not (a[2] & b[2]):
        return 0.0
    if a[1] and b[1]:
        return fuzz.token_set_ratio(a[1], b[1])
    return fuzz.token_sort_ratio(a[0], b[0])
