-- Replaces Underpass-API's src/postgres_osmosis/view.sql: the views the parser's SQL reads.
-- Differences: jsonb tags, relation members in Overpass's JSON shape, relation geometry.
CREATE OR REPLACE TEMP VIEW node_by_geom AS
SELECT id, version, tstamp AS created, changeset_id AS changeset, user_id AS uid, NULL::text AS user,
       jtags AS tags, NULL::bigint[] AS nodes, NULL::jsonb AS members, geom, 'n' AS osm_type
FROM nodes;
CREATE OR REPLACE TEMP VIEW node_by_id AS SELECT * FROM node_by_geom;

CREATE OR REPLACE TEMP VIEW way_by_geom AS
SELECT id, version, tstamp AS created, changeset_id AS changeset, user_id AS uid, NULL::text AS user,
       jtags AS tags, nodes, NULL::jsonb AS members, linestring AS geom, 'w' AS osm_type
FROM ways;
CREATE OR REPLACE TEMP VIEW way_by_id AS SELECT * FROM way_by_geom;

CREATE OR REPLACE TEMP VIEW relation_by_geom AS
SELECT r.id, r.version, r.tstamp AS created, r.changeset_id AS changeset, r.user_id AS uid, NULL::text AS user,
       r.jtags AS tags, NULL::bigint[] AS nodes,
       (SELECT jsonb_agg(jsonb_build_object(
                   'type', CASE m.member_type WHEN 'N' THEN 'node' WHEN 'W' THEN 'way' ELSE 'relation' END,
                   'ref', m.member_id, 'role', m.member_role) ORDER BY m.sequence_id)
        FROM relation_members m WHERE m.relation_id = r.id) AS members,
       g.geom, 'r' AS osm_type
FROM relations r LEFT JOIN relation_geoms g USING (id);
CREATE OR REPLACE TEMP VIEW relation_by_id AS SELECT * FROM relation_by_geom;

CREATE OR REPLACE TEMP VIEW nwr_by_geom AS
SELECT * FROM node_by_geom UNION ALL SELECT * FROM way_by_geom UNION ALL SELECT * FROM relation_by_geom;
CREATE OR REPLACE TEMP VIEW nwr_by_id AS SELECT * FROM nwr_by_geom;

-- Areas as in Underpass-API: built multipolygons (id + 3600000000) and closed ways.
CREATE OR REPLACE TEMP VIEW area_by_geom AS
SELECT id, NULL::integer AS version, NULL::timestamp AS created, NULL::bigint AS changeset, NULL::integer AS uid,
       NULL::text AS user, hstore_to_jsonb(tags) AS tags, NULL::bigint[] AS nodes, NULL::jsonb AS members,
       poly AS geom, 'a' AS osm_type
FROM multipolygons WHERE id > 3600000000
UNION ALL
SELECT id, version, tstamp, changeset_id, user_id, NULL::text, jtags, nodes, NULL::jsonb,
       ST_MakePolygon(linestring)::geometry(Geometry, 4326), 'w'
FROM ways WHERE ST_IsClosed(linestring) AND ST_NPoints(linestring) >= 4;
CREATE OR REPLACE TEMP VIEW area_by_id AS SELECT * FROM area_by_geom;
