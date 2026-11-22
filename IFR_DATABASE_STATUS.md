# FlightTempo IFR navigation data — status audit

**Audit date:** 2026-11-22  
**Bottom line:** FlightTempo does **not** currently have an active, current worldwide IFR navigation database. It has a mixed reference dataset with daily airport/runway/navaid refreshes, a legacy 2012.08 worldwide fix/airway baseline, and a current-ish FAA CIFP package that is not automatically imported.

| Data class | Packaged source / cycle | Refresh | Coverage | Status |
|---|---|---|---|---|
| Airports | OurAirports CC0 | Daily workflow | Worldwide | Active refresh; community reference |
| Runways | OurAirports CC0 | Daily workflow | Worldwide | Active refresh; community reference |
| Community navaids | OurAirports CC0 | Daily workflow | Worldwide | Active refresh; incomplete/not authoritative |
| IFR fixes | X-Plane mirror snapshot 2012.08, GPL-3.0 | Manual legacy importer | Worldwide | **Stale; not current AIRAC** |
| Airways | X-Plane mirror snapshot 2012.08, GPL-3.0 | Manual legacy importer | Worldwide | **Stale; not current AIRAC** |
| SID/STAR | FAA CIFP 2611, effective 2026-10-29, expires 2026-11-25 | Currentness monitor only; no auto-import | US NAS | Package is one cycle behind next published cycle 261126 (effective 2026-11-26); US-only |
| Approaches | FAA CIFP parsing incomplete | Not auto-imported | US NAS only where parser supports | Not an active complete approach DB |
| European IFR procedures | France SIA AIXM 4.5/XML Open Licence source identified | Not ingested | France candidate | Reusable source confirmed, parser/integration not built |
| EUROCONTROL FRA points | Official source monitor | Not ingested | ECAC | Candidate; licensing/format integration gate |
| Global current IFR procedures | No free, redistributable, complete feed confirmed | — | Worldwide | **Missing** |

## Important product boundary

The 2012.08 fixes/airways and graph are **development route-preview data only**. The route graph must not be advertised as current IFR route planning or operational navigation. It currently contains synthetic airport connectors, bidirectional airway assumptions, and no complete current restrictions/NOTAM integration.

## Prioritized build plan

1. Replace stale worldwide fixes/airways with a source-by-source legally reusable current feed, prioritizing official/open data.
2. Ingest and regression-test the France SIA AIXM 4.5 data as the first current regional IFR dataset.
3. Investigate the EUROCONTROL FRA points list and licence/redistribution scope; build FRA edges separately from published airways.
4. Upgrade FAA CIFP import to automatic cycle detection, verified ARINC 424 parsing, regression comparisons and safe publication before replacing cycle 2611 with 261126.
5. Keep legacy sources available only as clearly labelled fallback/reference data, with provenance and age visible.

No current package should be represented as a complete worldwide IFR database.
