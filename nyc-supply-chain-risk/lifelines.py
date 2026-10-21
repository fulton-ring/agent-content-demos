import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import io
    import json
    import re
    import time
    import zipfile
    from datetime import UTC, datetime

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx
    import numpy as np
    import pandas as pd
    from pypdf import PdfReader

    # Downloads, the cache, source checks, hazards and parcel reading are shared with supply_chain_risk.py.
    from common import (
        DATA,
        FLOOD_RANK,
        NRI_RATINGS,
        NY_FEET,
        OUT,
        PARCELS,
        arcgis,
        brooklyn_lots,
        cached,
        check_passage,
        document_text,
        get,
        hazards,
        nri_tracts,
        read_parcels,
    )

    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # The other lifelines: water, wastewater, gas, fuel, food and telecom

    **The question.** The power notebook ([`supply_chain_risk.py`](supply_chain_risk.py)) showed that FEMA's Supply
    Chain Resilience Guide can be followed row by row for electric power in Brooklyn: parcel, network, substation,
    plant, with a source for each link. The guide names other lifelines that supply chain nodes usually depend on.
    For each of them, can public data place the facilities, and, harder, say **which facility serves which part
    of Brooklyn**, so that a parcel lists its upstream risks across all lifelines?

    For each lifeline the notebook:

    1. places the facilities from public datasets;
    2. writes the links (supplier → consumer) with the document and passage behind each one, as in the power
       notebook, and checks every passage in the downloaded source;
    3. matches all 275,864 Brooklyn tax lots to a serving facility where public data allows it, and says how
       (`documented`, `inferred`, or only at the level of the whole borough or city);
    4. puts the same FEMA flood zone and National Risk Index ratings on every located facility;
    5. lists the upstream facilities, across lifelines, for the sample parcels.

    It reads the power notebook's `output/upstream_risks.csv`, so run that one first (`run.sh` does).
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. Sources

    Each source below backs one or more links, locations or stressors with an exact passage. As in the power
    notebook, the source is downloaded and the passage looked for, ignoring case, spaces and punctuation.
    """)
    return


@app.cell
def _():
    _nyc = "https://www.nyc.gov/assets"
    _psc = "https://documents.dps.ny.gov/public/Common/ViewDoc.aspx?DocRefId="
    _vz = "https://www.verizon.com/about/sites/default/files"
    _vz_es = "https://espanol.verizon.com/about/sites/default/files"
    documents = {
        # Water supply
        "dep-tunnel3-eis-2005": (
            "NYC DEP, City Tunnel No. 3 Stage 2 Shaft 33B Final EIS, Chapter 2, October 2005",
            f"{_nyc}/dep/downloads/pdf/environmental-reviews/city-tunnel-no-3-stage-2-manhattan-leg-shaft-33b-project/"
            "2projectoverview.pdf",
        ),
        "dep-pipeline-2022": (
            "NYC DEP, Weekly Pipeline, 13 September 2022",
            f"{_nyc}/dep/downloads/pdf/about/weekly-pipeline/13662-pipeline.pdf",
        ),
        # Wastewater
        "dep-wastewater-map": (
            "NYC DEP, NYC Wastewater System Map (plant table), 2025",
            f"{_nyc}/dep/downloads/pdf/water/wastewater/nyc-wastewater-system-map.pdf",
        ),
        "dep-sandy-2013": (
            "NYC DEP, press release 13-107 on the Wastewater Resiliency Plan, 29 October 2013",
            "https://www.nyc.gov/html/dep/html/press_releases/13-107pr.shtml",
        ),
        # Natural gas
        "psc-gas-ltp-order-2025": (
            "NY PSC, Case 24-G-0248, Order Regarding Long-Term Natural Gas Plan, 18 September 2025",
            f"{_psc}%7BA0AD5D99-0000-C813-8D15-675F257642CA%7D",
        ),
        "ngrid-ltp-update-2026": (
            "National Grid, Annual Gas System Long-Term Plan Update, Case 24-G-0248, 15 May 2026",
            f"{_psc}%7B60312D9E-0000-CC85-BA09-FD26A6411789%7D",
        ),
        "psc-gas-rehearing-2025": (
            "NY PSC, Case 24-G-0248, Order Denying Petitions for Rehearing, 22 December 2025",
            f"{_psc}%7B6054479B-0000-C230-92E3-616045E85526%7D",
        ),
        "ferc-rockaway-2012": (
            "FERC notice of intent, Rockaway Delivery Lateral, Federal Register 2012-13279, 1 June 2012",
            "https://www.govinfo.gov/content/pkg/FR-2012-06-01/pdf/2012-13279.pdf",
        ),
        # Refined fuel
        "doe-hurricanes-2013": (
            "US DOE, Comparing the Impacts of Northeast Hurricanes on Energy Infrastructure, April 2013",
            "https://www.energy.gov/ceser/articles/comparing-impacts-northeast-hurricanes-energy-infrastructure-april-2013",
        ),
        "cgep-fuel-2016": (
            "Columbia CGEP, Improving Regional Situational Awareness During Fuel Emergencies, July 2016",
            "https://www.energypolicy.columbia.edu/sites/default/files/energy/CGEP_Tri_State_Situational_Awareness_July"
            "%202016.pdf",
        ),
        # Food
        "nyc-food-flow-2016": (
            "NYC Mayor's Office / NYCEDC, Food Distribution & Resiliency Study Results (Five Borough Food Flow), 2016",
            f"{_nyc}/foodpolicy/downloads/pdf/2016_food_supply_resiliency_study_results.pdf",
        ),
        "osc-hunts-point-2023": (
            "NY State Comptroller, Report 14-2024 on the Hunts Point Food Distribution Center, November 2023",
            "https://www.osc.ny.gov/files/reports/osdc/pdf/report-14-2024.pdf",
        ),
        "cpc-terminal-market-2010": (
            "NYC City Planning Commission, report C 090376 PPK (Brooklyn Terminal Market), 14 July 2010",
            f"{_nyc}/planning/download/pdf/about/cpc/090376.pdf",
        ),
        "edc-hunts-point-2025": (
            "NYCEDC, Hunts Point Resiliency Working Group Recommendations, 2025",
            "https://edc.nyc/sites/default/files/2025-01/Hunts-Point-Resiliency-Working-Group-Recommendations-FINAL.pdf",
        ),
        # Telecom: Verizon's copper retirement notices to the FCC list addresses by serving wire center.
        "vz-copper-2016-03-A": (
            "Verizon New York, copper retirement notice 2016-03-A-NY, 15 September 2016",
            f"{_vz}/9-15-16%20NY%20Copper%20Ret%20Notice.pdf",
        ),
        "vz-copper-2017-02-B": (
            "Verizon New York, copper retirement notice 2017-02-B-NY",
            f"{_vz_es}/Copper-Retirement-ID-No-2017-02-B-NY.pdf",
        ),
        "vz-copper-2017-03-A": (
            "Verizon New York, copper retirement notice 2017-03-A-NY",
            f"{_vz}/Copper-%20Retirement-ID-No-2017-03-A-NY.pdf",
        ),
        "vz-copper-2017-04-A": (
            "Verizon New York, copper retirement notice 2017-04-A-NY (refiled)",
            f"{_vz_es}/REFILED-Copper-Retirement-%20ID-No-2017-04-A-NY.pdf",
        ),
        "vz-copper-2018-01-A": (
            "Verizon New York, copper retirement notice 2018-01-A-NY, 9 March 2018",
            f"{_vz}/3-9-18-NY-Copper-Ret-Notice-2018-01-A-NY-web.pdf",
        ),
        "sirr-telecom-2013": (
            "City of New York, A Stronger, More Resilient New York, Chapter 9: Telecommunications, June 2013",
            f"{_nyc}/sirr/downloads/pdf/Ch_9_Telecommunications_FINAL_singles.pdf",
        ),
    }
    document_texts = {source: document_text(source, url) for source, (_, url) in documents.items()}
    return document_texts, documents


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. Where the facilities are

    One table of facilities for all six lifelines, each with how it was placed: NYC's Facilities Database for the
    treatment plants, HIFLD Next for the fuel terminals, and NYC Planning's GeoSearch for the addresses the
    documents give (Verizon wire centers, the Greenpoint LNG plant, the two food markets). Where a facility sits
    on an NYC tax lot, its footprint is that lot's MapPLUTO outline, so the flood check below looks at the whole
    site rather than one point (in the power notebook a single missing footprint hid a real Sandy flood). Gas gate
    stations, pipelines, tunnels and reservoirs have no public location from an operator, so they stay unplaced.
    """)
    return


