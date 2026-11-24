# France SIA ENR import (fixes, navaids, airways, airspace)

Source: the free "ZIP eAIP complet" product published by SIA / DGAC, read from the SIA web eAIP
(`html/eAIP/FR-ENR-*.html`). Licence: SIA Licence Ouverte (commercial reuse allowed with attribution,
integrity, no endorsement). The importer re-verifies the product price and the licence wording live
(`verify_sia_commercial_reuse`) on every run and refuses to publish if the proof disappears.
The SIA site is only reachable from some networks (it is from GitHub Actions); when it is not, the run
ends cleanly without touching published data.

| Page | Output | Dataset id |
|---|---|---|
| ENR 4.4 significant points | `navigation/sia_france/fixes.csv` | `sia_france_fixes` |
| ENR 4.1 radio navigation aids | `navigation/sia_france/navaids.csv` | `sia_france_navaids` |
| ENR 3.2 ATS routes | `navigation/sia_france/airway_segments.csv` | `sia_france_airway_segments` |
| ENR 2.1, 2.2, 5.1 airspace | `airspace/sia/FR.json.gz` + `index.json` | `sia_france_airspace` |

CSV columns match the FAA NASR files; airspace packs use the same schema as the openAIP/OFMA packs.

Each dataset is `available` only inside its AIRAC window (checked again by `enforce_app_manifest_rights.py`).
Guards: minimum record counts and a 30% drop limit against the previously published file.

Known approximations: arcs and circles become polylines; national-border and coast segments are joined by
straight lines and the feature is flagged `approx`; vertical limits are normalised to feet.
Not covered yet: ENR 5.2-5.7 special zones, ENR 3.3 VFR transit routes. Reference data only, not for navigation.

Run: `python scripts/import_sia_france_enr.py` then `python scripts/register_sia_france_manifest.py`
(workflow `update-sia-france-enr.yml`, shared concurrency group `flighttempo-shared-manifest-updates`).
