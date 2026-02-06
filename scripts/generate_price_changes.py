"""
Generate Price Change CSV with Temporal Complexity

Creates realistic price change history with intentional temporal issues:
- Overlapping effective date ranges (two prices active simultaneously)
- Missing end dates (promotions without expiration)
- Future-dated changes (scheduled price changes)
- Gap in price history (price jumps with no audit trail)
- Invalid transitions (old_price doesn't match previous new_price)

Why this matters:
Price history is a Slowly Changing Dimension (SCD) problem. Handling temporal
overlap and gaps correctly is critical for:
- Accurate margin analysis over time
- Promotion effectiveness measurement
- Price elasticity modeling
- Preventing revenue leakage from pricing errors

This demonstrates understanding of temporal data challenges beyond simple
point-in-time snapshots.

Usage:
    python scripts/generate_price_changes.py --num-changes 500 --output data/raw/
"""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

import pandas as pd


# Price change reason codes (realistic retail scenarios)
REASON_CODES = {
    "PROMO": [
        ("WEEKLY_AD", "Weekly circular promotion"),
        ("BOGO", "Buy one get one promotion"),
        ("CLEARANCE", "Clearance pricing"),
        ("SEASONAL", "Seasonal promotion"),
        ("MANAGER_SPECIAL", "Manager's special"),
    ],
    "COST": [
        ("VENDOR_INCREASE", "Vendor cost increase"),
        ("VENDOR_DECREASE", "Vendor cost decrease"),
        ("FREIGHT_SURCHARGE", "Freight cost adjustment"),
    ],
    "COMPETITIVE": [
        ("PRICE_MATCH", "Competitive price match"),
        ("MARKET_ADJUST", "Market-driven adjustment"),
    ],
    "REGULAR": [
        ("PROMO_END", "Return to regular price"),
        ("NEW_ITEM", "Initial pricing for new item"),
        ("PRICE_CORRECTION", "Correcting pricing error"),
    ],
}

# User IDs for approval tracking
APPROVERS = ["jsmith", "mdavis", "skumar", "lchen", "system"]


def generate_base_prices(num_skus: int = 1000) -> Dict[str, float]:
    """
    Generate base prices for a subset of SKUs.

    In reality, you'd join to the item master, but for this generator
    we'll create a standalone price change file.
    """
    prices = {}
    for i in range(num_skus):
        sku = f"GRN-{random.randint(100000, 999999):06d}"
        # Base price between $0.99 and $29.99
        base_price = round(random.uniform(0.99, 29.99), 2)
        prices[sku] = base_price

    return prices


def generate_promotion_cycle(
    sku: str,
    base_price: float,
    start_date: datetime,
) -> List[Dict]:
    """
    Generate a realistic promotion cycle for a product.

    Typical pattern:
    1. Regular price
    2. Promotion (reduce 10-40%)
    3. Return to regular price
    4. Sometimes: new regular price (vendor cost changed)
    """
    changes = []
    current_date = start_date
    current_price = base_price

    # How many cycles? (1-4 over the time period)
    num_cycles = random.randint(1, 4)

    for i in range(num_cycles):
        # Promotion
        promo_discount = random.uniform(0.10, 0.40)
        promo_price = round(current_price * (1 - promo_discount), 2)

        # Promotion duration (typically 1-2 weeks)
        promo_duration = random.randint(7, 14)

        reason_code, reason_desc = random.choice(REASON_CODES["PROMO"])

        changes.append({
            "sku": sku,
            "effective_date": current_date,
            "end_date": current_date + timedelta(days=promo_duration),
            "price_type": "PROMO",
            "old_price": current_price,
            "new_price": promo_price,
            "reason_code": reason_code,
            "reason_description": reason_desc,
            "approved_by": random.choice(APPROVERS[:-1]),  # Not system
            "approved_date": current_date - timedelta(days=random.randint(1, 7)),
        })

        # Return to regular price
        current_date = current_date + timedelta(days=promo_duration)

        # Sometimes vendor cost changed during promotion
        if random.random() > 0.8:
            # Cost increase/decrease
            cost_change = random.uniform(-0.10, 0.15)
            new_regular_price = round(current_price * (1 + cost_change), 2)
            reason_code, reason_desc = random.choice(
                REASON_CODES["COST"] if cost_change > 0 else REASON_CODES["COMPETITIVE"]
            )
        else:
            # Back to original price
            new_regular_price = current_price
            reason_code = "PROMO_END"
            reason_desc = "Return to regular price"

        changes.append({
            "sku": sku,
            "effective_date": current_date,
            "end_date": None,  # Open-ended until next change
            "price_type": "REGULAR",
            "old_price": promo_price,
            "new_price": new_regular_price,
            "reason_code": reason_code,
            "reason_description": reason_desc,
            "approved_by": "system" if reason_code == "PROMO_END" else random.choice(APPROVERS[:-1]),
            "approved_date": current_date,
        })

        current_price = new_regular_price

        # Gap before next promotion (2-8 weeks)
        current_date = current_date + timedelta(days=random.randint(14, 56))

    return changes


