import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline" / "build_corridors.py"
pipeline_spec = importlib.util.spec_from_file_location("benchmark_pipeline", PIPELINE)
benchmark_pipeline = importlib.util.module_from_spec(pipeline_spec)
pipeline_spec.loader.exec_module(benchmark_pipeline)

BATCH = Path(__file__).resolve().parents[1] / "pipeline" / "batch_archive_benchmark.py"
batch_spec = importlib.util.spec_from_file_location("batch_archive_benchmark", BATCH)
batch_benchmark = importlib.util.module_from_spec(batch_spec)
batch_spec.loader.exec_module(batch_benchmark)

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
            self.assertTrue(raw.endswith("\n"))

    def test_batch_runner_callsign_and_europe_filter(self):
        self.assertEqual(batch_benchmark.flight_prefix({"flight": "RYR6TH"}), "RYR")
        readsb_trace={"trace":[[0,52.0,4.0,30000,420,90,0,0,{"type":"adsb_icao","flight":"DLH7YA  "}]]}
        self.assertEqual(batch_benchmark.flight_prefix(readsb_trace), "DLH")
        self.assertIn("RYR", batch_benchmark.EUROPE_AIRLINE_PREFIXES)
        self.assertTrue(batch_benchmark.eu_coord((51.5, 5.4)))
        self.assertFalse(batch_benchmark.eu_coord((40.0, -100.0)))

    def test_batch_confidence_thresholds_are_observation_only(self):
        self.assertEqual(batch_benchmark.confidence_for_sample_count(1), "LOW")
        self.assertEqual(batch_benchmark.confidence_for_sample_count(2), "LOW")
        self.assertEqual(batch_benchmark.confidence_for_sample_count(3), "MEDIUM")
        self.assertEqual(batch_benchmark.confidence_for_sample_count(4), "MEDIUM")
        self.assertEqual(batch_benchmark.confidence_for_sample_count(5), "HIGH")
        self.assertEqual(batch_benchmark.CONFIDENCE_THRESHOLDS["HIGH"], [5])

    def test_batch_artifacts_are_strict_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "scale_summary.json"
            batch_benchmark.strict_write(path, {"promotion_enabled": False, "n": 2})
            parsed = json.loads(path.read_text(encoding="utf-8"),
                                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            self.assertFalse(parsed["promotion_enabled"])

    def test_batch_privacy_guard_rejects_identity_and_trace_fields(self):
        batch_benchmark.assert_privacy_safe({"trace_members_scanned": 4, "aircraft_processed": 25})
        with self.assertRaisesRegex(ValueError, "Privacy audit failed"):
            batch_benchmark.assert_privacy_safe({"leg_metrics": [{"callsign": "RYR6TH"}]})
        with self.assertRaisesRegex(ValueError, "Privacy audit failed"):
            batch_benchmark.assert_privacy_safe({"leg_metrics": [{"_observed_trace_endpoints": {}}]})

    def test_diag_leg_measures_actual_observed_endpoints_and_severe_gaps(self):
        graph_coords={"FIXA":(52.0,4.0),"FIXB":(54.0,8.0)}

        class FakeNav:
            last_route_endpoint_resolution={
                "start":{"coord":graph_coords["FIXA"]},
                "goal":{"coord":graph_coords["FIXB"]},
            }

            def resolve_physical_endpoint(self, fix, coord, role):
                return {"offset_nm":0.0,"coord":graph_coords[fix],"node_index":fix}

            def a_star_connected(self, start_fix, goal_fix, start_coord, goal_coord):
                return ({"nodes":[start_fix,goal_fix]},200.0)

        leg={
            "matchedFixes":["FIXA","FIXB"],
            "matchedFixDetails":[
                {"fix":"FIXA","lat":52.0,"lon":4.0},
                {"fix":"FIXB","lat":54.0,"lon":8.0},
            ],
            "_observed_trace_endpoints":{"start":[50.0,4.0],"end":[56.0,8.0]},
        }
        result=batch_benchmark.diag_leg(leg,FakeNav())
        self.assertTrue(result["connected"])
        self.assertGreater(result["start_gap_nm"],100)
        self.assertGreater(result["end_gap_nm"],100)
        expected_start=benchmark_pipeline._nm((50.0,4.0),graph_coords["FIXA"])
        expected_end=benchmark_pipeline._nm((56.0,8.0),graph_coords["FIXB"])
        self.assertAlmostEqual(result["start_gap_nm"],round(expected_start,2),places=2)
        self.assertAlmostEqual(result["end_gap_nm"],round(expected_end,2),places=2)
        expected_coverage=round(200.0/(200.0+round(expected_start,2)+round(expected_end,2)),4)
        self.assertEqual(result["covered_fraction"],expected_coverage)

    def test_diag_leg_requires_observed_endpoints_instead_of_falling_back_to_fixes(self):
        result=batch_benchmark.diag_leg({"matchedFixes":["FIXA"]},object())
        self.assertEqual(result["status"],"MISSING_OBSERVED_TRACE_ENDPOINTS")
        self.assertIsNone(result["start_gap_nm"])

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
            result=builder.process_trace(p,airports,fixes,{"EHAM":0,"EHEH":1},
                                         include_observed_endpoints=True)
        self.assertEqual(result[0]["origin"],"EHAM")
        self.assertEqual(result[0]["destination"],"EHEH")
        details=result[0]["matchedFixDetails"]
        self.assertGreaterEqual(len(details),2)
        self.assertTrue(all({"fix","lat","lon","distanceNm"}<=set(x) for x in details))
        self.assertTrue(all("t" not in x for x in details))
        self.assertEqual(result[0]["_observed_trace_endpoints"]["start"],trace[0][1:3])
        self.assertEqual(result[0]["_observed_trace_endpoints"]["end"],trace[-1][1:3])

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


    def test_batch_accepts_small_trace_members_and_rejects_oversize_members(self):
        self.assertTrue(batch_benchmark.trace_member_size_is_readable(1))
        self.assertTrue(batch_benchmark.trace_member_size_is_readable(99_999))
        self.assertFalse(batch_benchmark.trace_member_size_is_readable(0))
        self.assertFalse(batch_benchmark.trace_member_size_is_readable(
            batch_benchmark.MAX_TRACE_MEMBER_BYTES + 1
        ))


if __name__ == "__main__":
    unittest.main()