@app.cell
def _():
    def geosearch(address: str) -> str | None:
        """BBL of an NYC address from NYC Planning's GeoSearch (no key needed)."""
        reply = get("https://geosearch.planninglabs.nyc/v2/search", {"text": address, "size": 1}).json()
        if not reply.get("features"):
            return None
        return reply["features"][0]["properties"].get("addendum", {}).get("pad", {}).get("bbl")

    lots = brooklyn_lots()
    # DEP's codes for the plants that serve Brooklyn, with the SPDES permit the state's sewershed layer uses.
    plant_codes = {
        "OH": ("Owls Head WRRF", "NY0026166"),
        "CI": ("Coney Island WRRF", "NY0026182"),
        "NC": ("Newtown Creek WRRF", "NY0026204"),
        "26W": ("26th Ward WRRF", "NY0026212"),
        "RH": ("Red Hook WRRF", "NY0027073"),
        "JA": ("Jamaica WRRF", "NY0026115"),
    }
    return geosearch, lots, plant_codes


@app.cell
def _(document_texts):
    # Wire center headings in Verizon's notices: "...wire center located at <address>; CLLI: <code> (<name>)".
    _heading = re.compile(r"wire center located (?:at )?(.+?)[;\s]*CLLI:\s*([A-Z0-9]{8})\s*\(([^)]*)\)", re.S)
    # A wrapped line of a house-number list holds only numbers, letter suffixes and commas.
    _wrapped = re.compile(r"^\s*\d+(\s?[A-Z])?(\s*,\s*\d+(\s?[A-Z])?)*\s*,?\s*$")
    _sections: list[tuple[str, str, str, str, list[str]]] = []
    for _source in [s for s in document_texts if s.startswith("vz-copper")]:
        _path = DATA / f"doc-{_source}"
        if not _path.exists():
            continue
        _text = "\n".join(page.extract_text() or "" for page in PdfReader(_path).pages)
        _starts = list(_heading.finditer(_text))
        for _n, _match in enumerate(_starts):
            _address, _clli, _name = (" ".join(g.split()) for g in _match.groups())
            if not _clli.startswith("NYCK") or "QUEENS" in _address.upper():
                continue  # NYCK is Brooklyn; one NYCK wire center (Fairview) sits in Queens
            _end = _starts[_n + 1].start() if _n + 1 < len(_starts) else len(_text)
            _lines: list[str] = []
            for _line in _text[_match.end() : _end].split("\n"):
                _line = _line.strip().upper()
                if not _line or _line.startswith("COMMUNITY") or "COPPER FACILITIES" in _line:
                    continue
                if _wrapped.match(_line) and _lines:
                    _lines[-1] += " " + _line
                else:
                    _lines.append(_line)
            _sections.append((_clli, _name, _address.split(",")[0], _source, _lines))
    # One entry per section: (wire center, its address rows). A wire center recurs across notices.
    notice_sections = [(clli, lines) for clli, _, _, _, lines in _sections]
    wire_centers = (
        pd.DataFrame([s[:4] for s in _sections], columns=["clli", "name", "address", "source"])
        .assign(
            name=lambda d: (
                d["name"].str.title().str.replace(r"(?<=\d)(St|Th|Nd|Rd)\b", lambda m: m[0].lower(), regex=True)
            )
        )
        .drop_duplicates("clli")
        .sort_values("clli")
        .reset_index(drop=True)
    )
    wire_centers
    return notice_sections, wire_centers


