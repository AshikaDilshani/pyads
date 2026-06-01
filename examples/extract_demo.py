"""Offline demonstration of pyads extraction without a live Mistral API key.

This script shows how pyads normalises a raw LLM JSON response into the
adsorption schema. It uses a pre-written JSON response so no API key or
network connection is required.

Run from the repository root:
    python examples/extract_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads.extractor import extract_data_from_text, flatten_record  # noqa: E402

# ---------------------------------------------------------------------------
# Simulated OCR text (as if Mistral OCR had processed a PDF)
# ---------------------------------------------------------------------------
SAMPLE_OCR_TEXT = """
Adsorption of CO2 and N2 on ZIF-8

Abstract
ZIF-8 (zeolitic imidazolate framework-8) was synthesised and characterised.
BET surface area: 1200 m²/g.  Total pore volume: 0.55 cm³/g.
Pore size (cavity diameter): 11.6 Å.

CO2 adsorption isotherms were measured at 273 K and 298 K.
N2 physisorption was performed at 77 K.

DOI: 10.1039/d0ta99999a
Title: CO2 and N2 adsorption on ZIF-8
Year: 2023
"""

# ---------------------------------------------------------------------------
# Simulated LLM JSON response (as if Mistral returned this)
# ---------------------------------------------------------------------------
SIMULATED_LLM_RESPONSE = json.dumps({
    "doi": "10.1039/d0ta99999a",
    "title": "CO2 and N2 adsorption on ZIF-8",
    "year": 2023,
    "material": "ZIF-8",
    "surface_area": {"value": 1200.0, "unit": "m2/g"},
    "pore_volume": {"value": 0.55, "unit": "cm3/g"},
    "pore_size": {"value": 11.6, "unit": "Å"},
    "gases": ["CO2", "N2"],
    "isotherm_temperatures": [
        {"value": 273, "unit": "K"},
        {"value": 298, "unit": "K"},
        {"value": 77, "unit": "K"},
    ],
})


def _make_mock_client(response_json: str) -> MagicMock:
    """Build a Mistral client mock that returns *response_json* verbatim."""
    mock_message = MagicMock()
    mock_message.content = response_json

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_usage = MagicMock()
    mock_usage.model_dump.return_value = {
        "prompt_tokens": 312,
        "completion_tokens": 87,
        "total_tokens": 399,
    }

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    client = MagicMock()
    client.chat.complete.return_value = mock_response
    return client


def main() -> None:
    """Run the offline extraction demo and print the result."""
    print("=" * 60)
    print("pyads — offline extraction demo")
    print("=" * 60)

    client = _make_mock_client(SIMULATED_LLM_RESPONSE)

    record, usage = extract_data_from_text(
        text=SAMPLE_OCR_TEXT,
        source_file="zif8_demo.txt",
        client=client,
        model="mistral-small-latest",
    )

    print("\nExtracted record (nested):")
    print(json.dumps(record, indent=2, ensure_ascii=False))

    print("\nFlattened row (as it appears in the Excel output):")
    flat = flatten_record(record)
    for key, value in flat.items():
        print(f"  {key}: {value!r}")

    print(f"\nToken usage: {usage}")
    print("\nDemo complete. No API key or network connection was used.")


if __name__ == "__main__":
    main()
