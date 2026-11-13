# Asian procedure data status

## Current position

No public, commercial-redistributable Asia-wide IFR SID/STAR/approach source has been confirmed. National AIP portals provide procedure information, but access to a chart or PDF is not the same as permission to extract it, republish it, or embed derived data in a commercial app.

## Reviewed national sources

| Jurisdiction | Official source / terms | Current FlightTempo decision |
| --- | --- | --- |
| Thailand | [CAAT AIP terms](https://ais.caat.or.th/term-condition) | Personal, non-commercial use only by default. Extraction, copying, storage, redistribution, republishing, adaptation and commercial use require authorization. CAAT invites commercial publishers and app developers to contact it. |
| India | [AAI disclaimer](https://aai.aero/en/disclaimer) and [AIM India terms](https://aim-india.aai.aero/terms-conditions) | AAI copyright remains with AAI; prior approval is required for reproduction/distribution. Do not import for public redistribution without approval. |
| Singapore | [CAAS terms of use](https://www.caas.gov.sg/terms-of-use/) and [AIS Singapore](https://aim-sg.caas.gov.sg/) | The default website terms limit downloads to one copy on one computer for personal, non-commercial use. No commercial bundle permission established. |
| Hong Kong | [Hong Kong AIS](https://www.ais.gov.hk/) | AIP items are labelled controlled documents and downloaded/copied versions are uncontrolled. Public commercial redistribution permission has not been established. |
| South Korea | [Current AIP GEN 0.1 copyright policy](https://aim.koca.go.kr/eaipPub/Package/2026-10-28-AIRAC/html/eAIP/KR-GEN-0.1-en-GB.html) | MOLIT claims copyright in all AIP content unless otherwise stated. Unauthorized reproduction/distribution is prohibited; use for profit or equivalent benefit requires prior permission or consultation. |

## Practical route for Asia

1. Identify the official AIS/AIP portal and current AIRAC package for each country.
2. Find whether it provides AIXM, a digital IFP dataset, or structured DATA procedure tables in the AIP.
3. Read the current copyright/reuse terms before extracting anything.
4. Request written commercial redistribution permission where required.
5. Only then build a country-specific importer and validate all procedures against the source AIP.

South Korea is a good example of why this distinction matters: its current AIP is directly accessible online, but GEN 0.1 expressly requires prior permission or consultation before using AIP information for profit. Public visibility is not a redistribution licence.

## Repository rule

Do not place Asian AIP procedure files or derived procedure rows in the public FlightTempo data repository until explicit redistribution rights are established. A private local test may still be technically possible, but the same source licence must be respected and it must not be represented as an official or operational navigation source.

The machine-readable inventory is in [source-registry.json](../source-registry.json).
