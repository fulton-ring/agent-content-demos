# Using this catalog

- Start at `catalog.json` and follow `child` links: `hifld/catalog.json`, then one catalog per layer.
- Read GeoParquet over HTTP range requests (DuckDB, GDAL, pyarrow); don't download whole files.
- PMTiles are for maps; the collection's `styles/maplibre.json` draws them.
- The same metadata is searchable at https://hifld.publicenvirodata.org/api and through the MCP server at https://hifld.publicenvirodata.org/mcp.
- Source and licence: each collection's `via` and `license` links.
