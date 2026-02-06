"""
Extraction Pipeline Orchestrator

Runs all extractors (CSV, PDF, OCR) to process raw files into staging DataFrames.

This script demonstrates the **orchestration pattern**:
1. Discover files in raw directories
2. Route each file to appropriate extractor
3. Handle failures gracefully (quarantine, don't crash)
4. Write extracted data to staging
5. Log summary statistics

Key Design Decisions:
---------------------
- Fail gracefully: One bad file shouldn't stop the whole pipeline
- Quarantine pattern: Save unparseable files for manual review
- Metadata tracking: Record source file, extraction time, success/failure
- Idempotent: Can safely re-run without duplicates

Usage:
    # Process all files
    python scripts/run_extraction.py

    # Process specific date range
    python scripts/run_extraction.py --start-date 2024-01-01 --end-date 2024-01-31

    # Dry run (validate without writing)
    python scripts/run_extraction.py --dry-run
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import logging
import json

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extractors.csv_extractor import CSVExtractor
from src.extractors.pdf_extractor import PDFExtractor
from src.extractors.ocr_extractor import OCRExtractor
from src.utils.config import get_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def setup_directories(config):
    """
    Ensure staging and quarantine directories exist.

    Directory structure:
    data/
    ├── staging/          # Successfully extracted data
    │   ├── invoices/
    │   ├── receipts/
    │   └── items/
    └── quarantine/       # Failed extractions for review
        ├── invoices/
        ├── receipts/
        └── items/
    """
    staging_dir = config.staging_data_dir
    quarantine_dir = config.quarantine_data_dir

    for subdir in ["invoices", "receipts", "items"]:
        (staging_dir / subdir).mkdir(parents=True, exist_ok=True)
        (quarantine_dir / subdir).mkdir(parents=True, exist_ok=True)

    logger.info(f"✓ Directories ready: {staging_dir}, {quarantine_dir}")


def extract_csv_files(config, dry_run=False):
    """
    Extract CSV files (item master, price changes).

    Returns:
        Dict with statistics (files_processed, success_count, failure_count)
    """
    logger.info("\n" + "=" * 60)
    logger.info("EXTRACTING CSV FILES")
    logger.info("=" * 60)

    raw_dir = config.raw_data_dir
    staging_dir = config.staging_data_dir
    quarantine_dir = config.quarantine_data_dir

    extractor = CSVExtractor()
    stats = {"files_processed": 0, "success": 0, "failed": 0}

    # Process item master files
    item_master_files = list((raw_dir / "item_master").glob("*.csv"))

    logger.info(f"Found {len(item_master_files)} item master file(s)")

    for csv_file in item_master_files:
        stats["files_processed"] += 1

        try:
            df = extractor.extract(csv_file)

            logger.info(
                f"✓ Extracted {len(df):,} rows from {csv_file.name} "
                f"(encoding: {df.attrs['encoding']})"
            )

            if not dry_run:
                # Write to staging as Parquet (more efficient than CSV)
                output_file = staging_dir / "items" / f"{csv_file.stem}.parquet"
                df.to_parquet(output_file, index=False)
                logger.info(f"  → Saved to {output_file}")

            stats["success"] += 1

        except Exception as e:
            logger.error(f"✗ Failed to extract {csv_file.name}: {e}")

            if not dry_run:
                # Quarantine the file
                quarantine_file = quarantine_dir / "items" / csv_file.name
                import shutil
                shutil.copy(csv_file, quarantine_file)

                # Save error info
                error_info = {
                    "file": str(csv_file),
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                }
                error_file = quarantine_file.with_suffix(".error.json")
                error_file.write_text(json.dumps(error_info, indent=2))

                logger.info(f"  → Quarantined to {quarantine_file}")

            stats["failed"] += 1

    return stats


def extract_pdf_files(config, dry_run=False):
    """
    Extract PDF invoice files.

    Returns:
        Dict with statistics
    """
    logger.info("\n" + "=" * 60)
    logger.info("EXTRACTING PDF INVOICES")
    logger.info("=" * 60)

    raw_dir = config.raw_data_dir / "invoices"
    staging_dir = config.staging_data_dir / "invoices"
    quarantine_dir = config.quarantine_data_dir / "invoices"

    pdf_files = list(raw_dir.glob("*.pdf"))

    logger.info(f"Found {len(pdf_files)} PDF invoice(s)")

    extractor = PDFExtractor()
    stats = {"files_processed": 0, "success": 0, "failed": 0}

    for pdf_file in pdf_files:
        stats["files_processed"] += 1

        result = extractor.extract(pdf_file)

        if result and result["success"]:
            logger.info(
                f"✓ Extracted {pdf_file.name} "
                f"({len(result['line_items'])} line items, "
                f"method: {result['extraction_method']})"
            )

            if not dry_run:
                # Save line items to Parquet
                output_file = staging_dir / f"{pdf_file.stem}_lines.parquet"
                result["line_items"].to_parquet(output_file, index=False)

                # Save metadata to JSON
                metadata_file = staging_dir / f"{pdf_file.stem}_metadata.json"
                metadata = {
                    **result["metadata"],
                    **result["totals"],
                    "extraction_method": result["extraction_method"],
                    "source_file": str(pdf_file),
                }
                metadata_file.write_text(json.dumps(metadata, indent=2))

                logger.info(f"  → Saved to {output_file}")

            stats["success"] += 1

        else:
            logger.warning(f"✗ Failed to extract {pdf_file.name}")

            if not dry_run:
                # Quarantine
                import shutil
                quarantine_file = quarantine_dir / pdf_file.name
                shutil.copy(pdf_file, quarantine_file)

                error_info = {
                    "file": str(pdf_file),
                    "error": result.get("error", "Unknown") if result else "No result",
                    "timestamp": datetime.now().isoformat(),
                }
                error_file = quarantine_file.with_suffix(".error.json")
                error_file.write_text(json.dumps(error_info, indent=2))

                logger.info(f"  → Quarantined to {quarantine_file}")

            stats["failed"] += 1

    return stats


def extract_receipt_images(config, dry_run=False, min_confidence=60.0):
    """
    Extract receipt images using OCR.

    Args:
        min_confidence: Minimum OCR confidence to accept (0-100)

    Returns:
        Dict with statistics
    """
    logger.info("\n" + "=" * 60)
    logger.info("EXTRACTING RECEIPT IMAGES (OCR)")
    logger.info("=" * 60)

    raw_dir = config.raw_data_dir / "receipts"
    staging_dir = config.staging_data_dir / "receipts"
    quarantine_dir = config.quarantine_data_dir / "receipts"

    image_files = list(raw_dir.glob("*.png")) + list(raw_dir.glob("*.jpg"))

    logger.info(f"Found {len(image_files)} receipt image(s)")

    extractor = OCRExtractor()
    stats = {"files_processed": 0, "success": 0, "failed": 0, "low_confidence": 0}

    for image_file in image_files:
        stats["files_processed"] += 1

        result = extractor.extract(image_file)

        if result["success"]:
            confidence = result["confidence"]

            if confidence >= min_confidence:
                logger.info(
                    f"✓ Extracted {image_file.name} "
                    f"(confidence: {confidence:.1f}%, "
                    f"words: {result['word_count']})"
                )

                if not dry_run:
                    # Save OCR text
                    text_file = staging_dir / f"{image_file.stem}.txt"
                    text_file.write_text(result["raw_text"])

                    # Save structured data
                    metadata_file = staging_dir / f"{image_file.stem}_metadata.json"
                    metadata = {
                        **result["structured_data"],
                        "confidence": confidence,
                        "word_count": result["word_count"],
                        "source_file": str(image_file),
                    }
                    metadata_file.write_text(json.dumps(metadata, indent=2))

                    logger.info(f"  → Saved to {text_file}")

                stats["success"] += 1

            else:
                logger.warning(
                    f"⚠ Low confidence ({confidence:.1f}%) for {image_file.name}"
                )

                if not dry_run:
                    # Quarantine low-confidence results
                    import shutil
                    quarantine_file = quarantine_dir / image_file.name
                    shutil.copy(image_file, quarantine_file)

                    error_info = {
                        "file": str(image_file),
                        "error": f"Low confidence: {confidence:.1f}%",
                        "ocr_text": result["raw_text"][:500],  # First 500 chars
                        "timestamp": datetime.now().isoformat(),
                    }
                    error_file = quarantine_file.with_suffix(".error.json")
                    error_file.write_text(json.dumps(error_info, indent=2))

                stats["low_confidence"] += 1

        else:
            logger.error(f"✗ OCR failed for {image_file.name}: {result.get('error')}")

            if not dry_run:
                import shutil
                quarantine_file = quarantine_dir / image_file.name
                shutil.copy(image_file, quarantine_file)

                error_info = {
                    "file": str(image_file),
                    "error": result.get("error", "Unknown"),
                    "timestamp": datetime.now().isoformat(),
                }
                error_file = quarantine_file.with_suffix(".error.json")
                error_file.write_text(json.dumps(error_info, indent=2))

            stats["failed"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Run extraction pipeline on raw data files"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate files without writing output",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=60.0,
        help="Minimum OCR confidence threshold (0-100)",
    )
    args = parser.parse_args()

    # Load configuration
    config = get_config()

    logger.info("""
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║              Retail Onboarding Pipeline - Extraction             ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
    """)

    if args.dry_run:
        logger.info("DRY RUN MODE - No files will be written\n")

    # Setup directories
    setup_directories(config)

    # Run extractors
    csv_stats = extract_csv_files(config, dry_run=args.dry_run)
    pdf_stats = extract_pdf_files(config, dry_run=args.dry_run)
    ocr_stats = extract_receipt_images(
        config,
        dry_run=args.dry_run,
        min_confidence=args.min_confidence
    )

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("EXTRACTION SUMMARY")
    logger.info("=" * 60)

    logger.info(f"\nCSV Files:")
    logger.info(f"  Processed: {csv_stats['files_processed']}")
    logger.info(f"  Success:   {csv_stats['success']}")
    logger.info(f"  Failed:    {csv_stats['failed']}")

    logger.info(f"\nPDF Invoices:")
    logger.info(f"  Processed: {pdf_stats['files_processed']}")
    logger.info(f"  Success:   {pdf_stats['success']}")
    logger.info(f"  Failed:    {pdf_stats['failed']}")

    logger.info(f"\nReceipt Images:")
    logger.info(f"  Processed:      {ocr_stats['files_processed']}")
    logger.info(f"  Success:        {ocr_stats['success']}")
    logger.info(f"  Low confidence: {ocr_stats['low_confidence']}")
    logger.info(f"  Failed:         {ocr_stats['failed']}")

    total_files = (
        csv_stats["files_processed"]
        + pdf_stats["files_processed"]
        + ocr_stats["files_processed"]
    )
    total_success = (
        csv_stats["success"]
        + pdf_stats["success"]
        + ocr_stats["success"]
    )
    total_failed = (
        csv_stats["failed"]
        + pdf_stats["failed"]
        + ocr_stats["failed"]
        + ocr_stats["low_confidence"]
    )

    logger.info(f"\nOverall:")
    logger.info(f"  Total files:    {total_files}")
    logger.info(f"  Success:        {total_success} ({total_success/total_files*100:.1f}%)")
    logger.info(f"  Failed/Quarant: {total_failed} ({total_failed/total_files*100:.1f}%)")

    logger.info("=" * 60)

    if not args.dry_run:
        logger.info(f"\n✓ Extracted data saved to: {config.staging_data_dir}")
        logger.info(f"✓ Quarantined files in: {config.quarantine_data_dir}")
        logger.info("\nNext steps:")
        logger.info("  1. Review quarantined files for manual processing")
        logger.info("  2. Load staging data to Snowflake: python scripts/run_pipeline.py")
    else:
        logger.info("\nDry run complete. No files were written.")


if __name__ == "__main__":
    main()
