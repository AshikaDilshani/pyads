# Contributing to pyads

Thank you for considering a contribution.  This guide covers the development
workflow, code standards, and how to run tests and lint checks locally.

---

## Prerequisites

- Python 3.11 or newer
- A virtual environment (recommended: `python -m venv .venv`)
- A Mistral API key (only required for live-pipeline runs, not for tests)

---

## Development setup

```powershell
# Clone the repository
git clone https://github.com/AshikaDilshani/pyadsorp.git
cd pyadsorp

# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install in editable mode with all dependencies
python -m pip install -e .

# Install lint tools
python -m pip install pylint pycodestyle pydocstyle
```

---

## Running the tests

All tests are fully offline — no Mistral or COD network calls are made.
The Mistral client is replaced with `unittest.mock.MagicMock` throughout.

```powershell
# Run the full test suite
python test.py

# Or with pytest (if installed)
pytest tests/ -v
```

---

## Code quality

pyads enforces **pylint 10/10**, **zero pycodestyle violations**, and
**zero pydocstyle violations** across the entire codebase.

```powershell
# Run all three tools at once
python quality_check.py

# Or individually
pylint pyads/
pycodestyle pyads/
pydocstyle pyads/
```

Configuration lives in `.pylintrc` (pylint) and `setup.cfg`
(pycodestyle + pydocstyle).  Key settings:

| Tool | Setting | Value |
|---|---|---|
| pylint | max-line-length | 120 |
| pylint | max-args | 9 |
| pylint | max-locals | 22 |
| pycodestyle | max-line-length | 120 |
| pydocstyle | convention | PEP257 |

---

## Submitting a pull request

1. Create a feature branch: `git checkout -b feature/my-improvement`
2. Make your changes and add tests for new behaviour.
3. Run `python quality_check.py` and `python test.py` — both must pass cleanly.
4. Open a pull request against `main` with a clear description of what changed
   and why.

---

## Adding a new material to `known_materials.py`

1. Find consensus literature values for BET surface area, pore volume, and
   pore size (use the activated-material values, not as-synthesised).
2. Add an entry to `KNOWN_MATERIAL_PROPERTIES` in `pyads/known_materials.py`
   following the existing format.
3. Add at least one alias (lowercase, no spaces) that covers common
   abbreviations used in the literature.
4. Add a test in `tests/test_known_materials.py` for the new alias and for
   at least one in-range and one out-of-range value.

---

## Reporting issues

Please open a GitHub issue with:
- A minimal reproducible example (OCR text or PDF if possible).
- The full pipeline command you ran.
- The output JSON and any error messages.
