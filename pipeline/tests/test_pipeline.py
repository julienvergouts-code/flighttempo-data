import json, tempfile, unittest
from pathlib import Path
from pipeline.adsb_fetch import read_trace, rdp, haversine_nm
from pipeline.corridor_cluster import resample, distance_lines
class PipelineTests(unittest.TestCase):
 def test_readsb_trace_normalization(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"trace.json";p.write_text(json.dumps({"icao":"abc123","flight":"TST123","timestamp":1000,"trace":[[0,50,4,12000,400,90],[10,51,5,15000,410,91],[20,None,None,None,None,None]]}))
   x=read_trace(p);self.assertEqual(x["icao"],"abc123");self.assertEqual(len(x["points"]),2);self.assertEqual(x["points"][1]["timestamp"],1010)
 def test_rdp_preserves_endpoints(self):
  pts=[{"lat":50,"lon":4},{"lat":50.01,"lon":4.01},{"lat":51,"lon":5}]
  out=rdp(pts,1);self.assertEqual(out[0],pts[0]);self.assertEqual(out[-1],pts[-1])
 def test_distance_and_resampling(self):
  self.assertGreater(haversine_nm((50,4),(51,5)),50)
  line=[[50,4],[51,5]];self.assertGreater(len(resample(line,10)),2)
  self.assertLess(distance_lines(line,line),0.01)
if __name__=="__main__":unittest.main()
