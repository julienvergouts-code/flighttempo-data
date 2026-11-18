import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "adsb_learning" / "build_corridors.py"
spec = importlib.util.spec_from_file_location("build_corridors", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
class CorridorBuilderTests(unittest.TestCase):
    def test_readsb_epoch_relative_seconds_and_ground_flag(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"trace.json"
            p.write_text(json.dumps({"timestamp":1000,"hex":"abcdef","r":"N123","flight":"TEST","trace":[[5,1,2,0,100,90,2]]}))
            _,points=builder.read_points(p)
        self.assertEqual(points[0]["t"],1005)
        self.assertTrue(points[0]["ground"])
    def test_candidate_link_is_low_confidence(self):
        m=[{"fix":"AAA","lat":50,"lon":5,"t":100},{"fix":"BBB","lat":50.2,"lon":5.2,"t":200}]
        link=builder.candidate_links(m)[0]
        self.assertEqual(link["evidenceType"],"INFERRED_OBSERVATION")
        self.assertEqual(link["confidence"],"low")
        self.assertEqual(link["independentSamples"],1)
    def test_non_us_exclusion_policy(self):
        self.assertEqual(builder.EXCLUDED_AIRPORT_PREFIXES,("K","P","T"))
if __name__=="__main__": unittest.main()
