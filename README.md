# pyads

**pyads** extracts structured adsorption data from scientific PDF papers and
cross-references the results against crystallographic databases.

The four-stage pipeline:

1. **OCR** — upload PDFs to the Mistral OCR API; save extracted text to `data/text/`.
2. **Extraction** — send OCR text to a Mistral LLM; parse adsorption properties into a validated JSON schema.
3. **CIF download** — query the Crystallography Open Database (COD) for each material; download matching CIF files.
4. **CIF analysis** — parse CIF files with gemmi and pymatgen; simulate XRD patterns; score material-name matches.

---

## Installation

```powershell
# Clone and enter the repository
cd pyadsorp

# Create a virtual environment (Python 3.11+)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install the package and its dependencies
python -m pip install -e .
```

---

## Configuration

Copy `.env.example` to `.env` and set your Mistral API key:

```text
MISTRAL_API_KEY=your_mistral_api_key_here
```

All other settings have working defaults and can be overridden:

| Variable | Default | Description |
|---|---|---|
| `PDF_DIR` | `data/pdfs` | Input PDFs for OCR |
| `TEXT_DIR` | `data/text` | OCR output (one `.txt` per PDF) |
| `EXTRACTION_DIR` | `data/extracted` | JSON/Excel extraction output |
| `EXTRACTION_MODEL` | `mistral-small-latest` | Mistral chat model |
| `EXTRACTION_MAX_CHARS` | `30000` | Max characters sent to LLM per file |
| `VALIDATION_MAX_CHARS` | `20000` | Max evidence chars in validation pass |
| `LOG_LEVEL` | `INFO` | Python logging level |

---

## Running the pipeline

Place PDF files in `data/pdfs/` or `PDF/`, then:

```powershell
# Full pipeline
python runner.py

# Skip stages you have already completed
python runner.py --skip-ocr
python runner.py --skip-ocr --skip-extraction

# Dry run: list PDFs without calling any API
python runner.py --dry-run

# Run only the strict LLM validation pass on existing output
python -m pyads.extractor --validate-existing data/extracted/adsorption_data.json
```

If installed as a package, the `pyads` console script is also available:

```powershell
pyads --skip-ocr --second-pass
```

---

## Output files

| File | Format | Description |
|---|---|---|
| `data/text/<stem>.txt` | Plain text | OCR text extracted from each PDF |
| `data/extracted/adsorption_data.json` | JSON | One record per paper (see schema below) |
| `data/extracted/adsorption_data.xlsx` | Excel | Flat table, one row per paper |
| `data/extracted/usage_summary.json` | JSON | Mistral token usage per stage |
| `cif_file/<material>.cif` | CIF | Downloaded crystal structure files |
| `cif_file/cif_download_report.csv` | CSV | Download status per material |
| `cif_file/cif_analysis_report.csv` | CSV | Structural analysis and match scores |
| `cif_file/xrd_patterns/<stem>_xrd.csv` | CSV | Simulated XRD pattern (2θ, intensity, hkl) |

---

## JSON schema

Each record in `adsorption_data.json` follows this schema (schema_version 1):

```json
{
  "schema_version": 1,
  "source_file": "paper_001.txt",
  "doi": "10.1039/d3ta01234a",
  "title": "CO2 capture with ZIF-8 at room temperature",
  "year": 2023,
  "material": "ZIF-8",
  "surface_area": {
    "value": 1200.0,
    "unit": "m2/g"
  },
  "pore_volume": {
    "value": 0.55,
    "unit": "cm3/g"
  },
  "pore_size": {
    "value": 3.4,
    "unit": "Å"
  },
  "gases": ["CO2", "N2"],
  "isotherm_temperatures": [
    {"value": 273, "unit": "K"},
    {"value": 298, "unit": "K"}
  ]
}
```

**Field notes:**

- `surface_area` — BET surface area only; unit must be an area-per-mass unit (m²/g, m2/g).
- `pore_volume` — total pore volume; unit must be cm³/g, cm3/g, or cc/g.
- `pore_size` — characteristic pore diameter or width; unit is typically nm or Å.
- `gases` — list of all adsorptive gases mentioned (CO2, N2, H2, CH4, …).
- `isotherm_temperatures` — all temperatures at which isotherms were measured, not synthesis temperatures.
- Null values indicate the property was not found in the paper; they are never guessed.

---

## Worked example

### 1. Prepare input

```powershell
# Create the input folder and drop in a PDF
New-Item -ItemType Directory -Force data/pdfs
Copy-Item my_mof_paper.pdf data/pdfs/
```

### 2. Run OCR only (saves API cost when iterating on extraction)

```powershell
python runner.py --skip-extraction --skip-cif-download --skip-cif-analysis
# → writes data/text/my_mof_paper.txt
```

### 3. Extract adsorption data with two-pass validation

```powershell
python runner.py --skip-ocr --skip-cif-download --skip-cif-analysis --second-pass
# → writes data/extracted/adsorption_data.json
# → writes data/extracted/adsorption_data.xlsx
```

### 4. Download CIF files for extracted materials

```powershell
python runner.py --skip-ocr --skip-extraction
# → writes cif_file/<material>.cif
# → writes cif_file/cif_download_report.csv
```

### 5. Analyse CIF files

```powershell
python runner.py --skip-ocr --skip-extraction --skip-cif-download
# → writes cif_file/cif_analysis_report.csv
# → writes cif_file/xrd_patterns/<material>_xrd.csv
```

### 6. Programmatic use

```python
from pyads.extractor import process_text_files

records, outputs, usage = process_text_files(
    text_dir="data/text",
    output_dir="data/extracted",
    second_pass=True,
)
print(f"Extracted {len(records)} records → {outputs['json']}")
```

See `examples/extract_demo.py` for a complete offline demonstration using a
pre-saved OCR text file.

---

## Running the tests

```powershell
python test.py
```

All tests are offline (no Mistral or COD network calls). The Mistral client is
mocked using `unittest.mock`.

---

## Lint and code quality

```powershell
pylint pyads/
pycodestyle pyads/
pydocstyle pyads/
```

---

## Python version

Python 3.11 or newer is required (see `pyproject.toml`).
