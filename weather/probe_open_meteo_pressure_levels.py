#!/usr/bin/env python3
"""Probe Open-Meteo global pressure-level wind/temperature forecast variables.

Only response metadata (variable names, units and time coverage) is stored.
No forecast values are published in the repository.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://api.open-meteo.com/v1/forecast"
LATITUDE = 50.9014
LONGITUDE = 4.4844  # EBBR
LEVELS = (300, 250, 200, 150)
VARIABLES = [
    f"{field}_{level}hPa"
    for level in LEVELS
    for field in ("wind_speed", "wind_direction", "temperature", "geopotential_height")
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("weather/open-meteo/pressure-level-probe.json"))
    args = parser.parse_args()

    params = {
        "latitude": str(LATITUDE),
        "longitude": str(LONGITUDE),
        "hourly": ",".join(VARIABLES),
        "forecast_days": "1",
        "wind_speed_unit": "kn",
        "temperature_unit": "celsius",
        "timezone": "UTC",
    }
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "FlightTempo-OpenMeteo-metadata-probe/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    hourly = payload.get("hourly", {})
    units = payload.get("hourly_units", {})
    times = hourly.get("time", [])
    missing = [name for name in VARIABLES if name not in hourly or name not in units]
    short = [name for name in VARIABLES if len(hourly.get(name, [])) != len(times)]
    if missing or short or not times:
        raise RuntimeError(f"Open-Meteo pressure-level schema incomplete; missing={missing}, mismatched={short}")

    report = {
        "provider": "Open-Meteo",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "metadata_only_pressure_level_forecast_probe",
        "forecast_values_published": False,
        "test_location": {"airport": "EBBR", "latitude": LATITUDE, "longitude": LONGITUDE},
        "http_status": 200,
        "time_count": len(times),
        "first_forecast_time_utc": times[0],
        "last_forecast_time_utc": times[-1],
        "variables": {name: {"unit": units[name], "sample_count": len(hourly[name])} for name in VARIABLES},
        "pressure_levels_hpa": list(LEVELS),
        "notes": [
            "Global pressure-level forecast fields are available for wind speed, wind direction, temperature and geopotential height.",
            "These are NWP forecast fields, not an aviation turbulence or icing product.",
            "Any wind-shear calculation must be labelled as a non-operational model-derived indicator, not EDR/CAT forecast.",
            "The hosted free API is for non-commercial use and requires CC BY 4.0 attribution; commercial use requires a separate licence."
        ],
        "source_url": "https://open-meteo.com/en/docs",
        "data_license": "CC-BY-4.0",
        "api_access": "free_non_commercial_only",
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
