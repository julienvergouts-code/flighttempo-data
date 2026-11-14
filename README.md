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
| `airports.csv` | FlightTempo airport reference with IATA/ICAO, IANA timezone, coordinates, elevation, a longest-runway compatibility field, and pipe-delimited lists of all matched runway pairs, headings and lengths |
| `airlines.csv` | Airline/operator roster profiles (currently ASL and generic commercial profile) |
| `route_rules.csv` | Roster text/classification rules |
| `navigation/airports/ourairports_airports.csv` | OurAirports global airport reference extract |
| `navigation/runways/runways_parsed.csv` | Normalized runway data |
| `navigation/navaids/navaids.csv` | OurAirports navaids |
| `navigation/aerosors/vor_ndb.csv` | Experimental Aero.Sors worldwide VOR/NDB table; development testing only |
| `navigation/aerosors/ils.csv` | Experimental Aero.Sors worldwide ILS table; development testing only |
| `navigation/aerosors/ge_navaids.csv` | Experimental Aero.Sors Google Earth world navaids with point coordinates; development testing only |
| `navigation/aerosors/ge_airports.csv` | Experimental Aero.Sors Google Earth world airport layer; development testing only |
| `navigation/waypoints/flightgear_fixes.csv` | Optional IFR fixes; only when a coherent, redistributable source is supplied |
| `navigation/navaids/flightgear_navaids.csv` | Optional IFR navaids; only when a coherent, redistributable source is supplied |
| `navigation/airways/flightgear_airway_segments.csv` | Optional airway segments; not part of the current MVP |
| `procedures/**` | Reserved for verified published SIDs, STARs and approaches; current files are not advertised as available |

Direct downloads use the paths recorded in the manifest. Do not hard-code a future AIRAC cycle or record count in the app.

### Airport reference enrichment

The first nine columns of `airports.csv` retain the legacy Android parser contract:

`iata, icao, timeZone, name, latitude, longitude, elevationFt, runwayPair, runwayHeadingDeg`

The following appended columns retain all paired open runway records matched from OurAirports:

- `allRunwayPairs`: pipe-delimited runway-end pairs (for example `07L/25R|07R/25L|01/19`)
- `allRunwayHeadingsDeg`: matching low-end true headings, in the same order
- `allRunwayLengthsFt`: matching runway lengths in feet, in the same order
- `runwayCount`: number of matched paired open runways

The longest runway is copied into the legacy primary runway fields so older app builds continue to parse the file. The extra fields are available for future multi-runway UI support. Enrichment is rebuilt from the daily OurAirports source snapshots. OurAirports releases its data to the public domain; the source provenance for the pre-existing IATA/time-zone reference fields remains under review. This dataset is community-maintained and is not guaranteed for operational use.

## Updating the data

- GitHub Actions refreshes the OurAirports airport, runway and navaid reference data daily.
- GitHub Actions also imports Aero.Sors VOR/NDB and ILS spreadsheets and Google Earth navaids/airport layers as experimental test datasets when the source files are reachable. They are not AIRAC-validated against each national AIP and are not cleared for operational or user release.
- The IFR importer accepts supplied compatible FIX/NAV sources only when their cycle metadata is coherent and redistribution permission is explicitly declared.
- Airline profiles and route rules are maintained in the root CSV files and are downloaded independently of navigation data.
- The manifest is regenerated with the dataset metadata and SHA-256 checksums.

## Provenance and limitations

- OurAirports data is identified in the manifest as CC0/public-domain as stated by its provider.
- The current FlightTempo airport-reference export has incomplete upstream provenance recorded; its manifest status explicitly says source review is required.
- No synthetic IFR fixes, airways, SIDs, STARs or approaches are invented.
- Aero.Sors-derived CSVs are explicitly marked development-only. The reviewed permission for unchanged package redistribution does not expressly confirm republication of derived CSVs; obtain written permission before external distribution or production use.
- Procedure data is not considered available until source provenance, redistribution rights, AIRAC cycle and content are verified.

These are aviation reference and roster-personalization datasets. They are not an approved aeronautical information publication or operational flight-planning/navigation source.
