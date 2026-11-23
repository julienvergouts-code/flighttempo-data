#!/usr/bin/env python3
"""Pack FTTR tiles into 10x10 degree block zips for GitHub Release hosting.

One zip per block (<= 100 tiles). Zips are deterministic (fixed timestamps,
stored not deflated because tiles are already compressed) so unchanged blocks keep
their SHA-256 and the app can skip re-downloading them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

BLOCK_DEG = 10
TILE_RE = re.compile(r"^([NS])(\d{2})([EW])(\d{3})\.fttr$")
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def tile_coords(name: str) -> tuple[int, int]:
    m = TILE_RE.match(name)
    if not m:
        raise ValueError(f"not a tile file name: {name}")
    lat = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
    lon = int(m.group(4)) * (1 if m.group(3) == "E" else -1)
    return lat, lon


def block_origin(lat: int, lon: int) -> tuple[int, int]:
    return (lat // BLOCK_DEG) * BLOCK_DEG, (lon // BLOCK_DEG) * BLOCK_DEG


def block_id(lat0: int, lon0: int) -> str:
    return f"{'N' if lat0 >= 0 else 'S'}{abs(lat0):02d}{'E' if lon0 >= 0 else 'W'}{abs(lon0):03d}"


def pack(tiles_dir: Path, out_dir: Path, url_base: str) -> list[dict]:
    """Zip every tile under ``tiles_dir`` into block zips in ``out_dir``; return index entries."""
    groups: dict[tuple[int, int], list[Path]] = {}
    for f in sorted(tiles_dir.rglob("*.fttr")):
        lat, lon = tile_coords(f.name)
        groups.setdefault(block_origin(lat, lon), []).append(f)
    if not groups:
        raise ValueError("no tiles to pack")
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for (la0, lo0), files in sorted(groups.items()):
        bid = block_id(la0, lo0)
        name = f"terrain-{bid}.zip"
        with zipfile.ZipFile(out_dir / name, "w", zipfile.ZIP_STORED) as z:
            for f in sorted(files, key=lambda p: p.name):
                info = zipfile.ZipInfo(f.name, FIXED_TIME)
                info.compress_type = zipfile.ZIP_STORED
                z.writestr(info, f.read_bytes())
        data = (out_dir / name).read_bytes()
        entries.append({
            "id": bid, "bbox": [la0, lo0, la0 + BLOCK_DEG, lo0 + BLOCK_DEG],
            "file": name, "url": url_base.rstrip("/") + "/" + name,
            "tileCount": len(files), "sizeBytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "tiles": [f.name[:-5] for f in sorted(files, key=lambda p: p.name)],
        })
    return entries


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tiles", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--url-base", required=True)
    p.add_argument("--entries", type=Path, required=True, help="write block entries (JSON) here")
    a = p.parse_args()
    entries = pack(a.tiles, a.out, a.url_base)
    a.entries.write_text(json.dumps(entries, indent=1) + "\n", encoding="utf-8")
    print(f"packed {sum(e['tileCount'] for e in entries)} tiles into {len(entries)} blocks, "
          f"{sum(e['sizeBytes'] for e in entries)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
