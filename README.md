# pyads

**pyads** extracts structured adsorption data from scientific PDF papers and
cross-references the results against crystallographic databases.

> **Domain**: porous materials science — MOFs, COFs, zeolites, and activated
> carbons.  The tool extracts BET surface area, pore volume, pore size, gas
> adsorbates, and isotherm temperatures from peer-reviewed papers.  Basic
> familiarity with adsorption science is helpful for interpreting the output.

The four-stage pipeline:

1. **OCR** — upload PDFs to the Mistral OCR API; save extracted text to `data/text/`.
2. **Extraction** — send OCR text to a Mistral LLM; parse adsorption properties into a validated JSON schema.
3. **CIF download** — query the Crystallography Open Database (COD) for each material; download matching CIF files.
4. **CIF analysis** — parse CIF files with gemmi and pymatgen; simulate XRD patterns; score material-name matches.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | Required by `pyproject.toml` |
| Mistral API key | Free tier available at [console.mistral.ai](https://console.mistral.ai) |
| Internet access | OCR upload and COD CIF download stages need network access |
| ~2 GB disk | pymatgen + ase are large scientific packages |

The test suite and `--dry-run` mode work **without** a Mistral API key.

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

## Entry points

| Command | Description |
|---|---|
| `python runner.py` | Full pipeline (recommended for most users) |
| `pyads` | Same as above, requires `pip install -e .` |
| `pyads-extract` | Extraction stage only |
| `pyads-cif-find` | CIF download stage only |
| `pyads-cif-analyze` | CIF analysis stage only |
| `pyads-benchmark` | Compare extraction output against ground truth |

Root-level scripts (`runner.py`, `extractor.py`, `cif_file_finder.py`,
`cif_file_analyzer.py`) are thin wrappers around the `pyads` package.
All logic lives in `pyads/`.

---

## Running the pipeline

Place PDF files in `data/pdfs/`, then:

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

Each paper in `adsorption_data.json` follows schema version 2.  A paper
carries its own DOI/title/year and a **`materials` list** so that studies
comparing multiple sorbents produce one record per material, not one record
per paper.

```json
{
  "schema_version": 2,
  "source_file": "paper_001.txt",
  "doi": "10.1039/d3ta01234a",
  "title": "CO2 and N2 adsorption on ZIF-8 and HKUST-1",
  "year": 2023,
  "materials": [
    {
      "material": "ZIF-8",
      "surface_area": {"value": 1630.0, "unit": "m2/g"},
      "pore_volume":  {"value": 0.636,  "unit": "cm3/g"},
      "pore_size":    {"value": 11.6,   "unit": "Å"},
      "gases": ["CO2", "N2"],
      "isotherm_temperatures": [
        {"value": 273, "unit": "K"},
        {"value": 298, "unit": "K"}
      ],
      "confidence": {
        "overall": "high",
        "fields": {
          "material": "high", "surface_area": "high",
          "pore_volume": "high", "pore_size": "high",
          "gases": "high", "isotherm_temperatures": "high"
        }
      }
    },
    {
      "material": "HKUST-1",
      "surface_area": {"value": 1507.0, "unit": "m2/g"},
      "pore_volume":  {"value": 0.75,   "unit": "cm3/g"},
      "pore_size":    {"value": null,   "unit": null},
      "gases": ["H2"],
      "isotherm_temperatures": [{"value": 77, "unit": "K"}],
      "confidence": {"overall": "high", "fields": {}}
    }
  ]
}
```

**Field notes:**

- `materials` — list of all distinct materials studied in the paper.  Most papers have 1–5 entries.
- `surface_area` — BET surface area only; unit must be an area-per-mass unit (m²/g, m2/g).
- `pore_volume` — total pore volume; unit must be cm³/g, cm3/g, or cc/g.
- `pore_size` — characteristic pore diameter or width; unit is typically nm or Å.
- `gases` — list of all adsorptive gases mentioned (CO2, N2, H2, CH4, …).
- `isotherm_temperatures` — all temperatures at which isotherms were measured, not synthesis temperatures.
- `confidence` — per-material; levels are `"high"`, `"medium"`, `"low"`, `"absent"`.
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
pre-saved OCR text file, and `examples/pipeline_demo.ipynb` for a step-by-step
Jupyter notebook that walks through extraction, confidence scoring, and benchmark
evaluation — all offline, no API key required.

---

## Agentic mode

The `--agentic` flag enables a third LLM query when numeric fields are
low-confidence or fall outside known literature ranges:

```powershell
python runner.py --skip-ocr --agentic
```

The agentic loop (observe → reason → act) fires at most once per record and
only when needed, so it adds no cost to well-extracted papers.

---

## Running the tests

```powershell
python test.py
```

All tests are offline (no Mistral or COD network calls). The Mistral client is
mocked using `unittest.mock`.  The suite covers: extractor, agent, confidence,
known_materials, OCR, CIF finder, CIF analyzer, and runner.

---

## Lint and code quality

```powershell
# Run all three tools at once (covers pyads/ + root-level scripts)
python quality_check.py

# Or individually
pylint pyads/
pycodestyle pyads/
pydocstyle pyads/
```

The project maintains **pylint 10/10**, zero pycodestyle violations, and zero
pydocstyle violations.  Configuration is in `.pylintrc` and `setup.cfg`.

---

## Troubleshooting

**`MISTRAL_API_KEY not set`**
Copy `.env.example` to `.env` and add your key.  Get a free key at
[console.mistral.ai](https://console.mistral.ai).

**`No PDF files found in data/pdfs`**
Create the directory and copy your PDFs: `New-Item -ItemType Directory -Force data/pdfs`

**`ModuleNotFoundError: No module named 'gemmi'` (or pymatgen/ase)**
Run `python -m pip install -e .` from the repo root to install all dependencies.
On Windows, use the conda environment from `environment.yml` if pip install fails.

**Mistral 429 rate-limit errors**
The extraction module retries automatically with backoff.  If you hit persistent
limits, reduce throughput with `--limit 1` and re-run for remaining files.

**`No CIF found in COD` for a material**
The material name may not match COD's naming conventions.  Try the `--material`
flag with an alternative name: `pyads-cif-find --material "Zinc imidazolate framework"`

**Low confidence scores across all fields**
The OCR text may be too short or the paper may not contain adsorption data.
Check `data/text/<stem>.txt` to verify the OCR output quality.

---

## Extraction confidence

Every record in `adsorption_data.json` includes a `confidence` key produced
by comparing the first LLM pass against the second (validation) pass:

```json
"confidence": {
  "overall": "high",
  "fields": {
    "doi": "high",
    "material": "high",
    "surface_area": "low",
    "pore_volume": "high",
    ...
  }
}
```

**Confidence levels:**
- `"high"` — both passes agreed on the same non-null value.
- `"medium"` — the validation pass *added* a value the first pass missed.
- `"low"` — the passes disagreed (value or unit changed, or one rejected the other's result).
- `"absent"` — the field was not found in the paper (null in both passes).

If `surface_area` is `"low"`, it usually means the first pass extracted a
value with the wrong unit (e.g. cm³/g instead of m²/g) and the validation
pass rejected it.  Use this to prioritise manual review.

---

## Sample data

`data/samples/` contains realistic pipeline output for a ZIF-8 CO₂ adsorption
paper, useful for understanding the output format without running the full pipeline:

| File | Description |
|---|---|
| `sample_ocr.txt` | Simulated OCR text from a scientific paper |
| `sample_adsorption_data.json` | Extracted record with confidence scores |
| `sample_cif_download_report.csv` | COD download result for ZIF-8 |
| `sample_cif_analysis_report.csv` | gemmi + pymatgen analysis of the CIF |

---

## Architecture notes

Key design decisions and the reasoning behind them:

**Two-pass extraction with strict validation.**
A single LLM call frequently confuses units (e.g. puts total pore volume in
the `surface_area` field).  A second "correction" prompt that re-reads the
evidence and applies explicit unit rules catches these errors.  The
`confidence` field records whether the two passes agreed, giving users a
reliable signal for which records need checking.

**COD as the CIF source.**
The Crystallography Open Database is fully open-access with a JSON REST API,
no API key, and machine-readable results.  CCDC and ICSD require licences.
COD covers >500,000 structures and is sufficient for MOF/COF literature.

**Three-library CIF analysis (gemmi + pymatgen + ase).**
Each library has different failure modes on real-world CIF files.  gemmi
validates syntax and extracts cell parameters; pymatgen computes composition,
density, space group, and XRD patterns; ase provides a second read check.
Using all three increases robustness and catches malformed files that pass
one parser but not another.

**Material-name match scoring.**
Downloaded CIFs are scored against the requested material name using token
overlap and sequence similarity rather than exact string matching.  This
handles common variations (e.g. "ZIF-8" vs "Zeolitic imidazolate
framework-8") and rejects generic names ("MOF", "material") that would
produce a meaningless match.

**Schema versioning.**
Every output record carries `"schema_version": 1`.  Downstream consumers
(databases, data pipelines) can use this to detect when the schema changes
and apply the appropriate migration logic.

See [DESIGN.md](DESIGN.md) for the full reasoning behind each decision, and
[RESULTS.md](RESULTS.md) for verified pipeline output on three published papers.

---

## Python version

Python 3.11 or newer is required (see `pyproject.toml`).

---

## Web interface

pyads ships a Streamlit app for point-and-click extraction — no CLI knowledge required.

```powershell
pip install streamlit          # one-time
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

| Tab | What it does |
|---|---|
| **Extract from text** | Paste OCR text, enter your API key, click Extract — results appear with colour-coded confidence badges |
| **Offline demo** | Explore a pre-computed ZIF-8 extraction result; download JSON or CSV — no API key needed |

---

## Benchmark

`pyads` includes a ground-truth evaluation module to measure extraction accuracy.

```powershell
# After running the pipeline, evaluate against the 3-paper ground truth:
python -m pyads.benchmark data/extracted/adsorption_data.json
```

Output (on the verified 3-paper set with ±5% numeric tolerance):

```
Field                  Precision   Recall      F1
------------------------------------------------------------
surface_area            1.000      1.000    1.000
pore_volume             1.000      1.000    1.000
pore_size               1.000      1.000    1.000
material                1.000      1.000    1.000
gases                   1.000      1.000    1.000
```

Ground truth covers **5 papers / 6 material records** including a multi-material entry (Rowsell & Yaghi 2005, which compared HKUST-1 and MOF-177 in the same publication). See [BENCHMARK.md](BENCHMARK.md) for methodology, limitations, and how to add your own ground truth.

---

## Further reading

- [DESIGN.md](DESIGN.md) — rationale for every architectural decision.
- [RESULTS.md](RESULTS.md) — verified pipeline output on three published papers.
- [BENCHMARK.md](BENCHMARK.md) — extraction accuracy metrics and evaluation methodology.
- [examples/pipeline_demo.ipynb](examples/pipeline_demo.ipynb) — Jupyter notebook walkthrough (offline, no API key needed).
- [CHANGELOG.md](CHANGELOG.md) — version history.
- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup, test and lint instructions.
