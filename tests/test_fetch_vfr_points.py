import csv
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline"
sys.path.insert(0, str(PIPELINE))
import fetch_vfr_points as mod


class Response:
    def __init__(self, text="", content=b"", status=200):
        self.text, self.content, self.status_code = text, content, status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
    def iter_content(self, chunk_size=65536):
        stream = io.BytesIO(self.content)
        while chunk := stream.read(chunk_size):
            yield chunk
    def __enter__(self): return self
    def __exit__(self, *args): return False


def make_csv(rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=["FIX_ID", "LAT_DECIMAL", "LONG_DECIMAL"])
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


def zip_bytes(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return out.getvalue()


def test_fix_link_case_insensitive_and_cycle_date():
    html = '<a href="/extra/26_Nov_2026_fix_csv.zip">FIX</a>'
    assert mod.extract_fix_links(html, "https://example.com/index/") == [
        ("https://example.com/extra/26_Nov_2026_fix_csv.zip", "2026-11-26")
    ]


def test_cycle_pages_and_dates():
    html = '<a href="cycle_26_Nov_2026.html">Cycle</a>'
    assert mod.extract_cycle_pages(html, "https://faa.gov/sub/") == [
        ("https://faa.gov/sub/cycle_26_Nov_2026.html", "2026-11-26")
    ]


def test_nested_zip_stream_parser_extracts_only_vp_points(tmp_path):
    inner = zip_bytes({"FIX_BASE.csv": make_csv([
        {"FIX_ID": "VPABC", "LAT_DECIMAL": "34.123456", "LONG_DECIMAL": "-118.123456"},
        {"FIX_ID": "KLAX", "LAT_DECIMAL": "33.9", "LONG_DECIMAL": "-118.4"},
    ])})
    outer = zip_bytes({"sub/fix.zip": inner})
    archive = tmp_path / "faa.zip"
    archive.write_bytes(outer)
    rows = mod.parse_faa_records(mod.iter_fix_base_lines(archive), "2026-11-26")
    assert rows == [{
        "icao": "", "code": "VPABC", "name": "VPABC", "lat": "34.123456",
        "lon": "-118.123456", "role": "VRP", "source": "FAA", "updated_date": "2026-11-26",
    }]


def test_fallback_to_previous_archive(monkeypatch, tmp_path):
    index = '<a href="26_Nov_2026_FIX_CSV.zip">latest</a><a href="29_Oct_2026_FIX_CSV.zip">prior</a>'
    archive = zip_bytes({"FIX_BASE.csv": make_csv([{"FIX_ID": "VPABC", "LAT_DECIMAL": "40", "LONG_DECIMAL": "-70"}])})
    def fake_get(url, **kwargs):
        if url == mod.INDEX_URL: return Response(text=index)
        if "26_Nov_2026" in url: return Response(status=404)
        if "29_Oct_2026" in url: return Response(content=archive)
        raise AssertionError(url)
    monkeypatch.setattr(mod, "FAA_FIX_URL", "")
    monkeypatch.setattr(mod, "get", fake_get)
    assert mod.fetch_faa()[0]["updated_date"] == "2026-10-29"


@pytest.mark.parametrize("lat,lon", [(0, 0), (91, 0), (0, 181), (-91, 20)])
def test_bad_coordinates_rejected(lat, lon):
    row = {"icao": "", "code": "VP001", "name": "test", "lat": lat, "lon": lon,
           "role": "VRP", "source": "FAA", "updated_date": "2026-11-26"}
    with pytest.raises(ValueError): mod.validate_record(row)


def test_rejection_rate_guard():
    bad = [{"icao": "", "code": "VP1", "name": "x", "lat": 0, "lon": 0, "role": "VRP",
            "source": "FAA", "updated_date": "2026-11-26"}] * 4
    with pytest.raises(RuntimeError, match="Rejection rate"):
        mod.validate_records(bad, guard=True)


def test_retention_when_source_failure_and_partial(monkeypatch, tmp_path):
    csvpath, metapath = tmp_path / "data.csv", tmp_path / "meta.json"
    old = [{"icao": "", "code": "VPOLD", "name": "VPOLD", "lat": 40, "lon": -70,
            "role": "VRP", "source": "FAA", "updated_date": "2026-10-01"}]
    mod.write_csv(csvpath, old, "2026-10-01T00:00:00Z")
    monkeypatch.setattr(mod, "CSV_PATH", csvpath)
    monkeypatch.setattr(mod, "META_PATH", metapath)
    monkeypatch.setattr(mod, "fetch_faa", lambda: (_ for _ in ()).throw(RuntimeError("bad archive")))
    assert mod.main(["--allow-partial"]) == 0
    assert [r["code"] for r in mod.read_existing(csvpath)] == ["VPOLD"]
    assert json.loads(metapath.read_text())["source_status"]["FAA"] == "failed"


def test_drop_guard_refuses_large_decrease(monkeypatch, tmp_path):
    path, meta = tmp_path / "points.csv", tmp_path / "meta.json"
    previous = [{"icao": "", "code": f"VP{i:03}", "name": "x", "lat": 40+i/100, "lon": -70,
                 "role": "VRP", "source": "FAA", "updated_date": "2026-10-01"} for i in range(10)]
    mod.write_csv(path, previous, "old")
    monkeypatch.setattr(mod, "CSV_PATH", path)
    monkeypatch.setattr(mod, "META_PATH", meta)
    monkeypatch.setattr(mod, "fetch_faa", lambda: previous[:6])
    assert mod.main([]) == 1
    assert len(mod.read_existing(path)) == 10


def test_dry_run_does_not_touch_production_files(monkeypatch, tmp_path, capsys):
    path, meta = tmp_path / "points.csv", tmp_path / "meta.json"
    records = [{"icao": "", "code": "VP001", "name": "VP001", "lat": 40, "lon": -70,
                "role": "VRP", "source": "FAA", "updated_date": "2026-11-26"}]
    monkeypatch.setattr(mod, "CSV_PATH", path)
    monkeypatch.setattr(mod, "META_PATH", meta)
    monkeypatch.setattr(mod, "fetch_faa", lambda: records)
    assert mod.main(["--dry-run"]) == 0
    assert not path.exists() and not meta.exists()
    assert "VP001" in capsys.readouterr().out


def test_publish_pair_rolls_back_if_second_replace_fails(monkeypatch, tmp_path):
    csvpath, metapath = tmp_path / "points.csv", tmp_path / "meta.json"
    csvpath.write_text("old-csv")
    metapath.write_text("old-meta")
    records = [{"icao": "", "code": "VP001", "name": "VP001", "lat": 40, "lon": -70,
                "role": "VRP", "source": "FAA", "updated_date": "2026-11-26"}]
    real_replace = mod.os.replace
    count = 0
    def fail_second(src, dst):
        nonlocal count
        count += 1
        if count == 2: raise OSError("simulated replace failure")
        return real_replace(src, dst)
    monkeypatch.setattr(mod.os, "replace", fail_second)
    with pytest.raises(OSError): mod.publish_pair(csvpath, metapath, records, "now", "ok")
    assert csvpath.read_text() == "old-csv"
    assert metapath.read_text() == "old-meta"
