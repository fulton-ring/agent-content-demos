-- Licence: AGPL-3.0, as Underpass-API, whose view.sql this adapts.
-- The views the parser's DuckDB SQL reads, over the Parquet tables from duckdb_build.sql.
-- Placeholder: {out} (the directory holding the tables). Every view has the same columns,
-- so recursion can UNION ALL them.
LOAD spatial;

CREATE OR REPLACE TEMP VIEW node_by_geom AS
SELECT id, NULL::INTEGER AS version, NULL::TIMESTAMP AS created, NULL::BIGINT AS changeset, NULL::INTEGER AS uid,
       NULL::VARCHAR AS "user", tags, NULL::BIGINT[] AS nodes,
       NULL::STRUCT(type VARCHAR, ref BIGINT, role VARCHAR)[] AS members, geom, bbox, 'n' AS osm_type
FROM read_parquet('{out}/nodes.parquet');
CREATE OR REPLACE TEMP VIEW node_by_id AS SELECT * FROM node_by_geom;

CREATE OR REPLACE TEMP VIEW way_by_geom AS
SELECT id, NULL::INTEGER AS version, NULL::TIMESTAMP AS created, NULL::BIGINT AS changeset, NULL::INTEGER AS uid, NULL::VARCHAR AS "user", tags, nodes,
       NULL::STRUCT(type VARCHAR, ref BIGINT, role VARCHAR)[] AS members, geom, bbox, 'w' AS osm_type
FROM read_parquet('{out}/ways.parquet');
CREATE OR REPLACE TEMP VIEW way_by_id AS SELECT * FROM way_by_geom;

CREATE OR REPLACE TEMP VIEW relation_by_geom AS
SELECT id, NULL::INTEGER AS version, NULL::TIMESTAMP AS created, NULL::BIGINT AS changeset, NULL::INTEGER AS uid, NULL::VARCHAR AS "user", tags, NULL::BIGINT[] AS nodes,
       members, geom, bbox, 'r' AS osm_type
FROM read_parquet('{out}/relations.parquet');
CREATE OR REPLACE TEMP VIEW relation_by_id AS SELECT * FROM relation_by_geom;

CREATE OR REPLACE TEMP VIEW nwr_by_geom AS
SELECT * FROM node_by_geom UNION ALL SELECT * FROM way_by_geom UNION ALL SELECT * FROM relation_by_geom;
CREATE OR REPLACE TEMP VIEW nwr_by_id AS SELECT * FROM nwr_by_geom;

CREATE OR REPLACE TEMP VIEW area_by_geom AS
SELECT id, NULL::INTEGER AS version, NULL::TIMESTAMP AS created, NULL::BIGINT AS changeset, NULL::INTEGER AS uid, NULL::VARCHAR AS "user", tags, NULL::BIGINT[] AS nodes,
       NULL::STRUCT(type VARCHAR, ref BIGINT, role VARCHAR)[] AS members, geom, bbox, osm_type
FROM read_parquet('{out}/areas.parquet');
CREATE OR REPLACE TEMP VIEW area_by_id AS SELECT * FROM area_by_geom;
