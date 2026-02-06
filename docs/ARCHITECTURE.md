# Architecture Overview

This document explains the technical design decisions behind the retail onboarding pipeline, with a focus on the **ELT (Extract-Load-Transform)** pattern and why we use SQL/dbt for transformations instead of Python.

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    SOURCE SYSTEMS                             │
│                                                                │
│  PDF Invoices  │  Scanned Receipts  │  CSV Exports           │
│  (100s/month)  │  (1000s/month)     │  (weekly dumps)        │
└────────┬────────────────┬────────────────┬───────────────────┘
         │                │                │
         │  Python Extractors (I/O Only)  │
         ▼                ▼                ▼
    ┌────────────────────────────────────────┐
    │         Raw DataFrames                 │
    │  • Minimal parsing                     │
    │  • No business logic                   │
    │  • Just convert bytes → tabular        │
    └────────┬───────────────────────────────┘
             │
             ├──────────────┬─────────────────┐
             │              │                 │
             ▼              ▼                 ▼
       ┌─────────┐    ┌──────────┐     ┌──────────┐
       │   S3    │    │ Snowflake│     │  Local   │
       │ Archive │    │   RAW    │     │  Parquet │
       │         │    │  Schema  │     │  (Dev)   │
       └─────────┘    └────┬─────┘     └──────────┘
                           │
                           │ dbt (SQL-based transformations)
                           │
              ┌────────────▼──────────────┐
              │   STAGING Schema          │
              │  • stg_invoices           │
              │  • stg_receipts           │
              │  • stg_items              │
              │                           │
              │  (1:1 with sources,       │
              │   light cleaning)         │
              └────────────┬──────────────┘
                           │
              ┌────────────▼──────────────┐
              │   ANALYTICS Schema        │
              │                           │
              │  Dimensions:              │
              │  • dim_vendor             │
              │  • dim_product            │
              │  • dim_date               │
              │  • dim_store              │
              │                           │
              │  Facts:                   │
              │  • fact_invoice_line      │
              │  • fact_receipt_line      │
              │  • fact_reconciliation    │
              └───────────────────────────┘
```

## Core Design Principle: ELT Over ETL

### The Old Way (ETL - Extract, Transform, Load)

```python
# BAD: Transforming in Python before loading

df = pd.read_csv('invoices.csv')

# Complex transformations in pandas
df['total'] = df['quantity'] * df['unit_price']
df['vendor_normalized'] = df['vendor'].str.upper().str.strip()
df = df.merge(vendors_df, on='vendor_id')  # Joining in memory
df = df[df['total'] > 0]  # Filtering

# Finally load to warehouse
df.to_sql('invoices', engine, if_exists='append')
```

**Problems with this approach:**
1. **Memory limits**: pandas can't handle datasets larger than RAM
2. **Slow**: Python loops are slow compared to SQL execution
3. **Hard to test**: Business logic scattered across Python functions
4. **Hard to review**: Not everyone knows pandas; everyone knows SQL
5. **No lineage**: Can't see how tables depend on each other

### The Modern Way (ELT - Extract, Load, Transform)

```python
# GOOD: Minimal extraction, load raw, transform in warehouse

# Extract (just parse the file format)
df = pd.read_csv('invoices.csv')

# Load raw data (no transformations)
df.to_sql('raw.invoices', engine, if_exists='replace')
```

```sql
-- Transform in the warehouse with dbt
-- models/staging/stg_invoices.sql

select
    invoice_id,
    upper(trim(vendor_name)) as vendor_name,  -- Normalize in SQL
    quantity * unit_price as total,           -- Calculate in SQL
    -- ... more transformations
from {{ source('raw', 'invoices') }}
where quantity * unit_price > 0  -- Filter in SQL
```

**Why this is better:**
1. **Scalable**: Snowflake can process billions of rows
2. **Fast**: Columnar storage + query optimization
3. **Testable**: dbt has built-in testing framework
4. **Reviewable**: SQL is universal language for data teams
5. **Lineage**: dbt generates DAGs automatically

## When to Use Python vs SQL

| Task | Use Python | Use SQL/dbt | Why |
|------|-----------|-------------|-----|
| Parse PDFs | ✅ | ❌ | Snowflake can't read PDFs directly |
| OCR scanned images | ✅ | ❌ | Need Tesseract for OCR |
| Read CSVs with encoding issues | ✅ | ❌ | Python's `chardet` auto-detects encoding |
| Upload files to S3 | ✅ | ❌ | AWS SDK is Python-based |
| Clean/normalize data | ❌ | ✅ | SQL is faster and more readable |
| Join tables | ❌ | ✅ | Databases are optimized for joins |
| Aggregate metrics | ❌ | ✅ | SQL is designed for this |
| Complex business logic | ❌ | ✅ | SQL with CTEs is clearer than pandas chains |
| Data quality tests | ❌ | ✅ | dbt tests + Great Expectations |

**Rule of Thumb**: If the data is already in the warehouse, use SQL. Python is only for getting data *into* the warehouse.

## Data Flow: Detailed

### 1. Extraction (Python)

**Responsibility**: Convert files into tabular format with minimal parsing.

```python
# src/extractors/pdf_extractor.py

