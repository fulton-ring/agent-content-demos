import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # Part 2: what state records portals ask for, and who tightened it in 2026

    **The question.** What does a state agency's public-records portal require before it accepts a request, and
    are agencies tightening that because of AI agents? Virginia's Department of Education said in November 2026
    that it asks "non-verifiable" requesters for photo ID and "will soon move to requiring ID for all submissions",
    after "an influx in nonsensical or incomplete communication requests" (WVTF, 2026-11-16).

    **The sample.** One agency per state and DC, chosen by one rule: the state environmental agency (DEQ, DEP,
    DEC or equivalent; for DC, DOEE). Environmental agencies handle large records volumes from the public,
    consultants and nonprofits in every state, so they are comparable. Each row of `survey.csv` was read by hand
    on 2026-11-21 from the agency's public records page and request form, without creating an account or
    submitting anything. Each row links the page it was read from.

    **The 2026 changes.** `changes_2026.csv` lists every 2026 change to records-request intake we found in a
    separate search: state laws, state agencies and local governments, each with its source and whether the
    source is primary.
    """)
    return (mo,)


@app.cell
def _():
    import json
    import os
    from pathlib import Path

    import pandas as pd

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("RESULTS_DIR", HERE / "results"))
    OUT.mkdir(parents=True, exist_ok=True)
    survey = pd.read_csv(HERE / "survey.csv", dtype=str, keep_default_na=False)
    changes = pd.read_csv(HERE / "changes_2026.csv", dtype=str, keep_default_na=False)
    assert survey["state"].is_unique and len(survey) == 51, "one row per state and DC"
    return OUT, Path, changes, json, pd, survey


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Could we read each portal?

    `read` means we saw the records page and the form. `partial` means part of it was behind a login, a
    script-only form or a bot check, so some fields are `unknown`. `blocked` means the agency's site refused us
    outright and the row was filled from search-engine copies of its pages.

    Part 1 (`collect.py`) re-fetches every URL once with a plain script and an honest user agent, as a check
    on which pages a simple automated client can reach at all.
    """)
    return


@app.cell
def _(OUT, mo, pd, survey):
    read_status = survey["read_status"].value_counts()
    fetch_path = OUT / "fetch.csv"
    fetch = pd.read_csv(fetch_path) if fetch_path.exists() else pd.DataFrame()
    script_blocked_states = (
        sorted(fetch.loc[fetch["outcome"].isin(["blocked", "error"]) & (fetch["page"] == "records"), "state"])
        if len(fetch)
        else []
    )
    mo.vstack(
        [
            mo.md(
                f"By hand: **{read_status.get('read', 0)} read, {read_status.get('partial', 0)} partial, "
                f"{read_status.get('blocked', 0)} blocked** of {len(survey)}."
            ),
            mo.md(
                f"By script: {len(fetch)} URLs fetched; the records page was blocked or failed for "
                f"**{len(script_blocked_states)}** states: {', '.join(script_blocked_states) or 'none'}."
                if len(fetch)
                else "No `results/fetch.csv` yet: run `collect.py` first."
            ),
            fetch["outcome"].value_counts().rename_axis("script outcome").reset_index() if len(fetch) else mo.md(""),
        ]
    )
    return fetch, read_status, script_blocked_states


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. What the portals ask for

    Each count is out of the agencies where we could tell; `unknown` is shown so the denominator is visible.
    "Account" counts `yes` only where the agency's online channel cannot be used without registering;
    `optional` portals let you submit as a guest.
    """)
    return


@app.cell
def _(pd, survey):
    fields = {
        "account_required": "Account required",
        "name_required": "Name required",
        "address_required": "Postal address required",
        "residency_required_by_form": "Form asks for residency",
        "photo_id_required": "Photo ID required",
        "captcha": "Captcha on form",
        "email_channel": "Accepts requests by email",
        "machine_channel": "API or machine channel",
    }
    requirements = pd.DataFrame(
        [{"requirement": label, **survey[col].value_counts().to_dict()} for col, label in fields.items()]
    ).fillna(0)
    for _c in ["yes", "no", "optional", "unknown"]:
        if _c not in requirements:
            requirements[_c] = 0
    requirements = requirements[["requirement", "yes", "optional", "no", "unknown"]].astype(
        {"yes": int, "optional": int, "no": int, "unknown": int}
    )
    requirements["known"] = requirements["yes"] + requirements["optional"] + requirements["no"]
    requirements
    return (requirements,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Residency: by law and by form

    We read each state's records statute for who may ask. Most say "any person". A few say "citizen" or
    "resident" of the state. Pennsylvania limits requesters to legal residents of the United States, not of
    Pennsylvania, so it is coded `us_only` and not counted as a state-residency law. New Jersey's text says
    "citizens", but an appellate court held out-of-state requesters have standing; it is counted by the text,
    and the note says so.
    """)
    return


