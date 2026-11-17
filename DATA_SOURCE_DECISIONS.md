# FlightTempo — free global data source decisions

**Purpose:** build one worldwide FlightTempo reference and weather system using free sources, while keeping source provenance, licence conditions, coverage and confidence visible. This repository is not an approved operational navigation database.

## Hard boundaries

- No paid feeds or paid subscriptions in the default product.
- No unlicensed redistribution, reverse engineering or repackaging of proprietary simulator/vendor data.
- Keep the existing worldwide legacy X-Plane/FlightGear baseline for development and route-graph continuity. It is stale (legacy 2012.08 snapshot) and must never be labelled current AIRAC or operational.
- Keep published IFR procedures, legacy navigation records, VFR reference geometry, observed ADS-B tracks and generated route suggestions as distinct data classes.
- An observed route is not a published airway, SID, STAR or procedure. Do not derive or label procedure legs from traffic density.
- Do not fabricate missing fixes, procedure legs, weather hazards or source validity.

## Active Sky / HiFi

Active Sky is a **weather and simulation integration**, not a navigation database.

- Active Sky FS advertises a third-party API for weather lookup, effects, mode control and weather-condition control. The product page confirms API integration, but does not publish the actual endpoint/schema on the public page.
- Active Sky XP 12 documents an HTTP API; its API documentation is installed locally in the product's Program Files Documentation folder.
- The Active Sky FS / XP12 API must be treated as an optional **local user-owned simulator adapter**. It may read weather exposed by the user's running licensed installation for personal simulator use.
- Do not extract HiFi DataNet backend data, bypass its login, scrape private endpoints, proxy the feed as a FlightTempo public weather service, or commit Active Sky outputs to the public repository without explicit written permission from HiFi.
- Keep all Active Sky output tagged provider=HiFi Active Sky, scope=local_simulator, with simulator product/version, request time, weather mode (live/historical/custom), and validity timestamp where the API provides them.
- Never use simulator weather as operational weather or dispatch/flight-planning authority.

Official references:
- Active Sky FS: https://hifisimtech.com/asfs/
- Active Sky XP 12 API information: https://hifisimtech.com/asxp12/
- HiFi developer services / custom API integrations: https://hifisimtech.com/services/

## Free aviation weather sources to implement

### 1. DWD aviation turbulence (EDP) and icing (ADWICE)

The DWD aviation product catalogue (status 1 October 2025) lists both turbulence EDP and ADWICE polygon data as free of charge for aviation:

- EDP: GeoJSON vector polygons, EU and global coverage, three severity levels (moderate, severe, extreme), T+0 to T+36 in hourly steps, refreshed every 6 hours, 36 pressure levels from FL100 to FL450.
- ADWICE: GeoJSON vector polygons, EU and global coverage, severity levels, T+4 to T+36 in hourly steps, refreshed every 6 hours, 41 pressure levels.
- The catalogue says these products are accessed through configured DWD GeoServer WFS layers.
- DWD SWIM documentation lists candidate layer names including dwd:ICON_ADWICE_POLYGONE_GLOBAL, dwd:ICON_ADWICE_POLYGONE, dwd:ICON_EDPP_POLYGONS, dwd:ICON-Turbulenz-Polygone, and dwd:ICON-EU-Turbulence-Polygons.

**Important access gate:** the catalogue's "free for aviation" pricing is not by itself a public redistribution licence. The SWIM/MET-CEUS registry describes subscription and HTTP Basic authentication for its protected service. Before app-side direct access or public caching, test the exact WFS layer and obtain written confirmation of the allowed use, commercial-app display, caching and redistribution terms. Do not assume every listed layer is anonymous/public.

Sources:
- DWD aviation product catalogue: https://www.dwd.de/EN/specialusers/aviation/download/services/wafor/productlist_aviation_download.pdf
- DWD SWIM layer inventory: https://swimt.dwd.de/swim_docs/reference/service_transition.html
- DWD GeoServer: https://maps.dwd.de/geoserver/ows
- MET-CEUS service registry: https://eur-registry.swim.aero/service-description/met-ceus-en-route-hazardous-meteorological-polygon-service

### 2. NOAA Aviation Weather Center API

Suitable for current terminal weather and official aviation warnings:

- METAR: worldwide
- TAF: worldwide
- SIGMET: worldwide
- PIREP/AIREP: primarily US and North Atlantic
- G-AIRMET: contiguous US; AIRMET: Alaska

The official API recommends cache files for broad queries, limits requests to 100/minute and most endpoints to 400 results. Use a descriptive User-Agent and sensible refresh intervals. Do not describe the limited PIREP/AIRMET coverage as global.

Sources:
- API: https://aviationweather.gov/data/api/
- API use and restrictions: https://aviationweather.gov/data/api/