def extract_invoice(pdf_path: Path) -> pd.DataFrame:
    """
    Extract line items from PDF invoice.

    Does NOT:
    - Normalize vendor names
    - Calculate totals
    - Validate data

    Does:
    - Parse PDF tables
    - Return raw DataFrame
    - Quarantine unparseable files
    """
    with pdfplumber.open(pdf_path) as pdf:
        tables = pdf.pages[0].extract_tables()
        # Convert to DataFrame and return
        return pd.DataFrame(tables[0][1:], columns=tables[0][0])
```

**Output**: Raw DataFrame written to Snowflake `RAW` schema

### 2. Loading (Python)

**Responsibility**: Move data from local/S3 into Snowflake.

```python
# src/loaders/snowflake_loader.py

def load_to_raw(df: pd.DataFrame, table: str) -> None:
    """
    Load DataFrame to Snowflake RAW schema.

    Does NOT:
    - Transform data
    - Validate business rules

    Does:
    - Upload to staging table
    - MERGE into target (idempotent)
    - Track load metadata
    """
    # Load to staging table
    df.to_sql(f'stg_{table}', engine, if_exists='replace')

    # Merge into target (idempotent pattern)
    engine.execute(f"""
        MERGE INTO raw.{table} AS target
        USING stg_{table} AS source
        ON target.invoice_id = source.invoice_id
        WHEN MATCHED THEN UPDATE SET ...
        WHEN NOT MATCHED THEN INSERT ...
    """)
```

**Output**: Data in Snowflake `RAW` schema, ready for dbt

### 3. Transformation (SQL/dbt)

**Responsibility**: All business logic, cleaning, and aggregation.

```sql
-- dbt/models/staging/stg_invoices.sql

