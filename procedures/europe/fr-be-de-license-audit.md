# France, Belgium and Germany — commercial reuse audit

**Checked:** 23 November 2026  
**Purpose:** Determine whether official aeronautical datasets may be ingested and redistributed in FlightTempo, including commercial app use. This is a source screening, not legal advice. Public access is not redistribution permission.

## Decision summary

| Country | Source | Rights finding | FlightTempo decision |
|---|---|---|---|
| France (FR) | SIA free-disposition digital products / Licence Ouverte v2.0 | Commercial reuse, adaptation and redistribution allowed for covered products, with attribution and preservation of meaning. Coverage must be checked product-by-product; UAS geographical-zone data is excluded from the open licence. | **Proceed with covered open products.** Keep eAIP DATA PDFs and XML/AIXM exports separate; document exact product scope and test completeness before publishing procedure records. |
| Belgium (BE) | AIM Belgium / skeyes eAIP and data provision | AIP is freely viewable online; data provision is restricted to specific users. The published skeyes application terms limit use to Belgium, prohibit copying/sharing/selling its underlying database absent express prior authorization, and require written approval for commercial uses outside the stated UAS-flight use. Free viewing is not a reuse licence. | **Blocked for redistribution pending written permission or an independently licensed dataset.** Do not scrape the eAIP into the app dataset. |
| Germany (DE) | DFS AIS Portal / DFS AIXM download | AIS Portal terms prohibit commercial resale/reuse of portal services/content, automated access except digital AIXM datasets, and other uses without prior written approval. AIXM is an exception to automation, not itself a reuse licence. AIP IFR/VFR charts and derived works require written approval for commercial reuse. | **Blocked pending exact AIXM product terms/licence verification.** Do not ingest portal AIP/chart content. Investigate only an explicitly licensed DFS digital dataset and preserve its licence. |

## Official evidence

### France
- SIA free-disposition catalogue and Open Licence: https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition.html
- eAIP listing: https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition/eaip.html
- Licence Ouverte terms: https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition.html
- Separate SIA XML/AIXM product listing must be evaluated on its own. Do not assume it contains full SID/STAR/approach legs.

### Belgium
- Skeyes terms (PDF): https://www.skeyes.be/media/2305/terms-and-conditions-of-use.pdf
- Skeyes access overview: https://www.skeyes.be/en/legal/
- Official eAIP access: https://ops.skeyes.be/
- Terms describe a limited, non-exclusive, non-transferable right, restricted to use in Belgium; database copying/sharing/selling requires prior authorization. Commercial purposes outside the specified use require written approval.

### Germany
- DFS AIS Portal disclaimer: https://ais.dfs.de/pilotservice/service/information/disclaimer/disclaimer.jsp
- DFS geo-data page: https://www.dfs.de/homepage/en/services/geo-data/
- EUROCONTROL AIXM overview (format specification only, not dataset rights): https://www.eurocontrol.int/model/aeronautical-information-exchange-model
- DFS portal terms: automated tools prohibited except for digital AIXM-format data; commercial reuse/sale of portal content prohibited; other uses and derived works require prior written approval. The AIXM exception is not an affirmative commercial redistribution licence.

## Implementation gates

1. Keep BE and DE source entries marked `permission_review_required` / unavailable in any app-facing manifest.
2. France: import only products explicitly covered by the SIA open licence; include source, licence version, attribution, source URL, retrieval date, AIRAC cycle, checksum and parser/version metadata.
3. Treat downloadable/viewable as separate from licence permission. No scraping or redistribution of restricted products.
4. Before publishing any terminal procedure dataset, validate procedure completeness, supported path terminators, coordinate resolution, runway/transition scope and cycle dates. Reference-only status stays explicit; operational capability flags remain disabled.
5. Re-open the official terms on each source change and record the evidence date.

## Next technical work
- France: prioritize the SIA openly licensed XML reference product for coordinate-bearing aerodrome/navaid/designated-point data, then separately validate the DATA PDF procedure importer against a wider set of airports and cycle changes.
- Belgium: pursue a written commercial redistribution grant from skeyes/AIM Belgium; meanwhile use only independently licensed open geodata (e.g. OurAirports) and OFMA coverage where applicable, clearly labelled by provenance.
- Germany: investigate exact DFS digital AIXM dataset product-level licence and redistribution terms; no ingestion until those terms expressly permit FlightTempo commercial redistribution.