@app.cell
def _(geosearch, lots, plant_codes, wire_centers):
    _hifld = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    _plants = get(
        "https://data.cityofnewyork.us/resource/ji82-xba5.json",
        {"$where": "datasource='dep_wwtc'", "$select": "facname,bbl"},
    ).json()
    _plant_bbl = {
        p["facname"].replace(" WWTP", "").title().replace("26Th", "26th") + " WRRF": p["bbl"] for p in _plants
    }
    _terminals = cached(
        "hifld-pol-terminals.parquet",
        lambda: gpd.read_parquet(
            io.BytesIO(
                get(f"{_hifld}/pol-terminals-1/pol-terminals-1/v1.0.0/geoparquet/pol-terminals-1.parquet").content
            )
        ),
    )
    brooklyn_terminals = _terminals[_terminals["CITY"].str.upper() == "BROOKLYN"].to_crs(4326)
    # A terminal's tax lot is the Brooklyn lot nearest its HIFLD point, within 300 ft.
    _near = gpd.sjoin_nearest(
        brooklyn_terminals.to_crs(NY_FEET)[["NAME", "geometry"]], lots.to_crs(NY_FEET), max_distance=300
    ).drop_duplicates("NAME")
    _terminal_bbl = dict(zip(_near["NAME"].str.title(), _near["bbl"], strict=True))

    # (lifeline, node, kind, how placed, BBL). No BBL means not placed.
    _rows = [
        *(
            ("wastewater", name, "treatment plant", "NYC Facilities Database", _plant_bbl.get(name))
            for name, _ in plant_codes.values()
        ),
        ("water supply", "Catskill and Delaware aqueducts", "aqueduct", "not placed", None),
        ("water supply", "Kensico Reservoir", "reservoir", "not placed", None),
        ("water supply", "Hillview Reservoir", "reservoir", "not placed", None),
        ("water supply", "City Tunnel No. 1", "tunnel", "not placed", None),
        ("water supply", "City Tunnel No. 2", "tunnel", "not placed", None),
        ("water supply", "Brooklyn water mains", "distribution (borough level)", "not placed", None),
        # The NYSDEC bulk storage registry (facility 2-2340) gives Greenpoint LNG's address.
        (
            "natural gas",
            "Greenpoint LNG plant",
            "LNG storage",
            "GeoSearch, 287 Maspeth Ave",
            geosearch("287 Maspeth Avenue, Brooklyn"),
        ),
        ("natural gas", "National Grid NY (KEDNY) system", "gas distribution utility", "not placed", None),
        ("natural gas", "Transco-Narrows city gate", "city gate", "not placed", None),
        ("natural gas", "Transco-Rockaway city gate (Floyd Bennett Field)", "city gate", "not placed", None),
        ("natural gas", "Tetco-Goethals city gate", "city gate", "not placed", None),
        ("natural gas", "Transco pipeline", "interstate pipeline", "not placed", None),
        ("natural gas", "Texas Eastern pipeline", "interstate pipeline", "not placed", None),
        ("natural gas", "Con Edison gas system", "gas distribution utility", "not placed", None),
        *(
            ("refined fuel", n, "bulk fuel terminal", "HIFLD Next POL terminals (EIA)", _terminal_bbl.get(n))
            for n in brooklyn_terminals["NAME"].str.title()
        ),
        ("refined fuel", "Buckeye pipeline", "products pipeline", "not placed", None),
        ("refined fuel", "Colonial pipeline (Linden terminus)", "products pipeline", "not placed", None),
        ("refined fuel", "NY Harbor marine deliveries", "barges and tankers", "not placed", None),
        ("refined fuel", "Brooklyn fuel deliveries", "truck delivery (borough level)", "not placed", None),
        (
            "food",
            "Hunts Point Food Distribution Center",
            "wholesale food hub",
            "GeoSearch, 355 Food Center Dr",
            geosearch("355 Food Center Drive, Bronx"),
        ),
        (
            "food",
            "Brooklyn Terminal Market",
            "wholesale food hub",
            "GeoSearch, 8201 Foster Ave",
            geosearch("8201 Foster Avenue, Brooklyn"),
        ),
        ("food", "NYC food outlets", "retail (city level)", "not placed", None),
        *(
            (
                "telecom",
                f"Verizon {w.name} ({w.clli})",
                "wire center",
                f"GeoSearch, {w.address}",
                geosearch(f"{w.address}, Brooklyn"),
            )
            for w in wire_centers.itertuples()
        ),
    ]
    _table = pd.DataFrame(_rows, columns=["lifeline", "node", "kind", "placed_by", "bbl"])
    _table["bbl"] = _table["bbl"].map(lambda b: str(int(float(b))) if pd.notna(b) and b else None)
    _bbls = ",".join(sorted(_table["bbl"].dropna().unique()))
    _footprints = arcgis(
        "https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services/MAPPLUTO/FeatureServer/0",
        {"where": f"BBL IN ({_bbls})", "outFields": "BBL"},
    )
    _outline = _footprints.assign(bbl=_footprints["BBL"].astype("int64").astype(str)).dissolve(by="bbl")["geometry"]
    facilities = gpd.GeoDataFrame(_table, geometry=_table["bbl"].map(_outline), crs=4326)
    facilities.loc[facilities.geometry.isna() & facilities["bbl"].notna(), "placed_by"] += " (lot not in MapPLUTO)"
    facilities.drop(columns="geometry").assign(placed=facilities.geometry.notna())
    return brooklyn_terminals, facilities


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. The links, row by row

    Same format as the power notebook: `supplier` feeds `consumer`, with the document and passage. `documented`
    means a document or a dataset field names the link; `inferred` means we filled it in. A consumer ending in
    *(borough level)* or *(city level)* means the source names the link only for all of Brooklyn or all of the
    city, not for a part of it.
    """)
    return


@app.cell
def _(brooklyn_terminals, wire_centers):
    _eis, _psc, _ltp = "dep-tunnel3-eis-2005", "psc-gas-ltp-order-2025", "ngrid-ltp-update-2026"
    _gates = "KEDNY’s city gates are Tetco–Goethals (Staten Island), Transco–Narrows (Brooklyn), and Transco–Rockaway"
    _rows = [
        # Water supply: one chain for the whole borough.
        (
            "water supply",
            "Catskill and Delaware aqueducts",
            "Kensico Reservoir",
            _eis,
            "through the 92-mile- long Catskill Aqueduct and the 85-mile-long Delaware Aqueduct to the Kensico "
            "Reservoir",
        ),
        (
            "water supply",
            "Kensico Reservoir",
            "Hillview Reservoir",
            _eis,
            "conveyed to the Hillview Reservoir in Yonkers",
        ),
        *(
            (
                "water supply",
                "Hillview Reservoir",
                f"City Tunnel No. {n}",
                _eis,
                "From the Hillview Reservoir, the water enters City Tunnels No. 1 and 2 for distribution throughout "
                "the City.",
            )
            for n in (1, 2)
        ),
        (
            "water supply",
            "City Tunnel No. 1",
            "Brooklyn water mains",
            _eis,
            "extends south from the Hillview Reservoir through the West Bronx to Manhattan and Brooklyn",
        ),
        (
            "water supply",
            "City Tunnel No. 2",
            "Brooklyn water mains",
            "dep-pipeline-2022",
            "City Water Tunnel No. 2 was activated in 1936 and brings water to the residents of Queens and Brooklyn.",
        ),
        # Wastewater: DEP's plant table gives each plant's borough, population served and drainage acres.
        *(
            ("wastewater", f"{plant} WRRF", "lots in its DEP drainage area", "dep-wastewater-map", passage)
            for plant, passage in [
                ("Owls Head", "OH Owls Head 1952 120 240 Brooklyn 758,007 12,947"),
                ("Coney Island", "CI Coney Island 1935 110 220 Brooklyn 596,326 15,087"),
                ("26th Ward", "26W 26th Ward 1944 85 170 Brooklyn 283,428 5,907"),
                ("Red Hook", "RH Red Hook 1987 60 120 Brooklyn 192,050 3,200"),
                ("Newtown Creek", "NC Newtown Creek 1967 310 700 Brooklyn 1,068,012 15,656"),
            ]
        ),
        # Natural gas: the utility territory, its three city gates, its LNG plant and the Con Edison transfer.
        *(
            (
                "natural gas",
                gate,
                "National Grid NY (KEDNY) system",
                _psc,
                "KEDNY receives supply from the Tetco-Goethals, Transco-Narrows and Transco-Rockaway city gates",
            )
            for gate in (
                "Transco-Narrows city gate",
                "Transco-Rockaway city gate (Floyd Bennett Field)",
                "Tetco-Goethals city gate",
            )
        ),
        (
            "natural gas",
            "Greenpoint LNG plant",
            "National Grid NY (KEDNY) system",
            _psc,
            "Greenpoint contains two LNG storage tanks that help to meet periods of peak demand",
        ),
        (
            "natural gas",
            "Con Edison gas system",
            "National Grid NY (KEDNY) system",
            _psc,
            "on a design day KEDNY/KEDLI are net takers and depend on Con Edison to transfer supply",
        ),
        ("natural gas", "Transco pipeline", "Transco-Narrows city gate", _ltp, _gates),
        (
            "natural gas",
            "Transco pipeline",
            "Transco-Rockaway city gate (Floyd Bennett Field)",
            "ferc-rockaway-2012",
            "from Transco's pipeline system to National Grid's distribution system in Brooklyn, New York",
        ),
        ("natural gas", "Texas Eastern pipeline", "Tetco-Goethals city gate", _ltp, _gates),
        # Refined fuel: documented down to "Brooklyn/Queens terminals"; which terminal fills which truck is private.
        (
            "refined fuel",
            "Colonial pipeline (Linden terminus)",
            "Buckeye pipeline",
            "cgep-fuel-2016",
            "Petroleum products are delivered to the area primarily via (1) the Colonial and Buckeye pipeline systems",
        ),
        *(
            (
                "refined fuel",
                t.NAME.title(),
                "Brooklyn fuel deliveries",
                "doe-hurricanes-2013",
                "These distribution terminals supply gasoline, heating oil, and diesel fuel to trucks for delivery to "
                "retail outlets and local distributors.",
            )
            for t in brooklyn_terminals.itertuples()
        ),
        # Pipeline and marine receipts are fields in the EIA terminal data; Buckeye is the only products pipeline
        # that reaches Brooklyn on EIA's map, so we infer that PIPE_IN means Buckeye.
        *(
            (
                "refined fuel",
                "Buckeye pipeline",
                t.NAME.title(),
                None,
                "inferred: PIPE_IN = YES, and Buckeye is the only products pipeline into Brooklyn",
            )
            for t in brooklyn_terminals.itertuples()
            if t.PIPE_IN == "YES"
        ),
        *(
            (
                "refined fuel",
                "NY Harbor marine deliveries",
                t.NAME.title(),
                "dataset:hifld-pol-terminals",
                "MARINE_IN = YES",
            )
            for t in brooklyn_terminals.itertuples()
            if t.MARINE_IN == "YES"
        ),
        # Food: Hunts Point's citywide share is documented; no hub has a documented service area.
        (
            "food",
            "Hunts Point Food Distribution Center",
            "NYC food outlets",
            "osc-hunts-point-2023",
            "About 12 percent of all food in the City goes through FDC, including about 25 percent of produce, 35 "
            "percent of meat and 45 percent of fish.",
        ),
        # Telecom: each wire center serves the addresses its copper notices list (matched to lots in section 4).
        *(
            (
                "telecom",
                f"Verizon {w.name} ({w.clli})",
                "addresses its notices list",
                w.source,
                f"wire center located ... {w.clli}",
            )
            for w in wire_centers.itertuples()
        ),
    ]
    lifeline_links = pd.DataFrame(_rows, columns=["lifeline", "supplier", "consumer", "source", "passage"])
    lifeline_links["status"] = lifeline_links["source"].map(
        lambda s: "documented" if isinstance(s, str) else "inferred"
    )
    lifeline_links["level"] = (
        lifeline_links["consumer"]
        .map({"Brooklyn water mains": "borough", "Brooklyn fuel deliveries": "borough", "NYC food outlets": "city"})
        .fillna("facility")
    )
    lifeline_links
    return (lifeline_links,)


@app.cell
def _():
    # Documented stressors. A node in parentheses applies to the whole lifeline.
    _psc = "psc-gas-ltp-order-2025"
    lifeline_stressors = pd.DataFrame(
        [
            (
                "water supply",
                "City Tunnel No. 2",
                "Tunnel No. 3's Brooklyn/Queens leg still unfinished in 2022",
                "dep-pipeline-2022",
                "one of the final shafts for the portion of City Water Tunnel No. 3 that will serve Queens and "
                "Brooklyn",
            ),
            (
                "wastewater",
                "(all DEP plants)",
                "10 of 14 plants and 42 of 96 pumping stations damaged in Sandy",
                "dep-sandy-2013",
                "were damaged during Sandy and nearly $50 million has been already been spent on repairs",
            ),
            (
                "natural gas",
                "National Grid NY (KEDNY) system",
                "2019 moratorium on new gas service",
                _psc,
                "National Grid announced a moratorium on new gas service installations in its KEDNY and KEDLI service "
                "territories",
            ),
            (
                "natural gas",
                "National Grid NY (KEDNY) system",
                "supply constrained by interstate pipeline capacity",
                "psc-gas-rehearing-2025",
                "National Grid’s downstate natural gas system has current reliability concerns due to supply "
                "constraints, which in turn are due to inadequate interstate pipeline capacity",
            ),
            (
                "refined fuel",
                "(all NY Harbor terminals)",
                "40 of 53 harbor terminals flooded in Sandy",
                "doe-hurricanes-2013",
                "Forty, or 76 percent, of the 53 petroleum terminals located in the New York Harbor were in flooded "
                "areas during Sandy",
            ),
            (
                "refined fuel",
                "Colonial pipeline (Linden terminus)",
                "Linden outage shut Colonial's line to NY Harbor after Sandy",
                "doe-hurricanes-2013",
                "The Linden facility is the terminus of the Colonial Pipeline and the outage of this facility caused "
                "Colonial to shut down the segment of its mainline system",
            ),
            (
                "refined fuel",
                "Buckeye pipeline",
                "affected by Irene and Sandy",
                "doe-hurricanes-2013",
                "Both storms affected portions of the Buckeye Pipeline",
            ),
            (
                "food",
                "Hunts Point Food Distribution Center",
                "low-lying, prone to flooding and loss of power",
                "edc-hunts-point-2025",
                "there is awareness that Hunts Point is a low lying area prone to flooding and loss of power",
            ),
            (
                "telecom",
                "(all central offices)",
                "Sandy flooded central offices and cut service in the areas they served",
                "sirr-telecom-2013",
                "At critical facilities in Southern Manhattan, Red Hook, and the Rockaways, flood damage to equipment "
                "and backup power systems caused service to go out in the areas they served.",
            ),
        ],
        columns=["lifeline", "node", "stressor", "source", "passage"],
    )
    # Passages that say a link is missing, or that place a facility.
    lifeline_notes = pd.DataFrame(
        [
            (
                "food",
                "no outlet has a single supplier, so no hub has a service area",
                "nyc-food-flow-2016",
                "All point-of-sale outlets are sourced from several types of distributors – no outlet has a single "
                "source.",
            ),
            (
                "food",
                "Brooklyn Terminal Market location and role",
                "cpc-terminal-market-2010",
                "Established in 1942, the Brooklyn Terminal Market offers wholesale and retail produce, flowers, "
                "plants, fish, groceries, and paper goods.",
            ),
            (
                "telecom",
                "what a central office serves",
                "sirr-telecom-2013",
                "They provide connectivity across all major services and each supports tens of thousands of customers.",
            ),
        ],
        columns=["lifeline", "what", "source", "passage"],
    )
    return lifeline_notes, lifeline_stressors


@app.cell
def _(document_texts, documents, lifeline_links, lifeline_notes, lifeline_stressors):
    _checks = pd.concat(
        [
            lifeline_links.assign(what=lifeline_links["supplier"] + " -> " + lifeline_links["consumer"]),
            lifeline_stressors.assign(what=lifeline_stressors["node"] + ": " + lifeline_stressors["stressor"]),
            lifeline_notes,
        ]
    )[["lifeline", "what", "source", "passage"]]
    lifeline_source_check = _checks.assign(
        result=[
            "from dataset"
            if isinstance(s, str) and s.startswith("dataset:")
            else check_passage(document_texts.get(s), s, p)
            for s, p in zip(_checks["source"], _checks["passage"], strict=True)
        ],
        url=_checks["source"].map(lambda s: documents[s][1] if s in documents else ""),
    )
    lifeline_source_check.to_csv(OUT / "lifeline_source_check.csv", index=False)
    mo.vstack([mo.md("**Passages checked on this run:**"), lifeline_source_check.groupby(["source", "result"]).size()])
    return (lifeline_source_check,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. Which facility serves each lot

    This is the hard part. For each lifeline, the best public answer:

    - **Wastewater: documented.** DEP publishes the drainage area of each of its 14 treatment plants as polygons
      (ArcGIS item *Citywide WWTP Drainage Areas*). A lot inside one drains to that plant. As a check, we compare
      with an independent statewide sewershed layer (Hill and Larsen, 2023).
    - **Natural gas: documented to the utility.** New York State publishes gas utility territories; Brooklyn is
      National Grid's NYC territory (KEDNY). Which gate or main feeds which part of Brooklyn is not public, so
      every Brooklyn lot depends on all of KEDNY's gates.
    - **Telecom: documented for some buildings, inferred for the rest.** No wire-center boundary file is public.
      But Verizon's copper retirement notices list, by house number and street, the buildings each wire center
      serves. We match those addresses to tax lots (*seed* lots) and give every other lot the wire center of its
      nearest seed. We test the rule by hiding a fifth of the tax blocks and predicting them.
    - **Water supply, refined fuel, food: borough or city level only.** The documents name the chain for all of
      Brooklyn (or the city), so every lot gets the same upstream facilities.
    """)
    return


