import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import io
    import json
    import os
    import re
    import time
    from datetime import UTC, datetime
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx
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
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Can we map and record supply chain risk in NYC using FEMA's method?

    **The question.** FEMA's [Supply Chain Resilience Guide](https://www.fema.gov/sites/default/files/2020-07/supply-chain-resilience-guide.pdf)
    (April 2019) tells emergency managers to map a supply chain's nodes, the infrastructure they depend on, and the
    hazards on each. Can that be done row by row from public data for one lifeline, electric power, in Brooklyn, so
    that anyone can add a parcel and get a ranked list of the upstream facilities it depends on and the risks on
    each, with a source for every link?

    We expected yes, with gaps where public data doesn't show how the grid is connected. The notebook:

    1. turns the guide's steps into four tables (nodes, links, hazards, sources);
    2. builds the power dependency chain for Brooklyn: parcel, Con Edison network, area substation, transmission
       substation, plants;
    3. attaches FEMA's flood zones and National Risk Index (NRI) ratings to every node;
    4. reads a parcel file (`PARCELS`, by default [`sample_parcels.csv`](sample_parcels.csv)) and ranks each
       parcel's upstream risks.
    """)
    return


@app.cell
def _():
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

    def cached(name: str, load) -> gpd.GeoDataFrame:
        """Run load() once and keep the result in DATA/name (GeoParquet) for later runs."""
        path = DATA / name
        if not path.exists():
            load().to_parquet(path)
        return gpd.read_parquet(path)

    return arcgis, cached, get


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. The guide's steps as a schema

    The guide has five phases. Only the first two use data: *Research and Mapping* and *Analysis*. Phases 3 to 5
    (outreach, action, assess and refine) are meetings and exercises with the companies that own the nodes, so
    they're out of scope here, except that Phase 5's "validate and refine data" is what the source check in
    section 2 does. Each Phase 1 step becomes a table or a column:
    """)
    return


