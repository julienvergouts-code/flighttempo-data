# Terrain tiles (FTTR v1) and airspace packs

## Terrain tiles
Built by the **Build terrain tiles (Copernicus GLO-30)** workflow from the public Copernicus DEM GLO-30 bucket. Tiles are published on the `terrain-data` branch; `terrain/index.json` on `main` lists them and is registered in `navigation_manifest.json` as `terrain_tiles` (`tileBaseUrl` + tile path).

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
Show: "(c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved. Produced using Copernicus WorldDEM-30." and pass on: "The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM-30."

The licence text grants free worldwide reproduction, distribution and adaptation without time limit; it does not use the word "commercial". The manifest keeps `terrain_tiles` blocked until `data/terrain_rights_confirmation.json` is set to confirmed by the owner.

## Airspace packs (OFMA)
`airspace/ofma/index.json` lists one `<REGION>.json.gz` pack per OFMA region (CTR, TMA, ATZ, RMZ, TMZ, D/R/P and similar; FIR/UIR excluded). Each feature has `type`, `name`, `class`, `lower`/`upper` (`ft` plus `ref` = AGL, MSL, FL, GND, UNL), `rings` (lists of `[lat, lon]`, closed) and `bbox` `[minLat, minLon, maxLat, maxLon]`. `approx: true` means a border-following boundary was drawn with straight lines. Download only the regions whose bbox the route touches. Updated every AIRAC cycle.

OFMA General Users' License: commercial use is allowed; keep "Contains information from the open flightmaps database, see www.openflightmaps.org"; the data is passed on under the same terms (GUL 4.5); alterations (declared in the index) must be communicated to OFMA within 15 days (GUL 4.3); if app users can edit the data, link the OFMA contributor site (GUL 4.4). Reference data only.


## Measured accuracy (spot checks, `scripts/verify_terrain_spots.py`)

Tiles are max-pooled, so flat or rounded terrain reads at or above the real height. Very sharp peaks are the weak spot of the source data (radar-derived surface model):

| Place | Tile vs real |
|---|---|
| Mont Blanc | +5 m |
| Innsbruck (Hafelekarspitze / Patscherkofel) | +77 m / +7 m |
| Zugspitze | -12 m |
| Mount Fuji | -7 m |
| Matterhorn | about -147 m (-480 ft) |
| Mont Orohena (Tahiti) | about -400 m (-1,300 ft) |

Under-reads over sharp alpine or tropical peaks can exceed a 1,000 ft buffer in Polynesia. French Polynesia carries an `accuracyNote` in the index so the app can show it.

## Known gaps

- Copernicus withholds GLO-30 tiles for a few countries (the ESA announcement says only "some countries"). A missing tile is published as absent and the app treats absent as open sea, so land in those countries is missing, not flat. Treat "no tile" over land as "no data".
- Licence: COPDEM-30 grants a free, worldwide, unlimited-in-time right to reproduce, distribute, adapt and combine the data. It does not mention commercial use either way. Required: the attribution and "Produced using Copernicus WorldDEM-30" notice (Art. 6a-b), the liability disclaimer (6c), no implied official endorsement (6d), and subsequent users bound by the same obligations (6e). `scripts/terrain_notices.py` holds the wording.
