# Legacy global X-Plane / FlightGear-format navigation source

This folder contains the imported legacy worldwide navigation snapshot used for FlightTempo's development route graph.

- **Upstream:** https://github.com/ptsmonteiro/x-plane-navdata
- **Licence:** GPL-3.0, as declared by the upstream repository
- **Source cycle token:** 2012.08
- **Format:** XPFIX600 / XPNAV1100 / AWY640 compatible legacy records
- **Use:** personal development, parser validation and route-preview experiments only

Imported source files:

- `earth_fix.dat`
- `earth_nav.dat`
- `earth_awy.dat`

The importer writes normalized outputs to:

- `navigation/waypoints/flightgear_fixes.csv`
- `navigation/navaids/flightgear_navaids.csv`
- `navigation/airways/flightgear_airway_segments.csv`

The importer preserves source headers, hashes, format versions, cycle token and record counts in `import_metadata.json`. The normalized files retain waypoint/navaid types, ILS/localizer/glideslope/marker facilities, airway direction, flight levels, altitude restrictions and endpoint resolution where present.

**Staleness warning:** 2012.08 is not a current AIRAC. Do not use these records for operational navigation or claim they represent current procedures or airways.
