import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import base64
    import io
    import json
    import os
    import time
    from concurrent.futures import ThreadPoolExecutor

    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from PIL import Image, ImageDraw
    from pydantic import BaseModel, Field
    from pyproj import Transformer

    from common import ANSWERS_FILE, DATA, OUT, PAIRS_FILE, fetch_bytes, triage

    USGS_IMAGERY = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
    DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
    CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
    JEV_MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.14")
    CHAT_MODEL = os.environ.get("CHAT_MODEL", "google/gemini-3.8-flash")


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 3. Can a decision model say which records share a site, and how sure it is?

    [2. Rules](2_rules.py) showed that rules built on HIFLD's points are right about 80% of the time, and that the
    address rules can merge but never confidently keep two schools apart. Here we ask
    [Jev](https://openrouter.ai/docs/guides/community/jev), a *decision model*: it takes a state and a typed question
    and returns a probability, not text. One yes/no ("Noul") question per pair, through OpenRouter's Decisions API.

    We ask it in four ways, changing only what it is told about the pair, and put one of them to a cheap chat model
    for comparison. The pairs and evidence come from [1. Pairs](1_pairs.py).
    """)
    return


@app.cell
def _():
    pairs = pd.read_parquet(PAIRS_FILE)
    return (pairs,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The question

    The same in every variant. The two variants that see the address geocodes also get the note, which says why.
    """)
    return