### 3. WAFS turbulence / icing grids

The official WAFS products provide global gridded turbulence and icing forecasts. WIFS access requires registration and eligibility (international flight operations or support to them), and credentials/API access. This is not an anonymous, no-account public feed, so it is not part of the free-by-default pipeline unless the user independently qualifies and the access terms permit the intended app use.

Sources:
- WAFS SIGWX: https://aviationweather.gov/sigwx/help.html
- WIFS eligibility: https://connect.aviationweather.gov/wifs/

## Free navigation / traffic sources

### OpenFlightMaps (OFMA)

- OFMA's General Users' License explicitly allows commercial use and derivative databases, subject to its conditions.
- Attribution is required.
- Alterations to OFMA data used in a public derivative/collective database must be communicated or contributed within the stated licence period (15 days in the current licence text); the application must provide an end-user mechanism for error reports/corrections.
- OFMA explicitly says its data is not certified and must not be used as a primary navigation source.
- Its stated mission is VFR aeronautical mapping. Treat its routes as VFR reference geometry; do not turn them into IFR SIDs/STARs or airways.
- The current downloads index lists regions including Belgium (EB), Germany (ED), France (LF), Netherlands (EH), Denmark (EK), Italy (LI), Austria (LO), and others. Current region pages must be checked individually; a map preview is not proof that a machine-readable data export is available for that region.

Sources:
- Downloads/regions: https://openflightmaps.org/downloads/
- FAQ: https://openflightmaps.org/faq/
- GUL: https://www.openflightmaps.org/live/downloads/20150306-GUL.pdf

### ADS-B observed routes

- adsb.lol offers an API under ODbL 1.0. Anonymous access is rate-limited (500 requests/day per IP); free adhoc keys are available subject to the provider's request process and ODbL explanation.
- Use only for **observed traffic tracks/corridors** and keep timestamps, aircraft identifiers where lawful, source, and observation count.
- Do not call the output a published airway, SID, STAR, route clearance or procedure.
- ODbL obligations (attribution and share-alike for derivative databases/produced works) must be implemented before publishing an aggregated track database.
- OpenSky is not the default source because commercial-use permission was not established in the earlier review.

Sources:
- adsb.lol API / licence: https://www.adsb.lol/docs/open-data/api
- free key and ODbL conditions: https://www.adsb.lol/request

## Existing navigation data that remains in place

- OurAirports airport/runway/navaid data: CC0/Public Domain as stated by provider; refresh through the existing pipeline.
- Legacy global X-Plane/FlightGear fixes, navaids, airway segments and corridor graph: retained as stale development baseline, clearly labelled and not operational.
- FAA CIFP: current US NAS procedure test/reference data only; not Europe or worldwide procedures.
- French SIA XML: open reference data, but do not assume it contains complete SID/STAR/approach legs.
- National AIP / EAD / simulator / Jeppesen data: do not redistribute without a verified licence covering the intended use.

## Implementation order

1. Pipeline reliability repair completed on 17 November 2026: queued workflows now check out the latest main branch instead of a stale triggering SHA; airline-only changes no longer trigger the navigation rebuild; the global airline directory is preserved by navigation manifest refreshes and covered by a regression test. The main navigation refresh and airline directory publication both passed after the fixes.
2. Probe the DWD WFS GetCapabilities endpoint, confirm the exact EDP and ADWICE layers, anonymous/authenticated access, schema, timestamps, forecast levels and pagination. Keep the first probe as a non-publishing test.
3. Confirm DWD's rights for use in a public FlightTempo app, caching and redistribution. If only licensed-user consumption is allowed, integrate as a user-provided/local provider rather than a shared public feed.
4. Add NOAA global METAR/TAF/SIGMET retrieval with bounded requests, caching and freshness timestamps.
5. Add OFMA VFR data only after confirming machine-readable downloads and implement attribution + user error reporting/change feedback.
6. Add adsb.lol observed-track collection only after implementing ODbL attribution/share-alike and retention controls.
7. Keep Active Sky as an optional local simulator adapter, separate from the shared weather backend.
8. Only enable app capabilities once source access, rights, coverage, freshness and validation all pass.

## Required data labels in the app

Every record should carry provider, dataset, source_url, retrieved_at_utc, valid_from_utc / valid_to_utc when supplied, forecast_reference_time_utc / forecast_lead_hours for forecasts, horizontal_coverage, vertical_level / flight_level when applicable, license_id, and data_class.

Recommended data_class values:
- published_ifr_procedure
- legacy_navigation_reference
- vfr_reference_geometry
- observed_adsb_track
- weather_observation
- weather_forecast
- weather_hazard_polygon
- simulator_local_weather

No weather or traffic layer should silently upgrade the status of a navigation dataset.
