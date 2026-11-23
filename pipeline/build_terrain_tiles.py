#!/usr/bin/env python3
"""Build FlightTempo terrain tiles (FTTR v1) from Copernicus DEM GLO-30.

Source: Copernicus DEM GLO-30 (public AWS open-data bucket, no account needed).
Each 1 x 1 degree GeoTIFF is reduced to 400 x 400 cells keeping the highest
sample per cell (see terrain_tiles.py) and written to ``--out``. Tiles that
already exist are skipped, so reruns only add what is missing. Open-sea tiles do
not exist in the source and are simply not published.

Fail-closed: canary peaks (Mont Blanc, Fuji, Orohena...) must read back inside a
plausible range or nothing is indexed.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import logging
import math
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PIPELINE = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE))
import terrain_tiles as tt  # noqa: E402

ROOT = PIPELINE.parent
CONFIG = ROOT / "data/terrain_regions.json"
UA = "FlightTempo-Data-Maintenance/1.0 (+https://github.com/julienvergouts-code/flighttempo-data)"
ATTRIBUTION = ("© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS "
               "by the European Union and ESA; all rights reserved. Produced using Copernicus WorldDEM-30.")
DISCLAIMER = ("The organisations in charge of the Copernicus programme by law or by delegation do not incur any "
              "liability for any use of the Copernicus WorldDEM-30.")
log = logging.getLogger("terrain")


class TerrainError(RuntimeError):
    pass


def source_url(cfg: dict[str, Any], lat0: int, lon0: int) -> str:
    return cfg["source"]["urlPattern"].format(
        bucket=cfg["source"]["bucket"], ns="N" if lat0 >= 0 else "S", lat=abs(lat0),
        ew="E" if lon0 >= 0 else "W", lon=abs(lon0))


def region_tiles(region: dict[str, Any]) -> list[tuple[int, int]]:
    return [(la, lo) for la in range(region["south"], region["north"])
            for lo in range(region["west"], region["east"])]


FETCH_ATTEMPTS = 6


def fetch_tile(url: str, sleep=time.sleep) -> bytes | None:
    """Download one source tile. 403/404 means the tile does not exist (open sea).

    Any other network failure (dropped connection, timeout, 5xx) is retried with
    backoff; a world build makes thousands of requests and must not die on one.
    """
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(FETCH_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return None
            if attempt == FETCH_ATTEMPTS - 1:
                raise
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            if attempt == FETCH_ATTEMPTS - 1:
                raise
        sleep(min(60, 2 ** (attempt + 1)))
    return None


def read_dem(raw: bytes):
    import rasterio  # imported lazily so the format code is testable without it
    from rasterio.io import MemoryFile
    with MemoryFile(raw) as mem, mem.open() as ds:
        arr = ds.read(1).astype("float32")
        nodata = ds.nodata
    if nodata is not None:
        arr[arr == nodata] = 0.0
    arr[arr < -500] = 0.0
    return arr


def build_one(cfg: dict[str, Any], out: Path, lat0: int, lon0: int, downloader=fetch_tile, reader=read_dem):
    rel = tt.tile_relpath(lat0, lon0)
    target = out / rel
    if target.is_file():
        data = target.read_bytes()
        return lat0, lon0, "kept", data
    raw = downloader(source_url(cfg, lat0, lon0))
    if raw is None:
        return lat0, lon0, "absent", None
    grid = tt.to_int16_metres(tt.max_pool(reader(raw)))
    data = tt.encode_tile(lat0, lon0, grid)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    return lat0, lon0, "built", data


def check_canaries(cfg: dict[str, Any], out: Path, region_ids: set[str]) -> list[str]:
    results = []
    for canary in cfg.get("canaries", []):
        la0, lo0 = math.floor(canary["lat"]), math.floor(canary["lon"])
        f = out / tt.tile_relpath(la0, lo0)
        if not f.is_file():
            continue  # canary outside the regions being built
        _, _, grid = tt.decode_tile(f.read_bytes())
        # highest cell within ~2 km of the summit (peaks fall on cell borders)
        n = grid.shape[0]
        row = int((la0 + 1 - canary["lat"]) * n)
        col = int((canary["lon"] - lo0) * n)
        window = grid[max(0, row - 8):row + 9, max(0, col - 8):col + 9]
        value = int(window.max())
        if not canary["minM"] <= value <= canary["maxM"]:
            import numpy as np
            r, c = np.unravel_index(int(grid.argmax()), grid.shape)
            raise TerrainError(
                f"canary {canary['name']}: {value} m outside {canary['minM']}-{canary['maxM']} m; "
                f"tile max {int(grid.max())} m at lat {la0 + 1 - (r + 0.5) / n:.4f} lon {lo0 + (c + 0.5) / n:.4f} "
                f"(expected lat {canary['lat']} lon {canary['lon']}); grid {grid.shape} dtype {grid.dtype}")
        results.append(f"{canary['name']}: {value} m")
    return results


def write_index(cfg: dict[str, Any], out: Path, tiles: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    regions = []
    for region in cfg["regions"]:
        entries = tiles.get(region["id"], [])
        regions.append({
            "id": region["id"], "name": region["name"],
            "bbox": [region["south"], region["west"], region["north"], region["east"]],
            "tileCount": len(entries), "sizeBytes": sum(e["sizeBytes"] for e in entries), "tiles": entries,
            **({"accuracyNote": region["accuracyNote"]} if region.get("accuracyNote") else {}),
        })
    index = {
        "schema": 1, "format": "FlightTempo terrain tiles (FTTR v1)",
        "tilePath": "tiles/{NS}{lat:02d}/{NS}{lat:02d}{EW}{lon:03d}.fttr",
        "cellsPerDegree": tt.CELLS, "cellSizeArcSeconds": 3600 / tt.CELLS,
        "heightUnit": "metre", "rowOrder": "north_to_south",
        "elevationMeaning": ("Highest source sample in each cell, rounded up (max pooling; never averaged). "
                             "Metres above the EGM2008 geoid (about mean sea level). Surface model: includes "
                             "vegetation and structures. Open-sea tiles are not published (treat as 0 m)."),
        "source": "Copernicus DEM GLO-30", "license": "Copernicus DEM free licence (GLO-30)",
        "attribution": ATTRIBUTION, "disclaimer": DISCLAIMER,
        "modificationNotice": "Resampled by max pooling from 1 arc-second to 9 arc-second cells.",
        "operationalUse": False,
        "notice": "Reference data for planning only. Not for navigation or terrain-clearance decisions.",
        "regions": regions,
    }
    body = json.dumps(index, indent=1, ensure_ascii=False) + "\n"
    (out / "index.json").write_text(body, encoding="utf-8")
    return index


def run(config: Path, out: Path, region_ids: list[str] | None, workers: int = 12,
        downloader=fetch_tile, reader=read_dem) -> int:
    cfg = json.loads(config.read_text(encoding="utf-8"))
    selected = [r for r in cfg["regions"] if not region_ids or r["id"] in region_ids]
    if not selected:
        raise TerrainError("no regions selected")
    out.mkdir(parents=True, exist_ok=True)
    tiles: dict[str, list[dict[str, Any]]] = {}
    previous = out / "index.json"
    if previous.is_file():  # keep already indexed regions that are not being rebuilt
        for r in json.loads(previous.read_text())["regions"]:
            tiles[r["id"]] = r["tiles"]
    counts = {"built": 0, "kept": 0, "absent": 0}
    for region in selected:
        todo = region_tiles(region)
        entries: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(build_one, cfg, out, la, lo, downloader, reader) for la, lo in todo]
            for fut in as_completed(futures):
                la, lo, status, data = fut.result()
                counts[status] += 1
                if data is not None:
                    _, _, grid = tt.decode_tile(data)
                    entries.append({"id": tt.tile_name(la, lo), "lat": la, "lon": lo,
                                    "maxM": int(grid.max()), "sizeBytes": len(data),
                                    "sha256": hashlib.sha256(data).hexdigest()})
        entries.sort(key=lambda e: e["id"])
        tiles[region["id"]] = entries
        log.info("%s: %d tiles (%d bytes)", region["id"], len(entries), sum(e["sizeBytes"] for e in entries))
    if sum(len(v) for v in tiles.values()) == 0:
        raise TerrainError("no tiles produced")
    log.info("canaries: %s", check_canaries(cfg, out, {r["id"] for r in selected}))
    write_index(cfg, out, tiles)
    log.info("tiles %s", counts)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--region", action="append")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run(args.config, args.out, args.region, args.workers)
    except TerrainError as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
