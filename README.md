# Mistral PDF Reader

End-to-end adsorption paper processing pipeline:

1. Read PDF papers with Mistral OCR.
2. Extract structured adsorption data from text files.
3. Download matching CIF files from open crystallography sources.
4. Analyze downloaded CIF files for validity, material matching, structure data, and simulated XRD.

`runner.py` is the main entrypoint for the project.

## Outputs

- `data/text/` - OCR text files.
- `data/extracted/adsorption_data.json` - structured adsorption records.
- `data/extracted/adsorption_data.xlsx` - Excel version of the structured records.
- `data/extracted/usage_summary.json` - Mistral token usage for extraction.
- `cif_file/*.cif` - downloaded CIF files.
- `cif_file/cif_download_report.csv` - CIF search/download report.
- `cif_file/cif_analysis_report.csv` - CIF validity and material-match report.
- `cif_file/xrd_patterns/` - simulated XRD pattern CSV files.

## Setup

Install dependencies in the Python environment you will use to run the project:

```powershell
python -m pip install -e .
```

Use an activated environment (venv/conda) before installing so the `pyads` command is available in that shell.

Create `.env` from `.env.example` and set:

```text
MISTRAL_API_KEY=your_mistral_api_key_here
```

Do not commit `.env`.

If Python keeps using the wrong environment, run with the full environment path, for example:

```powershell
C:\Users\2929642\AppData\Local\anaconda3\envs\adsorption\python.exe -m pip install -e .
```

## Inputs

Supported PDF input folders:

- `data/pdfs/`
- `PDF/`

The CIF downloader uses `data/extracted/adsorption_data.json` by default because JSON avoids Excel file-locking problems from OneDrive or an open spreadsheet. Excel output is still written for manual review.

## Run The Full Pipeline

From the project root folder, run:

```powershell
pyads
```

This is equivalent to:

```powershell
python runner.py
```

Useful options:

```powershell
pyads --limit 1
pyads --skip-ocr
pyads --skip-extraction
pyads --skip-cif-download
pyads --skip-cif-analysis
pyads --second-pass
```

`--second-pass` enables the stricter Mistral validation pass. It is off by default to reduce rate-limit errors and token usage.

Examples:

```powershell
pyads --skip-ocr --limit 1
pyads --skip-ocr --skip-extraction
pyads --skip-ocr --skip-extraction --skip-cif-download
```

## Run CIF Tools Manually

Download CIF files for all extracted materials:

```powershell
python cif_file_finder.py --input data/extracted/adsorption_data.json
```

Search one manually entered material:

```powershell
python cif_file_finder.py --material "CALF-20"
```

Analyze downloaded CIF files:

```powershell
python cif_file_analyzer.py
```

## Testing

Run offline unit tests:

```powershell
python test.py
```

These tests must not use API keys, Mistral, COD, CCDC, or any network service. Unit tests should use small local inputs and mocked clients so they are deterministic and cheap to run.

Good unit-test inputs for this project:

- short text snippets that contain DOI, title, year, material, gas, surface area, pore volume, and pore size;
- small in-memory adsorption rows or temporary JSON/CSV files;
- tiny synthetic CIF strings for valid, invalid, matching, and wrong-material cases;
- temporary output folders for report-writing tests;
- mocked Mistral/OCR/CIF-search clients for external API behavior.

Keep live API tests separate as manual integration tests. Integration tests need real PDFs, a `.env` file with `MISTRAL_API_KEY`, network access, and enough API quota.

## Quality Checklist

- Use `runner.py` as the normal project entrypoint.
- Keep unit tests offline and deterministic.
- Mock external services in tests.
- Keep API keys in `.env`, never in source code.
- Prefer `data/extracted/adsorption_data.json` for downstream processing to avoid locked Excel files.
- Commit source code, tests, README, requirements, and small fixtures only.
- Do not commit generated outputs, `.env`, `__pycache__/`, or large downloaded datasets.
