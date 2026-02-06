"""
Execute Snowflake Schema Setup

Runs the DDL script to create database, schemas, and tables.

This script demonstrates:
- Snowflake connection management
- SQL execution from file
- Error handling for DDL operations
- Idempotent schema creation (IF NOT EXISTS)

Usage:
    python scripts/run_snowflake_setup.py

    # Dry run (show SQL without executing)
    python scripts/run_snowflake_setup.py --dry-run
"""

import argparse
import sys
from pathlib import Path
import logging

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import snowflake.connector
from src.utils.config import get_config, require_snowflake_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def execute_sql_file(conn, sql_file: Path, dry_run: bool = False):
    """
    Execute SQL commands from file.

    Args:
        conn: Snowflake connection
        sql_file: Path to SQL file
        dry_run: If True, print SQL without executing
    """
    sql_content = sql_file.read_text()

    # Split into individual statements
    # (Snowflake connector can't execute multiple statements at once)
    statements = [
        stmt.strip()
        for stmt in sql_content.split(";")
        if stmt.strip() and not stmt.strip().startswith("--")
    ]

    logger.info(f"Found {len(statements)} SQL statements in {sql_file.name}")

    if dry_run:
        logger.info("\nDRY RUN - SQL to be executed:")
        logger.info("=" * 60)
        for i, stmt in enumerate(statements, 1):
            logger.info(f"\n-- Statement {i}")
            logger.info(stmt[:200] + "..." if len(stmt) > 200 else stmt)
        logger.info("=" * 60)
        return

    cursor = conn.cursor()

    try:
        for i, statement in enumerate(statements, 1):
            # Skip empty statements
            if not statement:
                continue

            # Log what we're executing (truncated)
            stmt_preview = statement[:100].replace("\n", " ")
            logger.info(f"[{i}/{len(statements)}] Executing: {stmt_preview}...")

            try:
                cursor.execute(statement)

                # Show results for SELECT statements
                if statement.strip().upper().startswith("SELECT"):
                    results = cursor.fetchall()
                    for row in results:
                        logger.info(f"  → {row}")

            except snowflake.connector.errors.ProgrammingError as e:
                # Some errors are okay (e.g., "object already exists")
                error_msg = str(e).lower()
                if "already exists" in error_msg or "if not exists" in error_msg:
                    logger.debug(f"  (Already exists, skipping)")
                else:
                    logger.error(f"  ✗ Error: {e}")
                    raise

        logger.info("\n✓ All SQL statements executed successfully")

    finally:
        cursor.close()


def main():
    parser = argparse.ArgumentParser(description="Setup Snowflake schema")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL without executing",
    )
    args = parser.parse_args()

    logger.info("""
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║              Snowflake Schema Setup                              ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
    """)

    # Load configuration
    config = get_config()
    require_snowflake_config(config)

    logger.info(f"Connecting to Snowflake account: {config.snowflake_account}")

    # Connect to Snowflake
    try:
        conn = snowflake.connector.connect(
            account=config.snowflake_account,
            user=config.snowflake_user,
            password=config.snowflake_password,
            warehouse=config.snowflake_warehouse,
            # Don't specify database/schema - we'll create them
            role=config.snowflake_role,
        )

        logger.info("✓ Connected to Snowflake")

        # Execute SQL file
        sql_file = Path(__file__).parent / "setup_snowflake.sql"

        if not sql_file.exists():
            logger.error(f"SQL file not found: {sql_file}")
            sys.exit(1)

        execute_sql_file(conn, sql_file, dry_run=args.dry_run)

        if not args.dry_run:
            logger.info("\n" + "=" * 60)
            logger.info("SETUP COMPLETE")
            logger.info("=" * 60)
            logger.info(f"\nDatabase: {config.snowflake_database}")
            logger.info(f"Warehouse: {config.snowflake_warehouse}")
            logger.info("\nSchemas created:")
            logger.info("  - RAW (for raw data loads)")
            logger.info("  - STAGING (for dbt staging models)")
            logger.info("  - ANALYTICS (for dbt marts)")
            logger.info("  - METADATA (for pipeline tracking)")
            logger.info("\nNext steps:")
            logger.info("  1. Generate test data: python scripts/generate_all_data.py")
            logger.info("  2. Run extraction: python scripts/run_extraction.py")
            logger.info("  3. Load to Snowflake: python scripts/run_pipeline.py")

        conn.close()

    except snowflake.connector.errors.DatabaseError as e:
        logger.error(f"Snowflake connection failed: {e}")
        logger.error("\nCheck your .env file for correct credentials:")
        logger.error("  SNOWFLAKE_ACCOUNT")
        logger.error("  SNOWFLAKE_USER")
        logger.error("  SNOWFLAKE_PASSWORD")
        sys.exit(1)

    except Exception as e:
        logger.error(f"Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
