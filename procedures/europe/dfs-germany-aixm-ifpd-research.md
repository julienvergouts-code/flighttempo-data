# Germany — DFS AIXM Instrument Flight Procedures research

**Status:** source existence confirmed; downloadable package, EDDV coverage, redistribution rights and extraction are not yet verified. No procedure records have been imported.

## Confirmed source facts

- EUROCONTROL's Germany AIXM data-source catalogue lists an **Instrument Flight Procedures data set** with procedures in **AIXM 5.1.1**, using SNAPSHOT and BASELINE TimeSlices. It also states that BASELINE data is exposed through the NOW / NEXT / AFTER menu, with checksums in a checklist and a website/REST API documentation section.
  - Source: https://ext.eurocontrol.int/aixm_confluence/x/4gFY
  - PDF snapshot: https://ext.eurocontrol.int/aixm_confluence/download/export/pdfexport-20260512-120526-0427-81859/AIX-Germany-120526-0427-81860.pdf
- EUROCONTROL's 2024 implementation monitoring report (data reviewed 1 July 2025) marks Germany's IFP data sets as available, but notes that the German AIS provider had not received data from all affected aerodromes. This is a material completeness warning; nationwide coverage must not be assumed.
  - Source: https://www.eurocontrol.int/archive_download/all/node/15648
- DFS AIS Portal terms allow automated/electronic use of the portal **only for AIXM download data**. The same disclaimer says commercial sharing/resale of portal services and content is not permitted, and other uses require prior written approval. This exception permits automation of the AIXM download; it is **not** an express public redistribution licence for extracted procedures.
  - Source: https://ais.dfs.de/pilotservice/service/information/disclaimer/disclaimer.jsp
- DFS contact for data questions is data@dfs.de (as listed in the EUROCONTROL Germany data-source catalogue).

## Decision for FlightTempo

1. Treat DFS AIXM IFPD as a promising source for a **private extraction/technical feasibility test**, not as cleared public data.
2. Do not publish EDDV or other extracted procedure rows in the public repository, redistribute the AIXM source files, or enable app-facing procedure downloads until DFS confirms in writing the permitted use, derivative-data rights, redistribution, attribution and commercial-app rights.
3. Do not confuse the separate DFS INSPIRE WFS/WMS transport-network dataset with the AIXM IFPD procedure dataset. INSPIRE provides airports, runways, navaids, points, routes and airspace; it is not itself the terminal procedure feed.
4. When access and terms are established, start with EDDV. Preserve all AIXM procedure-leg properties and temporal validity; retain source identifiers, UUIDs, sequence, path terminators, fix references, altitude/speed constraints, runway/transition associations and source TimeSlice. Validate each extracted procedure against the corresponding current German AIP chart/text and the source checklist/checksum.
5. Record missing aerodromes, unsupported feature types and unresolved fix references explicitly. Never synthesize missing legs or infer geometry from a chart.

## Next actions

- Obtain the current DFS AIXM portal URL and its REST/API documentation from the catalogue's "Documentation" link.
- Inspect the current NOW/NEXT/AFTER checklist and determine whether EDDV is present in the IFPD package.
- Confirm whether the package can be downloaded without registration and record the dataset cycle/effective interval and SHA-256.
- Send DFS a written rights query before committing any extracted records to the public repository.
- Only after the above, implement a dedicated AIXM 5.1.1 IFPD importer and an EDDV-only test fixture.

## Related standards

AIXM is an aeronautical data exchange model, not a licence. EUROCONTROL describes it as a global specification for encoding and distributing aeronautical information; its model and documentation are openly available, but that does not grant rights to the underlying DFS dataset.
- https://www.eurocontrol.int/model/aeronautical-information-exchange-model
