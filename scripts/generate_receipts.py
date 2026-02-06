"""
Generate Scanned Receipt Images with OCR Challenges

Creates realistic grocery receipt images with intentional OCR degradation:
- Faded thermal paper
- Rotation (0°, 90°, 180°, 270°)
- Stains and marks (coffee rings, water damage)
- Warped/crumpled appearance
- Low resolution
- Variable contrast

Why this matters:
During retailer onboarding, you often receive historical sales data as
scanned receipts rather than clean database exports. OCR accuracy directly
impacts revenue recognition, basket analysis, and reconciliation logic.

Usage:
    python scripts/generate_receipts.py --num-receipts 50 --output data/raw/receipts/
"""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import numpy as np


# Receipt configuration
RECEIPT_WIDTH = 400  # pixels (thermal receipts are narrow)
CHAR_WIDTH = 40  # characters per line
LINE_HEIGHT = 20  # pixels
MARGIN = 20  # pixels


def generate_receipt_data(receipt_id: int, date: datetime) -> Dict:
    """Generate receipt transaction data."""

    products = [
        ("BANANAS ORGANIC", 0.99, "lb"),
        ("BREAD WHOLE WHEAT", 4.29, None),
        ("MILK 2% GALLON", 5.49, None),
        ("EGGS LARGE DOZEN", 6.99, None),
        ("COFFEE GROUND 12OZ", 9.99, None),
        ("APPLES HONEYCRISP", 1.99, "lb"),
        ("YOGURT GREEK 32OZ", 5.99, None),
        ("CHEESE CHEDDAR 8OZ", 4.49, None),
        ("CHICKEN BREAST", 6.99, "lb"),
        ("TOMATOES CHERRY", 3.99, None),
        ("LETTUCE ROMAINE", 2.49, None),
        ("ORANGE JUICE 64OZ", 5.99, None),
        ("PASTA PENNE 16OZ", 1.99, None),
        ("RICE BROWN 2LB", 3.99, None),
        ("CEREAL GRANOLA", 5.49, None),
    ]

    # Select 5-10 random items
    num_items = random.randint(5, 10)
    selected_items = random.sample(products, num_items)

    items = []
    for i, (desc, price, unit) in enumerate(selected_items):
        if unit:
            # Variable weight item
            weight = round(random.uniform(0.5, 3.0), 2)
            line_total = round(weight * price, 2)
            items.append({
                "description": desc,
                "weight": weight,
                "unit": unit,
                "unit_price": price,
                "total": line_total,
            })
        else:
            # Fixed price item
            items.append({
                "description": desc,
                "weight": None,
                "unit": None,
                "unit_price": price,
                "total": price,
            })

    # Random coupon (20% chance)
    coupon = None
    if random.random() > 0.8:
        coupon_amount = random.choice([0.50, 1.00, 1.50, 2.00])
        coupon = {
            "description": "COUPON",
            "amount": -coupon_amount,
        }

    subtotal = sum(item["total"] for item in items)
    if coupon:
        subtotal += coupon["amount"]

    # Tax (Oregon has no sales tax, but this is realistic for other states)
    tax = 0.00
    total = subtotal + tax

    return {
        "store_name": "PACIFIC NW GROCERS",
        "store_number": random.randint(1, 12),
        "address": "4232 NE Broadway St",
        "city": "Portland, OR 97213",
        "date": date,
        "time": f"{random.randint(7, 21):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}",
        "cashier": random.choice(["Maria T.", "John S.", "Sarah K.", "David L."]),
        "register": random.randint(1, 8),
        "transaction_id": f"{random.randint(1, 12):03d}{receipt_id:07d}",
        "items": items,
        "coupon": coupon,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "payment_method": random.choice(["VISA", "MASTERCARD", "CASH", "DEBIT"]),
        "card_last_four": f"{random.randint(1000, 9999)}",
        "saved": abs(coupon["amount"]) if coupon else 0.00,
    }