@app.cell
def _(mo, survey):
    law_states = sorted(survey.loc[survey["residency_limit_in_law"] == "yes", "state"])
    form_states = sorted(survey.loc[survey["residency_required_by_form"] == "yes", "state"])
    either_states = sorted(set(law_states) | set(form_states))
    mo.vstack(
        [
            mo.md(
                f"- State residency limit **in law**: **{len(law_states)}** ({', '.join(law_states)})\n"
                f"- Form asks the requester to state residency: **{len(form_states)}** ({', '.join(form_states)})\n"
                f"- Either: **{len(either_states)}**"
            ),
            survey.loc[
                survey["state"].isin(either_states) | (survey["residency_limit_in_law"] == "us_only"),
                ["state", "residency_limit_in_law", "residency_required_by_form", "statute", "statute_note"],
            ],
        ]
    )
    return either_states, form_states, law_states


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. What changed in 2026

    First, the 51 surveyed agencies: did their intake rules, or a state law that governs them, change in
    2026? Each row's `change_2026_kind` was coded by hand from its `change_2026` text and source.
    """)
    return


@app.cell
def _(survey):
    kinds = survey["change_2026_kind"].value_counts().rename_axis("change_2026_kind").reset_index()
    tightened_states = sorted(survey.loc[survey["change_2026_kind"] == "tightened_by_law", "state"])
    changed_states = sorted(
        survey.loc[survey["change_2026_kind"].isin(["tightened_by_law", "agency_channel_change"]), "state"]
    )
    kinds
    return changed_states, tightened_states


@app.cell
def _(mo, survey, tightened_states):
    mo.vstack(
        [
            mo.md(
                f"**{len(tightened_states)}** surveyed agencies sit under a state law that tightened intake in or "
                f"for 2026 ({', '.join(tightened_states)}). None of those laws requires photo ID; Illinois's "
                "forbids asking for it. Bills that would have added ID or residency proof died in KY, NH and RI."
            ),
            survey.loc[
                survey["change_2026_kind"] != "none",
                ["state", "agency", "change_2026_kind", "change_2026", "change_2026_source"],
            ],
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    Then every 2026 change we found anywhere, including the Virginia Department of Education (not in the
    sample, since Virginia's row is its environmental agency) and local governments. A change counts as
    **tightened** if it was enacted, adopted or announced, not if a bill died.
    """)
    return


@app.cell
def _(changes):
    tightened = changes[changes["status"].isin(["enacted", "adopted", "said"])]
    outside_virginia = tightened[~((tightened["jurisdiction"] == "VA") & (tightened["level"] == "state agency"))]
    ai_motivated = outside_virginia[outside_virginia["ai_or_bot_motive"] == "yes"]
    photo_id = tightened[tightened["photo_id"] == "yes"]
    changes[["jurisdiction", "level", "body", "status", "date", "ai_or_bot_motive", "photo_id", "source_kind"]]
    return ai_motivated, outside_virginia, photo_id, tightened


@app.cell
def _(ai_motivated, changes, mo, outside_virginia, photo_id, tightened):
    died = changes[changes["status"].str.startswith("died")]
    mo.md(
        f"- Tightenings found (enacted, adopted or announced): **{len(tightened)}**; outside VDOE: "
        f"**{len(outside_virginia)}**, of which **{len(ai_motivated)}** cite AI, bots or automated requests.\n"
        f"- By level, outside VDOE: "
        + ", ".join(f"{k} {v}" for k, v in outside_virginia["level"].value_counts().items())
        + f".\n- Requiring **photo ID**: **{len(photo_id)}** ({', '.join(photo_id['body'])}).\n"
        f"- Bills that died: **{len(died)}** ({', '.join(died['jurisdiction'])})."
    )
    return (died,)