@app.cell
def _():
    fema_steps = pd.DataFrame(
        [
            (
                "1 Research and Mapping",
                "Identify the primary crucial suppliers for the local community.",
                "nodes, kind = plant (supply nodes)",
            ),
            (
                "1 Research and Mapping",
                "Identify supply chain nodes within the scope of the review.",
                "nodes inside the Brooklyn boundary; transmission substations are the points of concentration",
            ),
            (
                "1 Research and Mapping",
                "Identify ultimate destinations of goods.",
                "the parcels a user adds (demand nodes), and all 277k Brooklyn tax lots for coverage",
            ),
            (
                "1 Research and Mapping",
                "Identify infrastructure systems supporting supply chain operations.",
                "links table: who supplies whom, each with its public source; network service areas",
            ),
            (
                "1 Research and Mapping",
                "Overlay key threats and hazards, and other stressors and disruptors, against the identified "
                "primary crucial suppliers.",
                "hazards on each node (flood zone, NRI) and documented stressors (capacity, deactivation)",
            ),
            (
                "2 Analysis",
                "identify the seven or fewer sources that are likely to generate 70 to 80 percent of total flows",
                "concentration: how many substations serve 80% of Brooklyn's lots",
            ),
            (
                "2 Analysis",
                "Distinguish between the nodes that comprise a supply chain (such as manufacturing facilities and "
                "hospitals) and the infrastructure that those nodes depend on",
                "nodes.kind: parcel versus network, substation, plant",
            ),
        ],
        columns=["phase", "the guide says", "becomes"],
    )
    fema_steps
    return (fema_steps,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. Sources, and checking that each one says what we use it for

    No single public dataset says which substation serves which part of Brooklyn. The links come from utility and
    grid-operator documents instead. Each source below has the exact passage we rely on. The notebook downloads
    every source and checks that the passage is in it (ignoring case, spaces and punctuation), so a reader can see
    which links were verified on this run. For the NYISO queue spreadsheet a passage `a ... b` means both parts sit
    in the same row. fema.gov blocks automated downloads from some networks; a source that can't be downloaded
    comes back as `unreachable`, not as verified.
    """)
    return


@app.cell
def _():
    _psc = "https://documents.dps.ny.gov/public/Common/ViewDoc.aspx?DocRefId="
    _nyiso = "https://www.nyiso.com/documents/20142"
    documents = {
        "fema-guide": (
            "FEMA, Supply Chain Resilience Guide, April 2019",
            "https://www.fema.gov/sites/default/files/2020-07/supply-chain-resilience-guide.pdf",
        ),
        "psc-network-ranking-2012": (
            "Con Edison, 2012 Network Ranking, Exhibit IIP-8, filed with the NY PSC",
            f"{_psc}%7BF62626F2-2E5B-47D3-88FB-EC5AC20C085D%7D",
        ),
        "bqdm-petition-2014": (
            "Con Edison, Brooklyn/Queens Demand Management petition, NY PSC Case 14-E-0302, July 2014",
            f"{_psc}%7BFA6E8548-E790-4E6A-8BF2-61DDF62EAB4E%7D",
        ),
        "bceh-dps12-2023": (
            "Con Edison, response DPS-12 on the Brooklyn Clean Energy Hub, NY PSC Case 20-E-0197, February 2023",
            f"{_psc}%7BC0E87187-0000-CF35-9148-3E240230B194%7D",
        ),
        "nyiso-queue": (
            "NYISO Interconnection Queue (current file; withdrawn and in-service sheets)",
            f"{_nyiso}/1407078/NYISO-Interconnection-Queue.xlsx",
        ),
        "nyiso-bps": (
            "NYISO, The New York State Bulk Power Transmission Facilities",
            f"{_nyiso}/1407249/existing_bps_transmission_facilities.pdf/aecc0414-397b-4095-9d21-634eb9674639",
        ),
        "coned-ltp-2025": (
            "Con Edison, Local Transmission Plan update to NYISO, 21 January 2025",
            f"{_nyiso}/49295323/CECONY's_LTP_Update_1_21_2025.pdf/abf6cfb4-10e6-eee4-3988-0a434f5a1dcb",
        ),
        "nyiso-gold-book-2026": (
            "NYISO, 2026 Load & Capacity Data (Gold Book)",
            f"{_nyiso}/2226333/2026-Gold-Book-Public.pdf",
        ),
        "ju-reliability-2024": (
            "Joint Utilities of NY, 2024 Annual Report on Electric Service and Power Quality (Con Edison section)",
            "https://jointutilitiesofny.org/sites/default/files/2024%20Annual%20Report%20on%20Electric%20Service"
            "%20and%20Power%20Quality.pdf",
        ),
    }
    return (documents,)


@app.cell
def _(documents, get):
    def normalise(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", text.lower())

    def document_text(source: str) -> list[str] | None:
        """The document's text, normalised: one entry per spreadsheet row, or one for a whole PDF or page.
        None if it can't be downloaded from here."""
        path = DATA / f"doc-{source}"
        if not path.exists():
            try:
                path.write_bytes(get(documents[source][1], tries=2).content)
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

    document_texts = {source: document_text(source) for source in documents}
    return document_texts, normalise


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. The links, row by row

    Each row is one dependency: `supplier` feeds `consumer`. `status` is `documented` when a public document names
    the link, and `inferred` when we had to guess it from the map (the nearest transmission substation). Every
    documented row carries its source and passage.

    - **Network to area substation.** Con Edison's 2012 network ranking, filed with the PSC, lists the area
      substation for every network. It's the only public table of these pairs we found, and it is 14 years old.
    - **Area substation to transmission substation.** Named in the BQDM petition (Farragut to Brownsville), the
      NYISO queue (the Greenwood–Bensonhurst 138 kV feeders) and the Gold Book (Gowanus to Greenwood). Nothing
      public names the supply of Plymouth Street or Water Street; both sit within 200 m of Farragut, so we infer it.
    - **Transmission ties and plants.** NYISO's bulk-system list gives the 345 kV circuits; the queue's in-service
      sheet gives the points where some plants connect; Con Edison's transmission plan says which plants support
      the Greenwood 138 kV load area. We stop one hop out on the 345 kV system: past that it's a meshed grid, and
      every plant in the city is upstream of everything.
    """)
    return


@app.cell
def _():
    _psc = "psc-network-ranking-2012"
    _rows = [
        # Network to area substation, Brooklyn rows of the 2012 ranking (rank, region, network ID, network, substation).
        ("Plymouth St.", "Borough Hall", _psc, "4 B 1B Borough Hall Plymouth St."),
        ("Greenwood", "Park Slope", _psc, "5 B 2B Park Slope Greeenwood"),
        ("Brownsville No. 1", "Crown Heights", _psc, "12 B 3B Crown Heights Brownsville No. 1"),
        ("Bensonhurst No. 2", "Flatbush", _psc, "9 B 4B Flatbush Bensonhurst No.2"),
        ("Brownsville No. 1", "Ridgewood", _psc, "1 B 5B Ridgewood Brownsville No. 1"),
        ("Water St.", "Williamsburg", _psc, "5 B 6B Williamsburg Water St."),
        ("Bensonhurst No. 1", "Ocean Parkway", _psc, "14 B 7B Ocean Parkway Bensonhurst No.1"),
        ("Greenwood", "Bay Ridge", _psc, "23 B 8B Bay Ridge Greeenwood"),
        ("Brownsville No. 2", "Richmond Hill", _psc, "10 Q 9B Richmond Hill Brownsville No. 2 (Bk)"),
        ("Bensonhurst No. 1", "Sheepshead Bay", _psc, "3 B 10B Sheepshead Bay Bensonhurst No.1"),
        ("Bensonhurst No. 2", "Brighton Beach", _psc, "7 B 11B Brighton Beach Bensonhurst No.2"),
        ("Water St.", "Prospect Park", _psc, "40 B 12B Prospect Park Water St."),
        # A Queens network whose load area takes in 4,788 Brooklyn lots along the border.
        ("Glendale", "Maspeth", _psc, "24 Q 6Q Maspeth Glendale"),
        # Area substation to transmission substation.
        *(
            (
                "Farragut",
                f"Brownsville No. {n}",
                "bqdm-petition-2014",
                "The Brownsville substations are supplied by a set of five 138,000 volt",
            )
            for n in (1, 2)
        ),
        *(
            (
                "Greenwood",
                f"Bensonhurst No. {n}",
                "nyiso-queue",
                "Greenwood-Bensonhurst and Farragut-Brownsville 138 kV feeders",
            )
            for n in (1, 2)
        ),
        ("Gowanus", "Greenwood", "nyiso-gold-book-2026", "Gowanus Greenwood Xfmr/PAR/Feeder"),
        ("Farragut", "Plymouth St.", None, "inferred: nearest 345/138 kV substation, about 50 m away"),
        ("Farragut", "Water St.", None, "inferred: nearest 345/138 kV substation, about 200 m away"),
        # 345 kV ties, one hop out from Farragut and Gowanus.
        ("Gowanus", "Farragut", "nyiso-bps", "41 FARRAGUT 345 GOWANUS N41 345"),
        ("Farragut", "Gowanus", "nyiso-bps", "42 FARRAGUT 345 GOWANUS S42 345"),
        ("Rainey", "Farragut", "nyiso-bps", "61 RAINEY 345 FARRAGUT 345"),
        ("E. 13th St.", "Farragut", "nyiso-bps", "45 E.13TH ST A 345 FARRAGUT 345"),
        ("Hudson (NJ)", "Farragut", "nyiso-bps", "B3402 HUDSON A 345 FARRAGUT 1 345"),
        ("Goethals", "Gowanus", "nyiso-bps", "25 GOWANUS N. 345 GOETHALS N.1 345"),
        # Plants.
        ("NYPA 23rd St and 3rd Ave", "Gowanus", "nyiso-queue", "23rd St and 3rd Ave ... Gowanus Substation"),
        ("Bayonne Energy Center", "Gowanus", "nyiso-queue", "Bayonne Energy Center ... Gowanus Substation 345kV"),
        (
            "NYPA N First St and Grand Ave",
            "Greenwood",
            "nyiso-queue",
            "N First St and Grand Ave ... Vernon-Greenwood line",
        ),
        *(
            (
                plant,
                "Greenwood",
                "coned-ltp-2025",
                "The Greenwood 138 kV TLA is supplied by transmission feeders from other parts of the Con Edison "
                "system, the NYPA gas turbines, and the Gowanus and Narrows Barges",
            )
            for plant in ("Gowanus barges", "Narrows barges")
        ),
        ("Brooklyn Navy Yard Cogen", "Farragut", None, "inferred: nearest 345/138 kV substation, about 700 m away"),
    ]
    documented_links = pd.DataFrame(_rows, columns=["supplier", "consumer", "source", "passage"])
    documented_links["status"] = documented_links["source"].map(
        lambda s: "documented" if isinstance(s, str) else "inferred"
    )
    documented_links
    return (documented_links,)


@app.cell
def _():
    # Documented stressors (FEMA: "other stressors and disruptors"), each with its source and passage.
    _capacity = (
        "bceh-dps12-2023",
        "existing Water Street, Plymouth Street, Greenwood, and Bensonhurst No. 2 distribution area substations are "
        "projected to no longer be able to reliably serve customer demand",
    )
    stressors = pd.DataFrame(
        [
            ("Water St.", "projected over capacity (2023-2042 forecast)", *_capacity),
            ("Plymouth St.", "projected over capacity (2023-2042 forecast)", *_capacity),
            ("Greenwood", "projected over capacity (2023-2042 forecast)", *_capacity),
            ("Bensonhurst No. 2", "projected over capacity (2023-2042 forecast)", *_capacity),
            ("Greenwood", "138 kV load area deficient from 2026", "coned-ltp-2025", "A new local reliability need"),
            *(
                (
                    f"Brownsville No. {n}",
                    "at capacity limit by summer 2028",
                    "bceh-dps12-2023",
                    "demonstrate the need for the new Gateway Park No. 1 facility",
                )
                for n in (1, 2)
            ),
            (
                "Gowanus barges",
                "deactivation notice for 14 July 2026",
                "nyiso-gold-book-2026",
                "Gowanus 2-1 through 2-8",
            ),
            (
                "Narrows barges",
                "deactivation notice for 14 July 2026",
                "nyiso-gold-book-2026",
                "Narrows 1-1 through 2-8",
            ),
        ],
        columns=["node", "stressor", "source", "passage"],
    )
    return (stressors,)


@app.cell
def _(document_texts, documented_links, documents, fema_steps, normalise, stressors):
    def check(source: str | float, passage: str) -> str:
        if not isinstance(source, str):
            return "no source"
        lines = document_texts[source]
        if lines is None:
            return "unreachable"
        # A passage written "a ... b" needs every part in the same spreadsheet row (or the same document).
        parts = [normalise(part) for part in passage.split(" ... ")]
        return "verified" if any(all(part in line for part in parts) for line in lines) else "passage not found"

    _checks = pd.concat(
        [
            fema_steps.assign(source="fema-guide", passage=fema_steps["the guide says"], what="FEMA step"),
            documented_links.assign(what=documented_links["supplier"] + " -> " + documented_links["consumer"]),
            stressors.assign(what=stressors["node"] + ": " + stressors["stressor"]),
        ]
    )[["what", "source", "passage"]]
    source_check = _checks.assign(
        result=[check(s, p) for s, p in zip(_checks["source"], _checks["passage"], strict=True)]
    )
    source_check = source_check.assign(
        document=source_check["source"].map(lambda s: documents[s][0] if isinstance(s, str) else ""),
        url=source_check["source"].map(lambda s: documents[s][1] if isinstance(s, str) else ""),
    )
    source_check.to_csv(OUT / "source_check.csv", index=False)
    mo.vstack([mo.md("**Passages checked on this run:**"), source_check.groupby(["source", "result"]).size()])
    return (source_check,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. Where each node is

    The documents name facilities; the map needs their footprints. OpenStreetMap has Con Edison's substations and
    the city's plants, with names and voltages, and Overture publishes it as versioned GeoParquet on S3. (Overpass
    failed on three servers in the `hifld-grid-gaps` spike, so we read Overture with DuckDB.) A hand-made
    crosswalk matches each document name to its OSM name. Brownsville No. 1 and No. 2 share one site, as do
    Bensonhurst No. 1 and No. 2.
    """)
    return


