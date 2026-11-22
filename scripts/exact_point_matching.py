"""Exact cross-source point matching for safe VFR-to-IFR reference reuse.

Names are compared case-insensitively after trimming/collapsing whitespace.
Coordinates are compared as exact decimal values; no spatial tolerance, alias,
nearest-neighbour or ident-only match is accepted.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable


def normalized_name(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _coordinate(value: object, *, minimum: Decimal, maximum: Decimal) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or not minimum <= number <= maximum:
        return None
    return number


def point_key(
    record: dict,
    *,
    name_field: str = "name",
    latitude_field: str = "latitude",
    longitude_field: str = "longitude",
) -> tuple[str, Decimal, Decimal] | None:
    name = normalized_name(record.get(name_field))
    latitude = _coordinate(
        record.get(latitude_field), minimum=Decimal("-90"), maximum=Decimal("90")
    )
    longitude = _coordinate(
        record.get(longitude_field), minimum=Decimal("-180"), maximum=Decimal("180")
    )
    if not name or latitude is None or longitude is None:
        return None
    return name, latitude, longitude


def exact_point_matches(
    ifr_points: Iterable[dict],
    vfr_points: Iterable[dict],
    *,
    ifr_name_field: str = "name",
    ifr_latitude_field: str = "latitude",
    ifr_longitude_field: str = "longitude",
    vfr_name_field: str = "name",
    vfr_latitude_field: str = "latitude",
    vfr_longitude_field: str = "longitude",
) -> list[tuple[dict, dict]]:
    """Return IFR/VFR pairs with the same name and exactly equal coordinates."""
    vfr_index: dict[tuple[str, Decimal, Decimal], list[dict]] = {}
    for point in vfr_points:
        key = point_key(
            point,
            name_field=vfr_name_field,
            latitude_field=vfr_latitude_field,
            longitude_field=vfr_longitude_field,
        )
        if key is not None:
            vfr_index.setdefault(key, []).append(point)

    matches = []
    for ifr_point in ifr_points:
        key = point_key(
            ifr_point,
            name_field=ifr_name_field,
            latitude_field=ifr_latitude_field,
            longitude_field=ifr_longitude_field,
        )
        if key is None:
            continue
        matches.extend((ifr_point, vfr_point) for vfr_point in vfr_index.get(key, []))
    return matches