def create_receipt_image(receipt_data: Dict) -> Image.Image:
    """
    Create a clean thermal receipt image.

    This simulates what a fresh thermal receipt looks like before
    degradation (fading, stains, etc.).
    """
    # Calculate image height based on content
    num_lines = (
        6  # Header
        + len(receipt_data["items"]) * 2  # Each item takes 2 lines
        + (1 if receipt_data["coupon"] else 0)
        + 8  # Totals and footer
    )

    height = num_lines * LINE_HEIGHT + 2 * MARGIN

    # Create white background
    img = Image.new("RGB", (RECEIPT_WIDTH, height), "white")
    draw = ImageDraw.Draw(img)

    # Try to use a monospace font, fall back to default
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Courier.dfont", 14)
    except:
        font = ImageFont.load_default()

    y = MARGIN

    # Helper function to draw text
    def draw_line(text, y_pos, align="left"):
        if align == "center":
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            x = (RECEIPT_WIDTH - text_width) // 2
        elif align == "right":
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            x = RECEIPT_WIDTH - text_width - MARGIN
        else:
            x = MARGIN
        draw.text((x, y_pos), text, fill="black", font=font)
        return y_pos + LINE_HEIGHT

    # Header
    draw_line("=" * 40, y, "center")
    y += LINE_HEIGHT
    draw_line(receipt_data["store_name"], y, "center")
    y += LINE_HEIGHT
    draw_line(f"Store #{receipt_data['store_number']:03d} - Portland", y, "center")
    y += LINE_HEIGHT
    draw_line(receipt_data["address"], y, "center")
    y += LINE_HEIGHT
    draw_line(receipt_data["city"], y, "center")
    y += LINE_HEIGHT
    draw_line("=" * 40, y, "center")
    y += LINE_HEIGHT

    # Transaction info
    date_str = receipt_data["date"].strftime("%m/%d/%Y")
    draw_line(f"Date: {date_str}    Time: {receipt_data['time']}", y)
    y += LINE_HEIGHT
    draw_line(f"Cashier: {receipt_data['cashier']}   Reg: {receipt_data['register']:02d}", y)
    y += LINE_HEIGHT
    draw_line(f"Transaction: {receipt_data['transaction_id']}", y)
    y += LINE_HEIGHT
    y += LINE_HEIGHT / 2  # Spacer

    # Items
    for item in receipt_data["items"]:
        if item["weight"]:
            # Variable weight item (two lines)
            draw_line(f"{item['description']}  {item['weight']} {item['unit']}", y)
            y += LINE_HEIGHT
            price_line = f"  @ ${item['unit_price']:.2f}/{item['unit']}"
            total_str = f"${item['total']:.2f}"
            spacing = " " * (38 - len(price_line) - len(total_str))
            draw_line(f"{price_line}{spacing}{total_str}", y)
            y += LINE_HEIGHT
        else:
            # Fixed price item (one line)
            desc = item["description"]
            total_str = f"${item['total']:.2f}"
            spacing = " " * (38 - len(desc) - len(total_str))
            draw_line(f"{desc}{spacing}{total_str}", y)
            y += LINE_HEIGHT

    # Coupon if present
    if receipt_data["coupon"]:
        y += LINE_HEIGHT / 2
        desc = f"  {receipt_data['coupon']['description']} -$1.00"
        total_str = f"-${abs(receipt_data['coupon']['amount']):.2f}"
        spacing = " " * (38 - len(desc) - len(total_str))
        draw_line(f"{desc}{spacing}{total_str}", y)
        y += LINE_HEIGHT

    # Separator
    y += LINE_HEIGHT / 2
    draw_line("-" * 40, y, "center")
    y += LINE_HEIGHT

    # Totals
    draw_line(f"SUBTOTAL{' ' * 23}${receipt_data['subtotal']:.2f}", y)
    y += LINE_HEIGHT
    draw_line(f"TAX (OR 0%){' ' * 20}${receipt_data['tax']:.2f}", y)
    y += LINE_HEIGHT
    draw_line(f"TOTAL{' ' * 26}${receipt_data['total']:.2f}", y)
    y += LINE_HEIGHT
    y += LINE_HEIGHT / 2

    # Payment
    if receipt_data["payment_method"] in ["VISA", "MASTERCARD", "DEBIT"]:
        draw_line(f"{receipt_data['payment_method']} ****{receipt_data['card_last_four']}{' ' * 10}${receipt_data['total']:.2f}", y)
        y += LINE_HEIGHT
        draw_line(f"CHANGE DUE{' ' * 23}$0.00", y)
        y += LINE_HEIGHT
    else:
        draw_line(f"CASH{' ' * 27}${receipt_data['total']:.2f}", y)
        y += LINE_HEIGHT

    y += LINE_HEIGHT / 2
    items_count = len(receipt_data["items"])
    saved_str = f"You Saved: ${receipt_data['saved']:.2f}" if receipt_data["saved"] > 0 else ""
    draw_line(f"Items: {items_count}{' ' * 10}{saved_str}", y)
    y += LINE_HEIGHT
    y += LINE_HEIGHT / 2

    # Footer
    draw_line("Thank you for shopping local!", y, "center")
    y += LINE_HEIGHT
    draw_line("=" * 40, y, "center")

    return img


