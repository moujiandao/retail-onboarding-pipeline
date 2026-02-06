"""
Generate Item Master CSV with Realistic Quality Issues

This script creates a synthetic grocery product catalog with intentionally
seeded data quality problems that mirror real retail systems.

Why generate bad data?
- Tests validation logic (can we catch duplicate UPCs?)
- Demonstrates defensive coding (handle encoding issues)
- Shows domain knowledge (these are REAL problems in retail)

Quality issues included:
- Duplicate UPCs (same barcode, different products)
- Missing UPCs (legacy items without barcodes)
- Encoding issues (UTF-8 vs ISO-8859-1 corruption)
- Inconsistent units ("LB" vs "lb" vs "pound")
- Invalid prices (cost = 0, retail < cost)
- Orphaned vendor IDs (foreign key violations)
- Stale records (ACTIVE but not sold in years)

Usage:
    python scripts/generate_item_master.py --num-skus 15000 --output data/raw/item_master/
"""

import argparse
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd


# =============================================================================
# Product Taxonomy - Realistic Grocery Categories
# =============================================================================

DEPARTMENTS = {
    "100": "Produce",
    "200": "Dairy",
    "300": "Meat & Seafood",
    "400": "Bakery",
    "500": "Frozen",
    "600": "Grocery",
    "700": "Beverages",
    "800": "Health & Beauty",
    "900": "General Merchandise",
}

# Realistic product templates by category
# Format: (description_template, brand_options, unit_size_range, unit_measure, pack_size)
PRODUCT_TEMPLATES = {
    "Produce": [
        ("Organic {variety} Bananas", ["Dole", "Chiquita", "Del Monte"], (1.0, 1.0), "LB", 1),
        ("{variety} Apples", ["Honeycrisp", "Gala", "Fuji", "Granny Smith"], (1.0, 3.0), "LB", 1),
        ("Romaine Lettuce {variety}", ["Organic", "Conventional", "Hydroponic"], (1.0, 1.0), "EA", 1),
        ("{variety} Tomatoes", ["Cherry", "Grape", "Roma", "Beefsteak"], (1.0, 2.0), "LB", 1),
        ("Kale {variety}", ["Curly", "Lacinato", "Red Russian"], (1.0, 1.0), "BUNCH", 1),
    ],
    "Dairy": [
        ("{fat} Milk", ["Whole", "2%", "1%", "Skim"], (0.5, 1.0), "GAL", 1),
        ("{variety} Yogurt", ["Greek", "Regular", "Icelandic"], (6.0, 32.0), "OZ", 1),
        ("{type} Cheese", ["Cheddar", "Mozzarella", "Swiss", "Pepper Jack"], (8.0, 16.0), "OZ", 1),
        ("Butter {variety}", ["Salted", "Unsalted", "European Style"], (16.0, 16.0), "OZ", 1),
        ("{variety} Eggs", ["Large", "Extra Large", "Jumbo"], (12.0, 18.0), "CT", 1),
    ],
    "Meat & Seafood": [
        ("{cut} Beef", ["Ground", "Ribeye", "Sirloin", "Chuck Roast"], (1.0, 1.0), "LB", 1),
        ("{cut} Chicken", ["Breast", "Thighs", "Drumsticks", "Whole"], (1.0, 1.0), "LB", 1),
        ("{type} Salmon", ["Atlantic", "Sockeye", "Coho"], (1.0, 1.0), "LB", 1),
        ("{variety} Shrimp", ["Raw", "Cooked", "Peeled"], (16.0, 16.0), "OZ", 1),
    ],
    "Bakery": [
        ("{variety} Bread", ["Whole Wheat", "Sourdough", "White", "Multigrain"], (24.0, 24.0), "OZ", 1),
        ("{type} Bagels", ["Plain", "Everything", "Sesame"], (6.0, 12.0), "CT", 1),
        ("{flavor} Muffins", ["Blueberry", "Chocolate Chip", "Bran"], (4.0, 6.0), "CT", 1),
    ],
    "Frozen": [
        ("{flavor} Ice Cream", ["Vanilla", "Chocolate", "Strawberry"], (48.0, 64.0), "OZ", 1),
        ("Frozen {vegetable}", ["Peas", "Corn", "Green Beans", "Mixed Vegetables"], (16.0, 16.0), "OZ", 1),
        ("{type} Pizza", ["Pepperoni", "Cheese", "Supreme"], (24.0, 36.0), "OZ", 1),
    ],
    "Grocery": [
        ("{variety} Pasta", ["Spaghetti", "Penne", "Rigatoni"], (16.0, 16.0), "OZ", 1),
        ("{type} Rice", ["White", "Brown", "Basmati", "Jasmine"], (32.0, 80.0), "OZ", 1),
        ("{flavor} Cereal", ["Corn Flakes", "Cheerios", "Raisin Bran"], (18.0, 24.0), "OZ", 1),
        ("{variety} Soup", ["Tomato", "Chicken Noodle", "Vegetable"], (10.5, 18.0), "OZ", 1),
    ],
    "Beverages": [
        ("{flavor} Soda", ["Cola", "Lemon-Lime", "Orange"], (12.0, 67.6), "OZ", 6),
        ("{variety} Coffee", ["Colombian", "French Roast", "Breakfast Blend"], (12.0, 16.0), "OZ", 1),
        ("{flavor} Juice", ["Orange", "Apple", "Cranberry"], (64.0, 64.0), "OZ", 1),
    ],
    "Health & Beauty": [
        ("{type} Shampoo", ["Moisturizing", "Volumizing", "Color Safe"], (16.0, 24.0), "OZ", 1),
        ("{variety} Toothpaste", ["Whitening", "Sensitive", "Fresh Mint"], (6.0, 6.0), "OZ", 1),
    ],
}

