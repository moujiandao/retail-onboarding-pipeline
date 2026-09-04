# Retail Onboarding Pipeline

This repository is a reference implementation for extracting and staging grocery-retailer data from CSV files, vendor invoices, and receipt images.

It focuses on the messy boundary between source files and a warehouse: inconsistent encodings, changing delimiters, semi-structured PDFs, OCR confidence, cloud configuration, and recoverable failures. It is a practice project, not a deployed production pipeline.

## Implemented

- CSV extraction with encoding and delimiter detection.
- Header normalization and source-file metadata attached to extracted frames.
- PDF invoice extraction using table detection with a text-pattern fallback.
- Receipt OCR with image preprocessing and confidence scoring.
- Staging output in Parquet, text, and JSON formats.
- Quarantine paths for files that cannot be parsed or fall below the OCR confidence threshold.
- Synthetic generators for product catalogs, price changes, invoices, and receipt images.
- S3 upload utilities with partitioned object keys and checksum metadata.
- Snowflake loading utilities built around staging tables and `MERGE` operations.
- Environment-based configuration with explicit validation for optional cloud services.

## Current flow

```text
Synthetic or local source files
    |
    +-- CSV extractor
    +-- PDF invoice extractor
    +-- receipt OCR extractor
    |
    +-- successful records -> data/staging/
    +-- failed records     -> data/quarantine/
                              + error metadata

Optional cloud loaders
    +-- raw or staged files -> Amazon S3
    +-- staged data         -> Snowflake
```

The extraction runner processes independent files and records failures without stopping the entire batch.

## Local setup

Requirements:

- Python 3.10+
- Tesseract when processing receipt images

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Tesseract installation examples:

```bash
# macOS
brew install tesseract

# Ubuntu or Debian
sudo apt-get install tesseract-ocr
```

AWS and Snowflake configuration is optional for local extraction work. Keep credentials in `.env`, which is excluded from Git.

## Generate synthetic input

```bash
python scripts/generate_all_data.py
```

The generators create related product, price, invoice, and receipt fixtures under `data/raw/`. Use the individual `generate_*.py` scripts when a smaller dataset is enough.

## Run extraction

```bash
# Inspect inputs without writing staged output
python scripts/run_extraction.py --dry-run

# Write successful output and quarantine failures
python scripts/run_extraction.py
```

Generated source and staging data are excluded from version control.

## Verification

```bash
pytest tests/
ruff check src/ tests/ scripts/
ruff format --check src/ tests/ scripts/
```

The current tests exercise configuration behavior and the CSV extractor, including encoding, delimiter, schema, and malformed-input cases.
The suite currently has four known CSV-extractor failures around numeric coercion, Latin-1 detection, and trailing punctuation in normalized column names. Ruff also reports existing formatting and lint debt. The commands above define the cleanup gate for the next implementation pass.

## Technology

- Python and pandas
- pdfplumber and PyPDF2
- Tesseract and Pillow
- Boto3
- Snowflake Connector for Python
- pytest and Ruff

## Current limitations

- The repository does not yet contain the documented dbt transformation project.
- Great Expectations is listed as a dependency but no expectation suite is implemented.
- There is no complete extraction-to-S3-to-Snowflake orchestration command.
- PDF, OCR, S3, and Snowflake behavior do not yet have the same test coverage as configuration and CSV extraction.
- Cloud loading requires separately provisioned AWS and Snowflake accounts.

These gaps are intentionally stated here rather than represented as finished functionality.
