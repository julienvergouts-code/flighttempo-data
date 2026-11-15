# World corridor graph

`world_corridor_graph.bin` is generated from the imported legacy X-Plane AWY640 global airway segments and the FlightTempo airport reference.

## Binary format v1

All integers are little-endian. The file contains:

1. Header: `<4sHHIIII>` — magic `FTWG`, version, flags, node count, edge count, string-table byte count, airport-node count.
2. Node table: `<iiIHH>` — latitude/longitude in degrees × 10^7, UTF-8 identifier offset, identifier byte length, flags.
3. Edge table: `<IIIHBBII>` — from-node index, to-node index, UTF-8 airway/connector string offset and length, airway level (0 unknown, 1 low, 2 high), edge kind (0 source airway, 1 generated airport connector), direction (0 bidirectional), minimum altitude feet, maximum altitude feet.
4. UTF-8 string table.

Node flag 0 denotes a source airway endpoint; flag 1 denotes an airport reference point. Airport connector edges are generated direct links from an airport coordinate to up to three nearby airway nodes within 150 NM. They are not published SID/STAR geometry.

AWY640 does not encode a one-way restriction. Its edges are treated as bidirectional for this development route-preview graph. The source's low/high level code is retained as 1=low and 2=high.

## Source and limitations

- Source: https://github.com/ptsmonteiro/x-plane-navdata
- Source snapshot cycle token: 2012.08 (not an AIRAC cycle assertion)
- Source licence: GPLv3, as stated in the upstream README. Original source files and attribution are retained in navigation/sources/flightgear/.
- The graph is stale and may contain gaps, obsolete routes and inaccurate data.
- No SIDs, STARs, approaches, FIR polygons, NOTAM restrictions, operator rules or vertical airspace checks are encoded in this file.
- Airport connectors are synthetic graph links. They must not be presented as published procedures, clearances or operationally approved routes.

This file is for personal FlightTempo development and route-engine experiments only. It is not suitable for operational flight planning or navigation.
