# OFMA OFMX VFR reference-point import

This pipeline imports only OpenFlightMaps designated points whose `Dpn.codeType`
is one of `VFR-RP`, `VFR-MRP`, `VFR-ENR`, `VFR-GLDR`, or `VFR-HELI`.
It deliberately excludes generic/IFR designated points, navaids, aerodromes,
airspace, and all procedure data.

## Sources and endpoints

The download endpoint pattern and archive member layout are cross-checked against
the public WairToNow OFM downloader implementation. The source files themselves
are official OFMA snapshots, and each regional download page is recorded in
`data/ofma_ofmx_sources.json`.

Active regions for the initial pipeline:
- EB — Belgium (`ebbu`)
- ED — Germany (`ed`)
- EH — Netherlands (`ehaa`)

France (LF) is intentionally excluded pending confirmation of its current
snapshot region key and publication availability.

The workflow resolves the AIRAC cycle dynamically from the 28-day cycle anchor
for 2601 and downloads that cycle. It runs weekly and can be manually dispatched.
If a source fails, the pipeline fails closed and does not publish a partial
replacement dataset.

## Outputs

- `data/ofma_ofmx_vfr_points.csv`
- `data/ofma_ofmx_vfr_points_meta.json`
- `navigation_manifest.json` registration (reference dataset; not operationally available)

CSV coordinates are normalized to decimal degrees and include region, code,
name, VFR type, source and license.

## License and product boundary

Source: OpenFlightMaps Association, OFMA General Users License (GUL). Commercial
use is permitted only subject to the GUL terms. Keep attribution and source
provenance. The GUL also requires reporting errors/alterations and a user error
reporting mechanism; FlightTempo must implement/verify that reporting route
before distributing this dataset in the commercial app.

OFMA explicitly disclaims certification and says the data must never be used as
a primary navigation source. This pipeline is reference-only; it is not an IFR
dataset, not an AIP replacement, and not suitable for operational navigation.

## Validation

Unit tests cover coordinates (decimal degrees and compact DMS), hemispheres,
bounds, VFR-only filtering, ZIP member selection, empty-input fail-closed
behavior, and AIRAC rollover.
