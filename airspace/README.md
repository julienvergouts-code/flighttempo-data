# FlightTempo airspace and route policy

This directory contains the machine-readable EASA CZIB advisory feed, the route-preview FIR filter and the small policy contract consumed by the route generator.

The route generator should build paths from the airport and airway graph, not from a hardcoded list of popular passenger city pairs. Airline schedule popularity and airline nationality are not routing inputs.

## Two distinct layers

1. **Advisory avoidance** — active EASA CZIBs are risk advisories. The default preview can suggest avoiding their mapped FIR polygons, with one pilot preference toggle. This is not a universal legal prohibition.
2. **Verified legal restrictions** — a separate layer for current State AIP/NOTAM/regulatory prohibitions. These are not user-overridable in the route planner. No such complete global machine-readable prohibition feed is currently ingested.

Do not label a country as a hard no-fly zone merely because an advisory exists, and do not infer sanctions from an airline's nationality. A sanction, an advisory and a legally prohibited airspace are different things.

Observed ADS-B tracks may be displayed as evidence of where an aircraft flew. They do not establish that the same route is currently legal, available, safe or suitable for another operator.

The graph and all airspace data here are development/reference datasets, not operational navigation information.


## Explicit Russia and Belarus advisory scope

- **Russia — EASA CZIB 2025-01 R3:** the official bulletin names FIR MOSCOW (UUWV), ROSTOV-NA DONU (URRV), SANKT-PETERSBURG (ULLL), YEKATERINBURG (USSV) and SAMARA (UWWW), at all altitudes/flight levels in Russian Federation airspace west of 60°E. The EASA record is source ID `141480`, valid until 31 January 2027 unless reviewed earlier. This is a safety recommendation, not a universal statutory prohibition. See the [official EASA bulletin](https://www.easa.europa.eu/en/domains/air-operations/czibs/2025-01-r3).
- The current OpenAIP export contains candidate polygons for **URRV** and **UWWW** only among those five codes. Those are community reference shapes, not State-AIP-verified boundaries; UWWW also extends east of 60°E and would require a correct longitude clip. Geometry for **ULLL, UUWV and USSV** is missing. Accordingly, the complete Russian advisory is recorded with all five explicit FIR codes but `routeAvoidanceReady: false`; partial shapes are deliberately excluded from `activeFirs` until all five are source-validated, clipped where applicable and complete. Do not fill this gap with hand-drawn rectangles, approximate coordinates or forced route waypoints.
- **Belarus — EASA Safety Directives, not a CZIB:** SD 2021-02 asks EASA Member State NCAs to ensure operators with their principal place of business in the State do not operate in FIR Minsk (UMMV), subject to the unforeseen-safe-operation exception. SD 2021-03 applies directly to Regulation (EU) 965/2012 operators for which EASA issued the AOC and acts as competent authority. SIB 2021-10 is the related advisory for EASA Member State operators and EASA-authorised TCOs when operating to/from/within the EU. These are stored under `operatorSpecificAdvisories`, not as a universal no-fly zone. Check the current national implementation and NOTAM for the applicable operator. The current [EASA Ukraine CZIB](https://www.easa.europa.eu/en/domains/air-operations/czibs/czib-2022-01r14) also references SD 2021-02 and SD 2021-03.
- No Minsk FIR polygon is currently present in the licensed FlightTempo OpenAIP boundary export. The directive's FIR code is recorded, but geometry is unavailable and the Belarus advisory is not route-avoidance-ready.

These records support development-time warnings and data-quality checks only. They do not establish operational route availability or legal clearance.
