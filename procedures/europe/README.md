# European procedure data status

## Current position

FlightTempo does **not** yet contain a complete Europe-wide IFR SID/STAR/approach dataset. The existing FAA CIFP files remain US-only test data and must never be labelled as European procedures.

There is one confirmed, openly reusable national IFR source to start with: **France SIA**. It has not yet been ingested into FlightTempo. Other European sources have narrower coverage or require separate licences.

## France — public redistribution source

The SIA's official open-data catalogue lists the XML AIRAC 11/26 export as free to download (EUR 0), 5.8 MB, effective **29 October to 25 November 2026**. The ZIP contains:

- `AIXM4.5_all_FR_OM_YYYY-MM-DD.xml` — AIXM 4.5 export for the France and overseas AIP database
- `XML_SIA_YYYY-MM-DD.xml` — SIA-specific XML export

Sources:

- [SIA XML AIRAC 11/26 product page](https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition/les-bases-de-donnees-sia/donnees-aeronautiques-xml-airac-11-26.html)
- [SIA open-data products and legal terms](https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition.html)
- [SIA legal information](https://www.sia.aviation-civile.gouv.fr/informationslegales)
- [Licence Ouverte 2.0 full terms](https://www.data.gouv.fr/pages/legal/licences/etalab-2-0)
- [Public mirror directory used by open-data tooling](https://data.cquest.org/dgac/aip/)

The SIA's open-data terms permit worldwide commercial and non-commercial reuse, including extraction, transformation, redistribution and inclusion in a product or application. FlightTempo must preserve the SIA attribution and the last-update date, and must not alter or misrepresent the meaning of the source data.

**Important:** the source is approved for reuse, but FlightTempo has not yet downloaded, parsed or validated the AIXM/XML export. The source is therefore recorded as `source_current_not_ingested`, not as available procedure data. Before publication, the importer must validate airport identity, runway and transition associations, ordered legs, path terminators, altitude/speed constraints, fix references, AIRAC dates and checksums. Unknown or unsupported legs must not be guessed.

## Other European sources

| Source | What it provides | Current FlightTempo decision |
| --- | --- | --- |
| OpenFlightMaps (OFMA) | VFR traffic circuits, arrival routes and departure routes in supported regions | Commercial app use is permitted subject to the OFMA General Users' License. Treat it as VFR geometry, **not** IFR SIDs/STARs or instrument approaches. Coverage varies by region. |
| DFS INSPIRE (Germany) | Airports, runways, navaids, waypoints, routes and airspace via WFS/WMS | Public reference geodata only; it does not provide the German IFR terminal procedure set. DFS notes data may be incomplete and is updated twice per year. |
| EUROCONTROL EAD | ECAC AIP/AIXM source material | EAD Basic is a limited, general-purpose consultation tool, not an operational source. Commercial third-party re-serving requires EAD Type 3 service charges and Member State royalty fees. Not a public bundle source. |
| ENAIRE (Spain) | National AIP, including terminal procedures | Public commercial redistribution rights have not been confirmed. Do not publish until the relevant licence or written permission is established. |
| NATS / UK AIS | UK AIP procedure material | Crown Copyright / NATS reuse terms require review before extraction or redistribution. |

Simulator and community files reviewed (TerraSync Brest/Ponta Delgada, Bulgaria samples, Geneva and Berlin scenery) are not imported: they are isolated, potentially stale examples, and their upstream chart-derived rights and current validity have not been established.

## Import and release policy

1. Keep the French SIA data in its own source namespace and retain source attribution and AIRAC metadata.
2. Keep OFMA VFR routes separate from IFR procedure datasets.
3. Treat each national AIP as a separate licence and provenance boundary.
4. Do not use EAD, paid navdata or personal-use AIP downloads in a public dataset without the necessary commercial redistribution licence.
5. Enable the app's IFR procedure capability only after content validation and current-cycle checks have passed.

The current source-by-source status is machine-readable in [source-registry.json](../source-registry.json).
