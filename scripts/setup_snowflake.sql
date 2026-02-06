-- =============================================================================
-- Snowflake Schema Setup for Retail Onboarding Pipeline
-- =============================================================================
--
-- This script creates the database structure for the ELT pipeline.
--
-- Schema Organization:
--   RAW      - Immutable source data (1:1 with files)
--   STAGING  - Light cleaning, 1:1 with RAW (dbt models)
--   ANALYTICS - Star schema for business use (dbt models)
--   METADATA - Pipeline tracking and lineage
--
-- Design Decisions:
-- -----------------
-- 1. VARIANT columns for semi-structured data (JSON metadata)
-- 2. Clustering keys on date columns (query performance)
-- 3. NOT NULL only where truly required (flexible for messy data)
-- 4. Separate metadata schema (don't pollute business data)
--
-- Usage:
--   snowsql -f scripts/setup_snowflake.sql
--   OR
--   python scripts/run_snowflake_setup.py
--
-- =============================================================================

-- =============================================================================
-- Database & Warehouse Setup
-- =============================================================================

-- Create database (if not exists)
CREATE DATABASE IF NOT EXISTS RETAIL_ONBOARDING
    COMMENT = 'Retail onboarding pipeline database';

USE DATABASE RETAIL_ONBOARDING;

-- Create warehouse for ETL workloads
-- Size: X-Small is sufficient for development (2 servers, $2/hour)
-- AUTO_SUSPEND: Pause after 5 min of inactivity (save costs)
-- AUTO_RESUME: Start automatically when queried
CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH
    WAREHOUSE_SIZE = 'X-SMALL'
    AUTO_SUSPEND = 300
    AUTO_RESUME = TRUE
    COMMENT = 'General purpose warehouse for ETL';

USE WAREHOUSE COMPUTE_WH;

-- =============================================================================
-- Schema Creation
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS RAW
    COMMENT = 'Raw data loaded from source files (immutable)';

CREATE SCHEMA IF NOT EXISTS STAGING
    COMMENT = 'Staging layer - light cleaning (dbt models)';

CREATE SCHEMA IF NOT EXISTS ANALYTICS
    COMMENT = 'Business analytics layer - star schema (dbt models)';

CREATE SCHEMA IF NOT EXISTS METADATA
    COMMENT = 'Pipeline metadata and lineage tracking';

-- =============================================================================
-- RAW Schema Tables
-- =============================================================================
-- These tables are loaded directly from files via COPY INTO.
-- Structure mirrors file schemas as closely as possible.
-- Minimal constraints (allow messy data, validate in dbt).
-- =============================================================================

USE SCHEMA RAW;

-- Raw invoices (from PDF extraction)
CREATE TABLE IF NOT EXISTS invoices (
    -- Primary identification
    invoice_id VARCHAR(100),
    invoice_number VARCHAR(100),
    invoice_date VARCHAR(50),  -- String because date formats vary

    -- Vendor information
    vendor_name VARCHAR(500),
    vendor_id VARCHAR(100),

    -- Amounts (stored as strings to preserve formatting)
    subtotal VARCHAR(50),
    tax VARCHAR(50),
    freight VARCHAR(50),
    total VARCHAR(50),

    -- Metadata from extraction
    extraction_method VARCHAR(50),
    source_file VARCHAR(500),
    line_item_count INT,

    -- Semi-structured data (full extraction result as JSON)
    raw_metadata VARIANT,

    -- Audit columns
    loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),

    -- No primary key constraint (allow duplicates to be handled in dbt)
    COMMENT = 'Raw invoice headers extracted from PDFs'
);

-- Raw invoice line items
CREATE TABLE IF NOT EXISTS invoice_lines (
    -- Link to invoice
    invoice_number VARCHAR(100),
    line_number INT,

    -- Line item details
    item_code VARCHAR(100),
    description VARCHAR(500),
    upc VARCHAR(50),
    quantity VARCHAR(50),  -- String to handle decimals and units
    unit VARCHAR(20),
    unit_price VARCHAR(50),
    line_total VARCHAR(50),

    -- Metadata
    source_file VARCHAR(500),
    loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),

    COMMENT = 'Raw invoice line items'
);

