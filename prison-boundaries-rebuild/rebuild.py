import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")

with app.setup:
    import html as htmllib
    import io
    import json
    import math
    import os
    import re
    import time
    from pathlib import Path
    from urllib.parse import quote, urljoin

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import matplotlib
    import pandas as pd
    import pdfplumber
    import requests
    import shapely

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from bs4 import BeautifulSoup
    from PIL import Image
    from rapidfuzz import fuzz

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("PRISONS_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("PRISONS_OUTPUT_DIR", HERE / "output"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    USER_AGENT = "Mozilla/5.0 (prison-boundaries-rebuild spike)"
    # The last public HIFLD Open Prison Boundaries, as mirrored by Penn State's PASDA (same change log as the
    # Data Rescue Project's copy archived 2025-08-26). It is our answer key; we only count and compare against it.
    HIFLD = "https://mapservices.pasda.psu.edu/server/rest/services/pasda/HIFLD_FEMA/MapServer/131"
    BOP = "https://www.bop.gov/PublicInfo/execute/locations?todo=query&output=json"
    QLEVER = "https://qlever.dev/api/osm-planet"
    OVERTURE = "s3://overturemaps-us-west-2/release/2026-10-21.0"
    CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
    TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    METRIC = "EPSG:9311"  # US National Atlas Equal Area: distances and areas in metres everywhere
    STATES = (
        "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
        "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY"
    ).split()
    STATE_NAMES: dict[str, str] = dict(
        zip(
            STATES,
            [
                "Alabama",
                "Alaska",
                "Arizona",
                "Arkansas",
                "California",
                "Colorado",
                "Connecticut",
                "Delaware",
                "District of Columbia",
                "Florida",
                "Georgia",
                "Hawaii",
                "Idaho",
                "Illinois",
                "Indiana",
                "Iowa",
                "Kansas",
                "Kentucky",
                "Louisiana",
                "Maine",
                "Maryland",
                "Massachusetts",
                "Michigan",
                "Minnesota",
                "Mississippi",
                "Missouri",
                "Montana",
                "Nebraska",
                "Nevada",
                "New Hampshire",
                "New Jersey",
                "New Mexico",
                "New York",
                "North Carolina",
                "North Dakota",
                "Ohio",
                "Oklahoma",
                "Oregon",
                "Pennsylvania",
                "Rhode Island",
                "South Carolina",
                "South Dakota",
                "Tennessee",
                "Texas",
                "Utah",
                "Vermont",
                "Virginia",
                "Washington",
                "West Virginia",
                "Wisconsin",
                "Wyoming",
            ],
            strict=True,
        )
    )
    # Lines that are labels, not names, when we look for the facility name above an address.
    LABEL = re.compile(
        r"^(physical|mailing|street|location|address|contact|phone|fax|warden|superintendent|county|inmate|"
        r"security|directions|map|email)\b.*|.*:$",
        re.I,
    )
    # Lower 48, Alaska east of the antimeridian, Hawaii.
    US_BOXES = [(-125.0, 24.4, -66.8, 49.5), (-180.0, 51.0, -129.0, 71.6), (-161.0, 18.8, -154.7, 22.4)]
    RUN_STARTED = time.perf_counter()


@app.function
def get(url: str, data: dict | None = None, files: dict | None = None, timeout: int = 300) -> bytes:
    """GET (or POST) with up to 4 tries and backoff; any non-200 answer is an error."""
    for attempt in range(4):
        try:
            if data is None and files is None:
                response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            else:
                response = requests.post(
                    url, data=data, files=files, headers={"User-Agent": USER_AGENT}, timeout=timeout
                )
            response.raise_for_status()
            return response.content
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as error:
            client_error = (
                isinstance(error, requests.HTTPError)
                and error.response is not None
                and error.response.status_code < 500
            )
            if attempt == 3 or client_error:
                raise
            print(f"{url}: {error!r}, retrying", flush=True)
            time.sleep(5 * 2**attempt)
    raise AssertionError("unreachable")


@app.function
def cached(name: str, url: str, data: dict | None = None) -> Path:
    """Download url into DATA/name once; later runs reuse the copy."""
    path = DATA / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        Path(f"{path}.part").write_bytes(get(url, data=data))
        Path(f"{path}.part").rename(path)
    return path


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Can we rebuild a national prison boundaries layer from public sources?

    HIFLD's *Prison Boundaries* layer (built by Oak Ridge National Laboratory) outlined every secure detention
    facility in the US, from federal prisons to county jails. It moved behind DHS's restricted GII portal, so HIFLD
    Next can't republish it. This notebook asks whether we can rebuild it from sources anyone can download:

    1. **Points**: the Federal Bureau of Prisons' facility list, plus each state department of corrections' list.
    2. **Outlines**: an OpenStreetMap `amenity=prison` polygon, or failing that an Overture building footprint.
    3. **Check**: against the last public HIFLD copy (the answer key) and by eye on aerial imagery.

    It's wrong if fewer than about half the states publish usable lists, or most facilities end up with no polygon.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The answer key: the last public HIFLD layer

    The public layer was taken down, but Penn State's PASDA still serves a copy (its change log, "80 records added,
    132 closed, 30 reopened, and 363 removed", matches the Data Rescue Project's copy archived in August 2025).
    We download it to count and compare against; nothing from it goes into our output.
    """)
    return


@app.cell
def _():
    _pages = [
        cached(
            f"hifld/page-{_offset}.geojson",
            f"{HIFLD}/query?where=1%3D1&outFields=*&outSR=4326&f=geojson&orderByFields=OBJECTID"
            f"&resultOffset={_offset}&resultRecordCount=1000",
        )
        for _offset in range(0, 10_000, 1000)
    ]
    _frames = [gpd.read_file(p) for p in _pages]
    hifld = gpd.GeoDataFrame(pd.concat([f for f in _frames if len(f)], ignore_index=True), crs=4326)
    _expected = json.loads(get(f"{HIFLD}/query?where=1%3D1&returnCountOnly=true&f=json"))["count"]
    assert len(hifld) == _expected, f"read {len(hifld)} HIFLD records, the server has {_expected}"
    hifld = hifld[hifld["STATE"].isin(STATES)].to_crs(METRIC)
    hifld_counts = pd.crosstab(hifld["TYPE"], hifld["STATUS"], margins=True, margins_name="total")
    hifld_counts.to_csv(OUT / "hifld_counts.csv")
    _latest = pd.to_datetime(pd.to_numeric(hifld["SOURCEDATE"], errors="coerce"), unit="ms").max().date()
    print(f"HIFLD records in the 50 states and DC: {len(hifld)}, latest SOURCEDATE {_latest}")
    hifld_counts
    return (hifld,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Which states publish a usable list?

    Before writing any code we looked at every state's corrections agency site (and its GIS portal) by hand, with
    subagents fetching each page. `state_sources.csv` records, for each state: the page, any machine-readable
    download, the format, whether it gives addresses or coordinates, the date shown, and whether a script can read
    it. "Usable" means it gives a street address or coordinates for each facility and a script can read it.
    """)
    return


