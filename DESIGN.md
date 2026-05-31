# pyads — Design Decisions

This document explains the reasoning behind the key design choices in pyads.
It is intended for contributors and evaluators who want to understand *why*
the code is structured the way it is, not just *what* it does.

---

## Why two-pass LLM extraction?

The single biggest source of error in automated extraction of adsorption data
is **unit confusion**.  Scientific papers report BET surface area in m²/g,
pore volume in cm³/g, and pore size in nm or Å, but these units often appear
close together in the text.  A single LLM pass frequently assigns a pore
volume value (e.g. 0.55 cm³/g) to the `surface_area` field, or reports an
isotherm measurement temperature when it should report a synthesis temperature.

The two-pass approach addresses this directly:

1. **First pass** — broad extraction from the full OCR text.  Asks the model
   to extract everything it can find.
2. **Second (validation) pass** — a stricter prompt that re-reads the relevant
   evidence and applies explicit domain rules:
   - `surface_area` must have an area-per-mass unit (m²/g, m^2/g, m²/g).
     If the extracted value has a volume unit (cm³/g), it is wrong and must
     be set to null.
   - `pore_volume` must have a volume-per-mass unit (cm³/g, cc/g).
   - Isotherm temperatures (77 K, 87 K, 195 K, 273 K, 298 K) are adsorption
     measurement conditions.  Synthesis temperatures (400 °C, 150 °C) are not.

The `confidence` field records whether the two passes agreed.  A `"low"`
confidence on `surface_area` almost always means the first pass got the unit
wrong, which the validation pass then corrected.  This gives users a reliable
signal for which records need manual checking before use in downstream work.

---

## Why the Crystallography Open Database (COD)?

The two most comprehensive crystal structure databases are:
- **CCDC** (Cambridge Crystallographic Data Centre) — requires a commercial
  licence (~$3,000/year for academic use).
- **ICSD** (Inorganic Crystal Structure Database) — requires a licence.
- **COD** (Crystallography Open Database) — fully open-access, no API key,
  JSON REST API, >500,000 structures.

For a research tool aimed at the scientific community, COD is the only
practical choice.  It covers the MOF, COF, and zeolite structures that appear
most frequently in the adsorption literature.  The COD REST endpoint returns
structured JSON (title, chemical name, formula, journal) which is used both
for downloading the CIF and for the material-name match scoring.

---

## Why three CIF analysis libraries (gemmi + pymatgen + ase)?

Each library has different failure modes on real-world CIF files:

- **gemmi** — fast, strict CIF parser; handles malformed symmetry blocks and
  CIF 2.0 syntax.  Used for cell parameters, space group, and atom site count.
- **pymatgen** — full crystallographic analysis; computes composition, density,
  space group number, crystal system, and simulated XRD patterns.  Fails on
  some CIF files with unusual atom-site loop conventions.
- **ase** — secondary read check; confirms the structure is geometrically
  sensible.  Returns the chemical formula independently of pymatgen.

Using all three means a CIF that causes one library to fail is still analysed
by the others.  The `make_error_row` function captures per-CIF failures so
the analysis report is always complete, even when individual files are
malformed.

---

## Why token overlap + sequence similarity for material matching?

Matching a requested material name (e.g. "ZIF-8") against a COD CIF file
requires handling common surface variations:
- Abbreviations vs full names: "ZIF-8" vs "zeolitic imidazolate framework-8"
- Hyphenation: "HKUST-1" vs "HKUST 1"
- Formula order: "Zn4C16H32N32" vs "C16H32N32Zn4"

Pure string equality fails on all of these.  The approach used:
1. **Token overlap** — split both strings into alphanumeric tokens of length
   ≥ 3, remove stop words (the, and, framework, mof, …), compute Jaccard
   overlap.  Handles abbreviation expansion.
2. **Sequence similarity** — `difflib.SequenceMatcher` ratio on normalized
   strings.  Handles minor spelling and spacing variations.
3. **Exact substring** — normalized material name is a substring of the
   combined CIF metadata.  Catches direct name matches despite surrounding text.

The `GENERIC_MATERIAL_NAMES` list explicitly rejects names like "MOF",
"material", "covalent organic framework" that are too broad to trust as a
unique CIF identifier.

---

## Why schema_version?

The `adsorption_data.json` output is intended to be consumed by downstream
tools (databases, visualisation scripts, ML models).  Without a version
field, any future change to the schema (adding a field, renaming a unit) is
invisible to consumers and can cause silent data corruption.

`"schema_version": 1` is added automatically by `_empty_record()` and is
preserved through both extraction passes.  When the schema changes, the
version number will be incremented and a migration note added here.

---

## Why separate pyads/confidence.py?

Confidence scoring is a self-contained computation that does not call any API
and has no side effects.  Keeping it in its own module means:
- It can be tested exhaustively without mocking (17 pure-function tests).
- It can be imported and used independently of the rest of the pipeline.
- The logic is easy to audit and modify without touching the extraction code.

---

## Pipeline data flow

```
PDF files (data/pdfs/)
    │
    ▼  [pyads.ocr]  Mistral OCR API
OCR text files (data/text/*.txt)
    │
    ▼  [pyads.extractor]  Mistral LLM, two-pass extraction + confidence scoring
adsorption_data.json  ←── schema_version, per-record confidence field
adsorption_data.xlsx
usage_summary.json
    │
    ▼  [pyads.cif_finder]  COD REST API, retry with backoff
CIF files (cif_file/*.cif)
cif_download_report.csv
    │
    ▼  [pyads.cif_analyzer]  gemmi + pymatgen + ase
cif_analysis_report.csv
xrd_patterns/*_xrd.csv
```

Each stage reads only from the output of the previous stage and writes to a
documented location.  All paths are configurable via CLI flags or environment
variables; the defaults in `pyads/config.py` assume the standard repo layout.
