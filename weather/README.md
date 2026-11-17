# FlightTempo weather sources

This directory contains source-specific weather integration research and metadata probes. The app-facing provider contract is [weather_manifest.json](../weather_manifest.json).

## Verified live feed: NOAA Aviation Weather Center

The metadata-only GitHub Actions probe ran successfully on 17 November 2026:

| Product | Coverage | Result |
| --- | --- | --- |
| METAR | Worldwide | EBBR query returned 1 record (HTTP 200) |
| TAF | Worldwide | EBBR query returned 1 record (HTTP 200) |
| Current SIGMET cache | Worldwide | 151 records retrieved from the public cache |
| PIREP/AIREP cache | Primarily US and North Atlantic | 2,350 reports retrieved |

Additional endpoint checks against the exact URLs used by the Android map code:

- `/api/data/isigmet?format=geojson`: HTTP 200, 150 features
- `/api/data/sigmet?format=geojson`: HTTP 200, 149 features
- `/api/data/airsigmet?format=geojson`: HTTP 200, 1 feature
- `/api/data/surface?format=geojson`: **HTTP 404**

The last result identifies a real map-layer defect: the current implementation's surface-analysis URL is not a valid AWC API endpoint. Its fallback pressure centers must be removed; synthetic H/L centers must never be drawn as live weather. Show the surface-analysis layer as unavailable until a supported, verified source is integrated.

Only availability, counts and field names are committed. No raw weather observations or hazard records are stored in this repository.

### App integration rules

- Use the documented AWC Data API directly from a native Android HTTP client or an authorized backend.
- METAR and TAF are queried by ICAO airport identifier.
- Use the global SIGMET cache for current worldwide warning polygons; it is refreshed by AWC once per minute.
- PIREPs/AIREPs are reports of observed conditions, including turbulence and icing. They are not forecasts and are not worldwide.
- Respect the 100 requests/minute limit, the typical 400-result query cap, and use a descriptive User-Agent.
- Browser CORS is disabled. Native Android HTTP is not browser CORS, but it must still respect AWC's request limits and terms.
- Store issue/observation time, validity interval, source, and retrieval time. Expire warnings when their published validity ends.
- Keep official SIGMETs separate from model guidance and pilot reports.

Official API documentation: https://aviationweather.gov/data/api/

### Required Android map corrections

1. Keep the verified international SIGMET GeoJSON endpoint. The legacy SIGMET endpoint also returns data; do not merge both blindly because their feature sets overlap. Prefer the global SIGMET cache or de-duplicate by FIR, series identifier and validity interval.
2. Remove the unsupported `/api/data/surface?format=geojson` request and the four hardcoded pressure-center fallback points. If the source fails, return an explicit unavailable state and draw no pressure centers/fronts.
3. Add the AWC PIREP/AIREP feed as a separate observation layer. Use report coordinates, observation time, turbulence/icing intensity and vertical bounds. Label reports as pilot observations, not forecast corridors. Filter stale reports and avoid implying worldwide coverage.
4. Do not label the current three sampled 250 hPa wind points and synthetic line segments as a complete jetstream analysis. They are sparse upper-air wind samples. A proper route layer needs time-aware sampling at multiple pressure levels (at least 300/250/200/150 hPa) along the full route, with wind direction/speed and temperature retained at each point.
5. Do not infer turbulence or icing from a high-wind threshold. Without a verified EDR/icing forecast, show SIGMETs and PIREPs as their actual data classes and label any model-derived shear indicator as a non-operational proxy.

## Regional turbulence and icing guidance: NOAA GFA

The AWC Graphical Forecasts for Aviation includes:
- GTG / EDR turbulence guidance
- Current Icing Product (CIP)
- Regional forecasts and warning overlays

Its documented coverage is the United States (including Alaska and Hawaii), the Gulf and Caribbean, and portions of the Atlantic and Pacific. It is not a worldwide turbulence/icing grid. A supported machine-readable integration endpoint has not yet been verified, so FlightTempo must not scrape undocumented map endpoints.

Reference: https://aviationweather.gov/gfa/help/

## DWD EDP turbulence and ADWICE icing

The DWD aviation product catalogue lists EDP turbulence and ADWICE icing polygons as free of charge for aviation. The catalogue describes GeoJSON polygons, global and European coverage, forecast levels and hourly steps.

However, an automated anonymous access probe found:
- WFS: 61 feature types, no candidate EDP/ADWICE layer
- WMS: 207 layers, no candidate EDP/ADWICE layer
- WCS: 118 coverages, no candidate EDP/ADWICE coverage

The DWD SWIM/MET-CEUS aviation hazard service is a protected service requiring subscription and HTTP Basic Authentication. "Free for aviation" does not establish anonymous access or public redistribution rights.

Do not enable DWD layers until DWD confirms access, permitted use in a public app, caching and redistribution rights.

References:
- DWD aviation product catalogue: https://www.dwd.de/EN/specialusers/aviation/download/services/wafor/productlist_aviation_download.pdf
- DWD SWIM layer inventory: https://swimt.dwd.de/swim_docs/reference/service_transition.html
- DWD service registry: https://eur-registry.swim.aero/service-description/met-ceus-en-route-hazardous-meteorological-polygon-service

## HiFi Active Sky FS

Active Sky remains an optional local simulator weather adapter:
- It is not a navigation-data source.
- The API is intended for local simulator integration; the public product page does not publish the full endpoint/schema.
- The exact installed Active Sky FS version and its local API documentation are required before implementation.
- Do not scrape HiFi DataNet, bypass authentication or redistribute/proxy its weather feed without written permission.

Reference: https://hifisimtech.com/asfs/

## What is not yet available globally for free

As of the 17 November 2026 probes, FlightTempo has not verified a public no-key worldwide gridded turbulence/icing forecast feed. The verified free global layer is METAR/TAF/SIGMET; PIREP coverage is regional. DWD EDP/ADWICE may be available to eligible aviation users through a protected service, and HiFi Active Sky can be used locally if its API contract is supplied.

Do not label global SIGMETs or PIREPs as a substitute for a continuous gridded turbulence/icing forecast. Do not create synthetic hazard polygons or infer hazard severity from unrelated data.
