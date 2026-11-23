# FlightTempo Data

Reference data for the FlightTempo application and its development pipelines.

The app-facing download contract is `navigation_manifest.json`. Only datasets with verified commercial reuse rights and valid source-cycle dates may be marked `available: true`. Each downloadable dataset includes its source, licence, attribution, cycle, checksum and record count.

**This is not an approved operational navigation database.** Reference records may be incomplete and must not replace official AIPs, NOTAMs or operator procedures.

## Current IFR and VFR coverage

- **Global reference tables:** OurAirports airport, runway and navaid records are CC0/public domain and refreshed by the navigation-data workflow. Mixed-source airport exports are blocked.
- **US IFR:** FAA AeroNav CIFP cycle 2611 SIDs, STARs and approach records are in the repository. They are US-only, reference-only, and expire after 2026-11-25. A daily monitor checks for new cycles; no verified automatic ARINC 424 import currently exists.
- **US IFR fixes, navaids and airways:** FAA NASR FIX, NAV and AWY data (US government public domain) in `navigation/faa_nasr/`, one coordinate-bearing 28-day cycle at a time. A weekly workflow imports the newest cycle whose effective date has passed; airway segments are published only when both endpoints resolve to exactly one coordinate. US only, reference-only, and blocked by the manifest gate once the cycle expires.
- **France IFR:** the official SIA eAIP lists SID/STAR DATA sheets under its Open Licence, which permits commercial reuse with attribution. A daily pipeline selects the current cycle, accounts for every indexed sheet, and imports only supported tables. Partial coverage and skipped sheets are disclosed in generated metadata.
- **US VFR:** FAA NASR VFR reporting points are public domain. The current file is effective 2026-11-26 and the manifest keeps it unavailable before that date.
- **Regional VFR:** OFMA OFMX reference points are commercially usable under the OFMA General Users' License, subject to its attribution and other conditions. Coverage is limited to the regions listed in the metadata.
- **Worldwide IFR fixes and airways:** the legacy cycle 2012.08 snapshot is stale and excluded from app downloads. There is no complete worldwide IFR data source in this repository.

See [IFR database status](IFR_DATABASE_STATUS.md) and [VFR database status](VFR_DATABASE_STATUS.md) for coverage details and matching rules.

## Data rights and attribution

There is no blanket licence for this repository. The licence and conditions belong to each dataset:

- OurAirports: [data terms](https://ourairports.com/data/)
- FAA CIFP/NASR: US government public-domain sources; verify current cycle and source notices.
- SIA France eAIP: [eAIP listing](https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition/eaip.html) and [SIA Open Licence](https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition.html)
- OFMA: [General Users' License](https://www.openflightmaps.org/live/downloads/20150306-GUL.pdf)

The pipeline does not treat public accessibility as permission. On each run, the French eAIP workflow checks the exact free current-cycle product and re-reads the SIA terms for commercial reuse, redistribution and required attribution. Any new country or AIP source must pass its own product-specific rights check before import. Sources with non-commercial or unverified redistribution terms are excluded from the app download manifest. No paid navigation data is used.

## Updating data

GitHub Actions refreshes OurAirports and FAA VFR reference data, imports FAA NASR US fixes, navaids and airway segments (`update-faa-nasr-ifr.yml`), imports OFMA reference points, checks the published FAA CIFP cycle and fetches the current French eAIP SID/STAR sheets. IFR cycle data is not replaced unless the import succeeds and validation passes.

The exact-name/exact-coordinate matcher is implemented for source-backed point records. Procedure legs without their own coordinates are never assigned VFR coordinates by ident alone.