@app.cell
def _():
    QUESTION = (
        "Do record_a and record_b describe schools at the same physical site, so that a map of school facilities "
        "should show them as one place?"
    )
    CRITERIA = {
        "true": "They share a building or a campus: co-located schools, academies or programs inside a larger "
        "school, or one school listed twice.",
        "false": "They are at separate sites, even if they are close together, belong to the same organization, or "
        "share a phone number or mailing address.",
    }
    GEOCODED_NOTE = (
        " The map points come from the source layer and are sometimes misplaced by hundreds of metres. The reported "
        "street addresses, and the distance between their independent Census Bureau geocodes, are more reliable."
    )
    mo.md(f"> {QUESTION}\n\n- **Yes:** {CRITERIA['true']}\n- **No:** {CRITERIA['false']}\n- **Note:** {GEOCODED_NOTE}")
    return CRITERIA, GEOCODED_NOTE, QUESTION


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What each variant is told

    - **`jev_text`**: both records and the facts from HIFLD's points (distance, same footprint, same grounds).
    - **`jev_text_image`**: the same, plus a USGS aerial image of the pair (public domain) with A in red and B in blue.
    - **`jev_geocoded`**: `jev_text`, plus the distance between the two Census address geocodes, plus the note. We
      added this after the first run, when the answer key showed that pairs whose points share a building often have
      different addresses and really are in different buildings.
    - **`jev_semantic`**: the pair **described in words**, with no map points or footprint flags at all: what each
      school is, where its address falls, and how the two addresses relate. Plus the note.
    - **`chat_text_image`**: `jev_text_image` as a prompt to a chat model, asked to state a probability as JSON.
    """)
    return


@app.cell
def _():
    def text(value: object) -> str | None:
        return value if isinstance(value, str) and value != "NOT AVAILABLE" else None

    def point_state(row: pd.Series, geocoded: bool) -> dict:
        """Both records and the facts from HIFLD's points (and the address geocodes if asked)."""

        def record(side: str) -> dict:
            _area = row[f"{side}_building_area_m2"]
            return {
                "name": row[f"{side}_name"],
                "address": f"{row[f'{side}_address']}, {row[f'{side}_city']}",
                "phone": row[f"{side}_telephone"],
                "grades": f"{row[f'{side}_st_grade']}-{row[f'{side}_end_grade']}",
                "level": row[f"{side}_level_"],
                "enrollment": int(row[f"{side}_enrollment"]),
                "charter": bool(row[f"{side}_charter"] == 1),
                "district_id": row[f"{side}_districtid"],
                "school_grounds_in_openstreetmap": text(row[f"{side}_osm_area_name"]),
                "building_footprint_m2": None if pd.isna(_area) else int(_area),
            }

        _state = {
            "record_a": record("a"),
            "record_b": record("b"),
            "distance_between_points_m": round(float(row["distance_m"])),
            "same_street_address": bool(row["same_address"]),
            "same_building_footprint": bool(row["same_building"]),
            "same_openstreetmap_school_grounds": bool(row["same_osm_grounds"]),
        }
        if geocoded:
            _d = row["geocoded_distance_m"]
            _state["distance_between_geocoded_addresses_m"] = None if pd.isna(_d) else int(_d)
        return _state

    def semantic_state(row: pd.Series) -> dict:
        """The pair in words: what each school is, where its address falls, how the addresses relate."""

        def record(side: str) -> dict:
            return {
                "name": row[f"{side}_name"],
                "reported_address": f"{row[f'{side}_address']}, {row[f'{side}_city']}",
                "address_as_matched_by_census": text(row[f"{side}_census_address"]) or "not found",
                "address_lies_within_school_grounds_named": text(row[f"{side}_address_grounds_name"]),
                "district": text(row[f"{side}_district_name"]),
                "school_type": text(row[f"{side}_school_type"]),
                "charter": bool(row[f"{side}_charter"] == 1),
                "virtual": text(row[f"{side}_virtual"]),
                "grades": f"{row[f'{side}_st_grade']}-{row[f'{side}_end_grade']}",
                "enrollment": int(row[f"{side}_enrollment"]),
                "phone": text(row[f"{side}_telephone"]),
                "website": text(row[f"{side}_website"]),
            }

        _d = row["geocoded_distance_m"]
        return {
            "record_a": record("a"),
            "record_b": record("b"),
            "street_addresses": row["street_relation"],
            "addresses_geocode": "one could not be geocoded" if pd.isna(_d) else f"about {int(round(_d, -1))} m apart",
        }

    return point_state, semantic_state


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **An example.** What `jev_text` and `jev_semantic` are given for the same pair: the first New York pair, by ID,
    whose two records give an identical street address.
    """)
    return


@app.cell
def _(pairs, point_state, semantic_state):
    _row = pairs[(pairs["region"] == "New York City") & (pairs["street_relation"] == "identical street address")]
    _row = _row.sort_values("pair_id").iloc[0]
    mo.hstack(
        [
            mo.vstack([mo.md("**`jev_text`**"), mo.json(point_state(_row, geocoded=False))]),
            mo.vstack([mo.md("**`jev_semantic`**"), mo.json(semantic_state(_row))]),
        ],
        widths="equal",
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Asking

    Every answer is checked against a schema and cached in `data/answers/`, so a rerun makes no paid calls. The chat
    model costs about 100 times more per pair, so it only answers the pairs with a key.
    """)
    return


