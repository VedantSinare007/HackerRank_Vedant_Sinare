# Deletion audit agent

## Approach

This is a deterministic evidence-driven agent. It resolves the request email through the current identity snapshot and historical identity changes, then evaluates only evidence captured at or before each case's audit time. It inspects JSON snapshots, SQLite-compatible SQL exports, structured logs, PDFs, and screenshots. Explicit identity-catalog links from the activity stream can associate an evidence resource with the user; operational success/failure fields are not treated as proof of current state.

Policy findings and follow-up steps are generated from the required treatment for each data category. The agent preserves required audit and legal-hold records, retains backups while blocking restore access, and orders findings, remediation, and verification using the challenge's operation order.

## Run locally

From the repository root, place the challenge corpus in dataset/ and run:

```bash
python code/main.py --dataset dataset --output output.csv
python code/evaluation/main.py --dataset dataset --predictions output.csv
```

Python 3.10+ is required. Core processing uses only the standard library. To inspect image evidence, install Pillow, pytesseract, and the Tesseract OCR executable; PDF extraction uses pdftotext when present and falls back to pypdf.

## GitHub workflow

The workflow fetches the public participant-facing dataset into a temporary runner directory, generates output.csv and the evaluation reports, packages README.md plus code/ into code.zip, and uploads that ZIP as a workflow artifact. Dataset and evidence files are not committed or packaged. The generated CSV and reports are committed back to the repository.

## AI and usage

The final runner uses no hosted model and makes no paid inference calls. It uses deterministic structured retrieval, policy rules, and OCR for raster evidence. The usage report records zero model tokens and estimated model cost.
