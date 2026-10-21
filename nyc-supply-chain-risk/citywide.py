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
    import openpyxl
    import pandas as pd
    import requests
    import shapely
    from pypdf import PdfReader

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("SUPPLY_CHAIN_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("SUPPLY_CHAIN_OUTPUT_DIR", HERE / "output")) / "citywide"
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    NY_FEET = "EPSG:2263"
    BOROUGHS = {"MN": "Manhattan", "BX": "Bronx", "BK": "Brooklyn", "QN": "Queens", "SI": "Staten Island"}
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Citywide: which substation serves every tax lot in New York City?

    **The question.** The [Brooklyn notebook](supply_chain_risk.py) showed that FEMA's supply chain mapping steps
    work for power in one borough: every lot traced to a Con Edison network or feeder, then to its area substation,
    transmission substation and plants, with a public source for each link. Does that hold for all five boroughs?

    Three things change at city scale:

    1. **Network to area substation.** Brooklyn used Con Edison's 2012 network table. Con Edison's 2025
       reliability report has a current one for every area substation in the city; we read it by code and
       compare it with 2012 to see what moved.
    2. **Area substation to transmission substation.** Brooklyn needed a handful of filings. The city needs one
       link for every area substation, from Con Edison's, NYISO's and LIPA's public documents.
    3. **The places Con Edison's networks don't reach.** Most of Staten Island and eastern Queens are fed by
       overhead feeders at 33, 27, 13 and 4 kV, and the Rockaways are served by LIPA through PSEG Long Island,
       not by Con Edison at all.

    We measure what the issue asks for: facilities and links by type and borough, documented versus inferred;
    coverage against the counts Con Edison publishes per borough; and the share of the city's 857,000 tax lots
    matched to a network or feeder.
    """)
    return


@app.cell
def _():
    def get(url: str, params: dict | None = None, tries: int = 4) -> requests.Response:
        """GET with a fixed number of retries."""
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

    def arcgis(layer: str, params: dict, page: int = 2000, max_pages: int = 200) -> gpd.GeoDataFrame:
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

    def read_table(text: str, columns: list[str]) -> pd.DataFrame:
        """A table written one row per line with ' | ' between fields; an empty field is missing."""
        rows = [[field.strip() or None for field in line.split(" | ")] for line in text.strip().splitlines()]
        assert all(len(row) == len(columns) for row in rows), "every row needs one field per column"
        return pd.DataFrame(rows, columns=columns)

    return arcgis, cached, get, read_table


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. Sources, and checking each passage

    As in the Brooklyn notebook, every link that comes from a document carries the exact passage we rely on, and
    the notebook downloads the document and checks the passage is in it (ignoring case, spaces and punctuation).
    """)
    return


