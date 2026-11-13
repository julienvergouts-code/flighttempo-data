# Asian procedure data status

## Current position

FlightTempo does **not** currently have a confirmed, public-commercial-redistribution source for Asian IFR SIDs, STARs or instrument approaches. Several national AIP portals make current procedures freely viewable or downloadable, but free access is not the same as permission to extract, bundle and redistribute them in a public app.

No Asian procedure files have been imported or enabled. The review below covers selected major AIP portals; it is not a legal audit of every Asian state.

## National sources reviewed

| Jurisdiction | Authority/source | Reuse position found | FlightTempo decision |
| --- | --- | --- | --- |
| Thailand | [CAAT AIS terms](https://ais.caat.or.th/term-condition) | Personal non-commercial use only. The terms prohibit extracting, copying, storing, redistributing, republishing, adapting or commercially exploiting AIP material without authorization. Commercial app developers are directed to contact CAAT. | Permission required; do not ingest into public data. |
| India | [AAI disclaimer](https://aai.aero/en/disclaimer) and [AIM India terms](https://aim-india.aai.aero/terms-conditions) | AAI states its website material remains copyrighted and may not be reproduced or distributed without prior approval. AIM India terms restrict certain documents to AAI personnel for internal non-commercial use. | Prior written permission required. |
| Singapore | [CAAS terms of use](https://www.caas.gov.sg/terms-of-use/) and [AIM-SG AIP portal](https://aim-sg.caas.gov.sg/) | AIP and charts are viewable, but CAAS website terms limit downloaded copies to one computer and personal, non-commercial use. | Commercial redistribution permission required. |
| Hong Kong | [Hong Kong AIS](https://www.ais.gov.hk/) | AIP products are identified as controlled documents. The reviewed portal terms did not establish a public commercial redistribution grant. | Do not copy; obtain written permission or a clear licence first. |

Other national AIS portals, including China, Japan, Korea, Malaysia, Indonesia and the Philippines, have not yet passed a source-by-source redistribution review. Their availability online must not be treated as an open-data licence.

## What would unlock Asia

For each country, FlightTempo needs one of:

- an explicit open licence permitting public and commercial redistribution of extracted procedure data; or
- a written licence from the national AIS that permits redistribution in a commercial mobile application.

A user's individual subscription, personal AIP login or local simulator installation cannot be used to seed this public repository. This includes commercial navigation providers and any personal-use-only AIP source.

Once a country is cleared, store it as a separately attributable provider/country package with its own AIRAC cycle, effective/expiry dates, record counts, file hashes and validation results. Do not represent partial country coverage as Asia-wide coverage.

The current source-by-source status is machine-readable in [source-registry.json](../source-registry.json).
