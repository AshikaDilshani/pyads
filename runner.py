"""Backward-compatible entry point; all pipeline logic lives in pyads.runner.

Run the full pipeline with:
    python runner.py [--skip-ocr] [--skip-extraction] [--skip-cif-download] [--skip-cif-analysis]

Or use the installed console script:
    pyads [options]
"""

from pyads.runner import main

if __name__ == "__main__":
    main()