@app.cell
def _():
    _psc = "https://documents.dps.ny.gov/public/Common/ViewDoc.aspx?DocRefId="
    _nyiso = "https://www.nyiso.com/documents/20142"
    documents = {
        "psc-network-ranking-2012": (
            "Con Edison, 2012 Network Ranking, Exhibit IIP-8, filed with the NY PSC",
            f"{_psc}%7BF62626F2-2E5B-47D3-88FB-EC5AC20C085D%7D",
        ),
        "ju-reliability-2024": (
            "Joint Utilities of NY, 2024 Annual Report on Electric Service and Power Quality (Con Edison section)",
            "https://jointutilitiesofny.org/sites/default/files/2024%20Annual%20Report%20on%20Electric%20Service"
            "%20and%20Power%20Quality.pdf",
        ),
        "ju-reliability-2025": (
            "Joint Utilities of NY, 2025 Annual Report on Electric Service and Power Quality, filed March 2026",
            "https://jointutilitiesofny.org/sites/default/files/2025%20Annual%20Report%20on%20Electric%20Service"
            "%20and%20Power%20Quality.pdf",
        ),
        "psc-eiop-exhibits-2025": (
            "Con Edison, Exhibits EIOP 1-14 (capital project white papers), NY PSC Case 25-E-0072, January 2025",
            f"{_psc}%7BE0F9BD94-0100-C339-B1A4-BC256268F274%7D",
        ),
        "psc-eiop-exhibits-2025-upd": (
            "Con Edison, Exhibits EIOP 1-5, 7-10, 13 updated, NY PSC Case 25-E-0072, April 2025",
            f"{_psc}%7B20172196-0000-CF8D-A6FE-1D567712803A%7D",
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
        "nyiso-gold-book-2014": (
            "NYISO, 2014 Load & Capacity Data (Gold Book), the last edition with the public line list (Table VI-1b); "
            "copy filed in Kentucky PSC case 2014-00371",
            "https://psc.ky.gov/pscecf/2014-00371/rateintervention@ag.ky.gov/04062015035908/2014_GoldBook_Final.pdf",
        ),
        "nyiso-binding-2003": (
            "NYISO, Autumn 2003 TCC auction binding constraints",
            f"{_nyiso}/1400159/binding_constrt_081503.pdf/a549d691-41ec-4896-6a9b-8b62832d2028",
        ),
        "coned-lrtp-2011": (
            "Con Edison, The Long-Range Transmission Plan 2011-2020, September 2011",
            f"{_nyiso}/1406526/ConEd_2011_LTP.pdf/0b5b27b4-ea04-d7b0-f967-cbc8e8bb91ad",
        ),
        "coned-lrtp-2014": (
            "Con Edison, Long-Range Transmission Plan 2014-2024, presentation to NYISO ESPWG/TPAS, September 2014",
            f"{_nyiso}/1402382/Con%20Ed%202014%20Long%20Range%20Transmission%20Plan%20-%20NYISO%209-23.pdf"
            "/8b9f6ca8-84c2-54d5-0647-4a74676ac0e9",
        ),
        "psc-eiop-2013": (
            "Con Edison, Electric Infrastructure and Operations Panel testimony, 2013 rate case",
            f"{_psc}%7BA3EFED44-5E61-42B6-9348-7AB59BAA8CB5%7D",
        ),
        "psc-eiop-2016": (
            "Con Edison, Electric Infrastructure and Operations Panel testimony, 2016 rate case",
            f"{_psc}%7B4BEE2FD7-6E49-40AE-B007-3B76085F31AC%7D",
        ),
        "psc-eiop4-2019": (
            "Con Edison, Exhibit EIOP-4, New Business and System Expansion white papers, Case 19-E-0065",
            f"{_psc}%7B243D796F-6683-46BB-B445-8BD1A2917962%7D",
        ),
        "psc-eiop-2022": (
            "Con Edison, Electric Infrastructure and Operations Panel testimony, Case 22-E-0064, January 2022",
            f"{_psc}%7BB0E87187-0000-CC36-9CBE-30E2CBB7FDD4%7D",
        ),
        "psc-eiop-update-2022": (
            "Con Edison, Electric Infrastructure and Operations Panel update with exhibits, Case 22-E-0064",
            f"{_psc}%7BC03D03B9-B1C0-4B1E-A0F8-BF45B2D499C2%7D",
        ),
        "psc-urgent-projects-2024": (
            "Con Edison, Urgent Projects Proposal, Case 24-E-0364",
            f"{_psc}%7B50672793-0000-C09B-BFAB-3705801008E7%7D",
        ),
        "colt-w49-2012": (
            "The Colt Group, SF6 leak reduction case study of Con Edison's West 49th Street station, EPA workshop "
            "(a contractor's slides, not a Con Edison document)",
            "https://www.epa.gov/sites/default/files/2017-02/documents/colby_presentation_2017_workshop.pdf",
        ),
        "pseg-li-ltp-2023": (
            "PSEG Long Island / LIPA, Local Transmission Plan update to NYISO, 2023",
            f"{_nyiso}/36107410/04_2023_PSEGLI_LIPA_LTPupdate_Final.pdf/c7be52ed-bba9-4823-7d0d-f41cb531c846",
        ),
        "psc-wntp-2017": (
            "PSEG Long Island, Western Nassau Transmission Project filing, NY PSC Case 17-T-0752",
            f"{_psc}%7BC7D98A3D-4EB6-4919-BFB7-EE2F70195647%7D",
        ),
    }
    return (documents,)


@app.cell
def _(documents, get):
    def normalise(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", text.lower())

    def raw_text(source: str) -> list[str] | None:
        """The document's text: one entry per spreadsheet row, or per PDF page, or one for a web page.
        None if it can't be downloaded from here. The Brooklyn notebook's copies in DATA are reused."""
        path = DATA / f"doc-{source}"
        if not path.exists():
            try:
                path.write_bytes(get(documents[source][1], tries=2).content)
            except RuntimeError as error:
                print(f"unreachable: {source}: {error}")
                return None
        raw = path.read_bytes()
        if raw.startswith(b"%PDF"):
            return [page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages]
        if raw.startswith(b"PK"):
            book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True)
            rows = (row for sheet in book.worksheets for row in sheet.iter_rows(values_only=True))
            return [" ".join(str(c) for c in row if c is not None) for row in rows]
        return [re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "replace"))]

    document_pages = {source: raw_text(source) for source in documents}
    return document_pages, normalise


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. Network to area substation

    **Today's table.** Con Edison's annual reliability report, filed with the PSC and published by the Joint
    Utilities, has a table of the power quality monitors at each area substation. Each row names the substation
    and the network IDs and names it supplies, so it is the current version of the pairing the Brooklyn notebook
    took from 2012. We read the 2025 report's table (filed March 2026) with a regular expression.
    """)
    return


@app.cell
def _(arcgis, cached):
    _coned = "https://services.arcgis.com/ciPnsNFi1JLWVjva/arcgis/rest/services"
    networks = cached(
        "coned-networks.parquet",
        lambda: arcgis(f"{_coned}/CECONY_NetworkLCSD_Prod/FeatureServer/0", {"outFields": "NETWORK,BOROUGH"}, 1000),
    )
    network_areas = cached(
        "coned-network-supplied-areas.parquet",
        lambda: arcgis(f"{_coned}/CECONY_NwkSuppliedArea_Prod/FeatureServer/0", {"outFields": "OBJECTID"}, 1000),
    )
    networks = networks[networks["BOROUGH"] != "Westchester"].rename(
        columns={"NETWORK": "network", "BOROUGH": "borough"}
    )
    # The map splits Richmond Hill at the borough line and Fulton and Bowling Green into sub-networks.
    networks["base"] = networks["network"].str.replace(r" - (BK|QN)| SN\d", "", regex=True)
    networks[["network", "borough"]].groupby("borough").size().rename("load areas on Con Edison's map")
    return network_areas, networks


@app.cell
def _():
    def canonical_station(name: str) -> str:
        """One spelling per area substation: the reports, the 2012 table and the hosting capacity map differ."""
        name = re.sub(r"\s*\((Bk|Bx|Mhtn)\)", "", name).replace("Greeenwood", "Greenwood").replace("#", "No. ")
        name = name.title() if name.isupper() else name
        name = re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), name)
        name = re.sub(r"\s+", " ", name).replace(" Substation", "")
        name = re.sub(r"No\.\s*(\d)", r"No. \1", name)
        name = re.sub(r"^E\.? ", "East ", re.sub(r"^W\.? ", "West ", name))
        name = re.sub(r"\bSt\.?$|\bSt\.? (?=No)", "Street ", name).strip()
        name = re.sub(r"^Leonard (?=No)", "Leonard Street ", re.sub(r"\bAve\. A$", "Avenue A", name))
        name = re.sub(r"\s+", " ", name.replace("Hell Gate", "Hellgate")).strip()
        # The hosting capacity map drops "Street" from Plymouth; the 2012 table writes Trade Center without "No. 1".
        return {"Plymouth": "Plymouth Street", "Trade Center": "Trade Center No. 1"}.get(name, name)

    return (canonical_station,)


@app.cell
def _(canonical_station, document_pages, normalise):
    _pages = document_pages["ju-reliability-2025"]
    assert _pages is not None, "the 2025 reliability report holds today's network table; it must download"
    _table = "\n".join(p for p in _pages if "Quantity and Location of PQ Nodes" in p)
    # "<monitors> <transformers> <substation> <IDs like 28M, 47M> <names> LAN|WIRELESS"; Bensonhurst No. 1 wraps.
    _row = re.compile(r"^\s*\d+ \d+ +(.+?) +((?:\d+[MBQXRW], ?)*\d+[MBQXRW])\b(.*?)(?=LAN|WIRELESS)", re.M | re.S)
    _rows = []
    for _station, _ids, _names in _row.findall(_table):
        for _id in re.findall(r"\d+[MBQXRW]", _ids):
            _rows.append((canonical_station(_station), str(int(_id[:-1])) + _id[-1], " ".join(_names.split())))
    table_2025 = pd.DataFrame(_rows, columns=["area_substation", "network_id", "names"])
    # Westchester (W) is outside the city.
    table_2025 = table_2025[~table_2025["network_id"].str.endswith("W")]
    _total = re.search(r"In total, there are (\d+) area substations", _table)
    assert _total, "the table's own total is missing"
    mo.md(
        f"Read **{table_2025['area_substation'].nunique()} NYC area substations** and "
        f"**{len(table_2025)} network IDs** from the 2025 table (the report's own total, with Westchester's 12: "
        f"{_total.group(1)} area substations)."
    )
    return (table_2025,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **The 2012 table, for comparison.** Con Edison's 2012 network ranking (PSC exhibit IIP-8), used in Brooklyn,
    pairs each network with its area substation in one row. Network and substation names run together in its
    text, so we split them at the longest network name that also appears on Con Edison's map.
    """)
    return


