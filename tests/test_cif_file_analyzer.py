"""Unit tests for pyads.cif_analyzer — offline, no network or file-system I/O."""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads import cif_analyzer  # noqa: E402


class CifAnalyzerTests(unittest.TestCase):
    """Tests for CIF metadata parsing and material-match scoring."""

    def test_common_name_is_used_when_systematic_name_is_placeholder(self):
        cif_text = """
data_calf-20
_chemical_name_systematic        ?
_chemical_name_common            CALF-20
_chemical_formula_sum            'C14 H8 N12 O9 Zn4'
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            cif_path = Path(temp_dir) / "CALF-20 CIF.cif"
            cif_path.write_text(cif_text, encoding="utf-8")
            metadata = cif_analyzer.cif_text_metadata(cif_path)

        self.assertEqual(metadata["chemical_name"], "CALF-20")
        self.assertEqual(metadata["chemical_formula"], "C14 H8 N12 O9 Zn4")

    def test_material_match_accepts_common_name(self):
        result = cif_analyzer.material_match_score(
            "CALF-20 CIF",
            {"chemical_name": "CALF-20", "chemical_formula": "", "publication_title": ""},
            "Zn4H8C14N12O9",
        )

        self.assertEqual(result["match_label"], "likely_match")
        self.assertEqual(result["match_score"], 1.0)

    def test_material_match_accepts_data_block_name(self):
        result = cif_analyzer.material_match_score(
            "CALF-20 CIF",
            {
                "chemical_name": "",
                "chemical_formula": "",
                "publication_title": "",
                "data_block": "calf-20",
                "file_stem": "CALF-20",
            },
            "Zn4H8C14N12O9",
        )

        self.assertEqual(result["match_label"], "likely_match")

    def test_material_match_does_not_accept_formula_only_wrong_material(self):
        result = cif_analyzer.material_match_score(
            "MIL-53(Al)",
            {"chemical_name": "?", "chemical_formula": "C2 H3 Al F5 N3 Zn", "publication_title": ""},
            "AlZnH3C2N3F5",
        )

        self.assertEqual(result["match_label"], "likely_wrong_material")

    def test_generic_material_is_rejected(self):
        result = cif_analyzer.material_match_score(
            "MOF",
            {"chemical_name": "CALF-20", "chemical_formula": "", "publication_title": ""},
            "Zn4H8C14N12O9",
        )

        self.assertEqual(result["match_label"], "reject_generic_material_name")


if __name__ == "__main__":
    unittest.main()
