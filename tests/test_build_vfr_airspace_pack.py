import gzip, importlib.util, json, tempfile, unittest
from pathlib import Path
import xml.etree.ElementTree as ET
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"build_vfr_airspace_pack.py"
SPEC=importlib.util.spec_from_file_location("vfr",SCRIPT); M=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)
FIXTURE="""<m xmlns:a="urn:a" xmlns:gml="http://www.opengis.net/gml"><a:Airspace id="A1">
<a:txtName>Test CTR</a:txtName><a:codeType>CTR</a:codeType>
<a:AirspaceVolume><a:valLowerLimit uom="FT">SFC</a:valLowerLimit><a:valUpperLimit uom="FT">2500</a:valUpperLimit>
<a:horizontalProjection><gml:Polygon><gml:exterior><gml:LinearRing><gml:posList>4 50 5 50 5 51 4 50</gml:posList></gml:LinearRing></gml:exterior>
<gml:interior><gml:LinearRing><gml:posList>4.2 50.2 4.3 50.2 4.3 50.3 4.2 50.2</gml:posList></gml:LinearRing></gml:interior></gml:Polygon></a:horizontalProjection></a:AirspaceVolume>
<a:AirspaceVolume><a:valLowerLimit uom="FT">2500</a:valLowerLimit><a:valUpperLimit uom="FT">4500</a:valUpperLimit><a:horizontalProjection><gml:Polygon><gml:exterior><gml:LinearRing><gml:posList>4 50 5 50 5 51 4 50</gml:posList></gml:LinearRing></gml:exterior></gml:Polygon></a:horizontalProjection></a:AirspaceVolume>
</a:Airspace></m>"""
class Tests(unittest.TestCase):
 def test_volume_split_and_holes(self):
  rows,errs=M.extract(ET.fromstring(FIXTURE),"auto"); self.assertEqual(len(rows),2)
  self.assertEqual(rows[0]["name"],"Test CTR"); self.assertEqual(len(rows[0]["geometry"]["coordinates"]),2)
  self.assertEqual(rows[0]["lowerLimit"]["value"],"SFC"); self.assertEqual(rows[1]["lowerLimit"]["value"],"2500")
  self.assertFalse(errs)
 def test_axis_order(self):
  self.assertEqual(M.ring_points(ET.fromstring('<r><posList>50 4 50 5 51 5</posList></r>'),"latlon")[0],[4.0,50.0])
 def test_curves_fail_closed(self):
  xml=FIXTURE.replace("<gml:posList>","<gml:Arc/><gml:posList>",1)
  rows,errs=M.extract(ET.fromstring(xml),"auto"); self.assertEqual(len(rows),1)
  self.assertTrue(any("Arc" in e for e in errs))
 def test_filter(self):
  rows,_=M.extract(ET.fromstring(FIXTURE.replace(">CTR<",">FIR<")),"auto"); self.assertEqual(rows,[])
 def test_deterministic_gzip(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"a.gz"; h1=M.write_gzip(p,[{"x":1}]); b=p.read_bytes()
   h2=M.write_gzip(p,[{"x":1}]); self.assertEqual(h1,h2); self.assertEqual(b,p.read_bytes())
   with gzip.open(p,"rt") as f: self.assertEqual(json.load(f),[{"x":1}])
if __name__=="__main__": unittest.main()
