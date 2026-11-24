#!/usr/bin/env python3
"""ADSB.lol archive access: a seekable range reader over the split daily TAR release and trace-member loading.

Extracted from the earlier benchmark so the observed-route importer does not depend on the legacy navigation
graph. Raw traces are processed in memory only and never written out.
"""
from __future__ import annotations

import bisect
import gzip
import io
import json
import re
import time
import zlib
from collections import OrderedDict
from datetime import datetime

try:  # the range reader needs requests; the pure helpers below work without it (generic regression runs have no extras)
    import requests
except ImportError:  # pragma: no cover
    requests = None

API = "https://api.github.com/repos/adsblol/globe_history_{year}/releases/tags/{tag}"
MAX_TRACE_MEMBER_BYTES = 50 * 1024 * 1024
PREFIX_COMPRESSED_BYTES = 16 * 1024
PREFIX_DECODED_BYTES = 256 * 1024
AIRLINE_CALLSIGN = re.compile(r"^[A-Z]{3}[0-9]")


class HTTPRangeConcatReader(io.RawIOBase):
    """Seekable virtual file over split TAR assets using validated HTTP byte ranges."""
    CACHE_BLOCK_BYTES = 8 * 1024
    CACHE_BLOCKS = 8
    MAX_RETRIES = 3
    RETRY_BACKOFF_SECONDS = 1.0

    def __init__(self, assets: list[dict], session: requests.Session):
        if not assets or any(int(a.get("size", 0)) <= 0 for a in assets):
            raise ValueError("Range archive assets require positive sizes")
        self.assets = assets
        self.session = session
        self.starts = []
        self.total_size = 0
        for asset in assets:
            self.starts.append(self.total_size)
            self.total_size += int(asset["size"])
        self.position = 0
        self.cache = OrderedDict()
        self.range_requests = 0
        self.range_bytes_downloaded = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            new_position = offset
        elif whence == io.SEEK_CUR:
            new_position = self.position + offset
        elif whence == io.SEEK_END:
            new_position = self.total_size + offset
        else:
            raise ValueError(f"invalid whence {whence}")
        if new_position < 0:
            raise ValueError("negative seek position")
        self.position = new_position
        return self.position

    def _asset_for(self, virtual_position):
        index = bisect.bisect_right(self.starts, virtual_position) - 1
        if index < 0 or index >= len(self.assets):
            raise EOFError("archive range position outside assets")
        return index, virtual_position - self.starts[index]

    def _fetch_block(self, asset_index, local_start):
        asset = self.assets[asset_index]
        size = int(asset["size"])
        block_start = (local_start // self.CACHE_BLOCK_BYTES) * self.CACHE_BLOCK_BYTES
        block_end = min(block_start + self.CACHE_BLOCK_BYTES, size) - 1
        key = (asset_index, block_start)
        for attempt in range(self.MAX_RETRIES + 1):
            response = None
            try:
                headers = {
                    "Accept-Encoding": "identity",
                    "Range": f"bytes={block_start}-{block_end}",
                }
                response = self.session.get(
                    asset["url"], headers=headers, timeout=(30, 120), stream=False
                )
                if response.status_code != 206:
                    raise RuntimeError(
                        f"archive range returned HTTP {response.status_code}, expected 206"
                    )
                content_range = response.headers.get("Content-Range", "")
                match = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)$", content_range, re.I)
                if not match or int(match.group(1)) != block_start or int(match.group(2)) != block_end:
                    raise RuntimeError(f"invalid archive Content-Range: {content_range!r}")
                data = response.content
                if len(data) != block_end - block_start + 1:
                    raise RuntimeError(
                        f"short archive range: received {len(data)} bytes, "
                        f"expected {block_end - block_start + 1}"
                    )
                self.range_requests += 1
                self.range_bytes_downloaded += len(data)
                self.cache[key] = data
                self.cache.move_to_end(key)
                while len(self.cache) > self.CACHE_BLOCKS:
                    self.cache.popitem(last=False)
                return data
            except Exception as exc:
                if attempt >= self.MAX_RETRIES:
                    raise RuntimeError(
                        f"archive range failed at asset {asset_index + 1}, "
                        f"bytes {block_start}-{block_end} after {attempt + 1} attempts"
                    ) from exc
                delay = self.RETRY_BACKOFF_SECONDS * (2 ** attempt)
                print(
                    f"[archive] range request retry {attempt + 1}/{self.MAX_RETRIES} "
                    f"in {delay:.0f}s: {exc}", flush=True
                )
                time.sleep(delay)
            finally:
                if response is not None:
                    response.close()
        raise RuntimeError("unreachable range retry state")

    def read(self, size=-1):
        if size is None or size < 0:
            size = self.total_size - self.position
        size = min(size, max(0, self.total_size - self.position))
        output = bytearray()
        remaining = size
        while remaining:
            asset_index, local = self._asset_for(self.position)
            asset_size = int(self.assets[asset_index]["size"])
            key = (asset_index, (local // self.CACHE_BLOCK_BYTES) * self.CACHE_BLOCK_BYTES)
            data = self.cache.get(key)
            if data is None:
                data = self._fetch_block(asset_index, local)
            else:
                self.cache.move_to_end(key)
            block_start = key[1]
            in_block = local - block_start
            take = min(remaining, len(data) - in_block, asset_size - local)
            if take <= 0:
                raise IOError("archive range cache returned no bytes at requested offset")
            output.extend(data[in_block:in_block + take])
            self.position += take
            remaining -= take
        return bytes(output)

    def readinto(self, target):
        data = self.read(len(target))
        count = len(data)
        target[:count] = data
        return count


def release_asset_specs(date: str, session: requests.Session) -> tuple[dict, list[dict]]:
    day = datetime.strptime(date, "%Y-%m-%d")
    for channel in ("prod", "staging"):
        tag = f"v{day:%Y.%m.%d}-planes-readsb-{channel}-0"
        url = API.format(year=day.year, tag=tag)
        response = session.get(url, timeout=30)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        release = response.json()
        assets = [a for a in release.get("assets", []) if re.search(r"\.tar\.[a-z]{2}$", a.get("name", ""))]
        assets.sort(key=lambda a: a["name"])
        if assets:
            return release, [
                {"url": a["browser_download_url"], "name": a["name"], "size": int(a["size"])}
                for a in assets
            ]
    raise RuntimeError(f"No ADSB.lol production or staging archive release found for {date}")


def callsign_values(text: str) -> list[str]:
    values = re.findall(r'"(?:flight|callsign)"\s*:\s*("(?:\\.|[^"\\])*")', text, re.I)
    out = []
    for raw in values:
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, list):
            value = "".join(str(x) for x in value)
        out.append(re.sub(r"[^A-Z0-9]", "", str(value or "").upper()))
    return out


def looks_like_airline_flight(text: str) -> bool | None:
    """True when a callsign has an airline pattern (three letters then a digit); None when no callsign is visible."""
    values = callsign_values(text)
    if not values:
        return None
    return any(AIRLINE_CALLSIGN.match(v) for v in values)


def load_trace_member(tar, member) -> tuple[dict | None, str | None]:
    """Return (decoded trace document, None) or (None, reason). Screens out non-airline traces from a small prefix first."""
    source = tar.extractfile(member)
    if source is None:
        return None, "unreadable_member"
    try:
        head = source.read(min(member.size, PREFIX_COMPRESSED_BYTES))
        is_gzip = head[:2] == b"\x1f\x8b"
        try:
            decoded = (zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(head, PREFIX_DECODED_BYTES)
                       if is_gzip else head[:PREFIX_DECODED_BYTES])
        except zlib.error:
            decoded = b""
        if looks_like_airline_flight(decoded.decode("utf-8", errors="replace")) is False:
            return None, "not_airline_callsign"
        reader = getattr(tar, "fileobj", None)
        original = getattr(reader, "CACHE_BLOCK_BYTES", None)
        if original is not None:
            reader.CACHE_BLOCK_BYTES = 128 * 1024
            reader.cache.clear()
        try:
            source.seek(0)
            raw = source.read(MAX_TRACE_MEMBER_BYTES + 1)
        finally:
            if original is not None:
                reader.CACHE_BLOCK_BYTES = original
                reader.cache.clear()
        if len(raw) > MAX_TRACE_MEMBER_BYTES:
            return None, "oversize_trace"
        if is_gzip:
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as gz:
                    raw = gz.read(MAX_TRACE_MEMBER_BYTES + 1)
            except (OSError, EOFError, zlib.error):
                return None, "invalid_gzip"
            if len(raw) > MAX_TRACE_MEMBER_BYTES:
                return None, "oversize_decoded_trace"
        try:
            doc = json.loads(raw)
        except ValueError:
            return None, "invalid_json"
        return (doc, None) if isinstance(doc, dict) else (None, "invalid_json")
    finally:
        source.close()
