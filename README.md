# Mistral PDF Reader

## Steps to run

1. Open a terminal in this folder:

```powershell
cd mistral_PDF_reader
```

2. Create and activate an environment.

Conda option:

```powershell
conda env create -f environment.yml
conda activate pyads-env
```

Or venv option:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

3. Create `.env` from `.env.example` and set your API key:

```text
MISTRAL_API_KEY=your_mistral_api_key_here
```

4. Put your PDF files in either `data/pdfs/` or `PDF/`.

5. Run:

```powershell
pyads
```

(Equivalent: `python runner.py`)

## Python version note

- Recommended: Python 3.11 (stable and broadly compatible).
- `pyproject.toml` now requires Python `>=3.11`.
- If you currently use Python 3.10, create a new environment with 3.11 and run `python -m pip install -e .`.
