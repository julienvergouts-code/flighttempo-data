"""FlightTempo terrain tiles (FTTR v1): encode, decode and route queries.

A tile covers one 1 x 1 degree cell. It holds CELLS x CELLS int16 elevations in
metres (rows run north -> south, columns west -> east). Every cell stores the
HIGHEST source sample inside its footprint (max pooling, rounded up), never an
average, so a peak is never smoothed away. The data is conservative: a cell can
be higher than the terrain at its centre, never lower than any sample in it.

Binary layout (little endian):
    header  <4sHhhHHHhH   magic 'FTTR', version, lat0, lon0, rows, cols, cells_per_degree, max_m, flags
    payload zlib(level 9) of: row-wise delta of the int16 grid, byte-shuffled
            (all low bytes, then all high bytes)
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path
from typing import Iterable

import numpy as np

MAGIC = b"FTTR"
VERSION = 1
HEADER = struct.Struct("<4sHhhHHHhH")
CELLS = 400  # per degree: 9 arc-seconds, about 280 m north-south
NM_PER_DEGREE = 60.0
M_TO_FT = 3.280839895


def tile_name(lat0: int, lon0: int) -> str:
    return f"{'N' if lat0 >= 0 else 'S'}{abs(lat0):02d}{'E' if lon0 >= 0 else 'W'}{abs(lon0):03d}"


def tile_relpath(lat0: int, lon0: int) -> str:
    name = tile_name(lat0, lon0)
    return f"tiles/{name[:3]}/{name}.fttr"


def max_pool(source: np.ndarray, cells: int = CELLS) -> np.ndarray:
    """Reduce ``source`` (rows x cols, metres) to cells x cells keeping the maximum.

    Source rows/columns that straddle two output cells count for both, so the
    result is never lower than any source sample inside a cell.
    """
    src = np.asarray(source, dtype=np.float32)
    if src.ndim != 2 or src.shape[0] < 1 or src.shape[1] < 1:
        raise ValueError("source must be a non-empty 2-D array")
    rows, cols = src.shape
    out = np.empty((cells, cells), dtype=np.float32)
    r_lo = [math.floor(i * rows / cells) for i in range(cells)]
    r_hi = [min(rows, max(math.ceil((i + 1) * rows / cells), r_lo[i] + 1)) for i in range(cells)]
    c_lo = [math.floor(j * cols / cells) for j in range(cells)]
    c_hi = [min(cols, max(math.ceil((j + 1) * cols / cells), c_lo[j] + 1)) for j in range(cells)]
    # first reduce columns, then rows (max is separable)
    by_col = np.empty((rows, cells), dtype=np.float32)
    for j in range(cells):
        by_col[:, j] = src[:, c_lo[j]:c_hi[j]].max(axis=1)
    for i in range(cells):
        out[i, :] = by_col[r_lo[i]:r_hi[i], :].max(axis=0)
    return out


def to_int16_metres(grid: np.ndarray) -> np.ndarray:
    """Round UP to whole metres (conservative) and clamp to a sane range."""
    return np.clip(np.ceil(grid), -500, 9000).astype(np.int16)


def encode_tile(lat0: int, lon0: int, grid_m: np.ndarray) -> bytes:
    if grid_m.dtype != np.int16 or grid_m.shape != (CELLS, CELLS):
        raise ValueError("grid must be int16 CELLS x CELLS")
    delta = grid_m.copy()
    delta[:, 1:] = grid_m[:, 1:] - grid_m[:, :-1]
    raw = delta.astype("<i2").tobytes()
    shuffled = raw[0::2] + raw[1::2]
    header = HEADER.pack(MAGIC, VERSION, lat0, lon0, CELLS, CELLS, CELLS, int(grid_m.max()), 0)
    return header + zlib.compress(shuffled, 9)


def decode_tile(data: bytes) -> tuple[int, int, np.ndarray]:
    magic, version, lat0, lon0, rows, cols, cpd, max_m, _flags = HEADER.unpack_from(data)
    if magic != MAGIC or version != VERSION:
        raise ValueError("not an FTTR v1 tile")
    payload = zlib.decompress(data[HEADER.size:])
    n = rows * cols
    if len(payload) != n * 2:
        raise ValueError("tile payload has the wrong size")
    raw = bytearray(n * 2)
    raw[0::2], raw[1::2] = payload[:n], payload[n:]
    delta = np.frombuffer(bytes(raw), dtype="<i2").reshape(rows, cols).astype(np.int32)
    grid = np.cumsum(delta, axis=1).astype(np.int16)
    if int(grid.max()) != max_m:
        raise ValueError("tile checksum (max elevation) mismatch")
    return lat0, lon0, grid


def cell_at(grid: np.ndarray, lat0: int, lon0: int, lat: float, lon: float) -> int:
    n = grid.shape[0]
    row = min(n - 1, max(0, int((lat0 + 1 - lat) * n)))
    col = min(n - 1, max(0, int((lon - lon0) * n)))
    return int(grid[row, col])


def max_elevation_along(tile_dir: Path, path: Iterable[tuple[float, float]], corridor_nm: float = 0.0,
                        step_nm: float = 0.1) -> dict:
    """Reference implementation of the app query: highest terrain within ``corridor_nm`` of a route.

    ``path`` is a list of (lat, lon). Missing tiles (open sea / not downloaded) are
    reported, never assumed to be zero. ``step_nm`` must stay below the cell size
    (60 NM / CELLS = 0.15 NM) or a single-cell peak can fall between samples; an app
    implementation should visit every cell the corridor touches.
    """
    pts = list(path)
    cache: dict[tuple[int, int], np.ndarray | None] = {}
    best, where, missing = None, None, set()

    def grid_for(lat: float, lon: float):
        key = (math.floor(lat), math.floor(lon))
        if key not in cache:
            f = tile_dir / tile_relpath(*key)
            cache[key] = decode_tile(f.read_bytes())[2] if f.is_file() else None
        if cache[key] is None:
            missing.add(tile_name(*key))
        return cache[key], key

    for (la1, lo1), (la2, lo2) in zip(pts, pts[1:]):
        dlat, dlon = la2 - la1, (lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2))
        length = math.hypot(dlat, dlon) * NM_PER_DEGREE
        steps = max(1, int(length / step_nm))
        side = int(math.ceil(corridor_nm / step_nm))
        for s in range(steps + 1):
            f = s / steps
            lat, lon = la1 + (la2 - la1) * f, lo1 + (lo2 - lo1) * f
            for off in range(-side, side + 1):
                # offset perpendicular to the leg
                norm = math.hypot(dlat, dlon) or 1.0
                plat = lat + (-dlon / norm) * off * step_nm / NM_PER_DEGREE
                plon = lon + (dlat / norm) * off * step_nm / NM_PER_DEGREE / max(0.2, math.cos(math.radians(lat)))
                grid, key = grid_for(plat, plon)
                if grid is None:
                    continue
                v = cell_at(grid, key[0], key[1], plat, plon)
                if best is None or v > best:
                    best, where = v, (round(plat, 4), round(plon, 4))
    return {"maxM": best, "maxFt": None if best is None else int(round(best * M_TO_FT)),
            "at": where, "missingTiles": sorted(missing)}