@app.cell
def _():
    overture_release = "2026-09-23.0"
    _path = DATA / f"overture-power-nyc-{overture_release}.parquet"
    if not _path.exists():
        _con = duckdb.connect()
        _con.sql("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
        # An empty key makes DuckDB read the public bucket anonymously instead of using any AWS credentials around.
        _con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
        _con.sql(f"""
            COPY (
                SELECT id, class, names.primary AS name, source_tags['operator'] AS operator,
                       source_tags['voltage'] AS voltage, source_tags['substation'] AS substation_type,
                       ST_AsWKB(geometry) AS geometry
                FROM read_parquet('s3://overturemaps-us-west-2/release/{overture_release}/theme=base/type=infrastructure/*')
                WHERE bbox.xmin > -74.3 AND bbox.xmax < -73.6 AND bbox.ymin > 40.45 AND bbox.ymax < 40.95
                  AND subtype = 'power' AND class IN ('substation', 'plant')
            ) TO '{_path}' (FORMAT parquet)
        """)
    _osm = pd.read_parquet(_path)
    osm_power = gpd.GeoDataFrame(_osm, geometry=shapely.from_wkb(_osm["geometry"]), crs=4326)
    return osm_power, overture_release


@app.cell
def _(osm_power):
    # Document name -> (kind, OSM name). None means OSM has no feature we could match.
    crosswalk = {
        "Brownsville No. 1": ("area substation", "Brownsville Substation"),
        "Brownsville No. 2": ("area substation", "Brownsville Substation"),
        "Bensonhurst No. 1": ("area substation", "Bensonhurst Substation"),
        "Bensonhurst No. 2": ("area substation", "Bensonhurst Substation"),
        "Greenwood": ("area substation", "Greenwood Substation"),
        "Plymouth St.": ("area substation", "Plymouth Substation"),
        "Water St.": ("area substation", "Water Street Substation"),
        "Glendale": ("area substation", None),
        "Corona No. 2": ("area substation", "Corona Substation"),
        "Farragut": ("transmission substation", "Farragut Substation"),
        "Gowanus": ("transmission substation", "Gowanus Substation"),
        "Rainey": ("transmission substation", "Rainey Substation"),
        "Goethals": ("transmission substation", "Goethals Substation"),
        "E. 13th St.": ("transmission substation", None),
        "Hudson (NJ)": ("transmission substation", None),
        "Gowanus barges": ("plant", "Gowanus Power Plant"),
        "Narrows barges": ("plant", "Narrows Gas Turbines Generating"),
        "NYPA 23rd St and 3rd Ave": ("plant", "Joseph J. Seymour Power Project"),
        "NYPA N First St and Grand Ave": ("plant", "North 1st power station"),
        "Bayonne Energy Center": ("plant", "Bayonne Energy Center"),
        "Brooklyn Navy Yard Cogen": ("plant", "Building 202"),
    }
    # Some sites are mapped as several polygons (Farragut has three); merge them into one footprint per name.
    _sites = osm_power[osm_power["name"].isin({osm for _, osm in crosswalk.values() if osm})]
    _sites = _sites[(_sites["class"] == "plant") | _sites["operator"].fillna("").str.contains("Consolidated Edison")]
    _footprints = _sites.dissolve(by="name")["geometry"]
    facility_nodes = gpd.GeoDataFrame(
        [
            {"node": name, "kind": kind, "osm_name": osm, "geometry": _footprints.get(osm) if osm else None}
            for name, (kind, osm) in crosswalk.items()
        ],
        crs=4326,
    )
    facility_nodes[["node", "kind", "osm_name"]].assign(on_map=facility_nodes.geometry.notna())
    return (facility_nodes,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. Which network or feeder serves each lot

    Con Edison's [hosting capacity map](https://www.coned.com/en/business-partners/hosting-capacity) (the utility's
    entry in DOE's U.S. Atlas of Electric Distribution System Hosting Capacity Maps) publishes three layers we can
    use without a login:

    - each **network's load area**, a polygon named for the network, which together cover nearly all of Brooklyn;
    - the **network-supplied area**, the part actually fed by the underground network grid (unnamed polygons);
    - every overhead **feeder segment**, each tagged with its area substation.

    A lot in both a load area and a network-supplied area is served by that network. Any other lot is matched to
    the nearest feeder segment within 500 feet. A lot near no segment falls back to its load area's network, which
    we mark as inferred. We match all 276k Brooklyn tax lots (MapPLUTO points from NYC Open Data) to measure
    coverage, then the same rule serves the user's parcels.
    """)
    return


@app.cell
def _(arcgis, cached):
    _coned = "https://services.arcgis.com/ciPnsNFi1JLWVjva/arcgis/rest/services"
    networks = cached(
        "coned-networks.parquet",
        lambda: arcgis(f"{_coned}/CECONY_NetworkLCSD_Prod/FeatureServer/0", {"outFields": "NETWORK,BOROUGH"}),
    )
    network_areas = cached(
        "coned-network-supplied-areas.parquet",
        lambda: arcgis(f"{_coned}/CECONY_NwkSuppliedArea_Prod/FeatureServer/0", {"outFields": "OBJECTID"}),
    )
    _brooklyn_box = {
        "outFields": "FEEDER_ID,SUBSTATION",
        "geometry": "-74.05,40.56,-73.83,40.74",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
    }
    # Layer 0 holds three-phase overhead segments, layer 1 one- and two-phase ones.
    feeders = cached(
        "coned-overhead-segments-brooklyn.parquet",
        lambda: pd.concat(
            [arcgis(f"{_coned}/CECONY_NodalHCV_Prod/FeatureServer/{n}", _brooklyn_box, page=2000) for n in (0, 1)],
            ignore_index=True,
        ),
    )
    # The 2012 PSC table and the map spell names differently; these are the only differences.
    networks["network"] = networks["NETWORK"].str.replace(" - BK", "", regex=False)
    feeders["area_substation"] = (
        feeders["SUBSTATION"]
        .str.title()
        .str.replace(r"No\.(\d)", r"No. \1", regex=True)
        .replace({"Plymouth": "Plymouth St."})
    )
    return feeders, network_areas, networks


@app.cell
def _(cached, get):
    def pluto_brooklyn() -> gpd.GeoDataFrame:
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

    lots = cached("pluto-brooklyn-lots.parquet", pluto_brooklyn)
    return (lots,)


@app.cell
def _(feeders, network_areas, networks):
    def serve(points: gpd.GeoDataFrame) -> pd.DataFrame:
        """For each point: its network if it is inside a network-supplied area, else the area substation of the
        nearest overhead segment within 500 ft, else the load area it sits in (an inference), else nothing."""
        _pts = points.to_crs(NY_FEET)
        area = gpd.sjoin(_pts, networks.to_crs(NY_FEET)[["network", "geometry"]], predicate="within", how="left")
        area = area[~area.index.duplicated()]["network"]
        supplied = gpd.sjoin(_pts, network_areas.to_crs(NY_FEET)[["geometry"]], predicate="within", how="inner")
        on_network = _pts.index.isin(supplied.index) & area.notna()
        near = gpd.sjoin_nearest(
            _pts[~on_network], feeders.to_crs(NY_FEET)[["area_substation", "geometry"]], how="left", max_distance=500
        )
        near = near[~near.index.duplicated()]["area_substation"].reindex(points.index)
        served = pd.DataFrame(index=points.index)
        served["served_by"] = area.where(on_network).fillna(near).fillna(area)
        served["match"] = "not matched"
        served.loc[area.notna(), "match"] = "load area only (inferred)"
        served.loc[near.notna(), "match"] = "overhead feeder"
        served.loc[on_network, "match"] = "network boundary"
        return served

    return (serve,)


@app.cell
def _(lots, serve):
    lot_service = serve(lots)
    lot_match = lot_service["match"].value_counts()
    lot_match
    return lot_match, lot_service


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. The dependency graph

    The links become a directed graph, supplier to consumer, built with NetworkX. A parcel's upstream facilities are
    its ancestors in the graph. We also ask whether each upstream facility can be reached on documented links
    alone, so the reader can tell which parts of a parcel's chain rest on an inference.
    """)
    return


@app.cell
def _(documented_links, feeders, networks):
    graph = nx.DiGraph()
    for _row in documented_links.itertuples():
        graph.add_edge(_row.supplier, _row.consumer, status=_row.status, source=_row.source)
    _brooklyn_networks = set(networks.loc[networks["BOROUGH"] == "Brooklyn", "network"])
    _unlinked = sorted(_brooklyn_networks - set(graph.nodes))
    # Overhead feeders name their area substation directly; a substation that appears only here has no supplier.
    for _sub in sorted(set(feeders["area_substation"].dropna())):
        graph.add_node(_sub)
    documented_graph = graph.edge_subgraph(
        [(u, v) for u, v, d in graph.edges(data=True) if d["status"] == "documented"]
    )
    # The radial graph drops the 345 kV ties, leaving each lot's direct supply chain.
    radial_graph = graph.copy()
    radial_graph.remove_edges_from([(u, v) for u, v, d in graph.edges(data=True) if d["source"] == "nyiso-bps"])
    mo.md(
        f"The graph has **{graph.number_of_nodes()} nodes and {graph.number_of_edges()} links**. "
        f"Brooklyn networks on Con Edison's map with no area substation in the 2012 table: {_unlinked or 'none'}."
    )
    return documented_graph, graph, radial_graph


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 7. Hazards on every node

    - **FEMA flood zone** (National Flood Hazard Layer, effective maps) anywhere on the node's footprint. We take the
      worst zone: `VE` (coastal high hazard), then `A`/`AE`/`AO` (1% annual chance), then the 0.2% annual chance
      shaded `X`, then unshaded `X`. NYC's effective maps date from 2007; FEMA's 2015 preliminary maps, which put more
      of the waterfront in the 1% zone, are not in NFHL's effective layer.
    - **National Risk Index** ratings for the census tract the node sits in: overall risk, coastal flooding,
      hurricane and heat wave (heat drives peak load, which is what the documented capacity limits are about).
    """)
    return


@app.cell
def _(arcgis, cached, get):
    _nri = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Census_Tracts/FeatureServer/0"
    _counties = "'36005','36047','36061','36081','36085','34017'"  # NYC's five counties and Hudson County, NJ
    nri_tracts = cached(
        "nri-tracts-nyc.parquet",
        lambda: arcgis(
            _nri,
            {
                "where": f"STCOFIPS IN ({_counties})",
                "outFields": "TRACTFIPS,RISK_SCORE,RISK_RATNG,CFLD_RISKR,HRCN_RISKR,HWAV_RISKR,NRI_VER",
            },
        ),
    )
    flood_rank = {"VE": 4, "V": 4, "AE": 3, "A": 3, "AO": 3, "AH": 3, "X 0.2%": 2, "X": 1, "none": 0}

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
        return max(zones, key=lambda z: flood_rank.get(z, 0))

    def hazards(points: gpd.GeoDataFrame, name: str) -> pd.DataFrame:
        """Flood zone and NRI ratings for each geometry; flood zones are cached in DATA/name."""
        path = DATA / name
        known = json.loads(path.read_text()) if path.exists() else {}
        for key, geometry in zip(points.index, points.geometry, strict=True):
            if str(key) not in known and geometry is not None:
                known[str(key)] = flood_zone(geometry)
                path.write_text(json.dumps(known, indent=1))  # saved as we go, so a rerun resumes here
        _located = points[points.geometry.notna()]
        _centres = gpd.GeoDataFrame(geometry=_located.geometry.representative_point(), index=_located.index, crs=4326)
        # Nearest tract within 1,000 ft, so piers and barges just off the tract shoreline still get a rating.
        tract = gpd.sjoin_nearest(_centres.to_crs(NY_FEET), nri_tracts.to_crs(NY_FEET), how="left", max_distance=1000)
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

    return flood_rank, hazards, nri_tracts


@app.cell
def _(facility_nodes, hazards, stressors):
    _facilities = facility_nodes.set_index("node")
    node_hazards = _facilities[["kind", "osm_name"]].join(hazards(_facilities, "nfhl-facilities.json"))
    node_hazards["stressors"] = stressors.groupby("node")["stressor"].agg("; ".join).reindex(node_hazards.index)
    node_hazards.reset_index().to_csv(OUT / "nodes.csv", index=False)
    node_hazards
    return (node_hazards,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 8. Concentration (FEMA Phase 2)

    The guide says to find "the seven or fewer sources that are likely to generate 70 to 80 percent of total
    flows". Counting tax lots (not load, which isn't public by lot) behind each facility. The 345 kV ties are left
    out here: Farragut and Gowanus back each other up, so with the ties every facility would sit behind nearly every
    lot.
    """)
    return


