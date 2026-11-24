import gzip
import io
import json
import sys
import tarfile
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import adsb_archive as arch  # noqa: E402
import adsb_observed_routes as m  # noqa: E402

BRU, LHR = (50.9014, 4.4844), (51.4706, -0.4619)
AIRPORTS = [("EBBR", *BRU), ("EGLL", *LHR), ("LFPG", 49.0097, 2.5479)]


def trace(origin, dest, n=60, lateral=0.0, callsign="BAW123", cruise=35000):
    """Synthetic readsb trace: ground dwell at the origin, a straight flight, ground dwell at the destination."""
    rows, t = [], 0
    for _ in range(4):
        rows.append([t, origin[0], origin[1], "ground", 0, 0, 2, None, {"flight": callsign}])
        t += 10
    for k in range(n):
        f = (k + 1) / (n + 1)
        rows.append([t, origin[0] + (dest[0] - origin[0]) * f + lateral, origin[1] + (dest[1] - origin[1]) * f,
                     cruise, 450, 0, 0, None, {"flight": callsign}])
        t += 30
    for _ in range(4):
        rows.append([t, dest[0], dest[1], "ground", 0, 0, 2, None, {"flight": callsign}])
        t += 10
    return {"timestamp": 1_700_000_000, "icao": "abcdef", "trace": rows}


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.index = m.AirportIndex(AIRPORTS)

    def test_flight_to_route(self):
        flights = m.complete_flights(m.read_points(trace(BRU, LHR)))
        self.assertEqual(len(flights), 1)
        route, reason = m.flight_to_route(flights[0], self.index)
        self.assertIsNone(reason)
        self.assertEqual(route[:2], ("EBBR", "EGLL"))
        self.assertTrue(8 <= len(route[2]) <= 14)  # about 190 NM at 20 NM spacing

    def test_rejections(self):
        low = m.complete_flights(m.read_points(trace(BRU, LHR, cruise=9000)))
        self.assertEqual(m.flight_to_route(low[0], self.index)[1], "no_cruise")
        short = m.complete_flights(m.read_points(trace(BRU, (50.7, 4.9))))
        self.assertIn(m.flight_to_route(short[0], self.index)[1], ("short_leg", "airports_unresolved"))
        lost = m.complete_flights(m.read_points(trace((10.0, 10.0), (11.0, 11.0))))
        self.assertEqual(m.flight_to_route(lost[0], self.index)[1], "airports_unresolved")

    def test_open_ended_trace_is_not_a_flight(self):
        doc = trace(BRU, LHR)
        doc["trace"] = doc["trace"][:-4]  # never lands in the data
        self.assertEqual(m.complete_flights(m.read_points(doc)), [])

    def test_grouping_and_confidence(self):
        pairs, rejected = {}, Counter()
        for lat in (0.0, 0.05, 0.02):          # three nearly identical flights
            self.assertEqual(m.process_document(trace(BRU, LHR, lateral=lat), self.index, pairs, "2026-11-20", rejected), 1)
        m.process_document(trace(BRU, LHR, lateral=1.5), self.index, pairs, "2026-11-21", rejected)  # about 90 NM off
        groups = pairs["EBBR-EGLL"]
        self.assertEqual(sorted(g["samples"] for g in groups), [1, 3])
        self.assertEqual(m.confidence(3), "MEDIUM")
        self.assertEqual(m.confidence(5), "HIGH")
        self.assertEqual(m.confidence(2), "LOW")
        self.assertEqual(max(g["lastObserved"] for g in groups), "2026-11-21")

    def test_cluster_cap(self):
        pairs = {}
        for i in range(10):
            m.add_route(pairs, "EBBR", "EGLL", [(50.0 + i, 4.0), (51.0 + i, 3.0), (52.0 + i, 2.0)], "2026-11-20")
        self.assertEqual(len(pairs["EBBR-EGLL"]), m.MAX_CLUSTERS_PER_PAIR)

    def test_antimeridian(self):
        a, b = (-17.5, -149.6), (35.7, 140.4)
        mid = m.lerp((10.0, 170.0), (10.0, -170.0), 0.5)
        self.assertAlmostEqual(abs(mid[1]), 180.0, 3)
        path = m.resample([a, (0.0, -170.0), (10.0, 179.0), b], 100.0)
        self.assertTrue(all(-180 <= p[1] <= 180 for p in path))

    def test_resample_spacing(self):
        path = m.resample([(0.0, 0.0), (0.0, 10.0)], 20.0)  # 600 NM
        self.assertEqual(len(path), 32)  # 30 steps of 20 NM, then the 0.4 NM remainder
        self.assertAlmostEqual(m.dist_nm(path[1], path[2]), 20.0, 0)


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.state = {"processedDates": ["2026-11-20"], "pairs": {}}
        m.add_route(self.state["pairs"], "EBBR", "EGLL", [(50.9, 4.5), (51.2, 2.0), (51.47, -0.46)], "2026-11-20")

    def test_pack_is_deterministic_and_private(self):
        a, b = m.pack_bytes(self.state), m.pack_bytes(self.state)
        self.assertEqual(a, b)
        body = json.loads(gzip.decompress(a))
        def keys(v):
            if isinstance(v, dict):
                for k, c in v.items():
                    yield str(k).lower()
                    yield from keys(c)
            elif isinstance(v, list):
                for c in v:
                    yield from keys(c)
        found = set(keys({k: v for k, v in body.items() if k != "pairs"})) | set(keys(list(body["pairs"].values())))
        for banned in ("icao24", "hex", "callsign", "flight", "registration", "timestamp", "t"):
            self.assertNotIn(banned, found)
        self.assertEqual(set(body["pairs"]["EBBR-EGLL"][0]), {"samples", "polyline", "lengthNm", "lastObserved"})

    def test_index_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            idx = m.write_outputs(self.state, Path(d))
            self.assertFalse(idx["legacyGraphUsed"])
            self.assertEqual(idx["routeCount"], 1)
            self.assertEqual(m.load_existing(Path(d))["pairs"].keys(), self.state["pairs"].keys())
            self.assertEqual(json.loads((Path(d) / "index.json").read_text())["sha256"], idx["sha256"])


