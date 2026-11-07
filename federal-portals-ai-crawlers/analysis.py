import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # Part 2: which federal datasets do AI agents get turned away from, and what do assistants say about them?

    Part 1 (`crawl.py`) read robots.txt and requested one dataset page on each of 100 federal data hosts with
    each AI agent's user agent, from two networks:

    - **anthropic-cloud**: the cloud container this spike was built in. Its public address is in Anthropic's own
      block (ARIN `NET-160-79-104-0-1`, 160.79.104.0/21, "Anthropic, PBC"). A firewall that checks a bot's address
      sees our ClaudeBot and Claude-User requests as genuine Anthropic traffic, and the others as impostors.
    - **github-actions**: a GitHub-hosted runner on Microsoft Azure, where no AI agent's address checks out.

    This notebook puts the two runs together, counts the blocks, then asks two search assistants a question only
    each blocked dataset answers and records whose pages they cite.
    """)
    return (mo,)


@app.cell
def _():
    import json
    import os
    import random
    import time
    from pathlib import Path
    from urllib.parse import urlsplit

    import pandas as pd
    import requests
    from pydantic import BaseModel

    HERE = Path(__file__).parent
    RESULTS = HERE / "results"
    ANSWERS = HERE / "answers"
    ANSWERS.mkdir(exist_ok=True)
    NETWORKS = os.environ.get("NETWORKS", "anthropic-cloud,github-actions").split(",")
    STARTED = time.time()
    return (
        ANSWERS,
        BaseModel,
        HERE,
        NETWORKS,
        RESULTS,
        STARTED,
        json,
        os,
        pd,
        random,
        requests,
        time,
        urlsplit,
    )


@app.cell
def _(HERE, NETWORKS, RESULTS, pd):
    hosts = pd.read_csv(HERE / "hosts.csv")
    robots = pd.concat([pd.read_csv(RESULTS / f"robots-{n}.csv") for n in NETWORKS], ignore_index=True)
    live = pd.concat([pd.read_csv(RESULTS / f"live-{n}.csv") for n in NETWORKS], ignore_index=True)
    assert set(robots["network"]) == set(NETWORKS) == set(live["network"]), "both networks' crawls are needed"
    AI_AGENTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User", "PerplexityBot"]
    return AI_AGENTS, hosts, live, robots


@app.cell
def _(AI_AGENTS, hosts, mo, pd, robots):
    # robots.txt is the same file from both networks unless a firewall hid it from one; take a block from either.
    _ai = robots[robots["agent"].isin([*AI_AGENTS, "Google-Extended"])]
    _readable = robots[robots["block_kind"] != "unreachable"]["host"].unique()
    _blocks = _ai[_ai["block_kind"].isin(["named", "catch-all"])]
    robots_blocked_hosts = sorted(_blocks["host"].unique())
    _kind_per_host = _blocks.groupby("host")["block_kind"].agg(lambda k: "named" if "named" in set(k) else "catch-all")
    _google_blocked = set(robots[(robots["agent"] == "Googlebot") & ~robots["page_allowed"]]["host"])
    _per_agent = (
        _blocks.drop_duplicates(["host", "agent"])
        .pivot_table(index="agent", columns="block_kind", values="host", aggfunc="count", fill_value=0)
        .reindex([*AI_AGENTS, "Google-Extended"], fill_value=0)
        .reset_index()
    )
    _detail = (
        _blocks.drop_duplicates(["host", "agent"])
        .groupby("host")
        .agg(agents=("agent", lambda a: ", ".join(a)), kind=("block_kind", lambda k: ", ".join(sorted(set(k)))))
        .assign(googlebot_blocked_too=lambda d: d.index.isin(_google_blocked))
        .reset_index()
    )
    robots_summary = {
        "hosts_checked": len(hosts),
        "robots_readable": len(_readable),
        "robots_blocking_hosts": len(robots_blocked_hosts),
        "robots_named_hosts": int((_kind_per_host == "named").sum()),
        "robots_catchall_only_hosts": int((_kind_per_host == "catch-all").sum()),
        "robots_ai_only_hosts": len(set(robots_blocked_hosts) - _google_blocked),
    }
    mo.vstack(
        [
            mo.md(f"""
    ## robots.txt

    Of {len(hosts)} hosts we could read robots.txt on **{len(_readable)}**. The rest answered with a firewall
    refusal, an HTML page or nothing, so their rules are unknown to us.

    **{len(robots_blocked_hosts)}** hosts disallow the dataset page for at least one AI agent. On
    **{robots_summary["robots_named_hosts"]}** of them a rule names an AI bot; on
    **{robots_summary["robots_catchall_only_hosts"]}** the block comes only from `User-agent: *`. Only
    **{robots_summary["robots_ai_only_hosts"]}** of the blocks keep AI agents out while letting Googlebot in, the
    pattern Blackburn counted on state and local sites; the others shut out every crawler from that path.
    """),
            _per_agent,
            _detail,
        ]
    )
    return robots_blocked_hosts, robots_summary


@app.cell
def _(mo):
    mo.md(r"""
    ## What the servers did

    A host **refuses an agent** on a network when the agent's request was refused or challenged there while the
    browser control got the page both before and after it. A host that refused the browser too turns away
    scripted clients from that network, whatever they call themselves, and isn't counted against any agent.
    """)
    return


@app.cell
def _(AI_AGENTS, NETWORKS, live, mo, pd):
    _wide = live.pivot_table(index=["network", "host"], columns="ua_label", values="outcome", aggfunc="first")
    _control_ok = (_wide["browser-before"] == "ok") & (_wide["browser-after"] == "ok")
    _turned_away = _wide[AI_AGENTS].isin(["refused", "challenge"]).mul(_control_ok, axis=0)
    refusals = _turned_away.stack().rename("refused").reset_index().rename(columns={"ua_label": "agent"})
    _by_agent = refusals.pivot_table(index="agent", columns="network", values="refused", aggfunc="sum").reindex(
        AI_AGENTS
    )
    _any = refusals.groupby(["network", "host"])["refused"].any()
    _control_blocked = (~_control_ok).groupby(level="network").sum()
    # The opposite case: the browser control was turned away but at least one AI agent got the page.
    _ai_let_in = ((_wide["browser-before"] != "ok") & (_wide[AI_AGENTS] == "ok").any(axis=1)).groupby(level="network")
    _ai_preferred = {n: int(v.sum()) for n, v in _ai_let_in}
    live_refusing_hosts = sorted(_any[_any].index.get_level_values("host").unique())
    _per_network = {n: int(_any[n].sum()) for n in NETWORKS}
    _edges = (
        live[live["outcome"].isin(["refused", "challenge"]) & live["ua_label"].isin(AI_AGENTS)]
        .merge(_any[_any].reset_index()[["network", "host"]], on=["network", "host"])
        .drop_duplicates(["network", "host"])
        .groupby(["network", "edge"])
        .size()
        .rename("hosts")
        .reset_index()
    )
    live_summary = {
        "live_refusing_hosts_any_network": len(live_refusing_hosts),
        **{f"live_refusing_hosts_{n}": v for n, v in _per_network.items()},
        **{f"control_blocked_{n}": int(_control_blocked[n]) for n in NETWORKS},
        **{f"ai_let_in_browser_not_{n}": _ai_preferred[n] for n in NETWORKS},
    }
    mo.vstack(
        [
            mo.md(f"""
    Hosts that refused or challenged at least one AI agent while letting the browser through:
    **{_per_network[NETWORKS[0]]}** from {NETWORKS[0]}, **{_per_network[NETWORKS[1]]}** from {NETWORKS[1]},
    **{len(live_refusing_hosts)}** from either. Hosts that refused the browser control too:
    {", ".join(f"{_control_blocked[n]} from {n}" for n in NETWORKS)}. On
    {" and ".join(f"**{_ai_preferred[n]}** from {n}" for n in NETWORKS)} of those, at least one AI agent got the
    page the browser was refused: the bot firewall lets known AI bots in and challenges an unknown scripted client.

    Hosts refusing each agent, per network:
    """),
            _by_agent.reset_index(),
            mo.md("Who answered the refusals (the edge network in the response headers):"),
            _edges,
        ]
    )
    return live_refusing_hosts, live_summary, refusals


@app.cell
def _(AI_AGENTS, NETWORKS, live, mo, pd):
    # Disagreement: the same host and user agent got a different outcome on the two networks.
    _labels = [*AI_AGENTS, "browser-before"]
    _cmp = live[live["ua_label"].isin(_labels)].pivot_table(
        index=["host", "ua_label"], columns="network", values="outcome", aggfunc="first"
    )
    _diff = _cmp[_cmp[NETWORKS[0]] != _cmp[NETWORKS[1]]].reset_index()
    disagreement = {
        "pairs_compared": len(_cmp),
        "pairs_disagreeing": len(_diff),
        "hosts_disagreeing": int(_diff["host"].nunique()),
    }
    mo.vstack(
        [
            mo.md(f"""
    ## Where the two networks disagree

    Of {len(_cmp)} host-and-user-agent pairs (six AI agents plus the browser), **{len(_diff)}** got a different
    outcome on the two networks, on **{disagreement["hosts_disagreeing"]}** hosts. Hosts that turn away every user
    agent, browser included, from one network only are blocking that network. Hosts where the same AI user agent gets in
    from one network and not the other are judging the agent together with where it comes from.
    """),
            _diff,
        ]
    )
    return (disagreement,)


@app.cell
def _(HERE, hosts, live, live_refusing_hosts, mo, pd, random, robots, robots_blocked_hosts):
    blocked = sorted(set(robots_blocked_hosts) | set(live_refusing_hosts))
    questions = pd.read_csv(HERE / "questions.csv")
    _missing = set(blocked) - set(questions["host"])
    assert not _missing, f"write a question for {_missing}"
    # Control: an equal number of open hosts (no agent blocked, browser control served on both networks), drawn
    # with a fixed seed from those with a question written.
    _browser = live[live["ua_label"].str.startswith("browser")]
    _browser_ok = set(_browser.groupby("host")["outcome"].agg(lambda o: (o == "ok").all()).loc[lambda x: x].index)
    _open = sorted((set(questions["host"]) & _browser_ok) - set(blocked))
    control = sorted(random.Random(218).sample(_open, min(len(blocked), len(_open))))
    asked = questions[questions["host"].isin([*blocked, *control])].merge(hosts, on="host")
    asked["group"] = asked["host"].map(lambda h: "blocked" if h in blocked else "open")
    # How each blocked host turns agents away: robots.txt shutting out every crawler (Googlebot too), robots.txt
    # naming AI bots, or only the server refusing.
    _all_crawlers = set(robots[(robots["agent"] == "Googlebot") & (robots["block_kind"] == "catch-all")]["host"])
    _named = set(robots[robots["block_kind"] == "named"]["host"])
    asked["how_blocked"] = asked["host"].map(
        lambda h: (
            "open"
            if h not in blocked
            else "robots: every crawler"
            if h in _all_crawlers
            else "robots: names AI bots"
            if h in _named
            else "server only"
        )
    )
    mo.vstack(
        [
            mo.md(f"""
    ## The assistant check

    **{len(blocked)}** hosts turn away at least one AI agent in robots.txt or at the server. For each we wrote a
    question that its dataset page answers (`questions.csv`), and the same for **{len(control)}** open hosts as a
    control. Each question goes to two assistants with web search on, through OpenRouter:

    - **Perplexity Sonar** (`perplexity/sonar`), whose index is built by PerplexityBot;
    - **GPT-5.6 Luna** with OpenAI's native web search (`openai/gpt-5.6-luna`, OpenRouter `web` plugin, engine
      `native`), whose index is built by OAI-SearchBot.

    Answers are saved in `answers/`; a rerun reads them instead of calling the models again unless
    `REFRESH_ANSWERS=1`.
    """),
            asked[["group", "how_blocked", "host", "agency", "question"]],
        ]
    )
    return (asked,)


@app.cell
def _(ANSWERS, BaseModel, asked, json, mo, os, requests, time):
    class Citation(BaseModel):
        url: str

    class Annotation(BaseModel):
        type: str
        url_citation: Citation | None = None

    class Message(BaseModel):
        content: str
        annotations: list[Annotation] | None = None

    class Choice(BaseModel):
        message: Message

    class Usage(BaseModel):
        cost: float = 0.0

    class Completion(BaseModel):
        model: str
        choices: list[Choice]
        usage: Usage

    MODELS = {"perplexity/sonar": {}, "openai/gpt-5.6-luna": {"plugins": [{"id": "web", "engine": "native"}]}}
    _refresh = os.environ.get("REFRESH_ANSWERS") == "1"
    _calls = 0
    for _model, _extra in MODELS.items():
        _path = ANSWERS / f"{_model.replace('/', '_')}.jsonl"
        _saved = (
            {}
            if _refresh or not _path.exists()
            else {r["host"]: r for r in map(json.loads, _path.read_text().splitlines())}
        )
        for _host, _q in zip(asked["host"], asked["question"], strict=True):
            if _host in _saved and _saved[_host]["question"] == _q:
                continue
            _key = os.environ.get("OPENROUTER_API_KEY")
            assert _key, "OPENROUTER_API_KEY is needed to ask questions that have no saved answer"
            for _attempt in range(3):
                _r = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {_key}"},
                    json={
                        "model": _model,
                        "messages": [{"role": "user", "content": _q}],
                        "usage": {"include": True},
                        **_extra,
                    },
                    timeout=180,
                )
                if _r.status_code == 200:
                    break
                time.sleep(5 * (_attempt + 1))
            _r.raise_for_status()
            _c = Completion.model_validate(_r.json())
            _saved[_host] = {
                "host": _host,
                "model": _model,
                "question": _q,
                "answer": _c.choices[0].message.content,
                "citations": [a.url_citation.url for a in _c.choices[0].message.annotations or [] if a.url_citation],
                "cost_usd": _c.usage.cost,
                "asked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _calls += 1
        _path.write_text("".join(json.dumps(_saved[h]) + "\n" for h in sorted(_saved)))
    answers = [
        json.loads(line) for m in MODELS for line in (ANSWERS / f"{m.replace('/', '_')}.jsonl").read_text().splitlines()
    ]
    answers = [a for a in answers if a["host"] in set(asked["host"])]
    mo.md(f"Model calls this run: **{_calls}**; answers on file for this question set: **{len(answers)}**.")
    return (answers,)


@app.cell
def _(answers, asked, mo, pd, urlsplit):
    # Domains that keep copies of federal data. HIFLD Next is ours; the rest are archives, research mirrors and
    # data-sharing sites.
    MIRRORS = (
        "publicenvirodata.org",
        "archive.org",
        "datalumos",
        "openicpsr.org",
        "icpsr.umich.edu",
        "edgi",
        "kaggle.com",
        "github.com",
        "githubusercontent.com",
        "huggingface.co",
        "data.world",
        "zenodo.org",
        "figshare.com",
        "dataverse",
        "socrata.com",
        "opendatasoft.com",
        "arcgis.com",
        "dataset.science",
    )

    def registrable(host: str) -> str:
        """usgs.gov from waterdata.usgs.gov; army.mil style too. Good enough for .gov and .mil hosts."""
        return ".".join(host.lower().removeprefix("www.").split(".")[-2:])

    def citation_class(url: str, dataset_host: str) -> str:
        netloc = urlsplit(url).netloc.lower().split(":")[0]
        if netloc == dataset_host:
            return "the dataset host"
        if registrable(netloc) == registrable(dataset_host):
            return "same agency, other host"
        if any(m in netloc for m in MIRRORS):
            return "mirror"
        if netloc.endswith((".gov", ".mil")):
            return "other government"
        return "other"

    _group = dict(zip(asked["host"], asked["group"], strict=True))
    _rows = []
    for _a in answers:
        _classes = {citation_class(u, _a["host"]) for u in _a["citations"]}
        if not _classes:
            _best = "nothing"
        elif _classes & {"the dataset host", "same agency, other host"}:
            _best = "agency"
        elif "mirror" in _classes:
            _best = "mirror"
        else:
            _best = "other source"
        _rows.append(
            {
                "group": _group[_a["host"]],
                "model": _a["model"],
                "host": _a["host"],
                "cites_dataset_host": "the dataset host" in _classes,
                "cites": _best,
                "n_citations": len(_a["citations"]),
                "cost_usd": _a["cost_usd"],
            }
        )
    cited = pd.DataFrame(_rows)
    _share = (
        cited.groupby(["group", "model"])["cites"]
        .value_counts(normalize=True)
        .mul(100)
        .round(0)
        .unstack(fill_value=0)
        .reset_index()
    )
    _how = dict(zip(asked["host"], asked["how_blocked"], strict=True))
    cited["how_blocked"] = cited["host"].map(_how)
    _host_share = (
        cited.pivot_table(index="how_blocked", columns="model", values="cites_dataset_host", aggfunc="mean")
        .mul(100)
        .round(0)
        .assign(hosts=cited.groupby("how_blocked")["host"].nunique())
        .reset_index()
    )
    mo.vstack(
        [
            mo.md("""
    ### Whose pages the assistants cite

    Each answer is put in the best class among its citations: **agency** (the dataset host, or another host of the
    same agency), else **mirror**, else **other source**, else **nothing** (no citations). Shares in percent:
    """),
            _share,
            mo.md("""
    Citing the agency is the norm either way, so the sharper measure is whether an answer cites **the dataset
    host itself**. Percent of answers that do, by how the host blocks:
    """),
            _host_share,
        ]
    )
    return (cited,)


@app.cell
def _(
    NETWORKS,
    RESULTS,
    STARTED,
    cited,
    disagreement,
    json,
    live,
    live_summary,
    mo,
    robots_summary,
    time,
):
    _blocked = cited[cited["group"] == "blocked"]
    summary = {
        **robots_summary,
        **live_summary,
        **disagreement,
        "blocked_answers": len(_blocked),
        "blocked_cites_agency_pct": round(100 * (_blocked["cites"] == "agency").mean(), 1),
        "blocked_cites_mirror_pct": round(100 * (_blocked["cites"] == "mirror").mean(), 1),
        "blocked_cites_nothing_pct": round(100 * (_blocked["cites"] == "nothing").mean(), 1),
        "cites_dataset_host_pct": {
            k: round(100 * float(v), 1) for k, v in cited.groupby("how_blocked")["cites_dataset_host"].mean().items()
        },
        "model_cost_usd": round(cited["cost_usd"].sum(), 4),
        "crawl_requests": len(live),
        "crawl_seconds_per_network": {
            n: round(float(live[live["network"] == n]["seconds"].sum()), 1) for n in NETWORKS
        },
        "analysis_seconds": round(time.time() - STARTED, 1),
    }
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    mo.md(
        "## Headline numbers\n\nWritten to `results/summary.json`:\n\n```json\n"
        + json.dumps(summary, indent=2)
        + "\n```"
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show, and what didn't work

    - We send each agent's user agent from our own addresses. A firewall that checks addresses treats our
      OpenAI and Perplexity requests as impostors on both networks, so a refusal of those is an upper bound on what
      the real bots see. For Claude user agents the anthropic-cloud network is the real thing, address and all.
    - A bot-check page we couldn't get past (we didn't try) hides the dataset from scripted clients on that network
      whatever their name, so those hosts count as neither open nor blocked to AI.
    - One request per agent per page is a snapshot. Rate limits and firewall scoring change by the hour.
    - We test one dataset page per host; a robots.txt can block one path and allow another.
    - Two assistants and one question per dataset is a small sample; read the shares as a direction, not a rate.
    """)
    return


if __name__ == "__main__":
    app.run()