@app.cell
def _(facility_nodes, graph, lot_service, radial_graph):
    _kind = dict(zip(facility_nodes["node"], facility_nodes["kind"], strict=True))
    _served = lot_service.loc[lot_service["served_by"].notna(), "served_by"]
    _per_first = _served.value_counts()
    _counts: dict[str, int] = {}
    for _first, _n in _per_first.items():
        _upstream = nx.ancestors(radial_graph, _first) if _first in radial_graph else set()
        for _node in _upstream | {_first}:
            _counts[_node] = _counts.get(_node, 0) + int(_n)
    concentration = (
        pd.Series(_counts, name="lots").rename_axis("node").reset_index().sort_values("lots", ascending=False)
    )
    concentration["share_of_brooklyn_lots"] = (concentration["lots"] / len(lot_service)).round(3)
    # For the 80% test, count each lot once, under the area substation that serves it directly (Greenwood also
    # feeds Bensonhurst over 138 kV, so the totals above count Bensonhurst's lots twice).
    _direct = {
        f: f if _kind.get(f) == "area substation" else next(iter(graph.predecessors(f)), f) for f in _per_first.index
    }
    direct_lots = _served.map(_direct).value_counts()
    area_substations_for_80 = int((direct_lots.cumsum() / len(lot_service) < 0.8).sum() + 1)
    concentration.to_csv(OUT / "concentration.csv", index=False)
    mo.vstack(
        [
            mo.md(
                f"**{area_substations_for_80} area substations serve 80% of Brooklyn's {len(lot_service):,} lots.** "
                "Top facilities by lots behind them:"
            ),
            direct_lots.rename("lots served directly"),
            mo.md("Lots with each facility anywhere upstream (345 kV ties left out):"),
            concentration.head(12),
        ]
    )
    return area_substations_for_80, concentration, direct_lots


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 9. Coverage against Con Edison's own counts

    Con Edison's 2024 reliability report counts Brooklyn's distribution system. The 2012 table names seven
    Brooklyn area substations where the report counts six; the report may count the co-located Brownsville No. 1
    and No. 2, or Bensonhurst No. 1 and No. 2, as one. It counts 11 network or load areas where the map has 12
    networks in Brooklyn; Richmond Hill is counted under Queens in the report.
    """)
    return


@app.cell
def _(facility_nodes, networks, nri_tracts, osm_power):
    _brooklyn = nri_tracts[nri_tracts["TRACTFIPS"].str.startswith("36047")].union_all()
    _in_bk = osm_power[osm_power.geometry.representative_point().within(_brooklyn)]
    _coned = _in_bk[_in_bk["operator"].fillna("").str.contains("Consolidated Edison")]
    _volts = _coned["voltage"].fillna("")
    coverage = pd.DataFrame(
        [
            ("Area substations", 6, 7, int(_volts.str.startswith("138000;27000").sum())),
            ("Network or load areas", 11, 12, int((networks["BOROUGH"] == "Brooklyn").sum())),
            ("4 kV unit substations", 15, None, int(_volts.str.startswith("27000;4000").sum())),
        ],
        columns=["Brooklyn", "Con Edison 2024 report", "2012 PSC table", "on the public map (OSM or Con Ed)"],
    )
    _placed = facility_nodes.geometry.notna()
    coverage.to_csv(OUT / "coverage.csv", index=False)
    mo.vstack(
        [
            coverage,
            mo.md(
                f"Of the {len(facility_nodes)} facilities the documents name, **{int(_placed.sum())} are on the "
                f"map** and {int((~_placed).sum())} are not: "
                f"{', '.join(facility_nodes.loc[~_placed, 'node'])}."
            ),
        ]
    )
    return (coverage,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 10. Add your own parcel

    Set `PARCELS` to a CSV with columns `name` and either `bbl` (NYC's borough-block-lot number) or `lat` and `lon`,
    or to a GeoJSON file of points or polygons with a `name` property. Each parcel is placed (BBL looked up in
    PLUTO, otherwise its own coordinates), matched to a network or feeder, and its upstream facilities are listed with
    their hazards. The ranking puts the parcel's direct supply chain first and the 345 kV ties after it (the ties
    are meshed, so losing one is less likely to cut the parcel off). Within each group it puts the worst flood zone
    first, then NRI coastal flooding, then the NRI overall score, with documented stressors shown alongside.
    """)
    return


