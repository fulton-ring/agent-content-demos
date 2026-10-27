-- Our adapter on top of Underpass-API's Osmosis schema (run after its init.sql).
-- The parser now emits jsonb (tags->>'k', tags?'k'); Osmosis stores hstore.
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS jtags jsonb GENERATED ALWAYS AS (hstore_to_jsonb(tags)) STORED;
ALTER TABLE ways ADD COLUMN IF NOT EXISTS jtags jsonb GENERATED ALWAYS AS (hstore_to_jsonb(tags)) STORED;
ALTER TABLE relations ADD COLUMN IF NOT EXISTS jtags jsonb GENERATED ALWAYS AS (hstore_to_jsonb(tags)) STORED;
CREATE INDEX IF NOT EXISTS nodes_jtags ON nodes USING gin (jtags);
CREATE INDEX IF NOT EXISTS ways_jtags ON ways USING gin (jtags);
CREATE INDEX IF NOT EXISTS relations_jtags ON relations USING gin (jtags);
CREATE INDEX IF NOT EXISTS ways_nodes ON ways USING gin (nodes);

-- Overpass finds a relation in a bbox or area through its members, so a
-- relation's geometry is the collection of its member nodes and ways.
DROP TABLE IF EXISTS relation_geoms;
CREATE TABLE relation_geoms AS
SELECT rm.relation_id AS id, ST_Collect(coalesce(n.geom, w.linestring)) AS geom
FROM relation_members rm
LEFT JOIN nodes n ON rm.member_type = 'N' AND n.id = rm.member_id
LEFT JOIN ways w ON rm.member_type = 'W' AND w.id = rm.member_id
WHERE coalesce(n.geom, w.linestring) IS NOT NULL
GROUP BY rm.relation_id;
ALTER TABLE relation_geoms ADD PRIMARY KEY (id);
CREATE INDEX relation_geoms_geom ON relation_geoms USING gist (geom);
ANALYZE;
