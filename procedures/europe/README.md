# European procedure data status

## Current position

FlightTempo currently contains **no European SID, STAR or approach records and no European VFR reporting-point records**. The FAA CIFP files in this repository are US-only development/test data and must never be labelled as European procedures. The current global fixes and airway files are a stale 2012.08 development snapshot and are blocked from app downloads.

France is the first practical national candidate because its official eAIP publishes separate **DATA SID**, **DATA STAR** and some **DATA RWY / RNP** procedure tables. These are more useful for structured extraction than the graphical route charts alone.

## France — structured procedure tables identified

The next French eAIP package identified is AIRAC 12/26, effective **26 November to 23 December 2026**. Its official GEN 0.4 checklist lists the individual aerodrome documents, including the DATA procedure sheets. The package can be browsed as PDFs; for FlightTempo ingestion, download only the procedure DATA sheets rather than the full eAIP ZIP.

Key sources:

- [Official AIP France XML AIRAC 12/26 product page](https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition/les-bases-de-donnees-sia/donnees-aeronautiques-xml-airac-12-26.html)
- [Official AIP France GEN 0.4 document index — AIRAC 11/26](https://www.sia.aviation-civile.gouv.fr/media/dvd/eAIP_29_OCT_2026/FRANCE/AIRAC-2026-10-29/pdf/FR-GEN-0.4-fr-FR.pdf)
- [LFPG SID DATA example — RWY 26L/26R RNAV CODE 02](https://www.sia.aviation-civile.gouv.fr/media/dvd/eAIP_29_OCT_2026/FRANCE/AIRAC-2026-10-29/html/eAIP/Cartes/LFPG/AD_2_LFPG_DATA_SID_RWY26L-26R_RNAV_CODE_02.pdf)
- [LFPG STAR DATA example — RWY 26L RNAV CODE 02](https://www.sia.aviation-civile.gouv.fr/media/dvd/eAIP_29_OCT_2026/FRANCE/AIRAC-2026-10-29/html/eAIP/Cartes/LFPG/AD_2_LFPG_DATA_STAR_RWY26L_RNAV_CODE_02.pdf)
- [SIA open-data catalogue and Licence Ouverte terms](https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition.html)

The DATA SID/STAR PDFs contain table columns such as procedure identification, path terminator, waypoint identification, fly-over, magnetic and true direction, distance, turn direction, minimum/maximum altitude, maximum IAS and navigation accuracy. Some RNP approach DATA sheets also include a leg sequence, path terminator, waypoint, altitude/speed constraints and vertical-angle/TCH information.

### Extraction implementation

The first importer is now in scripts/import_sia_eaip_procedures.py. It is designed to:

1. Read individual SIA DATA PDFs using pdfplumber.
2. Preserve the published procedure heading, runway selector and each row's path terminator and constraints.
3. Keep shared/blank runway selectors as shared/unspecified rather than expanding them into guessed runway branches.
4. Preserve altitude and speed text as published rather than silently converting ambiguous formats.
5. Resolve a waypoint coordinate only when an optional source-backed fix list produces exactly one matching ident; otherwise the fix remains unresolved or ambiguous.
6. Write a provenance report with source file hash, document revision date, AIRAC effective date, source URL and row counts.

The importer does not create route geometry from headings/distances, invent missing legs, infer a coordinate from a waypoint name, or enable operational procedure capabilities. FNA-only final-approach precoding sheets are excluded from the complete-RNP-approach filename pattern.

A CI smoke test downloads two LFPG DATA PDFs from the SIA site and verifies extraction: 56 SID legs and 42 STAR legs (98 rows total) on AIRAC 11/26. The output is temporary test data only; no French procedure CSV is yet published in this repository. The parser still needs coverage testing across different airport document layouts, approach variants, fix-coordinate joins and AIRAC updates.

### Licence boundary

The official SIA eAIP ZIP product is listed in the "Produits numériques en libre disposition" catalogue, and its product page links to the SIA Licence Ouverte. The licence grants worldwide, free reuse for commercial or non-commercial purposes, including extraction, adaptation, redistribution and inclusion in an app. It requires attribution to SIA and forbids misrepresenting or distorting the source. This confirms reuse rights for the eAIP DATA tables. The source PDF remains copyrighted; the data rows are published only with source date, URL, document hash and SIA attribution.

Sources: [SIA eAIP product page](https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition/eaip/zip-eaip-complet-airac-11-26.html); [linked Licence Ouverte terms](https://www.sia.aviation-civile.gouv.fr/pub/media/news/file//l/i/licenceopendata-vf_2.pdf).

The separate SIA XML AIRAC export is also listed as a free-disposition product under Licence Ouverte 2.0. It is useful reference data for airports, runways, navaids and designated points, but it is not a complete IFR procedure-leg feed. The workflow attempts a daily refresh of WGS-84 DPN designated points and keeps them separate from IFR route and VFR reporting-point data. The current mirror index did not expose a dated XML archive during CI, so no designated-point package was generated; the failure is logged and no empty package is published.

## Other European sources

| Source | What it provides | Current FlightTempo decision |
| --- | --- | --- |
| OpenFlightMaps (OFMA) | VFR traffic circuits, arrival routes and departure routes in supported regions | Commercial app use is permitted subject to the OFMA General Users' License. Treat it as VFR geometry, **not** IFR SIDs/STARs or instrument approaches. Coverage varies by region. |
| DFS INSPIRE (Germany) | Airports, runways, navaids, waypoints, routes and airspace via WFS/WMS | Current catalogue marks the licence as restricted use; redistribution must be confirmed. It does not provide the German IFR terminal procedure set. |
| EUROCONTROL EAD | ECAC AIP/AIXM source material | The EAD is a source for procedures and wider AIS data, but commercial third-party re-serving requires the applicable service charges and State royalties. Not a free public bundle source. |
| ENAIRE (Spain) | National AIP, including terminal procedures | Public commercial redistribution rights have not been confirmed. Do not publish until the relevant licence or written permission is established. |
| NATS / UK AIS | UK AIP procedure material | Crown Copyright / NATS reuse terms require review before extraction or redistribution. |

Simulator and community files reviewed (TerraSync Brest/Ponta Delgada, Bulgaria samples, Geneva and Berlin scenery) are not imported: they are isolated, potentially stale examples, and their upstream chart-derived rights and current validity have not been established.

## Import and release policy

1. Keep each country's procedures in their own source namespace and retain both AIRAC effective date and document revision date.
2. Keep OFMA VFR routes separate from IFR procedure datasets.
3. Treat each national AIP as a separate licence and provenance boundary.
4. Do not use EAD, paid navdata or personal-use AIP downloads in a public dataset without the necessary commercial redistribution licence.
5. Keep unsupported path terminators, unresolved fixes and incomplete transitions visible as validation errors; do not fabricate substitutes.
6. Enable an app's IFR procedure capability only after the complete procedure content, source licence, cycle and fix links have been reviewed.

The current source-by-source status is machine-readable in [source-registry.json](../source-registry.json).
