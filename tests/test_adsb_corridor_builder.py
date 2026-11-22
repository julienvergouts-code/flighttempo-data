import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline" / "build_corridors.py"
pipeline_spec = importlib.util.spec_from_file_location("benchmark_pipeline", PIPELINE)
benchmark_pipeline = importlib.util.module_from_spec(pipeline_spec)
pipeline_spec.loader.exec_module(benchmark_pipeline)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "adsb_learning" / "build_corridors.py"
spec = importlib.util.spec_from_file_location("build_corridors", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CorridorBuilderTests(unittest.TestCase):
    def test_benchmark_recorder_evidence_is_strict_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "benchmark_evidence.json"
            recorder = benchmark_pipeline.BenchmarkRecorder(path, {"test": True})
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            self.assertEqual(parsed["status"], "running")
            self.assertTrue(raw.endswith("\\n"))
            self.assertFalse(raw.endswith("\\\\n"))

    def test_readsb_epoch_relative_seconds_and_ground_flag(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "trace.json"
            p.write_text(json.dumps({
                "timestamp": 1000,
                "hex": "abcdef",
                "r": "N123",
                "flight": "TEST",
                "trace": [[5, 1, 2, 0, 100, 90, 2]],
            }))
            _, points = builder.read_points(p)
        self.assertEqual(points[0]["t"], 1005)
        self.assertTrue(points[0]["ground"])

    def test_process_trace_retains_matched_fix_coordinates_without_timestamps(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"trace.json"
            trace=[]
            for i in range(30):
                if i<10:
                    lat,lon=52.31+(i*0.0002),4.77
                elif i<20:
                    lat,lon=51.88+(i-10)*0.0002,5.10
                else:
                    lat,lon=51.46+(i-20)*0.0002,5.38
                trace.append([i,lat,lon,10000,200,90,0])
            p.write_text(json.dumps({"timestamp":1700000000,"trace":trace}))
            airports=[("EHAM",52.3086,4.7639),("EHEH",51.4500,5.3740)]
            fixes=[("FIXA",52.31,4.77),("FIXB",51.88,5.10),("FIXC",51.46,5.38)]
            result=builder.process_trace(p,airports,fixes,{"EHAM":0,"EHEH":1})
        self.assertEqual(result[0]["origin"],"EHAM")
        self.assertEqual(result[0]["destination"],"EHEH")
        details=result[0]["matchedFixDetails"]
        self.assertGreaterEqual(len(details),2)
        self.assertTrue(all({"fix","lat","lon","distanceNm"}<=set(x) for x in details))
        self.assertTrue(all("t" not in x for x in details))

    def test_candidate_link_is_low_confidence(self):
        matches = [
            {"fix": "AAA", "lat": 50, "lon": 5, "t": 100},
            {"fix": "BBB", "lat": 50.2, "lon": 5.2, "t": 200},
        ]
        link = builder.candidate_links(matches)[0]
        self.assertEqual(link["evidenceType"], "INFERRED_OBSERVATION")
        self.assertEqual(link["confidence"], "low")
        self.assertEqual(link["independentSamples"], 1)

    def test_airport_anchor_uses_multiple_boundary_points_with_25nm_radius(self):
        airports = [("EHAM", 52.3086, 4.7639), ("LFPG", 49.0097, 2.5479)]
        points = []
        for i in range(6):
            points.append({"t": i, "lat": 52.31 + i * 0.002, "lon": 4.77, "ground": False})
        for i in range(6):
            points.append({"t": 100 + i, "lat": 49.01 + i * 0.002, "lon": 2.55, "ground": False})
        self.assertEqual(builder.anchor_airports(points, airports), ("EHAM", "LFPG"))

    def test_airport_anchor_rejects_airports_beyond_25nm(self):
        airports = [("EHAM", 52.3086, 4.7639), ("LFPG", 49.0097, 2.5479)]
        points = [{"t": i, "lat": 55.0, "lon": 8.0, "ground": False} for i in range(12)]
        self.assertEqual(builder.anchor_airports(points, airports), (None, None))

    def test_non_us_exclusion_policy(self):
        self.assertEqual(builder.EXCLUDED_AIRPORT_PREFIXES, ("K", "P", "T"))


if __name__ == "__main__":
    unittest.main()
