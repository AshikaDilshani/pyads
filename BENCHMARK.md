# pyads — Benchmark

This document describes the benchmark methodology, ground-truth dataset, and
per-field accuracy results for the pyads extraction pipeline.

---

## Ground-truth dataset

Ground-truth values are stored in `data/benchmark/ground_truth.json`.  They
were manually verified against the original publications and match the
end-to-end pipeline output documented in [RESULTS.md](RESULTS.md).

| Paper | Material | BET (m²/g) | Vp (cm³/g) | dp | Gases |
|---|---|---|---|---|---|
| Park et al. (2006) PNAS 103, 10186 | ZIF-8 | 1630 | 0.636 | 11.6 Å | N₂ |
| Rowsell & Yaghi (2005) Angew. Chem. 44, 4670 | HKUST-1 | 1507 | 0.75 | — | H₂ |
| Eddaoudi et al. (2002) Science 295, 469 | MOF-5 | 2900 | 1.04 | 15.1 Å | CH₄ |

The MOF-5 BET value (2900 m²/g) is the **BET** area, not the Langmuir area
(4400 m²/g) also reported in the paper — this is the hardest case in the set
because a naïve extractor conflates them.  The agentic pass was specifically
designed to resolve this class of error.

---

## Evaluation methodology

Papers are matched by DOI.  Materials within a paper are matched by name
(exact case-insensitive first, then substring fallback).

| Field type | Scoring rule |
|---|---|
| Numeric (`surface_area`, `pore_volume`, `pore_size`) | Correct if extracted value is within ±5 % of ground truth |
| String (`material`) | Correct if names match case-insensitively |
| List (`gases`) | Correct if all ground-truth gases appear in the extraction |

Metrics reported: **precision**, **recall**, and **F1** per field, aggregated
across all material records.

- **Precision** = TP / (TP + FP) — of extracted values, how many are correct.
- **Recall** = TP / (TP + FN) — of ground-truth values, how many were found.
- **F1** = harmonic mean of precision and recall.

---

## Results on 3-paper ground truth (two-pass extraction with agentic mode)

```
Benchmark: 3 papers, 3 materials, numeric tolerance ±5%
------------------------------------------------------------
Field                  Precision   Recall      F1
------------------------------------------------------------
surface_area            1.000      1.000    1.000
pore_volume             1.000      1.000    1.000
pore_size               1.000      1.000    1.000
material                1.000      1.000    1.000
gases                   1.000      1.000    1.000
------------------------------------------------------------
```

All five fields score F1 = 1.000.  The hardest case (MOF-5 BET vs Langmuir)
was resolved by the agentic targeted pass, which is reflected in the `"medium"`
confidence score on `surface_area` for that record — see [RESULTS.md](RESULTS.md).

---

## Running the benchmark

```powershell
# Run the full pipeline first to generate adsorption_data.json, then:
python -m pyads.benchmark data/extracted/adsorption_data.json

# Against a custom ground-truth file:
python -m pyads.benchmark data/extracted/adsorption_data.json \
    --ground-truth data/benchmark/ground_truth.json

# Stricter numeric tolerance (2%):
python -m pyads.benchmark data/extracted/adsorption_data.json --tolerance 0.02
```

---

## Limitations and future work

- The ground truth currently covers **3 papers and 3 material records**.  A
  production-grade benchmark should cover 50–100 papers across diverse journals,
  material families (MOFs, COFs, zeolites, activated carbons), and measurement
  conditions.
- **Multi-material papers** (≥ 2 materials per paper) are not yet represented
  in this ground truth, even though schema v2 supports them.  The next step
  is to add at least 5 papers where a novel material is compared against a
  reference (e.g. ZIF-8 as a benchmark sorbent alongside a new MOF).
- **Pore size** remains the most error-prone field in practice: papers routinely
  report cage diameter, window diameter, and BJH mean simultaneously.  A future
  schema extension should allow `pore_size` to be a list of typed values
  (`{"type": "cage", "value": 11.6, "unit": "A"}`).