@app.cell
def _(canonical_station, document_pages, networks):
    _text = document_pages["psc-network-ranking-2012"]
    assert _text is not None, "the 2012 network ranking must download"
    _row = re.compile(r"^(\d+) ([BMQX]) (\d+[BMQX]) (.+?) (\d\.\d{6}) (\d\.\d\d)\s*$")
    # Names on today's map, plus the one 2012 name that has since gone (Randalls Island, misspelled in the exhibit).
    _names = set(networks["base"]) | {"Randalls Insland"}
    _parsed = []
    for _line in _text[0].splitlines():
        _m = _row.match(_line.strip())
        if not _m:
            continue
        _words = _m.group(4).split()
        _cut = max(k for k in range(1, len(_words)) if " ".join(_words[:k]) in _names)
        _parsed.append((_m.group(3), " ".join(_words[:_cut]), canonical_station(" ".join(_words[_cut:]))))
    ranking_2012 = pd.DataFrame(_parsed, columns=["network_id", "network_2012", "area_substation_2012"])
    mo.md(f"Parsed **{len(ranking_2012)} networks** from the 2012 table.")
    return (ranking_2012,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Each load area on the map, paired.** A load area takes its network ID from the 2012 table (by name), then its
    area substation from the 2025 table (by ID). The networks created since 2012 have no 2012 ID, so they are found
    by name in the 2025 table, as are Staten Island's five load areas, which are named for their substations.
    Where the two tables disagree, that's a change since 2012.
    """)
    return


@app.cell
def _(networks, normalise, ranking_2012, table_2025):
    _id_2012 = ranking_2012.set_index("network_2012")["network_id"]
    _station_2012 = ranking_2012.set_index("network_id")["area_substation_2012"]
    _by_id = table_2025.drop_duplicates("network_id").set_index("network_id")["area_substation"]
    _rows = []
    for _net in networks.itertuples():
        _id = _id_2012.get(_net.base)
        if _id in _by_id.index:
            _station, _how = _by_id[_id], "2025 table, by network ID"
        else:
            _hits = table_2025[table_2025["names"].map(normalise).str.contains(normalise(_net.base))]
            _hits = table_2025[table_2025["area_substation"] == _net.base] if _hits.empty else _hits
            _station = _hits["area_substation"].iloc[0] if len(_hits) else None
            _how = "2025 table, by name" if len(_hits) else "no area substation found"
        _rows.append((_net.network, _net.borough, _id, _station, _station_2012.get(_id), _how))
    network_links = pd.DataFrame(
        _rows, columns=["network", "borough", "network_id", "area_substation", "area_substation_2012", "how"]
    )
    _moved = network_links[
        network_links["area_substation_2012"].notna()
        & (network_links["area_substation"] != network_links["area_substation_2012"])
    ]
    _gone = sorted(set(ranking_2012["network_id"]) - set(table_2025["network_id"]))
    _new = network_links["network_id"].isna() & (network_links["borough"] != "Staten Island")
    mo.vstack(
        [
            network_links.groupby(["borough", "how"]).size().unstack(fill_value=0),
            mo.md("**Changes since 2012.** Networks on a different area substation than in 2012:"),
            _moved[["network", "area_substation_2012", "area_substation"]],
            mo.md(
                "New since 2012 (no 2012 row): "
                f"{', '.join(network_links.loc[_new, 'network'])}. "
                f"2012 network IDs missing from the 2025 table: {', '.join(_gone) or 'none'}."
            ),
        ]
    )
    return (network_links,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Planned changes.** Con Edison's 2025 rate case, adopted by the PSC in January 2026, plans five new area
    substations and splits several networks between 2026 and 2035. None is in service, so the lot matching uses
    the 2025 table; the rows below are the changes a future run will need, each with its passage.
    """)
    return


