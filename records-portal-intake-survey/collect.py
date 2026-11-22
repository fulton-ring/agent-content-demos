import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # Part 1: can a plain script read each portal's public pages?

    `survey.csv` was read by hand (see the README for which fields). This notebook checks the part a script can
    check: it requests each row's records page and request form once, with an honest user agent that names this
    survey, and records what came back: the HTTP status, where it redirected, whether the page carries a captcha or
    bot-challenge script, and a SHA-256 of the body so a later run can tell whether the page changed.

    It never logs in, submits anything or retries past a block. A page that answers with a challenge is recorded
    as blocked, the same rule the hand survey followed. It writes `results/fetch.csv`.
    """)
    return (mo,)


@app.cell
def _():
    import hashlib
    import os
    import re
    import time
    from datetime import UTC, datetime
    from pathlib import Path

    import pandas as pd
    import requests

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("RESULTS_DIR", HERE / "results"))
    OUT.mkdir(parents=True, exist_ok=True)
    USER_AGENT = "Mozilla/5.0 (compatible; records-portal-intake-survey/1.0; +https://github.com/fulton-ring/agent-content-demos)"
    TIMEOUT_S = 25
    MAX_BODY = 2_000_000
    DELAY_S = float(os.environ.get("DELAY_SECONDS", "1"))
    return (
        DELAY_S,
        HERE,
        MAX_BODY,
        OUT,
        TIMEOUT_S,
        USER_AGENT,
        datetime,
        UTC,
        hashlib,
        pd,
        re,
        requests,
        time,
    )


@app.cell
def _(HERE, mo, pd):
    survey = pd.read_csv(HERE / "survey.csv", dtype=str, keep_default_na=False)
    assert survey["state"].is_unique and len(survey) == 51, "one row per state and DC"
    targets = pd.concat(
        [
            survey[["state", "records_page_url"]].rename(columns={"records_page_url": "url"}).assign(page="records"),
            survey[["state", "form_url"]].rename(columns={"form_url": "url"}).assign(page="form"),
        ]
    )
    targets = targets[targets["url"].str.startswith("http")].drop_duplicates("url").reset_index(drop=True)
    mo.md(f"{len(targets)} distinct URLs to fetch from {len(survey)} rows.")
    return survey, targets


@app.cell
def _(mo):
    mo.md(r"""
    **What counts as a challenge.** We look for the scripts and markers of the common bot walls and captcha
    widgets in the body: Google reCAPTCHA, hCaptcha, Cloudflare Turnstile and its "Just a moment" interstitial,
    Akamai and Imperva/Incapsula challenge pages. A captcha widget on a form page that otherwise loaded is a
    captcha, not a block; a page whose only content is a challenge, or a 403/429, is a block.
    """)
    return


@app.cell
def _(re):
    CAPTCHA = re.compile(r"recaptcha|hcaptcha|turnstile|cf-turnstile|captcha", re.I)
    CHALLENGE = re.compile(
        r"Just a moment\.\.\.|cf-chl|challenge-platform|_Incapsula_Resource|Request unsuccessful\. Incapsula"
        r"|Access Denied</title>|akamai.*?reference|bm-verify|Pardon Our Interruption",
        re.I | re.S,
    )
    return CAPTCHA, CHALLENGE


@app.cell
def _(
    CAPTCHA,
    CHALLENGE,
    DELAY_S,
    MAX_BODY,
    TIMEOUT_S,
    USER_AGENT,
    UTC,
    datetime,
    hashlib,
    pd,
    requests,
    targets,
    time,
):
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    rows = []
    for t in targets.itertuples():
        fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            r = session.get(t.url, timeout=TIMEOUT_S, allow_redirects=True)
        except requests.RequestException as err:
            rows.append(
                {
                    "state": t.state,
                    "page": t.page,
                    "url": t.url,
                    "status": 0,
                    "outcome": "error",
                    "error": type(err).__name__,
                    "fetched_at": fetched_at,
                }
            )
            continue
        body = r.content[:MAX_BODY]
        text = body.decode(r.encoding or "utf-8", errors="replace")
        challenge = bool(CHALLENGE.search(text))
        blocked = r.status_code in (401, 403, 429, 503) or (challenge and len(text) < 20_000)
        outcome = "blocked" if blocked else ("ok" if r.ok else "http_error")
        rows.append(
            {
                "state": t.state,
                "page": t.page,
                "url": t.url,
                "status": r.status_code,
                "outcome": outcome,
                "final_url": r.url,
                "bytes": len(r.content),
                "captcha_marker": bool(CAPTCHA.search(text)),
                "challenge_marker": challenge,
                "sha256": hashlib.sha256(r.content).hexdigest(),
                "error": "",
                "fetched_at": fetched_at,
            }
        )
        time.sleep(DELAY_S)
    fetch = pd.DataFrame(rows)
    return (fetch,)


@app.cell
def _(OUT, fetch, mo):
    fetch.to_csv(OUT / "fetch.csv", index=False)
    mo.vstack(
        [
            mo.md(f"Wrote `results/fetch.csv`: {len(fetch)} URLs. Outcomes:"),
            fetch["outcome"].value_counts().rename_axis("outcome").reset_index(),
            fetch,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
