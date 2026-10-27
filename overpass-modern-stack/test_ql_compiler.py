"""The patched parser on the answer key: every query compiles for both dialects, and out-of-scope QL fails loudly.

Needs the patched `overpass2sql`, which `ql_compiler.py` builds (or set OVERPASS2SQL).
"""

import os
import subprocess
from pathlib import Path

import pytest

from answer_key import QUERIES, UNSUPPORTED

PARSER = Path(
    os.environ.get(
        "OVERPASS2SQL",
        Path(__file__).parent / "data" / "build" / "overpass_parser_rust" / "target" / "release" / "overpass2sql",
    )
)
pytestmark = pytest.mark.skipif(not PARSER.exists(), reason="run ql_compiler.py first to build the parser")


def compile_ql(ql: str, dialect: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(PARSER), dialect], input=ql, capture_output=True, text=True)


@pytest.mark.parametrize("dialect", ["postgres", "duckdb"])
@pytest.mark.parametrize(("name", "ql"), QUERIES, ids=[q[0] for q in QUERIES])
def test_answer_key_compiles(name: str, ql: str, dialect: str) -> None:
    done = compile_ql(ql, dialect)
    assert done.returncode == 0, f"{name}: {done.stderr[-500:]}"
    assert "SELECT" in done.stdout


@pytest.mark.parametrize(("name", "ql"), [u for u in UNSUPPORTED if u[0] != "foreach"], ids=lambda v: str(v)[:20])
def test_out_of_scope_names_the_feature(name: str, ql: str) -> None:
    done = compile_ql(ql, "postgres")
    assert done.returncode != 0
    assert "unsupported Overpass QL feature" in done.stderr


def test_trailing_text_is_an_error_not_ignored() -> None:
    # Before the patch, the parser stopped at the first statement it didn't know and dropped the rest.
    done = compile_ql('[out:json];node["amenity"="cafe"];out;garbage here;', "postgres")
    assert done.returncode != 0


def test_global_bbox_reaches_every_query() -> None:
    done = compile_ql("[out:json][bbox:1,2,3,4];(node[a];way[b];);out;", "postgres")
    assert done.returncode == 0
    assert done.stdout.count("ST_MakeEnvelope(2, 1, 4, 3, 4326)") == 2
