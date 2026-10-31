# OSM rules for this contribution

Read on 2026-10-31 from the OSM wiki (raw wikitext), the OSM Community Forum (public JSON), MapRoulette's docs
and openstreetmap.us. Quotes are verbatim. Nothing here was posted anywhere.

## The precedent that matters most

In March 2026 PowerGEM did almost exactly this: traced HIFLD substation points on imagery and uploaded them with
HIFLD names. They were "told to stop and go through the import process. All of the data we had uploaded was
reverted." ([forum thread 141961](https://community.openstreetmap.org/t/integration-of-substations-in-hifld-into-osm/141961),
started 2026-03-02.) Objections raised there:

- tracing from Google Street View (forbidden);
- duplicates and overlaps with existing ways, including a `disused:power` feature;
- bad names: "multiple name which are not names… 'LLC'… Please fix those and as well properly document your import";
- no changeset source or link: "Just posting a bit here does not give you a free pass";
- working "on behalf of the company" means the Organised Editing Guidelines apply: "That's exactly what the OEG are for".

PowerGEM then documented itself as organised editing ([thread 142145](https://community.openstreetmap.org/t/142145),
[wiki page](https://wiki.openstreetmap.org/wiki/Organised_Editing/Activities/Mapping_HIFLD_Substations)) and
stopped using any HIFLD field, even the name. One reply (Skunkman56, post 34) said: "Seems like this would be a good
challenge for MapRoulette and thereby avoid appearances of an import". Minh_Nguyen argued HIFLD names are usable
"as long as they don't override any existing names". Nobody raised security in either thread.

**Disclosure:** the HIFLD Next site's footer reads "Made by Fulton Ring". Our posts have to say so.

## Is this an import?

- [Import/Guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines) cover "importing data from external
  sources into the OpenStreetMap database". If it is an import, you **must** get permission for the data, write a
  wiki plan, get local buy-in, post to the forum with the `import` tag, wait 14 days and resolve concerns, and use a
  `<username>_Import` account.
- [Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct) covers
  "edits where changes are made to objects in the database without review individually by the person controlling
  the edits". It still advises discussing systematic changes in advance.
- The guidelines say nothing about MapRoulette or about using external data as hints. No official page says a
  MapRoulette hint list is or isn't an import. The [HIFLD wiki page](https://wiki.openstreetmap.org/wiki/HIFLD)
  lists Electric Power Transmission Lines among "Reference Datasets… aren't suitable for importing, but are still
  useful to use as reference when mapping."

**Our reading:** if every substation is drawn by a volunteer from imagery in a MapRoulette task, and no geometry
or attribute is copied over in bulk, it isn't an import or an automated edit. But because we're a company and
these are hints from an external dataset, the Organised Editing Guidelines apply. Expect the community to want:
an organised-editing wiki page, a forum discussion **before** the challenge goes live, and a changeset `source`
that names the hint data. Our package is built for that route, and the drafts ask for review first.

## Licence

- **HIFLD lines:** the data.gov record for "Electric Power Transmission Lines" shows
  `license: https://www.usa.gov/government-works`. The OSM wiki's HIFLD page says "Data License: Public Domain", and
  Import/Catalogue lists HIFLD the same way. HIFLD Next itself has no licence statement. It republishes HIFLD v1.0.0,
  so cite the federal record.
- **EIA-860M:** US federal, public domain. The [Legal FAQ](https://wiki.openstreetmap.org/wiki/Legal_FAQ) says
  "Only sources with compatible licenses - such as US Government information released into the public domain - may
  be used".
- **Utility, ISO and state-commission documents:** not cleared. The Legal FAQ: "Unless the data is genuinely offered
  without any restrictions on use at all (i.e. public domain), please contact the Licensing Working Group". We
  found no OSM page saying a name copied from such a document is a free fact. **So the MapRoulette file proposes
  `name`/`operator` only from HIFLD and EIA. Values from other documents are in the CSV as corroboration, flagged
  `osm_ok = no`.**
- **Points and outlines:** our own observations on Esri World Imagery. Esri: "Esri allowed the usage of Esri World
  Imagery (and its variants) in OSM mapping, without restrictions"
  ([wiki](https://wiki.openstreetmap.org/wiki/Esri)). Bing is also allowed ([wiki](https://wiki.openstreetmap.org/wiki/Bing_Maps)).
  Google is forbidden: "Can I trace data from Google Maps…? **No.**" (Legal FAQ). We used Esri only. MapYourGrid
  notes that about 25% of HIFLD line features cite OSM as a source, so HIFLD is partly downstream of OSM.

## Tagging ([Tag:power=substation](https://wiki.openstreetmap.org/wiki/Tag:power%3Dsubstation), [Key:substation](https://wiki.openstreetmap.org/wiki/Key:substation))

- `power=substation` is mandatory; `substation=*`, `voltage=*`, `name=*` are recommended; `operator`, `ref` are optional.
- "Most substations should be mapped as areas"; "Outdoor substations should be mapped as areas"
  ([guidelines](https://wiki.openstreetmap.org/wiki/Power_networks/Guidelines/Substations)).
- `voltage` in volts, highest first: `500000;230000`.
- `substation=transmission` for a step-down yard; `switching` when every line is the same voltage;
  `generation` for a plant's own yard. "`substation=transmission` wins if you're not able to find distinguished perimeters."
- `source` goes on the changeset, not on objects ([Key:source](https://wiki.openstreetmap.org/wiki/Key:source)).

## MapRoulette ([learn.maproulette.org](https://learn.maproulette.org/en-US/))

- A challenge can be created from a GeoJSON file. Line-by-line (RFC 7464) is preferred and plain FeatureCollection is accepted.
- Task ids: "Make sure your ids don't look like OSM ids… give your external id field a different name, like
  externalId". We use `externalId` (`hifld-node-…`).
- Instructions can use `{{property}}` from each task.
- Good tasks are "easy to solve (typically less than one minute); Do not require local knowledge".
- MapRoulette is an OSM US programme. No rule requires forum review before creating a challenge, but OSM US took a
  September 2026 MapRoulette import of EV chargers through forum review ([thread 147179](https://community.openstreetmap.org/t/147179)).

## Where to post (all as drafts; a founder posts)

- The forum thread above (US category).
- OpenStreetMap US: team@openstreetmap.us; Slack #utilities, #maproulette, #imports. There is no power working group.

## Security

- No OSM policy covers US substations. Forum threads ([127393](https://community.openstreetmap.org/t/127393),
  [138682](https://community.openstreetmap.org/t/138682)) treat it as depending on circumstances.
- MapYourGrid's practice note: "Do not map sensitive internal components such as control rooms, surveillance
  systems, or security details." We propose only the yard outline and the public tags.