@app.cell
def _(read_table):
    # network | from | to | year | source | passage
    network_changes = read_table(
        """
    Ridgewood | Brownsville No. 1 | Glendale | 2026 | psc-eiop-exhibits-2025 | transfer 60 MW from Brownsville No. 1 to Glendale.
    Crown Heights | Brownsville No. 1 | Gateway Park No. 1 | 2028 | psc-eiop-exhibits-2025 | Split Crown Heights network and transfer 120 MW from Brownsville No. 1 to Gateway
    Jamaica | Jamaica | Idlewild | 2028 | psc-eiop-exhibits-2025 | Transferring 170 MW from the Jamaica Network to the new Idlewild 27 kV Distribution Area Substation
    Flatbush | Bensonhurst No. 2 | Gateway Park No. 1 | 2030 | psc-eiop-exhibits-2025 | 4B South of Newkirk Avenue will be supplied by the newly established Gateway Park 1 (GP1) substation.
    Williamsburg | Water Street | Nevins Street | 2032 | psc-eiop-exhibits-2025 | 6B South of Flushing Avenue supplied by the new Nevins station.
    Flushing | Corona No. 1 | Hillside | 2033 | psc-eiop-exhibits-2025 | this load will then be fed from the new Hillside substation and will be referred to as the Bayside
    Richmond Hill | Brownsville No. 2 | Atlantic | 2034 | psc-eiop-exhibits-2025-upd | Brownsville No. 2 to Atlantic Area Substation-Richmond Hill (9B) to Ozone Park (11Q) Transfer
    Bay Ridge | Greenwood | Industry City | 2034 | psc-eiop-exhibits-2025-upd | Greenwood to Industry City - Bay Ridge (8B) to South Brooklyn (15B) Transfer
        """,
        ["network", "from", "to", "year", "source", "passage"],
    )
    network_changes["change"] = (
        "part moves from "
        + network_changes["from"]
        + " to "
        + network_changes["to"]
        + " ("
        + network_changes["year"]
        + ")"
    )
    network_changes[["network", "from", "to", "year"]]
    return (network_changes,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. Area substation to transmission substation

    Brooklyn's links came from four filings. For the city we searched Con Edison's rate-case testimony and
    exhibits, its long-range transmission plans, NYISO's Gold Books and bulk-system list, and LIPA's transmission
    plan. One row per link, written out so it can be read:

    - `documented`: the passage names both ends (or, for testimony, the sentence about that station names its
      supplier);
    - `planned`: a filing names the link for a project not yet in service;
    - `inferred`: no document says it. Most are stations that share a site and a name with a 138 kV station
      (Corona, Jamaica, Hellgate); a few rest on a sentence that names a group of suppliers without saying which
      feeds which, or on a line that exists without saying which way it supplies.

    Transmission stations carry their top voltage in the name (`Farragut 345 kV`), so a station that is both a
    transmission and an area substation (Greenwood) appears as two nodes. Past the first transmission station
    we add the 345 and 138 kV ties named in the 2014 Gold Book (the last public edition of Con Edison's line list;
    later editions withhold it) and NYISO's bulk-system list, and stop there, as in Brooklyn. Plants are left out.
    """)
    return


@app.cell
def _(read_table):
    # supplier | consumer | status | source | passage. Testimony passages are the sentence about that station; the
    # Rainey sentence opens on the line before ("the East 75th and West 110th Street Area").
    supply_links = read_table(
        """
    West 49th Street 345 kV | West 42nd Street No. 1 | documented | colt-w49-2012 | Eleven 138 kV feeders from the station supply W 42nd St., W 50th St., W 65th St. and Astor
    West 49th Street 345 kV | West 42nd Street No. 2 | documented | colt-w49-2012 | Eleven 138 kV feeders from the station supply W 42nd St., W 50th St., W 65th St. and Astor
    West 49th Street 345 kV | West 50th Street | documented | colt-w49-2012 | Eleven 138 kV feeders from the station supply W 42nd St., W 50th St., W 65th St. and Astor
    West 49th Street 345 kV | West 65th Street No. 1 | documented | colt-w49-2012 | Eleven 138 kV feeders from the station supply W 42nd St., W 50th St., W 65th St. and Astor
    West 49th Street 345 kV | West 65th Street No. 2 | documented | colt-w49-2012 | Eleven 138 kV feeders from the station supply W 42nd St., W 50th St., W 65th St. and Astor
    West 49th Street 345 kV | Astor | documented | colt-w49-2012 | Eleven 138 kV feeders from the station supply W 42nd St., W 50th St., W 65th St. and Astor
    East 13th Street 345 kV | Cherry Street | documented | coned-lrtp-2011 | Transfer 25 MW from Cherry St. (E 13th St. S/S) to Seaport #1
    East 13th Street 345 kV | West 19th Street | inferred | psc-eiop-2016 | supplied from the West 49th Street, East 13th Street, and
    East 13th Street 345 kV | East 29th Street | inferred | psc-eiop-2016 | supplied from the West 49th Street, East 13th Street, and
    East 13th Street 345 kV | East 36th Street | inferred | psc-eiop-2016 | supplied from the West 49th Street, East 13th Street, and
    East 13th Street 345 kV | Avenue A | inferred | psc-eiop-2016 | supplied from the West 49th Street, East 13th Street, and
    Vernon 138 kV | East 40th Street No. 1 | inferred | psc-eiop-2016 | supplied from the West 49th Street, East 13th Street, and
    Vernon 138 kV | East 40th Street No. 2 | inferred | psc-eiop-2016 | supplied from the West 49th Street, East 13th Street, and
    Vernon 138 kV | Murray Hill | inferred | psc-eiop-2016 | supplied from the West 49th Street, East 13th Street, and
    Queensbridge 138 kV | East 63rd Street No. 1 | inferred |  | inferred: only forum posts name it
    Queensbridge 138 kV | East 63rd Street No. 2 | inferred |  | inferred: only forum posts name it
    Farragut 345 kV | Seaport No. 1 | documented | psc-eiop-update-2022 | the Seaport/Trade Center loads that are currently supplied by the Farragut
    Farragut 345 kV | Seaport No. 2 | documented | psc-eiop-update-2022 | the Seaport/Trade Center loads that are currently supplied by the Farragut
    Farragut 345 kV | Trade Center No. 1 | documented | psc-eiop-update-2022 | the Seaport/Trade Center loads that are currently supplied by the Farragut
    Rainey 345 kV | East 75th Street | documented | psc-eiop-2013 | Substations in Manhattan are supplied from Rainey
    Rainey 345 kV | West 110th Street No. 1 | documented | psc-eiop-2013 | Substations in Manhattan are supplied from Rainey
    Rainey 345 kV | West 110th Street No. 2 | documented | psc-eiop-2013 | Substations in Manhattan are supplied from Rainey
    East River 69 kV | Leonard Street No. 1 | documented | psc-eiop-2013 | East River Gen. No. 1 and the power supply to the Leonard
    East River 69 kV | Leonard Street No. 2 | documented | psc-eiop-2013 | East River Gen. No. 1 and the power supply to the Leonard
    Dunwoodie North 138 kV | Sherman Creek | documented | nyiso-gold-book-2014 | Dunwoodie North Sherman Creek (c) 138 7.88 1 1500 CU 648 715 A
    Mott Haven 345 kV | Parkview | planned | psc-eiop-update-2022 | This project will establish 138kV supply feeder 38M85 from the Mott Haven 345kV Substation to the
    Mott Haven 345 kV | Mott Haven | inferred |  | inferred: same site
    East 179th Street 138 kV | Parkchester No. 1 | documented | nyiso-gold-book-2014 | East 179th St. Parkchester 138 2.19 4 1250 CU 786 927 A
    East 179th Street 138 kV | Parkchester No. 2 | documented | nyiso-gold-book-2014 | East 179th St. Parkchester 138 2.19 4 1250 CU 786 927 A
    East 179th Street 138 kV | East 179th Street | inferred |  | inferred: same site
    Hellgate 138 kV | Hellgate | inferred |  | inferred: same site
    Hellgate 138 kV | Bruckner | inferred |  | inferred: no document names Bruckner's supply
    Farragut 345 kV | Brownsville No. 1 | documented | bqdm-petition-2014 | The Brownsville substations are supplied by a set of five 138,000 volt
    Farragut 345 kV | Brownsville No. 2 | documented | bqdm-petition-2014 | The Brownsville substations are supplied by a set of five 138,000 volt
    Farragut 345 kV | Plymouth Street | documented | psc-eiop-2016 | supplied from the Farragut Substation by five 138 kV
    Hudson Avenue East 138 kV | Water Street | documented | psc-eiop4-2019 | creating an additional supply source for Plymouth and Water St.
    Greenwood 138 kV | Greenwood | documented | coned-lrtp-2014 | transferred from the Greenwood Area Station (served by Greenwood Transmission Station).
    Greenwood 138 kV | Bensonhurst No. 1 | documented | nyiso-queue | Greenwood-Bensonhurst and Farragut-Brownsville 138 kV feeders
    Greenwood 138 kV | Bensonhurst No. 2 | documented | nyiso-queue | Greenwood-Bensonhurst and Farragut-Brownsville 138 kV feeders
    Vernon 138 kV | Glendale | documented | psc-eiop-2022 | with Feeder 38Q01 from Vernon Substation, the Glendale Area
    Vernon 138 kV | Newtown | documented | psc-eiop4-2019 | Installation of fourth transformer and 138 kV supply feeder 38Q05 from Vernon (east bus) to
    Astoria East 138 kV | North Queens | documented | psc-eiop-2016 | The Astoria East/North Queens Substation is a 138kV
    Corona 138 kV | Corona No. 1 | inferred |  | inferred: same site
    Corona 138 kV | Corona No. 2 | inferred |  | inferred: same site
    Jamaica 138 kV | Jamaica | inferred |  | inferred: same site
    Fresh Kills 345 kV | Wainwright | documented | psc-eiop-update-2022 | originate from Fresh Kills Substation and are the only two supplies for Wainwright Substation.
    Fresh Kills 345 kV | Willowbrook | inferred | nyiso-binding-2003 | Willowbrook – Freshkills 138 kV
    Fresh Kills 345 kV | Woodrow | inferred |  | inferred: Woodrow's supply feeders are named, not their source
    Fresh Kills 345 kV | Fresh Kills | inferred |  | inferred: same site
    Fox Hills 138 kV | Fox Hills | documented | nyiso-gold-book-2026 | ConEd Fox Hills Fox Hills Transformer S 2030 138/33
    Valley Stream 138 kV | Far Rockaway | inferred | psc-wntp-2017 | (defined as the area encompassing the Far Rockaway load pocket and parts of the
    Far Rockaway | Arverne | documented | pseg-li-ltp-2023 | 33kV Far Rockaway to Arverne New Circuit
    Arverne | Rockaway Beach | documented | pseg-li-ltp-2023 | Install a new 33 kV circuit between the Arverne substation to the Rockaway Beach substation
        """,
        ["supplier", "consumer", "status", "source", "passage"],
    )
    # 138 and 345 kV ties, one hop out. Direction is bulk toward local; the lines themselves run both ways.
    tie_links = read_table(
        """
    Gowanus 345 kV | Greenwood 138 kV | nyiso-gold-book-2026 | ConEd Gowanus Greenwood Xfmr/PAR/Feeder
    Vernon 138 kV | Greenwood 138 kV | nyiso-gold-book-2014 | Vernon Greenwood (c) 138 9.58 2 1500 CU 810 908 A
    Greenwood 138 kV | Fox Hills 138 kV | nyiso-gold-book-2014 | Greenwood Fox Hills (c) 138 6.41 2 1500 CU 810 908 A
    Fresh Kills 345 kV | Fox Hills 138 kV | nyiso-gold-book-2014 | Fox Hills Fresh Kills (c) 138 7.51 2 2000 CU 844 960 A
    Goethals 345 kV | Fox Hills 138 kV | nyiso-gold-book-2026 | ConEd Goethals Fox Hills Xfmr/PAR/Feeder
    Goethals 345 kV | Fresh Kills 345 kV | nyiso-bps | 22 GOETHALS N.1 345 FRESHKILLS 345
    Gowanus 345 kV | Goethals 345 kV | nyiso-bps | 25 GOWANUS N. 345 GOETHALS N.1 345
    Farragut 345 kV | Gowanus 345 kV | nyiso-bps | 41 FARRAGUT 345 GOWANUS N41 345
    Rainey 345 kV | Farragut 345 kV | nyiso-bps | 61 RAINEY 345 FARRAGUT 345
    East 13th Street 345 kV | Farragut 345 kV | nyiso-bps | 45 E.13TH ST A 345 FARRAGUT 345
    Hudson Avenue East 138 kV | Farragut 345 kV | nyiso-gold-book-2014 | Hudson Avenue East Farragut (c) 138 0.28 3 2000 CU 495
    Astoria Annex 345 kV | East 13th Street 345 kV | nyiso-bps | Q35L POLETTI 345 E.13TH ST C 345
    West 49th Street 345 kV | East 13th Street 345 kV | nyiso-bps | M54 W.49TH ST 345 E.13TH ST A 345
    Sprain Brook 345 kV | West 49th Street 345 kV | nyiso-bps | M51 SPRAINBROOK 345 W.49TH ST 345
    Vernon 138 kV | West 49th Street 345 kV | nyiso-gold-book-2014 | Vernon West 49th Street 138 4.45 1 2000 CU 729 842 A
    Rainey 345 kV | Vernon 138 kV | nyiso-bps | 36312 RAINEY 1 138 VERNON 138
    Queensbridge 138 kV | Vernon 138 kV | nyiso-gold-book-2014 | Queensbridge Vernon (c) 138 0.59 1 2000 CU 1688 1920 A
    Astoria West 138 kV | Queensbridge 138 kV | nyiso-gold-book-2014 | Astoria West Queensbridge (c) 138 2.87 2 1500 CU 1620
    Hellgate 138 kV | Astoria West 138 kV | nyiso-gold-book-2014 | Hell Gate Astoria West (c) 138 1.55 5 1500 CU 746 876 A
    Hellgate 138 kV | Astoria East 138 kV | nyiso-gold-book-2014 | Hell Gate Astoria East (c) 138 1.74 2 1500 CU 810 908 A
    Astoria East 138 kV | Corona 138 kV | nyiso-gold-book-2014 | Astoria East Corona (c) 138 5.07 6 1500 CU 810 908 A
    Corona 138 kV | Jamaica 138 kV | nyiso-gold-book-2014 | Corona Jamaica (c) 138 4.55 2 1500 CU 775 898 A
    Hudson Avenue East 138 kV | Jamaica 138 kV | nyiso-gold-book-2014 | Hudson Avenue East Jamaica (c) 138 11.12 2 1500 CU 682
    East 179th Street 138 kV | Hellgate 138 kV | nyiso-gold-book-2014 | East 179th St. Hell Gate (c) 138 4.26 3 1500 CU 769
    Dunwoodie South 138 kV | East 179th Street 138 kV | nyiso-gold-book-2014 | Dunwoodie South East 179th St. (c) 138 7.45 1
    East 179th Street 138 kV | Sherman Creek | nyiso-gold-book-2014 | Sherman Creek East 179th St. (c) 138 2.04 2 1500 CU 753
    Rainey 345 kV | Mott Haven 345 kV | nyiso-gold-book-2014 | Mott Haven Rainey 345 4.39 2 2000 CU 1315 1377 A
    Dunwoodie 345 kV | Rainey 345 kV | nyiso-bps | 71 DUNWOODIE 345 RAINEY 345
        """,
        ["supplier", "consumer", "source", "passage"],
    ).assign(status="documented")
    supply_links["status"].value_counts().rename("area substation supply links")
    return supply_links, tie_links


@app.cell
def _(document_pages, documents, network_changes, normalise, supply_links, tie_links):
    _normalised = {s: [normalise(p) for p in pages] if pages else None for s, pages in document_pages.items()}

    def check(source: str | float | None, passage: str) -> str:
        if not isinstance(source, str):
            return "no source"
        entries = _normalised[source]
        if entries is None:
            return "unreachable"
        # A passage written "a ... b" needs every part on the same page or spreadsheet row.
        parts = [normalise(part) for part in passage.split(" ... ")]
        return "verified" if any(all(p in entry for p in parts) for entry in entries) else "passage not found"

    _checks = pd.concat(
        [
            supply_links.assign(what=supply_links["supplier"] + " -> " + supply_links["consumer"]),
            tie_links.assign(what=tie_links["supplier"] + " -> " + tie_links["consumer"]),
            network_changes.assign(what=network_changes["network"] + ": " + network_changes["change"]),
        ]
    )[["what", "source", "passage"]]
    source_check = _checks.assign(
        result=[check(s, p) for s, p in zip(_checks["source"], _checks["passage"], strict=True)]
    )
    source_check["document"] = source_check["source"].map(lambda s: documents[s][0] if isinstance(s, str) else "")
    source_check["url"] = source_check["source"].map(lambda s: documents[s][1] if isinstance(s, str) else "")
    source_check.to_csv(OUT / "source_check.csv", index=False)
    mo.vstack(
        [
            mo.md("**Passages checked on this run:**"),
            source_check.groupby("result").size(),
            source_check[source_check["result"].isin(["passage not found", "unreachable"])],
        ]
    )
    return (source_check,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. Where each facility is

    Footprints come from OpenStreetMap through Overture's versioned GeoParquet, read with DuckDB, as in the
    Brooklyn notebook (same release and cache file). Document names are matched to OSM names by rule: drop the
    voltage and the `No. 1` (co-located stations share a site), then look for `<name> Substation` or `<name>`.
    A few OSM spellings differ and are listed by hand. A facility's borough is the borough of the nearest tax lot
    within 2,000 feet; anything farther is outside the city.
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
def _(lots, osm_power, supply_links, table_2025, tie_links):
    _links = pd.concat([supply_links, tie_links])
    _names = sorted(set(_links["supplier"]) | set(_links["consumer"]) | set(table_2025["area_substation"]))
    _spelling = {
        "Hellgate": "Hell Gate",
        "Fox Hills": "Fox Hill",
        "Plymouth Street": "Plymouth",
        "Valley Stream": "2K Valley Stream",
        "Hudson Avenue East": "Hudson Avenue",
    }
    _subs = osm_power[osm_power["class"] == "substation"]
    _footprints = _subs.dissolve(by="name")["geometry"]
    _rows = []
    for _name in _names:
        _key = re.sub(r" \d+ kV$| No\. \d$", "", _name)
        _key = _spelling.get(_key, _key)
        _osm = next((n for n in (f"{_key} Substation", _key) if n in _footprints.index), None)
        _kind = "transmission substation" if _name.endswith(" kV") else "area substation"
        _rows.append({"node": _name, "kind": _kind, "osm_name": _osm, "geometry": _footprints[_osm] if _osm else None})
    facility_nodes = gpd.GeoDataFrame(_rows, crs=4326)
    _located = facility_nodes[facility_nodes.geometry.notna()]
    _near = gpd.sjoin_nearest(
        gpd.GeoDataFrame(geometry=_located.geometry.representative_point(), crs=4326).to_crs(NY_FEET),
        lots[["borough", "geometry"]].to_crs(NY_FEET),
        how="left",
        max_distance=2000,
    )
    facility_nodes["borough"] = _near[~_near.index.duplicated()]["borough"].reindex(facility_nodes.index)
    facility_nodes.loc[facility_nodes.geometry.notna() & facility_nodes["borough"].isna(), "borough"] = "outside NYC"
    facility_nodes[["node", "kind", "osm_name", "borough"]]
    return (facility_nodes,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. Which network or feeder serves each lot, citywide

    The rule is the Brooklyn notebook's, run on all of the city's tax lots (MapPLUTO points from NYC Open Data):
    a lot inside both a network's load area and Con Edison's network-supplied area is served by that network;
    any other lot takes the area substation of the nearest overhead feeder segment within 500 feet; a lot near no
    segment falls back to the load area it sits in, marked inferred. Con Edison's hosting capacity layers carry
    every overhead segment in its territory with its area substation, so this step needs no new source outside
    the Rockaways.
    """)
    return


@app.cell
def _(arcgis, cached):
    _coned = "https://services.arcgis.com/ciPnsNFi1JLWVjva/arcgis/rest/services"
    _nyc_box = {
        "outFields": "FEEDER_ID,SUBSTATION",
        "geometry": "-74.26,40.49,-73.69,40.92",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
    }
    # Layer 0 holds three-phase overhead segments, layer 1 one- and two-phase ones.
    feeders = cached(
        "coned-overhead-segments-nyc.parquet",
        lambda: pd.concat(
            [arcgis(f"{_coned}/CECONY_NodalHCV_Prod/FeatureServer/{n}", _nyc_box) for n in (0, 1)],
            ignore_index=True,
        ),
    )
    feeders
    return (feeders,)


@app.cell
def _(cached, get):
    def pluto_nyc() -> gpd.GeoDataFrame:
        rows: list[dict] = []
        for page in range(40):
            batch = get(
                "https://data.cityofnewyork.us/resource/64uk-42ks.json",
                {
                    "$select": "bbl,borough,latitude,longitude",
                    "$where": "latitude IS NOT NULL",
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
                return gpd.GeoDataFrame(lots[["bbl", "borough"]], geometry=points, crs=4326)
        raise RuntimeError("PLUTO returned more than 2,000,000 lots")

    lots = cached("pluto-nyc-lots.parquet", pluto_nyc)
    lots["borough"] = lots["borough"].map(BOROUGHS)
    lots.groupby("borough").size().rename("tax lots")
    return (lots,)


@app.cell
def _(canonical_station, feeders, network_areas, networks):
    def serve(points: gpd.GeoDataFrame) -> pd.DataFrame:
        """For each point: its network if inside a network-supplied area, else the area substation of the nearest
        overhead segment within 500 ft, else the load area it sits in (an inference), else nothing."""
        pts = points.to_crs(NY_FEET)
        area = gpd.sjoin(pts, networks.to_crs(NY_FEET)[["network", "geometry"]], predicate="within", how="left")
        area = area[~area.index.duplicated()]["network"]
        supplied = gpd.sjoin(pts, network_areas.to_crs(NY_FEET)[["geometry"]], predicate="within", how="inner")
        on_network = pts.index.isin(supplied.index) & area.notna()
        _feeders = feeders.assign(area_substation=feeders["SUBSTATION"].map(canonical_station, na_action="ignore"))
        near = gpd.sjoin_nearest(
            pts[~on_network], _feeders.to_crs(NY_FEET)[["area_substation", "geometry"]], how="left", max_distance=500
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
    lot_service = lots[["bbl", "borough"]].join(serve(lots))
    pd.crosstab(lot_service["borough"], lot_service["match"], margins=True)
    return (lot_service,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **The Rockaways.** LIPA, not Con Edison, serves the Rockaway peninsula, through PSEG Long Island. PSEG Long
    Island's hosting capacity map needs a login, so no public layer ties a lot to a feeder there. We place lots
    with the NY Department of Public Service's utility territory map (data.ny.gov `awza-4vgu`): a lot that no Con
    Edison network or feeder reaches and that sits in LIPA's territory gets the nearest of LIPA's three Rockaway
    substations (Far Rockaway, Arverne, Rockaway Beach), marked inferred.
    """)
    return


@app.cell
def _(cached, facility_nodes, lot_service, lots, network_links):
    def _lipa_territory() -> gpd.GeoDataFrame:
        shapes = gpd.read_file(
            io.BytesIO(
                requests.get(
                    "https://data.ny.gov/api/geospatial/awza-4vgu?method=export&format=GeoJSON",
                    timeout=180,
                    headers={"User-Agent": "Mozilla/5.0 (nyc-supply-chain-risk spike)"},
                ).content
            )
        )
        return shapes[shapes["comp_short"] == "LIPA"][["comp_full", "geometry"]]

    lipa = cached("nys-dps-lipa-territory.parquet", _lipa_territory)
    _in_lipa = lots.index.isin(gpd.sjoin(lots[["geometry"]], lipa, predicate="within").index)
    _stations = facility_nodes[facility_nodes["node"].isin(["Far Rockaway", "Arverne", "Rockaway Beach"])]
    assert _stations.geometry.notna().all(), "the three LIPA Rockaway substations must be on the map"
    _open = _in_lipa & (lot_service["match"] == "not matched").to_numpy()
    _nearest = gpd.sjoin_nearest(
        lots.loc[_open, ["geometry"]].to_crs(NY_FEET),
        gpd.GeoDataFrame(
            {"node": _stations["node"].to_numpy()}, geometry=_stations.geometry.to_numpy(), crs=4326
        ).to_crs(NY_FEET),
    )
    lot_area = lot_service.copy()
    lot_area.loc[_open, "served_by"] = _nearest[~_nearest.index.duplicated()]["node"]
    lot_area.loc[_open, "match"] = "LIPA territory, nearest substation (inferred)"
    # A network name becomes its area substation; a feeder match already names one.
    _station = network_links.set_index("network")["area_substation"]
    lot_area["area_substation"] = lot_area["served_by"].map(_station).fillna(lot_area["served_by"])
    lot_area["in_lipa_territory"] = _in_lipa
    _match = pd.crosstab(lot_area["borough"], lot_area["match"], margins=True)
    mo.vstack(
        [
            _match,
            mo.md(
                f"Lots in LIPA's territory that a Con Edison layer also reaches (territory edges disagree): "
                f"{int((_in_lipa & (lot_service['match'] != 'not matched').to_numpy()).sum()):,}."
            ),
        ]
    )
    return (lot_area,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. The dependency chain, and how much of it is documented

    Every lot now has an area substation. Its first transmission station is that substation's supplier in section
    3. Counting lots behind each one gives FEMA's Phase 2 concentration test at city scale ("the seven or fewer
    sources that are likely to generate 70 to 80 percent of total flows"), counting tax lots, not load. And for
    each lot we ask how much of its chain rests on documents: the lot-to-substation step (network boundary or
    feeder versus inference) and the substation-to-transmission step (documented, planned or inferred).
    """)
    return


@app.cell
def _(lot_area, supply_links):
    _first = supply_links[~supply_links["supplier"].isin(["Far Rockaway", "Arverne"])].drop_duplicates("consumer")
    _first = _first.set_index("consumer")
    chain = lot_area.assign(
        transmission=lot_area["area_substation"].map(_first["supplier"]),
        supply_status=lot_area["area_substation"].map(_first["status"]),
    )
    # The Rockaway stations hang off Far Rockaway, which LIPA's filings place behind Valley Stream.
    _lipa = chain["area_substation"].isin(["Far Rockaway", "Arverne", "Rockaway Beach"])
    chain.loc[_lipa, "transmission"] = "Valley Stream 138 kV"
    chain.loc[_lipa, "supply_status"] = "inferred"
    chain["lot_step"] = chain["match"].map(
        lambda m: (
            "documented"
            if m in ("network boundary", "overhead feeder")
            else "inferred"
            if m != "not matched"
            else "none"
        )
    )
    _n = len(chain)
    by_station = chain["area_substation"].value_counts()
    by_transmission = chain["transmission"].value_counts()
    stations_for_80 = int((by_station.cumsum() / _n < 0.8).sum() + 1)
    transmission_for_80 = int((by_transmission.cumsum() / _n < 0.8).sum() + 1)
    chain_documented = pd.crosstab(chain["lot_step"], chain["supply_status"].fillna("none"), margins=True)
    pd.DataFrame({"lots": by_transmission, "share": (by_transmission / _n).round(3)}).to_csv(
        OUT / "concentration_transmission.csv", index_label="transmission"
    )
    pd.DataFrame({"lots": by_station, "share": (by_station / _n).round(3)}).to_csv(
        OUT / "concentration_area_substations.csv", index_label="area_substation"
    )
    mo.vstack(
        [
            mo.md(
                f"**{stations_for_80} area substations and {transmission_for_80} first-hop transmission stations "
                f"serve 80% of the city's {_n:,} lots.** Lots behind each transmission station:"
            ),
            (by_transmission / _n).round(3).rename("share of NYC lots").head(12),
            mo.md("Lots by how their chain is sourced (rows: lot to substation; columns: substation to transmission):"),
            chain_documented,
        ]
    )
    return by_station, by_transmission, chain, chain_documented, stations_for_80, transmission_for_80


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 7. Coverage against Con Edison's own counts

    The Joint Utilities' 2024 reliability report describes each Con Edison region's distribution system in a short
    list ("Brooklyn's distribution system is comprised of: 6 Area substations, 11 Network/Load areas, ...").
    The notebook reads those lists from the PDF and sets them beside what the public sources give: the area
    substations in the 2025 table (each counted in the borough where most of the lots it serves are), how many of
    them OpenStreetMap places, the load areas on Con Edison's map, and the 4 kV unit substations OpenStreetMap has
    in each borough.
    """)
    return


@app.cell
def _(document_pages):
    _pages = document_pages["ju-reliability-2024"]
    assert _pages is not None, "the Joint Utilities report gives the published counts; it must download"
    _heads = {
        "Bronx": r"The Bronx distribution system is comprised of",
        "Brooklyn": r"Brooklyn’s distribution system is comprised of",
        "Queens": r"Queens’ distribution system\d? is comprised of",
        "Manhattan": r"The Manhattan primary distribution system is comprised of",
        "Staten Island": r"Staten Island primary distribution system is comprised of",
    }
    _kinds = {
        "area substations": r"Area [Ss]ubstations",
        "networks or load areas": r"Network/Load areas|Secondary Networks|Load Areas",
        "4 kV unit and multibank substations": r"4\s?kV (?:[Uu]nit|[Mm]ulti-?bank) substations",
    }
    _text = "\n".join(_pages)
    _published = {}
    for _borough, _head in _heads.items():
        _m = re.search(_head + r"(.*?)CAPITAL", _text, re.S)
        assert _m, f"no system description for {_borough} in the report"
        # Only the list itself: Queens' list sits between Brooklyn's and the next heading.
        _items = re.findall(r"•\s*(\d+)\s+([^\n]+)", _m.group(1).split("comprised of")[0])
        for _kind, _pattern in _kinds.items():
            _hits = [int(n) for n, label in _items if re.match(_pattern, label.strip())]
            _published[(_borough, _kind)] = sum(_hits) if _hits else None
    published_counts = pd.Series(_published, name="Con Edison 2024 report")
    published_counts.unstack()
    return (published_counts,)


@app.cell
def _(chain, facility_nodes, lots, networks, osm_power, published_counts, table_2025):
    # An area substation's borough is where most of the lots it serves are (Hellgate is in the Bronx but serves
    # Yorkville in Manhattan).
    _home = chain.groupby("area_substation")["borough"].agg(lambda b: b.value_counts().index[0])
    _named = pd.Series(sorted(set(table_2025["area_substation"])), dtype=str).map(_home)
    _on_osm = facility_nodes.loc[
        facility_nodes["node"].isin(table_2025["area_substation"]) & facility_nodes["osm_name"].notna(), "node"
    ].map(_home)
    # 4 kV unit and multibank substations: OSM features stepping 27 or 33 kV down to 4 kV, by nearest lot.
    _unit = osm_power[osm_power["voltage"].fillna("").str.match(r"(27000|33000);4000")]
    _unit_pts = gpd.GeoDataFrame(geometry=_unit.geometry.representative_point(), crs=4326).to_crs(NY_FEET)
    _unit_borough = gpd.sjoin_nearest(_unit_pts, lots[["borough", "geometry"]].to_crs(NY_FEET), max_distance=2000)
    _unit_borough = _unit_borough[~_unit_borough.index.duplicated()]["borough"]
    _boroughs = list(BOROUGHS.values())
    coverage = pd.DataFrame(
        {
            "area substations, 2024 report": [published_counts.get((b, "area substations")) for b in _boroughs],
            "area substations, 2025 table": [int((_named == b).sum()) for b in _boroughs],
            "area substations found on OSM": [int((_on_osm == b).sum()) for b in _boroughs],
            "load areas, 2024 report": [published_counts.get((b, "networks or load areas")) for b in _boroughs],
            "load areas on Con Edison's map": [int((networks["borough"] == b).sum()) for b in _boroughs],
            "4 kV unit substations, 2024 report": [
                published_counts.get((b, "4 kV unit and multibank substations")) for b in _boroughs
            ],
            "4 kV unit substations on OSM": [int((_unit_borough == b).sum()) for b in _boroughs],
        },
        index=_boroughs,
    )
    coverage.to_csv(OUT / "coverage.csv", index_label="borough")
    coverage
    return (coverage,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 8. Facilities and links, by type and borough
    """)
    return


@app.cell
def _(facility_nodes, network_links, supply_links, tie_links):
    _borough = facility_nodes.set_index("node")["borough"].fillna("not located")
    facilities_by_borough = pd.crosstab(facility_nodes["kind"], facility_nodes["borough"].fillna("not located"))
    _supply = supply_links.assign(
        type="transmission -> area substation", borough=supply_links["consumer"].map(_borough)
    )
    _ties = tie_links.assign(type="transmission tie", borough=tie_links["consumer"].map(_borough))
    _networks = network_links.assign(
        type="area substation -> load area",
        status=network_links["area_substation"].notna().map({True: "documented", False: "none"}),
    )
    all_links = pd.concat(
        [
            _networks[["type", "borough", "status"]],
            _supply[["type", "borough", "status"]],
            _ties[["type", "borough", "status"]],
        ],
        ignore_index=True,
    )
    links_by_borough = pd.crosstab([all_links["type"], all_links["status"]], all_links["borough"], margins=True)
    links_by_borough.to_csv(OUT / "links_by_borough.csv")
    facility_nodes.drop(columns="geometry").to_csv(OUT / "facilities.csv", index=False)
    pd.concat([supply_links.assign(type="supply"), tie_links.assign(type="tie")]).to_csv(OUT / "links.csv", index=False)
    mo.vstack([facilities_by_borough, links_by_borough])
    return all_links, facilities_by_borough, links_by_borough


@app.cell
def _(chain, facility_nodes, networks, supply_links, tie_links):
    _fig, _ax = plt.subplots(figsize=(11, 11))
    networks.plot(ax=_ax, color="lightsteelblue", alpha=0.35, edgecolor="grey", linewidth=0.4)
    _located = facility_nodes[facility_nodes.geometry.notna()].set_index("node")
    _centre = _located.geometry.representative_point()
    _colour = {"documented": "black", "planned": "darkorange", "inferred": "red"}
    for _link in pd.concat([supply_links, tie_links]).itertuples():
        if _link.supplier in _centre.index and _link.consumer in _centre.index:
            _a, _b = _centre[_link.supplier], _centre[_link.consumer]
            _ax.plot(
                [_a.x, _b.x],
                [_a.y, _b.y],
                color=_colour[_link.status],
                linewidth=0.7,
                linestyle="-" if _link.status == "documented" else "--",
            )
    _lots_per = chain["area_substation"].value_counts()
    for _kind, (_marker, _c) in {"transmission substation": ("^", "navy"), "area substation": ("o", "teal")}.items():
        _pts = _centre[_located["kind"] == _kind]
        _size = (
            20 + _pts.index.map(lambda n: _lots_per.get(n, 0)).to_numpy() / 300 if _kind == "area substation" else 70
        )
        _ax.scatter(_pts.x, _pts.y, marker=_marker, color=_c, s=_size, label=_kind, zorder=3, alpha=0.85)
    _ax.set_xlim(-74.27, -73.69)
    _ax.set_ylim(40.49, 40.92)
    _ax.legend(loc="upper left")
    _ax.set_title(
        "NYC power supply chain: load areas (shaded), area substations sized by lots served,\n"
        "documented links (black), planned (orange), inferred (red)"
    )
    _ax.set_axis_off()
    _fig.savefig(OUT / "map.png", dpi=120, bbox_inches="tight")
    _fig
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 9. Summary of this run

    The counts below come from this run; the README discusses them.
    """)
    return


@app.cell
def _(
    all_links,
    by_transmission,
    chain,
    chain_documented,
    coverage,
    facilities_by_borough,
    network_changes,
    network_links,
    overture_release,
    source_check,
    stations_for_80,
    transmission_for_80,
):
    _n = len(chain)
    _unmatched = chain[chain["match"] == "not matched"]
    _both = int(((chain["lot_step"] == "documented") & (chain["supply_status"] == "documented")).sum())
    summary = {
        "run_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "overture_release": overture_release,
        "nyc_lots": _n,
        "lots_by_match": chain["match"].value_counts().to_dict(),
        "lots_matched_share": round(1 - len(_unmatched) / _n, 4),
        "unmatched_lots_by_borough": _unmatched["borough"].value_counts().to_dict(),
        "lots_with_both_steps_documented_share": round(_both / _n, 3),
        "lots_with_no_transmission_link": int(chain["transmission"].isna().sum()),
        "chain_sourcing": chain_documented.to_dict(),
        "area_substations_for_80pct_of_lots": stations_for_80,
        "transmission_stations_for_80pct_of_lots": transmission_for_80,
        "lots_by_first_transmission_station": {k: int(v) for k, v in by_transmission.items()},
        "load_areas_by_how_paired": network_links["how"].value_counts().to_dict(),
        "planned_network_changes": len(network_changes),
        "facilities_by_type_and_borough": facilities_by_borough.to_dict(orient="index"),
        "links_by_type_and_status": {
            f"{t} / {s}": int(n) for (t, s), n in all_links.groupby(["type", "status"]).size().items()
        },
        "coverage": coverage.to_dict(orient="index"),
        "passages": source_check["result"].value_counts().to_dict(),
        "run_seconds": round(time.perf_counter() - RUN_STARTED, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    mo.md(f"```json\n{json.dumps(summary, indent=2, default=str)}\n```")
    return (summary,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 10. What didn't work, and what this doesn't show

    - **The transmission step is a third inferred.** 20 of 53 area substation supply links have no document that
      names them. Most are co-located stations (Corona, Jamaica, Hellgate, East 179th Street, Mott Haven, Fresh
      Kills); the rest are Manhattan stations a 2016 testimony sentence gives as a group, Queensbridge to East 63rd
      Street (only forum posts), and Bruckner, Woodrow and Willowbrook.
    - **Con Edison's line list went private after 2014.** The 138 kV ties come from the 2014 Gold Book, found only
      as a copy in a Kentucky PSC case; later Gold Books withhold the table.
    - **The Rockaways are a guess at the substation level.** PSEG Long Island's feeder map needs a login, so a
      Rockaway lot gets the nearest of three LIPA substations.
    - **Some Bronx lots sit on Westchester feeders.** Lots within 500 feet of an overhead segment tagged with a
      Westchester station (Washington Street, Granite Hill, Cedar Street) are matched to it; the 2024 report does
      count 19 Westchester feeders among the Bronx's, but we have no transmission link for those stations.
    - **OSM places about two thirds of the area substations** and few 4 kV unit substations, so hazards per facility
      (as in Brooklyn) would miss a third of the chain. This notebook doesn't attach hazards.
    - **Lots, not load**, as in Brooklyn; and the 500 ft feeder rule and load-area fallback are models.
    - **Planned changes aren't applied.** Five new area substations and eight network splits are due between 2026
      and 2035 (section 2).
    """)
    return


if __name__ == "__main__":
    app.run()
