# VFR airspace AIXM ingestion

The importer converts AIXM 4.x XML into a compact gzip JSON reference pack.

Run:
```bash
python3 scripts/build_vfr_airspace_pack.py --input /path/to/official_export.xml --country FR --effective-date YYYY-MM-DD --output navigation/vfr/fr_vfr_airspace.json.gz --manifest navigation/vfr/fr_vfr_meta.json
```

Use country BE for a Belgian AIS export. Source XML is not committed; preserve the original archive and checksum separately.

## Data integrity
- Retains CTR, TMA, D, P, R and RMZ classifications. National code mapping must be verified before country release.
- Keeps each AirspaceVolume separate with its own lower/upper limit, unit and reference.
- Preserves polygon interior rings and emits bounding boxes for future SQLite R*Tree indexing.
- Vertical values are preserved verbatim; SFC/GND/AMSL/STD/FL are not guessed or normalised.
- Curved GML primitives (arcs, circles, geodesics, composite curves) fail closed and are counted. They are not silently converted to straight lines. A country pack must not be released until the actual source curve types are implemented with a documented metre tolerance.
- Axis order uses GML axisLabels/CRS84 when present, otherwise the documented aviation longitude-first convention. Override only after inspecting the source CRS.
- operationallyAvailable is always false: reference/development only, not for navigation or separation assurance.

No official Belgian or French XML export is bundled yet. The script and fixtures are a foundation, not evidence that either country has been ingested.
