import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # Part 1: do federal data portals turn away AI crawlers?

    Josh Blackburn's October 2026 census of 15,331 state and local .gov domains found hundreds that block ChatGPT
    search while letting Google in, mostly through a catch-all rule rather than a rule naming the bot. He left
    federal domains out. This notebook runs the same check on 100 federal data hosts, in two ways:

    1. **robots.txt.** For each host we read robots.txt and ask, for each AI agent's token, whether it may fetch
       the host's dataset page. A block is **named** if a `User-agent` line names the bot, or **catch-all** if the
       bot falls through to `User-agent: *`. Googlebot is checked as a control.
    2. **What the server does.** We request the dataset page once with each AI agent's user-agent string and
       record what comes back: the page, a refusal (403, 429 and the like) or a bot-challenge page. A plain
       browser user agent is sent first and last as the control, so a refusal counts against the AI agent only
       when the browser got through from the same network.

    The notebook runs on two networks (set `NETWORK`), and part 2 (`analysis.py`) compares them. It writes
    `results/robots-<network>.csv` and `results/live-<network>.csv`.
    """)
    return (mo,)


@app.cell
def _():
    import os
    import re
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from urllib.parse import urlsplit

    import pandas as pd
    import requests
    from protego import Protego

    HERE = Path(__file__).parent
    NETWORK = os.environ.get("NETWORK", "local")
    OUT = Path(os.environ.get("RESULTS_DIR", HERE / "results"))
    OUT.mkdir(parents=True, exist_ok=True)
    DELAY_S = float(os.environ.get("DELAY_SECONDS", "2"))
    TIMEOUT_S = 20
    MAX_BODY = 300_000
    WORKERS = 8
    STARTED = time.time()
    return (
        DELAY_S,
        MAX_BODY,
        NETWORK,
        OUT,
        Protego,
        STARTED,
        TIMEOUT_S,
        ThreadPoolExecutor,
        WORKERS,
        pd,
        re,
        requests,
        time,
        urlsplit,
        HERE,
    )


@app.cell
def _(HERE, mo, pd):
    hosts = pd.read_csv(HERE / "hosts.csv")
    assert hosts["host"].is_unique, "one row per host"
    assert len(hosts) <= 100
    mo.vstack(
        [
            mo.md(f"""
    ## The hosts

    {len(hosts)} federal data hosts from {hosts["agency"].nunique()} agencies, each with one dataset page that a
    browser loads. The list is in `hosts.csv`: catalogs (data.gov, ScienceBase), agency data portals (OpenFEMA,
    CDC WONDER, data.census.gov, Envirofacts), agency ArcGIS hubs, APIs and plain agency pages that host downloads.
    """),
            hosts,
        ]
    )
    return (hosts,)


@app.cell
def _(mo, pd):
    # Published user-agent strings: OpenAI (developers.openai.com/api/docs/bots), Perplexity
    # (docs.perplexity.ai/guides/bots). Anthropic names its tokens but doesn't publish full strings; these follow the
    # form seen in server logs. Google-Extended and Googlebot are robots.txt tokens only here: Google-Extended never
    # fetches pages, and we don't impersonate Googlebot.
    agents = pd.DataFrame(
        [
            (
                "GPTBot",
                "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.4; +https://openai.com/gptbot",
            ),
            (
                "OAI-SearchBot",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36; compatible; OAI-SearchBot/1.4; +https://openai.com/searchbot",
            ),
            (
                "ChatGPT-User",
                "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
            ),
            (
                "ClaudeBot",
                "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; "
                "+claudebot@anthropic.com)",
            ),
            (
                "Claude-User",
                "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; "
                "+Claude-User@anthropic.com)",
            ),
            ("PerplexityBot", "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)"),
            ("Google-Extended", None),
            ("Googlebot", None),
        ],
        columns=["agent", "user_agent"],
    )
    BROWSER_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/141.0.0.0 Safari/537.36"
    )
    ROBOTS_UA = "federal-portals-ai-crawlers/0.1 (research; +https://github.com/fulton-ring/agent-content-demos)"
    mo.vstack(
        [mo.md("## The agents\n\nGooglebot is the control for robots.txt; a browser is the control live."), agents]
    )
    return BROWSER_UA, ROBOTS_UA, agents


@app.cell
def _(DELAY_S, ROBOTS_UA, TIMEOUT_S, ThreadPoolExecutor, WORKERS, hosts, mo, requests, time):
    def fetch_robots(host: str) -> dict:
        """One robots.txt request. RFC 9309: a 4xx means no rules; a 5xx or no answer means assume full disallow."""
        url = f"https://{host}/robots.txt"
        try:
            r = requests.get(url, headers={"User-Agent": ROBOTS_UA}, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            return {"host": host, "robots_status": None, "robots_error": type(e).__name__, "robots_text": ""}
        finally:
            time.sleep(DELAY_S)
        text = r.text if r.status_code == 200 else ""
        # A 200 that is an HTML page (a firewall block or a soft 404) holds no rules, and we can't see the real file.
        is_html = text.lstrip().lower().startswith(("<!doctype", "<html"))
        return {
            "host": host,
            "robots_status": r.status_code,
            "robots_error": "html" if is_html else "",
            "robots_text": "" if is_html else text,
        }

    with ThreadPoolExecutor(WORKERS) as _pool:
        robots_raw = list(_pool.map(fetch_robots, hosts["host"]))
    mo.md(f"Fetched robots.txt for {len(robots_raw)} hosts.")
    return (robots_raw,)


@app.cell
def _(NETWORK, OUT, Protego, agents, hosts, mo, pd, re, robots_raw, urlsplit):
    _rows = []
    for _host, _url, _raw in zip(hosts["host"], hosts["dataset_url"], robots_raw, strict=True):
        assert _raw["host"] == _host
        _text = _raw["robots_text"]
        _status = _raw["robots_status"]
        # We can't see the rules when there is no answer, a 5xx, a firewall refusal or an HTML page instead of the
        # file. (RFC 9309 tells crawlers to treat 401/403 as "no rules", but for us they mean "unknown".)
        _unreachable = _status is None or _status >= 500 or _status in (401, 403, 429) or _raw["robots_error"] == "html"
        _parser = Protego.parse(_text)
        # Tokens a group names explicitly, lowercased, so we can tell a named block from a catch-all one.
        _named = {m.lower() for m in re.findall(r"(?im)^\s*user-agent\s*:\s*([^\s#]+)", _text)}
        _parts = urlsplit(_url)
        for _agent in agents["agent"]:
            _page_ok = _parser.can_fetch(_url, _agent)
            _root_ok = _parser.can_fetch(f"{_parts.scheme}://{_parts.netloc}/", _agent)
            if _unreachable:
                _kind = "unreachable"
            elif _page_ok:
                _kind = "allowed"
            else:
                _kind = "named" if _agent.lower() in _named else "catch-all"
            _rows.append(
                {
                    "network": NETWORK,
                    "host": _host,
                    "agent": _agent,
                    "robots_status": _status,
                    "robots_error": _raw["robots_error"],
                    "has_rules": bool(_text.strip()),
                    "names_agent": _agent.lower() in _named,
                    "page_allowed": _page_ok,
                    "site_root_allowed": _root_ok,
                    "block_kind": _kind,
                }
            )
    robots = pd.DataFrame(_rows)
    robots.to_csv(OUT / f"robots-{NETWORK}.csv", index=False)

    _unreadable = robots[robots["block_kind"] == "unreachable"]["host"].nunique()
    _ai = robots[~robots["agent"].isin(["Googlebot"])]
    _blocked_hosts = _ai[_ai["block_kind"].isin(["named", "catch-all"])]["host"].unique()
    _by_agent = (
        robots.pivot_table(index="agent", columns="block_kind", values="host", aggfunc="count", fill_value=0)
        .reindex(agents["agent"])
        .reset_index()
    )
    mo.vstack(
        [
            mo.md(f"""
    ## robots.txt results ({NETWORK})

    - Hosts with robots.txt rules: **{robots.groupby("host")["has_rules"].first().sum()}** of {len(hosts)}
    - Hosts whose robots.txt we couldn't read (no answer, 5xx, 401/403/429 or an HTML page): **{_unreadable}**
    - Hosts that block at least one AI agent from the dataset page: **{len(_blocked_hosts)}**

    Blocks per agent, by kind (named = a group names the bot; catch-all = it falls under `User-agent: *`):
    """),
            _by_agent,
        ]
    )
    return (robots,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Live responses

    Each host gets its dataset page requested with the browser control, then each AI agent's user agent, then the
    browser again, one request each, with a pause between them. Hosts run in parallel, requests to one host don't.

    We classify what comes back from the status code and from markers that bot firewalls put in their pages:

    - **ok**: a 2xx after redirects with no challenge markers;
    - **challenge**: a bot-check interstitial (Cloudflare, Akamai, AWS WAF, Imperva, F5, DataDome, PerimeterX);
    - **refused**: 401, 403, 406, 429, 451 or a 5xx with no challenge markers;
    - **not found**: 404 or 410; **error**: no answer (timeout, reset, TLS).

    We also record which edge network answered (from the response headers), to see whether blocks come from
    firewall defaults.
    """)
    return


