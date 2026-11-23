# Terrain tiles (FTTR v1) and airspace packs

## Terrain tiles
Built by the **Build terrain tiles (Copernicus GLO-90)** workflow from the public Copernicus DEM GLO-90 bucket. Tiles are published on the `terrain-data` branch; `terrain/index.json` on `main` lists them and is registered in `navigation_manifest.json` as `terrain_tiles` (`tileBaseUrl` + tile path).

- One tile per 1 x 1 degree cell, named by its south-west corner: `tiles/N45/N45E006.fttr`.
- 400 x 400 cells per tile (9 arc-seconds, about 280 m north-south).
- **Each cell holds the highest source sample inside it, rounded up to whole metres** (max pooling, never averaged). A peak is never smoothed away; a cell may read higher than the ground at its centre but never lower than any sample inside it.
- Heights are metres above the EGM2008 geoid (about mean sea level). The source is a surface model (vegetation and structures included). Tiles over open sea do not exist: treat a missing tile as 0 m but tell the user the area has no data.
- Reference data for planning only; not for navigation or terrain-clearance decisions.

### Binary layout (little endian)
| Bytes | Field |
|---|---|
| 0-3 | magic `FTTR` |
| 4-5 | version (1) |
| 6-7 | south edge latitude, int16 |
| 8-9 | west edge longitude, int16 |
| 10-11 | rows (400) |
| 12-13 | cols (400) |
| 14-15 | cells per degree (400) |
| 16-17 | highest elevation in tile, int16 metres |
| 18-19 | flags (0) |
| 20- | zlib stream |

The zlib payload holds `rows*cols` int16 values: first all low bytes, then all high bytes ("byte shuffle"). Un-shuffle, read as int16, then take a running sum along each row (the data is stored as differences between neighbouring columns). Rows run north to south, columns west to east. Cell for a point: `row = floor((lat0 + 1 - lat) * 400)`, `col = floor((lon - lon0) * 400)`.

### Querying a route
Visit **every cell** the route corridor touches. Sampling coarser than a cell (0.15 NM) can step over a single-cell peak. `pipeline/terrain_tiles.py::max_elevation_along` is the reference implementation.

### Licence and attribution (Copernicus DEM)
Show: "(c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved. Produced using Copernicus WorldDEM-90." and pass on: "The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM-90."

The licence text grants free worldwide reproduction, distribution and adaptation without time limit; it does not use the word "commercial". The manifest keeps `terrain_tiles` blocked until `data/terrain_rights_confirmation.json` is set to confirmed by the owner.

## Airspace packs (OFMA)
`airspace/ofma/index.json` lists one `<REGION>.json.gz` pack per OFMA region (CTR, TMA, ATZ, RMZ, TMZ, D/R/P and similar; FIR/UIR excluded). Each feature has `type`, `name`, `class`, `lower`/`upper` (`ft` plus `ref` = AGL, MSL, FL, GND, UNL), `rings` (lists of `[lat, lon]`, closed) and `bbox` `[minLat, minLon, maxLat, maxLon]`. `approx: true` means a border-following boundary was drawn with straight lines. Download only the regions whose bbox the route touches. Updated every AIRAC cycle.

OFMA General Users' License: commercial use is allowed; keep "Contains information from the open flightmaps database, see www.openflightmaps.org"; the data is passed on under the same terms (GUL 4.5); alterations (declared in the index) must be communicated to OFMA within 15 days (GUL 4.3); if app users can edit the data, link the OFMA contributor site (GUL 4.4). Reference data only.