-- Raw item master (from CSV)
CREATE TABLE IF NOT EXISTS items (
    upc VARCHAR(50),
    sku VARCHAR(100),
    description VARCHAR(500),
    brand VARCHAR(200),
    category VARCHAR(100),
    subcategory VARCHAR(100),
    department VARCHAR(20),
    unit_size NUMBER(10, 2),
    unit_measure VARCHAR(20),
    pack_size INT,
    vendor_id VARCHAR(100),
    vendor_name VARCHAR(200),
    cost NUMBER(10, 2),
    retail_price NUMBER(10, 2),
    margin_pct NUMBER(5, 2),
    status VARCHAR(20),
    created_date DATE,
    modified_date DATE,

    -- Metadata
    source_file VARCHAR(500),
    loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),

    COMMENT = 'Raw item master from CSV exports'
);

-- Raw receipts (from OCR extraction)
CREATE TABLE IF NOT EXISTS receipts (
    -- Transaction identification
    transaction_id VARCHAR(100),
    transaction_date VARCHAR(50),  -- String because OCR may garble dates
    transaction_time VARCHAR(20),

    -- Store information
    store_name VARCHAR(200),
    store_number VARCHAR(20),

    -- Transaction details
    cashier VARCHAR(100),
    register VARCHAR(20),

    -- Amounts
    subtotal VARCHAR(50),
    tax VARCHAR(50),
    total VARCHAR(50),

    -- Payment
    payment_method VARCHAR(50),
    card_last_four VARCHAR(10),

    -- OCR quality
    ocr_confidence NUMBER(5, 2),
    word_count INT,

    -- Full OCR text for debugging
    raw_text TEXT,

    -- Structured data as JSON
    structured_data VARIANT,

    -- Metadata
    source_file VARCHAR(500),
    loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),

    COMMENT = 'Raw receipts extracted via OCR'
);

-- Raw price changes (from CSV)
CREATE TABLE IF NOT EXISTS price_changes (
    sku VARCHAR(100),
    effective_date DATE,
    end_date DATE,
    price_type VARCHAR(20),  -- PROMO, REGULAR
    old_price NUMBER(10, 2),
    new_price NUMBER(10, 2),
    reason_code VARCHAR(50),
    reason_description VARCHAR(200),
    approved_by VARCHAR(100),
    approved_date DATE,

    -- Metadata
    source_file VARCHAR(500),
    loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),

    COMMENT = 'Raw price change history'
);

-- =============================================================================
-- METADATA Schema Tables
-- =============================================================================
-- Track pipeline execution, data lineage, and quality metrics
-- =============================================================================

USE SCHEMA METADATA;

-- Load history tracking
CREATE TABLE IF NOT EXISTS load_history (
    load_id INT AUTOINCREMENT PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    load_type VARCHAR(50),  -- FULL, INCREMENTAL
    source_location VARCHAR(500),  -- S3 path or local path

    -- Statistics
    rows_loaded INT,
    rows_failed INT,
    bytes_loaded BIGINT,

    -- Timing
    load_started_at TIMESTAMP_NTZ,
    load_completed_at TIMESTAMP_NTZ,
    duration_seconds INT,

    -- Status
    status VARCHAR(20),  -- SUCCESS, FAILED, PARTIAL
    error_message TEXT,

    -- Audit
    loaded_by VARCHAR(100),  -- User or service account

    COMMENT = 'History of all data loads into warehouse'
);

-- File processing log
CREATE TABLE IF NOT EXISTS file_processing_log (
    log_id INT AUTOINCREMENT PRIMARY KEY,
    file_path VARCHAR(500) NOT NULL,
    file_type VARCHAR(50),  -- PDF, CSV, IMAGE
    file_size_bytes BIGINT,

    -- Processing details
    processing_stage VARCHAR(50),  -- EXTRACTION, LOADING
    status VARCHAR(20),  -- SUCCESS, FAILED, QUARANTINED

    -- Quality metrics
    records_extracted INT,
    confidence_score NUMBER(5, 2),  -- For OCR

    -- Error handling
    error_message TEXT,
    quarantine_reason VARCHAR(500),

    -- Timing
    processed_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),

    COMMENT = 'Log of individual file processing'
);