# Vendor names (realistic distributors and suppliers)
VENDORS = [
    ("VEND-001", "UNFI - United Natural Foods"),
    ("VEND-002", "KeHE Distributors"),
    ("VEND-003", "C&S Wholesale Grocers"),
    ("VEND-004", "Fresh Direct Produce"),
    ("VEND-005", "Mountain Valley Dairy"),
    ("VEND-006", "Pacific Seafood"),
    ("VEND-007", "Sysco Foods"),
    ("VEND-008", "US Foods"),
    ("VEND-009", "Organic Valley Cooperative"),
    ("VEND-010", "Green Acres Farm"),
]

# Unit measure variations (for inconsistency)
UNIT_VARIATIONS = {
    "LB": ["LB", "lb", "Lb", "pound", "POUND", "lbs", "LBS"],
    "OZ": ["OZ", "oz", "Oz", "ounce", "OUNCE", "FL OZ"],
    "EA": ["EA", "ea", "each", "EACH"],
    "GAL": ["GAL", "gal", "gallon", "GALLON"],
    "CT": ["CT", "ct", "count", "COUNT"],
    "BUNCH": ["BUNCH", "bunch", "Bunch"],
}


def generate_upc() -> str:
    """
    Generate a realistic UPC-A barcode (12 digits).

    Real UPCs have a check digit calculated by the Luhn algorithm,
    but we'll simplify for mock data.
    """
    # First 6 digits = manufacturer code
    # Next 5 digits = product code
    # Last digit = check digit (we'll just use random)
    return f"{random.randint(100000, 999999):06d}{random.randint(10000, 99999):05d}{random.randint(0, 9)}"


def generate_sku() -> str:
    """Generate internal SKU (format: GRN-XXXXXX)."""
    return f"GRN-{random.randint(100000, 999999):06d}"


