# FlightTempo Data

Public, data-only repository used by FlightTempo to download aviation reference data and airline profiles.

The Android/iOS applications are distributed separately through Google Play and the Apple App Store. This repository does **not** publish app source code or APKs.

## Download endpoint

The app reads the current manifest from:

`https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/navigation_manifest.json`

The manifest lists the available datasets, their relative paths, download URLs, record counts, byte sizes, SHA-256 checksums, source information and data-cycle status. The app should only download datasets marked `available: true`, then verify the SHA-256 checksum before installing them.

## Current data packages

| File | Purpose |
| --- | --- |
| `airports.csv` | FlightTempo airport-reference export with IATA/ICAO identifiers, IANA time-zone IDs and coordinates |
| `airlines.csv` | Airline/operator roster profiles (currently ASL and generic commercial profile) |
| `route_rules.csv` | Roster text/classification rules |
| `navigation/airports/ourairports_airports.csv` | OurAirports global airport reference extract |
| `navigation/runways/runways_parsed.csv` | Normalized runway data |
| `navigation/navaids/navaids.csv` | OurAirports navaids |
| `navigation/waypoints/flightgear_fixes.csv` | Optional IFR fixes; only when a coherent, redistributable source is supplied |
| `navigation/navaids/flightgear_navaids.csv` | Optional IFR navaids; only when a coherent, redistributable source is supplied |
| `navigation/airways/flightgear_airway_segments.csv` | Optional airway segments; not part of the current MVP |
| `procedures/**` | Reserved for verified published SIDs, STARs and approaches; current files are not advertised as available |

Direct downloads use the paths recorded in the manifest. Do not hard-code a future AIRAC cycle or record count in the app.

## Updating the data

- GitHub Actions refreshes the OurAirports airport, runway and navaid reference data daily.
- The IFR importer accepts supplied compatible FIX/NAV sources only when their cycle metadata is coherent and redistribution permission is explicitly declared.
- Airline profiles and route rules are maintained in the root CSV files and are downloaded independently of navigation data.
- The manifest is regenerated with the dataset metadata and SHA-256 checksums.

## Provenance and limitations

- OurAirports data is identified in the manifest as CC0/public-domain as stated by its provider.
- The current FlightTempo airport-reference export has incomplete upstream provenance recorded; its manifest status explicitly says source review is required.
- No synthetic IFR fixes, airways, SIDs, STARs or approaches are invented.
- Procedure data is not considered available until source provenance, redistribution rights, AIRAC cycle and content are verified.

These are aviation reference and roster-personalization datasets. They are not an approved aeronautical information publication or operational flight-planning/navigation source.
