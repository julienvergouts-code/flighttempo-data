# FlightTempo Data

Master repository for FlightTempo's downloadable aviation reference datasets.

- `navigation_manifest.json` describes published datasets, source provenance, checksums, record counts and capabilities.
- `navigation/` contains normalized navigation datasets and retained original source files.
- `procedures/` is reserved for genuine published SIDs, STARs and ILS/RNAV/RNP procedure data.
- `scripts/build_aviation_db.py` builds the datasets.
- `.github/workflows/update-navigation-data.yml` runs the scheduled/manual build and validation.

The repository schema is independent of the Android app's internal models. The Android importer is responsible for adapting these master datasets.

See [navigation/README.md](navigation/README.md) for scope, source policy, current coverage and limitations.

This is reference data, not an approved aeronautical information publication or an operational flight-planning/navigation source.