@app.cell
def _():
    sources = pd.read_csv(HERE / "state_sources.csv", dtype=str).fillna("")
    assert sorted(sources["state"]) == sorted(STATES), "state_sources.csv needs one row per state and DC"
    sources["located"] = sources["has_coordinates"].eq("yes") | sources["has_addresses"].isin(["yes", "partial"])
    sources["usable"] = sources["located"] & sources["scriptable"].eq("yes")
    source_summary = pd.DataFrame(
        {
            "states (incl. DC)": [len(sources)],
            "list gives addresses or coordinates": [int(sources["located"].sum())],
            "...and a script can read it (usable)": [int(sources["usable"].sum())],
            "list has coordinates": [int(sources["has_coordinates"].eq("yes").sum())],
            "machine-readable file or API": [
                int(sources["format"].isin(["csv", "json", "arcgis", "geojson", "xlsx"]).sum())
            ],
        }
    ).T.rename(columns={0: "count"})
    source_summary.to_csv(OUT / "source_summary.csv")
    print("usable:", " ".join(sources.loc[sources["usable"], "state"]))
    print("not usable:", " ".join(sources.loc[~sources["usable"], "state"]))
    source_summary
    return (sources,)


@app.cell
def _(sources):
    mo.ui.table(
        sources[
            [
                "state",
                "agency",
                "format",
                "n_facilities",
                "has_coordinates",
                "has_addresses",
                "last_updated",
                "scriptable",
                "source_url",
            ]
        ],
        selection=None,
        page_size=51,
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Federal prisons: the Bureau of Prisons

    BOP's facility locator is backed by a JSON endpoint that lists every location with coordinates. We keep the
    institutions and leave out regional offices, reentry-management offices, the central office, training centres
    and the complex records (an FCC's component prisons are listed separately).
    """)
    return


@app.cell
def _():
    _bop = pd.DataFrame(json.loads(cached("bop.json", BOP).read_bytes())["Locations"])
    _institutions = ["FCI", "USP", "FPC", "FMC", "FDC", "MDC", "MCC", "FTC", "MCFP"]
    print("BOP location types:", _bop["type"].value_counts().to_dict())
    bop = pd.DataFrame(
        {
            "source": "BOP",
            "state": _bop["state"],
            "name": _bop["nameDisplay"],
            "address": _bop["address"],
            "city": _bop["city"],
            "zip": _bop["zipCode"].str[:5],
            "lon": pd.to_numeric(_bop["longitude"], errors="coerce"),
            "lat": pd.to_numeric(_bop["latitude"], errors="coerce"),
            "kind": _bop["type"],
            "source_url": "https://www.bop.gov" + _bop["url"],
            "licence": "public domain (US government)",
        }
    )[_bop["type"].isin(_institutions)].reset_index(drop=True)
    print(f"{len(bop)} BOP institutions, {bop['lon'].notna().sum()} with coordinates")
    return (bop,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## State prisons: one generic scraper for every state's list

    Writing 50 bespoke parsers would prove only that we can write parsers. Instead every state goes through the
    same small scraper, set up by a few columns in `state_sources.csv`:

    - `fetch`: `vector` (ArcGIS, GeoJSON or KML, read with GeoPandas), `json`, `html`, `raw` (HTML hidden inside
      escaped JavaScript), `pdf`, or `none` when the survey found nothing a script can read;
    - `selector`: a CSS selector for one facility per element, when the page has one;
    - `link_pattern`: when addresses are only on per-facility pages, which links to follow;
    - `after`, `keep`, `exclude`: where on a page the address starts, and which names to keep or drop.

    A US street address is found with one regular expression (number, street, city, state, ZIP), skipping PO
    boxes. We then compare what the scraper got with the survey's hand count.
    """)
    return


@app.function
def page_text(html: str) -> str:
    """Visible text of an HTML page, one line per block, without scripts or styles."""
    soup = BeautifulSoup(html.replace("<br>", "\n").replace("<br />", "\n").replace("<br/>", "\n"), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    # A "(map)" link after a street would hide the street from the address pattern.
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]*\(\s*map\s*\)", "", soup.get_text("\n")))


@app.function
def addresses(text: str, state: str, po_boxes: bool = False) -> list[dict]:
    """Every street address in text for this state ('123 Main St, Town, ST 12345').

    PO boxes are left out, or with po_boxes kept with an empty street (the town and ZIP still say where it is)."""
    po_box = r"P\.?\s*O\.?\s*Box\s+\d[A-Za-z0-9 .#'&/-]{0,60}?|" if po_boxes else ""
    pattern = re.compile(
        rf"(?<![\d-])(?P<street>{po_box}(?:\d{{1,3}}-)?\d{{1,6}}\s+[A-Za-z][A-Za-z0-9 .#'&/-]{{1,60}}?)"
        r"[ \t]*(?:,|\n)\s*"
        r"(?:(?P<middle>[A-Za-z0-9 .#'-]{1,40})\n\s*)?"
        rf"(?P<city>[A-Za-z][A-Za-z .'-]{{1,30}}?)\s*,?\s+(?:{state}|{STATE_NAMES[state]})\.?,?\s+(?P<zip>\d{{5}})"
    )
    found = []
    for m in pattern.finditer(text):
        po_box = bool(re.search(r"\b(p\.?\s*o\.?\s*box|box)\b", m["street"], re.I))
        if po_box and not po_boxes:
            continue
        # 'P.O. Box 12' followed by a street line: the street is the location.
        street_after_box = m["middle"].strip() if m["middle"] and re.match(r"\d+\s+[A-Za-z]", m["middle"]) else ""
        found.append(
            {
                "street": re.sub(r"\s+", " ", m["street"]).strip() if not po_box else street_after_box,
                "city": m["city"].strip(),
                "zip": m["zip"],
                "start": m.start(),
            }
        )
    return found


@app.function
def pick(record: dict, *candidates: str) -> str:
    """The first non-empty field of record whose lower-cased name is one of candidates."""
    lower = {str(k).lower(): k for k in record}
    for name in candidates:
        value = record.get(lower.get(name, ""), None)
        if value not in (None, "") and not (isinstance(value, float) and math.isnan(value)):
            return str(value).strip()
    return ""


@app.function
def from_record(record: dict) -> dict:
    """A facility from a GIS or JSON record, whatever its field names."""
    return {
        "name": pick(
            record,
            "name",
            "facility",
            "county facility",
            "county correctional institution",
            "facility_name",
            "agency_name",
            "prison_name",
            "institution",
            "title",
            "landmkname",
        ),
        "address": pick(record, "address", "street address", "addressline1", "physical_address", "street", "address1"),
        "city": pick(record, "city", "town", "city_1"),
        "zip": pick(record, "zip", "zipcode", "zip5", "zip_code").split(".")[0][:5],
        "lat": pick(record, "latitude", "lat", "n_lat"),
        "lon": pick(record, "longitude", "lon", "lng", "n_lon"),
    }


@app.function
def scrape_state(cfg: dict) -> list[dict]:
    """Facilities from one source, as configured by its row of state_sources.csv or jail_sources.csv."""
    state, fetch, options = cfg["state"], cfg["fetch"], cfg["options"].split()
    po_boxes = "by_name" in options
    rows: list[dict] = []
    for url in cfg["list_urls"].split():
        if fetch == "vector":
            layer = gpd.read_file(io.BytesIO(get(url)))
            for record, geom in zip(layer.drop(columns="geometry").to_dict("records"), layer.geometry, strict=True):
                rows.append(from_record(record) | ({"lon": geom.x, "lat": geom.y} if geom is not None else {}))
            continue
        body = get(url)
        if fetch == "json" and not cfg["link_pattern"]:
            data = json.loads(body)
            rows += [from_record(r) for r in (data if isinstance(data, list) else data["items"])]
            continue
        if fetch == "pdf_table":
            rows += pdf_table_rows(cfg, body)
            continue
        html = body.decode("utf-8", "replace")
        if cfg["link_pattern"]:
            rows += follow_links(cfg, url, html)
            continue
        if fetch == "pdf":
            with pdfplumber.open(io.BytesIO(body)) as pdf:
                pages = pdf.pages
                if "two_columns" in options:
                    pages = [
                        p.crop(box)
                        for p in pages
                        for box in [(0, 0, p.width / 2, p.height), (p.width / 2, 0, p.width, p.height)]
                    ]
                text = "\n".join(p.extract_text() or "" for p in pages)
            if cfg["selector"]:
                # In a PDF the selector is a regular expression for one facility's line, with named groups.
                rows += [m.groupdict() for m in re.finditer(cfg["selector"], text, re.M)]
                continue
        elif fetch == "raw":
            for _ in range(5):
                html = htmllib.unescape(html.replace("\\u0026", "&")).replace("\\/", "/").replace('\\"', '"')
            # The facility list sits inside a script tag, so strip tags with a regex rather than parse the page.
            text = re.sub(r"\n\s*\n+", "\n", re.sub(r"<[^>]+>", "\n", html))
        else:
            text = ""
        items = BeautifulSoup(html, "html.parser").select(cfg["selector"]) if cfg["selector"] else []
        if items:
            for item in items:
                block = page_text(str(item))
                if cfg["keep"] and not re.search(cfg["keep"], block):
                    continue
                lines = [ln.strip() for ln in block.split("\n") if ln.strip() and not LABEL.match(ln.strip())]
                found = addresses(block, state, po_boxes)
                rows.append(
                    {
                        "name": lines[0] if lines else "",
                        "lat": item.get("data-lat", ""),
                        "lon": item.get("data-lng", ""),
                    }
                    | ({k: found[0][k] for k in ["city", "zip"]} | {"address": found[0]["street"]} if found else {})
                )
            continue
        text = text or page_text(html)
        for found in addresses(text, state, po_boxes):
            before = [
                ln.strip() for ln in text[: found["start"]].split("\n") if ln.strip() and not LABEL.match(ln.strip())
            ]
            rows.append(
                {
                    "name": before[-1] if before else "",
                    "address": found["street"],
                    "city": found["city"],
                    "zip": found["zip"],
                }
            )
    return rows


@app.function
def pdf_table_rows(cfg: dict, body: bytes) -> list[dict]:
    """Rows of every PDF table with a header row whose first cell matches the selector, read by column name."""
    rows = []
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                cells = [[re.sub(r"\s+", " ", c or "").strip() for c in row] for row in table]
                starts = [i for i, row in enumerate(cells) if row and re.search(cfg["selector"], row[0])]
                if not starts:
                    continue
                header = cells[starts[0]]
                for row in cells[starts[0] + 1 :]:
                    if cfg["keep"] and not re.search(cfg["keep"], " | ".join(row)):
                        continue
                    rows.append(from_record(dict(zip(header, row, strict=False))))
    return rows


@app.function
def follow_links(cfg: dict, url: str, html: str) -> list[dict]:
    """Open every link on a list page (or in a JSON list) that matches link_pattern and read its address.

    link_pattern is a regular expression for the link, or 'css <selector>' for the links a CSS selector picks. With a
    selector, each element it picks on a linked page is one facility; otherwise each page is one facility."""
    links: dict[str, str] = {}
    soup = BeautifulSoup(html, "html.parser")
    by_css = cfg["link_pattern"].startswith("css ")
    for a in soup.select(cfg["link_pattern"][4:]) if by_css else soup.find_all("a", href=True):
        href = str(a.get("href", ""))
        if href and (by_css or re.search(cfg["link_pattern"], href)):
            links.setdefault(urljoin(url, href), a.get_text(" ", strip=True))
    for href in re.findall(r'"(?:url|link)"\s*:\s*"([^"]+)"', html):
        href = href.replace("\\/", "/")
        if not by_css and re.search(cfg["link_pattern"], href):
            links.setdefault(urljoin(url, href), "")
    rows = []
    for link, label in list(links.items())[:200]:
        try:
            page = get(link).decode("utf-8", "replace")
        except requests.RequestException as error:
            print(f"{cfg['state']}: {link} failed: {error!r}")
            continue
        if cfg["selector"]:
            for item in BeautifulSoup(page, "html.parser").select(cfg["selector"]):
                block = page_text(str(item))
                lines = [ln.strip() for ln in block.split("\n") if ln.strip() and not LABEL.match(ln.strip())]
                found = addresses(block, cfg["state"], "by_name" in cfg["options"])
                rows.append(
                    {"name": lines[0] if lines else ""}
                    | (
                        {"address": found[0]["street"], "city": found[0]["city"], "zip": found[0]["zip"]}
                        if found
                        else {}
                    )
                )
            time.sleep(0.3)
            continue
        text = page_text(page)
        start = re.search(cfg["after"], text) if cfg["after"] else None
        if start:
            text = text[start.end() :]
        h1 = BeautifulSoup(page, "html.parser").find("h1")
        name = label or (h1.get_text(" ", strip=True) if h1 else "")
        if cfg["keep"] and not re.search(cfg["keep"], name):
            continue
        if "map_address" in cfg["options"]:
            # The street address is only in the title of the page's Google Maps embed, with no ZIP.
            title = re.search(r'title="Google map for ([^"]+)"', page)
            rows.append({"name": name, "address": " ".join(htmllib.unescape(title[1]).split()) if title else ""})
            continue
        found = addresses(text, cfg["state"], "by_name" in cfg["options"])
        rows.append(
            {"name": name}
            | ({"address": found[0]["street"], "city": found[0]["city"], "zip": found[0]["zip"]} if found else {})
        )
        time.sleep(0.3)
    return rows


@app.function
def read_sources(sources: pd.DataFrame, folder: str) -> pd.DataFrame:
    """Scrape each source row once (cached in DATA/folder/<ST>.csv) and drop rows that are not facilities."""
    frames = []
    for cfg in sources[sources["fetch"].ne("none")].to_dict("records"):
        path = DATA / folder / f"{cfg['state']}.csv"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                rows = scrape_state(cfg)
            except (requests.RequestException, ValueError, KeyError) as error:
                print(f"{folder}/{cfg['state']}: failed, {error!r}")
                rows = []
            pd.DataFrame(rows, columns=["name", "address", "city", "zip", "lat", "lon"]).to_csv(path, index=False)
        f = pd.read_csv(path, dtype=str).fillna("")
        # Drop names that are phone numbers or addresses, and rows we can't locate (unless the source is one whose
        # rows we place by name). The same address and ZIP twice is a head office repeated on every page.
        f = f[f["name"].str.len().between(3, 120) & ~f["name"].str.match(r"^[\d(]")]
        f = f[f["address"].ne("") | f["lat"].ne("") | ("by_name" in cfg["options"].split())]
        f = f[f["zip"].eq("") | f["address"].eq("") | ~(f["address"] + f["zip"]).duplicated()]
        if cfg["exclude"]:
            f = f[~f["name"].str.contains(cfg["exclude"], case=False, regex=True)]
        frames.append(f.drop_duplicates("name").assign(state=cfg["state"], source_url=cfg["source_url"]))
    rows = pd.concat(frames, ignore_index=True)
    rows["lon"] = pd.to_numeric(rows["lon"], errors="coerce")
    rows["lat"] = pd.to_numeric(rows["lat"], errors="coerce")
    # A few GIS layers use a projected X/Y; anything outside the US boxes is treated as no coordinates.
    bad = ~rows["lon"].between(-180, -66) | ~rows["lat"].between(18, 72)
    rows.loc[bad, ["lon", "lat"]] = float("nan")
    return rows


@app.function
def yield_table(rows: pd.DataFrame, sources: pd.DataFrame) -> pd.DataFrame:
    """Per state: rows scraped, with an address, with coordinates, or a name only, against the expected count."""
    counts = rows.groupby("state").agg(
        scraped=("name", "size"),
        with_address=("address", lambda s: int(s.ne("").sum())),
        with_coordinates=("lon", lambda s: int(s.notna().sum())),
    )
    counts["name_only"] = (
        rows[rows["address"].eq("") & rows["lon"].isna()].groupby("state").size().reindex(counts.index, fill_value=0)
    )
    table = sources.set_index("state")[["fetch", "n_facilities", "reason"]].join(counts).fillna({"scraped": 0})
    table["hand_count"] = pd.to_numeric(table.pop("n_facilities"), errors="coerce")
    table["located"] = table[["with_address", "with_coordinates"]].max(axis=1).fillna(0)
    table["located_share_of_hand_count"] = (table["located"] / table["hand_count"]).round(2)
    return table[[c for c in table.columns if c != "reason"] + ["reason"]]


@app.cell
def _(sources):
    _s = read_sources(sources, "states")
    state_rows = pd.DataFrame(
        {
            "source": _s["state"] + " DOC",
            "state": _s["state"],
            "name": _s["name"],
            "address": _s["address"],
            "city": _s["city"],
            "zip": _s["zip"],
            "lon": _s["lon"],
            "lat": _s["lat"],
            "kind": "state",
            "source_url": _s["source_url"],
            "licence": "state government public record (terms vary by state)",
        }
    )
    scrape_yield = yield_table(state_rows, sources)
    scrape_yield.to_csv(OUT / "scrape_yield.csv")
    print(
        f"{len(state_rows)} state rows from {state_rows['state'].nunique()} states; "
        f"states where the scraper located at least 80% of the hand count: "
        f"{int((scrape_yield['located_share_of_hand_count'] >= 0.8).sum())}; "
        f"name only, placed later by name: {int(scrape_yield['name_only'].sum())}"
    )
    scrape_yield
    return (state_rows,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## County and local jails: the states that publish a jail list

    No national public list of jails with locations exists (BJS's Census of Jails facility file is restricted; the
    NIC National Jails Compendium isn't published). But several states regulate their county jails through a
    jail-standards body, and some of those publish a list. `jail_sources.csv` configures them for the same scraper:
    GIS layers with coordinates, DOC location pages, and PDFs. Two scraper settings exist for the PDFs: `pdf_table`
    reads a table by its column names (the `selector` is the first header cell), and for a `pdf` the `selector` can
    be a regular expression for one facility's line. Where a list gives only names (Tennessee, Kentucky,
    California), the rows are kept (`by_name`) and placed later by the same Overture name match as the state lists.
    The `hand_count` here is the count the source itself states or that we counted by hand in the file.
    """)
    return


@app.cell
def _():
    jail_sources = pd.read_csv(HERE / "jail_sources.csv", dtype=str).fillna("")
    jail_sources["reason"] = ""
    _j = read_sources(jail_sources, "jails")
    jail_rows = pd.DataFrame(
        {
            "source": _j["state"] + " jail list",
            "state": _j["state"],
            "name": _j["name"],
            "address": _j["address"],
            "city": _j["city"],
            "zip": _j["zip"],
            "lon": _j["lon"],
            "lat": _j["lat"],
            "kind": "local jail",
            "source_url": _j["source_url"],
            "licence": "state government public record (terms vary by state)",
        }
    )
    jail_yield = yield_table(jail_rows, jail_sources).drop(columns="reason")
    jail_yield.to_csv(OUT / "jail_yield.csv")
    print(f"{len(jail_rows)} local jails from {jail_rows['state'].nunique()} state lists")
    jail_yield
    return (jail_rows,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Geocoding addresses

    Most state lists give a street address, not coordinates. We send every row without coordinates to the US
    Census batch geocoder (free, no key). Colorado's addresses come from map titles with no ZIP and no comma before
    the town, which the batch format can't split, so those go one at a time to the geocoder's one-line endpoint.
    Prisons are often on rural routes or PO boxes the geocoder can't place, so we count how many it misses. Rows it
    can't place, and rows that only have a name, get an Overture place whose name matches.
    """)
    return


@app.cell
def _(bop, jail_rows, places, state_rows):
    facilities = pd.concat([bop, state_rows, jail_rows], ignore_index=True)
    facilities["facility_id"] = [f"F{i:05d}" for i in range(len(facilities))]
    facilities["group"] = facilities["kind"].map({"state": "state DOC", "local jail": "local jail"}).fillna("BOP")
    facilities["location"] = facilities["lon"].notna().map({True: "source coordinates", False: ""})
    _no_town = facilities["city"].fillna("").eq("")
    _todo = facilities[facilities["lon"].isna() & facilities["address"].fillna("").ne("") & ~_no_town]
    _body = io.StringIO()
    _todo[["facility_id", "address", "city", "state", "zip"]].to_csv(_body, header=False, index=False)
    _path = DATA / f"geocode-{len(_todo)}.csv"
    if len(_todo) and not _path.exists():
        _path.write_bytes(
            get(
                CENSUS_GEOCODER,
                data={"benchmark": "Public_AR_Current"},
                files={"addressFile": ("addresses.csv", _body.getvalue(), "text/csv")},
                timeout=900,
            )
        )
    if len(_todo):
        _g = pd.read_csv(_path, header=None, dtype=str, names=list(range(8))).set_index(0)
        _xy = _g[5].str.split(",", expand=True)
        _match = facilities["facility_id"].map(_g[2]).eq("Match")
        facilities.loc[_match, "lon"] = pd.to_numeric(facilities.loc[_match, "facility_id"].map(_xy[0]))
        facilities.loc[_match, "lat"] = pd.to_numeric(facilities.loc[_match, "facility_id"].map(_xy[1]))
        facilities["location"] = facilities["location"].where(~_match, "Census geocoder")
    _oneline = facilities[facilities["lon"].isna() & facilities["address"].fillna("").ne("") & _no_town]
    _path = DATA / f"geocode-oneline-{len(_oneline)}.json"
    if not _path.exists():
        _found = {}
        for _address in _oneline["address"].unique()[:200]:
            _url = (
                f"{CENSUS_GEOCODER.replace('addressbatch', 'onelineaddress')}?benchmark=Public_AR_Current&format=json"
            )
            _hits = json.loads(get(f"{_url}&address={quote(_address)}"))["result"]["addressMatches"]
            _found[_address] = [_hits[0]["coordinates"]["x"], _hits[0]["coordinates"]["y"]] if _hits else None
        _path.write_text(json.dumps(_found))
    _found = json.loads(_path.read_text())
    for _i in _oneline.index:
        if _found.get(facilities.at[_i, "address"]):
            facilities.loc[_i, ["lon", "lat"]] = _found[facilities.at[_i, "address"]]
            facilities.at[_i, "location"] = "Census geocoder"
    # Fallback for addresses the geocoder can't place: an Overture jail_or_prison place in the same state whose
    # name matches (token-set similarity of at least 90, and a clear best).
    _region = places["region"].fillna("").str.replace("US-", "", regex=False).str.upper()
    _xy = places.to_crs(4326).geometry
    for _i in facilities.index[facilities["lon"].isna()]:
        _cand = places.index[_region.eq(facilities.at[_i, "state"])]
        _scores = [fuzz.token_set_ratio(facilities.at[_i, "name"], places.at[j, "place_name"] or "") for j in _cand]
        _ranked = sorted(zip(_scores, _cand, strict=True), reverse=True)
        if _ranked and _ranked[0][0] >= 90 and (len(_ranked) == 1 or _ranked[1][0] < _ranked[0][0]):
            facilities.loc[_i, ["lon", "lat"]] = [_xy[_ranked[0][1]].x, _xy[_ranked[0][1]].y]
            facilities.at[_i, "location"] = "Overture place name match"
    facilities["location"] = facilities["location"].where(facilities["lon"].notna(), "not located")
    geocode_summary = pd.crosstab(
        facilities["group"],
        facilities["location"],
        margins=True,
        margins_name="total",
    )
    geocode_summary.to_csv(OUT / "geocode_summary.csv")
    geocode_summary
    return (facilities,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Outlines from OpenStreetMap and Overture

    **OSM.** Overpass reset our connections, so as in the crosswalk spike we ask [QLever](https://qlever.dev), a
    SPARQL engine over the whole OSM planet, for every `amenity=prison` node, way and relation in the US, with its
    full geometry. OSM is ODbL: anything derived from it is share-alike, so OSM-derived files stay out of git.

    **Overture places.** Every place whose category is `jail_or_prison` or `juvenile_detention_center`
    (CDLA-Permissive-2.0, points only).

    **Overture buildings.** Footprints near each facility point (Overture distributes buildings under ODbL; most
    come from OSM, Microsoft and Google footprints). A footprint is the building, not the fence line, so it is the
    fallback when OSM has no prison outline.
    """)
    return


@app.cell
def _():
    _path = DATA / "osm-amenity-prison.tsv"
    if not _path.exists():
        _query = """
            PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
            PREFIX ogc: <http://www.opengis.net/rdf#>
            PREFIX osmrel: <https://www.openstreetmap.org/relation/>
            PREFIX geo: <http://www.opengis.net/ont/geosparql#>
            SELECT ?osm ?name ?wkt WHERE {
              osmrel:148838 ogc:sfContains ?osm . ?osm osmkey:amenity "prison" .
              ?osm geo:hasGeometry/geo:asWKT ?wkt . OPTIONAL { ?osm osmkey:name ?name }
            } ORDER BY ?osm"""
        _response = requests.post(
            QLEVER, data={"query": _query}, headers={"Accept": "text/tab-separated-values"}, timeout=600
        )
        _response.raise_for_status()
        _path.write_text(_response.text)
    _tsv = pd.read_csv(_path, sep="\t", quoting=3, dtype=str)
    osm = gpd.GeoDataFrame(
        {
            "osm_id": _tsv["?osm"].str.extract(r"org/(\w+/\d+)>")[0],
            "osm_name": _tsv["?name"].str.strip('"').str.replace(r'"\^\^.*$', "", regex=True),
        },
        geometry=shapely.from_wkt(_tsv["?wkt"].str.strip('"').str.replace(r'"\^\^.*$', "", regex=True)),
        crs=4326,
    ).to_crs(METRIC)
    osm["polygon"] = osm.geom_type.isin(["Polygon", "MultiPolygon"])
    print(f"OSM amenity=prison in the US: {len(osm)} features, {osm['polygon'].sum()} of them polygons")
    return (osm,)


@app.cell
def _():
    _path = DATA / "overture-places-prisons.parquet"
    if not _path.exists():
        _con = duckdb.connect()
        _con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        _con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
        _boxes = " OR ".join(
            f"(bbox.xmin > {a} AND bbox.xmax < {c} AND bbox.ymin > {b} AND bbox.ymax < {d})" for a, b, c, d in US_BOXES
        )
        _con.sql(f"""
            COPY (
                SELECT id AS place_id, names.primary AS place_name, taxonomy.primary AS category,
                       sources[1].dataset AS place_source, sources[1].license AS place_licence,
                       addresses[1].region AS region,
                       ST_X(geometry) AS lon, ST_Y(geometry) AS lat
                FROM read_parquet('{OVERTURE}/theme=places/type=place/*.parquet')
                WHERE ({_boxes}) AND basic_category = 'jail_or_prison'
            ) TO '{_path}.part' (FORMAT parquet)""")
        Path(f"{_path}.part").rename(_path)
    _p = pd.read_parquet(_path)
    places = gpd.GeoDataFrame(_p, geometry=gpd.points_from_xy(_p["lon"], _p["lat"]), crs=4326).to_crs(METRIC)
    print(f"Overture jail_or_prison places in the US boxes: {len(places)}")
    places["category"].value_counts()
    return (places,)


@app.cell
def _(facilities):
    # One pass over Overture buildings, keeping footprints whose south-west bbox corner falls in a 0.002° cell
    # (about 200 m) from 600 m south-west to 400 m north-east of a facility: enough for any building that contains
    # the point or lies within 50 m of it. Reading the bbox column for the whole US takes about 20 minutes.
    _located = facilities.dropna(subset=["lon"])
    _path = DATA / f"overture-buildings-{len(_located)}.parquet"
    if not _path.exists():
        _con = duckdb.connect()
        _con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        _con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
        _con.sql("SET threads = 8")
        _con.sql("SET memory_limit = '4GB'")
        _con.sql("SET preserve_insertion_order = false")
        _con.register("pts", _located[["facility_id", "lon", "lat"]])
        _con.sql("""
            CREATE TABLE cells AS SELECT DISTINCT CAST(floor(lon / 0.002) AS INT) + dx AS cx,
                                                  CAST(floor(lat / 0.002) AS INT) + dy AS cy
            FROM pts, range(-3, 2) a(dx), range(-3, 2) b(dy)""")
        _parts = []
        for _i, (_a, _b, _c, _d) in enumerate(US_BOXES):
            _part = DATA / f"buildings-box{_i}.parquet"
            _con.sql(f"""
                COPY (
                    SELECT b.id AS building_id, b.sources[1].dataset AS building_source,
                           ST_AsWKB(b.geometry) AS wkb
                    FROM read_parquet('{OVERTURE}/theme=buildings/type=building/*') b
                    JOIN cells c ON c.cx = CAST(floor(b.bbox.xmin / 0.002) AS INT)
                                AND c.cy = CAST(floor(b.bbox.ymin / 0.002) AS INT)
                    WHERE b.bbox.xmin > {_a} AND b.bbox.xmax < {_c} AND b.bbox.ymin > {_b} AND b.bbox.ymax < {_d}
                ) TO '{_part}' (FORMAT parquet)""")
            _parts.append(pd.read_parquet(_part))
            print(f"buildings box {_i + 1} of {len(US_BOXES)}: {time.perf_counter() - RUN_STARTED:.0f} s", flush=True)
        pd.concat(_parts, ignore_index=True).to_parquet(_path)
    _b = pd.read_parquet(_path)
    buildings = gpd.GeoDataFrame(
        _b[["building_id", "building_source"]], geometry=gpd.GeoSeries.from_wkb(_b["wkb"]), crs=4326
    ).to_crs(METRIC)
    print(f"{len(buildings)} Overture buildings near the facilities")
    return (buildings,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Matching each facility to an outline

    For each located facility: the OSM `amenity=prison` polygon that contains the point or is nearest within
    250 m; failing that, the Overture building that contains the point or is nearest within 50 m. We also note
    any Overture `jail_or_prison` place within 250 m, as a second open source saying a facility is there.
    """)
    return


@app.cell
def _(buildings, facilities, osm, places):
    _pts = gpd.GeoDataFrame(
        facilities.dropna(subset=["lon"]),
        geometry=gpd.points_from_xy(facilities.dropna(subset=["lon"])["lon"], facilities.dropna(subset=["lon"])["lat"]),
        crs=4326,
    ).to_crs(METRIC)
    _osm_poly = osm[osm["polygon"]].reset_index(drop=True)
    _o = gpd.sjoin_nearest(_pts[["facility_id", "geometry"]], _osm_poly, max_distance=250, distance_col="osm_m")
    _o = _o.sort_values("osm_m").drop_duplicates("facility_id")
    _b = gpd.sjoin_nearest(_pts[["facility_id", "geometry"]], buildings, max_distance=50, distance_col="building_m")
    _b = _b.sort_values("building_m").drop_duplicates("facility_id")
    _p = gpd.sjoin_nearest(_pts[["facility_id", "geometry"]], places, max_distance=250, distance_col="place_m")
    _p = _p.sort_values("place_m").drop_duplicates("facility_id")
    matched = facilities.merge(
        _o[["facility_id", "osm_id", "osm_name", "osm_m", "index_right"]].rename(columns={"index_right": "osm_row"}),
        on="facility_id",
        how="left",
    )
    matched = matched.merge(
        _b[["facility_id", "building_id", "building_source", "building_m", "index_right"]].rename(
            columns={"index_right": "building_row"}
        ),
        on="facility_id",
        how="left",
    )
    matched = matched.merge(_p[["facility_id", "place_id", "place_name", "place_m"]], on="facility_id", how="left")
    matched["outline"] = "none"
    matched.loc[matched["building_id"].notna(), "outline"] = "Overture building"
    matched.loc[matched["osm_id"].notna(), "outline"] = "OSM prison polygon"
    matched.loc[matched["lon"].isna(), "outline"] = "not located"
    _geoms = []
    for _row in matched.itertuples():
        if _row.outline == "OSM prison polygon":
            _geoms.append(_osm_poly.geometry.iloc[int(_row.osm_row)])
        elif _row.outline == "Overture building":
            _geoms.append(buildings.geometry.iloc[int(_row.building_row)])
        else:
            _geoms.append(None)
    matched = gpd.GeoDataFrame(matched.drop(columns=["osm_row", "building_row"]), geometry=_geoms, crs=METRIC)
    _group = matched["group"]
    outline_summary = pd.crosstab(_group, matched["outline"], margins=True, margins_name="total")
    outline_share = pd.crosstab(_group, matched["outline"], normalize="index").round(3)
    outline_summary.to_csv(OUT / "outline_summary.csv")
    outline_share.to_csv(OUT / "outline_share.csv")
    print(
        "Overture place within 250 m:",
        matched.groupby(_group)["place_id"].apply(lambda s: round(s.notna().mean(), 3)).to_dict(),
    )
    mo.vstack([outline_summary, outline_share])
    return (matched,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## How much of the old layer does this rebuild?

    Three comparisons with the last public HIFLD copy:

    1. **Coverage**: of HIFLD's open federal and state records, how many have a rebuilt facility within 1 km?
    2. **Outline agreement**: where a rebuilt outline and a HIFLD polygon describe the same facility, how much do
       they overlap (intersection over union)?
    3. **What the open maps alone cover**, by HIFLD type, including county and local jails, which no BOP or
       state DOC list gives us: is there an OSM prison polygon on the HIFLD polygon, or an Overture
       `jail_or_prison` place within 250 m of it?
    """)
    return


@app.cell
def _(hifld, matched, osm, places):
    _open = hifld[hifld["STATUS"].eq("OPEN")].reset_index(drop=True)
    _pts = matched[matched["lon"].notna()].copy()
    _pts = gpd.GeoDataFrame(_pts, geometry=gpd.points_from_xy(_pts["lon"], _pts["lat"]), crs=4326).to_crs(METRIC)
    _near = gpd.sjoin_nearest(_open[["geometry"]], _pts[["facility_id", "geometry"]], max_distance=1000)
    _open["rebuilt"] = _open.index.isin(_near.index)
    _hit = gpd.sjoin(_open[["geometry"]], osm[osm["polygon"]][["geometry"]], predicate="intersects")
    _open["osm_polygon"] = _open.index.isin(_hit.index)
    _pl = gpd.sjoin_nearest(_open[["geometry"]], places[["geometry"]], max_distance=250)
    _open["overture_place"] = _open.index.isin(_pl.index)
    _open["either_open_map"] = _open["osm_polygon"] | _open["overture_place"]
    coverage = _open.groupby("TYPE").agg(
        hifld_open=("NAME", "size"),
        rebuilt_within_1km=("rebuilt", "sum"),
        osm_polygon=("osm_polygon", "sum"),
        overture_place=("overture_place", "sum"),
        either_open_map=("either_open_map", "sum"),
    )
    coverage.loc["total"] = coverage.sum()
    for _c in ["rebuilt_within_1km", "osm_polygon", "overture_place", "either_open_map"]:
        coverage[f"{_c}_share"] = (coverage[_c] / coverage["hifld_open"]).round(3)
    coverage.to_csv(OUT / "hifld_coverage.csv")
    # The other direction: how many rebuilt facilities land within 1 km of any HIFLD record (open or not)?
    _back = gpd.sjoin_nearest(
        _pts[["facility_id", "source", "geometry"]], hifld[["TYPE", "geometry"]], max_distance=1000
    )
    _pts["near_hifld"] = _pts["facility_id"].isin(_back["facility_id"])
    _agg = {"located": "size", "within_1km_of_a_hifld_record": "sum"}
    _all = _pts.groupby("group")["near_hifld"].agg(**_agg)
    _all.index = pd.MultiIndex.from_product([_all.index, ["all"]], names=["group", "location"])
    on_hifld = pd.concat([_all, _pts.groupby(["group", "location"])["near_hifld"].agg(**_agg)]).sort_index()
    on_hifld["share"] = (on_hifld["within_1km_of_a_hifld_record"] / on_hifld["located"]).round(3)
    on_hifld.to_csv(OUT / "rebuilt_on_hifld.csv")
    print(on_hifld)

    # Outline agreement: each rebuilt outline against the HIFLD polygon it overlaps most.
    _outl = matched[matched.geometry.notna()].copy()
    _pairs = gpd.sjoin(
        _outl[["facility_id", "outline", "geometry"]], hifld[["geometry"]].reset_index(), predicate="intersects"
    )
    _pairs["hifld_geom"] = hifld.geometry.loc[_pairs["index"]].to_numpy()
    _pairs["iou"] = [
        a.intersection(b).area / a.union(b).area for a, b in zip(_pairs.geometry, _pairs["hifld_geom"], strict=True)
    ]
    _best = _pairs.sort_values("iou", ascending=False).drop_duplicates("facility_id")
    outline_agreement = _best.groupby("outline")["iou"].describe()[["count", "25%", "50%", "75%"]].round(2)
    outline_agreement["share_iou_over_0.5"] = _best.groupby("outline")["iou"].apply(
        lambda s: round((s > 0.5).mean(), 2)
    )
    outline_agreement.to_csv(OUT / "outline_agreement.csv")
    mo.vstack([coverage, on_hifld, outline_agreement])
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The state jail lists against HIFLD's county and local jails

    For each state with a jail list: how many jails it gives, how many we could locate and outline (same rules as
    above), and what share of HIFLD's open COUNTY and LOCAL records have one of these jails within 1 km.
    """)
    return


@app.cell
def _(hifld, matched):
    _jails = matched[matched["group"].eq("local jail")]
    _pts = _jails[_jails["lon"].notna()]
    _pts = gpd.GeoDataFrame(_pts, geometry=gpd.points_from_xy(_pts["lon"], _pts["lat"]), crs=4326).to_crs(METRIC)
    _local = hifld[hifld["STATUS"].eq("OPEN") & hifld["TYPE"].isin(["COUNTY", "LOCAL"])].reset_index(drop=True)
    _near = gpd.sjoin_nearest(_local[["geometry"]], _pts[["geometry"]], max_distance=1000)
    _local["matched"] = _local.index.isin(_near.index)
    jail_coverage = pd.crosstab(_jails["state"], _jails["outline"]).reindex(
        columns=["OSM prison polygon", "Overture building", "none", "not located"], fill_value=0
    )
    jail_coverage.insert(0, "jails_listed", _jails.groupby("state").size())
    for _type in ["COUNTY", "LOCAL"]:
        _t = _local[_local["TYPE"].eq(_type)].groupby("STATE")["matched"]
        jail_coverage[f"hifld_open_{_type.lower()}"] = _t.size().reindex(jail_coverage.index, fill_value=0)
        jail_coverage[f"{_type.lower()}_within_1km"] = _t.sum().reindex(jail_coverage.index, fill_value=0)
    jail_coverage.loc["states with a list"] = jail_coverage.sum()
    _all = _local.groupby("TYPE")["matched"]
    jail_coverage.loc["all states"] = 0
    for _type in ["COUNTY", "LOCAL"]:
        jail_coverage.loc["all states", f"hifld_open_{_type.lower()}"] = _all.size()[_type]
        jail_coverage.loc["all states", f"{_type.lower()}_within_1km"] = _all.sum()[_type]
    _hifld = jail_coverage["hifld_open_county"] + jail_coverage["hifld_open_local"]
    _hit = jail_coverage["county_within_1km"] + jail_coverage["local_within_1km"]
    jail_coverage["county_and_local_share"] = (_hit / _hifld.where(_hifld > 0)).round(3)
    jail_coverage["outlined_share"] = (
        (jail_coverage["OSM prison polygon"] + jail_coverage["Overture building"]) / jail_coverage["jails_listed"]
    ).round(3)
    jail_coverage.loc["all states", ["jails_listed", "outlined_share"]] = float("nan")
    jail_coverage.to_csv(OUT / "jail_coverage.csv")
    jail_coverage
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The output layer

    `output/prison_boundaries_rebuilt.parquet` (GeoParquet, not committed): one row per facility from BOP and the
    state lists, with its outline where we found one, or its point. Every row says where its attributes came from
    and where its geometry came from, with each licence. Rows whose geometry is from OSM or Overture buildings are
    ODbL; the rest carry the BOP or state terms. `output/facilities.csv` (committed) has the same facilities with
    no OSM-derived geometry.
    """)
    return


@app.cell
def _(matched):
    _out = matched.copy()
    _points = gpd.GeoSeries(gpd.points_from_xy(_out["lon"], _out["lat"]), crs=4326).to_crs(METRIC)
    _out["geometry_source"] = (
        _out["outline"]
        .map(
            {
                "OSM prison polygon": "OpenStreetMap amenity=prison",
                "Overture building": "Overture buildings 2026-10-21.0",
            }
        )
        .fillna(_out["location"])
    )
    _out["geometry_licence"] = (
        _out["outline"]
        .map({"OSM prison polygon": "ODbL 1.0", "Overture building": "ODbL 1.0"})
        .fillna(
            _out["location"]
            .map(
                {
                    "Census geocoder": "public domain (US Census geocoder)",
                    "Overture place name match": "CDLA-Permissive-2.0",
                }
            )
            .fillna(_out["licence"])
        )
    )
    _out = _out.set_geometry(_out.geometry.where(_out.geometry.notna(), _points)).rename(
        columns={"licence": "attributes_licence"}
    )
    _keep = [
        "facility_id",
        "source",
        "state",
        "name",
        "address",
        "city",
        "zip",
        "kind",
        "source_url",
        "attributes_licence",
        "location",
        "outline",
        "geometry_source",
        "geometry_licence",
        "osm_id",
        "building_id",
        "building_source",
        "place_id",
        "place_name",
    ]
    _out = _out[_out.geometry.notna() & ~_out.geometry.is_empty][_keep + ["geometry"]].to_crs(4326)
    _out.to_parquet(OUT / "prison_boundaries_rebuilt.parquet")
    _cols = ["facility_id", "source", "state", "name", "address", "city", "zip", "kind", "source_url", "licence"]
    matched[_cols + ["location", "lon", "lat", "outline"]].to_csv(OUT / "facilities.csv", index=False)
    print(f"wrote {len(_out)} rows; geometry licence: {_out['geometry_licence'].value_counts().to_dict()}")
    # A map of the lower 48 for the README: each located facility, coloured by where its outline came from.
    _pts = matched[matched["lon"].between(-125, -66) & matched["lat"].between(24, 50)]
    _fig, _ax = plt.subplots(figsize=(11, 6.5))
    for _kind, _colour in [("OSM prison polygon", "#1b7837"), ("Overture building", "#e08214"), ("none", "#b2182b")]:
        for _jail, _marker in [(False, "o"), (True, "^")]:
            _k = _pts[_pts["outline"].eq(_kind) & _pts["group"].eq("local jail").eq(_jail)]
            _label = f"{_kind}, {'state-listed jail' if _jail else 'prison'} ({len(_k)})"
            _ax.scatter(_k["lon"], _k["lat"], s=7, c=_colour, marker=_marker, label=_label)
    _ax.set_aspect(1.25)
    _ax.set_axis_off()
    _ax.legend(loc="lower left", frameon=False, title="Outline found")
    _ax.set_title("BOP and state DOC facilities and state-listed jails, lower 48, by outline source")
    _fig.tight_layout()
    _fig.savefig(OUT / "facilities_map.png", dpi=110)
    plt.close(_fig)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Hand check against imagery

    A seeded sample of 40 located BOP and state facilities (20 with an OSM outline, 15 with only an Overture
    building, 5 with neither), drawn in #300, is shown on Esri World Imagery at two zooms, with the outline in
    yellow and the point in red. The images go to `data/chips/` (not committed: the imagery is Esri's). Each image
    was labelled by a reviewer who saw only the image and the facility's name: is the point on a correctional
    facility, and does the outline fit it? The labels are in `hand_check.csv`, keyed by state and name. Later runs
    find the same 40 facilities by state and name rather than drawing again, so the labels stay valid as states
    and jails are added. The added jails are not hand-checked.
    """)
    return


@app.function
def tile_mosaic(lon: float, lat: float, zoom: int) -> tuple[Image.Image, list[float]]:
    """A 3x3 block of Esri World Imagery tiles around a point, and its Web Mercator extent."""
    n = 2**zoom
    cx = int((lon + 180) / 360 * n)
    cy = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    image = Image.new("RGB", (768, 768))
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            tile = Image.open(io.BytesIO(get(TILES.format(z=zoom, x=cx + dx, y=cy + dy)))).convert("RGB")
            image.paste(tile, ((dx + 1) * 256, (dy + 1) * 256))
    half, span = 20037508.342789244, 2 * 20037508.342789244 / n
    left, top = -half + (cx - 1) * span, half - (cy - 1) * span
    return image, [left, left + 3 * span, top - 3 * span, top]


@app.cell
def _(matched):
    _labelled = pd.read_csv(HERE / "hand_check.csv", dtype=str)[["state", "name"]]
    _located = matched[matched["lon"].notna() & matched["group"].ne("local jail")]
    sample = _located.merge(_labelled, on=["state", "name"]).drop_duplicates(["state", "name"])
    assert len(sample) == len(_labelled), f"found {len(sample)} of the {len(_labelled)} hand-checked facilities"
    sample[["facility_id", "source", "state", "name", "outline"]].to_csv(OUT / "hand_check_sample.csv", index=False)
    _chips = DATA / "chips"
    _chips.mkdir(exist_ok=True)
    for _row in sample.to_crs(3857).itertuples():
        _path = _chips / f"{_row.facility_id}.jpg"
        if _path.exists() or os.environ.get("PRISONS_SKIP_CHIPS"):
            continue
        _xy = gpd.GeoSeries(gpd.points_from_xy([_row.lon], [_row.lat]), crs=4326).to_crs(3857).iloc[0]
        _fig, _axes = plt.subplots(1, 2, figsize=(14, 7))
        for _ax, _zoom in zip(_axes, [15, 17], strict=True):
            _img, _ext = tile_mosaic(_row.lon, _row.lat, _zoom)
            _ax.imshow(_img, extent=_ext)
            if _row.geometry is not None:
                gpd.GeoSeries([_row.geometry], crs=3857).plot(ax=_ax, facecolor="none", edgecolor="yellow", linewidth=2)
            _ax.scatter([_xy.x], [_xy.y], s=200, facecolors="none", edgecolors="red", linewidths=2)
            _ax.set_xlim(_ext[0], _ext[1])
            _ax.set_ylim(_ext[2], _ext[3])
            _ax.set_axis_off()
        _fig.suptitle(f"{_row.facility_id}: {_row.name} ({_row.state}); yellow = outline, red = point")
        _fig.tight_layout()
        _fig.savefig(_path, dpi=60)
        plt.close(_fig)
    return (sample,)


@app.cell
def _(sample):
    _labels_path = HERE / "hand_check.csv"
    if not _labels_path.exists():
        print("hand_check.csv not written yet: label the chips in data/chips/ first")
        hand_check = None
    else:
        _labels = pd.read_csv(_labels_path, dtype=str)
        _h = sample[["facility_id", "state", "name", "outline"]].merge(
            _labels[["state", "name", "point", "outline_fit"]], on=["state", "name"], how="left"
        )
        assert _h["point"].notna().all(), "hand_check.csv is missing facilities from the sample"
        hand_check = pd.DataFrame(
            {
                "facilities checked": [len(_h)],
                "point on a correctional facility": [int(_h["point"].eq("yes").sum())],
                "outlines checked": [int(_h["outline"].ne("none").sum())],
                "outline fits the facility": [int(_h["outline_fit"].eq("fits").sum())],
                "outline covers part of it": [int(_h["outline_fit"].eq("partial").sum())],
                "outline is something else": [int(_h["outline_fit"].eq("wrong").sum())],
            }
        ).T.rename(columns={0: "count"})
        _by = _h[_h["outline"].ne("none")].groupby("outline")["outline_fit"].value_counts().unstack(fill_value=0)
        hand_check.to_csv(OUT / "hand_check_summary.csv")
        _by.to_csv(OUT / "hand_check_by_outline.csv")
        print(_by)
    hand_check
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What didn't work

    - **Ten states have no list a script can read** (`fetch = none` or a low yield above): NY, RI and SD block
      plain HTTP with bot protection; HI and DC describe their few facilities in prose; NH's only machine-readable
      layer is about 15 years old; AK's addresses sit in a two-column PDF; CO gives no ZIP; KS and WY give PO boxes.
      Sub-issue #308 takes these on, with Playwright for the blocked sites.
    - **The generic scraper is noisy at the edges.** A few rows are head offices rather than prisons; Mississippi's
      page also lists county-run regional prisons, Florida's adds work camps and release centres, and the state
      GIS layers (AZ 2020, IA 2015, KY 2018, IL) lag their DOC's own list. We keep what each source says and let
      the HIFLD comparison and the hand check show the cost.
    - **The Census geocoder can't place rural prison addresses** (highways, rural routes); the Overture name match
      recovers some, and the rest stay unlocated.
    - **A building footprint is not a prison boundary.** Where OSM has no `amenity=prison` polygon, the nearest
      Overture building is usually one cell block or the administration building, so it overlaps HIFLD's fence-line
      polygon far less than an OSM outline does.
    - **Local jails have no national public list with locations.** BJS's Census of Jails facility file is
      restricted, the NIC National Jails Compendium isn't published, and the Census Bureau API (group-quarters
      counts by block) now needs a key. The open maps above are the only national source we could measure.
    - **Overpass** reset our connections, so OSM comes from QLever.
    """)
    return


@app.cell
def _():
    print(f"run time: {time.perf_counter() - RUN_STARTED:.0f} s; cost: $0 (no paid services)")
    return


if __name__ == "__main__":
    app.run()
