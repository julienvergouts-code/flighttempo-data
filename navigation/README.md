# FlightTempo Navigation Data

This repository is the master source for FlightTempo's independently downloadable aviation reference datasets. It supports geographical IFR route previews; it is not an approved aeronautical information publication and must not be used for operational flight planning or navigation.

## MVP dataset scope

| Dataset | Source / status |
| --- | --- |
| Airports | OurAirports normalized dataset |
| Runways | OurAirports normalized dataset |
| OurAirports navaids | Separate source dataset |
| IFR fixes | Separate import from X-Plane/FlightGear-compatible FIX data |
| En-route navaids | Separate import from X-Plane/FlightGear-compatible NAV data; never merged with OurAirports |
| SIDs and STARs | Genuine published procedures only, when source rights and cycle are verified |
| ILS, RNAV and RNP approaches | Genuine published procedures only, when source rights and cycle are verified |
| En-route airways | Excluded from the MVP; optional later enhancement |

Each verified dataset is independently described in the root manifest. Android can download each file separately. The data repository changes do not, by themselves, modify the Android application's routing or display code.

## IFR fixes and navaids import

Place a coherent source set in \`navigation/sources/flightgear/\`:

- \`earth_fix.dat\` / \`fix.dat\` (XPFIX600, XPFIX1101 or XPFIX1200)
- \`earth_nav.dat\` / \`nav.dat\` (XPNAV1100, XPNAV1150 or XPNAV1200)

Plain-text and gzip-compressed \`.dat.gz\` / \`.gz\` inputs are accepted. The two required input headers must declare the same complete known data-cycle token (for example, \`2016.10\`). The source token is preserved exactly and is not automatically assumed to be a current AIRAC cycle.

XPFIX1101 records retain the published waypoint-type code; XPFIX1200 also retains printed waypoint names, including embedded spaces. Legacy FIX600 records contain only coordinates and an identifier, so their region, terminal/en-route scope and waypoint type remain unknown. Unsupported formats fail rather than being guessed.

The optional \`earth_awy.dat\` / \`awy.dat\` file is deliberately ignored by default, even when present. A future explicit import can use \`--include-airways\`; the MVP routing engine must not depend on it.

Add a \`source-manifest.json\` before publishing, containing the actual provider, licence and explicit confirmation that redistribution is permitted:

\`\`\`json
{
  "provider": "Actual provider name",
  "sourceUrl": "https://actual-source.example/",
  "license": "Exact licence name",
  "licenseUrl": "https://actual-source.example/license",
  "redistributable": true
}
\`\`\`

The example values are placeholders, not assertions about a particular supplier. The importer refuses public publication unless a licence is stated and \`redistributable\` is explicitly true. This is a declaration gate, not a legal determination; confirm rights for the exact files before adding them.

Run:

\`\`\`bash
python3 scripts/import_xplane_navdata.py
python3 -m unittest discover -s tests -v
\`\`\`

The standard importer writes:

- \`navigation/waypoints/flightgear_fixes.csv\`
- \`navigation/navaids/flightgear_navaids.csv\`

Airway segments are not imported or advertised unless explicitly enabled. If enabled later, legacy AWY640 coordinate-bearing records remain marked as unknown-typed segments; they must not be promoted to typed/verified airway graph connectivity.

Source navaids remain separate from \`navigation/navaids/navaids.csv\` (OurAirports). Source headers, file hashes, payload hashes, compression type, format versions, build dates and source cycle are retained in \`navigation/sources/flightgear/import_metadata.json\` and the master manifest.

## Aero.Sors experimental VOR/NDB and ILS tables

The build workflow downloads the two published Aero.Sors workbooks and exports:
- `navigation/aerosors/vor_ndb.csv`
- `navigation/aerosors/ils.csv`

The importer preserves every non-empty worksheet row. It maps fields when column names are recognized and keeps the original row values in `raw_fields_json`. Coordinates are populated as decimal degrees only when the source cell is unambiguous; DMS or packed coordinate strings remain in the raw JSON rather than being guessed. Dataset metadata records the source workbook checksum, row counts and the Aero.Sors cycle label when available.

**Scope:** this is the spreadsheet export only. It does not decode the full World FSXP3D BGL package and therefore does not provide the package's airport/runway records, fixes/intersections or airway segments. It does not create SIDs, STARs or approaches. The source data is simulator-oriented and is not validated against every national AIP.

**Test-only status:** keep these files for FlightTempo development experiments. Reviewed Aero.Sors terms allow unchanged redistribution of the original package on free media, but explicit permission for derivative CSV republication has not been confirmed. Do not treat a public GitHub location or a development-only label as a licence grant; obtain written permission before any user-facing or commercial release.

Run locally:

```bash
python3 -m pip install -r requirements-aerosors.txt
python3 scripts/import_aerosors_tables.py
```

## Aero.Sors Google Earth geospatial layers

The workflow also downloads the public Google Earth KMZ layers and exports their KML Placemark data:
- \`navigation/aerosors/ge_navaids.csv\`
- \`navigation/aerosors/ge_airports.csv\`

Every Placemark is retained. KML Point coordinates are mapped to decimal-degree latitude/longitude; other geometry or records without a Point remain metadata-only. Original ExtendedData and description text are retained in each row. Altitude follows the KML unit (metres).

These layers add worldwide geographic positions to the Aero.Sors VOR/NDB and ILS workbook exports. They are still simulator/reference data, not a national AIP. They do not provide a complete IFR fix/intersection database, airway graph, SIDs, STARs or approaches. Derivative CSV republication rights are not confirmed; keep these exports for personal FlightTempo development only unless written permission is obtained.

Run locally:

\`\`\`bash
python3 scripts/import_aerosors_kmz.py
\`\`\`

## Routing architecture

FlightTempo constructs its own generated en-route waypoint sequence from geolocated fixes and navaids. The initial routing engine should:

1. Build a geodesic direct-track baseline between the departure and destination.
2. Find candidates in a finite geographic corridor around that segment.
3. Resolve homonyms with type, region/area and coordinates rather than identifier text alone.
4. Enforce forward along-track progress and penalize backtracking, repeated fixes, zigzags and excessive detours.
5. Validate total track miles against a direct-distance guardrail.
6. Keep generated en-route routing separate from published terminal procedure geometry.

Corridor and detour filters apply only to generated en-route points. Published SID, STAR and approach legs must retain their genuine published path geometry and constraints, including procedure legs that intentionally turn away from the direct track.

The app should label generated routing as a calculated waypoint route, not an airway route, ATC clearance or operationally approved flight plan. Missing procedure data must remain explicitly unavailable; never manufacture SID/STAR/approach legs from runway headings or generic airport geometry.

## Provenance and limitations

- No paid/subscription data may be committed without explicit redistribution permission.
- Do not infer a licence from a file format or filename.
- Do not claim an AIRAC cycle unless recorded in the source header.
- The required fixes and navaids files must have matching known data-cycle tokens.
- OurAirports is community-maintained reference data, not an official, current operational AIS database.
- Missing source data remains unavailable; no synthetic worldwide procedures or routes are generated.
