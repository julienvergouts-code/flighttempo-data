# FlightTempo Procedures

This directory stores source-backed terminal procedure datasets and their provenance. Source availability, downloadability and operational suitability are separate states.

## Current downloadable files: FAA test dataset only

The CSV files currently present in this directory are parsed from FAA CIFP:

- **Provider:** FAA AeroNav
- **Source:** [FAA CIFP cycle 2611](https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_261029.zip)
- **Cycle:** 2611
- **Effective:** 29 October 2026
- **Expiry:** 25 November 2026
- **Licence:** US Government Public Domain (FAA AeroNav)
- **Geographic scope:** United States / FAA National Airspace System only

| Dataset | Records | Airports | Size |
| --- | ---: | ---: | ---: |
| SIDs | 33,349 | 480 | 1.65 MB |
| STARs | 44,197 | 482 | 2.26 MB |
| Instrument approaches | 114,966 | 2,839 | 5.61 MB |

Pinned file hashes, source tags, source URL, effective/expiry dates and exact counts are in [source-manifest.json](source-manifest.json). Matching files are exposed for **development/test download only**: the standard `available` field permits the app to fetch/cache them, while `testDownloadAvailable: true`, `downloadPurpose: development_test_only` and `operationallyAvailable: false` explicitly keep them out of operational procedure selection. The `sids`, `stars`, `approaches`, `ilsApproaches` and `rnavApproaches` capability flags remain false.

Treat cycle 2611 as expired after 25 November 2026 unless a newer, verified file replaces it. These FAA files must not be labelled as European or Asian coverage.

## Europe

**No complete Europe-wide IFR dataset is currently available in FlightTempo.** The current French eAIP (AIRAC 11/26) publishes DATA SID and DATA STAR PDFs with structured leg tables, and a parser has been added for testing against official LFPG examples. No French procedure CSV has yet been published. The SIA XML export is a separate open-licensed reference-data product; it is not assumed to contain complete IFR procedure legs. The exact Licence Ouverte scope for the eAIP DATA PDFs must be confirmed before the derived rows are released publicly. OpenFlightMaps is a viable conditional source for VFR routes/traffic circuits, not IFR SIDs/STARs. DFS INSPIRE provides German baseline geodata, not the German IFR terminal procedure set. EAD and other national AIPs have separate paid, personal-use or permission requirements.

See [European procedure source status](europe/README.md).

## Asia

**No public-commercial-redistribution source for Asian IFR SIDs/STARs/approaches has been confirmed in the reviewed sources.** Thailand, India and Singapore impose personal-use or approval conditions; Hong Kong's AIP is a controlled document; South Korea's MOLIT copyright policy requires prior permission or consultation for profit-making use. Do not copy AIP files into the public repository merely because they are freely viewable or downloadable.

See [Asian procedure source status](asia/README.md).

## Machine-readable source inventory

[Source registry](source-registry.json) records regional source candidates, licences, restrictions, AIRAC dates where known, and whether a dataset has actually been imported. The navigation manifest generator copies this inventory into `regionalProcedureCoverage` so the app can distinguish a source candidate from an installed procedure dataset.

## French SIA procedure-table importer

The importer in scripts/import_sia_eaip_procedures.py reads official SIA DATA PDFs, preserves their leg fields and produces a provenance report. A CI smoke test downloads current LFPG SID and STAR DATA PDFs and checks that the PDF tables are extractable. It does not generate route geometry or synthetic fixes, and it leaves the procedure capability flags disabled. The importer is not yet a published French dataset: extraction across the national set, fix-coordinate joins, approach coverage and the specific eAIP PDF licence scope still require validation.

## Data handling rules

- Retain genuine published procedure legs, runway associations, transitions, ordered sequences, path terminators, altitude/speed constraints and source-linked fix references.
- Do not manufacture procedure legs from runway headings, generic airport geometry or en-route airway data.
- Do not infer a licence from file format, simulator availability, a public URL or the licence of a repository's software.
- Do not claim an AIRAC cycle, validity period or geographic coverage unless the source supports it.
- Keep incomplete, stale or unverified sources out of operational capability flags.
- Keep IFR instrument procedures separate from VFR circuits and arrival/departure routes.
- ILS, RNAV and RNP approaches remain distinct procedure types; an ILS facility or runway attribute is not itself an approach procedure.

This repository is a reference-data source for FlightTempo, not an approved aeronautical information publication or an operational navigation source.


## Automatic FAA cycle monitoring and staging

The daily navigation workflow checks the official [FAA CIFP download page](https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/cifp/download/) and writes `faa-cifp-currentness.json`. It records the packaged cycle, latest published cycle, effective/expiry dates and whether an update is due. The monitor fails the daily pipeline when a newer cycle becomes effective and again if the packaged cycle is expired.

### Verified staging pipeline

The FAA 261126 archive (effective 26 November 2026) was downloaded successfully in GitHub Actions and staged as a 14-day artifact. The pipeline:

1. Downloads the FAA-published archive and checks ZIP integrity and SHA-256.
2. Audits archive members, safe paths, ASCII text, record lengths and source checksums.
3. Extracts the `FAACIFP18` fixed-width source into staging.
4. Runs a partial header-field extractor for procedure records (SID, STAR and approach record types), producing non-publishable NDJSON plus a summary.
5. Uploads the archive, audit report and parser outputs as a staging artifact.

For cycle 261126, the extractor scanned 397,414 records, all 132 columns wide, and staged 199,021 procedure records: 33,349 SID, 44,197 STAR and 121,475 approach records. It identified 2,888 airport identifiers and 49,885 procedure/transition groups.

The comparison to the current packaged CSV counts is **informational only**: SID and STAR counts match; the source approach-record count (121,475) is 6,509 higher than the packaged approaches CSV count (114,966). Raw CIFP record counts and normalized CSV rows are not necessarily equivalent. This difference requires investigation before any approach dataset update.

**This is not a complete ARINC 424 importer.** Leg semantics (path terminators, altitude/speed constraints, RF/turn instructions, continuation and termination handling), full CSV conversion, cycle-to-cycle equivalence checks, and release/activation gates are not implemented. The parser currently writes staging outputs only; it never replaces packaged CSVs or changes app capability flags. Full data replacement remains prohibited until those components and regression tests are complete.

FAA CIFP is updated every 28 days. Its customer agreement requires recipients to notify downstream users of reported errors and notify FAA when errors are found. See the FAA product page and customer agreement.
