# Do federal data portals turn away AI crawlers and agents?

Issue [#218](https://github.com/fulton-ring/agent-content-demos/issues/218). Josh Blackburn's October 2026 census
of 15,331 state and local .gov domains found hundreds that block ChatGPT search, mostly by accident. He left federal
domains out. We checked 100 federal data hosts: their robots.txt, what their servers return to each AI agent, from
two networks, and what two search assistants cite when asked about the datasets behind the blocks.

**Short answer: few federal data hosts block AI agents on purpose, and blocks rarely keep a dataset out of answers.**
9 of 100 hosts disallow an AI agent in robots.txt. Only 3 name AI bots; the other 6 shut out every crawler,
Googlebot included. 14 hosts refuse at least one AI user agent at the server while serving a browser. The bigger
pattern runs the other way: on 10 hosts, the bot firewall challenged our browser control but let at least one AI
agent's user agent through (6 from the second network). Assistants still cited the agency for 97% of questions about
blocked datasets. The block that does hide a dataset host is the old "Disallow: /" for everyone: those hosts were
cited in a third of answers, against 95 to 100% for every other group.

## Run it

```bash
./run.sh                 # crawl from this network (about 5 min), then the analysis; needs uv
SKIP_CRAWL=1 ./run.sh    # the analysis only, from the committed crawl results
```

`OPENROUTER_API_KEY` is needed only for questions with no saved answer in `answers/`. A rerun reads the saved
answers, so it costs nothing. A live re-crawl can drift; if it puts a new host in the blocked set, that host has no
saved answer and the run needs a key. `REFRESH_ANSWERS=1` asks the assistants again (about $1.25). Set `NETWORK` to name
the network you crawl from.

## What's here

- `hosts.csv`: the 100 hosts (33 agencies), each with one dataset page that a browser loads.
- `crawl.py` (part 1, marimo): reads robots.txt with [protego](https://github.com/scrapy/protego), Scrapy's
  Google-spec parser, for GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, Claude-User, PerplexityBot,
  Google-Extended and Googlebot (as control). It then requests each dataset page once per AI user agent, with a
  browser user agent first and last as the control and a 2-second pause between requests to the same host.
  Writes `results/robots-<network>.csv` and `results/live-<network>.csv`.
- `analysis.py` (part 2, marimo): joins the two networks, counts blocks and disagreements, asks the assistants and
  classifies their citations. Writes `results/summary.json`; `outputs/analysis.html` is the rendered notebook.
- `questions.csv`: one question per host that its dataset page answers. `answers/`: every model answer with its
  citations and cost.
- `second-network.yml`: the GitHub Actions workflow that ran `crawl.py` from the second network. It lived in
  `.github/workflows/` only while the spike branch needed the run.

## The two networks

- **anthropic-cloud**: the container this was built in. Its address, 160.79.106.134, is in `NET-160-79-104-0-1`
  (160.79.104.0/21), registered to Anthropic, PBC (ARIN RDAP). So a firewall that verifies bots by address sees our
  Claude user agents as the real thing.
- **github-actions**: a GitHub-hosted runner at 52.161.51.65 (Microsoft), outside OpenAI's published SearchBot
  ranges. No AI agent's address checks out here.

## Results (from the run in `results/`, 2026-11-07)

| | |
|---|---|
| Hosts checked | 100 |
| robots.txt readable (either network) | 82; the other 18 returned a firewall 403, an HTML page or nothing |
| Hosts disallowing ≥1 AI agent from the dataset page | **9**: 3 named, 6 catch-all |
| ...of which keep AI out but let Googlebot in | 3 (civilrightsdata.ed.gov, data.hrsa.gov, sciencebase.gov) |
| Hosts refusing ≥1 AI user agent while serving the browser | **14** from anthropic-cloud, **12** from github-actions |
| Hosts refusing the browser control too | 15 / 21 |
| ...where an AI user agent got in anyway | **10** / 6 |
| Host and user agent pairs that disagree between networks | 66 of 700, on 19 hosts |
| Crawl | 1,600 requests, about 5 min per network, $0 |
| Assistant check | 76 answers, $1.25 on OpenRouter |

**Named blocks look like copied templates.** The Civil Rights Data Collection, the site Transluce saw agents hit
200,000 times, names GPTBot, ChatGPT-User, ClaudeBot, Google-Extended and the 2023-era `anthropic-ai`, but not
OAI-SearchBot, Claude-User or PerplexityBot. HRSA names 26 bots in one group, Bingbot among them. ScienceBase's file
is Cloudflare's managed robots.txt (`Content-Signal: search=yes,ai-train=no`), a firewall default.

**Catch-all blocks shut out everyone.** api.weather.gov, enviro.epa.gov, quickstats.nass.usda.gov,
www.nass.usda.gov, www.spc.noaa.gov and mrdata.usgs.gov disallow `/` to all crawlers. On mrdata the cause is two
`User-agent: *` groups that merge into one under the Google spec, which looks accidental.

**Server refusals, by agent** (anthropic-cloud / github-actions): GPTBot 10 / 7, ClaudeBot 9 / 8, ChatGPT-User
7 / 5, PerplexityBot 5 / 4, OAI-SearchBot 4 / 2, Claude-User 2 / 2. Patterns: four Socrata portals (data.cdc.gov,
data.transportation.gov, healthdata.gov, data.va.gov) refuse ClaudeBot and nothing else. NOAA's NHC, NDBC and SPC
refuse GPTBot and ChatGPT-User. ScienceBase
(Cloudflare) refuses all but ChatGPT-User. waterdata.usgs.gov refuses every AI user agent except Claude-User from
Anthropic's network; from Azure it challenges the browser too.

**Where the networks disagree.** Five hosts (broadbandmap.fcc.gov, collegescorecard.ed.gov, earthdata.nasa.gov,
www.nrc.gov, www.msha.gov) served every request from Anthropic's network and turned away every request, browser
included, from Azure. That block goes by network, not by agent. On four Akamai sites (www.cdc.gov, wonder.cdc.gov,
www.bls.gov, www.ssa.gov), the browser and PerplexityBot were challenged from both networks. The OpenAI user agents
got in from Azure but not from Anthropic's network, and the Claude user agents got in from both. The firewall judges
a user agent together with the network it comes from, so a crawl from one network would have misreported these
hosts.

**Assistants** (Perplexity Sonar, and GPT-5.6 Luna with OpenAI's native web search), 19 blocked hosts and 19 open
controls, one question each:

| How the host blocks | hosts | answers citing the dataset host itself |
|---|---|---|
| open (control) | 19 | 97% |
| robots.txt names AI bots | 3 | 100% |
| server refuses some AI agents only | 10 | 95% |
| robots.txt disallows every crawler | 6 | **33%** |

For the blocked hosts, 97% of answers cited the agency (that host or another of the same agency), 0% a mirror and
0% nothing. Named robots.txt blocks didn't stop either assistant citing the host. Search indexes and user-triggered
fetches don't depend on the training crawlers those rules name.

## What it doesn't show

- We sent each agent's user agent from our own addresses. A firewall that verifies addresses would treat the real
  bots differently, so live refusals of OpenAI and Perplexity user agents are an upper bound. We didn't try to get
  past any bot check.
- One dataset page per host and one request per agent: robots.txt can block one path and allow another, and
  firewall scoring changes by the hour. A rerun from the same network moved one host in and out of the count
  (13 then 14 from anthropic-cloud).
- 18 hosts' robots.txt couldn't be read from either network, so 9 is a floor for robots.txt blocks.
- Two assistants and one question per dataset is a small sample. No answer cited HIFLD Next or another mirror,
  partly because the blocked datasets here aren't the HIFLD layers it preserves.
- The mirror list and the "same agency" rule (same registrable domain, e.g. `usgs.gov`) are simple heuristics in
  `analysis.py`.

## What we looked at first

protego for robots.txt, because Python's `urllib.robotparser` uses first-match rather than the longest-match rule
of RFC 9309 and Google's parser. We found no maintained library that labels bot-challenge pages, so `crawl.py`
matches the markers that Cloudflare, Akamai, AWS WAF, Imperva, F5, DataDome and PerimeterX put in their pages.
User-agent strings come from OpenAI's and Perplexity's bot pages. Anthropic names its tokens but publishes no full
strings, so ours follow the form seen in server logs.
