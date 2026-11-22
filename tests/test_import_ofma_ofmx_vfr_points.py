import zipfile
import io
import json
import unittest
from pathlib import Path
from datetime import date

from pipeline.import_ofma_ofmx_vfr_points import current_airac, parse_coord, parse_xml, select_ofmx_url, xml_from_zip

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
            with self.assertRaises(ValueError): parse_coord(value)
    def test_filters_only_vfr_designated_points(self):
        xml=b"""<OFMX-Snapshot><Dpn><DpnUid region="EBBU"><codeId>AB123</codeId><geoLat>491234N</geoLat><geoLong>0041234E</geoLong></DpnUid><codeType>VFR-RP</codeType><txtName>REPORT POINT</txtName></Dpn><Dpn><DpnUid><codeId>IFR01</codeId><geoLat>491234N</geoLat><geoLong>0041234E</geoLong></DpnUid><codeType>OTHER</codeType><txtName>OTHER</txtName></Dpn></OFMX-Snapshot>"""
        rows=parse_xml(xml,{"region":"EB","cycle":"2611"})
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]["code"],"AB123")
        self.assertEqual(rows[0]["kind"],"VFR-RP");self.assertEqual(rows[0]["feature_region"],"EBBU")
        self.assertEqual(rows[0]["source_regions"],"EB")
    def test_non_vfr_region_is_valid_but_empty_schema_is_not(self):
        xml=b"""<OFMX-Snapshot><Dpn><DpnUid><codeId>X</codeId><geoLat>491234N</geoLat><geoLong>0041234E</geoLong></DpnUid><codeType>OTHER</codeType></Dpn></OFMX-Snapshot>"""
        self.assertEqual(parse_xml(xml,{"region":"XX"}),[])
        with self.assertRaisesRegex(ValueError,"no Dpn"): parse_xml(b"<OFMX-Snapshot/>",{"region":"XX"})
    def test_publication_service_selects_only_current_official_ofmx_zip(self):
        xml=b"""<publications><item type="downloads"><product type="OFMX"><download URL="https://snapshots.openflightmaps.org/live/2611/ofmx/ebbu/latest/ofmx_eb.zip"/></product><product type="ARINC424"><download URL="https://snapshots.openflightmaps.org/live/2611/arinc424/ebbu/latest/arinc_eb.zip"/></product><product type="OFMX"><variant URL="https://example.org/ofmx_bad.zip"/></product></item></publications>"""
        self.assertEqual(select_ofmx_url(xml,"2611"),"https://snapshots.openflightmaps.org/live/2611/ofmx/ebbu/latest/ofmx_eb.zip")
    def test_publication_service_fails_closed_on_missing_or_ambiguous_package(self):
        with self.assertRaises(ValueError): select_ofmx_url(b"<publications/>","2611")
        xml=b"""<publications><product type="OFMX"><download URL="https://snapshots.openflightmaps.org/live/2611/ofmx/ebbu/latest/ofmx_eb.zip"/><variant URL="https://snapshots.openflightmaps.org/live/2611/ofmx/ed/latest/ofmx_ed.zip"/></product></publications>"""
        with self.assertRaisesRegex(ValueError,"found 2"): select_ofmx_url(xml,"2611")
    def test_zip_member_selection(self):
        source={"region":"EB","regionKey":"ebbu","archiveKey":"eb"}
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,"w") as archive:
            archive.writestr("ofmx_eb/embedded/ofmx_eb","<OFMX-Snapshot/>")
            archive.writestr("ofmx_eb/embedded/ofmx_eb_ofmShapeExtension.xml","<Shape/>")
            archive.writestr("ofmx_eb/isolated/ofmx_eb","<OFMX-Snapshot/>")
        self.assertEqual(xml_from_zip(buffer.getvalue(),source),b"<OFMX-Snapshot/>")
        with zipfile.ZipFile(buffer,"a") as archive: archive.writestr("another/embedded/ofmx_eb","<OFMX-Snapshot/>")
        with self.assertRaises(ValueError): xml_from_zip(buffer.getvalue(),source)
    def test_config_contains_all_ofma_catalogue_regions_and_commercial_license_gate(self):
        root=Path(__file__).resolve().parents[1]
        config=json.loads((root/"data/ofma_ofmx_sources.json").read_text(encoding="utf-8"))
        expected={"EB","ED","EF","EH","EK","EP","ES","FA","FY","LD","LF","LG","LH","LI","LJ","LK","LM","LO","LR","LS","LZ"}
        self.assertEqual({item["region"] for item in config["regions"]},expected)
        self.assertTrue(all(item["license"]=="OFMA_GUL" for item in config["regions"]))
        self.assertTrue(all(item["sourcePage"].startswith("https://openflightmaps.org/downloads/") for item in config["regions"]))

if __name__=="__main__": unittest.main()