@app.cell
def _(BROWSER_UA, DELAY_S, MAX_BODY, TIMEOUT_S, ThreadPoolExecutor, WORKERS, agents, hosts, re, requests, time):
    CHALLENGE_MARKERS = {
        "cloudflare": r"cf-chl|challenge-platform|<title>just a moment|attention required! \| cloudflare",
        "akamai": r"errors\.edgesuite\.net|<title>access denied</title>|_abck|ak-challenge",
        "aws-waf": r"awswaf|aws-waf-token|challenge\.js",
        "imperva": r"_incapsula_resource|incapsula incident",
        "f5": r"the requested url was rejected\. please consult with your administrator",
        "datadome": r"captcha-delivery\.com|geo\.captcha-delivery",
        "perimeterx": r"px-captcha|_pxhd",
        "captcha": r"g-recaptcha|h-captcha|hcaptcha\.com|turnstile",
    }

    def edge_of(headers: requests.structures.CaseInsensitiveDict) -> str:
        server = headers.get("server", "").lower()
        if "cf-ray" in headers or "cloudflare" in server:
            return "cloudflare"
        if "akamai" in server or "x-akamai-transformed" in headers or "akamai-grn" in headers:
            return "akamai"
        if "x-iinfo" in headers or "incap" in headers.get("x-cdn", "").lower():
            return "imperva"
        if "x-amz-cf-id" in headers or "cloudfront" in server or "awselb" in server:
            return "aws"
        if "x-served-by" in headers and "cache-" in headers.get("x-served-by", ""):
            return "fastly"
        return server.split("/")[0] or "unknown"

    def classify(status: int, body: str) -> tuple[str, str]:
        head = body[:MAX_BODY].lower()
        for vendor, pattern in CHALLENGE_MARKERS.items():
            # Challenge markers only count on short pages or non-2xx answers; a big 2xx page that loads a captcha
            # script for a form is a real page.
            if re.search(pattern, head) and (status >= 300 or len(body) < 20_000):
                return "challenge", vendor
        if 200 <= status < 300:
            return "ok", ""
        if status in (404, 410):
            return "not found", ""
        if status in (401, 403, 406, 429, 451) or status >= 500:
            return "refused", ""
        return "other", ""

    def fetch_page(url: str, label: str, ua: str) -> dict:
        t0 = time.time()
        try:
            r = requests.get(
                url,
                headers={"User-Agent": ua, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"},
                timeout=TIMEOUT_S,
                stream=True,
            )
            body = r.raw.read(MAX_BODY, decode_content=True).decode(r.encoding or "utf-8", errors="replace")
            r.close()
        except requests.RequestException as e:
            return {
                "ua_label": label,
                "status": None,
                "outcome": "error",
                "vendor": "",
                "edge": "",
                "final_url": "",
                "bytes": 0,
                "error": type(e).__name__,
                "seconds": round(time.time() - t0, 2),
            }
        outcome, vendor = classify(r.status_code, body)
        return {
            "ua_label": label,
            "status": r.status_code,
            "outcome": outcome,
            "vendor": vendor,
            "edge": edge_of(r.headers),
            "final_url": r.url,
            "bytes": len(body),
            "error": "",
            "seconds": round(time.time() - t0, 2),
        }

    _live_agents = agents.dropna(subset=["user_agent"])
    SEQUENCE = [
        ("browser-before", BROWSER_UA),
        *zip(_live_agents["agent"], _live_agents["user_agent"], strict=True),
        ("browser-after", BROWSER_UA),
    ]

    def probe_host(row: tuple[str, str]) -> list[dict]:
        host, url = row
        out = []
        for label, ua in SEQUENCE:
            out.append({"host": host, **fetch_page(url, label, ua)})
            time.sleep(DELAY_S)
        return out

    with ThreadPoolExecutor(WORKERS) as _pool:
        live_raw = [
            r for rows in _pool.map(probe_host, zip(hosts["host"], hosts["dataset_url"], strict=True)) for r in rows
        ]
    return (live_raw,)


@app.cell
def _(NETWORK, OUT, STARTED, live_raw, mo, pd, time):
    live = pd.DataFrame(live_raw)
    live.insert(0, "network", NETWORK)
    live.to_csv(OUT / f"live-{NETWORK}.csv", index=False)

    _wide = live.pivot(index="host", columns="ua_label", values="outcome")
    _control_ok = (_wide["browser-before"] == "ok") & (_wide["browser-after"] == "ok")
    _ai_cols = [c for c in _wide.columns if not c.startswith("browser")]
    _refuses_ai = {a: int(((_wide[a].isin(["refused", "challenge"])) & _control_ok).sum()) for a in _ai_cols}
    _control_blocked = int(_wide["browser-before"].isin(["refused", "challenge"]).sum())
    mo.vstack(
        [
            mo.md(f"""
    ### Live results ({NETWORK})

    - Requests sent: **{len(live)}** to {live["host"].nunique()} hosts in {time.time() - STARTED:.0f} s.
    - Hosts where the browser control got the page both times: **{int(_control_ok.sum())}**
    - Hosts that refused or challenged the browser control too (they turn away scripted clients from this network,
      whatever the user agent): **{_control_blocked}**

    Hosts that refused or challenged each AI agent while the browser control got through:
    """),
            pd.DataFrame({"agent": list(_refuses_ai), "hosts_refusing": list(_refuses_ai.values())}),
            mo.md("Outcome per host and user agent:"),
            _wide.reset_index(),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
