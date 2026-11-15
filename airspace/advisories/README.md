# EASA conflict-zone advisories

FlightTempo imports the official EASA CZIB JSON export:

https://www.easa.europa.eu/en/domains/air-operations/czibs/export-json?_format=json&page=

The daily workflow stores the source response at `easa_czibs_source.json`, normalizes the active and withdrawn records into `easa_czibs.json`, and builds `../airspace_filter.json` for route-preview advisory handling.

Attribution: Source: European Union Aviation Safety Agency (EASA), Conflict Zone Information Bulletins. EASA's copyright notice states that reproduction is authorised provided the source is acknowledged.

## Interpretation

- An active CZIB is an advisory/risk assessment, not automatically a legal prohibition or a NOTAM.
- A withdrawn or expired advisory must not remain active merely because a stale local copy exists.
- The route preview may suggest avoidance of active advisories, but must retain a separate hard-restriction layer for actual published prohibitions and operator requirements.
- The EASA export identifies affected countries and advisory text. It does not supply a complete machine-readable FIR polygon mapping. The importer only assigns an FIR code when the bulletin title explicitly identifies one; it does not infer geometry from a country name or a centroid.
- This dataset is not a sole source for operational risk assessment. Check State AIPs/NOTAMs, operator policy and the original bulletin.

Last-mile data rights and disclaimers: https://www.easa.europa.eu/en/disclaimer
