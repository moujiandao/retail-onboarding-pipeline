# Retail Onboarding Pipeline

Production data pipeline for onboarding new grocery retailers onto the platform. Processes vendor invoices, transaction receipts, and product catalogs from heterogeneous source systems into a unified Snowflake data warehouse.

## Overview

This pipeline handles the data engineering workflow for bringing new grocery retail customers online. It processes:

- **PDF invoices** from multiple vendor formats (EDI, handwritten, scanned)
- **Transaction receipts** (including OCR for scanned/photographed receipts)
- **Product catalogs** (CSV exports from legacy POS systems)
- **Price change logs** with temporal reconciliation

The system is designed for data quality and auditability, with immutable raw data storage, comprehensive validation, and detailed lineage tracking.

## Architecture

**ELT Pattern**: Extract → Load → Transform (in warehouse)

```
┌─────────────────────────────────────────────┐
│         Source Systems (Raw Files)          │
│   PDF Invoices | Scanned Receipts | CSVs    │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│         Python Extractors (src/extractors)   │
│   • pdfplumber (structured PDF tables)       │
│   • pytesseract (OCR for scanned images)     │
│   • pandas (CSV with encoding detection)     │
│                                               │
│   Output: Raw DataFrames (minimal parsing)   │
└──────────────────┬───────────────────────────┘
                   │
                   ├─────────────────┐
                   │                 │
                   ▼                 ▼
         ┌─────────────────┐  ┌──────────────┐
         │   S3 Archival   │  │  Snowflake   │
         │   (Raw Files)   │  │  RAW Schema  │
         └─────────────────┘  └──────┬───────┘
                                     │
                                     │ All transformations
                                     │ happen here ↓
                                     │
                         ┌───────────▼──────────────┐
                         │   dbt (SQL-based)        │
                         │                          │
                         │  STAGING schema:         │
                         │  • Rename columns        │
                         │  • Cast types            │
                         │  • Add surrogate keys    │
                         │                          │
                         │  ANALYTICS schema:       │
                         │  • dim_vendor            │
                         │  • dim_product           │
                         │  • dim_date              │
                         │  • fact_invoice_line     │
                         │  • fact_receipt_line     │
                         │  • fact_reconciliation   │
                         │                          │
                         │  + Built-in tests        │
                         │  + Lineage tracking      │
                         └──────────────────────────┘
```

**Why This Architecture?**

1. **Python for I/O only**: Extract from files, load to warehouse. No business logic.
2. **SQL for transformations**: dbt runs in Snowflake where data already lives (faster, more scalable)
3. **Clear separation**: Data engineers write SQL, not complex pandas code
4. **Testable**: dbt has built-in testing, Great Expectations validates at each layer

## Project Structure

```
retail-onboarding-pipeline/
│
├── data/
│   ├── raw/                    # Immutable source data
│   │   ├── invoices/
│   │   ├── receipts/
│   │   └── item_master/
│   ├── staging/                # Intermediate processing
│   └── processed/              # Validated output
│
├── src/
│   ├── extractors/             # Parse source files → DataFrames
│   ├── loaders/                # Load DataFrames → Snowflake/S3
│   └── utils/                  # Config, logging, helpers
│
├── dbt/                        # Data transformation models
│   ├── models/
│   │   ├── staging/           # 1:1 source models
│   │   └── marts/             # Business logic layer
│   └── tests/                 # Data quality tests
│
├── scripts/                    # Pipeline orchestration
│   ├── generate_*.py          # Mock data generators
│   ├── run_extraction.py      # Extraction orchestrator
│   └── run_pipeline.py        # Full pipeline runner
│
└── tests/
    ├── unit/                  # Component tests
    ├── integration/           # End-to-end tests
    └── fixtures/              # Test data
```

### Why This Structure?

**Raw/Staging/Processed Separation**: Raw data is immutable—never modified after ingestion. This enables:
- Re-running transformations from scratch when logic changes
- Comparing processed output against original source for debugging
- Maintaining audit trail for compliance

**ELT Over ETL**: We load raw data into Snowflake first, then transform it with SQL/dbt. Why?
- **Performance**: Transform where data lives (in the warehouse, not Python)
- **Scalability**: Snowflake can process billions of rows; pandas struggles at millions
- **Maintainability**: SQL transformations are easier to review and test than pandas code
- **Collaboration**: Analysts understand SQL; not everyone knows pandas

**No `transformers/` Package**: All transformations are in `dbt/models/` (SQL), not Python. Python is only for:
- Reading files that can't be loaded directly (PDFs, OCR)
- Loading data into Snowflake
- Orchestration logic

**Modular Extractors/Loaders**: Each is independently testable. Swapping implementations (e.g., S3 → GCS) requires changing one module.

## Quick Start

```bash
# Clone and setup
git clone <repository-url>
cd retail-onboarding-pipeline

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Snowflake/AWS credentials

# Verify installation
pytest tests/ -v
```

### System Requirements

**Python**: 3.10 or higher

**Tesseract OCR** (required for receipt processing):
```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr

# Windows
# Download from: https://github.com/UB-Mannheim/tesseract/wiki
```

## Usage

