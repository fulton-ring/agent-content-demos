## pandas + NetworkX (#62)

```
tier = nx.shortest_path_length(full.reverse(copy=False), first)
direct = nx.ancestors(radial, first)
documented = nx.ancestors(documented_graph, first) if first in documented_graph else set()
```

## DuckDB, recursive SQL

```
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
```

## DuckDB + DuckPGQ

```
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
```

## LadybugDB (Kùzu fork)

```
MATCH p = (u:Node)-[:FEEDS* SHORTEST 1..12]->(f:Node)
RETURN f.name AS first, u.name AS upstream, length(p) + 1 AS hops,
  EXISTS { MATCH (u)-[:FEEDS*1..12 (e, n | WHERE coalesce(e.source, '') <> 'nyiso-bps')]->(f) } AS direct,
  EXISTS { MATCH (u)-[:FEEDS*1..12 (e, n | WHERE e.status = 'documented')]->(f) } AS documented
```

## Neo4j Community

```
MATCH p = SHORTEST 1 (u:Node)-[:FEEDS]->+(f:Node)
RETURN f.name AS first, u.name AS upstream, length(p) + 1 AS hops,
  EXISTS { (u) (()-[e:FEEDS WHERE coalesce(e.source, '') <> 'nyiso-bps']->())+ (f) } AS direct,
  EXISTS { (u) (()-[e:FEEDS WHERE e.status = 'documented']->())+ (f) } AS documented
```
