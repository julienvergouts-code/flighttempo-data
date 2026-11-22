# Data automation and publication policy

This repository is a development/reference data source for FlightTempo. It is not an operational navigation database.

## Scheduled refreshes

| Source / task | Schedule | What is refreshed | Publication status |
| --- | --- | --- | --- |
| OurAirports | Daily, 04:15 UTC | Global airport, runway and navaid snapshots; airport reference enrichment | Normalized OurAirports tables are app-downloadable under the provider's CC0 terms. The legacy enriched `airport_reference` table remains research-only while IATA/time-zone provenance is under review. |
| EASA CZIB export | Daily, 04:23 UTC | Official advisory records and advisory metadata | App-downloadable reference only; source acknowledgement required |
| OpenAIP FIR/UIR geometry | Weekly, Monday 04:41 UTC | Research/reference geometry and associated airspace review metadata | Repository research only; CC BY-NC 4.0, excluded from app download manifest |
| FAA PRN KICZ index | Daily, in the main navigation workflow | FAA PRN notice references and source PDFs/checksums | FAA reference only; not live NOTAM status and not a hard restriction feed |
| FAA CIFP cycle | Daily, in the main navigation workflow | Checks official FAA publication page against the packaged procedure cycle | Currentness report only; parsed procedure CSVs are not auto-replaced |
| French SIA AIXM designated points | Daily, in the main navigation workflow | Reads the public AIXM archive mirror and extracts WGS-84 DPN points | Separate France/overseas reference package only when download and validation succeed; not classified as VFR reporting points or complete IFR fixes |
| EUROCONTROL FRA ECAC + MUAC | Daily, 04:45 UTC | Downloads latest FRA XLSX to ephemeral CI storage; reports publication URL, workbook structure, aggregate counts and checksum | Metadata/schema monitoring only; source XLSX and point records are not retained or redistributed; rights review required |
| OFMA regional downloads | Daily, 04:50 UTC | Checks 21 regional pages and download-plugin scripts for endpoints and format hints | Endpoint metadata only; no data imported or republished until importer and compliance obligations verified |
| French SIA eAIP | CI smoke test in the main workflow | Tests extraction from official LFPG SID/STAR DATA PDFs under the confirmed SIA Licence Ouverte | 98 LFPG rows validated in CI; smoke-test output only, not yet a packaged procedure dataset |
| Legacy 2012.08 IFR data | No automatic source refresh | Preserves the existing global fixes, navaids, airway segments and graph | Development-only and blocked from app downloads; never label as current AIRAC |

All workflows that write shared manifests use the same GitHub Actions concurrency group so scheduled jobs do not overwrite one another's manifest updates.

The app manifest rights guard runs after airport enrichment and blocks the mixed-source legacy airport table before package validation. The full OurAirports tables remain separately available with their provider license and checksums.

## Deliberate non-automation

- **FAA CIFP:** The FAA publishes a new CIFP every 28 days. The repository now detects a newly published cycle and fails the daily workflow once the packaged cycle has expired. Automatic replacement is deliberately disabled until a verified ARINC 424 parser, full import validation and cycle-to-cycle regression tests are available. The current package is US NAS only and test/reference use only.
- **Aero.Sors:** Derived CSV exports were removed because permission to republish transformed CSV derivatives has not been confirmed. The importer scripts remain dormant; no scheduled workflow runs them.
- **OpenAIP:** Non-commercial research data remains in the repository for reference, but its FIR geometry and any mixed-source airspace filter are not offered through the app download manifest.
- **OFMA:** Commercial use is permitted under its GUL subject to attribution, alteration reporting and a correction-report mechanism. Regional CUP/OpenAir/OFMX exports exist, but the live region pages inspected by the monitor do not expose raw download endpoints yet.
- **DFS Germany INSPIRE:** The official WFS/WMS includes waypoints and routes and is updated twice yearly. The German data catalogue currently marks reuse as restricted, so FlightTempo redistribution is not confirmed.
- **EUROCONTROL FRA:** The daily monitor tracks the ECAC and MUAC FRA-point publications and inspects workbook structure/aggregate metadata. The source XLSX is downloaded only to ephemeral CI storage; no point rows or source workbook are committed or uploaded. Redistribution and source-data rights remain unconfirmed, so FRA data is excluded from the app manifest pending written permission or a verified reuse licence.
- **National AIPs / terminal procedures:** No automated extraction is enabled unless the source terms, product scope and redistribution rights have been checked.

## Integrity and safety gates

Every main navigation-data run:
1. runs the Python unit-test suite;
2. refreshes the eligible source datasets;
3. rebuilds and smoke-tests the global corridor graph;
4. refreshes FAA PRN references; the legacy IFR importer also checks committed source checksums and refuses unexpectedly small exports before replacing global CSVs;
5. checks the packaged FAA CIFP cycle against the official publication;
6. applies the app-manifest redistribution-rights guard;
7. validates every app-downloadable CSV for file presence, path containment, byte size, SHA-256, header uniqueness, row widths and manifest record count;
8. verifies the complete manifest and generated packages before committing.

A successful workflow means the repository package passed these automated checks. It does not certify aeronautical accuracy, currentness of legacy sources, or operational suitability.
