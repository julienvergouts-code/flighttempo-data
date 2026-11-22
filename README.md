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
| `navigation/airports/ourairports_airports.csv` | 86,377 worldwide airport records | OurAirports CC0 |
| `navigation/runways/runways_parsed.csv` | 47,131 runway records | OurAirports CC0 |
| `navigation/navaids/navaids.csv` | 11,008 navaids | OurAirports CC0 |
| `data/vfr_points.csv` | 681 VFR waypoints | FAA NASR; United States only; reference-only |
| `navigation/waypoints/flightgear_fixes.csv` | 113,356 old fix records | Repository-only development data; cycle token 2012.08; excluded from app downloads |
| `navigation/navaids/flightgear_navaids.csv` | 26,599 old navaid records, including ILS-related facilities | Repository-only development data; cycle token 2012.08; excluded from app downloads |
| `navigation/airways/flightgear_airway_segments.csv` | 70,291 old airway segments | Repository-only development data; cycle token 2012.08; excluded from app downloads |
| `navigation/graph/world_corridor_graph.bin` | 59,073 nodes and 156,701 edges, including synthetic airport connectors | Development graph built from 2012.08 airways; excluded from app downloads |
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

1. The only global fixes and published airway segments in the repository are from a 2012.08 X-Plane/FlightGear-format snapshot. They are now blocked from the app download manifest. There is no current worldwide or Europe-wide airway/fix dataset in the app package.
2. Published SIDs, STARs and approaches are currently populated from FAA CIFP for the US NAS only. The app has no European procedures or VFR reporting points. No complete worldwide or Europe-wide redistributable procedure database has been confirmed.
3. OpenAIP FIR/UIR coverage is partial and non-commercial. Required attribution is recorded in `LICENSES/OpenAIP.md`.
4. FAA PRN/KICZ records are an official reference index, not a live cancellation feed. The FAA live NOTAM API is not connected; access is required.
5. Aero.Sors-derived CSVs are isolated as experimental personal-development data. Permission to redistribute the derived CSVs has not been confirmed.
6. The legacy app-facing `airports/airports.csv` has mixed upstream provenance; see its `meta.json`.

## Updating data

- OurAirports airport, runway and navaid reference tables refresh daily.
- The legacy global IFR source is retained for development and the corridor graph is rebuilt by GitHub Actions; both are blocked from app downloads because their source cycle is 2012.08.
- EASA CZIB advisories and FAA PRN references refresh daily.
- OpenAIP FIR/UIR exports refresh weekly.
- FAA CIFP procedures remain cycle-pinned until the next verified import.
- FAA VFR waypoints refresh on the NASR publication cycle and currently cover the United States only.
- A separate France/overseas SIA designated-point package refresh is attempted from the open AIXM feed. These points are not classified as VFR reporting points or a current airway network.

## Provenance and licensing

There is no blanket licence for all data in this repository. Each dataset has a `meta.json` and a source-specific licence/attribution note under `LICENSES/`. The root `manifest.json` is the repository-wide provenance catalogue; `navigation_manifest.json` is the app-facing download contract.

Do not infer a licence from a file format, filename or public URL. Do not treat any dataset in this repository as an approved AIP or operational flight-planning source.
