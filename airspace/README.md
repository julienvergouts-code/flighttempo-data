# FlightTempo airspace and route policy

This directory contains the machine-readable EASA CZIB advisory feed, the route-preview FIR filter and the small policy contract consumed by the route generator.

The route generator should build paths from the airport and airway graph, not from a hardcoded list of popular passenger city pairs. Airline schedule popularity and airline nationality are not routing inputs.

## Two distinct layers

1. **Advisory avoidance** — active EASA CZIBs are risk advisories. The default preview can suggest avoiding their mapped FIR polygons, with one pilot preference toggle. This is not a universal legal prohibition.
2. **Verified legal restrictions** — a separate layer for current State AIP/NOTAM/regulatory prohibitions. These are not user-overridable in the route planner. No such complete global machine-readable prohibition feed is currently ingested.

Do not label a country as a hard no-fly zone merely because an advisory exists, and do not infer sanctions from an airline's nationality. A sanction, an advisory and a legally prohibited airspace are different things.

Observed ADS-B tracks may be displayed as evidence of where an aircraft flew. They do not establish that the same route is currently legal, available, safe or suitable for another operator.

The graph and all airspace data here are development/reference datasets, not operational navigation information.

## Russia and Belarus advisory coverage (reviewed 15 November 2026)

- EASA CZIB 2025-01 R3 is active until 31 January 2027 and names five Russian FIRs west of 60°E: UUWV, URRV, ULLL, USSV and UWWW. This is a safety recommendation, not a universal legal prohibition.
- The current OpenAIP import contains matching Russian polygons only for URRV and UWWW among those five. The UWWW polygon extends east of 60°E and is not clipped to the EASA limit. ULLL, UUWV and USSV geometry are missing. UMKK and UKFV may appear in the Russian country export but are not members of the five-FIR EASA CZIB list and must not be associated with it.
- EASA Safety Directive SD-2021-02 concerns FIR Minsk (UMMV). It is recorded separately from CZIBs; it is addressed to national competent authorities and its implementation/applicability must be checked for the operator. No Minsk FIR polygon is present in the current boundary export.
- Missing geometry is explicitly listed in `missingFIRGeometry`; it means unknown/incomplete map coverage, never unrestricted airspace. Do not fabricate FIR rectangles or mark these zones as exactly mapped.
- FAA KICZ records remain operator-scope conditional references and must not be conflated with EASA CZIBs or Safety Directives.
