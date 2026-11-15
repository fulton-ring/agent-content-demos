"""Helpers shared by the notebooks: one typed model call, and turning a printed result into a value.

`2_extraction.py` and `4_multi_sample.py` both call models; `3_results.py` and `4_multi_sample.py` both read
results. The notebooks explain each rule where it is used.
"""

import asyncio
import json
import math
import re
import time
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent, BinaryContent, capture_run_messages
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import infer_model
from pydantic_ai.models.openrouter import OpenRouterModelSettings


def response_cost(m: ModelResponse) -> float:
    return float((m.provider_details or {}).get("cost") or 0.0)


async def ask(
    model: str, output_type: type[BaseModel], instructions: str, prompt: str, pngs: list[Path], save: Path
) -> dict:
    """One typed model call, with its cost and time, saved to `save` and reused if it's already there."""
    if save.exists():
        return json.loads(save.read_text())
    agent = Agent(
        infer_model(model),
        output_type=output_type,
        instructions=instructions,
        retries=2,
        model_settings=OpenRouterModelSettings(
            temperature=0, max_tokens=12000, thinking="low", openrouter_usage={"include": True}
        ),
    )
    parts = [prompt] + [BinaryContent(p.read_bytes(), media_type="image/png") for p in pngs]
    result = {"usd": 0.0, "seconds": 0.0, "failed_attempts": 0, "output": None, "error": None}
    for attempt in range(4):
        t0 = time.time()
        with capture_run_messages() as messages:
            try:
                result["output"] = (await agent.run(parts)).output.model_dump(mode="json")
            except Exception as e:  # rate limits, network errors, malformed output after retries
                result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        result["usd"] += sum(response_cost(m) for m in messages if isinstance(m, ModelResponse))
        result["seconds"] += time.time() - t0
        if result["output"] is not None:
            result["error"] = None
            break
        result["failed_attempts"] += 1
        await asyncio.sleep(10 * (attempt + 1))
    save.parent.mkdir(parents=True, exist_ok=True)
    save.write_text(json.dumps(result, indent=1))
    return result


def spent(folder: Path) -> float:
    """Dollars spent on every saved answer under `folder`."""
    return sum(json.loads(p.read_text())["usd"] for p in folder.rglob("*.json"))


CANONICAL = {
    "antimony": "antimony",
    "arsenic": "arsenic",
    "barium": "barium",
    "beryllium": "beryllium",
    "boron": "boron",
    "cadmium": "cadmium",
    "calcium": "calcium",
    "chloride": "chloride",
    "chromium": "chromium",
    "cobalt": "cobalt",
    "fluoride": "fluoride",
    "lead": "lead",
    "lithium": "lithium",
    "mercury": "mercury",
    "molybdenum": "molybdenum",
    "selenium": "selenium",
    "sulfate": "sulfate",
    "thallium": "thallium",
    "total dissolved solids": "tds",
    "tds": "tds",
    "solids, total dissolved": "tds",
    "residue, filterable": "tds",
}


def canonical(name: str) -> str | None:
    text = name.lower().strip()
    if re.fullmatch(r"ph\b.*", text) or text.startswith("ph,"):
        return "ph"
    return next((c for k, c in CANONICAL.items() if text.startswith(k) or text.split(",")[0] == k), None)


def number(text: str | None) -> float | None:
    match = re.search(r"\d*\.?\d+(?:[eE]-?\d+)?", (text or "").replace(",", ""))
    return float(match.group()) if match else None


def meaning(printed: str | None, reporting_limit: str | None = None) -> tuple[bool, float | None] | None:
    """(non-detect, value) for a printed result, or None if it can't be read."""
    text = re.sub(r"(MG/L|UG/L|NG/L|S\.?U\.?)$", "", (printed or "").strip().upper().replace(" ", ""))
    if not text:
        return None
    if text.startswith("<"):
        return True, number(text)
    if text in ("ND", "U", "<RL", "NOTDETECTED"):
        return True, number(reporting_limit)
    if re.match(r"<?[A-Z]", text):  # a code printed instead of a value, such as AEP's "Q18"
        return None
    value = number(text)
    return None if value is None else (False, value)


def in_mg_per_l(value: tuple | None, units: str) -> tuple | None:
    """Results printed in µg/L or ng/L, converted to mg/L."""
    unit = units.lower().replace(" ", "")
    divisor = {"ug/l": 1e3, "µg/l": 1e3, "μg/l": 1e3, "ng/l": 1e6}.get(unit)
    if value is None or value[1] is None or divisor is None:
        return value
    return value[0], value[1] / divisor


PH_UNITS = {"s.u.", "su", "s.u", "units", "std units", "ph units", "none", ""}


def checks(analyte: str, value: tuple | None, units: str) -> list[str]:
    """The checks a value must pass to be accepted: readable, the usual units, a plausible size."""
    failed = []
    if value is None or value[1] is None:
        return ["unreadable result"]
    unit = units.lower().strip()
    if analyte == "ph":
        if unit not in PH_UNITS:
            failed.append(f"units {units}")
        if not 0 <= value[1] <= 14:
            failed.append("pH outside 0-14")
    else:
        if unit not in ("mg/l", "ug/l", "µg/l", "μg/l", "ng/l"):
            failed.append(f"units {units}")
        if not 0 <= value[1] <= 100_000:
            failed.append("implausible value")
    return failed


def same(a: tuple | None, b: tuple | None) -> bool:
    if a is None or b is None or a[0] != b[0] or a[1] is None or b[1] is None:
        return False
    return math.isclose(a[1], b[1], rel_tol=1e-9, abs_tol=1e-12)


def well_name(text: str | None) -> str:
    return re.sub(r"\s+", "", (text or "").upper()).translate(str.maketrans("‐‑‒–", "----"))
