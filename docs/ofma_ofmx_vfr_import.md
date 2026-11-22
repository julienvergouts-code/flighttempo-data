# OFMA OFMX VFR reference-point import

This importer fetches VFR-designated points from every current regional product published by OFMA. It does not use or scrape AIP pages or AIP files.

The current official OFMA catalogue lists 21 regional products: EB, ED, EF, EH, EK, EP, ES, FA, FY, LD, LF, LG, LH, LI, LJ, LK, LM, LO, LR, LS, and LZ. The catalogue is regional and does not provide worldwide geographic coverage; it covers only regions OFMA has published.

## Source discovery and refresh

For each region, the pipeline checks the official download page's regionCode, reads the current AIRAC publication XML from OFMA's publicationServices, selects the official OFMX ZIP URL from the OFMX product, then downloads that package from snapshots.openflightmaps.org.

It imports Dpn.codeType values VFR-RP, VFR-MRP, VFR-ENR, VFR-GLDR, and VFR-HELI. It excludes IFR procedure definitions, navaids, aerodromes, airspace, and unrelated OFMX records. Data is merged only on matching feature region, code, exact coordinates, and VFR type, while preserving source-region provenance.

A missing or ambiguous current publication, unexpected redirect, invalid package, schema change, or malformed VFR coordinate fails the build before replacing the point CSV and metadata. A region package with Dpn records but no VFR-coded points is explicitly recorded as an empty VFR region. If all packages are empty, the existing dataset is retained.

The workflow tests the parser, downloads all configured official publications, validates each package, uploads the data and source archives for review, registers the layer in the shared navigation_manifest.json, and writes generated data back to the PR branch when the PR comes from this repository. Scheduled and manually dispatched refreshes update their checked-out branch.

## Outputs and architecture

- data/ofma_ofmx_vfr_points.csv
- data/ofma_ofmx_vfr_points_meta.json
- data/ofma_source_archives/*.zip (temporary CI review artifacts; not an app-download layer)
- navigation_manifest.json registration

The OFMA points are an independently versioned, attributed reference layer in the existing shared navigation data foundation. They do not create a separate IFR/VFR app or replace current IFR datasets.

A VFR point may be shared with an IFR point only when the independently licensed IFR record has the same normalized name and exactly the same latitude and longitude. The existing matcher in scripts/exact_point_matching.py enforces this rule and rejects ident-only, approximate-coordinate, and fuzzy matches. The current repository has no current commercially reusable worldwide IFR fix layer to match; its 2012.08 global legacy baseline is stale and excluded from app downloads.

## Commercial license and use boundary

Source data: OpenFlightMaps Association, [OFMA General Users' License](https://www.openflightmaps.org/live/downloads/20150306-GUL.pdf). OFMA explicitly permits commercial use, worldwide and royalty-free, subject to the license. Every output includes attribution and official source provenance. Before commercial app distribution, FlightTempo must honor the GUL requirement to communicate data alterations within 15 days and, if users can alter OFMA data, provide the direct contributor interface required by section 4.4.

OFMA states that its database is provided without accuracy or completeness warranty and must not be used as a primary source for navigation. This layer is reference-only and is not operational IFR or VFR navigation data.

The importer does not acquire chart imagery, AIP documents, maps, or OFMA's proprietary client software.