def corrupt_encoding(text: str, probability: float = 0.08) -> str:
    """
    Simulate encoding corruption (UTF-8 decoded as ISO-8859-1).

    Common when legacy systems export in Windows-1252 and modern
    systems expect UTF-8.

    Examples:
    - "Jalapeño" → "JalapeÃ±o"
    - "Café" → "CafÃ©"
    """
    if random.random() > probability:
        return text

    # Common character corruptions
    replacements = {
        "ñ": "Ã±",
        "é": "Ã©",
        "á": "Ã¡",
        "í": "Ã­",
        "ó": "Ã³",
        "ú": "Ãº",
        "ü": "Ã¼",
        "Ñ": "Ã'",
    }

    for original, corrupted in replacements.items():
        if original in text:
            text = text.replace(original, corrupted)
            break  # Only corrupt one character

    return text


def generate_product(category: str, department_code: str) -> Dict[str, Any]:
    """Generate a single product record."""
    template = random.choice(PRODUCT_TEMPLATES[category])
    desc_template, variety_options, size_range, unit_measure, pack_size = template

    # Generate description
    if "{variety}" in desc_template or "{type}" in desc_template or "{flavor}" in desc_template or "{cut}" in desc_template or "{fat}" in desc_template or "{vegetable}" in desc_template:
        variety = random.choice(variety_options) if isinstance(variety_options, list) else variety_options[0]
        description = desc_template.format(
            variety=variety, type=variety, flavor=variety, cut=variety, fat=variety, vegetable=variety
        )
    else:
        description = desc_template

    # Generate brand (some products are "Store Brand")
    brand = random.choice(variety_options + ["Store Brand", "Generic"]) if random.random() > 0.3 else "Store Brand"

    # Generate size
    unit_size = round(random.uniform(*size_range), 2) if isinstance(size_range, tuple) else size_range

    # Select vendor
    vendor_id, vendor_name = random.choice(VENDORS)

    # Generate pricing
    # Cost-to-retail margin typically 30-50% for grocery
    cost = round(random.uniform(0.50, 25.00), 2)
    margin_pct = random.uniform(30, 50)
    retail_price = round(cost / (1 - margin_pct / 100), 2)

    # Status
    status = "ACTIVE" if random.random() > 0.15 else "INACTIVE"

    # Dates
    created_date = datetime.now() - timedelta(days=random.randint(365, 365 * 5))
    modified_date = created_date + timedelta(days=random.randint(0, 365 * 3))

    return {
        "upc": generate_upc(),
        "sku": generate_sku(),
        "description": corrupt_encoding(description),
        "brand": brand,
        "category": category,
        "subcategory": random.choice(variety_options) if isinstance(variety_options, list) else variety_options,
        "department": department_code,
        "unit_size": unit_size,
        "unit_measure": unit_measure,  # We'll vary this later
        "pack_size": pack_size,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "cost": cost,
        "retail_price": retail_price,
        "margin_pct": round(margin_pct, 1),
        "status": status,
        "created_date": created_date.strftime("%Y-%m-%d"),
        "modified_date": modified_date.strftime("%Y-%m-%d"),
    }


