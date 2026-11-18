# Preferred route learning (experimental)

This dataset contains **no ASL or Jeppesen crew flight plans**. Start with EBLG–LGAV as a test city pair, but do not publish a waypoint sequence until a lawful independent source and validation record exist.

## Source separation
- `graph_candidate`: computed from the existing FlightTempo graph; not a filed, cleared, preferred, or currently valid route.
- `historical_observed`: reconstructed from observations with an independently verified licence; not a filed route.
- `published_route`: route published by an authorised source with reuse permission; include exact source and licence.

Never label a graph-generated route as `preferred` merely because it is shortest. Do not use internal ASL/Jeppesen OFPs, screenshots, or route strings as ingestion or training inputs without explicit permission.

## Proposed route record fields
```json
{
  "route_id": "example-only",
  "origin": "EBLG",
  "destination": "LGAV",
  "classification": "graph_candidate",
  "waypoints": [],
  "airways": [],
  "geometry": [],
  "source_id": "flighttempo-graph",
  "source_version": "2012.08",
  "source_license": "review_required",
  "created_at_utc": null,
  "last_checked_utc": null,
  "validation_status": "unverified",
  "confidence": null,
  "evidence_count": 0
}
```

Do not add placeholder routes to the published JSON. Waypoint IDs are not unique worldwide: resolve against coordinates and graph topology. Reject disconnected legs and stale/unknown source status. Preserve source licences per record and per upstream dataset. Separate ODbL-derived observations from independently licensed navigation datasets.

## Test workflow
1. Generate EBLG–LGAV candidates using the existing graph without changing its source data.
2. Confirm connected edges, endpoints, geography, provenance and licence status.
3. Compare privately with the pilot's real-world route without copying any confidential route into GitHub or telemetry.
4. Publish only independently substantiated route patterns; retain the old version for rollback.
5. Never imply the route is ATC-cleared, airline-filed or operationally current.
