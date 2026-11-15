# FlightTempo data repository

Worldwide aviation reference data for personal FlightTempo development, route-building experiments, dataset cross-checking and flight-preparation practice.

**Not an approved operational navigation database.** Data may be stale, incomplete or experimental. Verify aeronautical information against current official publications before real-world use.

## Repository rules

1. Every dataset directory contains a meta.json with source, airacCycle, effectiveDate, expiryDate, sha256 and licenceStatus. Unknown values must be null or explicitly unknown/not_applicable; never invent them.
2. Missing regional SIDs, STARs and approaches remain missing. Never generate or infer published procedures.
3. OpenAIP-derived material must retain the required CC BY-NC 4.0 attribution in metadata and accompanying attribution text.
4. AIRAC.net data is not stored here until its licence explicitly permits the intended storage and redistribution.
5. Aero.Sors-derived exports remain isolated under navigation/aerosors/ and marked experimental; derivative redistribution rights have not been confirmed.
6. Record actual source, cycle, effective/expiry dates, SHA-256, record count where known, and licence status.
7. navigation_manifest.json remains the app-facing download contract. Root manifest.json is the broader provenance catalogue and does not replace it.

## Layout

- airlines/ — airline profiles and route rules
- airports/ — legacy app airport reference
- navigation/ — normalized airports, runways, navaids, fixes, airways and experimental sources
- procedures/ — genuine published SIDs, STARs and approaches
- LICENSES/ — source-specific licence and attribution notes
- schemas/ — metadata schema

FAA CIFP procedures cover the US NAS only. OurAirports provides worldwide airport/runway reference data. Regional procedure folders are not evidence of coverage: an empty regional dataset means no usable source has been ingested.

For each dataset, calculate SHA-256 over the exact committed file bytes. For multiple files, record a files array with path, SHA-256 and byte size for each. Do not convert a simulator database version or arbitrary date into an AIRAC cycle. Only record effective/expiry dates when supported by the source.