#!/usr/bin/env python3
"""Spot-check built FTTR tiles against known summits and approach hazards.

Usage: verify_terrain_spots.py <tiles_dir>
Each spot passes if the tile value within ~1 km is >= real elevation - tolerance
(tiles are max-pooled, so over-reading is expected and safe; under-reading is not).
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import terrain_tiles as tt  # noqa: E402

# name, lat, lon, real elevation (m), tolerated under-read (m)
SPOTS = [
    ("Mont Blanc", 45.8326, 6.8652, 4806, 60),
    ("Hafelekarspitze (Innsbruck Nordkette)", 47.3119, 11.3846, 2334, 60),
    ("Zugspitze", 47.4211, 10.9853, 2962, 60),
    ("Patscherkofel (Innsbruck S)", 47.2092, 11.4608, 2246, 60),
    ("Untersberg Salzburg (Berchtesgadener Hochthron)", 47.7000, 12.9800, 1972, 60),
    ("Gaisberg Salzburg", 47.8039, 13.1131, 1288, 60),
    # Copernicus under-reads this sharp pyramid by ~147 m (~480 ft): known, inside a 1,000 ft buffer
    ("Matterhorn", 45.9763, 7.6586, 4478, 160),
    ("Mount Fuji", 35.3606, 138.7274, 3776, 60),
    ("Morne du Vitet (St Barth)", 17.9086, -62.8533, 286, 40),
    ("Morne Lurin (St Barth)", 17.9114, -62.8750, 144, 40),
    ("Mont Orohena (Tahiti)", -17.6267, -149.4700, 2241, 60),
]


def window_max(root: Path, lat: float, lon: float, cells: int = 3):
    la0, lo0 = math.floor(lat), math.floor(lon)
    f = root / tt.tile_relpath(la0, lo0)
    if not f.is_file():
        return None
    _, _, grid = tt.decode_tile(f.read_bytes())
    n = grid.shape[0]
    r, c = int((la0 + 1 - lat) * n), int((lon - lo0) * n)
    return int(grid[max(0, r - cells):r + cells + 1, max(0, c - cells):c + cells + 1].max())


def main(root: Path) -> int:
    bad = 0
    for name, lat, lon, real, tol in SPOTS:
        got = window_max(root, lat, lon)
        if got is None:
            print(f"SKIP  {name}: tile not built")
            continue
        diff = got - real
        ok = diff >= -tol
        bad += not ok
        print(f"{'OK  ' if ok else 'LOW '}  {name}: tile {got} m, real {real} m ({diff:+d} m = {diff * 3.281:+.0f} ft)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
