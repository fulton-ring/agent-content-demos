"""Two read-only PyQGIS tools for the agent: describe a layer, and read its features.

Runs under the system Python that ships QGIS's bindings (/usr/bin/python3), not the project's uv
environment, so agent_runs.py calls it as a subprocess: `python3 pyqgis_tool.py '<json request>'`.
It prints one JSON object.
"""

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import QgsApplication, QgsExpression, QgsFeatureRequest, QgsVectorLayer  # noqa: E402  # ty: ignore[unresolved-import]

MAX_FEATURES = 50


def layer_info(layer: QgsVectorLayer) -> dict:
    ext = layer.extent()
    return {
        "crs": layer.crs().authid(),
        "crs_units": layer.crs().mapUnits().name
        if hasattr(layer.crs().mapUnits(), "name")
        else str(layer.crs().mapUnits()),
        "geometry_type": layer.geometryType().name
        if hasattr(layer.geometryType(), "name")
        else str(layer.geometryType()),
        "feature_count": layer.featureCount(),
        "extent": [ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()],
        "fields": [{"name": f.name(), "type": f.typeName()} for f in layer.fields()],
    }


def features(layer: QgsVectorLayer, expression: str, fields: list[str], limit: int) -> dict:
    request = QgsFeatureRequest()
    if expression:
        expr = QgsExpression(expression)
        if expr.hasParserError():
            return {"error": f"expression error: {expr.parserError()}"}
        request.setFilterExpression(expression)
    names = fields or [f.name() for f in layer.fields()]
    missing = [n for n in names if layer.fields().indexOf(n) < 0]
    if missing:
        return {"error": f"no such fields: {missing}"}
    rows, matched = [], 0
    for feat in layer.getFeatures(request):
        matched += 1
        if len(rows) < min(limit, MAX_FEATURES):
            rows.append({n: feat[n] if not hasattr(feat[n], "isNull") else None for n in names})
    return {"matched": matched, "returned": len(rows), "features": json.loads(json.dumps(rows, default=str))}


def main() -> None:
    req = json.loads(sys.argv[1])
    app = QgsApplication([], False)
    app.initQgis()
    layer = QgsVectorLayer(req["path"], "layer", "ogr")
    if not layer.isValid():
        print(json.dumps({"error": f"could not open {req['path']} as a vector layer"}))
        return
    if req["command"] == "layer_info":
        out = layer_info(layer)
    else:
        out = features(layer, req.get("expression", ""), req.get("fields", []), int(req.get("limit", 20)))
    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