-- Data quality checks
CREATE TABLE IF NOT EXISTS quality_checks (
    check_id INT AUTOINCREMENT PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    check_name VARCHAR(200) NOT NULL,
    check_type VARCHAR(50),  -- NOT_NULL, UNIQUE, RANGE, CUSTOM

    -- Results
    records_tested INT,
    records_passed INT,
    records_failed INT,
    pass_rate NUMBER(5, 2),

    -- Threshold
    threshold NUMBER(5, 2),  -- Minimum acceptable pass rate
    status VARCHAR(20),  -- PASSED, FAILED, WARNING

    -- Details
    failure_details VARIANT,  -- JSON with sample failures

    -- Timing
    checked_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),

    COMMENT = 'Data quality check results (Great Expectations)'
);

-- =============================================================================
-- Indexes & Clustering
-- =============================================================================
-- Snowflake doesn't have traditional indexes, but clustering keys
-- improve query performance by organizing data physically.
-- =============================================================================

-- Cluster invoices by date for efficient date-range queries
ALTER TABLE RAW.invoices CLUSTER BY (TO_DATE(invoice_date, 'YYYY-MM-DD'));

-- Cluster items by SKU for efficient lookups
ALTER TABLE RAW.items CLUSTER BY (sku);

-- Cluster receipts by date
ALTER TABLE RAW.receipts CLUSTER BY (TO_DATE(transaction_date, 'MM/DD/YYYY'));

-- =============================================================================
-- File Formats
-- =============================================================================
-- Define file formats for COPY INTO commands
-- =============================================================================

-- Parquet format (for staging data)
CREATE OR REPLACE FILE FORMAT parquet_format
    TYPE = PARQUET
    COMPRESSION = SNAPPY;

-- CSV format (for raw CSVs)
CREATE OR REPLACE FILE FORMAT csv_format
    TYPE = CSV
    FIELD_DELIMITER = ','
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    ESCAPE_UNENCLOSED_FIELD = NONE
    ENCODING = 'UTF8'
    ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE;  -- Allow variable columns

-- JSON format (for metadata files)
CREATE OR REPLACE FILE FORMAT json_format
    TYPE = JSON
    COMPRESSION = AUTO;

-- =============================================================================
-- Stages (S3 Integration)
-- =============================================================================
-- Stages define S3 locations for COPY INTO/UNLOAD commands
-- =============================================================================

-- External stage for S3
-- Note: In production, use IAM roles instead of credentials
-- CREATE OR REPLACE STAGE s3_stage
--     URL = 's3://your-bucket/retail-pipeline/'
--     CREDENTIALS = (AWS_KEY_ID = '...' AWS_SECRET_KEY = '...')
--     FILE_FORMAT = parquet_format;

-- Temporary stage for local development
CREATE OR REPLACE STAGE local_stage
    FILE_FORMAT = parquet_format;

-- =============================================================================
-- Views for Common Queries
-- =============================================================================

USE SCHEMA RAW;

-- View to parse invoice dates (handle format variations)
CREATE OR REPLACE VIEW invoices_parsed AS
SELECT
    invoice_id,
    invoice_number,
    -- Try multiple date formats
    COALESCE(
        TRY_TO_DATE(invoice_date, 'YYYY-MM-DD'),
        TRY_TO_DATE(invoice_date, 'MM/DD/YYYY'),
        TRY_TO_DATE(invoice_date, 'DD/MM/YYYY')
    ) AS invoice_date_parsed,
    vendor_name,
    vendor_id,
    TRY_TO_NUMBER(REPLACE(total, '$', ''), 10, 2) AS total_amount,
    source_file,
    loaded_at
FROM invoices;

-- =============================================================================
-- Grants (Security)
-- =============================================================================
-- In production, create roles and grant appropriate permissions
-- =============================================================================

-- Example roles (commented out - adjust for your environment)
-- CREATE ROLE IF NOT EXISTS data_engineer;
-- CREATE ROLE IF NOT EXISTS analyst;
-- CREATE ROLE IF NOT EXISTS service_account;

-- Grant schema permissions
-- GRANT USAGE ON SCHEMA RAW TO ROLE data_engineer;
-- GRANT SELECT ON ALL TABLES IN SCHEMA RAW TO ROLE analyst;
-- GRANT ALL ON SCHEMA METADATA TO ROLE data_engineer;

-- =============================================================================
-- Cleanup / Rollback (if needed)
-- =============================================================================
-- Uncomment to drop everything (use with caution!)
-- =============================================================================

-- DROP DATABASE IF EXISTS RETAIL_ONBOARDING CASCADE;

SELECT 'Snowflake schema setup complete!' AS status;
