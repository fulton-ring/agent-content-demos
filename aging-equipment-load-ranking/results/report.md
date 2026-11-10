# Plant 0: ten assets to bring to capital planning

Synthetic plant, 250 assets ({'motor': 120, 'switchgear': 90, 'transformer': 40}). Ranked by probability of failing in the next three years at today's metered load growing 4%/yr (bus D, the new line, twice that).

| # | Asset | Type | 3-yr failure chance | Age-only rank | Why it ranks here | Call |
|---|---|---|---|---|---|---|
| 1 | M-C249 | motor | 53% | 14 | 37 yrs old; at 115% of rating; 129% by year 3 (bus C); 0.13 normal lives used (test 6 yrs ago); risk mostly bearing/mechanical | **retest** |
| 2 | M-B233 | motor | 47% | 100 | 14 yrs old; at 102% of rating; 112% by year 3 (bus B); 0.21 normal lives used (test 4 yrs ago); risk mostly bearing/mechanical | **retest** |
| 3 | M-C137 | motor | 39% | 32 | 31 yrs old; at 47% of rating; 53% by year 3 (bus C); 0.01 normal lives used (test 3 yrs ago); risk mostly bearing/mechanical | **extend life** |
| 4 | M-A211 | motor | 37% | 12 | 30 yrs old; at 51% of rating; 0.01 normal lives used (test 0 yrs ago); risk mostly bearing/mechanical | **extend life** |
| 5 | M-B154 | motor | 37% | 80 | 19 yrs old; at 115% of rating; 126% by year 3 (bus B); 0.24 normal lives used (test 6 yrs ago); risk mostly bearing/mechanical | **retest** |
| 6 | M-C164 | motor | 31% | 61 | 23 yrs old; at 86% of rating; 96% by year 3 (bus C); 0.06 normal lives used (test 0 yrs ago); risk mostly bearing/mechanical | **extend life** |
| 7 | M-B162 | motor | 31% | 93 | 16 yrs old; at 58% of rating; 64% by year 3 (bus B); 0.01 normal lives used (test 5 yrs ago); risk mostly bearing/mechanical | **retest** |
| 8 | M-B160 | motor | 30% | 25 | 31 yrs old; at 65% of rating; 71% by year 3 (bus B); 0.03 normal lives used (test 0 yrs ago); risk mostly bearing/mechanical | **extend life** |
| 9 | M-B192 | motor | 29% | 85 | 18 yrs old; at 54% of rating; 59% by year 3 (bus B); 0.01 normal lives used (test 6 yrs ago); risk mostly bearing/mechanical | **retest** |
| 10 | M-C134 | motor | 29% | 83 | 19 yrs old; at 69% of rating; 77% by year 3 (bus C); 0.01 normal lives used (test 0 yrs ago); risk mostly bearing/mechanical | **extend life** |

Highest-ranked transformer: TX-A038, #101, 8.5% in 3 yrs; 28 yrs old; at 117% of rating; 1.38 normal lives used (test 3 yrs ago); risk mostly load/insulation; **replace**.  
Highest-ranked switchgear: SWG-C074, #121, 3.1% in 3 yrs; 32 yrs old; at 105% of rating; 118% by year 3 (bus C); 0.10 normal lives used (test 4 yrs ago); risk mostly load/insulation; **retest**.  

**How good is this list?** On 1,000 simulated plants like this one, the top ten caught 15% of the assets that failed within three years (in a single plant, 90% of the time between 4% and 27%); ranking by age alone caught 8%, ten at random 4%. The top 25 caught 28% (age alone 20%). Most failures it misses are motor bearing and mechanical failures that load and insulation tests don't predict.

**If load grows differently.** At 1%/yr instead of 4%, 8.1 of these ten stay in the top ten on average; at 8%/yr, 2.7.

**What it can't tell you.** Consequence of failure (a transformer outage costs more than a motor), spares and lead times, failures with no thermal cause, and anything about a real plant: every number here comes from a synthetic plant built from published IEEE failure rates and ageing curves.