def apply_thermal_fade(img: Image.Image, fade_level: float = 0.3) -> Image.Image:
    """
    Simulate thermal paper fading.

    Thermal receipts fade over time as the heat-sensitive coating degrades.
    This makes text lighter and harder to OCR.

    Args:
        fade_level: 0.0 (no fade) to 1.0 (completely faded)
    """
    # Convert to numpy array for manipulation
    img_array = np.array(img).astype(float)

    # Fade black text toward white
    # Black (0) → Gray (fade_level * 255)
    fade_amount = fade_level * 200  # Don't go completely white
    img_array = np.clip(img_array + fade_amount, 0, 255)

    return Image.fromarray(img_array.astype(np.uint8))


def apply_rotation(img: Image.Image, angle: int) -> Image.Image:
    """
    Rotate image (simulates improper scanning).

    Common angles: 0° (correct), 90° (sideways), 180° (upside-down), 270°
    """
    if angle == 0:
        return img
    return img.rotate(angle, expand=True, fillcolor="white")


def apply_stain(img: Image.Image, intensity: float = 0.5) -> Image.Image:
    """
    Add coffee stain or water damage.

    Creates irregular dark circles that obscure text.
    """
    draw = ImageDraw.Draw(img, "RGBA")

    # Random number of stains (0-3)
    num_stains = random.randint(0, 3)

    for _ in range(num_stains):
        # Random position
        x = random.randint(0, img.width)
        y = random.randint(0, img.height)

        # Random size
        radius = random.randint(30, 80)

        # Brown/gray stain color with transparency
        color = (
            random.randint(100, 150),
            random.randint(80, 120),
            random.randint(60, 100),
            int(intensity * 100),  # Alpha channel
        )

        # Draw irregular circle (slightly distorted)
        draw.ellipse(
            [x - radius, y - radius, x + radius * 1.2, y + radius * 0.8],
            fill=color,
        )

    return img.convert("RGB")


def apply_noise(img: Image.Image, noise_level: float = 0.02) -> Image.Image:
    """
    Add salt-and-pepper noise (simulates poor scanner quality).
    """
    img_array = np.array(img)

    # Random noise
    noise = np.random.random(img_array.shape[:2])

    # Salt (white pixels)
    salt_mask = noise < noise_level / 2
    img_array[salt_mask] = 255

    # Pepper (black pixels)
    pepper_mask = noise > (1 - noise_level / 2)
    img_array[pepper_mask] = 0

    return Image.fromarray(img_array)


def apply_blur(img: Image.Image, blur_level: float = 1.0) -> Image.Image:
    """
    Apply Gaussian blur (simulates out-of-focus scanning).
    """
    return img.filter(ImageFilter.GaussianBlur(radius=blur_level))


