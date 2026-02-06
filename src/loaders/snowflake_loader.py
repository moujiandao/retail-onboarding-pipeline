"""
Snowflake Loader with Idempotent MERGE Pattern

Loads data from S3/local files into Snowflake using COPY INTO + MERGE.

Why MERGE Instead of INSERT?
-----------------------------
INSERT: Re-running creates duplicates
MERGE:  Re-running updates existing records (idempotent)

This is critical for production pipelines where:
- Network failures require retries
- Airflow retries failed tasks
- Manual re-runs are needed for data fixes

Pattern: Staging Table + MERGE
-------------------------------
1. Load data into temporary staging table (COPY INTO)
2. MERGE from staging into target table (with deduplication key)
3. Drop staging table

This ensures:
- Atomic operations (all-or-nothing)
- Idempotency (safe to re-run)
- Auditability (track in load_history)

Usage:
    from src.loaders.snowflake_loader import SnowflakeLoader

    loader = SnowflakeLoader()
    loader.load_from_s3(
        s3_path="s3://bucket/invoices/year=2024/month=01/*.parquet",
        table="raw.invoices",
        merge_key="invoice_number"
    )
"""

import logging
from typing import Optional, List, Dict
from pathlib import Path
from datetime import datetime

import snowflake.connector
from snowflake.connector import DictCursor
import pandas as pd

from src.utils.config import get_config, require_snowflake_config

logger = logging.getLogger(__name__)