def introduce_temporal_issues(df: pd.DataFrame) -> pd.DataFrame:
    """
    Intentionally introduce temporal data quality issues.

    These are the kinds of problems that break time-series analysis
    and require sophisticated validation logic to catch.
    """
    df = df.copy()

    # Issue 1: Overlapping date ranges (5%)
    # Two price changes with overlapping effective dates
    print("Introducing temporal issues...")

    overlapping_skus = df["sku"].unique()[:int(len(df["sku"].unique()) * 0.05)]
    for sku in overlapping_skus:
        sku_prices = df[df["sku"] == sku].sort_values("effective_date")
        if len(sku_prices) >= 2:
            # Make second price change start before first one ends
            idx1, idx2 = sku_prices.index[:2]
            if pd.notna(df.loc[idx1, "end_date"]):
                # Move second effective_date to overlap with first
                overlap_date = df.loc[idx1, "effective_date"] + timedelta(days=3)
                df.loc[idx2, "effective_date"] = overlap_date

    print(f"  ✓ Introduced {len(overlapping_skus)} overlapping date ranges (5%)")

    # Issue 2: Missing end dates on promotions (15%)
    # Promotions should have end dates, but sometimes they're missing
    promo_mask = df["price_type"] == "PROMO"
    promo_indices = df[promo_mask].index
    missing_end_date_indices = random.sample(
        list(promo_indices),
        k=int(len(promo_indices) * 0.15)
    )
    df.loc[missing_end_date_indices, "end_date"] = None
    print(f"  ✓ Introduced {len(missing_end_date_indices)} missing end dates on promos (15%)")

    # Issue 3: Future-dated changes (2%)
    # Scheduled price changes that haven't taken effect yet
    future_mask = df.sample(frac=0.02).index
    future_date = datetime.now() + timedelta(days=random.randint(1, 30))
    for idx in future_mask:
        df.loc[idx, "effective_date"] = future_date
        df.loc[idx, "approved_date"] = datetime.now() - timedelta(days=random.randint(1, 7))
    print(f"  ✓ Introduced {len(future_mask)} future-dated changes (2%)")

    # Issue 4: Invalid price transitions (3%)
    # old_price doesn't match the previous new_price
    for sku in df["sku"].unique()[:int(len(df["sku"].unique()) * 0.03)]:
        sku_prices = df[df["sku"] == sku].sort_values("effective_date")
        if len(sku_prices) >= 2:
            # Break the chain: make old_price wrong
            idx = sku_prices.index[1]
            df.loc[idx, "old_price"] = round(df.loc[idx, "old_price"] * 1.1, 2)

    invalid_count = int(len(df["sku"].unique()) * 0.03)
    print(f"  ✓ Introduced {invalid_count} invalid price transitions (3%)")

    # Issue 5: Gaps in history (8%)
    # Price jumps with no record of the change
    gap_skus = df["sku"].unique()[:int(len(df["sku"].unique()) * 0.08)]
    for sku in gap_skus:
        sku_prices = df[df["sku"] == sku].sort_values("effective_date")
        if len(sku_prices) >= 2:
            # Delete a middle change record to create a gap
            idx_to_drop = sku_prices.index[len(sku_prices) // 2]
            df = df.drop(idx_to_drop)

    print(f"  ✓ Introduced {len(gap_skus)} gaps in price history (8%)")

    return df


def main():
    parser = argparse.ArgumentParser(
        description="Generate price change CSV with temporal issues"
    )
    parser.add_argument(
        "--num-changes",
        type=int,
        default=500,
        help="Approximate number of price changes to generate"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw"),
        help="Output directory",
    )
    args = parser.parse_args()

    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)

    # Generate base prices for subset of SKUs
    # We'll generate changes for ~200 SKUs (averaging 2-3 changes each)
    num_skus = args.num_changes // 3
    print(f"Generating price changes for {num_skus} SKUs...")

    base_prices = generate_base_prices(num_skus)

    # Generate price changes
    all_changes = []
    start_date = datetime.now() - timedelta(days=180)  # 6 months of history

    for sku, base_price in base_prices.items():
        # Not all SKUs have price changes
        if random.random() > 0.6:  # 60% have changes
            changes = generate_promotion_cycle(sku, base_price, start_date)
            all_changes.extend(changes)

    df = pd.DataFrame(all_changes)

    print(f"\n✓ Generated {len(df)} price changes for {df['sku'].nunique()} SKUs")

    # Introduce temporal issues
    print()
    df = introduce_temporal_issues(df)

    # Format dates as strings
    df["effective_date"] = df["effective_date"].dt.strftime("%Y-%m-%d")
    df["end_date"] = df["end_date"].apply(
        lambda x: x.strftime("%Y-%m-%d") if pd.notna(x) else ""
    )
    df["approved_date"] = df["approved_date"].dt.strftime("%Y-%m-%d")

    # Save to CSV
    timestamp = datetime.now().strftime("%Y%m%d")
    output_file = args.output / f"price_changes_{timestamp}.csv"

    df.to_csv(output_file, index=False)

    print(f"\n✓ Saved to {output_file}")
    print(f"\nSummary Statistics:")
    print(f"  Total price changes: {len(df):,}")
    print(f"  Unique SKUs: {df['sku'].nunique():,}")
    print(f"  Promotions: {len(df[df['price_type'] == 'PROMO']):,}")
    print(f"  Regular price changes: {len(df[df['price_type'] == 'REGULAR']):,}")
    print(f"  Missing end dates: {df['end_date'].isna().sum():,}")
    print(f"  Date range: {df['effective_date'].min()} to {df['effective_date'].max()}")

    # Show reason code distribution
    print(f"\nTop reason codes:")
    print(df["reason_code"].value_counts().head(5))


if __name__ == "__main__":
    main()