@app.cell
def _(CRITERIA, GEOCODED_NOTE, QUESTION, point_state, semantic_state):
    class JevNoul(BaseModel):
        type: str
        noul: float = Field(ge=0, le=1)

    class JevResponse(BaseModel):
        answers: dict[str, JevNoul]
        usage: dict

    class ChatVerdict(BaseModel):
        same_site_probability: float = Field(ge=0, le=1)

    _to_mercator = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

    def aerial_chip(row: pd.Series) -> dict:
        """The pair on USGS imagery, A in red and B in blue, as an image part (cached on disk)."""
        _path = DATA / "chips" / f"{row['pair_id']}.jpg"
        if not _path.exists():
            _path.parent.mkdir(exist_ok=True)
            _ax, _ay = _to_mercator.transform(row["a_lon"], row["a_lat"])
            _bx, _by = _to_mercator.transform(row["b_lon"], row["b_lat"])
            _cx, _cy = (_ax + _bx) / 2, (_ay + _by) / 2
            _half = max(150.0, 0.75 * max(abs(_ax - _bx), abs(_ay - _by)) + 80)
            _size = 768
            _url = (
                f"{USGS_IMAGERY}?bbox={_cx - _half},{_cy - _half},{_cx + _half},{_cy + _half}&bboxSR=3857"
                f"&imageSR=3857&size={_size},{_size}&format=jpg&f=image"
            )
            _image = Image.open(io.BytesIO(fetch_bytes(_url))).convert("RGB")
            _draw = ImageDraw.Draw(_image)
            for (_x, _y), _colour in (((_ax, _ay), "red"), ((_bx, _by), "blue")):
                _px, _py = (_x - _cx + _half) / (2 * _half) * _size, (_cy + _half - _y) / (2 * _half) * _size
                _draw.ellipse([_px - 9, _py - 9, _px + 9, _py + 9], outline=_colour, width=4)
            _image.save(_path, quality=85)
        _data = base64.b64encode(_path.read_bytes()).decode()
        return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_data}"}}

    def ask(method: str, row: pd.Series) -> dict:
        """One model answer for one pair: {'p': probability, 'cost': USD}, from the cache when it is there."""
        _path = DATA / "answers" / method / f"{row['pair_id']}.json"
        if _path.exists():
            return json.loads(_path.read_text())
        _headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"}
        if method == "jev_semantic":
            _state = semantic_state(row)
        else:
            _state = point_state(row, geocoded=method == "jev_geocoded")
        if method.startswith("jev"):
            if method == "jev_text_image":
                _state["aerial_image_red_marker_is_a_blue_marker_is_b"] = aerial_chip(row)
            _question = QUESTION + (GEOCODED_NOTE if method in ("jev_geocoded", "jev_semantic") else "")
            _body = {
                "model": JEV_MODEL,
                "state": _state,
                "questions": {"same_site": {"type": "noul", "instructions": _question, "criteria": CRITERIA}},
            }
            _reply = JevResponse.model_validate_json(
                fetch_bytes(DECISIONS_URL, json.dumps(_body).encode(), _headers, 120)
            )
            _answer = {"p": _reply.answers["same_site"].noul, "cost": float(_reply.usage.get("cost", 0))}
        else:
            _prompt = (
                f"{QUESTION}\nYes means: {CRITERIA['true']}\nNo means: {CRITERIA['false']}\n"
                f"The aerial image shows record_a as a red circle and record_b as a blue circle.\n"
                f'{json.dumps(_state)}\nReply with JSON: {{"same_site_probability": <0 to 1>}}'
            )
            _body = {
                "model": CHAT_MODEL,
                "messages": [{"role": "user", "content": [{"type": "text", "text": _prompt}, aerial_chip(row)]}],
                "response_format": {"type": "json_object"},
            }
            _reply = json.loads(fetch_bytes(CHAT_URL, json.dumps(_body).encode(), _headers, 180))
            _verdict = ChatVerdict.model_validate_json(_reply["choices"][0]["message"]["content"])
            _answer = {"p": _verdict.same_site_probability, "cost": float(_reply["usage"].get("cost", 0))}
        _path.parent.mkdir(parents=True, exist_ok=True)
        _path.write_text(json.dumps(_answer))
        return _answer

    return (ask,)


