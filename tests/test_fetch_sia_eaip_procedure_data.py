import unittest
from datetime import date

from scripts.fetch_sia_eaip_procedure_data import (
    discover_documents,
    issue_base_url,
    parse_catalog_issues,
    select_current_issue,
    validate_parse_coverage,
    verify_sia_commercial_reuse,
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

    def test_partial_parse_is_published_only_when_both_types_are_parsed_and_accounted(self):
        documents = [
            {"filename": "sid.pdf", "kind": "SID"},
            {"filename": "star.pdf", "kind": "STAR"},
            {"filename": "unsupported.pdf", "kind": "SID"},
        ]
        report = validate_parse_coverage(documents, [
            {"source_file": "sid.pdf", "record_count": 18},
            {"source_file": "star.pdf", "record_count": 7},
            {"source_file": "unsupported.pdf", "record_count": 0},
        ])
        self.assertTrue(report["partialExtraction"])
        self.assertEqual(report["parsedDocumentCount"], 2)
        self.assertEqual(report["skippedDocumentCount"], 1)
        self.assertEqual(report["parsedDocumentCountsByType"], {"SID": 1, "STAR": 1})

    def test_partial_parse_fails_if_any_indexed_sheet_is_unaccounted_for(self):
        with self.assertRaisesRegex(ValueError, "source accounting mismatch"):
            validate_parse_coverage(
                [{"filename": "sid.pdf", "kind": "SID"}],
                [],
            )

    def test_partial_parse_fails_if_sid_or_star_type_is_missing(self):
        with self.assertRaisesRegex(ValueError, "at least one indexed SID and STAR"):
            validate_parse_coverage(
                [
                    {"filename": "sid.pdf", "kind": "SID"},
                    {"filename": "star.pdf", "kind": "STAR"},
                ],
                [
                    {"source_file": "sid.pdf", "record_count": 18},
                    {"source_file": "star.pdf", "record_count": 0},
                ],
            )

    def test_commercial_reuse_is_verified_against_live_sia_product_and_terms(self):
        catalog = (
            "ZIP eAIP complet AIRAC 11/26 en vigueur du 29/10/2026 au 25/11/2026 "
            "TTC: 0,00 € 0,00 €"
        )
        license_text = (
            "Tous les produits des sous rubriques de Produits numériques en libre "
            "disposition sont soumis à la LICENCE OUVERTE, à l'exception des données "
            "des zones géographiques UAS. Réutilisation à des fins commerciales ou "
            "non dans le monde entier. Adapter, transformer, redistribuer, exploiter "
            "commercialement en incluant dans son propre produit ou application. "
            "Mentionner la source et la date de dernière mise à jour."
        )
        result = verify_sia_commercial_reuse(
            catalog, license_text, {"cycle": "11/26"}
        )
        self.assertTrue(result["commercialUseAllowed"])
        self.assertEqual(result["productPrice"], "EUR 0")

    def test_commercial_reuse_check_fails_if_product_is_paid_or_terms_change(self):
        issue = {"cycle": "11/26"}
        free_product = "ZIP eAIP complet AIRAC 11/26 TTC: 0,00 €"
        terms = (
            "Tous les produits des sous rubriques sont soumis à la LICENCE OUVERTE. "
            "A des fins commerciales ou non, redistribuer dans son produit ou application. "
            "Date de dernière mise à jour. Zones géographiques UAS."
        )
        with self.assertRaisesRegex(ValueError, "not listed as free"):
            verify_sia_commercial_reuse(
                free_product.replace("0,00", "10,00"), terms, issue
            )
        with self.assertRaisesRegex(ValueError, "no longer proves commercial"):
            verify_sia_commercial_reuse(
                free_product, terms.replace("commerciales ou non", "non-commercial"), issue
            )


if __name__ == "__main__":
    unittest.main()