@app.cell
def _(lots):
    def read_parcels(path: Path) -> gpd.GeoDataFrame:
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

    parcels = read_parcels(PARCELS)
    parcels
    return (parcels,)


@app.cell
def _(documented_graph, flood_rank, graph, hazards, node_hazards, parcels, radial_graph, serve, stressors):
    _placed = parcels[parcels.geometry.notna()]
    _service = serve(_placed).reindex(parcels.index)
    _service["match"] = _service["match"].fillna("not placed (BBL not in PLUTO and no coordinates)")
    _parcel_hazards = hazards(parcels.set_index("name"), "nfhl-parcels.json")
    _sources = stressors.groupby("node")["source"].agg(lambda s: ", ".join(sorted(set(s))))
    _rows: list[dict] = []
    for _i, _parcel in parcels.iterrows():
        _first = _service.loc[_i, "served_by"]
        if not isinstance(_first, str) or _first not in graph:
            continue
        _tier = nx.shortest_path_length(graph.reverse(copy=False), _first)
        _direct = nx.ancestors(radial_graph, _first) | {_first}
        for _node, _hops in _tier.items():
            _on_docs = _node == _first or (
                _node in documented_graph
                and _first in documented_graph
                and nx.has_path(documented_graph, _node, _first)
            )
            _known = _node in node_hazards.index
            _rows.append(
                {
                    "parcel": _parcel["name"],
                    "upstream": _node,
                    "kind": node_hazards.loc[_node, "kind"] if _known else "network",
                    "hops": _hops + 1,
                    "path": "direct supply" if _node in _direct else "345 kV tie",
                    "chain_documented": _on_docs,
                    **(
                        node_hazards.loc[
                            _node,
                            [
                                "flood_zone",
                                "nri_overall",
                                "nri_coastal_flood",
                                "nri_hurricane",
                                "nri_heat_wave",
                                "nri_score",
                                "stressors",
                            ],
                        ].to_dict()
                        if _known
                        else {}
                    ),
                    "stressor_sources": _sources.get(_node, ""),
                }
            )
    _ratings = ["Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High"]
    upstream = pd.DataFrame(_rows)
    upstream["flood_rank"] = upstream["flood_zone"].map(lambda z: flood_rank.get(z, -1))
    upstream["coastal_rank"] = upstream["nri_coastal_flood"].map(lambda r: _ratings.index(r) if r in _ratings else -1)
    upstream["tie"] = upstream["path"] == "345 kV tie"
    upstream = upstream.sort_values(
        ["parcel", "tie", "flood_rank", "coastal_rank", "nri_score"], ascending=[True, True, False, False, False]
    )
    upstream["rank"] = upstream.groupby("parcel").cumcount() + 1
    upstream = upstream.drop(columns=["tie", "flood_rank", "coastal_rank"])
    upstream.to_csv(OUT / "upstream_risks.csv", index=False)
    parcel_status = (
        parcels[["name", "bbl"]]
        .join(_service[["served_by", "match"]])
        .join(_parcel_hazards.reset_index(drop=True)[["flood_zone", "nri_overall"]])
    )
    parcel_status.to_csv(OUT / "parcels.csv", index=False)
    mo.vstack([parcel_status, upstream])
    return parcel_status, upstream