@app.cell
def _():
    _dep = "https://services.arcgis.com/at3rDjch5X7i9Bag/arcgis/rest/services"
    drainage_areas = cached(
        "dep-drainage-areas.parquet",
        lambda: arcgis(f"{_dep}/Drainage_areas/FeatureServer/0", {"outFields": "WPCP"}),
    )
    gas_territories = cached(
        "nys-gas-territories.parquet",
        lambda: gpd.read_file(
            io.BytesIO(
                get("https://data.ny.gov/api/geospatial/i7nm-ih89", {"method": "export", "format": "GeoJSON"}).content
            )
        )[["comp_short", "geometry"]],
    )

    def _sewersheds() -> gpd.GeoDataFrame:
        _zip = get("https://www.arcgis.com/sharing/rest/content/items/e795007660ae4a1fae5f86b40d065b3a/data").content
        _dir = DATA / "nys-sewersheds"
        zipfile.ZipFile(io.BytesIO(_zip)).extractall(_dir)
        return gpd.read_file(next(_dir.rglob("*.shp")))[["WWTP_ID", "Sewershed", "geometry"]].to_crs(4326)

    sewersheds = cached("nys-sewersheds.parquet", _sewersheds)
    return drainage_areas, gas_territories, sewersheds


@app.cell
def _(drainage_areas, gas_territories, plant_codes):
    def first_match(points: gpd.GeoDataFrame, areas: gpd.GeoDataFrame, column: str) -> pd.Series:
        """The value of `column` for the area each point falls in (the first, if areas overlap)."""
        joined = gpd.sjoin(
            points.to_crs(NY_FEET), areas.to_crs(NY_FEET)[[column, "geometry"]], predicate="within", how="left"
        )
        return joined[~joined.index.duplicated()][column].reindex(points.index)

    def wastewater_plant(points: gpd.GeoDataFrame) -> pd.Series:
        return first_match(points, drainage_areas, "WPCP").map(lambda c: plant_codes.get(c, (None,))[0])

    def gas_utility(points: gpd.GeoDataFrame) -> pd.Series:
        utility = first_match(points, gas_territories, "comp_short")
        return utility.map({"NGRID - NYC": "National Grid NY (KEDNY) system", "CONED": "Con Edison gas system"})

    return first_match, gas_utility, wastewater_plant


