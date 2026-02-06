"""
Master Data Generation Script

Runs all data generators in the correct order to create a complete
synthetic dataset for the retail onboarding pipeline.

This script orchestrates:
1. Item master CSV (products catalog)
2. Price change CSV (price history)
3. Vendor invoices PDF (vendor bills)
4. Receipt images PNG (transaction data)

Usage:
    python scripts/generate_all_data.py

    # Custom sizes
    python scripts/generate_all_data.py --num-skus 10000 --num-invoices 75 --num-receipts 100

Why run all generators together?
- Ensures consistent data (same SKUs referenced across sources)
- Faster than running individually
- Single command for new developers to set up test data
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_generator(script_name: str, args: list) -> bool:
    """
    Run a generator script and return success status.

    Args:
        script_name: Name of the generator script (e.g., "generate_item_master.py")
        args: List of command-line arguments

    Returns:
        True if successful, False otherwise
    """
    cmd = [sys.executable, f"scripts/{script_name}"] + args

    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    result = subprocess.run(cmd, capture_output=False)

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate all synthetic data for the pipeline"
    )
    parser.add_argument(
        "--num-skus",
        type=int,
        default=15000,
        help="Number of product SKUs to generate"
    )
    parser.add_argument(
        "--num-invoices",
        type=int,
        default=100,
        help="Number of vendor invoices to generate"
    )
    parser.add_argument(
        "--num-receipts",
        type=int,
        default=50,
        help="Number of receipt images to generate"
    )
    parser.add_argument(
        "--num-price-changes",
        type=int,
        default=500,
        help="Number of price change records to generate"
    )

    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║           Retail Onboarding Pipeline - Data Generator           ║
║                                                                  ║
║  This will generate synthetic grocery data with intentional     ║
║  quality issues to demonstrate real-world data challenges.      ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
    """)

    print(f"Configuration:")
    print(f"  Product SKUs: {args.num_skus:,}")
    print(f"  Invoices: {args.num_invoices:,}")
    print(f"  Receipts: {args.num_receipts:,}")
    print(f"  Price Changes: {args.num_price_changes:,}")
    print()

    # Track success/failure
    results = {}

    # 1. Generate item master
    print("\n[1/4] Generating Item Master CSV...")
    success = run_generator(
        "generate_item_master.py",
        ["--num-skus", str(args.num_skus)]
    )
    results["Item Master"] = success

    if not success:
        print("⚠️  Item master generation failed!")
        print("   Other generators will continue, but may reference non-existent SKUs")

    # 2. Generate price changes
    print("\n[2/4] Generating Price Change CSV...")
    success = run_generator(
        "generate_price_changes.py",
        ["--num-changes", str(args.num_price_changes)]
    )
    results["Price Changes"] = success

    # 3. Generate invoices
    print("\n[3/4] Generating Vendor Invoice PDFs...")
    success = run_generator(
        "generate_invoices.py",
        ["--num-invoices", str(args.num_invoices)]
    )
    results["Invoices"] = success

    # 4. Generate receipts
    print("\n[4/4] Generating Receipt Images...")
    success = run_generator(
        "generate_receipts.py",
        ["--num-receipts", str(args.num_receipts)]
    )
    results["Receipts"] = success

    # Summary
    print("\n" + "="*60)
    print("DATA GENERATION SUMMARY")
    print("="*60)

    all_success = True
    for name, success in results.items():
        status = "✓ Success" if success else "✗ Failed"
        print(f"{name:20s} {status}")
        if not success:
            all_success = False

    print("="*60)

    if all_success:
        print("\n✓ All data generated successfully!")
        print("\nNext steps:")
        print("  1. Verify data in data/raw/ directories")
        print("  2. Run extraction pipeline: python scripts/run_extraction.py")
        print("  3. Load to Snowflake: python scripts/run_pipeline.py")
    else:
        print("\n⚠️  Some generators failed. Check logs above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
