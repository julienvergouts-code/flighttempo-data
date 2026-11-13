# FlightTempo Procedures

This directory stores procedure datasets as independently downloadable source files. It does **not** imply that every file is current, complete or operationally suitable.

## Current files: FAA test dataset only

The CSV files currently present in this directory are parsed from the FAA CIFP source:

- **Provider:** FAA AeroNav
- **Source:** [FAA CIFP cycle 2611](https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_261029.zip)
- **Cycle:** 2611
- **Effective:** 29 October 2026
- **Expiry:** 25 November 2026
- **Licence:** US Government Public Domain (FAA AeroNav)
- **Geographic scope:** United States / FAA National Airspace System only

| Dataset | Records | Airports | Size |
| --- | ---: | ---: | ---: |
| SIDs | 33,349 | 480 | 1.65 MB |
| STARs | 44,197 | 482 | 2.26 MB |
| Instrument approaches | 114,966 | 2,839 | 5.61 MB |

Pinned file hashes, source tags, source URL, effective/expiry dates and exact counts are in [source-manifest.json](source-manifest.json). A manifest record is marked as a matching repository artifact only when its byte size, SHA-256, version directive, source tag, row count and airport count match.

These files are retained for **development and importer testing**. In `navigation_manifest.json`, a matching pinned identity sets `available: true` so the app can fetch/cache the files, and sets `testDownloadAvailable: true` with `downloadPurpose: development_test_only`. This does **not** enable procedure use: `operationallyAvailable` remains false and the `sids`, `stars`, `approaches`, `ilsApproaches` and `rnavApproaches` capability flags remain false. The files must not be selected as European procedures or used for operational flight planning/navigation. Treat this cycle as expired after 25 November 2026 unless a newer, verified file replaces it.

## Europe

**A complete Europe-wide SID/STAR/approach dataset is not currently included.** The FAA CIFP files above must not be represented as European coverage.

See [Europe procedure data status](europe/README.md) for the reviewed free/community sources, their limitations, and the import requirements before any European dataset can be added.

## Data handling rules

- Retain genuine published procedure legs, runway associations, transitions, path terminators, altitude/speed constraints and relevant fix/navaid references.
- Do not manufacture procedure legs from runway headings, generic airport geometry or en-route airway data.
- Do not infer source licences from a file format, simulator availability or filename.
- Do not claim an AIRAC cycle, validity period or geographic coverage unless the source supports it.
- Keep incomplete, stale or unverified sources out of operational capability flags.
- ILS, RNAV and RNP approaches remain distinct procedure types; an ILS facility or runway attribute is not itself an approach procedure.

This repository is a reference-data source for FlightTempo, not an approved aeronautical information publication or an operational navigation source.
