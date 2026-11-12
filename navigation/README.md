# FlightTempo Navigation Data

This repository is the master source for FlightTempo's downloadable aviation reference datasets. It is not an approved aeronautical information publication and must not be used for operational flight planning or navigation.

## Current verified coverage

The automated builder currently retrieves only the following datasets from OurAirports:

- Airports
- Runways
- Navaids (including VOR, VOR/DME, DME and NDB records where supplied by the provider)

The source files are retained under `sources/`; normalized datasets are stored in their respective folders and described in the root `navigation_manifest.json`.

## Planned / unavailable datasets

The following are part of the target data model but are **not currently populated from a verified source**:

- Independent IFR en-route fixes / waypoints
- Low- and high-level IFR airways and segment connectivity
- SIDs
- STARs
- Instrument approaches (ILS and RNAV/RNP)

Files that exist for these datasets must not be treated as verified published navigation data unless their manifest entry identifies the actual provider, source release/cycle, licence, extraction timestamp and validation results. Sample/test rows must never be shipped as navigation records.

## Data integrity rules

- Never invent fixes, airway segments, coordinates, procedures or AIRAC cycles.
- Do not infer published procedures from airport/runway geometry.
- Preserve provider attribution, licence and source provenance per dataset.
- An unavailable dataset must be marked unavailable in the manifest; do not silently substitute unrelated data.
- Publish updates only after per-dataset semantic validation succeeds. A failed dataset must retain its previous known-good version.
- Keep the repository schema independent from Android's current CSV/model format; the Android importer adapts these master datasets.

## Navaid coverage

Retain useful IFR navaid records, including VOR, VOR/DME, DME and NDB. These records support route/procedure references and map context even though the app's preferred terminal drawing remains published ILS first, then published RNAV/RNP, then a clearly labelled simplified direct connection when no suitable published procedure data is available.

## Important limitation

OurAirports data is community-maintained reference data. It is not an official, current operational AIS database. This repository is a FlightTempo reference-data project, not a substitute for current charts, NOTAMs, AIP, ATC clearance or an operational flight-planning system.
