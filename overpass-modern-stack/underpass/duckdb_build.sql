-- Builds the Parquet tables the DuckDB views read, from the extract and QuackOSM's output.
-- Placeholders: {pbf} (the extract), {quackosm} (QuackOSM's GeoParquet), {out} (output directory).
-- Raw elements come from DuckDB's ST_ReadOSM; way and relation geometry is assembled here;
-- area polygons come from QuackOSM, which already assembles multipolygons.
LOAD spatial;

CREATE TEMP TABLE raw AS SELECT * FROM ST_ReadOSM('{pbf}') WHERE kind IN ('node', 'way', 'relation');

CREATE TEMP TABLE nodes AS
SELECT id, tags, ST_Point(lon, lat) AS geom FROM raw WHERE kind = 'node';

-- A way's geometry is the line through its nodes, in order, as Overpass sees it (never a polygon).
CREATE TEMP TABLE way_points AS
SELECT wn.id, wn.pos, n.geom
FROM (SELECT id, UNNEST(refs) AS ref, generate_subscripts(refs, 1) AS pos FROM raw WHERE kind = 'way') AS wn
JOIN nodes AS n ON n.id = wn.ref;

CREATE TEMP TABLE ways AS
SELECT w.id, w.tags, w.refs AS nodes, g.geom
FROM raw AS w
JOIN (SELECT id, ST_MakeLine(list(geom ORDER BY pos)) AS geom FROM way_points GROUP BY id HAVING count(*) >= 2) AS g
    USING (id)
WHERE w.kind = 'way';

-- A relation's members in Overpass's JSON shape, and its geometry as the collection of its members'.
CREATE TEMP TABLE members AS
SELECT id, UNNEST(ref_types)::VARCHAR AS type, UNNEST(refs) AS ref, coalesce(UNNEST(ref_roles), '') AS role,
       generate_subscripts(refs, 1) AS pos
FROM raw WHERE kind = 'relation';

CREATE TEMP TABLE member_geoms AS
SELECT id, ST_Collect(list(geom)) AS geom
FROM (
    SELECT m.id, n.geom FROM members AS m JOIN nodes AS n ON m.type = 'node' AND n.id = m.ref
    UNION ALL
    SELECT m.id, w.geom FROM members AS m JOIN ways AS w ON m.type = 'way' AND w.id = m.ref
)
GROUP BY id;

CREATE TEMP TABLE relations AS
SELECT r.id, r.tags, l.members, g.geom
FROM raw AS r
LEFT JOIN (
    SELECT id, list({'type': type, 'ref': ref, 'role': role} ORDER BY pos) AS members FROM members GROUP BY id
) AS l USING (id)
LEFT JOIN member_geoms AS g USING (id)
WHERE r.kind = 'relation';

-- Areas: QuackOSM's polygons for closed ways and multipolygon/boundary relations (area id = relation id + 3600000000).
CREATE TEMP TABLE areas AS
SELECT
    split_part(feature_id, '/', 2)::BIGINT + CASE WHEN feature_id LIKE 'relation/%' THEN 3600000000 ELSE 0 END AS id,
    tags, geometry AS geom,
    CASE WHEN feature_id LIKE 'relation/%' THEN 'a' ELSE 'w' END AS osm_type
FROM read_parquet('{quackosm}')
WHERE feature_id NOT LIKE 'node/%' AND ST_GeometryType(geometry) IN ('POLYGON', 'MULTIPOLYGON');

-- Write each table sorted along a Hilbert curve, with a bbox struct, so Parquet row-group stats prune spatial filters.
COPY (
    SELECT *, {'xmin': ST_XMin(geom), 'ymin': ST_YMin(geom), 'xmax': ST_XMax(geom), 'ymax': ST_YMax(geom)} AS bbox
    FROM nodes ORDER BY ST_Hilbert(geom, ST_Extent(ST_MakeEnvelope(-180, -90, 180, 90)))
) TO '{out}/nodes.parquet' (FORMAT parquet, COMPRESSION zstd);
COPY (
    SELECT *, {'xmin': ST_XMin(geom), 'ymin': ST_YMin(geom), 'xmax': ST_XMax(geom), 'ymax': ST_YMax(geom)} AS bbox
    FROM ways ORDER BY ST_Hilbert(geom, ST_Extent(ST_MakeEnvelope(-180, -90, 180, 90)))
) TO '{out}/ways.parquet' (FORMAT parquet, COMPRESSION zstd);
COPY (
    SELECT *, {'xmin': ST_XMin(geom), 'ymin': ST_YMin(geom), 'xmax': ST_XMax(geom), 'ymax': ST_YMax(geom)} AS bbox
    FROM relations ORDER BY id
) TO '{out}/relations.parquet' (FORMAT parquet, COMPRESSION zstd);
COPY (
    SELECT *, {'xmin': ST_XMin(geom), 'ymin': ST_YMin(geom), 'xmax': ST_XMax(geom), 'ymax': ST_YMax(geom)} AS bbox
    FROM areas
) TO '{out}/areas.parquet' (FORMAT parquet, COMPRESSION zstd);
