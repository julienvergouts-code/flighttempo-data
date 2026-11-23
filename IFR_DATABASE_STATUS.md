# FlightTempo IFR database status

**Audit date:** 2026-11-22  
**Coverage:** Regional and cycle-pinned reference data only. There is no complete worldwide IFR database.

| Data | Source and licence | Coverage / cycle | Refresh and current status |
|---|---|---|---|
| Airports, runways and community navaids | OurAirports, CC0 / public domain | Worldwide reference records | Daily source refresh. The mixed-provenance airport export is blocked; only the OurAirports tables are downloadable. |
| US SIDs and STARs | FAA AeroNav CIFP, US government public-domain data | United States NAS, cycle 2611; effective 2026-10-29 through 2026-11-25 | Existing CSVs are in the repository and marked reference-only. A daily currentness monitor checks the FAA cycle. There is no verified automatic ARINC 424 importer; the next cycle 2612 is effective 2026-11-26. |
| US approaches | FAA AeroNav CIFP, US government public-domain data | United States NAS, cycle 2611 | Existing CSV is incomplete/test-only and must not be treated as complete approach coverage. |
| US fixes, navaids and airway segments | FAA NASR FIX/NAV/AWY CSV groups, US government public-domain data | United States NAS; one 28-day cycle, the newest already effective | Weekly workflow `update-faa-nasr-ifr.yml` writes `navigation/faa_nasr/`. It stops without publishing if any group is missing, the files are truncated, or too many airway endpoints cannot be resolved to a single coordinate. Reference-only; the manifest gate blocks it after the cycle expires. |
| French SIDs and STARs | Official SIA eAIP DATA PDFs under the SIA Open Licence; commercial reuse, adaptation and redistribution are permitted with attribution | France only; current eAIP cycle selected from the official catalogue | A daily GitHub workflow imports sheets it can parse, records every indexed sheet and skips unsupported layouts. It publishes only if both SID and STAR data are extracted. It is regional reference data, not operational. |
| Worldwide fixes, legacy navaids and airways | X-Plane/FlightGear-format snapshot, cycle token 2012.08 | Worldwide but stale | Kept only for history/provenance; excluded from app downloads and route-planning capabilities. No longer a live IFR feed. |
| Other country procedures | No additional source admitted without commercial redistribution terms verified for the exact product/country | Missing | No paid source is used. EUROCONTROL EAD redistribution requires negotiated fees and is excluded. |

## VFR points reused for IFR

A VFR point may be cross-referenced to an IFR point only when both source records provide the same normalized name and exactly equal latitude and longitude. There is no tolerance, nearest-point match, alias match or ident-only match.

The current French procedure tables identify fixes but do not provide their coordinates. FAA procedure CSVs also lack coordinates. For the United States, current coordinate-bearing fixes and navaids now exist (FAA NASR), but no VFR-to-IFR coordinate links are generated from them yet. Outside the United States the repository still has no current, coordinate-bearing IFR fix source suitable for proving those matches, so the pipeline leaves procedure coordinates blank and creates no VFR-to-IFR coordinate links there.

## Commercial reuse gate

The app download manifest fails closed unless a dataset has an explicit commercial-use grant or a recognized public-domain/CC0 status. It also blocks datasets before their effective date and after their cycle expiry. Source-specific attribution and licence conditions remain in the dataset metadata.

OpenAIP CC BY-NC data, mixed-source airport exports, unconfirmed derivatives and other records without confirmed commercial redistribution rights are not app-downloadable. No non-commercial or paid data source is used in the active IFR/VFR database.

**Operational boundary:** These are reference datasets for product development and planning practice. They are not an approved operational navigation database and do not replace current AIPs, NOTAMs or operator procedures.