class ArchiveTests(unittest.TestCase):
    def tar_with(self, doc, name="trace_full_abcdef.json.gz"):
        raw = gzip.compress(json.dumps(doc).encode())
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            info = tarfile.TarInfo("traces/ef/" + name)
            info.size = len(raw)
            t.addfile(info, io.BytesIO(raw))
        buf.seek(0)
        return tarfile.open(fileobj=buf, mode="r:")

    def test_airline_trace_loads(self):
        tar = self.tar_with(trace(BRU, LHR, callsign="BAW123"))
        doc, reason = arch.load_trace_member(tar, tar.next())
        self.assertIsNone(reason)
        self.assertIn("trace", doc)

    def test_non_airline_callsign_is_skipped(self):
        tar = self.tar_with(trace(BRU, LHR, callsign="OOABC"))
        doc, reason = arch.load_trace_member(tar, tar.next())
        self.assertEqual(reason, "not_airline_callsign")
        self.assertIsNone(doc)

    def test_callsign_pattern(self):
        self.assertTrue(arch.looks_like_airline_flight('"flight":"RYR4TN  "'))
        self.assertFalse(arch.looks_like_airline_flight('"flight":"N123AB"'))
        self.assertIsNone(arch.looks_like_airline_flight("{}"))


class IndependenceTests(unittest.TestCase):
    def test_no_legacy_graph_in_learning_code(self):
        for name in ("pipeline/adsb_observed_routes.py", "pipeline/adsb_archive.py"):
            text = (ROOT / name).read_text(encoding="utf-8").lower()
            for banned in ("flightgear", "ftwg", "world_corridor_graph", "x-plane", "awy640", "navigation/graph",
                           "navigation/airways", "navigation/waypoints", "flightgear_"):
                self.assertNotIn(banned, text, f"{name} mentions {banned}")


if __name__ == "__main__":
    unittest.main()