@app.cell
def _(first_match, lots, plant_codes, sewersheds, wastewater_plant):
    _ww = wastewater_plant(lots)
    _permit = {permit: name for name, permit in plant_codes.values()}
    _state = first_match(lots, sewersheds, "WWTP_ID").map(_permit)
    wastewater_agreement = float((_ww == _state)[_ww.notna()].mean())
    lot_wastewater = _ww
    mo.vstack(
        [
            mo.md(
                f"**{_ww.notna().mean():.1%} of Brooklyn lots fall in a DEP drainage area.** The state sewershed layer "
                f"names the same plant for {wastewater_agreement:.1%} of them."
            ),
            _ww.value_counts(dropna=False).rename("lots"),
        ]
    )
    return lot_wastewater, wastewater_agreement


@app.cell
def _(gas_utility, lots):
    lot_gas = gas_utility(lots)
    mo.vstack([mo.md("**Gas utility territory, Brooklyn lots:**"), lot_gas.value_counts(dropna=False).rename("lots")])
    return (lot_gas,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Telecom: from Verizon's address lists to tax lots

    Each notice row reads *wire center, street, house numbers*, for example `14TH STREET 13 238, 240, 242`
    (the 14th Street wire center serves 238, 240 and 242 13th Street). We split off the wire center name, which
    every row of a section shares, and match each house number and street to the address MapPLUTO gives each lot,
    after reducing both to a common spelling (`AVENUE` → `AV`, `EAST` → `E`, `STREET` dropped).
    """)
    return


@app.cell
def _(notice_sections):
    _pluto_path = DATA / "pluto-brooklyn-addresses.parquet"
    if not _pluto_path.exists():
        pd.concat(
            [
                pd.DataFrame(
                    get(
                        "https://data.cityofnewyork.us/resource/64uk-42ks.json",
                        {
                            "$select": "bbl,address",
                            "$where": "borough='BK'",
                            "$order": "bbl",
                            "$limit": 50000,
                            "$offset": page * 50000,
                        },
                    ).json()
                )
                for page in range(6)
            ],
            ignore_index=True,
        ).to_parquet(_pluto_path)
    _pluto = pd.read_parquet(_pluto_path)
    assert len(_pluto) < 300000, "PLUTO Brooklyn has grown past 6 pages; raise the page count"
    _words = {
        "STREET": "",
        "ST": "",
        "AVENUE": "AV",
        "AVE": "AV",
        "ROAD": "RD",
        "PLACE": "PL",
        "PARKWAY": "PKWY",
        "TERRACE": "TERR",
        "COURT": "CT",
        "BOULEVARD": "BLVD",
        "LANE": "LN",
        "DRIVE": "DR",
        "EAST": "E",
        "WEST": "W",
        "NORTH": "N",
        "SOUTH": "S",
    }

    def street_key(street: str) -> str:
        # The last word keeps E or W as is, so "WEST ST" stays "W" and "AVENUE W" stays "AV W".
        words = street.upper().replace(".", "").split()
        return " ".join(w for w in [_words.get(w, w) for w in words[:-1]] + [_words.get(words[-1], words[-1])] if w)

    _addr = _pluto.dropna().assign(bbl=lambda d: d["bbl"].astype(float).astype("int64").astype(str))
    _parts = _addr["address"].str.extract(r"^(\d+)([A-Z]?)\s+(.*)$").dropna()
    _lookup = pd.Series(
        _addr.loc[_parts.index, "bbl"].to_numpy(), index=_parts[0] + _parts[1] + "|" + _parts[2].map(street_key)
    )
    _lookup = _lookup[~_lookup.index.duplicated()]

    _addresses: list[tuple[str, str, str]] = []
    for _clli, _lines in notice_sections:
        _rows = [line.upper().split() for line in _lines]
        if _rows:
            # The wire center name is the 1 to 3 words that at least 60% of the section's rows start with.
            _prefix_len = max(
                (
                    k
                    for k in (1, 2, 3)
                    if pd.Series([tuple(r[:k]) for r in _rows]).value_counts().iloc[0] >= 0.6 * len(_rows)
                ),
                default=1,
            )
            _prefix = pd.Series([tuple(r[:_prefix_len]) for r in _rows]).value_counts().index[0]
            for _row in _rows:
                if tuple(_row[:_prefix_len]) != _prefix:
                    continue
                _rest = " ".join(_row[_prefix_len:])
                _head = _rest.split(",")[0].split()
                # The first house number is the last word before the first comma, with a letter suffix if any.
                _k = 2 if len(_head) > 2 and len(_head[-1]) == 1 and _head[-1].isalpha() and _head[-2].isdigit() else 1
                _street = " ".join(_head[:-_k])
                for _item in ["".join(_head[-_k:])] + _rest.split(",")[1:]:
                    _m = re.match(r"^\s*(\d+)(?:\s?([A-Z]))?\b", _item)
                    if _m and _street:
                        _addresses.append((_clli, _m.group(1) + (_m.group(2) or ""), _street))
    notice_addresses = pd.DataFrame(_addresses, columns=["clli", "number", "street"]).drop_duplicates()
    notice_addresses["bbl"] = (notice_addresses["number"] + "|" + notice_addresses["street"].map(street_key)).map(
        _lookup
    )
    _per_lot = notice_addresses.dropna(subset=["bbl"]).groupby("bbl")["clli"].nunique()
    telecom_seed_conflicts = int((_per_lot > 1).sum())
    mo.md(
        f"The notices list **{len(notice_addresses):,} Brooklyn addresses**; "
        f"**{notice_addresses['bbl'].notna().mean():.0%}** "
        f"match a PLUTO lot, giving **{len(_per_lot):,} seed lots**. Lots claimed by two wire centers: "
        f"{telecom_seed_conflicts}."
    )
    return notice_addresses, telecom_seed_conflicts


@app.cell
def _(facilities, lots, notice_addresses):
    _seed_clli = notice_addresses.dropna(subset=["bbl"]).drop_duplicates("bbl").set_index("bbl")["clli"]
    seeds = lots[lots["bbl"].isin(_seed_clli.index)].assign(clli=lambda d: d["bbl"].map(_seed_clli)).to_crs(NY_FEET)

    def nearest(points: gpd.GeoDataFrame, targets: gpd.GeoDataFrame) -> pd.DataFrame:
        """The target clli nearest each point, and its distance in feet."""
        joined = gpd.sjoin_nearest(
            points.to_crs(NY_FEET)[["geometry"]], targets[["clli", "geometry"]], how="left", distance_col="feet"
        )
        return joined[~joined.index.duplicated()][["clli", "feet"]].reindex(points.index)

    # Hold out a fifth of the tax blocks (a block is the BBL's first six digits) and predict them from the rest.
    _blocks = seeds["bbl"].str[:6]
    _held = set(np.random.default_rng(63).choice(_blocks.unique(), size=_blocks.nunique() // 5, replace=False))
    _test, _train = seeds[_blocks.isin(_held)], seeds[~_blocks.isin(_held)]
    telecom_holdout_accuracy = float((nearest(_test, _train)["clli"] == _test["clli"]).mean())
    # Baseline: the nearest wire center building.
    _offices = facilities[(facilities["lifeline"] == "telecom") & facilities.geometry.notna()].copy()
    _offices["clli"] = _offices["node"].str.extract(r"\((NYCK\w+)\)")[0]
    _offices = _offices.to_crs(NY_FEET)
    telecom_baseline_accuracy = float((nearest(_test, _offices)["clli"] == _test["clli"]).mean())

    def wire_center(points: gpd.GeoDataFrame) -> pd.DataFrame:
        """Each point's wire center: documented if it is a seed lot, else inferred from the nearest seed."""
        found = nearest(points, seeds)
        found["status"] = np.where(found["feet"] < 1, "documented", "inferred")
        return found

    lot_telecom = wire_center(lots)
    mo.md(
        f"Held-out tax blocks ({len(_test):,} seed lots): nearest seed gives the right wire center for "
        f"**{telecom_holdout_accuracy:.1%}**; the nearest wire center building, for "
        f"**{telecom_baseline_accuracy:.1%}**. "
        f"Every Brooklyn lot: {(lot_telecom['status'] == 'documented').mean():.1%} are seed lots, "
        f"{(lot_telecom['feet'] <= 1000).mean():.1%} are within 1,000 ft of one."
    )
    return lot_telecom, telecom_baseline_accuracy, telecom_holdout_accuracy, wire_center


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. Hazards on every located facility

    The same two measures as the power notebook: the worst FEMA flood zone anywhere on the facility's tax lot,
    and the National Risk Index ratings of its census tract.
    """)
    return


@app.cell
def _(facilities, lifeline_stressors):
    _tracts = nri_tracts()
    _located = facilities.set_index("node")
    lifeline_nodes = _located[["lifeline", "kind", "placed_by"]].join(hazards(_located, "nfhl-lifelines.json", _tracts))
    lifeline_nodes["stressors"] = (
        lifeline_stressors.groupby("node")["stressor"].agg("; ".join).reindex(lifeline_nodes.index)
    )
    lifeline_nodes.reset_index().to_csv(OUT / "lifeline_nodes.csv", index=False)
    lifeline_nodes
    return (lifeline_nodes,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. Coverage by lifeline

    The issue's measures, one row per lifeline: facilities placed, links documented and inferred, and the share
    of Brooklyn lots matched to a serving facility. Power comes from the power notebook's summary.
    """)
    return


