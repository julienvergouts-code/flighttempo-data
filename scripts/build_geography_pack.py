#!/usr/bin/env python3
"""Build FlightTempo's global offline geography packs from Natural Earth 1:10m.

The landmark pack intentionally remains a top-level JSON array because the
current Android NavigationRepository loader expects JSONArray after gzip.
Hydrography and country boundaries are emitted as a companion pack; the
current Android loader does not yet consume that companion file.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GEO_DIR = ROOT / "navigation" / "geography"
USER_AGENT = "FlightTempo-GeoBuilder/2.0 (https://github.com/julienvergouts-code/flighttempo-data)"

BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
SOURCES = {
    "populated_places": BASE + "ne_10m_populated_places_simple.geojson",
    "elevation_points": BASE + "ne_10m_geography_regions_elevation_points.geojson",
    "geography_points": BASE + "ne_10m_geography_regions_points.geojson",
    "rivers": BASE + "ne_10m_rivers_lake_centerlines.geojson",
    "lakes": BASE + "ne_10m_lakes.geojson",
    "country_borders": BASE + "ne_10m_admin_0_boundary_lines_land.geojson",
}

# Deliberate local-detail overrides: Natural Earth is global but may omit
# small islands, VFR landmarks and useful named features.
CURATED_LANDMARKS = [
    {"name": "Split", "country": "HR", "kind": "CITY", "lat": 43.5081, "lon": 16.4402, "popRank": 1},
    {"name": "Zadar", "country": "HR", "kind": "CITY", "lat": 44.1194, "lon": 15.2314, "popRank": 2},
    {"name": "Dubrovnik", "country": "HR", "kind": "CITY", "lat": 42.6507, "lon": 18.0944, "popRank": 1},
    {"name": "Šibenik", "country": "HR", "kind": "CITY", "lat": 43.7350, "lon": 15.8952, "popRank": 3},
    {"name": "Brač Island", "country": "HR", "kind": "ISLAND", "lat": 43.3075, "lon": 16.6528, "elevationFt": 2552, "popRank": 2},
    {"name": "Hvar Island", "country": "HR", "kind": "ISLAND", "lat": 43.1450, "lon": 16.7333, "elevationFt": 2060, "popRank": 2},
    {"name": "Korčula Island", "country": "HR", "kind": "ISLAND", "lat": 42.9500, "lon": 16.9000, "popRank": 3},
    {"name": "Vis Island", "country": "HR", "kind": "ISLAND", "lat": 43.0414, "lon": 16.1536, "popRank": 3},
    {"name": "Dinara Peak", "country": "HR", "kind": "PEAK", "lat": 44.0625, "lon": 16.3828, "elevationFt": 6007, "popRank": 2},
    {"name": "Biokovo (Sv. Jure)", "country": "HR", "kind": "PEAK", "lat": 43.3419, "lon": 17.0536, "elevationFt": 5781, "popRank": 2},
    {"name": "Sarajevo", "country": "BA", "kind": "CITY", "lat": 43.8563, "lon": 18.4131, "popRank": 1},
    {"name": "Mostar", "country": "BA", "kind": "CITY", "lat": 43.3438, "lon": 17.8078, "popRank": 2},
    {"name": "Kotor Bay", "country": "ME", "kind": "FEATURE", "lat": 42.4247, "lon": 18.7712, "popRank": 2},
    {"name": "Durmitor (Bobotov Kuk)", "country": "ME", "kind": "PEAK", "lat": 43.1283, "lon": 19.0342, "elevationFt": 8278, "popRank": 2},
    {"name": "Corfu Island", "country": "GR", "kind": "ISLAND", "lat": 39.6243, "lon": 19.9217, "popRank": 1},
    {"name": "Kefalonia Island", "country": "GR", "kind": "ISLAND", "lat": 38.1754, "lon": 20.5692, "elevationFt": 5341, "popRank": 2},
    {"name": "Mt. Olympus", "country": "GR", "kind": "PEAK", "lat": 40.0856, "lon": 22.3586, "elevationFt": 9573, "popRank": 1},
    {"name": "Corinth Canal", "country": "GR", "kind": "FEATURE", "lat": 37.9344, "lon": 22.9839, "popRank": 2},
    {"name": "Mont Blanc", "country": "FR", "kind": "PEAK", "lat": 45.8325, "lon": 6.8644, "elevationFt": 15777, "popRank": 1},
    {"name": "Matterhorn", "country": "CH", "kind": "PEAK", "lat": 45.9764, "lon": 7.6586, "elevationFt": 14692, "popRank": 1},
    {"name": "Jungfrau", "country": "CH", "kind": "PEAK", "lat": 46.5369, "lon": 7.9625, "elevationFt": 13642, "popRank": 2},
    {"name": "Zugspitze", "country": "DE", "kind": "PEAK", "lat": 47.4211, "lon": 10.9853, "elevationFt": 9718, "popRank": 1},
    {"name": "Grossglockner", "country": "AT", "kind": "PEAK", "lat": 47.0742, "lon": 12.6947, "elevationFt": 12461, "popRank": 1},
    {"name": "Triglav", "country": "SI", "kind": "PEAK", "lat": 46.3783, "lon": 13.8367, "elevationFt": 9396, "popRank": 2},
    {"name": "Marmolada (Dolomites)", "country": "IT", "kind": "PEAK", "lat": 46.4344, "lon": 11.8514, "elevationFt": 10968, "popRank": 2},
    {"name": "Mt. Etna", "country": "IT", "kind": "PEAK", "lat": 37.7510, "lon": 14.9934, "elevationFt": 11014, "popRank": 1},
    {"name": "Lake Constance", "country": "DE", "kind": "FEATURE", "lat": 47.6360, "lon": 9.3890, "popRank": 2},
    {"name": "Lake Garda", "country": "IT", "kind": "FEATURE", "lat": 45.6390, "lon": 10.6690, "popRank": 2},
    {"name": "Lake Balaton", "country": "HU", "kind": "FEATURE", "lat": 46.8310, "lon": 17.7340, "popRank": 2},
    {"name": "Lake Geneva", "country": "CH", "kind": "FEATURE", "lat": 46.4410, "lon": 6.5190, "popRank": 2},
    {"name": "Liège", "country": "BE", "kind": "CITY", "lat": 50.6326, "lon": 5.5797, "popRank": 1},
    {"name": "Namur", "country": "BE", "kind": "CITY", "lat": 50.4674, "lon": 4.8720, "popRank": 2},
    {"name": "Spa / Ardennes", "country": "BE", "kind": "FEATURE", "lat": 50.4922, "lon": 5.8647, "elevationFt": 2277, "popRank": 2},
]

def fetch_geojson(url: str) -> tuple[dict[str, Any], dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
                obj = json.loads(raw.decode("utf-8"))
                if obj.get("type") != "FeatureCollection" or not isinstance(obj.get("features"), list):
                    raise ValueError(f"Unexpected GeoJSON FeatureCollection: {url}")
                metadata = {
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "lastModified": response.headers.get("Last-Modified", ""),
                    "etag": response.headers.get("ETag", ""),
                }
                return obj, metadata
        except Exception as exc:  # retry transient upstream failures
            last_error = exc
    raise RuntimeError(f"Unable to fetch required Natural Earth source {url}: {last_error}")

def first(props: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = props.get(key)
        if value not in (None, ""):
            return value
    return default

def feature_point(feature: dict[str, Any]) -> tuple[float, float] | None:
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates")
    if geometry.get("type") != "Point" or not isinstance(coords, list) or len(coords) < 2:
        return None
    try:
        lon, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return lat, lon

def build_landmarks(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    landmarks: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(item: dict[str, Any]) -> None:
        name = str(item.get("name") or "").strip()
        try:
            lat, lon = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            return
        if not name or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return
        kind = str(item.get("kind") or "FEATURE").strip().upper()
        country_key = str(item.get("country") or "").strip().casefold()
        key = (name.casefold(), kind, country_key, round(lat, 3), round(lon, 3))
        if key in seen:
            return
        seen.add(key)
        record: dict[str, Any] = {
            "name": name,
            "country": str(item.get("country") or "").strip()[:8],
            "kind": kind,
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "popRank": max(1, min(9, int(item.get("popRank", 5)))),
        }
        elevation = item.get("elevationFt")
        if elevation is not None:
            try:
                elevation_ft = int(round(float(elevation)))
                if elevation_ft > 0:
                    record["elevationFt"] = elevation_ft
            except (TypeError, ValueError):
                pass
        landmarks.append(record)

    for item in CURATED_LANDMARKS:
        add(item)

    # No population/scalerank cutoff: retain every named Natural Earth place.
    for feature in sources["populated_places"]["features"]:
        props = feature.get("properties") or {}
        point = feature_point(feature)
        name = first(props, "name", "NAME", "nameascii", "NAMEASCII")
        if not point or not name:
            continue
        scalerank = first(props, "scalerank", "SCALERANK", default=8)
        try:
            rank = max(1, min(9, int(scalerank) + 1))
        except (TypeError, ValueError):
            rank = 8
        country = first(props, "iso_a2", "ISO_A2", "adm0_a3", "ADM0_A3", default="")
        add({"name": name, "country": country, "kind": "CITY", "lat": point[0], "lon": point[1], "popRank": rank})

    for feature in sources["elevation_points"]["features"]:
        props = feature.get("properties") or {}
        point = feature_point(feature)
        name = first(props, "name", "NAME")
        elevation_m = first(props, "elevation", "ELEVATION")
        if not point or not name or elevation_m is None:
            continue
        try:
            elevation_ft = float(elevation_m) * 3.28084
        except (TypeError, ValueError):
            continue
        if elevation_ft < 3500:
            continue
        country = first(props, "iso_a2", "ISO_A2", "adm0_a3", "ADM0_A3", "region", default="")
        add({"name": name, "country": country, "kind": "PEAK", "lat": point[0], "lon": point[1],
             "elevationFt": round(elevation_ft), "popRank": 1 if elevation_ft >= 10000 else 2})

    for feature in sources["geography_points"]["features"]:
        props = feature.get("properties") or {}
        point = feature_point(feature)
        name = first(props, "name", "NAME")
        if not point or not name:
            continue
        feature_class = str(first(props, "featurecla", "FEATURECLA", default="")).upper()
        kind = "ISLAND" if "ISLAND" in feature_class else "FEATURE"
        country = first(props, "iso_a2", "ISO_A2", "adm0_a3", "ADM0_A3", default="")
        add({"name": name, "country": country, "kind": kind, "lat": point[0], "lon": point[1], "popRank": 3})

    return landmarks

def round_coordinates(value: Any) -> Any:
    if isinstance(value, list):
        if len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
            # Keep lon/lat only; Natural Earth 1:10m geometry is already generalized.
            return [round(float(value[0]), 4), round(float(value[1]), 4)]
        return [round_coordinates(child) for child in value]
    return value

def compact_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in {
        "LineString", "MultiLineString", "Polygon", "MultiPolygon"
    }:
        return None
    props = feature.get("properties") or {}
    compact_props = {}
    for target, keys in {
        "name": ("name", "NAME", "name_en", "NAME_EN"),
        "class": ("featurecla", "FEATURECLA", "scalerank", "SCALERANK"),
        "country": ("iso_a2", "ISO_A2", "adm0_a3", "ADM0_A3"),
    }.items():
        value = first(props, *keys)
        if value not in (None, ""):
            compact_props[target] = value
    return {
        "type": "Feature",
        "properties": compact_props,
        "geometry": {"type": geometry["type"], "coordinates": round_coordinates(geometry.get("coordinates"))},
    }

def write_deterministic_gzip(path: Path, payload: Any) -> tuple[str, int]:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as raw_file:
        with gzip.GzipFile(fileobj=raw_file, mode="wb", compresslevel=9, mtime=0) as zipped:
            zipped.write(raw)
    os.replace(tmp, path)
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=GEO_DIR)
    args = parser.parse_args()
    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    fetched: dict[str, dict[str, Any]] = {}
    source_meta: dict[str, dict[str, str]] = {}
    for name, url in SOURCES.items():
        print(f"Downloading Natural Earth {name}: {url}")
        fetched[name], source_meta[name] = fetch_geojson(url)

    landmarks = build_landmarks(fetched)
    if len(landmarks) < 5000:
        raise RuntimeError(f"Global landmark pack unexpectedly small: {len(landmarks)}; refusing to publish partial data")

    # The app currently parses the decompressed payload as JSONArray. Keep that
    # exact wire format; do not wrap it in an object or it will fail to load.
    landmark_path = out_dir / "world_geography.json.gz"
    landmark_sha, landmark_size = write_deterministic_gzip(landmark_path, landmarks)

    hydro_layers = {}
    for layer, source_name in (("rivers", "rivers"), ("lakes", "lakes"), ("countryBorders", "country_borders")):
        compact = []
        for feature in fetched[source_name]["features"]:
            item = compact_feature(feature)
            if item is not None:
                compact.append(item)
        if not compact:
            raise RuntimeError(f"Natural Earth hydrography/border layer unexpectedly empty: {layer}")
        hydro_layers[layer] = compact

    hydro_payload = {
        "version": 1,
        "generatedAtUtc": None,
        "source": "Natural Earth 1:10m",
        "layers": hydro_layers,
    }
    hydro_path = out_dir / "world_hydrography.json.gz"
    hydro_sha, hydro_size = write_deterministic_gzip(hydro_path, hydro_payload)

    modified_dates = [item.get("lastModified") for item in source_meta.values() if item.get("lastModified")]
    generated_at = max(modified_dates) if modified_dates else None
    meta = {
        "version": 1,
        "file": landmark_path.name,
        "sha256": landmark_sha,
        "sizeBytes": landmark_size,
        "landmarkCount": len(landmarks),
        "generatedAtUtc": generated_at,
        "license": "Public Domain (Natural Earth data; curated coordinates are factual geographic references)",
        "sources": {name: {"url": SOURCES[name], **source_meta[name]} for name in SOURCES},
        "hydrography": {
            "file": hydro_path.name,
            "sha256": hydro_sha,
            "sizeBytes": hydro_size,
            "riversFeatureCount": len(hydro_layers["rivers"]),
            "lakesFeatureCount": len(hydro_layers["lakes"]),
            "countryBorderFeatureCount": len(hydro_layers["countryBorders"]),
            "note": "Companion pack; current Android landmark loader does not yet parse or render these geometry layers.",
        },
    }
    meta_path = out_dir / "meta.json"
    meta_tmp = meta_path.with_suffix(".json.tmp")
    meta_tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(meta_tmp, meta_path)

    print(f"Landmarks: {len(landmarks):,}; {landmark_size:,} bytes; sha256={landmark_sha}")
    print(f"Hydrography: {sum(len(v) for v in hydro_layers.values()):,} features; {hydro_size:,} bytes; sha256={hydro_sha}")
    print(f"Metadata: {meta_path}")

if __name__ == "__main__":
    main()
