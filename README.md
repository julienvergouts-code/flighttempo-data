# FlightTempo Data

Worldwide aviation reference data for personal FlightTempo development, route-building experiments and flight-preparation practice.

**This is not an approved operational navigation database.** Some datasets are old, incomplete, community-maintained or advisory-only. Always verify against current official AIPs, NOTAMs and operator procedures before real-world use.

## App download contract

The app reads:

`https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/navigation_manifest.json`

The manifest lists downloadable datasets, relative paths, SHA-256 checksums, record counts, source provenance and cycle status. The app should download only datasets marked `available: true` and verify each checksum.

## Current data packages

| Dataset | Coverage / contents | Current status |
| --- | --- | --- |
| `navigation/airports/ourairports_airports.csv` | 86,368 worldwide airport records | OurAirports CC0 |
| `navigation/runways/runways_parsed.csv` | 47,122 runway records | OurAirports CC0 |
| `navigation/navaids/navaids.csv` | 11,008 navaids | OurAirports CC0 |
| `navigation/waypoints/flightgear_fixes.csv` | 113,356 IFR fixes | Legacy X-Plane snapshot, cycle token 2012.08, GPL-3.0 |
| `navigation/navaids/flightgear_navaids.csv` | 26,599 navaids, including ILS-related facilities | Legacy X-Plane snapshot, cycle token 2012.08, GPL-3.0 |
| `navigation/airways/flightgear_airway_segments.csv` | 70,291 airway segments | Legacy X-Plane snapshot, cycle token 2012.08, GPL-3.0 |
| `navigation/graph/world_corridor_graph.bin` | 59,073 nodes and 156,701 edges, including airport connectors | Built from the legacy global navigation baseline |
| `procedures/sids/sids.csv` | 33,349 SIDs | FAA CIFP cycle 2611; United States NAS only |
| `procedures/stars/stars.csv` | 44,197 STARs | FAA CIFP cycle 2611; United States NAS only |
| `procedures/approaches/approaches.csv` | 114,966 approaches | FAA CIFP cycle 2611; United States NAS only |
| `airspace/advisories/easa_czibs.json` | 34 EASA CZIB records, including 16 active at the latest refresh | Daily refresh |
| `navigation/airspace/openaip_fir_boundaries.geojson` | 170 FIR/UIR polygons | OpenAIP CC BY-NC 4.0; partial coverage |
| `airspace/faa_prn_notams.json` | 16 KICZ NOTAM references and 7 SFAR links | FAA PRN index; live cancellation status not verified |

The graph is not a list of popular city pairs. It is an airway graph used to calculate routes dynamically between airport nodes, so uncommon pairs such as EBBR–RJAA can be routed without a hardcoded passenger-route entry.

## Conflict-zone and restriction data

- EASA CZIB records are imported automatically. The route policy defaults to avoiding active advisory FIRs and exposes one user control: **Avoid Conflict / Advisory FIRs**.
- OpenAIP supplies FIR/UIR geometry where available. Current coverage is partial: 170 polygons from 130 country exports; not every advisory has a matching polygon.
- FAA KICZ notices are imported from the official FAA Prohibitions, Restrictions and Notices page. The importer preserves the notice's affected FIR codes and applicability scope. KICZ is a NOTAM series/identifier, not a FIR code.
- The FAA PRN page is not a live NOTAM amendment/cancellation API. FAA references are marked as currentness-unverified and must not be used as a hard legal block without checking the current NOTAM.
- Restrictions are matched by applicability (operator, pilot certificate or aircraft registration where specified), not inferred from airline nationality. EASA advisories remain advisories; they are not automatically promoted to universal legal prohibitions.

## Important limitations

1. The worldwide fixes, navaids, ILS facilities and airways come from a legacy 2012.08 X-Plane/FlightGear-format snapshot. They are useful for development and A* route testing, not current operational navigation.
2. Published SIDs, STARs and approaches are currently populated from FAA CIFP for the US NAS only. No complete worldwide or Europe-wide redistributable procedure database has been confirmed.
3. OpenAIP FIR/UIR coverage is partial and non-commercial. Required attribution is recorded in `LICENSES/OpenAIP.md`.
4. FAA PRN/KICZ records are an official reference index, not a live cancellation feed. The FAA live NOTAM API is not connected; access is required.
5. Aero.Sors-derived CSVs are isolated as experimental personal-development data. Permission to redistribute the derived CSVs has not been confirmed.
6. The legacy app-facing `airports/airports.csv` has mixed upstream provenance; see its `meta.json`.

## Updating data

- OurAirports airport, runway and navaid reference tables refresh daily.
- The legacy global IFR source is imported and the world corridor graph is rebuilt by GitHub Actions.
- EASA CZIB advisories and FAA PRN references refresh daily.
- OpenAIP FIR/UIR exports refresh weekly.
- FAA CIFP procedures remain cycle-pinned until the next verified import.

## Provenance and licensing

There is no blanket licence for all data in this repository. Each dataset has a `meta.json` and a source-specific licence/attribution note under `LICENSES/`. The root `manifest.json` is the repository-wide provenance catalogue; `navigation_manifest.json` is the app-facing download contract.

Do not infer a licence from a file format, filename or public URL. Do not treat any dataset in this repository as an approved AIP or operational flight-planning source.
