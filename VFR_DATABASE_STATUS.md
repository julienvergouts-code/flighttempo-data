# FlightTempo VFR database status

**Audit date:** 2026-11-22

| Data | Source and commercial rights | Coverage / cycle | Repository status |
|---|---|---|---|
| VFR reporting points | FAA NASR subscription data; US government public-domain data | United States; dataset effective 2026-11-26 | 681-point CSV. The release is not available to app downloads until its effective date. |
| VFR points, reporting points and other designated reference points | open flightmaps (OFMA) OFMX under its General Users' License | Current cycle 2611; 1,786 deduplicated points from supported regional packages across 10 feature regions | Commercial use is permitted subject to the GUL. The export is reference-only, with source attribution and change-reporting conditions. |
| Airports, runways and community navaids | OurAirports CC0 / public domain | Worldwide | Updated through the navigation-data workflow. These are community reference records, not complete official VFR procedure data. |

## OFMA conditions

Attribution to open flightmaps is required. Changes to the data must be communicated within the GUL's stated period, and the app must preserve the licence's additional conditions for end-user modifications. The data is not a primary navigation source.

No OpenAIP data is used for the VFR/IFR database because its CC BY-NC 4.0 licence does not allow commercial reuse.

## VFR-to-IFR matching

A VFR point can support an IFR reference only when the IFR source has its own coordinate-bearing record and both source records have the same normalized name and exactly equal decimal latitude and longitude. The matching code deliberately rejects ident-only and near-coordinate matches. Current procedure extracts do not supply coordinates, so no such links are generated yet.

Data is reference-only and not an approved operational navigation source.
