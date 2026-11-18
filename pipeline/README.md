# ADS-B observed corridor pipeline

This pipeline keeps ADS-B-derived observations separate from the existing navigation baseline.

## Important source limitation

adsb.lol documents **one whole-sky archive per UTC day**, split across release parts, with per-aircraft files in `traces/`. It does not document a historical city-pair query endpoint. Therefore `adsb_fetch.py` consumes an already downloaded/extracted archive directory and identifies airport-pair candidates by proximity to the origin and destination airports. It does not fabricate a route from a city-pair API.

Download the relevant daily archive from https://github.com/adsblol/globe_history (choose the appropriate year repository), join the release parts and extract them. Point `--input-dir` at the extracted `traces/` directory. Daily archives are large; do not download whole years for a single route.

## Run

```bash
python pipeline/adsb_fetch.py --input-dir /data/2026-11-17/traces --origin EBLG --destination LGAV --date 2026-11-17
python pipeline/corridor_cluster.py --input-dir observed_traces --fixes navigation/waypoints/flightgear_fixes.csv
python pipeline/validation.py --input preferred_routes/europe.json --fixes navigation/waypoints/flightgear_fixes.csv
```

The repository's generic `navigation/waypoints/waypoints.csv` is a header-only placeholder. Matching defaults to the populated `flightgear_fixes.csv`; its source is an old GPL-3.0 development baseline, so ADS-B-derived outputs and that baseline remain separate. The matcher reads common identifier/latitude/longitude column names and skips rows it cannot parse.

## Interpretation

The fetcher filters points below 10,000 ft for the saved cruise/climb/descent polyline, but checks airport proximity against the full trace first. The clustering stage uses a lightweight symmetric mean-nearest-point distance and deterministic grouping; this is intentionally a first baseline, not DBSCAN or a certified route classifier. Matched fixes are proximity matches only, not proof that a flight used those fixes or an airway. The sample confidence value is a heuristic and must not be interpreted as a probability.

## Licensing

adsb.lol data is ODbL 1.0. Keep attribution and the licence notice with every redistributed derived database. Review ODbL share-alike obligations before publishing merged or adapted datasets. The existing navigation baseline has a separate GPL-3.0 provenance; do not merge the datasets into one database without a licence compatibility review.
