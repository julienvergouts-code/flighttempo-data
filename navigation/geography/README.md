# World geography pack

This directory contains two compressed Natural Earth 1:10m reference packs:

- \`world_geography.json.gz\`: a top-level JSON array of named cities/towns, major named peaks, islands and geographic landmarks. The array shape is required by the current Android \`NavigationRepository.loadWorldGeographyPackFromDisk\` implementation.
- \`world_hydrography.json.gz\`: compact GeoJSON-like geometry layers for rivers, lakes and land country boundaries. This is a companion dataset; the current Android landmark loader does not yet parse or render it.

## Source and licence

The builder downloads Natural Earth 1:10m GeoJSON source layers from the Natural Earth Vector repository. Natural Earth data is public domain. The metadata records the source URLs, upstream hashes and available Last-Modified/ETag values.

## Important limitations

These are cartographic/geographic reference layers, not aeronautical data. They are not terrain elevation models, obstacle databases, airspace boundaries, AIP data, or terrain-clearance references. Place coordinates and peak elevations are generalized map references and must not be used for operational navigation or obstacle/terrain clearance.

The landmark pack intentionally includes every named populated-place record in the Natural Earth source; it does not apply a population or scalerank cutoff. Curated landmarks add a few local visual references that may be absent from the global source.

The hydrography companion is published for future Android integration. Do not advertise rivers, lakes or borders as visible in the app until its downloader, parser, renderer and tests support this file.
