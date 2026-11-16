import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json

    import marimo as mo
    import pandas as pd

    import wade

    return json, mo, pd, wade


@app.cell
def _(mo):
    mo.md(r"""
    # WaDE rebuild: the three states side by side

    This reads the summaries `california.py`, `colorado.py` and `wyoming.py` wrote to
    `outputs/` and puts them in one table. Run those three first (`run.sh` does).
    """)
    return


@app.cell
def _(json, wade):
    summaries = [
        json.loads((wade.OUT_DIR / f"{s}_summary.json").read_text()) for s in ["CA", "CO", "WY"]
    ]
    return (summaries,)


@app.cell
def _(pd, summaries):
    def fields_with(summary: dict, statuses: set[str]) -> str:
        names = [f["field"] for f in summary["fields"] if f["status"] in statuses]
        return ", ".join(n.removeprefix("Allocation") for n in names) or "none"

    table = pd.DataFrame(
        [
            {
                "State": s["state"],
                "WaDE count": f"{s['wade_count']:,}",
                "Rebuilt count": f"{s['rebuilt_count']:,}",
                "WaDE IDs matched": f"{s['match_rate']:.1%}",
                "Location within 100 m": f"{s['location_within_100m']:.1%}",
                "Rights WaDE's checks dropped": f"{s['extra_rights']['dropped_by_wade_checks']:,}",
                "Fields back (≥95%)": fields_with(s, {"comes back"}),
                "Fields not back": fields_with(s, {"partly", "differs", "no source column"}),
                "Newest record": s["newest_record"],
                "Source updated": s["source_updated"],
                "Update frequency": s["update_frequency"],
                "Run time (s)": s["run_seconds"],
            }
            for s in summaries
        ]
    )
    table
    return (table,)


@app.cell
def _(pd, summaries):
    field_table = pd.DataFrame(
        {
            s["state"]: {
                f["field"]: f["status"]
                if f["same_value"] is None
                else f"{f['same_value']:.1%} ({f['status']})"
                for f in s["fields"]
            }
            for s in summaries
        }
    )
    field_table
    return (field_table,)


@app.cell
def _(field_table, mo, summaries, table, wade):
    _ca = next(s for s in summaries if s["state"] == "California")
    _crosswalk = "; ".join(
        f"{c['field'].removeprefix('Allocation')}: {c['lookup rows']} rows restore "
        f"{c['WaDE values restored']:.0%}"
        for c in _ca["crosswalk"]
    )
    _md = (
        "## Per state\n\n"
        + table.set_index("State").T.to_markdown()
        + "\n\n## Field agreement on matched rights\n\n"
        + field_table.to_markdown()
        + f"\n\nCalifornia crosswalk learned from WaDE's last table: {_crosswalk}.\n"
    )
    (wade.OUT_DIR / "summary.md").write_text(_md)
    mo.md(_md)
    return


if __name__ == "__main__":
    app.run()
