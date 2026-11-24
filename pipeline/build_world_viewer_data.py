#!/usr/bin/env python3
"""Build the data files for the world viewer.

Outputs (in --out):
  world_terrain.png   8-bit greyscale overview, 10 cells per degree, 60S..84N, 180W..180E.
                      Pixel = round(sqrt(max height in metres) * 255 / sqrt(9000)); 0 = sea or no tile.
  viewer_data.json    airports, route legs (great circle), terrain profile per leg (highest cell within the
                      corridor), airspace features near the legs and airports, land outlines, notices.
Terrain is read from the 10 degree block zips (or loose tiles); airspace from the OFMA and openAIP packs.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import terrain_tiles as tt  # noqa: E402

CPD = 10                      # overview cells per degree
LAT_TOP, LAT_BOTTOM = 84, -60
MAX_M = 9000.0
NM_PER_DEG = 60.0
EARTH_NM = 3440.065


def png_gray(arr: np.ndarray) -> bytes:
    h, w = arr.shape
    raw = b"".join(b"\x00" + arr[r].tobytes() for r in range(h))

    def chunk(kind: bytes, body: bytes) -> bytes:
        c = struct.pack(">I", len(body)) + kind + body
        return c + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def encode_height(m: np.ndarray) -> np.ndarray:
    return np.rint(np.sqrt(np.clip(m, 0, MAX_M)) * 255.0 / math.sqrt(MAX_M)).astype(np.uint8)


def decode_height(p: float) -> float:
    return (p * math.sqrt(MAX_M) / 255.0) ** 2


def iter_tiles(src: Path):
    for z in sorted(src.glob("*.zip")):
        with zipfile.ZipFile(z) as zf:
            for name in zf.namelist():
                if name.endswith(".fttr"):
                    yield zf.read(name)
    for f in sorted(src.rglob("*.fttr")):
        yield f.read_bytes()


def build_overview(src: Path) -> tuple[np.ndarray, int]:
    rows, cols = (LAT_TOP - LAT_BOTTOM) * CPD, 360 * CPD
    heights = np.zeros((rows, cols), dtype=np.int16)
    n = 0
    block = tt.CELLS // CPD
    for data in iter_tiles(src):
        lat0, lon0, grid = tt.decode_tile(data)
        if not (LAT_BOTTOM <= lat0 < LAT_TOP):
            continue
        small = grid.reshape(CPD, block, CPD, block).max(axis=(1, 3))
        r0 = (LAT_TOP - (lat0 + 1)) * CPD
        c0 = (lon0 + 180) * CPD
        heights[r0:r0 + CPD, c0:c0 + CPD] = small
        n += 1
    return heights, n


def gc_points(a, b, step_nm: float) -> list[tuple[float, float]]:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = 2 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
    n = max(2, int(d * EARTH_NM / step_nm) + 1)
    pts = []
    for i in range(n + 1):
        f = i / n
        A = math.sin((1 - f) * d) / math.sin(d)
        B = math.sin(f * d) / math.sin(d)
        x = A * math.cos(la1) * math.cos(lo1) + B * math.cos(la2) * math.cos(lo2)
        y = A * math.cos(la1) * math.sin(lo1) + B * math.cos(la2) * math.sin(lo2)
        z = A * math.sin(la1) + B * math.sin(la2)
        pts.append((round(math.degrees(math.atan2(z, math.hypot(x, y))), 4), round(math.degrees(math.atan2(y, x)), 4)))
    return pts


def dist_nm(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_NM * math.asin(min(1, math.sqrt(h)))


def profile(heights: np.ndarray, pts, corridor_nm: float, step_nm: float = 10.0) -> list[dict]:
    out, along = [], 0.0
    prev = None
    r_cells = max(1, int(math.ceil(corridor_nm / NM_PER_DEG * CPD)))
    for p in pts:
        if prev is not None:
            along += dist_nm(prev, p)
        prev = p
        row = int((LAT_TOP - p[0]) * CPD)
        col = int((p[1] + 180) * CPD) % heights.shape[1]
        r_lo, r_hi = max(0, row - r_cells), min(heights.shape[0], row + r_cells + 1)
        cols = [(col + dc) % heights.shape[1] for dc in range(-r_cells * 2, r_cells * 2 + 1)]
        if r_lo >= r_hi or not (LAT_BOTTOM <= p[0] < LAT_TOP):
            out.append({"nm": round(along), "m": None})
            continue
        out.append({"nm": round(along), "m": int(heights[r_lo:r_hi, cols].max())})
    return out


def near(point, polyline, limit_nm: float) -> bool:
    return any(dist_nm(point, q) <= limit_nm for q in polyline)


def feature_near(f: dict, polylines: list[list], limit_nm: float) -> bool:
    la0, lo0, la1, lo1 = f["bbox"]
    pad = limit_nm / NM_PER_DEG * 1.2 + 0.2
    for line in polylines:
        if any(la0 - pad <= p[0] <= la1 + pad and lo0 - pad <= p[1] <= lo1 + pad for p in line):
            for ring in f["rings"]:
                step = max(1, len(ring) // 60)
                if any(near(v, line if len(line) < 20 else line[::2], limit_nm) for v in ring[::step]):
                    return True
            if any(la0 <= p[0] <= la1 and lo0 <= p[1] <= lo1 for p in line):
                return True  # route crosses the bbox of a feature with a sparse outline
    return False


def load_airspace(root: Path, polylines, limit_nm: float) -> list[dict]:
    keep = []
    for source, folder in (("OFMA", "airspace/ofma"), ("openAIP", "airspace/openaip")):
        for pack in sorted((root / folder).glob("*.json.gz")):
            body = json.loads(gzip.decompress(pack.read_bytes()))
            for f in body["features"]:
                if f.get("type") in ("FIR", "UIR"):
                    continue
                if feature_near(f, polylines, limit_nm):
                    keep.append({
                        "src": source, "cc": pack.name.split(".")[0], "type": f.get("localType") or f["type"],
                        "name": f.get("name", ""), "cls": f.get("class", ""),
                        "lo": f["lower"], "hi": f["upper"],
                        "rings": [[[round(a, 3), round(b, 3)] for a, b in ring] for ring in f["rings"]],
                    })
    return keep


def land_outlines(path: Path) -> list[list[list[float]]]:
    out = []
    for line in path.read_text().splitlines():
        v = line.split()
        if len(v) >= 6:
            pts = [[float(v[i + 1]), float(v[i])] for i in range(0, len(v) - 1, 2)]
            out.append(pts[::2] if len(pts) > 40 else pts)
    return out


def build(src: Path, out: Path, root: Path = ROOT) -> dict:
    cfg = json.loads((root / "data/viewer_routes.json").read_text())
    airports = cfg["airports"]
    out.mkdir(parents=True, exist_ok=True)
    heights, tiles = build_overview(src)
    (out / "world_terrain.png").write_bytes(png_gray(encode_height(heights)))
    legs, lines = [], []
    for a, b in cfg["legs"]:
        pts = gc_points((airports[a]["lat"], airports[a]["lon"]), (airports[b]["lat"], airports[b]["lon"]), 10.0)
        lines.append(pts)
        legs.append({"from": a, "to": b, "nm": round(sum(dist_nm(pts[i], pts[i + 1]) for i in range(len(pts) - 1))),
                     "points": pts, "profile": profile(heights, pts, cfg["corridorNm"])})
    airport_lines = [[(v["lat"], v["lon"])] for v in airports.values()]
    airspace = load_airspace(root, lines, cfg["airspaceNm"]) + load_airspace(root, airport_lines, cfg["airportNm"])
    seen, unique = set(), []
    for f in airspace:
        key = (f["src"], f["cc"], f["name"], f["type"], f["rings"][0][0][0], f["rings"][0][0][1])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    data = {
        "schema": 1, "generatedFromTiles": tiles, "corridorNm": cfg["corridorNm"],
        "terrain": {"png": "world_terrain.png", "cellsPerDegree": CPD, "latTop": LAT_TOP, "latBottom": LAT_BOTTOM,
                    "maxM": MAX_M, "encoding": "m = (pixel * sqrt(9000) / 255)^2; 0 = sea or no tile"},
        "airports": airports, "legs": legs, "airspace": unique,
        "land": land_outlines(root / "world_land.txt"),
        "notices": [
            "Contains modified Copernicus DEM GLO-30 data (c) ESA / European Union; produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA; all rights reserved.",
            "Airspace: OFMA/OFMX (free commercial reuse under its licence) and openAIP (CC BY-NC, test phase, personal use only). Contains data from openAIP (www.openaip.net).",
            "Planning view only. Not certified, not for navigation. Terrain is a surface model, highest sample per cell; sharp peaks read low.",
        ],
    }
    (out / "viewer_data.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return {"tiles": tiles, "airspace": len(unique), "legs": len(legs)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True, help="folder with terrain-*.zip block files and/or loose .fttr tiles")
    ap.add_argument("--out", type=Path, default=ROOT / "viewer")
    a = ap.parse_args()
    print(build(a.src, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
