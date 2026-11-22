import unittest
from scripts.monitor_ofma_downloads import Links, REGIONS, FORMATS, scan_script_text
class Tests(unittest.TestCase):
    def test_region_registry_includes_key_european_regions(self):
        for code in ("EB","ED","EH","LF","LO","LI","LG"):
            self.assertIn(code,REGIONS)
    def test_extract_download_links_and_data_attributes(self):
        p=Links()
        p.feed('<a href="/data/points.cup">CUP</a><a href="/map">Map</a><script src="/app.js" data-api-url="/api/region"></script>')
        self.assertEqual(p.hrefs,["/data/points.cup","/map"])
        self.assertEqual(p.srcs,["/app.js"])
        self.assertEqual(p.data_attrs,[{"attribute":"data-api-url","value":"/api/region"}])
    def test_script_endpoint_string_scan(self):
        candidates,snippets=scan_script_text('"/wp-admin/admin-ajax.php?action=download" "snapshots/2612/eb/data.zip"')
        self.assertTrue(any("download" in value for value in candidates))
        self.assertTrue(any("snapshots" in value for value in candidates))
        self.assertTrue(snippets)
    def test_supported_format_hints(self):
        self.assertIn(".cup",FORMATS);self.assertIn(".ofmx",FORMATS)
if __name__=="__main__":unittest.main()
