# Scripts Directory

Utility scripts for data generation, pipeline orchestration, and Snowflake setup.

## Data Generation Scripts

These scripts create synthetic grocery data with realistic quality issues for development and testing.

### Quick Start

Generate all data at once:
```bash
python scripts/generate_all_data.py
```

Or run individual generators:

### `generate_item_master.py`

Creates product catalog CSV with ~15,000 SKUs across grocery categories.

**Intentional quality issues:**
- 5% missing UPCs
- 2% duplicate UPCs (same barcode, different products)
- 8% encoding corruption (UTF-8 vs ISO-8859-1)
- 15% inconsistent units ("LB" vs "lb" vs "pound")
- 1% invalid prices (cost=0, retail<cost)
- 3% orphaned vendor IDs
- 10% stale records (ACTIVE but not modified in 2+ years)

```bash
python scripts/generate_item_master.py --num-skus 15000
```

**Output:** `data/raw/item_master/item_master_YYYYMMDD.csv`

**Why these issues matter:**
- Duplicate UPCs → inventory chaos (sales misattributed)
- Encoding issues → joins fail silently
- Inconsistent units → aggregation errors

---

### `generate_invoices.py`

Creates vendor invoice PDFs with three format archetypes:
- **Major distributors** (50%): Clean, structured tables
- **Regional suppliers** (35%): Semi-structured, handwritten notes
- **Small vendors** (15%): Scanned appearance, minimal formatting

**Intentional quality issues:**
- Multi-page invoices (20%)
- Missing totals/subtotals (5%)
- Date format variations (MM/DD/YYYY, YYYY-MM-DD, Month DD, YYYY)
- Duplicate invoices (3% - same invoice scanned twice)

```bash
python scripts/generate_invoices.py --num-invoices 100
```

**Output:** `data/raw/invoices/invoice_YYYYMMDD_*.pdf`

**Why these issues matter:**
- Format variation → requires adaptive parsing logic
- Duplicates → overstated COGS if not deduplicated
- Missing totals → can't validate line item sums

---

### `generate_receipts.py`

Creates transaction receipt images with OCR degradation:

**Degradation levels:**
- **Clean** (10%): Minimal fade, easy to OCR
- **Medium** (70%): Typical thermal fade, some rotation/stains
- **Heavy** (20%): Severe fade, rotation, stains, blur

**OCR challenges introduced:**
- Thermal paper fading (text lightens over time)
- Rotation (90°, 180°, 270°)
- Coffee stains and water damage
- Salt-and-pepper noise (scanner quality)
- Gaussian blur (out-of-focus)

```bash
python scripts/generate_receipts.py --num-receipts 50
```

**Output:** `data/raw/receipts/receipt_YYYYMMDD_*.png`

**Why these issues matter:**
- OCR accuracy directly impacts revenue recognition
- Faded receipts are reality when onboarding historical data
- Rotation detection is critical for automated processing

---

### `generate_price_changes.py`

Creates price change history CSV with temporal complexity.

**Intentional temporal issues:**
- 5% overlapping date ranges (two prices active simultaneously)
- 15% missing end dates on promotions
- 2% future-dated changes (scheduled but not yet effective)
- 3% invalid transitions (old_price ≠ previous new_price)
- 8% gaps in history (missing change records)

```bash
python scripts/generate_price_changes.py --num-changes 500
```

**Output:** `data/raw/price_changes_YYYYMMDD.csv`

**Why these issues matter:**
- Overlapping dates → which price applies?
- Missing end dates → do promotions last forever?
- Gaps in history → breaks slowly-changing dimension logic

---

## Pipeline Orchestration Scripts

*(To be created in Phase 3-6)*

### `run_extraction.py`
Orchestrates all extractors (PDF, OCR, CSV) to process raw files into staging DataFrames.

### `run_pipeline.py`
Full end-to-end pipeline: Extract → S3 Upload → Snowflake Load → dbt Transform

### `run_snowflake_setup.py`
Executes Snowflake DDL to create database, schemas, and tables.

---

## Design Principles

### Why Generate Bad Data?

Most test data generators create clean, perfect data. But production data is **never clean**. By intentionally seeding quality issues, we:

1. **Test validation logic**: Can we catch duplicate UPCs? Overlapping dates?
2. **Demonstrate defensive coding**: Quarantine unparseable PDFs instead of crashing
3. **Show domain knowledge**: These are REAL problems in retail systems

### Data Generation Philosophy

**Realistic over random**: We don't generate random strings. Every product name, vendor, and price change follows realistic retail patterns.

**Documented issues**: Each quality issue has a comment explaining:
- What the issue is
- How often it occurs (percentage)
- Why it matters to the business

**Reproducible**: Using fixed random seeds (if needed) allows recreating the same dataset for debugging.

---

## Development Workflow

1. **Generate data**:
   ```bash
   python scripts/generate_all_data.py
   ```

2. **Verify output**:
   ```bash
   ls -lh data/raw/invoices/    # Check PDFs generated
   ls -lh data/raw/receipts/    # Check images generated
   head data/raw/item_master/*.csv  # Preview CSV
   ```

3. **Run extraction**:
   ```bash
   python scripts/run_extraction.py  # (Phase 3)
   ```

4. **Inspect staging data**:
   ```bash
   ls -lh data/staging/
   ```

5. **Load to Snowflake**:
   ```bash
   python scripts/run_pipeline.py  # (Phase 4)
   ```

---

## Troubleshooting

**"ModuleNotFoundError: No module named 'reportlab'"**
- Install dependencies: `pip install -r requirements.txt`

**Generated PDFs look blank**
- Font issue on macOS. Script uses fallback font if Courier not found.

**Receipt images all black**
- Pillow version issue. Ensure Pillow >= 10.0

**Want different data volumes**
- Use flags: `--num-skus 5000 --num-invoices 50 --num-receipts 25`

---

## Next Steps

After generating data:
1. Build extractors (Phase 3)
2. Build loaders (Phase 4)
3. Build dbt transformations (Phase 5)
4. Add data quality checks (Phase 6)
