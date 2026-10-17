"""Load a pipeline or recipe as a module: from a file, or from code in the experiment record."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from fri_rebuild.paths import HAZARDS_DIR


def load_pipeline(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"pipeline_{path.parent.name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_source(code: str, name: str) -> ModuleType:
    """A module from source code, e.g. an agent's candidate from experiments.jsonl."""
    module = ModuleType(f"pipeline_{name}")
    sys.modules[module.__name__] = module  # dataclasses and pickling look modules up by name
    exec(compile(code, f"<{name}>", "exec"), module.__dict__)  # noqa: S102 - our own record
    return module


def hazard_pipeline(hazard: str) -> ModuleType:
    """The final (kept) pipeline for one hazard folder under hazards/."""
    return load_pipeline(HAZARDS_DIR / hazard / "pipeline.py")
