import unittest
from datetime import date

from scripts.fetch_sia_eaip_procedure_data import (
    discover_documents,
    issue_base_url,
    parse_catalog_issues,
    select_current_issue,
)


class SiaCurrentProcedureFeedTests(unittest.TestCase):
    def test_catalog_issue_selection_uses_effective_dates(self):
        text = (
            "ZIP eAIP complet AIRAC 11/26 (984 Mo) en vigueur du 29/10/2026 au 25/11/2026 inclus "
            "ZIP eAIP complet AIRAC 12/26 (987 Mo) en vigueur du 26/11/2026 au 23/12/2026 inclus"
        )
        issues = parse_catalog_issues(text)
        self.assertEqual(len(issues), 2)
        self.assertEqual(select_current_issue(issues, date(2026, 11, 22))["cycle"], "11/26")
        self.assertEqual(select_current_issue(issues, date(2026, 11, 26))["cycle"], "12/26")
        with self.assertRaises(ValueError):
            select_current_issue(issues, date(2026, 12, 24))

    def test_current_release_folder_comes_from_effective_date(self):
        issue = {"effectiveDate": "2026-10-29"}
        self.assertEqual(
            issue_base_url(issue),
            "https://www.sia.aviation-civile.gouv.fr/media/dvd/eAIP_29_OCT_2026/FRANCE/AIRAC-2026-10-29",
        )

    def test_gen_04_finds_only_sid_and_star_data_sheets(self):
        index = """
        AD 2 LFPG DATA SID RWY26L-26R RNAV CODE 02 01 OCT 2026
        AD 2 LFPG DATA STAR RWY26L RNAV CODE 02 11 JUN 2026
        AD 2 LFPG DATA RWY26L FNA RNP CODE 01 OCT 2026
        AD 2 LFXX DATA SID TEST 01 01 OCT 2026
        """
        docs = discover_documents(index)
        self.assertEqual(len(docs), 3)
        by_name = {item["filename"]: item for item in docs}
        self.assertIn("AD_2_LFPG_DATA_SID_RWY26L-26R_RNAV_CODE_02.pdf", by_name)
        self.assertIn("AD_2_LFPG_DATA_STAR_RWY26L_RNAV_CODE_02.pdf", by_name)
        self.assertNotIn("AD_2_LFPG_DATA_RWY26L_FNA_RNP_CODE_01.pdf", by_name)
        self.assertEqual(by_name["AD_2_LFXX_DATA_SID_TEST_01.pdf"]["airport"], "LFXX")


if __name__ == "__main__":
    unittest.main()
