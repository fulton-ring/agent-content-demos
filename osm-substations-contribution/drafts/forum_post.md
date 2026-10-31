# DRAFT: not posted. For a founder to review, edit and post as a reply in the OSM Community Forum thread
# "Integration of Substations in HIFLD into OSM" (https://community.openstreetmap.org/t/integration-of-substations-in-hifld-into-osm/141961).
# Numbers are from outputs/run_log.txt (OSM checked 2026-10-31); re-run ./run.sh and update them before posting.

Hi all. I'm [founder name] from Fulton Ring, a small company that writes about public data. We also built
HIFLD Next (hifld.publicenvirodata.org), the site that republishes the retired federal HIFLD layers, so we have a
stake in HIFLD and want to say that up front.

I've read this thread and the follow-up on organised editing. We'd like to ask, before doing anything, whether a
much smaller and more cautious version of the same idea would be welcome.

**What we found.** We built substation points from where HIFLD's 230 kV+ transmission lines end and compared them
with OSM. 97% have an OSM substation within 1 km. None of the 180 that didn't (as of September) has been mapped
since. We looked at each of them on Esri World Imagery. To be clear about method: that look, and the
search of public records for names, were done by AI agents (Claude), and [founder: who reviewed the results, and how,
before posting]. Every edit would be made by a volunteer who checks the imagery themselves. What we saw:

- 12 points (10 distinct yards): a fenced yard is clearly visible where the lines end;
- 29: we couldn't tell, mostly power plants where the switchyard isn't obvious;
- 139: no yard. These are taps, wind farm fields or HIFLD errors, and we'd leave them out.

The method, the per-point list, and how a second, independent look agreed with the first on the same 50 points
(the same label on 45 of 50) are all public at
https://github.com/fulton-ring/agent-content-demos/tree/main/osm-substations-contribution.

**What we're proposing.** No import and no upload by us. A MapRoulette challenge of the 36 "yes" and
"unclear" places (after merging duplicates and dropping two that public records say are gone or a tap). Each
volunteer looks at Esri or Bing imagery, draws the fence line only if they see a yard, and skips the task otherwise. The draft instructions are in the folder. They ask mappers to:

- tag only `power=substation`, `substation=*` and `voltage=*`;
- add `name`/`operator` only where a US federal source (HIFLD, EIA, TVA, BLM), all public domain, gives one,
  never a company name with "LLC" and never overwriting a name already in OSM. Only 3 of the 10 yards get a name;
- not map anything inside the fence;
- put "Esri World Imagery; hint locations from HIFLD Transmission Lines (public domain)" in the changeset source.

**Our questions for you:**

1. Is a MapRoulette challenge of hint points the right route here, or would you want this run through the
   Import Guidelines anyway?
2. Should we write an Organised Editing page first, even though we wouldn't be editing ourselves?
3. Would you rather we leave `name` and `operator` out entirely, as PowerGEM decided to?
4. Any concerns about adding unmapped high-voltage yards at all? We've listed exactly which ones in the folder.

We won't create the challenge until this thread has had at least two weeks and the concerns are answered.

Thanks, [founder name]
