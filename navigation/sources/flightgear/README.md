# User-supplied X-Plane / FlightGear-format source files

The FlightTempo MVP requires one coherent fixes/navaids source set containing:

- \`earth_fix.dat\` (or \`fix.dat\`)
- \`earth_nav.dat\` (or \`nav.dat\`)

Plain-text and gzip-compressed versions are accepted, including \`.dat.gz\` and \`.gz\` filenames. The importer supports XPFIX600, XPFIX1101, XPFIX1200 and XPNAV1100/1150/1200 formats.

The airway file \`earth_awy.dat\` (or \`awy.dat\`) is optional and deliberately ignored by the default importer, even when present. Airway ingestion can be enabled later using the explicit \`--include-airways\` option.

The required fixes and navaids files must declare the same known data-cycle token. The original source token is preserved exactly; it is not automatically interpreted as a current AIRAC cycle.

Add \`source-manifest.json\` with the actual provider, source URL, exact redistribution licence, licence URL and \`redistributable: true\` before publishing normalized data:

\`\`\`json
{
  "provider": "Actual provider name",
  "sourceUrl": "https://actual-source.example/",
  "license": "Exact licence name",
  "licenseUrl": "https://actual-source.example/license",
  "redistributable": true
}
\`\`\`

Do not use placeholder values. This is a source-rights gate, not a legal determination; confirm redistribution permission for the exact files before adding them to this public repository.

The importer preserves source headers, hashes, compression type, format versions, source cycle, build date and raw source records. Source navaids are kept separate from OurAirports navaids. Legacy FIX600 data lacks region, scope and waypoint-type fields; these remain explicitly unknown rather than being inferred.
