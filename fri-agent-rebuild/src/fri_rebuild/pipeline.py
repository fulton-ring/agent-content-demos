"""Load a pipeline or recipe file (hazard pipelines, agent candidates, recipe-search agents)."""

import importlib.util
from pathlib import Path

from fri_rebuild.paths import HAZARDS_DIR


def load_pipeline(path: Path):  # noqa: ANN201 - returns a module
    spec = importlib.util.spec_from_file_location(f"pipeline_{path.parent.name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hazard_pipeline(hazard: str):  # noqa: ANN201 - returns a module
    """The final (kept) pipeline for one hazard folder under hazards/."""
    return load_pipeline(HAZARDS_DIR / hazard / "pipeline.py")