@app.cell
def _(ask, pairs):
    METHODS = ["jev_text", "jev_text_image", "chat_text_image", "jev_geocoded", "jev_semantic"]
    answers = pairs[["pair_id", "region", "half", "truth"]].copy()
    _runs = []
    for _method in METHODS:
        _rows = pairs if _method != "chat_text_image" else pairs.dropna(subset=["truth"])
        _started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as _pool:
            _out = list(_pool.map(ask, [_method] * len(_rows), [r for _, r in _rows.iterrows()]))
        answers.loc[_rows.index, _method] = [o["p"] for o in _out]
        _runs.append(
            {
                "method": _method,
                "pairs": len(_rows),
                # Cached answers keep the cost of the call that made them, so this is the first run's cost.
                "cost_usd": round(sum(o["cost"] for o in _out), 4),
                "seconds_this_run": round(time.perf_counter() - _started),
            }
        )
    answers.drop(columns=["region", "half", "truth"]).to_parquet(ANSWERS_FILE, index=False)
    model_runs = pd.DataFrame(_runs)
    model_runs.to_csv(OUT / "model_runs.csv", index=False)
    model_runs
    return METHODS, answers


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scored like the rules

    Thresholds for ≥97% precision in each direction are picked on the *tune* half and counted on the *test* half,
    as in notebook 2. "Plain" reads each probability at 0.5.
    """)
    return


@app.cell
def _(answers):
    model_triage = triage(
        answers,
        {
            "Jev: records, point distance, footprint and grounds flags": "jev_text",
            "Jev: the same + aerial image": "jev_text_image",
            "Jev: the same + distance between address geocodes": "jev_geocoded",
            "Jev: the pair described in words, no map points": "jev_semantic",
            f"{CHAT_MODEL}: records, flags and image": "chat_text_image",
        },
        {},
    )
    model_triage.to_csv(OUT / "triage_models.csv", index=False)
    model_triage
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Is the probability a probability?

    A calibrated model's "0.8" is right 80% of the time. Every keyed pair (both halves, both regions) is binned by
    its predicted probability; a calibrated model sits on the diagonal. ECE is the average gap, weighted by how many
    pairs fall in each bin. Brier is the mean squared error (0 is perfect, 0.25 a coin flip). AUC is how well the
    probability ranks same-site pairs above different-site ones (1 is perfect).
    """)
    return


@app.cell
def _(METHODS, answers):
    _known = answers.dropna(subset=["truth"])
    _fig, _ax = plt.subplots(figsize=(5.5, 5))
    _ax.plot([0, 1], [0, 1], color="#999", lw=1, ls="--")
    _rows = []
    for _method, _colour in zip(METHODS, ["#4c72b0", "#c44e52", "#55a868", "#8172b2", "#dd8452"], strict=True):
        _p, _y = _known[_method].astype(float), _known["truth"].astype(float)
        _bins = np.minimum((_p * 10).astype(int), 9)
        _cal = (
            pd.DataFrame({"p": _p, "y": _y, "bin": _bins})
            .groupby("bin")
            .agg(p=("p", "mean"), y=("y", "mean"), n=("y", "size"))
        )
        _ax.plot(_cal["p"], _cal["y"], marker="o", color=_colour, label=_method)
        _ranked = _y.to_numpy()[np.argsort(-_p.to_numpy())]
        _auc = ((_ranked == 1).cumsum()[_ranked == 0]).sum() / max(1, (_ranked == 1).sum() * (_ranked == 0).sum())
        _rows.append(
            {
                "method": _method,
                "pairs": len(_p),
                "Brier": round(float(((_p - _y) ** 2).mean()), 3),
                "ECE": round(float((abs(_cal["p"] - _cal["y"]) * _cal["n"]).sum() / _cal["n"].sum()), 3),
                "AUC": round(float(_auc), 3),
            }
        )
    _ax.set_xlabel("predicted probability of same site")
    _ax.set_ylabel("share that really are the same site")
    _ax.legend(frameon=False, fontsize=8)
    _fig.tight_layout()
    _fig.savefig(OUT / "calibration.png", dpi=120)
    calibration = pd.DataFrame(_rows)
    calibration.to_csv(OUT / "calibration.csv", index=False)
    mo.vstack([calibration, mo.as_html(_fig)])
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What this shows

    - **Jev does best when the pair is described in words and the map points are left out.** It then decides most
      New York pairs automatically, in both directions, which no rule can.
    - **Given the points, Jev believes them**, and does no better than the rules. The aerial image made it worse:
      requests with an image run in Jev's long-context mode, which TypeSafe says is less accurate.
    - **The probabilities are not calibrated in the middle** (see the chart), so thresholds must come from a labelled
      sample, as [TypeSafe's guidance](https://docs.typesafe.ai/confidence) says.
    - **The chat model ranks well but costs about 100 times more**, and its probabilities cluster at a few values, so
      few pairs clear 97%.
    - **The wording matters, and answers vary between runs.** See [4. Sites](4_sites.py) for both.
    """)
    return


if __name__ == "__main__":
    app.run()