{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with source as (
    select * from {{ source('raw', 'invoices') }}
),

cleaned as (
    select
        -- Surrogate key for idempotency
        {{ dbt_utils.generate_surrogate_key(['invoice_id', 'line_number']) }} as invoice_line_sk,

        -- Normalize strings
        upper(trim(vendor_name)) as vendor_name,
        upper(trim(item_description)) as item_description,

        -- Type conversions
        cast(quantity as integer) as quantity,
        cast(unit_price as decimal(10,2)) as unit_price,

        -- Calculated fields
        quantity * unit_price as line_total,

        -- Parse dates
        to_date(invoice_date, 'MM/DD/YYYY') as invoice_date,

        -- Metadata
        current_timestamp() as dbt_loaded_at

    from source

    -- Data quality: only valid records
    where quantity > 0
      and unit_price > 0
)

select * from cleaned
```

**Output**: Clean, typed data in `STAGING` schema

Then build dimensions and facts:

```sql
-- dbt/models/marts/dim_vendor.sql

{{
    config(
        materialized='table',
        schema='analytics'
    )
}}

select distinct
    {{ dbt_utils.generate_surrogate_key(['vendor_name']) }} as vendor_sk,
    vendor_name,
    min(invoice_date) as first_invoice_date,
    max(invoice_date) as latest_invoice_date,
    count(*) as total_invoices
from {{ ref('stg_invoices') }}
group by vendor_name
```

## Directory Structure Rationale

```
src/
├── extractors/          # Know how to READ from sources
│   ├── pdf_extractor.py    # pdfplumber logic
│   ├── ocr_extractor.py    # pytesseract logic
│   └── csv_extractor.py    # pandas + chardet
│
├── loaders/             # Know how to WRITE to destinations
│   ├── s3_loader.py        # boto3 upload
│   └── snowflake_loader.py # COPY INTO + MERGE
│
└── utils/               # Cross-cutting concerns
    ├── config.py           # Environment variables
    └── logging.py          # Structured logging

dbt/
├── models/
│   ├── staging/         # 1:1 with RAW tables
│   │   ├── stg_invoices.sql
│   │   ├── stg_receipts.sql
│   │   └── stg_items.sql
│   │
│   └── marts/           # Business logic layer
│       ├── dim_vendor.sql
│       ├── dim_product.sql
│       ├── fact_invoice_line.sql
│       └── fact_reconciliation.sql
│
├── tests/               # Data quality tests
│   ├── assert_invoice_totals_match.sql
│   └── assert_no_orphaned_vendors.sql
│
└── macros/              # Reusable SQL snippets
    └── cents_to_dollars.sql
```

### Why No `src/transformers/`?

**All transformations are in `dbt/models/` (SQL), not Python.**

This separation enforces discipline:
- Python engineers can't sneak business logic into extractors
- Analysts can modify transformations without touching Python
- Reviewing a PR is easier (SQL changes are in `dbt/`, not scattered)

## Idempotency Patterns

Every operation must be idempotent (re-running produces the same result).

### Extraction: Filename-based Deduplication

```python
def extract_if_not_processed(pdf_path: Path) -> Optional[pd.DataFrame]:
    """Only extract if we haven't processed this file already."""
    checksum = hashlib.md5(pdf_path.read_bytes()).hexdigest()

    if already_processed(checksum):
        logger.info(f"Skipping {pdf_path} - already processed")
        return None

    df = extract_invoice(pdf_path)
    record_processed(checksum, pdf_path)
    return df
```

### Loading: MERGE Instead of INSERT

```sql
-- BAD: Re-running creates duplicates
INSERT INTO raw.invoices SELECT * FROM staging;

-- GOOD: Re-running updates existing records
MERGE INTO raw.invoices AS target
USING staging AS source
ON target.invoice_id = source.invoice_id
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...
```

### Transformation: dbt Handles This

dbt models are idempotent by design:
- `materialized='table'`: Replaces table on each run
- `materialized='incremental'`: Only processes new rows
- `materialized='view'`: Re-computes on query

## Error Handling: Quarantine Pattern

Failed records are quarantined, not dropped:

```python
try:
    df = extract_invoice(pdf_path)
    load_to_snowflake(df, 'raw.invoices')
except ExtractionError as e:
    # Don't fail the whole pipeline
    quarantine_file(
        pdf_path,
        error=str(e),
        destination='data/quarantine/invoices/'
    )
    logger.warning(f"Quarantined {pdf_path}: {e}")
```

This enables:
- Manual review of failures
- Re-processing after bug fixes
- Quality metrics over time

## Performance Considerations

### Current Scale

- ~10,000 product SKUs
- ~100 invoices/month
- ~1,500 receipts/month
- **Pipeline runtime**: ~5 minutes end-to-end

At this scale, single-threaded Python is fine. Focus on correctness.

### Future Scale (10x+)

For larger volumes:

1. **Parallel Extraction**: Python `multiprocessing`
   ```python
   with Pool(cpu_count()) as pool:
       dfs = pool.map(extract_invoice, pdf_files)
   ```

2. **Incremental dbt Models**: Only transform new data
   ```sql
   {{ config(materialized='incremental') }}

   select * from {{ ref('stg_invoices') }}
   {% if is_incremental() %}
   where invoice_date > (select max(invoice_date) from {{ this }})
   {% endif %}
   ```

3. **Snowflake Clustering**: Speed up queries
   ```sql
   ALTER TABLE fact_invoice_line
   CLUSTER BY (invoice_date, vendor_sk);
   ```

**Don't optimize prematurely.** Build for current needs, architect for future growth.

## Testing Strategy

### Unit Tests (Python)

Test extractors and loaders in isolation:

```python
def test_pdf_extractor_with_valid_invoice():
    df = extract_invoice('tests/fixtures/sample_invoice.pdf')
    assert len(df) > 0
    assert 'invoice_id' in df.columns
```

### Integration Tests (Python)

Test end-to-end with real Snowflake (or mocked):

```python
@pytest.mark.integration
def test_load_to_snowflake():
    df = pd.DataFrame({'invoice_id': [1, 2, 3]})
    load_to_raw(df, 'invoices')
    # Verify data in Snowflake
    result = engine.execute("SELECT COUNT(*) FROM raw.invoices")
    assert result.scalar() == 3
```

### dbt Tests (SQL)

Built into dbt:

```yaml
# dbt/models/marts/schema.yml

models:
  - name: fact_invoice_line
    columns:
      - name: invoice_line_sk
        tests:
          - unique
          - not_null
      - name: vendor_sk
        tests:
          - relationships:
              to: ref('dim_vendor')
              field: vendor_sk
```

Custom tests:

```sql
-- dbt/tests/assert_invoice_totals_match.sql

-- Verify that sum of line items equals invoice total
select
    invoice_id,
    invoice_total,
    sum_of_lines
from (
    select
        invoice_id,
        max(invoice_total) as invoice_total,
        sum(line_total) as sum_of_lines
    from {{ ref('fact_invoice_line') }}
    group by invoice_id
)
where abs(invoice_total - sum_of_lines) > 0.01  -- Allow for rounding
```

Run with: `dbt test`

## Data Lineage

dbt automatically generates lineage DAGs:

```bash
dbt docs generate
dbt docs serve
```

This produces interactive documentation showing:
- Which models depend on which sources
- Column-level lineage
- Test results
- Compilation SQL

This is **invaluable** for:
- Understanding impact of changes
- Debugging data quality issues
- Onboarding new team members

## Summary: Key Architectural Decisions

1. **ELT over ETL**: Transform in the warehouse, not Python
2. **Python for I/O only**: Extract and load, nothing else
3. **SQL for business logic**: dbt models, not pandas chains
4. **Idempotent operations**: Safe to re-run at any step
5. **Quarantine failures**: Don't drop bad data, investigate it
6. **Test at every layer**: Python unit tests, dbt tests, Great Expectations
7. **Document with code**: dbt docs, schema.yml, architecture docs

This architecture enables **scalability** (Snowflake scales, pandas doesn't), **maintainability** (SQL is reviewable), and **reliability** (idempotent + tested).
