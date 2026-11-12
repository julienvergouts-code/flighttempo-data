# User-supplied X-Plane / FlightGear-format source files

Place one coherent source set in this folder:

- earth_fix.dat
- earth_nav.dat
- earth_awy.dat

Optionally add source-manifest.json. It must record the actual provider, source URL, exact redistribution licence, licence URL and redistributable=true before the normalized data can be published to this public repository.

Do not copy subscription-only or otherwise non-redistributable navdata here. The importer preserves source headers, file hashes, format version, data cycle, build date and raw source records in normalized output rows.
