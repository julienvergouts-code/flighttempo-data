# ADS-B observed routes

Learned airport-to-airport flight paths, built only from ADSB.lol ADS-B traces. They are evidence of what aircraft flew, not
filed routes, clearances or proof that an airway was used.

## Method (simple, no navigation graph)

`pipeline/adsb_observed_routes.py`, weekly workflow `update-adsb-observed-routes.yml`.

1. Read airline-style traces (callsign of three letters plus a digit) from one ADSB.lol archive day, through HTTP range
   reads of the daily release (`pipeline/adsb_archive.py`). Nothing is stored except the result.
2. Cut each trace into complete flights: airborne between two ground samples, ground seen at both ends.
3. Name origin and destination from OurAirports airports within 8 NM of the ground samples.
4. Keep a flight if the leg is at least 150 NM, reached 20,000 ft and its path is at most 1.6 times the direct distance.
5. Resample to a point every 20 NM. Paths of one airport pair whose mean separation is within 12 NM form one route; the
   first path seen is kept and flights are counted. At most six routes per pair.
6. Confidence: LOW 1-2 flights, MEDIUM 3-4, HIGH 5 or more.

Output: `routes/observed/observed_routes.json.gz` and `routes/observed/index.json`. Each archive day is counted once
(`processedDates`). No aircraft id, registration, callsign or per-point timestamp is stored.

Nothing from the 2012 FlightGear/X-Plane set (fixes, airways, the FTWG graph) is read, so this layer is separable from it.
`tests/test_adsb_observed_routes.py` fails if the code starts mentioning those sources.

## Licence check (ADSB.lol)

What was read on 2026-11-24:

- adsb.lol "Historical data" page: the data is under "ODbL 1.0 ... use it freely, just keep it open", "open, ODbL, since the
  beginning". It links to a "Privacy and License" page.
- Repository `adsblol/globe_history_2024` README: "This database is made available under the Open Database License:
  http://opendatacommons.org/licenses/odbl/1.0/". The repository metadata lists ODbL-1.0 and CC0-1.0.
- `github.com/adsblol` organisation page: "openly licensed, publicly available, unfiltered flight tracking"; the
  `globe_history_2026` repository is tagged ODbL-1.0.

Not confirmed: the content of the linked "Privacy and License" page (not reachable from this session), any separate terms of
use, and the 2026 repository README itself (the fetch was refused; the 2024 README and the organisation page were read).

Reading: ODbL 1.0 permits commercial use with attribution, and requires a published derived database to be offered under
ODbL (share-alike). Whether this layer counts as a derived database that must be shared, and how to handle that in the
app, has not been reviewed. Tier in the manifest: `odbl_1_0_share_alike_obligations_unreviewed_personal_use_only`,
`personalUseOnly: true`, `commercialUseAllowed: false`. It passes the rights gate only while `data/usage_scope.json` says
personal. Required attribution: "Contains information from ADSB.lol, made available under the Open Database License
(ODbL) 1.0."

## What happened to the earlier ADS-B work

The earlier ChatGPT/Gemini work lives on branches `feature/adsb-route-learning` (PR #26, open) and
`feature/adsb-observed-corridor-pipeline`. They have no common history with `main` (521 commits, no merge base), so they
cannot be merged. That code is a benchmark: it streams the archive, picks up to 50 European aircraft, matches their
positions to the 2012 fix list, compares them with an A* route over the 2012 FTWG graph and writes counts only (candidate
links with promotion disabled). It does not produce route geometry for the app. The archive range reader was the useful part;
it is carried over in `pipeline/adsb_archive.py`. The benchmark itself ran successfully (for example run 45176769217).
The two workflows that came with it on `main` pointed at files that exist only on that branch, which is why the
`unit-tests` check failed on unrelated pull requests.