@app.cell
def _(facility_nodes, graph, networks, node_hazards, parcels):
    _fig, _ax = plt.subplots(figsize=(10, 10))
    _bk = networks[networks["BOROUGH"] == "Brooklyn"]
    _bk.plot(ax=_ax, color="lightsteelblue", alpha=0.35, edgecolor="grey", linewidth=0.5)
    for _net in _bk.itertuples():
        _p = _net.geometry.representative_point()
        _ax.annotate(_net.network, (_p.x, _p.y), fontsize=7, ha="center", color="dimgrey")
    _located = facility_nodes[facility_nodes.geometry.notna()].set_index("node")
    _centre = _located.geometry.representative_point()
    for _u, _v, _d in graph.edges(data=True):
        if _u in _centre.index and _v in _centre.index:
            _ax.plot(
                [_centre[_u].x, _centre[_v].x],
                [_centre[_u].y, _centre[_v].y],
                color="black" if _d["status"] == "documented" else "red",
                linestyle="-" if _d["status"] == "documented" else "--",
                linewidth=0.8,
            )
    _style = {"plant": ("s", "darkorange"), "transmission substation": ("^", "navy"), "area substation": ("o", "teal")}
    for _kind, (_marker, _colour) in _style.items():
        _pts = _centre[_located["kind"] == _kind]
        _ax.scatter(_pts.x, _pts.y, marker=_marker, color=_colour, s=60, label=_kind, zorder=3)
    _placed = parcels[parcels.geometry.notna()]
    _ax.scatter(
        _placed.geometry.x, _placed.geometry.y, marker="*", color="crimson", s=160, label="sample parcel", zorder=4
    )
    _ax.set_xlim(-74.1, -73.82)
    _ax.set_ylim(40.56, 40.75)
    _wet = _centre[node_hazards.reindex(_centre.index)["flood_zone"].isin(["AE", "A", "AO", "AH", "VE", "V"])]
    _ax.scatter(
        _wet.x, _wet.y, s=260, facecolors="none", edgecolors="red", linewidths=1.5, label="in FEMA 1% flood zone"
    )
    _ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    _ax.set_title("Brooklyn power dependencies: Con Edison networks (shaded), documented links (black), inferred (red)")
    _ax.set_axis_off()
    _fig.savefig(OUT / "map.png", dpi=130, bbox_inches="tight")
    _fig
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 11. What didn't work, and what this doesn't show

    The counts below come from this run. The README discusses them.
    """)
    return


@app.cell
def _(
    area_substations_for_80,
    coverage,
    direct_lots,
    documented_links,
    facility_nodes,
    graph,
    lot_match,
    overture_release,
    parcel_status,
    source_check,
    upstream,
):
    _links = documented_links["status"].value_counts()
    _kind = dict(zip(facility_nodes["node"], facility_nodes["kind"], strict=True))
    _types = (
        documented_links["supplier"].map(_kind) + " -> " + documented_links["consumer"].map(_kind).fillna("network")
    )
    summary = {
        "run_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "overture_release": overture_release,
        "graph_nodes": graph.number_of_nodes(),
        "graph_links": graph.number_of_edges(),
        "links_documented": int(_links.get("documented", 0)),
        "links_inferred": int(_links.get("inferred", 0)),
        "links_by_type": pd.crosstab(_types, documented_links["status"]).to_dict(orient="index"),
        "facilities_by_type": facility_nodes["kind"].value_counts().to_dict(),
        "facilities_not_on_map": facility_nodes.loc[facility_nodes.geometry.isna(), "node"].tolist(),
        "passages": source_check["result"].value_counts().to_dict(),
        "brooklyn_lots": int(lot_match.sum()),
        "lots_by_match": {k: int(v) for k, v in lot_match.items()},
        "area_substations_for_80pct_of_lots": area_substations_for_80,
        "lots_by_direct_area_substation": {k: int(v) for k, v in direct_lots.items()},
        "coverage": coverage.to_dict(orient="records"),
        "parcels": parcel_status["match"].value_counts().to_dict(),
        "upstream_rows": len(upstream),
        "run_seconds": round(time.perf_counter() - RUN_STARTED, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    mo.md(f"```json\n{json.dumps(summary, indent=2, default=str)}\n```")
    return (summary,)


if __name__ == "__main__":
    app.run()