def introduce_quality_issues(df: pd.DataFrame) -> pd.DataFrame:
    """
    Intentionally introduce data quality issues.

    This is the key function that makes the data realistic.
    """
    df = df.copy()

    # Issue 1: Missing UPCs (5%)
    missing_upc_mask = df.sample(frac=0.05).index
    df.loc[missing_upc_mask, "upc"] = None
    print(f"  ✓ Introduced {len(missing_upc_mask)} missing UPCs (5%)")

    # Issue 2: Duplicate UPCs (2%)
    # Take 2% of rows and copy their UPC to another row
    num_duplicates = int(len(df) * 0.02)
    duplicate_upcs = df.sample(n=num_duplicates)["upc"].values
    duplicate_targets = df.sample(n=num_duplicates).index
    df.loc[duplicate_targets, "upc"] = duplicate_upcs
    print(f"  ✓ Introduced {num_duplicates} duplicate UPCs (2%)")

    # Issue 3: Inconsistent unit measures (15%)
    inconsistent_mask = df.sample(frac=0.15).index
    for idx in inconsistent_mask:
        original_unit = df.loc[idx, "unit_measure"]
        if original_unit in UNIT_VARIATIONS:
            df.loc[idx, "unit_measure"] = random.choice(UNIT_VARIATIONS[original_unit])
    print(f"  ✓ Introduced {len(inconsistent_mask)} inconsistent units (15%)")

    # Issue 4: Invalid prices (1%)
    # Some products have cost = 0 or retail < cost
    invalid_price_mask = df.sample(frac=0.01).index
    for idx in invalid_price_mask:
        issue_type = random.choice(["zero_cost", "negative_margin"])
        if issue_type == "zero_cost":
            df.loc[idx, "cost"] = 0.00
        else:
            # Retail less than cost (negative margin)
            df.loc[idx, "retail_price"] = df.loc[idx, "cost"] * 0.8
            df.loc[idx, "margin_pct"] = -20.0
    print(f"  ✓ Introduced {len(invalid_price_mask)} invalid prices (1%)")

    # Issue 5: Orphaned vendor IDs (3%)
    # Reference vendors that don't exist
    orphaned_mask = df.sample(frac=0.03).index
    df.loc[orphaned_mask, "vendor_id"] = "VEND-999"
    df.loc[orphaned_mask, "vendor_name"] = "Unknown Vendor"
    print(f"  ✓ Introduced {len(orphaned_mask)} orphaned vendor IDs (3%)")

    # Issue 6: Stale data (10% of ACTIVE records)
    # Items marked ACTIVE but haven't been modified in 2+ years
    active_mask = df[df["status"] == "ACTIVE"].index
    stale_mask = df.loc[active_mask].sample(frac=0.10).index
    old_date = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    df.loc[stale_mask, "modified_date"] = old_date
    print(f"  ✓ Introduced {len(stale_mask)} stale ACTIVE records (10% of active)")

    return df


def generate_item_master(num_skus: int = 15000) -> pd.DataFrame:
    """
    Generate complete item master with realistic distribution across categories.
    """
    products = []

    # Calculate distribution across departments
    # Grocery has most SKUs, followed by beverages, produce, etc.
    distribution = {
        "Produce": 0.15,
        "Dairy": 0.12,
        "Meat & Seafood": 0.08,
        "Bakery": 0.06,
        "Frozen": 0.14,
        "Grocery": 0.30,
        "Beverages": 0.10,
        "Health & Beauty": 0.05,
    }

    print(f"Generating {num_skus:,} product SKUs...")

    for category, pct in distribution.items():
        num_category = int(num_skus * pct)
        dept_code = [code for code, name in DEPARTMENTS.items() if name == category][0]

        print(f"  Generating {num_category:,} {category} items...")

        for _ in range(num_category):
            products.append(generate_product(category, dept_code))

    df = pd.DataFrame(products)

    print(f"\n✓ Generated {len(df):,} products")
    print(f"\nIntroducing data quality issues...")

    df = introduce_quality_issues(df)

    return df


def main():
    parser = argparse.ArgumentParser(description="Generate item master CSV with quality issues")
    parser.add_argument("--num-skus", type=int, default=15000, help="Number of SKUs to generate")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/item_master"),
        help="Output directory",
    )
    args = parser.parse_args()

    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)

    # Generate data
    df = generate_item_master(args.num_skus)

    # Save to CSV
    timestamp = datetime.now().strftime("%Y%m%d")
    output_file = args.output / f"item_master_{timestamp}.csv"

    df.to_csv(output_file, index=False)

    print(f"\n✓ Saved to {output_file}")
    print(f"\nSummary Statistics:")
    print(f"  Total SKUs: {len(df):,}")
    print(f"  Active: {len(df[df['status'] == 'ACTIVE']):,}")
    print(f"  Inactive: {len(df[df['status'] == 'INACTIVE']):,}")
    print(f"  Missing UPCs: {df['upc'].isna().sum():,}")
    print(f"  Duplicate UPCs: {df['upc'].duplicated().sum():,}")
    print(f"  Unique Vendors: {df['vendor_id'].nunique()}")
    print(f"  Price range: ${df['retail_price'].min():.2f} - ${df['retail_price'].max():.2f}")


if __name__ == "__main__":
    main()
