import io,sys,zipfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"pipeline"))
import import_ofma_cup_points as m
SRC={"region":"EB","regionName":"Belgium","sourcePage":"https://openflightmaps.org/downloads/eb/","url":"https://example.test/points.cup","license":"OFMA_GUL","effectiveDate":"2026-11-26"}
class Tests(unittest.TestCase):
 def test_coordinates(self):
  self.assertAlmostEqual(m.parse_coordinate("4812.345N"),48+12.345/60,places=5)
  self.assertAlmostEqual(m.parse_coordinate("48:12.345N"),48+12.345/60,places=5)
  self.assertAlmostEqual(m.parse_coordinate("0112.500E"),1+12.5/60,places=5)
  self.assertAlmostEqual(m.parse_coordinate("48.2"),48.2)
  self.assertAlmostEqual(m.parse_coordinate("0123.000W"),-(1+23/60),places=5)
  self.assertAlmostEqual(m.parse_coordinate("504901N"),50+49/60+1/3600,places=5)
  self.assertAlmostEqual(m.parse_coordinate("0042910E"),4+29/60+10/3600,places=5)
 def test_cup(self):
  rows=m.parse_cup("name,code,country,lat,lon,elev,style\nBrussels,EBBR,BE,504901N,0042910E,184,1\nPoint,ABC,BE,4812.345N,0112.500E,0,5\n",SRC)
  self.assertEqual(len(rows),2);self.assertEqual(rows[0]["region"],"EB");self.assertEqual(rows[0]["source"],"OFMA");self.assertEqual(rows[0]["license"],"OFMA_GUL")
 def test_zip(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,"w") as z:z.writestr("regional.cup","name,code,lat,lon\nTest,TST,4800N,01000E\n")
  self.assertIn("Test",m.payload(b.getvalue()))
 def test_rejections(self):
  with self.assertRaises(ValueError):m.parse_cup("name,code,lat\nA,B,4800N\n",SRC)
  with self.assertRaises(ValueError):m.parse_cup("name,code,lat,lon\nA,B,9999N,01000E\n",SRC)
 def test_source_validation(self):
  s=dict(SRC);s["license"]="CC-BY-NC"
  with self.assertRaises(ValueError):m.validate_source(s)
  s=dict(SRC);s["sourcePage"]="https://example.com"
  with self.assertRaises(ValueError):m.validate_source(s)
if __name__=="__main__":unittest.main()
