# FlightTempo Navigation Data

This repository is the master source for FlightTempo's independently downloadable aviation reference datasets. It supports geographical IFR route previews; it is not an approved aeronautical information publication and must not be used for operational flight planning or navigation.

## Dataset scope

| Dataset | Source / status |
| --- | --- |
| Airports | OurAirports normalized dataset |
| Runways | OurAirports normalized dataset |
| OurAirports navaids | Separate source dataset |
| IFR fixes | Separate import from X-Plane/FlightGear-compatible `earth_fix.dat` |
| En-route navaids | Separate import from `earth_nav.dat`; never merged with OurAirports |
| Low/high airway segments | Separate import from `earth_awy.dat` |
| SIDs, STARs, ILS and RNAV/RNP approaches | Publish only with verified source, redistribution rights and cycle |

Each verified dataset is independently described in the root manifest. Android can download each file separately; this repository phase does not modify the Android application.

## IFR import

Place a single coherent source set in `navigation/sources/flightgear/`:

- `earth_fix.dat` (XPFIX1101 or XPFIX1200)
- `earth_nav.dat` (XPNAV1100, XPNAV1150 or XPNAV1200)
- `earth_awy.dat` (XP AWY1101 specification; data header is `1100 Version`)

Legacy filenames `fix.dat`, `nav.dat`, and `awy.dat` are also accepted when they contain one of those supported formats. XPFIX1101 records retain the mandatory published waypoint-type code; XPFIX1200 also retains the printed waypoint name, including embedded spaces. XPNAV1200 retains the current NDB BFO field and newer approach path-point record fields in raw form. Unsupported formats fail rather than being guessed. All three input headers must declare the same four-digit data cycle.

Add a `source-manifest.json` before publishing, containing the actual provider, licence and explicit confirmation that redistribution is permitted:

```json
{
  "provider": "Actual provider name",
  "sourceUrl": "https://actual-source.example/",
  "license": "Exact licence name",
  "licenseUrl": "https://actual-source.example/license",
  "redistributable": true
}
```

The example values are placeholders, not assertions about a particular supplier. The importer refuses public publication unless a licence is stated and `redistributable` is explicitly true. This is a declaration gate, not a legal determination; confirm rights for the exact files before adding them.

Run:

```bash
python3 scripts/import_xplane_navdata.py
python3 -m unittest discover -s tests -v
```

The OurAirports builder deliberately does not synthesize or infer airway geometry from coordinate-only legacy records. A public FlightGear repository candidate was inspected and its regional fix/airway samples used legacy FIX 600 and AWY 640 formats; these do not carry the typed endpoint references required by FlightTempo and are therefore not used by this pipeline.

The importer writes:
- `navigation/waypoints/flightgear_fixes.csv`
- `navigation/navaids/flightgear_navaids.csv`
- `navigation/airways/flightgear_airway_segments.csv`

The source navaids remain separate from `navigation/navaids/navaids.csv` (OurAirports). Source headers, file hashes, format versions, build dates and source cycle are retained in `navigation/sources/flightgear/import_metadata.json` and the master manifest.

## Airway graph integrity

Each airway retains endpoint identifier, region and endpoint type, airway name(s), direction restriction, low/high classification, original altitude values and normalized feet values.

Endpoint resolution uses identifier + region + type:
- Type 11: en-route fix.
- Type 2: en-route NDB.
- Type 3: en-route VHF navaid.

If there is no unique match, the segment is retained with an explicit `unresolved`, `ambiguous`, or `unsupported_type` status. The importer does not choose an arbitrary duplicate. Fixes and navaids remain distinct entity types but both can supply coordinates when the airway endpoint type explicitly references them.

Direction codes are retained as N (no restriction), F (forward) or B (backward). Low/high classification and minimum/maximum altitude restrictions are retained in source form and feet.

## Procedures

An ILS is an approach procedure, not a runway attribute. RNAV/RNP approaches are separate published procedures. Preserve actual ordered legs, path terminators, transitions, runway associations, constraints and navaid references. Never manufacture procedure geometry from runway headings or airport coordinates.

The current repository has legacy procedure export files, but their source and redistribution provenance have not yet been validated. The manifest therefore must not advertise them as verified published procedure data until their source, licence, coverage and cycle are confirmed.

Route visualisation preference: compatible published ILS, then compatible RNAV/RNP, then a clearly labelled estimated visual connection if no published procedure is available. A visual connection is not a published instrument approach or an ATC clearance.

## Provenance and limitations

- No paid/subscription data may be committed without explicit redistribution permission.
- Do not infer a licence from a file format or filename.
- Do not claim an AIRAC cycle unless recorded in the source header.
- All three IFR files must have matching known cycles when the cycle is stated.
- OurAirports is community-maintained reference data, not an official, current operational AIS database.
- Missing source data remains unavailable; no synthetic worldwide routes or procedures are generated.
