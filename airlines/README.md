# Global airline directory

This package is a worldwide descriptive airline directory generated from Wikidata's structured data.

## Fields

Each record includes a stable Wikidata entity ID, English label, available IATA and ICAO designators, callsigns, country labels, inception/dissolution dates where recorded, and a conservative operating-status field.

`not_verified` means the source does not establish that the airline currently operates. It must not be interpreted as active. A recorded dissolution date is represented as `dissolved`.

## Source and licence

- Source: https://www.wikidata.org/
- Structured-data licence: CC0-1.0 / public domain.
- Wikidata licensing policy: https://www.wikidata.org/wiki/Wikidata:Licensing
- Access method: Wikidata Query Service, https://query.wikidata.org/sparql

The scheduled workflow refreshes this directory weekly. The app-facing dataset is registered in `navigation_manifest.json` and can be downloaded only when the manifest entry is marked available and its SHA-256 checksum matches.

## Scope and limitations

This is an entity directory, not a live airline registry, timetable, schedule, route network, fleet list, or proof of current operations. Wikidata coverage and field completeness vary. The dataset intentionally does not infer current status from missing dissolution dates.

The existing OpenFlights route snapshot is a separate historical dataset: its provider says route updates stopped in June 2014. It is not merged into this directory or represented as current airline service. Route-network publication requires a separate source and licence review.

No SID, STAR, approach, AIP, or procedure content is collected by this workflow.