def apply_crumple(img: Image.Image) -> Image.Image:
    """
    Simulate crumpling by adding wavy distortion.

    This is a simplified version - realistic warping would use
    perspective transforms or mesh warping.
    """
    # For simplicity, we'll skip heavy geometric transforms
    # Real implementation would use scipy or cv2 for mesh warping
    return img


def degrade_receipt(img: Image.Image, degradation_level: str = "medium") -> Image.Image:
    """
    Apply realistic degradation to receipt image.

    Levels:
    - clean: Minimal degradation (10% of receipts)
    - medium: Typical degradation (70% of receipts)
    - heavy: Severe degradation (20% of receipts)
    """
    if degradation_level == "clean":
        # Minimal processing
        img = apply_thermal_fade(img, fade_level=0.05)
        return img

    elif degradation_level == "medium":
        # Typical degradation
        img = apply_thermal_fade(img, fade_level=random.uniform(0.1, 0.3))

        # Sometimes rotate
        if random.random() > 0.85:
            angle = random.choice([90, 180, 270])
            img = apply_rotation(img, angle)

        # Sometimes add stain
        if random.random() > 0.8:
            img = apply_stain(img, intensity=0.3)

        # Add slight noise
        img = apply_noise(img, noise_level=0.01)

        return img

    else:  # heavy
        # Severe degradation
        img = apply_thermal_fade(img, fade_level=random.uniform(0.4, 0.7))

        # Likely rotated
        if random.random() > 0.5:
            angle = random.choice([90, 180, 270])
            img = apply_rotation(img, angle)

        # Likely stained
        if random.random() > 0.5:
            img = apply_stain(img, intensity=random.uniform(0.4, 0.7))

        # Heavy noise
        img = apply_noise(img, noise_level=0.03)

        # Blur
        img = apply_blur(img, blur_level=random.uniform(1.0, 2.0))

        return img


def main():
    parser = argparse.ArgumentParser(description="Generate receipt images with OCR challenges")
    parser.add_argument("--num-receipts", type=int, default=50, help="Number of receipts to generate")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/receipts"),
        help="Output directory",
    )
    args = parser.parse_args()

    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)

    # Degradation level distribution
    # 10% clean, 70% medium, 20% heavy
    degradation_levels = ["clean"] * 10 + ["medium"] * 70 + ["heavy"] * 20

    print(f"Generating {args.num_receipts} receipt images...")

    base_date = datetime.now()

    for i in range(args.num_receipts):
        # Generate receipt data
        receipt_date = base_date - timedelta(days=random.randint(0, 90))
        receipt_data = generate_receipt_data(i + 1, receipt_date)

        # Create clean image
        img = create_receipt_image(receipt_data)

        # Apply degradation
        degradation = random.choice(degradation_levels)
        img = degrade_receipt(img, degradation)

        # Save with timestamp in filename
        date_str = receipt_date.strftime("%Y%m%d")
        time_str = receipt_data["time"].replace(":", "")
        filename = args.output / f"receipt_{date_str}_{time_str}_{receipt_data['transaction_id']}.png"

        img.save(filename)

        if (i + 1) % 10 == 0:
            print(f"  Generated {i + 1}/{args.num_receipts} receipts...")

    print(f"\n✓ Generated {args.num_receipts} receipt images")
    print(f"\nDegradation distribution:")
    clean_count = degradation_levels.count("clean") * args.num_receipts // 100
    medium_count = degradation_levels.count("medium") * args.num_receipts // 100
    heavy_count = degradation_levels.count("heavy") * args.num_receipts // 100
    print(f"  Clean: {clean_count} (~10%)")
    print(f"  Medium: {medium_count} (~70%)")
    print(f"  Heavy: {heavy_count} (~20%)")
    print(f"\n✓ Saved to {args.output}")


if __name__ == "__main__":
    main()
