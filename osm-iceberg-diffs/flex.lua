-- osm2pgsql flex style for the candidate stack.
-- The middle tables (planet_osm_nodes/ways/rels, kept because we run --slim)
-- already hold every element's tags, way node lists and relation members, which
-- is what recursion needs. These three tables add geometry for spatial filters.

-- A GiST index for spatial filters and a GIN index for tag filters on each table.
local INDEXES = {
    { column = 'geom', method = 'gist' },
    { column = 'tags', method = 'gin' },
}

local nodes = osm2pgsql.define_node_table('nodes_geo', {
    { column = 'tags', type = 'jsonb' },
    { column = 'geom', type = 'point', projection = 4326, not_null = true },
}, { indexes = INDEXES })

local ways = osm2pgsql.define_way_table('ways_geo', {
    { column = 'tags', type = 'jsonb' },
    { column = 'geom', type = 'linestring', projection = 4326, not_null = true },
}, { indexes = INDEXES })

-- Named areas, the equivalent of Overpass's area objects: closed named ways and
-- named multipolygon/boundary relations.
local areas = osm2pgsql.define_area_table('areas_geo', {
    { column = 'tags', type = 'jsonb' },
    { column = 'geom', type = 'multipolygon', projection = 4326, not_null = true },
}, { indexes = INDEXES })

function osm2pgsql.process_node(object)
    nodes:insert({ tags = object.tags, geom = object:as_point() })
end

function osm2pgsql.process_way(object)
    ways:insert({ tags = object.tags, geom = object:as_linestring() })
    if object.is_closed and object.tags.name and object.tags.area ~= 'no' then
        areas:insert({ tags = object.tags, geom = object:as_multipolygon() })
    end
end

-- Untagged ways matter too: they are the members of multipolygons and routes,
-- and Overpass finds a relation in a bbox or area through its members.
function osm2pgsql.process_untagged_way(object)
    ways:insert({ geom = object:as_linestring() })
end

function osm2pgsql.process_relation(object)
    local kind = object.tags.type
    if object.tags.name and (kind == 'multipolygon' or kind == 'boundary') then
        areas:insert({ tags = object.tags, geom = object:as_multipolygon() })
    end
end
