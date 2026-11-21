# Non-US ADS-B corridor learning (Milestone 1)

Evidence generation only; this never modifies the authoritative navigation graph.

- Non-US airport pairs only; airport identifiers beginning K, P, or T are excluded.
- Ground samples are retained to anchor departure/arrival before anonymisation.
- readsb top-level timestamp is Unix epoch base; each trace row's first value is a relative seconds offset.
- Output contains airport pairs, anonymised sampled geometry, fix sequences, sample counts, low-confidence inferred links and FTWG A* comparison.
- No aircraft hex, registration, callsign, raw trace rows, or per-point timestamps are written.
- A single observation remains INFERRED_OBSERVATION / low confidence. Promotion requires repeat independent evidence or explicit airway matching.
- ADS-B is observed trajectory evidence, not filed route, clearance, or proof of airway use.
- Raw traces stay local; never commit them.
- ADSB.lol is ODbL 1.0; verify attribution/share-alike obligations before redistribution.

## Run locally

```bash
python scripts/adsb_learning/build_corridors.py --trace /path/to/trace.json --trace /path/to/another.json --output /tmp/corridor_evidence.json
```

The existing FlightGear/X-Plane graph has source cycle token 2012.08. A* comparison proves graph parser compatibility/path availability only, not current AIRAC validity or operational suitability.
