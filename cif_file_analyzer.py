"""Backward-compatible entry point; all CIF-analysis logic lives in pyads.cif_analyzer.

Run CIF analysis with:
    python cif_file_analyzer.py --cif-dir cif_file/

Or use the installed console script:
    pyads-cif-analyze --cif-dir cif_file/
"""

from pyads.cif_analyzer import main

if __name__ == "__main__":
    main()
