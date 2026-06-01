# Changelog

All notable changes to **pyads** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.1.0] — 2026-06-01

### Added
- **Known-materials validator** (`pyads/known_materials.py`): cross-checks
  extracted BET surface area, pore volume, and pore size against literature
  ranges for 20 common MOFs, COFs, and zeolites.  Integrated into the agentic
  loop to flag physically implausible extractions that pass two-pass confidence
  scoring.
- **`--agentic` CLI flag** in `runner.py`: exposes the adaptive extraction loop
  (observe → reason → act with targeted third query) to end users without
  writing Python.
- **`pyads/agent.py`**: agentic extraction loop with cost-conscious targeted
  retry for low-confidence numeric fields (surface area, pore volume, pore size).
- **`RESULTS.md`**: verified end-to-end pipeline output on three published papers
  (ZIF-8, HKUST-1, MOF-5/IRMOF-1).
- **Extraction confidence scoring** (`pyads/confidence.py`): per-field and
  overall confidence labels (`high` / `medium` / `low` / `absent`).
- **CI pipeline** (`.github/workflows/ci.yml`): runs the full offline test suite
  on every push.
- **Sample data** (`data/samples/`): realistic pipeline output for a ZIF-8 paper,
  useful for understanding output formats without a Mistral API key.
- **Console scripts**: `pyads`, `pyads-extract`, `pyads-cif-find`,
  `pyads-cif-analyze` registered in `pyproject.toml`.
- **`examples/`**: `demo.ipynb` Jupyter notebook and `extract_demo.py` offline
  script demonstrating extraction without a live API call.
- **`DESIGN.md`**: full rationale for every architectural decision.

### Changed
- Consolidated all logic into the `pyads/` package; root-level scripts
  (`runner.py`, `extractor.py`, `cif_file_finder.py`, `cif_file_analyzer.py`)
  are now thin entry-point wrappers.
- Removed `cli.py` (redundant alias for `runner.py`; use `python runner.py`
  or the `pyads` console script instead).
- `quality_check.py` now lints root-level scripts in addition to `pyads/`.

### Fixed
- Wildcard imports (`from pyads.* import *`) removed from root-level scripts.
- `pyads/__main__.py` import corrected to `from pyads.runner import main`
  (works when package is installed, not just run from the repo root).