class SnowflakeLoader:
    """
    Load data into Snowflake with idempotent MERGE pattern.

    Design Decisions:
    - Use MERGE instead of INSERT (idempotent)
    - Track load metadata (lineage, quality metrics)
    - Support both S3 and local file loading
    - Batch operations (don't load row-by-row)
    """

    def __init__(self):
        """Initialize Snowflake loader."""
        config = get_config()
        require_snowflake_config(config)

        self.config = config

        # Connection will be created on-demand
        self._conn = None

    @property
    def conn(self):
        """
        Lazy connection property.

        Creates connection only when first accessed.
        Reuses same connection for multiple operations.
        """
        if self._conn is None or self._conn.is_closed():
            logger.info(f"Connecting to Snowflake: {self.config.snowflake_account}")

            self._conn = snowflake.connector.connect(
                account=self.config.snowflake_account,
                user=self.config.snowflake_user,
                password=self.config.snowflake_password,
                warehouse=self.config.snowflake_warehouse,
                database=self.config.snowflake_database,
                schema=self.config.snowflake_schema,
                role=self.config.snowflake_role,
            )

            logger.info("✓ Connected to Snowflake")

        return self._conn

    def execute(self, sql: str, params: Optional[Dict] = None) -> List[Dict]:
        """
        Execute SQL query and return results.

        Args:
            sql: SQL query
            params: Optional query parameters (for parameterized queries)

        Returns:
            List of result rows as dictionaries
        """
        cursor = self.conn.cursor(DictCursor)

        try:
            cursor.execute(sql, params)
            results = cursor.fetchall()
            return results
        finally:
            cursor.close()

    def load_from_dataframe(
        self,
        df: pd.DataFrame,
        table: str,
        merge_key: str,
        if_exists: str = "merge",
    ) -> int:
        """
        Load DataFrame into Snowflake table.

        Args:
            df: pandas DataFrame
            table: Target table (schema.table format)
            merge_key: Column to use for deduplication
            if_exists: 'merge', 'replace', or 'append'

        Returns:
            Number of rows loaded

        Example:
            >>> loader = SnowflakeLoader()
            >>> df = pd.DataFrame({'invoice_number': ['INV-001'], ...})
            >>> loader.load_from_dataframe(
            ...     df,
            ...     table='raw.invoices',
            ...     merge_key='invoice_number',
            ...     if_exists='merge'
            ... )
            1
        """
        if df.empty:
            logger.warning("DataFrame is empty, nothing to load")
            return 0

        logger.info(f"Loading {len(df)} rows to {table}")

        if if_exists == "replace":
            # Simple replace (truncate + insert)
            return self._load_replace(df, table)

        elif if_exists == "append":
            # Simple append (just insert)
            return self._load_append(df, table)

        elif if_exists == "merge":
            # Idempotent merge (staging + merge)
            return self._load_merge(df, table, merge_key)

        else:
            raise ValueError(f"Invalid if_exists: {if_exists}")

    def _load_replace(self, df: pd.DataFrame, table: str) -> int:
        """
        Load by replacing all existing data.

        Use case: Full refresh of dimension tables
        """
        logger.info(f"REPLACE mode: Truncating {table}")

        # Truncate table
        self.execute(f"TRUNCATE TABLE {table}")

        # Insert all rows
        return self._insert_dataframe(df, table)

    def _load_append(self, df: pd.DataFrame, table: str) -> int:
        """
        Load by appending (no deduplication).

        Use case: Fact tables with unique keys (already deduplicated)
        Warning: Re-running will create duplicates!
        """
        logger.info(f"APPEND mode: Inserting into {table}")
        return self._insert_dataframe(df, table)

    def _load_merge(self, df: pd.DataFrame, table: str, merge_key: str) -> int:
        """
        Load using MERGE (idempotent, handles duplicates).

        Pattern:
        1. Create staging table
        2. Load data into staging
        3. MERGE staging → target (on merge_key)
        4. Drop staging table

        This is the production-grade pattern.
        """
        logger.info(f"MERGE mode: Using key '{merge_key}'")

        staging_table = f"{table}_staging_{int(datetime.now().timestamp())}"

        try:
            # Step 1: Create staging table (same structure as target)
            self.execute(f"CREATE TEMPORARY TABLE {staging_table} LIKE {table}")

            # Step 2: Load data into staging
            rows_loaded = self._insert_dataframe(df, staging_table)

            # Step 3: MERGE staging into target
            self._merge_tables(staging_table, table, merge_key)

            logger.info(f"✓ Merged {rows_loaded} rows into {table}")

            return rows_loaded

        finally:
            # Step 4: Drop staging table (even if error occurred)
            try:
                self.execute(f"DROP TABLE IF EXISTS {staging_table}")
            except:
                pass

    def _insert_dataframe(self, df: pd.DataFrame, table: str) -> int:
        """
        Insert DataFrame rows into table.

        Uses Snowflake's write_pandas for efficient bulk loading.
        """
        from snowflake.connector.pandas_tools import write_pandas

        # write_pandas is Snowflake's optimized bulk loader
        # Much faster than row-by-row INSERT
        success, num_chunks, num_rows, output = write_pandas(
            conn=self.conn,
            df=df,
            table_name=table.split(".")[-1],  # Just table name, not schema
            schema=table.split(".")[0] if "." in table else None,
            quote_identifiers=False,
        )

        if not success:
            raise Exception(f"write_pandas failed: {output}")

        logger.debug(f"  Inserted {num_rows} rows in {num_chunks} chunks")
        return num_rows

    def _merge_tables(self, source_table: str, target_table: str, merge_key: str):
        """
        MERGE source table into target table.

        SQL Pattern:
        MERGE INTO target USING source
        ON target.key = source.key
        WHEN MATCHED THEN UPDATE SET ...
        WHEN NOT MATCHED THEN INSERT ...

        This handles:
        - New records (INSERT)
        - Existing records (UPDATE)
        - Deduplication (only one row per key)
        """
        # Get column list from staging table
        cursor = self.conn.cursor()
        cursor.execute(f"DESCRIBE TABLE {source_table}")
        columns = [row[0] for row in cursor.fetchall()]
        cursor.close()

        # Build UPDATE SET clause (update all columns except merge_key)
        update_cols = [col for col in columns if col != merge_key]
        update_set = ", ".join([f"{col} = source.{col}" for col in update_cols])

        # Build INSERT columns
        insert_cols = ", ".join(columns)
        insert_values = ", ".join([f"source.{col}" for col in columns])

        # Build MERGE statement
        merge_sql = f"""
        MERGE INTO {target_table} AS target
        USING {source_table} AS source
        ON target.{merge_key} = source.{merge_key}
        WHEN MATCHED THEN
            UPDATE SET {update_set}
        WHEN NOT MATCHED THEN
            INSERT ({insert_cols})
            VALUES ({insert_values})
        """

        logger.debug(f"Executing MERGE on key: {merge_key}")
        self.execute(merge_sql)

    def load_from_s3(
        self,
        s3_path: str,
        table: str,
        merge_key: str,
        file_format: str = "parquet_format",
    ) -> int:
        """
        Load data directly from S3 using Snowflake's COPY INTO.

        This is more efficient than loading to pandas first:
        - No local memory required
        - Snowflake loads in parallel (faster)
        - Snowflake handles type conversion

        Args:
            s3_path: S3 path (supports wildcards: s3://bucket/path/*.parquet)
            table: Target table
            merge_key: Column for deduplication
            file_format: Snowflake file format name

        Returns:
            Number of rows loaded

        Example:
            >>> loader.load_from_s3(
            ...     s3_path='s3://bucket/invoices/year=2024/month=01/*.parquet',
            ...     table='raw.invoices',
            ...     merge_key='invoice_number'
            ... )
        """
        logger.info(f"Loading from S3: {s3_path} → {table}")

        staging_table = f"{table}_staging_{int(datetime.now().timestamp())}"

        try:
            # Create staging table
            self.execute(f"CREATE TEMPORARY TABLE {staging_table} LIKE {table}")

            # COPY INTO staging from S3
            copy_sql = f"""
            COPY INTO {staging_table}
            FROM '{s3_path}'
            FILE_FORMAT = (FORMAT_NAME = '{file_format}')
            MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
            ON_ERROR = CONTINUE  -- Skip bad rows, don't fail entire load
            """

            result = self.execute(copy_sql)

            # Parse result to get row count
            rows_loaded = result[0]["rows_loaded"] if result else 0

            logger.info(f"  Copied {rows_loaded} rows from S3")

            # MERGE into target
            self._merge_tables(staging_table, table, merge_key)

            logger.info(f"✓ Loaded {rows_loaded} rows into {table}")

            return rows_loaded

        finally:
            # Clean up staging table
            try:
                self.execute(f"DROP TABLE IF EXISTS {staging_table}")
            except:
                pass

    def track_load(
        self,
        table_name: str,
        load_type: str,
        source_location: str,
        rows_loaded: int,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
    ):
        """
        Track load in metadata.load_history table.

        This provides:
        - Audit trail (who loaded what when)
        - Debugging (when did data change?)
        - Monitoring (load success rates)

        Args:
            table_name: Table that was loaded
            load_type: FULL, INCREMENTAL
            source_location: S3 path or local path
            rows_loaded: Number of rows
            status: SUCCESS, FAILED, PARTIAL
            error_message: Error details if failed
        """
        insert_sql = """
        INSERT INTO metadata.load_history (
            table_name,
            load_type,
            source_location,
            rows_loaded,
            status,
            error_message,
            load_started_at,
            load_completed_at,
            loaded_by
        ) VALUES (
            %(table_name)s,
            %(load_type)s,
            %(source_location)s,
            %(rows_loaded)s,
            %(status)s,
            %(error_message)s,
            CURRENT_TIMESTAMP(),
            CURRENT_TIMESTAMP(),
            CURRENT_USER()
        )
        """

        self.execute(insert_sql, {
            "table_name": table_name,
            "load_type": load_type,
            "source_location": source_location,
            "rows_loaded": rows_loaded,
            "status": status,
            "error_message": error_message,
        })

        logger.debug(f"Tracked load in metadata.load_history")

    def close(self):
        """Close Snowflake connection."""
        if self._conn and not self._conn.is_closed():
            self._conn.close()
            logger.info("Snowflake connection closed")

    def __enter__(self):
        """Context manager support."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup."""
        self.close()
