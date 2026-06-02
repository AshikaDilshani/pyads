"""Unit tests for pyads.extractor — offline, Mistral client is fully mocked."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads import extractor  # noqa: E402


def _make_mock_client(response_json: str) -> MagicMock:
    """Return a Mistral client mock that returns *response_json* as the LLM reply."""
    mock_message = MagicMock()
    mock_message.content = response_json

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_usage = MagicMock()
    mock_usage.model_dump.return_value = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_client = MagicMock()
    mock_client.chat.complete.return_value = mock_response
    return mock_client


def _paper_response(materials=None):
    """Build a JSON string representing a v2 paper response with one or more materials."""
    if materials is None:
        materials = [{
            "material": "ZIF-8",
            "surface_area": {"value": 1200, "unit": "m2/g"},
            "pore_volume": {"value": 0.55, "unit": "cm3/g"},
            "pore_size": {"value": 3.4, "unit": "Å"},
            "gases": ["CO2", "N2"],
            "isotherm_temperatures": [
                {"value": 273, "unit": "K"},
                {"value": 298, "unit": "K"},
            ],
        }]
    return json.dumps({
        "doi": "10.1000/xyz123",
        "title": "CO2 capture with ZIF-8",
        "year": 2023,
        "materials": materials,
    })


class ParseJsonTests(unittest.TestCase):
    """Tests for the internal JSON-cleaning helper."""

    def test_parses_plain_json(self):
        raw = '{"material": "ZIF-8", "year": 2020}'
        result = extractor._parse_json(raw)
        self.assertEqual(result["material"], "ZIF-8")

    def test_strips_markdown_fences(self):
        raw = "```json\n{\"material\": \"MOF-5\"}\n```"
        result = extractor._parse_json(raw)
        self.assertEqual(result["material"], "MOF-5")

    def test_extracts_json_from_surrounding_text(self):
        raw = 'Here is the result: {"year": 2021} — end.'
        result = extractor._parse_json(raw)
        self.assertEqual(result["year"], 2021)


class NormalizeMaterialTests(unittest.TestCase):
    """Tests for _normalize_material — normalises one material entry."""

    def _normalize(self, raw: dict) -> dict:
        return extractor._normalize_material(raw)

    def test_valid_surface_area_is_kept(self):
        mat = self._normalize({"surface_area": {"value": 1500, "unit": "m2/g"}})
        self.assertEqual(mat["surface_area"]["value"], 1500)
        self.assertEqual(mat["surface_area"]["unit"], "m2/g")

    def test_surface_area_with_volume_unit_is_cleared(self):
        mat = self._normalize({"surface_area": {"value": 0.5, "unit": "cm3/g"}})
        self.assertIsNone(mat["surface_area"]["value"])

    def test_valid_pore_volume_is_kept(self):
        mat = self._normalize({"pore_volume": {"value": 0.55, "unit": "cm3/g"}})
        self.assertEqual(mat["pore_volume"]["value"], 0.55)

    def test_duplicate_temperatures_are_deduplicated(self):
        raw = {
            "isotherm_temperatures": [
                {"value": 298, "unit": "K"},
                {"value": 298, "unit": "K"},
                {"value": 273, "unit": "K"},
            ]
        }
        mat = self._normalize(raw)
        self.assertEqual(len(mat["isotherm_temperatures"]), 2)

    def test_gases_coerced_to_list_when_string(self):
        mat = self._normalize({"gases": "CO2"})
        self.assertIsInstance(mat["gases"], list)
        self.assertIn("CO2", mat["gases"])

    def test_empty_material_has_null_fields(self):
        mat = self._normalize({})
        self.assertIsNone(mat["material"])
        self.assertIsNone(mat["surface_area"]["value"])


class NormalizeRecordTests(unittest.TestCase):
    """Tests for _normalize_record — produces a v2 paper dict."""

    def test_schema_version_is_2(self):
        paper = extractor._normalize_record({}, "test.txt")
        self.assertEqual(paper["schema_version"], 2)

    def test_source_file_is_set(self):
        paper = extractor._normalize_record({}, "test.txt")
        self.assertEqual(paper["source_file"], "test.txt")

    def test_materials_list_is_normalised(self):
        raw = {
            "doi": "10.1/x",
            "materials": [
                {"material": "ZIF-8", "surface_area": {"value": 1630, "unit": "m2/g"}}
            ],
        }
        paper = extractor._normalize_record(raw, "test.txt")
        self.assertEqual(len(paper["materials"]), 1)
        self.assertEqual(paper["materials"][0]["material"], "ZIF-8")
        self.assertEqual(paper["materials"][0]["surface_area"]["value"], 1630)

    def test_multiple_materials_are_preserved(self):
        raw = {
            "materials": [
                {"material": "ZIF-8", "surface_area": {"value": 1630, "unit": "m2/g"}},
                {"material": "HKUST-1", "surface_area": {"value": 1507, "unit": "m2/g"}},
            ]
        }
        paper = extractor._normalize_record(raw, "test.txt")
        self.assertEqual(len(paper["materials"]), 2)

    def test_flat_v1_input_is_wrapped_in_materials_list(self):
        raw = {"material": "MOF-5", "surface_area": {"value": 2900, "unit": "m2/g"}}
        paper = extractor._normalize_record(raw, "test.txt")
        self.assertEqual(len(paper["materials"]), 1)
        self.assertEqual(paper["materials"][0]["material"], "MOF-5")

    def test_doi_and_year_at_paper_level(self):
        raw = {"doi": "10.1/x", "year": 2023, "materials": []}
        paper = extractor._normalize_record(raw, "test.txt")
        self.assertEqual(paper["doi"], "10.1/x")
        self.assertEqual(paper["year"], 2023)


class ExtractDataFromTextTests(unittest.TestCase):
    """Integration-style tests for extract_data_from_text with a mocked client."""

    def test_returns_v2_paper_with_materials(self):
        client = _make_mock_client(_paper_response())
        paper, usage = extractor.extract_data_from_text(
            "BET surface area 1200 m2/g. CO2 at 298 K.", "paper.txt", client, "mistral-small-latest"
        )
        self.assertEqual(paper["schema_version"], 2)
        self.assertEqual(len(paper["materials"]), 1)
        self.assertEqual(paper["materials"][0]["material"], "ZIF-8")
        self.assertEqual(paper["materials"][0]["surface_area"]["value"], 1200)
        self.assertEqual(usage["total_tokens"], 150)

    def test_multiple_materials_extracted(self):
        response = _paper_response(materials=[
            {"material": "ZIF-8", "surface_area": {"value": 1630, "unit": "m2/g"}, "gases": ["N2"],
             "pore_volume": {"value": 0.636, "unit": "cm3/g"}, "pore_size": {"value": 11.6, "unit": "A"},
             "isotherm_temperatures": [{"value": 77, "unit": "K"}]},
            {"material": "HKUST-1", "surface_area": {"value": 1507, "unit": "m2/g"}, "gases": ["H2"],
             "pore_volume": {"value": 0.75, "unit": "cm3/g"}, "pore_size": {"value": None, "unit": None},
             "isotherm_temperatures": [{"value": 77, "unit": "K"}]},
        ])
        client = _make_mock_client(response)
        paper, _ = extractor.extract_data_from_text("text", "multi.txt", client, "mistral-small-latest")
        self.assertEqual(len(paper["materials"]), 2)
        names = [m["material"] for m in paper["materials"]]
        self.assertIn("ZIF-8", names)
        self.assertIn("HKUST-1", names)

    def test_llm_is_called_once_per_extraction(self):
        client = _make_mock_client(_paper_response())
        extractor.extract_data_from_text("some text", "f.txt", client, "mistral-small-latest")
        client.chat.complete.assert_called_once()


class RetryLogicTests(unittest.TestCase):
    """Tests for _chat_json_with_retries rate-limit handling."""

    @staticmethod
    def _ok_response(content: str) -> MagicMock:
        msg = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        usage = MagicMock()
        usage.model_dump.return_value = {
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15
        }
        response = MagicMock()
        response.choices = [choice]
        response.usage = usage
        return response

    def test_raises_immediately_on_non_rate_limit_error(self):
        client = MagicMock()
        client.chat.complete.side_effect = ValueError("bad model")
        with self.assertRaises(ValueError):
            extractor._chat_json_with_retries(
                client, "mistral-small-latest", "prompt", "system", retries=2, base_delay=0
            )
        self.assertEqual(client.chat.complete.call_count, 1)

    def test_retries_on_rate_limit_then_succeeds(self):
        client = MagicMock()
        client.chat.complete.side_effect = [
            Exception("status 429: rate limit"),
            self._ok_response('{"material": "ZIF-8"}'),
        ]
        with patch("pyads.extractor.time.sleep"):
            result, _ = extractor._chat_json_with_retries(
                client, "mistral-small-latest", "prompt", "system", retries=2, base_delay=0
            )
        self.assertEqual(result.get("material"), "ZIF-8")
        self.assertEqual(client.chat.complete.call_count, 2)

    def test_raises_after_exhausting_retries(self):
        client = MagicMock()
        client.chat.complete.side_effect = Exception("status 429: rate limit")
        with patch("pyads.extractor.time.sleep"), self.assertRaises(Exception):
            extractor._chat_json_with_retries(
                client, "mistral-small-latest", "prompt", "system", retries=1, base_delay=0
            )
        self.assertEqual(client.chat.complete.call_count, 2)


class EvidenceTextTests(unittest.TestCase):
    """Tests for keyword-focused text truncation."""

    def test_short_text_is_returned_unchanged(self):
        text = "BET surface area 1000 m2/g"
        result = extractor._evidence_text(text, max_chars=10000)
        self.assertEqual(result, text)

    def test_long_text_is_truncated_to_max_chars(self):
        long_text = ("irrelevant filler\n\n" * 500) + "BET surface area 1200 m2/g"
        result = extractor._evidence_text(long_text, max_chars=500)
        self.assertLessEqual(len(result), 500)


class ValidateRecordFromTextTests(unittest.TestCase):
    """Tests for the strict second-pass validation function."""

    _CORRECTED = _paper_response(materials=[{
        "material": "ZIF-8",
        "surface_area": {"value": 1600.0, "unit": "m2/g"},
        "pore_volume": {"value": 0.636, "unit": "cm3/g"},
        "pore_size": {"value": 3.4, "unit": "Å"},
        "gases": ["CO2"],
        "isotherm_temperatures": [{"value": 298, "unit": "K"}],
    }])

    def test_returns_corrected_paper(self):
        client = _make_mock_client(self._CORRECTED)
        paper = extractor._empty_record("paper.txt")
        corrected, usage = extractor.validate_record_from_text(
            paper, "BET surface area 1600 m2/g.", client, "mistral-small-latest"
        )
        self.assertEqual(corrected["materials"][0]["material"], "ZIF-8")
        self.assertEqual(corrected["materials"][0]["surface_area"]["value"], 1600.0)
        self.assertEqual(usage["total_tokens"], 150)

    def test_llm_is_called_once_per_validation(self):
        client = _make_mock_client(self._CORRECTED)
        paper = extractor._empty_record("paper.txt")
        extractor.validate_record_from_text(paper, "some text", client, "mistral-small-latest")
        client.chat.complete.assert_called_once()

    def test_schema_version_2_preserved_after_correction(self):
        client = _make_mock_client(self._CORRECTED)
        paper = extractor._empty_record("paper.txt")
        corrected, _ = extractor.validate_record_from_text(
            paper, "some text", client, "mistral-small-latest"
        )
        self.assertEqual(corrected["schema_version"], 2)


class SaveOutputsTests(unittest.TestCase):
    """Tests for save_outputs: file creation and content correctness."""

    def _sample_paper(self, material="ZIF-8"):
        paper = extractor._empty_record("paper.txt")
        paper["doi"] = "10.1/test"
        paper["materials"] = [{
            **extractor._empty_material(),
            "material": material,
            "surface_area": {"value": 1200.0, "unit": "m2/g"},
            "gases": ["CO2"],
        }]
        return paper

    def test_creates_json_excel_and_usage_files(self):
        papers = [self._sample_paper()]
        usage = {"total": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
        with tempfile.TemporaryDirectory() as output_dir:
            outputs = extractor.save_outputs(papers, usage, output_dir)
            self.assertTrue(Path(outputs["json"]).exists())
            self.assertTrue(Path(outputs["excel"]).exists())
            self.assertTrue(Path(outputs["usage"]).exists())

    def test_json_contains_all_papers(self):
        papers = [self._sample_paper("ZIF-8"), self._sample_paper("HKUST-1")]
        usage = {"total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        with tempfile.TemporaryDirectory() as output_dir:
            outputs = extractor.save_outputs(papers, usage, output_dir)
            import json as _json  # pylint: disable=import-outside-toplevel
            saved = _json.loads(Path(outputs["json"]).read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]["materials"][0]["material"], "ZIF-8")

    def test_excel_has_one_row_per_material(self):
        multi_paper = extractor._empty_record("paper.txt")
        multi_paper["materials"] = [
            {**extractor._empty_material(), "material": "ZIF-8"},
            {**extractor._empty_material(), "material": "HKUST-1"},
        ]
        usage = {"total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        with tempfile.TemporaryDirectory() as output_dir:
            outputs = extractor.save_outputs([multi_paper], usage, output_dir)
            import pandas as pd  # pylint: disable=import-outside-toplevel
            df = pd.read_excel(outputs["excel"])
        self.assertEqual(len(df), 2)
        self.assertIn("ZIF-8", df["material"].tolist())
        self.assertIn("HKUST-1", df["material"].tolist())

    def test_json_records_carry_schema_version_2(self):
        papers = [self._sample_paper()]
        usage = {"total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        with tempfile.TemporaryDirectory() as output_dir:
            outputs = extractor.save_outputs(papers, usage, output_dir)
            import json as _json  # pylint: disable=import-outside-toplevel
            saved = _json.loads(Path(outputs["json"]).read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["schema_version"], 2)

    def test_output_dir_is_created_if_missing(self):
        papers = [self._sample_paper()]
        usage = {"total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        with tempfile.TemporaryDirectory() as base_dir:
            output_dir = Path(base_dir) / "nested" / "outputs"
            extractor.save_outputs(papers, usage, output_dir)
            self.assertTrue(output_dir.exists())


class ProcessTextFilesTests(unittest.TestCase):
    """End-to-end tests for process_text_files with a mocked Mistral client."""

    _LLM_RESPONSE = _paper_response(materials=[{
        "material": "ZIF-8",
        "surface_area": {"value": 1630.0, "unit": "m2/g"},
        "pore_volume": {"value": 0.636, "unit": "cm3/g"},
        "pore_size": {"value": 3.4, "unit": "Å"},
        "gases": ["CO2"],
        "isotherm_temperatures": [{"value": 298, "unit": "K"}],
    }])

    def _setup_dirs(self, text_content="BET surface area 1630 m2/g at 298 K."):
        tmp = tempfile.mkdtemp()
        text_dir = Path(tmp) / "text"
        output_dir = Path(tmp) / "output"
        text_dir.mkdir()
        (text_dir / "paper.txt").write_text(text_content, encoding="utf-8")
        return text_dir, output_dir

    def test_extracts_one_paper_from_one_text_file(self):
        text_dir, output_dir = self._setup_dirs()
        client = _make_mock_client(self._LLM_RESPONSE)
        with patch("pyads.extractor.MISTRAL_API_KEY", "test-key"), \
                patch("pyads.extractor.Mistral", return_value=client):
            papers, outputs, _ = extractor.process_text_files(
                text_dir=text_dir, output_dir=output_dir, second_pass=False,
            )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["materials"][0]["material"], "ZIF-8")
        self.assertTrue(Path(outputs["json"]).exists())

    def test_second_pass_calls_llm_twice(self):
        text_dir, output_dir = self._setup_dirs()
        client = _make_mock_client(self._LLM_RESPONSE)
        with patch("pyads.extractor.MISTRAL_API_KEY", "test-key"), \
                patch("pyads.extractor.Mistral", return_value=client):
            extractor.process_text_files(
                text_dir=text_dir, output_dir=output_dir, second_pass=True,
            )
        self.assertEqual(client.chat.complete.call_count, 2)

    def test_confidence_key_present_in_each_material(self):
        text_dir, output_dir = self._setup_dirs()
        client = _make_mock_client(self._LLM_RESPONSE)
        with patch("pyads.extractor.MISTRAL_API_KEY", "test-key"), \
                patch("pyads.extractor.Mistral", return_value=client):
            papers, _, _ = extractor.process_text_files(
                text_dir=text_dir, output_dir=output_dir, second_pass=True,
            )
        mat = papers[0]["materials"][0]
        self.assertIn("confidence", mat)
        self.assertIn("overall", mat["confidence"])

    def test_raises_when_no_api_key(self):
        text_dir, output_dir = self._setup_dirs()
        with patch("pyads.extractor.MISTRAL_API_KEY", None):
            with self.assertRaises(RuntimeError):
                extractor.process_text_files(text_dir=text_dir, output_dir=output_dir)

    def test_raises_when_no_text_files(self):
        with tempfile.TemporaryDirectory() as empty_dir, \
                tempfile.TemporaryDirectory() as output_dir:
            with patch("pyads.extractor.MISTRAL_API_KEY", "test-key"):
                with self.assertRaises(FileNotFoundError):
                    extractor.process_text_files(
                        text_dir=empty_dir, output_dir=output_dir,
                    )


class FlattenRecordTests(unittest.TestCase):
    """Tests for the public flatten_record helper — returns list[dict], one per material."""

    def _paper(self, materials=None):
        paper = extractor._empty_record("paper.txt")
        paper["doi"] = "10.1/test"
        if materials is not None:
            paper["materials"] = materials
        return paper

    def test_returns_list_with_one_row_per_material(self):
        paper = self._paper(materials=[
            {**extractor._empty_material(), "material": "ZIF-8"},
            {**extractor._empty_material(), "material": "MOF-5"},
        ])
        rows = extractor.flatten_record(paper)
        self.assertEqual(len(rows), 2)

    def test_paper_fields_repeated_on_each_row(self):
        paper = self._paper(materials=[
            {**extractor._empty_material(), "material": "ZIF-8"},
            {**extractor._empty_material(), "material": "MOF-5"},
        ])
        rows = extractor.flatten_record(paper)
        for row in rows:
            self.assertEqual(row["doi"], "10.1/test")
            self.assertEqual(row["source_file"], "paper.txt")

    def test_nested_surface_area_is_flattened(self):
        mat = {**extractor._empty_material(), "material": "ZIF-8",
               "surface_area": {"value": 1200.0, "unit": "m2/g"}}
        paper = self._paper(materials=[mat])
        rows = extractor.flatten_record(paper)
        self.assertEqual(rows[0]["bet_surface_area_value"], 1200.0)
        self.assertEqual(rows[0]["bet_surface_area_unit"], "m2/g")

    def test_gases_joined_with_semicolons(self):
        mat = {**extractor._empty_material(), "material": "ZIF-8", "gases": ["CO2", "N2"]}
        paper = self._paper(materials=[mat])
        rows = extractor.flatten_record(paper)
        self.assertEqual(rows[0]["gases"], "CO2; N2")

    def test_empty_materials_list_returns_one_placeholder_row(self):
        paper = self._paper(materials=[])
        rows = extractor.flatten_record(paper)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["material"])

    def test_null_surface_area_flattens_to_none(self):
        paper = self._paper(materials=[extractor._empty_material()])
        rows = extractor.flatten_record(paper)
        self.assertIsNone(rows[0]["bet_surface_area_value"])

    def test_confidence_overall_included_when_present(self):
        mat = {**extractor._empty_material(), "material": "ZIF-8",
               "confidence": {"overall": "high", "fields": {}}}
        paper = self._paper(materials=[mat])
        rows = extractor.flatten_record(paper)
        self.assertEqual(rows[0]["confidence_overall"], "high")


if __name__ == "__main__":
    unittest.main()
