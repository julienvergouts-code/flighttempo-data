# FlightTempo Navigation Data

This repository is the master source for FlightTempo's downloadable aviation reference datasets. It is not an approved aeronautical information publication and must not be used for operational flight planning or navigation.

## Agreed dataset scope

| Dataset | Scope |
|---|---|
| Airports and runways | Include |
| Independent IFR fixes / waypoints | Include |
| Low- and high-level IFR airways, including ordered segment connectivity | Include |
| VOR, VOR/DME, DME, NDB, NDB/DME, TACAN and VORTAC | Include where present in the source |
| SIDs and STARs | Include only when genuine procedure data is available |
| ILS approaches | Include |
| RNAV/RNP approaches | Include |
| VFR-only reporting points, routes and chart layers | Exclude |

Navaids are retained even when they are not the preferred visual drawing method. Route definitions and procedure records can reference VOR/DME/NDB fixes, and the app may use their genuine coordinates for route context.

The terminal drawing preference is separate from the database scope:

1. Use a genuine published ILS procedure when suitable procedure data exists.
2. Otherwise use a genuine published RNAV/RNP procedure.
3. If neither is available, show a clearly labelled simplified direct connection. Do not present that connection as a published procedure.

Localizer and glideslope facility records may be retained when needed to represent a genuine ILS. LOC-only approaches are not part of the current approach-display scope.

## Current verified coverage

The automated builder currently retrieves the following datasets from OurAirports:

- Airports
- Runways
- Navaids (including VOR, VOR/DME, DME and NDB records where supplied by the provider)

The source files are retained under `navigation/sources/`; normalized datasets are stored in their respective folders and described in the root `navigation_manifest.json`.

## Planned / unavailable datasets

The following are part of the target data model but are not currently populated from a verified source:

- Independent IFR en-route fixes / waypoints
- Low- and high-level IFR airways and segment connectivity
- SIDs
- STARs
- Instrument approaches (ILS and RNAV/RNP)

Existing placeholder files or empty directories are not evidence that a dataset is populated.

## Source strategy and licensing

OurAirports remains the current source for airports, runways and its supplied navaid records.

The selected expansion source ecosystem is FlightGear navigation data. Candidate source files include the FlightGear/X-Plane-format navigation, fix and airway datasets. Each actual upstream file must be inspected and recorded independently before ingestion:

- Confirm the upstream repository/release and exact download URL.
- Confirm the file's provenance and redistribution licence; do not assume every data file inherits the software repository's licence.
- Record the source version/release and cycle only when explicitly available in the source.
- Treat bundled simulator data as reference data that may be old. Do not label it current or assign an AIRAC cycle unless the source proves that.
- Do not replace missing FlightGear data with FAA, commercial, proprietary or unrelated datasets without an explicit change to this source decision.

A dataset may be published only when its actual provider, source release/cycle (where available), licence, extraction timestamp, checksum, record count and semantic validation are recorded in the manifest.

## Data integrity rules

- Never invent fixes, airway segments, coordinates, procedures or AIRAC cycles.
- Do not infer published procedures from airport/runway geometry.
- Preserve airway sequence, directionality and segment connectivity as supplied by the source.
- Preserve provider attribution, licence and source provenance per dataset.
- An unavailable dataset must be marked unavailable in the manifest; do not silently substitute unrelated data.
- Publish updates only after per-dataset semantic validation succeeds. A failed dataset must retain its previous known-good version.
- Keep the repository schema independent from Android's current CSV/model format; the Android importer adapts these master datasets.

## Important limitation

OurAirports is community-maintained reference data, not an official current operational AIS database. FlightGear bundled navigation files may also be outdated and must not be assumed to represent a current AIRAC cycle. This repository is a FlightTempo reference-data project, not a substitute for current charts, NOTAMs, AIP, ATC clearance or an operational flight-planning system.
