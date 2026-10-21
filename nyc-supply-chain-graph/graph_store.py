import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import statistics
    import sys
    import time
    from collections.abc import Callable
    from datetime import UTC, datetime
    from pathlib import Path
    from typing import LiteralString, cast

    import duckdb
    import ladybug
    import marimo as mo
    import neo4j
    import pandas as pd

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("GRAPH_SPIKE_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("GRAPH_SPIKE_OUTPUT_DIR", HERE / "output"))
    APP_DATA = Path(os.environ.get("GRAPH_SPIKE_APP_DATA_DIR", HERE / "app" / "public" / "data"))
    SPIKE_62 = Path(os.environ.get("SUPPLY_CHAIN_SPIKE_DIR", HERE.parent / "nyc-supply-chain-risk"))
    for _dir in (DATA, OUT, APP_DATA):
        _dir.mkdir(parents=True, exist_ok=True)
    # Neo4j runs only when a server is given, for example `docker run -p 7687:7687 neo4j:2026.08-community`.
    NEO4J_URI = os.environ.get("NEO4J_URI", "")
    REPEATS = 20  # each parcel query is timed this many times and the median kept


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Graph database or flat tables for the NYC supply chain risk map?

    Spike [#62](https://github.com/fulton-ring/agent-content-demos/issues/62) mapped Brooklyn's power supply chain
    with FEMA's method: every tax lot, the Con Edison network that serves it, and the substations and plants upstream,
    each with its flood zone, National Risk Index ratings and a public source. It keeps the graph in pandas tables and
    NetworkX. Issue [#65](https://github.com/fulton-ring/agent-content-demos/issues/65) asks two things:

    1. **Would a graph database do this better?** We load the same nodes, links and 275,864 lots into four stores and
       time the load, the per-parcel query and a whole-borough query, check every answer against #62's, and compare
       how readable the queries are and what they cost.
    2. **Can someone who doesn't run Python use it?** The last cell writes the data for a small web app (in `app/`)
       where you type an address or BBL and see the parcel's upstream facilities on a map.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. #62's data

    We run #62's notebook as it is, with its data and output folders pointed into this spike's `data/`, and take its
    tables from the run. So the graph is exactly the one #62 published, and #62's own ranked upstream lists for its
    sample parcels become the answer key every store has to match.
    """)
    return


@app.cell
def _():
    os.environ["SUPPLY_CHAIN_DATA_DIR"] = str(DATA / "spike-62")
    os.environ["SUPPLY_CHAIN_OUTPUT_DIR"] = str(DATA / "spike-62-output")
    sys.path.insert(0, str(SPIKE_62))
    from supply_chain_risk import app as spike_62

    _started = time.perf_counter()
    _, spike = spike_62.run()
    spike_seconds = time.perf_counter() - _started
    mo.md(f"#62's notebook ran in **{spike_seconds:.0f} s**.")
    return spike, spike_seconds


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. The flat tables

    Three tables hold everything a store needs: **nodes** (the 34 networks, substations and plants, with their
    hazards), **links** (supplier → consumer, documented or inferred, and the source), and **lots** (each Brooklyn BBL
    and the network or area substation that serves it). Every store below is loaded from these.
    """)
    return


@app.cell
def _(spike):
    _hazards = spike["node_hazards"]
    nodes = pd.DataFrame({"name": sorted(spike["graph"].nodes)})
    nodes["kind"] = nodes["name"].map(_hazards["kind"]).fillna("network")
    links = spike["documented_links"][["supplier", "consumer", "status", "source", "passage"]].reset_index(drop=True)
    lots = pd.DataFrame({"bbl": spike["lots"]["bbl"], "served_by": spike["lot_service"]["served_by"]})
    lots["match"] = spike["lot_service"]["match"]
    lots = lots[lots["served_by"].notna()].reset_index(drop=True)
    # Every lot's first node must be in the graph, or the stores would silently drop it.
    assert set(lots["served_by"]) <= set(nodes["name"]), set(lots["served_by"]) - set(nodes["name"])
    for _name, _table in {"nodes": nodes, "links": links, "lots": lots}.items():
        _table.to_parquet(DATA / f"{_name}.parquet")
    mo.md(
        f"**{len(nodes)} nodes, {len(links)} links, {len(lots):,} lots** with a first node "
        f"({lots['served_by'].nunique()} distinct first nodes). Flat files: "
        + ", ".join(f"`{p.name}` {p.stat().st_size / 1e6:.1f} MB" for p in sorted(DATA.glob("*.parquet")))
    )
    return links, lots, nodes


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. The answer key and what each store must return

    For a lot's first node `f` (its network, or its area substation if it is matched by overhead feeder), #62 lists
    every facility upstream of `f` with three facts that come from the graph:

    - **hops**: the shortest number of links to `f`, plus one (the first node itself is hop 1);
    - **direct**: whether it is upstream on the radial supply chain, leaving out the 345 kV ties (`nyiso-bps` links);
    - **documented**: whether it reaches `f` on documented links alone.

    Each store answers that with one query. Ranking the rows (by flood zone, then NRI coastal flooding, then NRI
    score) is a sort on node attributes, not a graph question, so it is done the same way for every store, below.
    A result passes only if every row and every rank equals #62's.

    One trap caught three of the five stores on the first run: the 3 inferred links have no source, and in SQL and
    Cypher `source <> 'nyiso-bps'` is null, not true, when the source is missing. The inferred links then fell out of
    the radial chain. The queries below say `IS DISTINCT FROM` or `coalesce` for that reason.
    """)
    return


@app.cell
def _(lots, spike):
    _status = spike["parcel_status"].dropna(subset=["served_by"])
    answer_key = spike["upstream"].merge(_status[["name", "bbl", "served_by"]], left_on="parcel", right_on="name")
    answer_key = answer_key[["parcel", "bbl", "served_by", "upstream", "hops", "path", "chain_documented", "rank"]]
    # The parcels given by BBL are the ones the per-parcel query looks up; the Canarsie point has no BBL.
    sample_bbls = [b for b in _status["bbl"].dropna() if b in set(lots["bbl"])]
    _node_hazards = spike["node_hazards"]
    _flood_rank = spike["flood_rank"]
    _ratings = ["Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High"]

    def rank_rows(result: pd.DataFrame, firsts: list[str]) -> pd.DataFrame:
        """A store's (first, upstream, hops, direct, documented) rows and the first node itself, ranked like #62."""
        _self = pd.DataFrame({"first": firsts, "upstream": firsts, "hops": 1, "direct": True, "documented": True})
        rows = pd.concat([_self, result[result["first"].isin(firsts)]], ignore_index=True)
        rows = rows.join(_node_hazards.drop(columns=["kind", "osm_name"]), on="upstream")
        rows["kind"] = rows["upstream"].map(_node_hazards["kind"]).fillna("network")
        rows["path"] = rows["direct"].map({True: "direct supply", False: "345 kV tie"})
        rows["flood_rank"] = rows["flood_zone"].map(lambda z: _flood_rank.get(z, -1))
        rows["coastal_rank"] = rows["nri_coastal_flood"].map(lambda r: _ratings.index(r) if r in _ratings else -1)
        rows = rows.sort_values(
            ["first", "direct", "flood_rank", "coastal_rank", "nri_score", "hops", "upstream"],
            ascending=[True, False, False, False, False, True, True],
        )
        rows["rank"] = rows.groupby("first").cumcount() + 1
        return rows.drop(columns=["flood_rank", "coastal_rank"]).reset_index(drop=True)

    def matches_key(result: pd.DataFrame) -> bool:
        """True if the ranked rows for the sample parcels' first nodes equal #62's rows exactly."""
        ranked = rank_rows(result, sorted(set(answer_key["served_by"])))
        ranked = ranked.rename(columns={"first": "served_by", "documented": "chain_documented"})
        mine = answer_key[["parcel", "served_by"]].drop_duplicates().merge(ranked, on="served_by")
        columns = ["parcel", "upstream", "hops", "path", "chain_documented", "rank"]
        theirs = answer_key[columns].sort_values(["parcel", "rank"]).reset_index(drop=True)
        mine = mine[columns].sort_values(["parcel", "rank"]).reset_index(drop=True)
        return mine.astype(str).equals(theirs.astype(str))

    concentration_key = spike["concentration"].set_index("node")["lots"].sort_index()

    def matches_concentration(counts: pd.Series) -> bool:
        """True if the lots behind each facility equal #62's concentration table."""
        return counts.astype(int).sort_index().equals(concentration_key.astype(int))

    mo.md(f"Answer key: **{len(answer_key)} rows** for {answer_key['parcel'].nunique()} sample parcels.")
    return answer_key, matches_concentration, matches_key, rank_rows, sample_bbls


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. Timing

    Each store is timed on the same three jobs:

    - **load**: build the store from the flat tables (nodes, links and all lots);
    - **one parcel**: given a BBL, return its upstream rows (the app's query), the median of 20 runs over the sample
      BBLs;
    - **whole borough**: the lots behind every facility on the radial chain (#62's concentration table, FEMA Phase 2).

    Every query's text is kept so we can count it and show it.
    """)
    return


@app.cell
def _(matches_concentration, matches_key, sample_bbls):
    def measure(
        store: str,
        load: Callable[[], None],
        all_upstream: Callable[[], pd.DataFrame],
        parcel_upstream: Callable[[str], pd.DataFrame],
        concentration: Callable[[], pd.Series],
        query_text: str,
        size_bytes: Callable[[], int | None],
    ) -> dict:
        """Load a store, run its three queries, check them against #62 and return one row of the comparison."""
        started = time.perf_counter()
        load()
        load_s = time.perf_counter() - started
        result = all_upstream()
        timings = []
        for bbl in sample_bbls * REPEATS:
            started = time.perf_counter()
            one = parcel_upstream(bbl)
            timings.append(time.perf_counter() - started)
            assert len(one) > 0, f"{store} found nothing upstream of {bbl}"
        started = time.perf_counter()
        counts = concentration()
        borough_s = time.perf_counter() - started
        size = size_bytes()
        return {
            "store": store,
            "load_s": round(load_s, 3),
            "one_parcel_ms": round(statistics.median(timings) * 1000, 2),
            "whole_borough_s": round(borough_s, 3),
            "matches_62_upstream": matches_key(result),
            "matches_62_concentration": matches_concentration(counts),
            "query_lines": len([line for line in query_text.strip().splitlines() if line.strip()]),
            "on_disk_mb": None if size is None else round(size / 1e6, 1),
            "result": result,
            "query_text": query_text,
        }

    return (measure,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5a. Flat tables in pandas and NetworkX (what #62 does)

    The baseline. NetworkX keeps the graph in memory and pandas looks up the lot. Three NetworkX calls answer the
    upstream question: shortest path lengths on the full graph, ancestors on the radial graph, ancestors on the
    documented graph.
    """)
    return


@app.cell
def _(links, lots, measure, nodes):
    import networkx as nx

    _store: dict = {}
    networkx_query = """
    tier = nx.shortest_path_length(full.reverse(copy=False), first)
    direct = nx.ancestors(radial, first)
    documented = nx.ancestors(documented_graph, first) if first in documented_graph else set()
    """

    def _load() -> None:
        _store["lots"] = lots.set_index("bbl")["served_by"]
        full = nx.DiGraph()
        full.add_nodes_from(nodes["name"])
        full.add_edges_from(zip(links["supplier"], links["consumer"], strict=True))
        _radial = links[links["source"] != "nyiso-bps"]
        _documented = links[links["status"] == "documented"]
        _store["full"] = full
        _store["radial"] = full.edge_subgraph(zip(_radial["supplier"], _radial["consumer"], strict=True))
        _store["documented"] = full.edge_subgraph(zip(_documented["supplier"], _documented["consumer"], strict=True))

    def _upstream(first: str) -> list[dict]:
        tier = nx.shortest_path_length(_store["full"].reverse(copy=False), first)
        direct = nx.ancestors(_store["radial"], first) if first in _store["radial"] else set()
        documented = nx.ancestors(_store["documented"], first) if first in _store["documented"] else set()
        return [
            {"first": first, "upstream": n, "hops": h + 1, "direct": n in direct, "documented": n in documented}
            for n, h in tier.items()
            if n != first
        ]

    def _all() -> pd.DataFrame:
        return pd.DataFrame([row for first in nodes["name"] for row in _upstream(first)])

    def _concentration() -> pd.Series:
        _per_first = _store["lots"].value_counts()
        _counts: dict[str, int] = {}
        for first, n in _per_first.items():
            for node in (nx.ancestors(_store["radial"], first) if first in _store["radial"] else set()) | {first}:
                _counts[node] = _counts.get(node, 0) + int(n)
        return pd.Series(_counts)

    networkx_row = measure(
        "pandas + NetworkX (#62)",
        _load,
        _all,
        lambda bbl: pd.DataFrame(_upstream(_store["lots"][bbl])),
        _concentration,
        networkx_query,
        lambda: None,
    )
    {k: v for k, v in networkx_row.items() if k not in ("result", "query_text")}
    return (networkx_row,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5b. Flat tables in DuckDB, with a recursive query

    The same three tables in a DuckDB file, and plain SQL: a recursive common table expression walks the links
    upstream from every node, carrying whether the walk so far used only radial links and only documented links. A
    list of visited nodes stops it going round the 345 kV loop between Farragut and Gowanus.
    """)
    return


@app.cell
def _(measure):
    duckdb_query = """
    WITH RECURSIVE walk(first, node, hops, direct, documented, visited) AS (
        SELECT name, name, 1, true, true, [name] FROM nodes
        UNION ALL
        SELECT w.first, l.supplier, w.hops + 1, w.direct AND l.source IS DISTINCT FROM 'nyiso-bps',
               w.documented AND l.status = 'documented', list_append(w.visited, l.supplier)
        FROM walk w JOIN links l ON l.consumer = w.node
        WHERE NOT list_contains(w.visited, l.supplier) AND w.hops < 12
    )
    SELECT first, node AS upstream, min(hops) AS hops, bool_or(direct) AS direct, bool_or(documented) AS documented
    FROM walk WHERE node <> first GROUP BY first, node
    """
    _path = DATA / "flat.duckdb"
    _path.unlink(missing_ok=True)
    _con = duckdb.connect(_path)

    def _load() -> None:
        for _name in ("nodes", "links", "lots"):
            _con.execute(f"CREATE TABLE {_name} AS FROM read_parquet('{DATA / _name}.parquet')")
        _con.execute(f"CREATE VIEW upstream AS {duckdb_query}")

    def _parcel(bbl: str) -> pd.DataFrame:
        _sql = "FROM upstream WHERE first = (SELECT served_by FROM lots WHERE bbl = ?)"
        return _con.execute(_sql, [bbl]).df()

    def _concentration() -> pd.Series:
        _sql = """
        WITH per_first AS (SELECT served_by AS first, count(*) AS lots FROM lots GROUP BY ALL),
             behind AS (SELECT first, upstream FROM upstream WHERE direct UNION ALL SELECT first, first FROM per_first)
        SELECT upstream, sum(lots)::BIGINT AS lots FROM behind JOIN per_first USING (first) GROUP BY upstream
        """
        return _con.execute(_sql).df().set_index("upstream")["lots"]

    duckdb_row = measure(
        "DuckDB, recursive SQL",
        _load,
        lambda: _con.execute("FROM upstream").df(),
        _parcel,
        _concentration,
        duckdb_query,
        lambda: _path.stat().st_size,
    )
    duckdb_con = _con
    {k: v for k, v in duckdb_row.items() if k not in ("result", "query_text")}
    return duckdb_con, duckdb_row


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5c. DuckDB with DuckPGQ (SQL/PGQ graph queries)

    [DuckPGQ](https://duckdb.org/community_extensions/extensions/duckpgq) adds the SQL:2023 property graph syntax to
    DuckDB: `CREATE PROPERTY GRAPH` over existing tables, then `MATCH` patterns. It has no build for DuckDB 1.5 yet,
    so this spike pins DuckDB 1.4.4. We found no way to filter edges inside a repeated pattern, so the radial and
    documented links become their own edge tables with their own labels. Two bugs shaped the query: `path_length(p)
    + 1` inside `COLUMNS` is a syntax error, and joining two `GRAPH_TABLE`s in one query crashed DuckDB (a
    segmentation fault, then an internal assertion). So each match goes into its own temporary table first.
    """)
    return


@app.cell
def _(measure):
    duckpgq_query = """
    CREATE OR REPLACE TEMP TABLE reach_rows AS FROM GRAPH_TABLE (supply
        MATCH p = ANY SHORTEST (u:nodes)-[e:feeds]->{1,12}(f:nodes WHERE {first})
        COLUMNS (f.name AS first, u.name AS upstream, path_length(p) AS links));
    CREATE OR REPLACE TEMP TABLE direct_rows AS FROM GRAPH_TABLE (supply
        MATCH p = ANY SHORTEST (u:nodes)-[e:radial]->{1,12}(f:nodes WHERE {first})
        COLUMNS (f.name AS first, u.name AS upstream));
    CREATE OR REPLACE TEMP TABLE documented_rows AS FROM GRAPH_TABLE (supply
        MATCH p = ANY SHORTEST (u:nodes)-[e:documented]->{1,12}(f:nodes WHERE {first})
        COLUMNS (f.name AS first, u.name AS upstream));
    SELECT first, upstream, links + 1 AS hops, d.first IS NOT NULL AS direct, doc.first IS NOT NULL AS documented
    FROM reach_rows LEFT JOIN direct_rows d USING (first, upstream)
        LEFT JOIN documented_rows doc USING (first, upstream)
    """
    # In memory: on a database file, DuckPGQ hit a fatal internal error in about one run in ten (see the README).
    _con = duckdb.connect()
    _con.execute("INSTALL duckpgq FROM community; LOAD duckpgq;")

    def _load() -> None:
        _con.execute(f"CREATE TABLE nodes AS FROM read_parquet('{DATA}/nodes.parquet')")
        _con.execute(f"CREATE TABLE lots AS FROM read_parquet('{DATA}/lots.parquet')")
        _links = f"read_parquet('{DATA}/links.parquet')"
        _con.execute(f"CREATE TABLE feeds AS FROM {_links}")
        _con.execute(f"CREATE TABLE radial AS FROM {_links} WHERE source IS DISTINCT FROM 'nyiso-bps'")
        _con.execute(f"CREATE TABLE documented AS FROM {_links} WHERE status = 'documented'")
        _edges = ", ".join(
            f"{t} SOURCE KEY (supplier) REFERENCES nodes (name) DESTINATION KEY (consumer) REFERENCES nodes (name) "
            f"LABEL {t}"
            for t in ("feeds", "radial", "documented")
        )
        _con.execute(f"CREATE PROPERTY GRAPH supply VERTEX TABLES (nodes) EDGE TABLES ({_edges})")

    def _upstream(first: str) -> pd.DataFrame:
        """Run the statements with `first` as the filter on f; only the last one returns rows."""
        *_tables, _select = duckpgq_query.replace("{first}", first).split(";")
        for _statement in _tables:
            _con.execute(_statement)
        return _con.execute(_select).df()

    def _parcel(bbl: str) -> pd.DataFrame:
        _row = _con.execute("SELECT served_by FROM lots WHERE bbl = ?", [bbl]).fetchone()
        assert _row is not None, bbl
        return _upstream("f.name = '" + _row[0].replace("'", "''") + "'")

    def _concentration() -> pd.Series:
        _upstream("true")
        _sql = """
        WITH per_first AS (SELECT served_by AS first, count(*) AS lots FROM lots GROUP BY ALL),
             behind AS (SELECT first, upstream FROM direct_rows UNION ALL SELECT first, first FROM per_first)
        SELECT upstream, sum(lots)::BIGINT AS lots FROM behind JOIN per_first USING (first) GROUP BY upstream
        """
        return _con.execute(_sql).df().set_index("upstream")["lots"]

    # If DuckPGQ fails with an internal error, DuckDB refuses the database afterwards; record it and go on.
    try:
        duckpgq_row = measure(
            "DuckDB + DuckPGQ",
            _load,
            lambda: _upstream("true"),
            _parcel,
            _concentration,
            duckpgq_query,
            lambda: None,
        )
    except duckdb.Error as _error:
        duckpgq_row = {"store": "DuckDB + DuckPGQ", "error": str(_error).splitlines()[0][:160], "query_text": ""}
    _con.close()
    {k: v for k, v in duckpgq_row.items() if k not in ("result", "query_text")}
    return (duckpgq_row,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5d. LadybugDB (the fork of Kùzu), embedded, in Cypher

    Kùzu was the embedded graph database most often suggested for this, but its company archived the project in
    October 2025 (last release 0.11.3). [LadybugDB](https://github.com/LadybugDB/ladybug) is the maintained fork,
    with the same Cypher dialect. Lots become `Lot` nodes with a `SERVED_BY` link to their first node, so one query
    goes from a BBL to everything upstream. Edges can be filtered inside a variable-length pattern.
    """)
    return


@app.cell
def _(links, lots, measure, nodes):
    ladybug_query = """
    MATCH p = (u:Node)-[:FEEDS* SHORTEST 1..12]->(f:Node)
    RETURN f.name AS first, u.name AS upstream, length(p) + 1 AS hops,
      EXISTS { MATCH (u)-[:FEEDS*1..12 (e, n | WHERE coalesce(e.source, '') <> 'nyiso-bps')]->(f) } AS direct,
      EXISTS { MATCH (u)-[:FEEDS*1..12 (e, n | WHERE e.status = 'documented')]->(f) } AS documented
    """
    _path = DATA / "ladybug.lbug"
    _path.unlink(missing_ok=True)
    _con = ladybug.Connection(ladybug.Database(str(_path)))

    def _query(cypher: str, params: dict | None = None) -> pd.DataFrame:
        result = _con.execute(cypher, params or {})
        assert isinstance(result, ladybug.QueryResult), "one statement gives one result"
        return result.get_as_df()

    def _load() -> None:
        _con.execute("CREATE NODE TABLE Node(name STRING PRIMARY KEY, kind STRING)")
        _con.execute("CREATE NODE TABLE Lot(bbl STRING PRIMARY KEY, match STRING)")
        _con.execute("CREATE REL TABLE FEEDS(FROM Node TO Node, status STRING, source STRING)")
        _con.execute("CREATE REL TABLE SERVED_BY(FROM Lot TO Node)")
        # COPY reads a pandas DataFrame named in the query; the first two columns of a link table are its ends.
        _node_rows = nodes[["name", "kind"]]
        _lot_rows = lots[["bbl", "match"]]
        _feeds = links[["supplier", "consumer", "status", "source"]]
        _served = lots[["bbl", "served_by"]]
        for _table, _frame in (("Node", "_node_rows"), ("Lot", "_lot_rows"), ("FEEDS", "_feeds")):
            _con.execute(f"COPY {_table} FROM {_frame}")
        _con.execute("COPY SERVED_BY FROM _served")

    def _parcel(bbl: str) -> pd.DataFrame:
        _sql = "MATCH (:Lot {bbl: $bbl})-[:SERVED_BY]->(f:Node) WITH f " + ladybug_query.replace("(f:Node)", "(f)", 1)
        return _query(_sql, {"bbl": bbl})

    def _concentration() -> pd.Series:
        _sql = """
        MATCH (:Lot)-[:SERVED_BY]->(f:Node) WITH f, count(*) AS lots
        MATCH (u:Node)-[:FEEDS*0..12 (e, n | WHERE coalesce(e.source, '') <> 'nyiso-bps')]->(f)
        WITH DISTINCT u, f, lots RETURN u.name AS upstream, sum(lots) AS lots
        """
        return _query(_sql).set_index("upstream")["lots"]

    ladybug_row = measure(
        "LadybugDB (Kùzu fork)",
        _load,
        lambda: _query(ladybug_query),
        _parcel,
        _concentration,
        ladybug_query,
        lambda: sum(p.stat().st_size for p in DATA.glob("ladybug.lbug*")),
    )
    {k: v for k, v in ladybug_row.items() if k not in ("result", "query_text")}
    return (ladybug_row,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5e. Neo4j Community, a server, in Cypher

    The best-known graph database. It runs as a separate server (Java), so this cell runs only when `NEO4J_URI` is
    set; the README says how to start one. Neo4j's newer GQL syntax writes the radial and documented filters inside
    the repeated pattern. Lots go in through the Python driver in batches of 10,000.
    """)
    return


@app.cell
def _(links, lots, measure, nodes):
    neo4j_query = """
    MATCH p = SHORTEST 1 (u:Node)-[:FEEDS]->+(f:Node)
    RETURN f.name AS first, u.name AS upstream, length(p) + 1 AS hops,
      EXISTS { (u) (()-[e:FEEDS WHERE coalesce(e.source, '') <> 'nyiso-bps']->())+ (f) } AS direct,
      EXISTS { (u) (()-[e:FEEDS WHERE e.status = 'documented']->())+ (f) } AS documented
    """
    neo4j_row: dict | None = None
    if NEO4J_URI:
        _auth = (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", ""))
        _driver = neo4j.GraphDatabase.driver(NEO4J_URI, auth=_auth)
        _driver.verify_connectivity()

        def _run(cypher: str, **params: object) -> pd.DataFrame:
            # The driver asks for literal query text; every query here is built from literals in this cell.
            return _driver.execute_query(cast(LiteralString, cypher), params, result_transformer_=neo4j.Result.to_df)

        def _load() -> None:
            _run("MATCH (n) DETACH DELETE n")
            _run("CREATE CONSTRAINT lot_bbl IF NOT EXISTS FOR (l:Lot) REQUIRE l.bbl IS UNIQUE")
            _run("CREATE CONSTRAINT node_name IF NOT EXISTS FOR (n:Node) REQUIRE n.name IS UNIQUE")
            _run("UNWIND $rows AS r CREATE (:Node {name: r.name, kind: r.kind})", rows=nodes.to_dict("records"))
            _run(
                "UNWIND $rows AS r MATCH (a:Node {name: r.supplier}), (b:Node {name: r.consumer}) "
                "CREATE (a)-[:FEEDS {status: r.status, source: r.source}]->(b)",
                rows=links.drop(columns="passage").astype(object).where(links.notna(), None).to_dict("records"),
            )
            _batch = 10_000
            for _start in range(0, len(lots), _batch):
                _run(
                    "UNWIND $rows AS r MATCH (f:Node {name: r.served_by}) "
                    "CREATE (:Lot {bbl: r.bbl, match: r.match})-[:SERVED_BY]->(f)",
                    rows=lots.iloc[_start : _start + _batch].to_dict("records"),
                )

        def _parcel(bbl: str) -> pd.DataFrame:
            _sql = "MATCH (:Lot {bbl: $bbl})-[:SERVED_BY]->(f:Node) WITH f " + neo4j_query.replace("(f:Node)", "(f)", 1)
            return _run(_sql, bbl=bbl)

        def _concentration() -> pd.Series:
            _sql = """
            MATCH (:Lot)-[:SERVED_BY]->(f:Node) WITH f, count(*) AS lots
            MATCH (u:Node) (()-[e:FEEDS WHERE coalesce(e.source, '') <> 'nyiso-bps']->())* (f)
            WITH DISTINCT u, f, lots RETURN u.name AS upstream, sum(lots) AS lots
            """
            return _run(_sql).set_index("upstream")["lots"]

        neo4j_row = measure(
            "Neo4j Community",
            _load,
            lambda: _run(neo4j_query),
            _parcel,
            _concentration,
            neo4j_query,
            lambda: None,
        )
        _driver.close()
    mo.md("Neo4j: " + ("measured." if neo4j_row else "not run (set `NEO4J_URI` and `NEO4J_PASSWORD`)."))
    return (neo4j_row,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. The comparison

    All four run free on a laptop. The hosted versions are where the cost differs: Neo4j's free cloud tier
    (AuraDB Free) stops at 200,000 nodes and 400,000 relationships, fewer nodes than Brooklyn's lots alone, while the
    flat tables are three Parquet files that a static web page can serve.
    """)
    return


@app.cell
def _(duckdb_row, duckpgq_row, ladybug_row, networkx_row, neo4j_row):
    _rows = [r for r in (networkx_row, duckdb_row, duckpgq_row, ladybug_row, neo4j_row) if r]
    comparison = pd.DataFrame([{k: v for k, v in r.items() if k not in ("result", "query_text")} for r in _rows])
    comparison.to_csv(OUT / "comparison.csv", index=False)
    (OUT / "queries.md").write_text(
        "\n\n".join(f"## {r['store']}\n\n```\n{r['query_text'].strip()}\n```" for r in _rows) + "\n"
    )
    mo.vstack(
        [
            comparison,
            mo.md("The upstream query in each store (also in `output/queries.md`):"),
            mo.hstack([mo.md(f"**{r['store']}**\n```\n{r['query_text'].strip()}\n```") for r in _rows], wrap=True),
        ]
    )
    return (comparison,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 7. Recommendation

    **No graph database, for this map.** The graph is 34 nodes and 32 links; the 275,864 lots hang off it one link
    each. Every store returns #62's answers, and the per-parcel query takes well under 0.1 s in all of them, so speed
    doesn't decide it. What decides it:

    - **The question is always the same and the answers are few.** There are only as many distinct upstream lists as
      there are first nodes, so they can be computed once and looked up. The app below does exactly that, with no
      database at all.
    - **The graph stores are harder to run and to keep.** Kùzu, the obvious embedded choice, was archived in 2025;
      its fork works but is young. DuckPGQ pins DuckDB to an older release and couldn't filter edges inside a
      pattern. Neo4j needs a Java server, and its free cloud tier is smaller than Brooklyn.
    - **Cypher reads best for paths, SQL is fine.** The Cypher queries are the shortest and closest to the question
      ("everything that feeds f"). The recursive SQL is longer but uses the tables #62 already has.

    A graph store starts to pay when the graph itself grows: all five boroughs and several lifelines (#63, #64), with
    links between lifelines (a pumping station that needs power, a substation that needs water for cooling) and
    questions that aren't known in advance. That is what [Seer.ai](https://www.seer.ai/)'s commercial platform does
    and these open options don't: it fuses subscribed proprietary data (commodities, energy infrastructure, hazards)
    into one queryable layer and keeps it current. Its data isn't public, so it can't back a reproducible demo.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 8. Data for the app

    The app needs three things: every Brooklyn BBL and its first node, the ranked upstream list for each first node,
    and each facility's location, hazards and sources. We write them as JSON from the DuckDB results, ranked the same
    way as above, and check once more that the sample parcels give #62's lists.
    """)
    return


@app.cell
def _(answer_key, duckdb_con, duckdb_row, links, lots, rank_rows, spike):
    _firsts = sorted(set(lots["served_by"]))
    _ranked = rank_rows(duckdb_row["result"], _firsts)
    _columns = ["upstream", "kind", "hops", "path", "documented", "flood_zone", "nri_overall", "nri_coastal_flood"]
    _columns += ["nri_heat_wave", "stressors", "rank"]
    _upstream = {
        first: json.loads(group[_columns].to_json(orient="records")) for first, group in _ranked.groupby("first")
    }
    # The facility's footprint centre, for the map; three facilities have no footprint (see #62).
    _footprints = spike["facility_nodes"].set_index("node").geometry
    _centres = _footprints[_footprints.notna()].representative_point()
    _documents = {key: {"title": title, "url": url} for key, (title, url) in spike["documents"].items()}
    _stressors = spike["stressors"][["node", "stressor", "source", "passage"]]
    _graph = {
        "run_date": datetime.now(UTC).date().isoformat(),
        "locations": {name: [round(p.x, 6), round(p.y, 6)] for name, p in _centres.items()},
        "links": json.loads(links.to_json(orient="records")),
        "stressors": json.loads(_stressors.to_json(orient="records")),
        "documents": _documents,
        "upstream": _upstream,
    }
    (APP_DATA / "graph.json").write_text(json.dumps(_graph))
    # Lots as {bbl: [first index, match index]}: about 4 MB, so the app needs no server.
    _match = sorted(set(lots["match"]))
    _lots = {
        "firsts": _firsts,
        "matches": _match,
        "lots": {
            b: [_firsts.index(f), _match.index(m)] for b, f, m in lots[["bbl", "served_by", "match"]].itertuples(False)
        },
    }
    (APP_DATA / "lots.json").write_text(json.dumps(_lots, separators=(",", ":")))
    # The answer key again, from the files the app reads.
    _app_rows = [
        {"parcel": p, "upstream": r["upstream"], "rank": r["rank"]}
        for p, first in answer_key[["parcel", "served_by"]].drop_duplicates().itertuples(False)
        for r in _upstream[first]
    ]
    _app_check = pd.DataFrame(_app_rows).sort_values(["parcel", "rank"]).reset_index(drop=True)
    _key = answer_key[["parcel", "upstream", "rank"]].sort_values(["parcel", "rank"]).reset_index(drop=True)
    app_matches_62 = _app_check.equals(_key)
    # The app's browser test (app/tests) reads the answer key from here.
    answer_key.to_csv(OUT / "answer_key.csv", index=False)
    answer_key.to_json(OUT / "answer_key.json", orient="records", indent=1)
    duckdb_con.close()
    mo.md(
        f"Wrote `graph.json` ({(APP_DATA / 'graph.json').stat().st_size / 1e3:.0f} kB) and `lots.json` "
        f"({(APP_DATA / 'lots.json').stat().st_size / 1e6:.1f} MB). Sample parcels in the app data equal #62's lists: "
        f"**{app_matches_62}**."
    )
    return (app_matches_62,)


@app.cell
def _(app_matches_62, comparison, spike_seconds):
    summary = {
        "run_date": datetime.now(UTC).date().isoformat(),
        "spike_62_seconds": round(spike_seconds, 1),
        "app_data_matches_62": app_matches_62,
        "comparison": json.loads(comparison.to_json(orient="records")),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    summary
    return


if __name__ == "__main__":
    app.run()
