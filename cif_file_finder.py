"""Backward-compatible entry point; all CIF-finder logic lives in pyads.cif_finder.

Run CIF search with:
    python cif_file_finder.py --material "ZIF-8"

Or use the installed console script:
    pyads-cif-find --material "ZIF-8"
"""

from pyads.cif_finder import main

if __name__ == "__main__":
    main()