@app.cell
def _(facilities, lifeline_links, lot_gas, lot_telecom, lot_wastewater, lots):
    _power = json.loads((OUT / "summary.json").read_text())
    _lots = len(lots)
    _matched = {
        "wastewater": (int(lot_wastewater.notna().sum()), 0, 0),
        "natural gas": (int(lot_gas.notna().sum()), 0, 0),
        "telecom": (
            int((lot_telecom["status"] == "documented").sum()),
            int((lot_telecom["status"] == "inferred").sum()),
            0,
        ),
        "water supply": (0, 0, _lots),
        "refined fuel": (0, 0, _lots),
        "food": (0, 0, _lots),
    }
    _rows = [
        {
            "lifeline": "power",
            "facilities": sum(_power["facilities_by_type"].values()),
            "placed": sum(_power["facilities_by_type"].values()) - len(_power["facilities_not_on_map"]),
            "links documented": _power["links_documented"],
            "links inferred": _power["links_inferred"],
            "lots matched, documented": _power["lots_by_match"].get("network boundary", 0)
            + _power["lots_by_match"].get("overhead feeder", 0),
            "lots matched, inferred": _power["lots_by_match"].get("load area only (inferred)", 0),
            "lots at borough or city level only": 0,
        }
    ]
    for _lifeline, (_doc, _inf, _area) in _matched.items():
        _f = facilities[facilities["lifeline"] == _lifeline]
        _l = lifeline_links[lifeline_links["lifeline"] == _lifeline]["status"].value_counts()
        _rows.append(
            {
                "lifeline": _lifeline,
                "facilities": len(_f),
                "placed": int(_f.geometry.notna().sum()),
                "links documented": int(_l.get("documented", 0)),
                "links inferred": int(_l.get("inferred", 0)),
                "lots matched, documented": _doc,
                "lots matched, inferred": _inf,
                "lots at borough or city level only": _area,
            }
        )
    lifeline_coverage = pd.DataFrame(_rows)
    for _col in ["lots matched, documented", "lots matched, inferred", "lots at borough or city level only"]:
        lifeline_coverage[_col.replace("lots", "share")] = (lifeline_coverage[_col] / _lots).round(3)
    lifeline_coverage.to_csv(OUT / "lifeline_coverage.csv", index=False)
    lifeline_coverage
    return (lifeline_coverage,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 7. The sample parcels, across lifelines

    For each parcel and lifeline we find the first facility (the plant whose drainage area it is in, its gas
    utility, its wire center, or the borough- or city-level node) and walk the links upstream with NetworkX, as
    the power notebook does. Power rows are copied from the power notebook's `upstream_risks.csv`. Within each
    parcel, rows are sorted by lifeline, then worst flood zone, then NRI coastal flooding.
    """)
    return


@app.cell
def _(gas_utility, lifeline_links, lifeline_nodes, lots, wastewater_plant, wire_center):
    parcels = read_parcels(PARCELS, lots)
    _placed = parcels[parcels.geometry.notna()]
    _first = pd.DataFrame(index=parcels.index)
    _first["wastewater"] = wastewater_plant(_placed).reindex(parcels.index)
    _first["natural gas"] = gas_utility(_placed).reindex(parcels.index)
    _wc = wire_center(_placed).reindex(parcels.index)
    _clli_node = {n.split("(")[-1].rstrip(")"): n for n in lifeline_nodes.index if "(NYCK" in n}
    _first["telecom"] = _wc["clli"].map(_clli_node)
    _first.loc[_placed.index, "water supply"] = "Brooklyn water mains"
    _first.loc[_placed.index, "refined fuel"] = "Brooklyn fuel deliveries"
    _first.loc[_placed.index, "food"] = "NYC food outlets"
    _level = {"water supply": "borough level", "refined fuel": "borough level", "food": "city level"}

    _graph = nx.DiGraph()
    for _link in lifeline_links.itertuples():
        _graph.add_edge(_link.supplier, _link.consumer, status=_link.status, source=_link.source)
    _rows: list[dict] = []
    for _i, _parcel in parcels.iterrows():
        for _lifeline in _first.columns:
            _start = _first.loc[_i, _lifeline]
            if not isinstance(_start, str):
                continue
            _how = _level.get(_lifeline) or (_wc.loc[_i, "status"] if _lifeline == "telecom" else "documented")
            _hops = nx.shortest_path_length(_graph.reverse(copy=False), _start) if _start in _graph else {_start: 0}
            for _node, _n in _hops.items():
                # The link from this node one step down its path to the parcel's first facility.
                _next = nx.shortest_path(_graph, _node, _start)[1] if _n else None
                _edge = _graph.edges[_node, _next] if _next else {}
                _rows.append(
                    {
                        "parcel": _parcel["name"],
                        "lifeline": _lifeline,
                        "upstream": _node,
                        "hops": _n + 1,
                        "match": _how,
                        "link_status": _edge.get("status", ""),
                        "link_source": _edge.get("source", ""),
                        **(
                            lifeline_nodes.loc[
                                _node, ["kind", "flood_zone", "nri_overall", "nri_coastal_flood", "stressors"]
                            ].to_dict()
                            if _node in lifeline_nodes.index
                            else {}
                        ),
                    }
                )
    _power = pd.read_csv(OUT / "upstream_risks.csv")
    _power = _power.assign(
        lifeline="power",
        match="see parcels.csv",
        link_status=np.where(_power["chain_documented"], "documented", "inferred"),
        link_source="supply_chain_risk.py",
    )
    all_upstream = pd.concat([_power, pd.DataFrame(_rows)], ignore_index=True)
    all_upstream["flood_rank"] = all_upstream["flood_zone"].map(lambda z: FLOOD_RANK.get(z, -1))
    all_upstream["coastal_rank"] = all_upstream["nri_coastal_flood"].map(
        lambda r: NRI_RATINGS.index(r) if r in NRI_RATINGS else -1
    )
    all_upstream = all_upstream.sort_values(
        ["parcel", "lifeline", "flood_rank", "coastal_rank", "hops"], ascending=[True, True, False, False, True]
    )
    _columns = [
        "parcel",
        "lifeline",
        "upstream",
        "kind",
        "hops",
        "match",
        "link_status",
        "link_source",
        "flood_zone",
        "nri_overall",
        "nri_coastal_flood",
        "stressors",
    ]
    all_upstream = all_upstream[_columns]
    all_upstream.to_csv(OUT / "upstream_risks_all_lifelines.csv", index=False)
    parcel_first = parcels[["name"]].join(_first)
    parcel_first.to_csv(OUT / "parcels_lifelines.csv", index=False)
    mo.vstack([parcel_first, all_upstream])
    return all_upstream, parcel_first, parcels


@app.cell
def _(drainage_areas, facilities, parcels, plant_codes):
    _fig, _ax = plt.subplots(figsize=(10, 10))
    _colours = dict(zip(plant_codes, plt.get_cmap("Pastel1")(range(len(plant_codes))), strict=True))
    for _code, _area in drainage_areas.groupby("WPCP"):
        if _code in plant_codes:
            _area.plot(ax=_ax, color=_colours[_code], alpha=0.6, edgecolor="grey", linewidth=0.4)
    _style = {
        "treatment plant": ("s", "teal"),
        "wire center": ("^", "purple"),
        "bulk fuel terminal": ("D", "darkorange"),
        "LNG storage": ("P", "firebrick"),
        "wholesale food hub": ("*", "darkgreen"),
    }
    _placed = facilities[facilities.geometry.notna()]
    for _kind, (_marker, _colour) in _style.items():
        _pts = _placed[_placed["kind"] == _kind].geometry.representative_point()
        _ax.scatter(_pts.x, _pts.y, marker=_marker, color=_colour, s=70, label=_kind, zorder=3)
    _p = parcels[parcels.geometry.notna()]
    _ax.scatter(
        _p.geometry.x,
        _p.geometry.y,
        marker="o",
        facecolors="none",
        edgecolors="crimson",
        s=140,
        linewidths=1.5,
        label="sample parcel",
        zorder=4,
    )
    _ax.set_xlim(-74.06, -73.83)
    _ax.set_ylim(40.56, 40.75)
    _ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    _ax.set_title("Brooklyn lifelines: DEP drainage areas (shaded by plant) and placed facilities")
    _ax.set_axis_off()
    _fig.savefig(OUT / "lifelines_map.png", dpi=130, bbox_inches="tight")
    _fig
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 8. Where public data has no service-area link

    The counts below come from this run; the README discusses them.
    """)
    return


