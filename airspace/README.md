# FlightTempo airspace and route policy

This directory contains the machine-readable EASA CZIB advisory feed, the route-preview FIR filter and the small policy contract consumed by the route generator.

The route generator should build paths from the airport and airway graph, not from a hardcoded list of popular passenger city pairs. Airline schedule popularity and airline nationality are not routing inputs.

## Two distinct layers

1. **Advisory avoidance** — active EASA CZIBs are risk advisories. The default preview can suggest avoiding their mapped FIR polygons, with one pilot preference toggle. This is not a universal legal prohibition.
2. **Verified legal restrictions** — a separate layer for current State AIP/NOTAM/regulatory prohibitions. These are not user-overridable in the route planner. No such complete global machine-readable prohibition feed is currently ingested.

Do not label a country as a hard no-fly zone merely because an advisory exists, and do not infer sanctions from an airline's nationality. A sanction, an advisory and a legally prohibited airspace are different things.

Observed ADS-B tracks may be displayed as evidence of where an aircraft flew. They do not establish that the same route is currently legal, available, safe or suitable for another operator.

The graph and all airspace data here are development/reference datasets, not operational navigation information.
