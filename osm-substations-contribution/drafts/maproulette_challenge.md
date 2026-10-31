# DRAFT: not created. A founder reviews this and creates the challenge only after the forum discussion.

## Challenge name

US: unmapped 230 kV+ substations at the ends of HIFLD transmission lines

## Short description

Draw substations that aerial imagery shows at the end of high-voltage lines, where OSM has no substation yet.

## Full description

Each task is a point where a 230 kV or higher transmission line in the US federal HIFLD dataset (public domain,
via HIFLD Next) ends, but OpenStreetMap has no `power=substation` within 1 km. We looked at each point on Esri World
Imagery and kept only those where a fenced yard with electrical equipment is visible, or where we couldn't tell.

The points are **hints, not data to copy**. Please trace only what you can see on Esri World Imagery or Bing, and
skip the task if you see no substation. HIFLD is often out of date, and about half of its line ends are not
substations at all.

The imagery check and the records search behind the hints were done by AI agents (Claude) and reviewed by
[founder: who]; nothing here is edited into OSM automatically. This challenge was prepared by Fulton Ring, a small
company that writes about public data. Fulton Ring also built the HIFLD Next website that republishes the federal data. How the points were found, and every source, is in
[the project folder](https://github.com/fulton-ring/agent-content-demos/tree/main/osm-substations-contribution)
and the forum thread "Integration of Substations in HIFLD into OSM".

## Changeset comment and source

- Comment: `Add substation traced from imagery #maproulette #hifld-substations`
- Source: `Esri World Imagery; hint locations from HIFLD Transmission Lines (public domain)`

## Task instructions (mustache fields come from each task's properties)

**{{externalId}}**: HIFLD says lines of **{{hifld_voltage_kv}} kV** end here. Our imagery check: *{{imagery_verdict}}*
({{imagery_note}}), Esri imagery dated {{imagery_date}}.

1. Turn on **Esri World Imagery** (or Bing). Do not use Google or any other source.
2. Look within about 500 m of the point for a fenced yard with transformers, breakers or busbars where the lines end.
3. If there is one and OSM doesn't already have it:
   - draw the fence line as a closed way;
   - tag `power=substation` and `substation={{proposed_substation}}`;
   - add `voltage={{proposed_voltage}}` if you're comfortable, highest first, in volts;
   - add `name={{proposed_name}}` and `operator={{proposed_operator}}` **only if these fields aren't empty**.
     They come from US federal sources (HIFLD, EIA, TVA, BLM), which are public domain. Don't overwrite a name
     already in OSM.
4. If the yard is part of a power plant, use `substation=generation` and draw only the switchyard.
5. If the lines end inside the yard, you may connect them, but don't redraw lines.
6. Don't map anything inside the fence except the outline. Don't map gates, cameras, control buildings or other
   security details.
7. Mark the task **Not an issue** if there's no substation, **Too hard / couldn't see** if the imagery is unclear,
   and **Already fixed** if OSM already has it.

[select "What did you find?" name="found" values="substation drawn,plant switchyard drawn,no substation,already mapped,imagery unclear"]
