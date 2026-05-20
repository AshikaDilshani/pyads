import importlib.util
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINDER_PATH = PROJECT_ROOT / "cif_file_finder.py"


def load_finder_module():
    spec = importlib.util.spec_from_file_location("cif_file_finder", FINDER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CifFileFinderTests(unittest.TestCase):
    def setUp(self):
        self.finder = load_finder_module()

    def test_unique_material_rows_uses_adsorption_columns(self):
        dataframe = pd.DataFrame(
            [
                {"material": "CALF-20", "doi": "10.1/example", "title": "Paper title"},
                {"material": "CALF-20", "doi": "10.1/example", "title": "Paper title"},
                {"material": "MOF", "doi": "10.2/generic", "title": "Generic material"},
            ]
        )

        rows = self.finder.unique_material_rows(dataframe)

        self.assertEqual(rows, [{"material": "CALF-20", "doi": "10.1/example", "title": "Paper title"}])

    def test_candidate_queries_include_material_doi_and_title(self):
        queries = self.finder.candidate_queries(
            "HKUST-1@PS_63",
            "10.1002_adma.201403827",
            "Protecting Metal-Organic Framework Crystals",
        )

        self.assertIn("HKUST-1@PS_63", queries)
        self.assertIn("HKUST-1@PS 63", queries)
        self.assertIn("10.1002/adma.201403827", queries)
        self.assertIn("Protecting Metal-Organic Framework Crystals", queries)

    def test_choose_best_cod_result_prefers_material_name(self):
        results = [
            {"file": "1", "title": "Unrelated compound"},
            {"file": "2", "title": "CALF-20 porous framework"},
        ]

        result = self.finder.choose_best_cod_result(results, "CALF-20", "")

        self.assertEqual(result["file"], "2")

    def test_looks_like_cif_requires_cif_markers(self):
        self.assertTrue(self.finder.looks_like_cif("data_test\n_cell_length_a 1\n"))
        self.assertFalse(self.finder.looks_like_cif("plain text"))


if __name__ == "__main__":
    unittest.main()