### Generate Mock Data (Development)

```bash
# Generate synthetic grocery data for testing
python scripts/generate_item_master.py
python scripts/generate_invoices.py
python scripts/generate_receipts.py
```

### Run Extraction Pipeline

```bash
# Extract from raw files to staging
python scripts/run_extraction.py

# With date filter
python scripts/run_extraction.py --start-date 2024-01-01 --end-date 2024-01-31

# Dry run (validate without writing)
python scripts/run_extraction.py --dry-run
```

### Run Full Pipeline

```bash
# Extract → S3 Upload → Snowflake Load → dbt Transform
python scripts/run_pipeline.py

# With verbose logging
python scripts/run_pipeline.py --log-level DEBUG
```

### dbt Operations

```bash
cd dbt/

# Run transformations
dbt run

# Run tests
dbt test

# Generate documentation
dbt docs generate
dbt docs serve
```

## Data Quality

### Validation Strategy

The pipeline implements multi-layered validation:

1. **Extraction Layer**: File format validation, encoding detection
2. **Great Expectations**: Schema validation, statistical profiling
3. **dbt Tests**: Business rule validation, referential integrity
4. **Reconciliation**: Invoice-to-receipt matching, variance detection

### Quarantine Pattern

Failed records are quarantined rather than discarded:

```
data/
├── processed/
│   └── invoices/2024-01-15_success.parquet
└── quarantine/
    └── invoices/2024-01-15_failed.parquet  # Includes error metadata
```

This enables:
- Manual review of failures
- Re-processing after bug fixes
- Quality metrics tracking over time

## Data Model

### Star Schema (dbt marts)

```
fact_invoice_line ─┬─→ dim_vendor
                   ├─→ dim_product
                   └─→ dim_date

fact_receipt_line ─┬─→ dim_store
                   ├─→ dim_product
                   └─→ dim_date

fact_reconciliation ─→ Matches invoices to receipts
```

### Key Tables

| Table | Type | Description |
|-------|------|-------------|
| `dim_vendor` | Dimension | Vendor master (SCD Type 1) |
| `dim_product` | Dimension | Product catalog with pricing |
| `dim_date` | Dimension | Date dimension for time-series |
| `fact_invoice_line` | Fact | Invoice line items |
| `fact_receipt_line` | Fact | Transaction line items |
| `fact_reconciliation` | Fact | Invoice-receipt matching |

## Configuration

All configuration via environment variables (12-factor app principle):

| Variable | Required | Description |
|----------|----------|-------------|
| `SNOWFLAKE_ACCOUNT` | Yes* | Snowflake account identifier |
| `SNOWFLAKE_USER` | Yes* | Database user |
| `SNOWFLAKE_PASSWORD` | Yes* | Database password |
| `AWS_ACCESS_KEY_ID` | Yes* | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | Yes* | AWS secret key |
| `S3_BUCKET` | Yes* | S3 bucket for data storage |
| `LOG_LEVEL` | No | Logging verbosity (default: INFO) |
| `DATA_DIR` | No | Data directory (default: ./data) |

\* Required for production; optional for local development with mock data

See `.env.example` for full configuration options.

## Development

### Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only (fast)
pytest tests/unit/ -v

# With coverage
pytest tests/ --cov=src --cov-report=html

# Specific test file
pytest tests/unit/test_config.py -v
```

### Code Quality

```bash
# Lint code
ruff check src/ tests/

# Auto-fix issues
ruff check src/ tests/ --fix

# Format code
ruff format src/ tests/
```

## Deployment

### Snowflake Setup

```bash
# Create warehouse, database, schemas
python scripts/run_snowflake_setup.py
```

This creates:
- Database: `RETAIL_ONBOARDING`
- Schemas: `RAW`, `STAGING`, `ANALYTICS`
- Tables: Invoice, receipt, and item tables
- Metadata: Load history tracking

### Production Considerations

1. **Idempotency**: All operations are idempotent. Re-running doesn't create duplicates.
2. **Incremental Loading**: Use `--start-date` and `--end-date` to process date ranges.
3. **Error Handling**: Failed records are quarantined, not dropped.
4. **Monitoring**: Pipeline logs include row counts, timing, and error rates.

## Troubleshooting

### Common Issues

**Tesseract not found**:
```bash
# Verify installation
tesseract --version

# If not in PATH, set TESSERACT_CMD in .env
TESSERACT_CMD=/path/to/tesseract
```

**Encoding errors in CSV parsing**:
- The pipeline auto-detects encoding using `chardet`
- If detection fails, files are quarantined with error details
- Check `data/quarantine/` for failed files

**Snowflake connection timeout**:
- Verify credentials in `.env`
- Check network connectivity and firewall rules
- Ensure Snowflake account is active

## Performance

Current scale (tested):
- ~10,000 product SKUs
- ~100 invoices/month
- ~1,500 receipts/month
- Pipeline runtime: ~5-10 minutes end-to-end

For 10x+ scale, consider:
- Parallel processing (Python multiprocessing or Dask)
- Incremental loading (process only changed files)
- Warehouse optimization (clustering keys, materialized views)

## License

MIT License - See LICENSE file for details