@app.cell
def _(
    OUT,
    ai_motivated,
    changed_states,
    died,
    either_states,
    fetch,
    form_states,
    json,
    law_states,
    mo,
    outside_virginia,
    photo_id,
    read_status,
    requirements,
    script_blocked_states,
    survey,
    tightened_states,
):
    req = requirements.set_index("requirement")
    summary = {
        "date_read": "2026-11-21",
        "portals_surveyed": len(survey),
        "read": int(read_status.get("read", 0)),
        "partial": int(read_status.get("partial", 0)),
        "blocked_by_hand": int(read_status.get("blocked", 0)),
        "script_records_page_blocked_or_failed": len(script_blocked_states),
        "script_urls_fetched": len(fetch),
        "requirements": {r: {k: int(req.loc[r, k]) for k in ["yes", "optional", "no", "unknown"]} for r in req.index},
        "residency_limit_in_law": law_states,
        "residency_asked_on_form": form_states,
        "residency_law_or_form": len(either_states),
        "surveyed_agencies_under_2026_tightening_law": tightened_states,
        "surveyed_agencies_changed_2026": changed_states,
        "tightenings_outside_vdoe": len(outside_virginia),
        "tightenings_outside_vdoe_citing_ai": len(ai_motivated),
        "tightenings_requiring_photo_id": list(photo_id["body"]),
        "bills_died": list(died["jurisdiction"]),
        "cost_usd": 0,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    pid = req.loc["Photo ID required"]
    acct = req.loc["Account required"]
    by_email = req.loc["Accepts requests by email", "yes"]
    by_api = req.loc["API or machine channel", "yes"]
    id_bodies = ", ".join(photo_id["body"])
    mo.md(f"""
    ## Result

    We read the records-request pages of **{len(survey)}** state environmental agencies on 2026-11-21
    ({summary["read"]} fully, {summary["partial"]} partly, {summary["blocked_by_hand"]} blocked).
    **{pid["yes"]}** require photo ID ({pid["no"]} don't; {pid["unknown"]} we couldn't see).
    **{acct["yes"]}** require an account before you can use their online channel. **{len(law_states)}** states
    limit requests to residents by law and **{len(form_states)}** forms ask about residency
    ({len(either_states)} either way). **{by_email}** accept requests by plain email; **{by_api}** offer an API.

    On the trend: outside VDOE we found **{len(outside_virginia)}** tightenings in 2026,
    **{len(ai_motivated)}** citing AI or bots: state laws in Indiana, Illinois and California, and local rules
    in a handful of towns and counties. **{len(photo_id)}** requires photo ID ({id_bodies}). The prediction
    that "a small number" are adding ID checks doesn't hold: the response so far is verify-you're-human steps,
    captchas, surcharges and AI carve-outs, and the {len(died)} bills that would have added ID, identity or
    residency proof or AI denials all died.

    Written to `results/summary.json`.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **Forms behind logins and scripts.** About a third of form fields are `unknown`: GovQA and AccessGov
      portals show nothing before you register, and several JustFOIA and NextRequest forms load their fields by
      script behind a bot check. We did not register or bypass checks, so we can't say what those forms ask.
    - **Bot walls.** Some agency sites refused our readers outright (Cloudflare, Incapsula, Radware, CloudFront).
      Those rows were filled from search-engine copies and are marked `blocked` or `partial`.
    - **Hand-read, not audited.** Every field except part 1's fetch results was read by hand (by agents
      reading the pages, each row with its source URL). A second reader would likely flip a few `unknown`s.
    - **One agency per state.** Environmental agencies aren't the whole state. A state law (IN, IL, CA) applies
      to all agencies; an agency policy (VDOE) doesn't.
    - **Local changes are a sample, not a census.** The local rows are what a search turned up; several rest on
      meeting summaries rather than the adopted text (`source_kind`).
    """)
    return


if __name__ == "__main__":
    app.run()
