#!/usr/bin/env python3
"""Parsers for the France SIA eAIP ENR pages (HTML), written against the real 2611 pages.

Pages used (all part of the free SIA eAIP package under the SIA Licence Ouverte):
  ENR 4.4  significant points   -> fixes
  ENR 4.1  radio navigation aids -> navaids
  ENR 3.2  RNAV/ATS routes       -> airway segments (ordered points with limits and track)
  ENR 2.1, 2.2, 5.1, 5.2 ... airspace tables -> airspace polygons

Everything here is pure (text in, records out) so it is testable with synthetic pages.
"""
from __future__ import annotations

import math
import re
from html.parser import HTMLParser
from typing import Any

NM_PER_KM = 1 / 1.852
EARTH_NM = 3440.065
COORD_PAIR = re.compile(
    r"(\d{2})°(\d{2})'(\d{2}(?:\.\d+)?)\"\s*([NS])\s*,?\s*(\d{3})°(\d{2})'(\d{2}(?:\.\d+)?)\"\s*([EW])")


class _RowParser(HTMLParser):
    """Collect table rows as lists of cell texts. Nested tables contribute their own rows;
    the outer row only keeps its own direct text, so nothing is counted twice."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._stack: list[dict[str, Any]] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "tr":
            self._stack.append({"cells": [], "cell": None})
        elif tag in ("td", "th") and self._stack:
            row = self._stack[-1]
            if row["cell"] is not None:
                row["cells"].append(_clean(" ".join(row["cell"])))
            row["cell"] = []
        elif tag == "br" and self._stack and self._stack[-1]["cell"] is not None:
            self._stack[-1]["cell"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._stack:
            row = self._stack[-1]
            if row["cell"] is not None:
                row["cells"].append(_clean(" ".join(row["cell"])))
                row["cell"] = None
        elif tag == "tr" and self._stack:
            row = self._stack.pop()
            if row["cell"] is not None:
                row["cells"].append(_clean(" ".join(row["cell"])))
            if any(row["cells"]):
                self.rows.append(row["cells"])

    def handle_data(self, data: str) -> None:
        if self._skip or not self._stack:
            return
        cell = self._stack[-1]["cell"]
        if cell is not None:
            cell.append(data)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def iter_rows(html: str) -> list[list[str]]:
    parser = _RowParser()
    parser.feed(html)
    parser.close()
    return [[c for c in cells] for cells in parser.rows]


def dms(deg: str, minutes: str, seconds: str, hemi: str) -> float:
    value = int(deg) + int(minutes) / 60 + float(seconds) / 3600
    return round(-value if hemi in "SW" else value, 6)


def find_coords(text: str) -> list[tuple[float, float]]:
    return [(dms(*m.group(1, 2, 3, 4)), dms(*m.group(5, 6, 7, 8))) for m in COORD_PAIR.finditer(text)]


def haversine_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(h)))


def _bearing(c: tuple[float, float], p: tuple[float, float]) -> float:
    la1, la2, dlo = math.radians(c[0]), math.radians(p[0]), math.radians(p[1] - c[1])
    y = math.sin(dlo) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlo)
    return math.degrees(math.atan2(y, x)) % 360


def _destination(c: tuple[float, float], bearing: float, nm: float) -> tuple[float, float]:
    d, b = nm / EARTH_NM, math.radians(bearing)
    la1, lo1 = math.radians(c[0]), math.radians(c[1])
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2))
    return round(math.degrees(la2), 5), round((math.degrees(lo2) + 540) % 360 - 180, 5)


# ---------------------------------------------------------------- fixes (ENR 4.4)

def parse_fixes(rows: list[list[str]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for cells in rows:
        if len(cells) < 2 or not re.fullmatch(r"[A-Z0-9]{2,6}", cells[0]):
            continue
        coords = find_coords(cells[1])
        if len(coords) != 1:
            continue
        key = (cells[0], coords[0])
        if key in seen:
            continue
        seen.add(key)
        routes = [r.strip() for r in cells[2].split(",") if r.strip()] if len(cells) > 2 and not find_coords(cells[2]) else []
        out.append({"ident": cells[0], "latitude": coords[0][0], "longitude": coords[0][1], "routes": " ".join(routes)})
    return out


# ---------------------------------------------------------------- navaids (ENR 4.1)

NAVAID_TYPES = {"VOR", "DME", "VOR-DME", "VORTAC", "NDB", "TACAN", "ILS", "LOC", "NDB-DME", "VOR/DME"}


def parse_navaids(rows: list[list[str]]) -> list[dict[str, Any]]:
    out = []
    for cells in rows:
        if len(cells) < 6 or cells[1] not in NAVAID_TYPES:
            continue
        coords = find_coords(cells[5])
        if len(coords) != 1:
            continue
        elevation = ""
        for cell in cells[6:8]:
            m = re.fullmatch(r"(\d+)\s*ft", cell)
            if m:
                elevation = m.group(1)
                break
        out.append({"name": cells[0], "type": cells[1], "ident": cells[2], "frequency": cells[3],
                    "latitude": coords[0][0], "longitude": coords[0][1], "elevation_ft": elevation})
    return out


# ---------------------------------------------------------------- vertical limits

def parse_limit(text: str) -> dict[str, Any]:
    t = text.strip().upper().replace("  ", " ")
    if t in ("SFC", "GND", "GROUND"):
        return {"ft": 0, "ref": "GND"}
    if t in ("UNL", "UNLIMITED"):
        return {"ft": 99999, "ref": "UNL"}
    m = re.fullmatch(r"FL\s*(\d{2,3})", t)
    if m:
        return {"ft": int(m.group(1)) * 100, "ref": "FL"}
    m = re.fullmatch(r"(\d+)\s*FT\s*(AMSL|ASFC|AGL|MSL)", t)
    if m:
        return {"ft": int(m.group(1)), "ref": "MSL" if m.group(2) in ("AMSL", "MSL") else "AGL"}
    return {"ft": None, "ref": "UNKNOWN"}


LIMITS = re.compile(r"^(.*?)\s*-{3,}\s*(.*?)$")


def split_limits(cell: str) -> tuple[dict, dict] | None:
    m = LIMITS.match(cell)
    if not m:
        return None
    upper, lower = parse_limit(m.group(1)), parse_limit(m.group(2))
    if upper["ref"] == "UNKNOWN" or lower["ref"] == "UNKNOWN":
        return None
    return lower, upper


# ---------------------------------------------------------------- airways (ENR 3.2)

ROUTE_ID = re.compile(r"^[A-Z]{1,3}\d{1,4}[A-Z]?$")
POINT_SYMBOLS = {"▲", "∆", "△", "▽", "▼", "◊", "◇", "○", "●", "■", "□"}


def parse_routes(rows: list[list[str]]) -> list[dict[str, Any]]:
    """Return one record per route with ordered points; segment limits belong to the point they follow."""
    routes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    point: dict[str, Any] | None = None
    for cells in rows:
        if len(cells) == 1 and ROUTE_ID.match(cells[0]):
            current = {"route": cells[0], "points": []}
            routes.append(current)
            point = None
            continue
        if current is None:
            continue
        coords = find_coords(" ".join(cells))
        if coords and len(cells) >= 2 and len(coords) == 1:
            name_cells = [c for c in cells if c not in POINT_SYMBOLS and not find_coords(c)]
            name = name_cells[0] if name_cells else ""
            m = re.search(r"\(\s*([A-Z0-9]{2,6})\s*\)\s*$", name)
            ident = m.group(1) if m else re.sub(r"\s+", " ", name).strip()
            point = {"ident": ident, "name": name, "lat": coords[0][0], "lon": coords[0][1],
                     "track": None, "upper": None, "lower": None}
            current["points"].append(point)
            continue
        if point is None:
            continue
        joined = " | ".join(cells)
        if len(cells) == 2 and re.fullmatch(r"\d{1,3}", cells[1]) and point["track"] is None:
            point["track"] = int(cells[1]) % 360
            continue
        if len(cells) == 1:
            lim = parse_limit(cells[0])
            if lim["ref"] != "UNKNOWN":
                if point["upper"] is None:
                    point["upper"] = lim
                elif point["lower"] is None:
                    point["lower"] = lim
        elif re.fullmatch(r"(FL\s*\d+|\d+\s*ft\s*A?MSL)", joined, flags=re.I):
            lim = parse_limit(joined)
            if point["upper"] is None:
                point["upper"] = lim
            elif point["lower"] is None:
                point["lower"] = lim
    return routes


def route_segments(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments = []
    for route in routes:
        pts = route["points"]
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if (a["lat"], a["lon"]) == (b["lat"], b["lon"]):
                continue
            lower = a["lower"]["ft"] if a["lower"] and a["lower"]["ft"] is not None else ""
            segments.append({
                "airway_id": route["route"], "segment_seq": 0,
                "from_ident": a["ident"], "from_latitude": a["lat"], "from_longitude": a["lon"],
                "to_ident": b["ident"], "to_latitude": b["lat"], "to_longitude": b["lon"],
                "distance_nm": round(haversine_nm((a["lat"], a["lon"]), (b["lat"], b["lon"])), 1),
                "mag_course": a["track"] if a["track"] is not None else "",
                "min_enroute_alt_ft": lower,
                "upper_limit_ft": a["upper"]["ft"] if a["upper"] and a["upper"]["ft"] is not None else "",
            })
    # sequence numbers per airway in document order
    counters: dict[str, int] = {}
    for s in segments:
        counters[s["airway_id"]] = counters.get(s["airway_id"], 0) + 1
        s["segment_seq"] = counters[s["airway_id"]]
    return segments


# ---------------------------------------------------------------- airspace (ENR 2.x, 5.x)

ARC = re.compile(r"arc\s+(horaire|anti-?horaire)\s+de\s+([\d.,]+)\s*(NM|km|m)\s+de\s+rayon\s+centr[ée]\s+sur\s+(.*)", re.I)
CIRCLE = re.compile(r"cercle\s+de\s+([\d.,]+)\s*(NM|km|m)\s+de\s+rayon\s+centr[ée]\s+sur\s+(.*)", re.I)
TYPE_WORDS = ("TMA", "CTA", "CTR", "TMZ", "RMZ", "SIV", "FIR", "UIR", "ZIT", "TSA", "TRA", "ATZ", "CBA", "FRA", "SECTEUR", "PARTIE")


def _radius_nm(value: str, unit: str) -> float:
    v = float(value.replace(",", "."))
    unit = unit.lower()
    return v if unit == "nm" else v * NM_PER_KM if unit == "km" else v / 1852


def circle_ring(centre: tuple[float, float], radius_nm: float, points: int = 48) -> list[list[float]]:
    ring = [list(_destination(centre, 360 * i / points, radius_nm)) for i in range(points)]
    ring.append(ring[0])
    return ring


def arc_points(centre: tuple[float, float], radius_nm: float, start: tuple[float, float],
               end: tuple[float, float], clockwise: bool, step: float = 6.0) -> list[list[float]]:
    a0, a1 = _bearing(centre, start), _bearing(centre, end)
    span = (a1 - a0) % 360 if clockwise else (a0 - a1) % 360
    n = max(1, int(span / step))
    out = []
    for i in range(1, n):
        ang = a0 + span * i / n if clockwise else a0 - span * i / n
        out.append(list(_destination(centre, ang % 360, radius_nm)))
    return out


def parse_geometry(text: str) -> tuple[list[list[float]] | None, dict[str, int]]:
    """Convert a SIA lateral-limits string to one ring [[lat, lon], ...].

    Returns (ring or None, stats). Border references ("Frontière franco-X") are joined by a straight
    line and counted in stats['border_segments']; such rings are flagged approximate by the caller.
    """
    stats = {"arcs": 0, "border_segments": 0}
    clean = _clean(text)
    m = CIRCLE.search(clean)
    if m and not find_coords(clean[:m.start()]):
        centre = find_coords(m.group(3))
        if len(centre) >= 1:
            return circle_ring(centre[0], _radius_nm(m.group(1), m.group(2))), stats
    tokens = [t.strip() for t in re.split(r"\s+-\s+", clean) if t.strip()]
    ring: list[list[float]] = []
    pending_arc = None
    for token in tokens:
        am = ARC.match(token)
        if am:
            centre = find_coords(am.group(4))
            if not centre:
                return None, stats
            pending_arc = (centre[0], _radius_nm(am.group(2), am.group(3)), am.group(1).lower() == "horaire")
            continue
        coords = find_coords(token)
        if len(coords) == 1 and re.fullmatch(r"[^A-Za-z]*" + COORD_PAIR.pattern + r"\s*(\(.*\))?", token):
            pt = list(coords[0])
            if pending_arc and ring:
                centre, radius, cw = pending_arc
                ring.extend(arc_points(centre, radius, tuple(ring[-1]), tuple(pt), cw))
                stats["arcs"] += 1
            pending_arc = None
            ring.append(pt)
        elif re.match(r"(?i)fronti[eè]re", token) or "côte" in token.lower() or "cote" in token.lower():
            stats["border_segments"] += 1
        else:
            if coords:
                return None, stats
    if len(ring) < 3:
        return None, stats
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring, stats


def _class_of(cells: list[str]) -> str:
    for c in cells:
        if re.fullmatch(r"[A-G]", c):
            return c
    return ""


def parse_airspace(rows: list[list[str]], section: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Parse one ENR airspace page. ``section`` is 'enr2' (CTA/TMA/CTR/TMZ...) or 'enr5' (P/R/D zones)."""
    stats = {"considered": 0, "parsed": 0, "no_geometry": 0, "no_limits": 0, "approx": 0, "arcs": 0,
             "border_segments": 0, "skipped_fir": 0}
    features: list[dict[str, Any]] = []
    name_hint = ""
    seen_ids: dict[str, int] = {}
    for cells in rows:
        joined = " ".join(cells)
        has_coords = bool(find_coords(joined)) or bool(CIRCLE.search(joined))
        limits_idx = next((i for i, c in enumerate(cells) if LIMITS.match(c)), None)
        if not has_coords or limits_idx is None:
            # a name row: remember it for the geometry row that follows
            if len(cells) <= 2 and not has_coords and cells and not LIMITS.match(cells[0]):
                if section == "enr5":
                    m = re.match(r"^LF\s+[PRD]\s+\S+(?:\s+\S+)?$", cells[0])
                    name_hint = (cells[0] + (" " + cells[1] if len(cells) > 1 else "")).strip() if m else name_hint
                else:
                    if re.match(r"^(" + "|".join(TYPE_WORDS) + r")\b", cells[0]) and len(cells[0]) < 90:
                        name_hint = cells[0]
            continue
        geom_idx = next((i for i, c in enumerate(cells) if (find_coords(c) or CIRCLE.search(c)) and i != limits_idx), None)
        if geom_idx is None:
            continue
        stats["considered"] += 1
        geom_text = cells[geom_idx]
        name = name_hint
        # name and geometry in the same cell: "TMA CLERMONT partie 3 46°06'16"N , ..."
        first = COORD_PAIR.search(geom_text)
        if first and first.start() > 0 and not geom_text[:first.start()].strip().endswith("-"):
            prefix = geom_text[:first.start()].strip()
            if prefix and len(prefix) < 90 and not CIRCLE.match(prefix):
                name, geom_text = prefix, geom_text[first.start():]
        # sector tables: "GS | 1 | FL 195 ---- SFC | geometry"
        lead = [c for i, c in enumerate(cells[:geom_idx]) if i != limits_idx]
        if not name or (cells[0] and cells[0] not in (name, geom_text) and geom_idx > 0 and not re.fullmatch(r"[A-G]", cells[0])):
            candidate = " ".join(c for c in lead if not re.fullmatch(r"[A-G]", c) and not LIMITS.match(c))
            if candidate and len(candidate) < 40 and geom_idx > limits_idx:
                name = candidate
        ring, gstats = parse_geometry(geom_text)
        if ring is None:
            stats["no_geometry"] += 1
            continue
        limits = split_limits(cells[limits_idx])
        if limits is None:
            stats["no_limits"] += 1
            continue
        lower, upper = limits
        name = re.sub(r"\s+", " ", name).strip()
        kind = ""
        if section == "enr5":
            m = re.match(r"^LF\s+([PRD])\b", name)
            kind = {"P": "P", "R": "R", "D": "D"}.get(m.group(1), "") if m else ""
        else:
            m = re.match(r"^(" + "|".join(TYPE_WORDS) + r")\b", name)
            kind = m.group(1) if m else ""
        if kind in ("FIR", "UIR"):
            stats["skipped_fir"] += 1
            continue
        stats["arcs"] += gstats["arcs"]
        stats["border_segments"] += gstats["border_segments"]
        approx = gstats["border_segments"] > 0
        if approx:
            stats["approx"] += 1
        lats = [p[0] for p in ring]
        lons = [p[1] for p in ring]
        base = f"{name}|{kind}|{ring[0][0]}|{ring[0][1]}"
        n = seen_ids.get(base, 0)
        seen_ids[base] = n + 1
        feature = {
            "id": f"sia-{abs(hash_text(base + str(n))):016x}"[:20],
            "type": kind or "OTHER", "name": name, "class": _class_of(cells),
            "lower": lower, "upper": upper, "rings": [ring],
            "bbox": [min(lats), min(lons), max(lats), max(lons)],
        }
        if approx:
            feature["approx"] = True
        features.append(feature)
        stats["parsed"] += 1
    return features, stats


def hash_text(text: str) -> int:
    import hashlib
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
