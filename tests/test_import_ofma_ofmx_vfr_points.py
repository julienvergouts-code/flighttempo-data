import io,unittest,zipfile
from pipeline.import_ofma_ofmx_vfr_points import parse_coord,parse_xml,xml_from_zip,current_airac
from datetime import date
class Tests(unittest.TestCase):
 def test_airac_cycle_rollover(self):
  self.assertEqual(current_airac(date(2026,11,22)),"2611")
  self.assertEqual(current_airac(date(2026,11,26)),"2612")
  self.assertEqual(current_airac(date(2027,1,21)),"2701")
 def test_coordinate_formats_and_hemispheres(self):
  self.assertAlmostEqual(parse_coord("491234.50N"),49+12/60+34.5/3600)
  self.assertAlmostEqual(parse_coord("48.98444444N"),48.98444444)
  self.assertAlmostEqual(parse_coord("015.29111111E"),15.29111111)
  self.assertAlmostEqual(parse_coord("4.755879W"),-4.755879)
  self.assertAlmostEqual(parse_coord("0041234E"),4+12/60+34/3600)
  self.assertAlmostEqual(parse_coord("4912N"),49+12/60)
  self.assertAlmostEqual(parse_coord("491234S"),-(49+12/60+34/3600))
 def test_coordinate_rejects_invalid(self):
  for value in ("496099N","911200N","0040000Q",""):
   with self.assertRaises(ValueError):parse_coord(value)
 def test_filters_only_vfr_designated_points(self):
  xml=b"""<OFMX-Snapshot><Dpn><DpnUid><codeId>AB123</codeId><geoLat>491234N</geoLat><geoLong>0041234E</geoLong></DpnUid><codeType>VFR-RP</codeType><txtName>REPORT POINT</txtName></Dpn><Dpn><DpnUid><codeId>IFR01</codeId><geoLat>491234N</geoLat><geoLong>0041234E</geoLong></DpnUid><codeType>OTHER</codeType><txtName>OTHER</txtName></Dpn></OFMX-Snapshot>"""
  rows=parse_xml(xml,{"region":"EB","effectiveDate":"2611"})
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]["code"],"AB123");self.assertEqual(rows[0]["kind"],"VFR-RP")
 def test_zip_member_selection(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,"w") as z:z.writestr("ofmx_ebbu/embedded/ofmx_ebbu","<OFMX-Snapshot/>")
  self.assertEqual(xml_from_zip(b.getvalue(),"ebbu"),b"<OFMX-Snapshot/>")
 def test_empty_or_bad_schema_fails_closed(self):
  with self.assertRaises(ValueError):parse_xml(b"<OFMX-Snapshot/>",{"region":"EB"})
if __name__=="__main__":unittest.main()