@app.cell
def _(
    all_upstream,
    lifeline_coverage,
    lifeline_links,
    lifeline_source_check,
    parcel_first,
    telecom_baseline_accuracy,
    telecom_holdout_accuracy,
    telecom_seed_conflicts,
    notice_addresses,
    wastewater_agreement,
):
    no_service_area = [
        "water supply: no public shaft, pressure-zone or trunk-main service areas; tunnels named only for whole "
        "boroughs",
        "refined fuel: which terminal supplies which station or building is commercial and not public",
        "food: no outlet has a single supplier (2016 Food Flow study); no hub has a service area",
        "natural gas (below the utility): which city gate or main feeds which part of Brooklyn is not public",
        "telecom (beyond Verizon wireline): no public link for mobile, cable or other carriers",
    ]
    lifeline_summary = {
        "run_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "coverage": lifeline_coverage.to_dict(orient="records"),
        "links_by_lifeline": pd.crosstab(lifeline_links["lifeline"], lifeline_links["status"]).to_dict(orient="index"),
        "passages": lifeline_source_check["result"].value_counts().to_dict(),
        "passages_not_verified": lifeline_source_check.loc[
            lifeline_source_check["result"] != "verified", ["what", "result"]
        ].to_dict(orient="records"),
        "wastewater_state_layer_agreement": round(wastewater_agreement, 4),
        "telecom_notice_addresses": len(notice_addresses),
        "telecom_addresses_matched": round(float(notice_addresses["bbl"].notna().mean()), 4),
        "telecom_seed_lots": int(notice_addresses["bbl"].nunique()),
        "telecom_seed_conflicts": telecom_seed_conflicts,
        "telecom_holdout_accuracy": round(telecom_holdout_accuracy, 4),
        "telecom_nearest_office_accuracy": round(telecom_baseline_accuracy, 4),
        "no_service_area_link": no_service_area,
        "parcels_placed": int(parcel_first.drop(columns="name").notna().any(axis=1).sum()),
        "upstream_rows_by_lifeline": all_upstream["lifeline"].value_counts().to_dict(),
        "run_seconds": round(time.perf_counter() - RUN_STARTED, 1),
    }
    (OUT / "lifelines_summary.json").write_text(json.dumps(lifeline_summary, indent=2, default=str))
    mo.md(f"```json\n{json.dumps(lifeline_summary, indent=2, default=str)}\n```")
    return (lifeline_summary,)


if __name__ == "__main__":
    app.run()
