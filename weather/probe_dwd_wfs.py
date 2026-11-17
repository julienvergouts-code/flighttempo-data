#!/usr/bin/env python3
"""Probe DWD aviation-weather WFS metadata without storing weather observations.

This is deliberately a metadata-only access test. It does not download, cache,
publish, or redistribute EDP/ADWICE forecast features.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

WFS_URL = "https://maps.dwd.de/geoserver/ows"
USER_AGENT = "FlightTempo-DWD-WFS-metadata-probe/1.0 (aviation weather integration research)"
CANDIDATES = {
    "adwice_global": ["dwd:ICON_ADWICE_POLYGONE_GLOBAL"],
    "adwice_europe": ["dwd:ICON_ADWICE_POLYGONE"],
    "edp_global": ["dwd:ICON_EDPP_POLYGONS", "dwd:ICON-Turbulenz-Polygone"],
    "edp_europe": ["dwd:ICON-EU-Turbulence-Polygons"],
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def request_bytes(params: dict[str, str], timeout: int = 60) -> bytes:
    url = WFS_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def get_feature_type_names(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    names = []
    for node in root.iter():
        if local_name(node.tag) == "Name" and node.text:
            value = node.text.strip()
            if ":" in value and value not in names:
                names.append(value)
    return sorted(names)


def schema_fields(xml_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    fields = []
    for node in root.iter():
        if local_name(node.tag) == "element" and node.attrib.get("name"):
            fields.append({
                "name": node.attrib["name"],
                "type": node.attrib.get("type", ""),
            })
    # Preserve order while removing duplicate declarations.
    unique = {}
    for item in fields:
        unique[item["name"]] = item
    return list(unique.values())


def get_wms_layers(xml_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    layers = []
    for node in root.iter():
        if local_name(node.tag) != "Layer":
            continue
        name = title = ""
        for child in list(node):
            if local_name(child.tag) == "Name" and child.text:
                name = child.text.strip()
            elif local_name(child.tag) == "Title" and child.text:
                title = child.text.strip()
        if name:
            layers.append({"name": name, "title": title})
    unique = {item["name"]: item for item in layers}
    return sorted(unique.values(), key=lambda item: item["name"])


def get_wcs_coverages(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    names = []
    for node in root.iter():
        if local_name(node.tag) in {"CoverageId", "CoverageName"} and node.text:
            value = node.text.strip()
            if value and value not in names:
                names.append(value)
    return sorted(names)


def probe_layer(layer: str) -> dict:
    result = {"layer": layer, "describe_status": "not_attempted", "sample_status": "not_attempted"}
    try:
        describe = request_bytes({
            "service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType",
            "typeNames": layer,
        })
        result["schema_fields"] = schema_fields(describe)
        result["describe_status"] = "ok"
    except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as exc:
        result["describe_status"] = "error"
        result["describe_error"] = str(exc)[:500]

    try:
        payload = request_bytes({
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": layer, "count": "1", "srsName": "EPSG:4326",
            "outputFormat": "application/json",
        })
        obj = json.loads(payload.decode("utf-8"))
        features = obj.get("features", []) if isinstance(obj, dict) else []
        result["sample_status"] = "ok"
        result["sample_feature_count"] = len(features)
        if features:
            feature = features[0]
            result["geometry_type"] = (feature.get("geometry") or {}).get("type")
            result["property_names"] = sorted((feature.get("properties") or {}).keys())
    except urllib.error.HTTPError as exc:
        result["sample_status"] = "http_error"
        result["sample_http_status"] = exc.code
        result["sample_error"] = exc.read(500).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        result["sample_status"] = "error"
        result["sample_error"] = str(exc)[:500]
    return result


def build_report() -> dict:
    report = {
        "provider": "Deutscher Wetterdienst (DWD)",
        "service_url": WFS_URL,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "metadata_only_access_probe",
        "weather_feature_data_downloaded": False,
        "weather_feature_data_published": False,
        "candidate_groups": {},
    }
    capabilities = request_bytes({
        "service": "WFS", "version": "2.0.0", "request": "GetCapabilities",
    })
    names = get_feature_type_names(capabilities)
    report["service_status"] = "anonymous_getcapabilities_ok"
    report["feature_type_count"] = len(names)
    report["feature_types_matching_aviation_weather"] = [
        name for name in names
        if any(token in name.upper() for token in ("ADWICE", "EDP", "TURBUL", "ICONV", "NCM"))
    ]

    for group, candidates in CANDIDATES.items():
        group_result = {}
        for layer in candidates:
            if layer in names:
                group_result[layer] = probe_layer(layer)
            else:
                group_result[layer] = {"layer": layer, "describe_status": "not_listed", "sample_status": "not_attempted"}
        report["candidate_groups"][group] = group_result

    try:
        wms = request_bytes({
            "service": "WMS", "version": "1.3.0", "request": "GetCapabilities",
        })
        wms_layers = get_wms_layers(wms)
        report["wms_status"] = "anonymous_getcapabilities_ok"
        report["wms_layer_count"] = len(wms_layers)
        report["wms_weather_layers"] = [
            item for item in wms_layers
            if any(token in (item["name"] + " " + item["title"]).upper()
                   for token in ("EDP", "ADWICE", "TURBUL", "ICING", "WAWFOR"))
        ]
    except (urllib.error.URLError, TimeoutError, OSError, ET.ParseError) as exc:
        report["wms_status"] = "error"
        report["wms_error"] = str(exc)[:500]

    try:
        wcs = request_bytes({
            "service": "WCS", "version": "2.0.1", "request": "GetCapabilities",
        })
        coverages = get_wcs_coverages(wcs)
        report["wcs_status"] = "anonymous_getcapabilities_ok"
        report["wcs_coverage_count"] = len(coverages)
        report["wcs_weather_coverages"] = [
            name for name in coverages
            if any(token in name.upper() for token in ("EDP", "ADWICE", "TURBUL", "ICING", "WAWFOR"))
        ]
    except (urllib.error.URLError, TimeoutError, OSError, ET.ParseError) as exc:
        report["wcs_status"] = "error"
        report["wcs_error"] = str(exc)[:500]

    report["access_summary"] = {
        "wfs_capabilities_anonymous": True,
        "wfs_candidate_layer_count": sum(
            1 for group in report["candidate_groups"].values()
            for item in group.values() if item.get("describe_status") == "ok"
        ),
        "wfs_successful_sample_count": sum(
            1 for group in report["candidate_groups"].values()
            for item in group.values() if item.get("sample_status") == "ok"
        ),
        "wms_weather_layer_count": len(report.get("wms_weather_layers", [])),
        "wcs_weather_coverage_count": len(report.get("wcs_weather_coverages", [])),
    }
    report["rights_status"] = "aviation_free_of_charge_claimed_by_DWD_catalogue; public_app_redistribution_not_confirmed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("weather/dwd/wfs-probe-report.json"))
    args = parser.parse_args()
    try:
        report = build_report()
    except (urllib.error.URLError, TimeoutError, OSError, ET.ParseError) as exc:
        print(f"DWD WFS metadata probe failed: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
