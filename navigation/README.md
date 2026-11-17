# FlightTempo Navigation Data

This directory contains the global reference datasets and the prebuilt route graph consumed by FlightTempo's development route-preview engine.

**Not an operational navigation database.** The legacy IFR source is cycle token 2012.08 and must never be presented as a current AIRAC.

## Populated global baseline

| Dataset | Records | Source / status |
| --- | ---: | --- |
| OurAirports airports | 86,371 | CC0 / Public Domain |
| OurAirports runways | 47,127 | CC0 / Public Domain |
| OurAirports navaids | 11,008 | CC0 / Public Domain |
| Legacy IFR fixes | 113,356 | X-Plane/FlightGear-format mirror, GPL-3.0, cycle 2012.08 |
| Legacy en-route navaids | 26,599 | X-Plane/FlightGear-format mirror, GPL-3.0, cycle 2012.08 |
| Legacy airway segments | 70,291 | X-Plane/FlightGear-format mirror, GPL-3.0, cycle 2012.08 |
| ILS-related facilities in legacy navaids | 10,006 | Localizers, glideslopes and marker beacons; stale development data |

The legacy source is preserved under `navigation/sources/flightgear/`, with source headers, checksums, cycle token and licence declaration. It is a development baseline only.

The populated global fix and airway exports are `waypoints/flightgear_fixes.csv` and `airways/flightgear_airway_segments.csv`. The generic `waypoints/waypoints.csv` and `airways/airways.csv` files are header-only placeholders; they are not the global datasets and must not be used as evidence that worldwide coverage is missing or loaded. The downloadable files are declared individually in `navigation_manifest.json`.

## World corridor graph

`graph/world_corridor_graph.bin` contains 59,073 nodes and 156,701 edges. It includes 70,291 airway edges and 86,410 airport-to-airway connectors. A* smoke tests currently find paths for:

- EBBR to RJAA (BRU–NRT), FL350
- EBBR to EDDM (BRU–MUC), FL250
- LFPG to EDDM, FL250

The route graph is dynamic: it does not require a pre-populated list of popular city pairs. Airport connectors let the search join airport endpoints to the global airway network. The route results are demonstrations against stale data, not operational routes or clearances.

## Procedures

- FAA CIFP cycle 2611 contains US NAS SIDs, STARs and approaches.
- No complete global or Europe-wide redistributable procedure source has been confirmed.
- Missing published procedures remain unavailable. Never invent SID/STAR/approach legs from runway headings or generic airport geometry.

## Source rules

- Keep OurAirports navaids separate from legacy X-Plane/FlightGear navaids.
- Preserve each source's exact cycle token; do not convert an arbitrary date into an AIRAC cycle.
- Keep per-file source and licence metadata in the relevant `meta.json`.
- Do not publish paid or restricted navigation data without explicit redistribution rights.
- Do not use any dataset here for operational flight planning or navigation.


## CSV package validation

The navigation-data workflow runs `scripts/validate_navigation_csvs.py` against every dataset marked `available: true` in `navigation_manifest.json`. It checks file presence, byte size, SHA-256, CSV header uniqueness, row widths and manifest record counts. This is a packaging/integrity check only; it does not validate aeronautical correctness, currentness or operational suitability.
