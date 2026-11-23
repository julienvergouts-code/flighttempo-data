# FlightTempo VFR database status

**Audit date:** 2026-11-23

| Data | Source and commercial rights | Coverage / cycle | Repository status |
|---|---|---|---|
| VFR reporting points | FAA NASR subscription data; US government public-domain data | United States; dataset effective 2026-11-26 | 681-point CSV. The release is not available to app downloads until its effective date. |
| VFR points, reporting points and other designated reference points | open flightmaps (OFMA) OFMX under its General Users' License | AIRAC 2611; 4,736 deduplicated records from 21 source regions across 23 feature regions | Imported, metadata-registered, reference-only. Commercial use is permitted subject to the GUL. |
| Airports, runways and community navaids | OurAirports CC0 / public domain | Worldwide | Updated through the navigation-data workflow. These are community reference records, not complete official VFR procedure data. |

## OFMA imported coverage

The current OFMA VFR export is `data/ofma_ofmx_vfr_points.csv`, with source inventory and hashes in `data/ofma_ofmx_vfr_points_meta.json`. It covers all 21 regions currently represented in the downloaded OFMA catalogue as of this audit: EB, ED, EF, EH, EK, EP, ES, FA, FY, LD, LF, LG, LH, LI, LJ, LK, LM, LO, LR, LS and LZ.

Feature-region distribution (23 regions): EBBU 91; ED 376; EFIN 116; EHAA 87; EKDK 46; EPWW 465; ESAA 292; FA 7; FYWH 68; LBSR 156; LDZO 205; LF 779; LFEE 123; LGGG 376; LHCC 134; LI 524; LJLA 104; LKAA 114; LMMM 22; LOVV 321; LRBB 181; LSAS 88; LZBB 61.

Imported feature types: VFR-MRP 3,716; VFR-RP 725; VFR-ENR 172; VFR-HELI 19; VFR-GLDR 104. These category totals describe raw parsed feature records and may overlap the deduplicated record count.

## OFMA licence and limitations

Attribution to open flightmaps is required. Changes to the data must be communicated within the GUL's stated period, and the app must preserve the licence's additional conditions for end-user modifications. OFMA explicitly says its data is not certified/quality-controlled with a warranty and must not be used as a primary navigation source; FlightTempo therefore keeps this export reference-only.

No OpenAIP data is used for the VFR/IFR database because its CC BY-NC 4.0 licence does not allow commercial reuse.

## Next expansion — not yet imported

The existing pipeline extracts designated VFR points. A separate exploratory audit is needed to determine which other feature classes are consistently present in the regional OFMX packages (e.g. aerodrome/runway objects, airspace, route/circuit geometry, frequencies and associated attributes), their schema coverage and quality, and which can safely be exported as complementary reference layers.

Do not imply any of these feature classes are ingested until a feature-specific extractor, provenance/licence metadata, validation and tests are implemented. Preserve source-region, package hash, cycle, source feature ID, feature type and geometry lineage. Keep operational availability disabled by default.

## VFR-to-IFR matching

A VFR point can support an IFR reference only when the IFR source has its own coordinate-bearing record and both source records have the same normalized name and exactly equal decimal latitude and longitude. The matching code deliberately rejects ident-only and near-coordinate matches. Current procedure extracts do not supply coordinates, so no such links are generated yet.

All imported OFMA data remains reference-only and is not an approved operational navigation source.
