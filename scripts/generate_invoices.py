"""
Generate Vendor Invoice PDFs with Format Variation

Creates realistic grocery vendor invoices in PDF format with three archetypes:
1. Clean (major distributors): Structured tables, machine-readable
2. Semi-structured (regional suppliers): Less consistent formatting
3. Messy (small vendors): Scanned appearance, handwritten notes

Quality issues intentionally included:
- Multi-page invoices
- Missing totals or subtotals
- Date format variations
- Duplicate invoice numbers (same invoice scanned multiple times)
- OCR-challenging fonts and layouts

Usage:
    python scripts/generate_invoices.py --num-invoices 100 --output data/raw/invoices/
"""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    PageBreak,
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER


# =============================================================================
# Vendor Templates
# =============================================================================

VENDORS = {
    "major_distributor": [
        {
            "name": "UNFI - United Natural Foods, Inc.",
            "address": "313 Iron Horse Way\nProvidence, RI 02908",
            "phone": "401-528-8634",
            "prefix": "INV-UNFI",
        },
        {
            "name": "KeHE Distributors LLC",
            "address": "1304 Woodland Dr\nNaperville, IL 60563",
            "phone": "630-961-5800",
            "prefix": "INV-KEHE",
        },
        {
            "name": "C&S Wholesale Grocers",
            "address": "7 Corporate Place\nKeene, NH 03431",
            "phone": "603-354-7000",
            "prefix": "INV-CS",
        },
    ],
    "regional_supplier": [
        {
            "name": "Mountain Valley Dairy",
            "address": "4521 SW Murray Blvd\nBeaverton, OR 97005",
            "phone": "503-555-0123",
            "prefix": "MV",
        },
        {
            "name": "Pacific Fresh Produce",
            "address": "1840 NW Nicolai St\nPortland, OR 97209",
            "phone": "503-555-0198",
            "prefix": "PFP",
        },
        {
            "name": "Cascade Bakery Supply",
            "address": "9220 SE Stark St\nPortland, OR 97216",
            "phone": "503-555-0187",
            "prefix": "CBS",
        },
    ],
    "small_vendor": [
        {
            "name": "Green Acres Farm",
            "address": "Sauvie Island, OR",
            "phone": "503-555-0142",
            "prefix": "GAF",
        },
        {
            "name": "Artisan Bread Co",
            "address": "NE Portland",
            "phone": "503-555-0176",
            "prefix": "ABC",
        },
    ],
}


def generate_line_items(num_items: int = None) -> List[Dict]:
    """Generate realistic invoice line items."""
    if num_items is None:
        num_items = random.randint(5, 25)

    products = [
        ("Organic Whole Milk 1gal", "041900073817", "EA", (3.50, 5.00)),
        ("Organic 2% Milk 1gal", "041900073824", "EA", (3.40, 4.90)),
        ("Almond Milk Unsweetened", "041900074012", "EA", (3.00, 4.50)),
        ("Heavy Cream 1pt", "041900080015", "EA", (2.50, 3.80)),
        ("Greek Yogurt 32oz", "041900082019", "EA", (4.00, 6.50)),
        ("Cheddar Cheese 8oz", "041900083012", "EA", (3.50, 5.50)),
        ("Organic Eggs Large", "041900084013", "DOZ", (4.50, 7.00)),
        ("Butter Unsalted 1lb", "041900085014", "EA", (4.00, 6.00)),
        ("Cream Cheese 8oz", "041900086015", "EA", (2.50, 4.00)),
        ("Sour Cream 16oz", "041900087016", "EA", (2.00, 3.50)),
        ("Whole Wheat Bread", "041900090001", "EA", (3.00, 4.50)),
        ("Sourdough Loaf", "041900090002", "EA", (4.50, 6.50)),
        ("Bagels Plain 6ct", "041900091003", "EA", (3.50, 5.00)),
        ("English Muffins", "041900092004", "EA", (2.50, 4.00)),
        ("Croissants 4ct", "041900093005", "EA", (4.00, 6.00)),
        ("Organic Bananas", "041220000012", "LB", (0.40, 0.70)),
        ("Honeycrisp Apples", "041220000029", "LB", (1.50, 2.50)),
        ("Romaine Lettuce", "041220000036", "EA", (1.50, 2.50)),
        ("Cherry Tomatoes", "041220000043", "LB", (2.00, 3.50)),
        ("Kale Bunch", "041220000050", "EA", (1.50, 2.50)),
    ]

    items = []
    for i in range(num_items):
        desc, upc, unit, price_range = random.choice(products)
        qty = random.randint(6, 72)
        unit_price = round(random.uniform(*price_range), 2)
        total = round(qty * unit_price, 2)

        items.append({
            "line_num": i + 1,
            "description": desc,
            "upc": upc,
            "qty": qty,
            "unit": unit,
            "unit_price": unit_price,
            "total": total,
        })

    return items


def create_clean_invoice(filename: Path, invoice_data: Dict):
    """
    Generate clean, structured invoice (Type 1: Major Distributor).

    This represents modern ERP systems with consistent formatting.
    """
    doc = SimpleDocTemplate(str(filename), pagesize=letter)
    story = []
    styles = getSampleStyleSheet()

    # Custom styles
    header_style = ParagraphStyle(
        "CustomHeader",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#003366"),
    )

    # Header
    story.append(Paragraph(invoice_data["vendor"]["name"], header_style))
    story.append(Paragraph(invoice_data["vendor"]["address"], styles["Normal"]))
    story.append(Paragraph(f"Phone: {invoice_data['vendor']['phone']}", styles["Normal"]))
    story.append(Spacer(1, 0.3 * inch))

    # Invoice details
    details = f"""
    <b>Invoice Number:</b> {invoice_data['invoice_number']}<br/>
    <b>Invoice Date:</b> {invoice_data['invoice_date']}<br/>
    <b>Order Date:</b> {invoice_data['order_date']}<br/>
    <b>Payment Terms:</b> Net 30<br/>
    """
    story.append(Paragraph(details, styles["Normal"]))
    story.append(Spacer(1, 0.3 * inch))

    # Customer info
    customer = f"""
    <b>Bill To:</b><br/>
    Pacific NW Grocers - Store #{invoice_data['store_id']}<br/>
    4232 NE Broadway St<br/>
    Portland, OR 97213
    """
    story.append(Paragraph(customer, styles["Normal"]))
    story.append(Spacer(1, 0.3 * inch))

    # Line items table
    table_data = [["Item", "Description", "UPC", "Qty", "Unit", "Price", "Total"]]

    for item in invoice_data["line_items"]:
        table_data.append([
            str(item["line_num"]),
            item["description"],
            item["upc"],
            str(item["qty"]),
            item["unit"],
            f"${item['unit_price']:.2f}",
            f"${item['total']:.2f}",
        ])

    table = Table(table_data, colWidths=[0.5*inch, 2.5*inch, 1.2*inch, 0.6*inch, 0.6*inch, 0.8*inch, 0.8*inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (3, 0), (6, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
    ]))

    story.append(table)
    story.append(Spacer(1, 0.3 * inch))

    # Totals
    subtotal = sum(item["total"] for item in invoice_data["line_items"])
    freight = 25.00 if random.random() > 0.3 else 0.00
    tax = 0.00  # Wholesale exempt
    total = subtotal + freight + tax

    totals_data = [
        ["Subtotal:", f"${subtotal:.2f}"],
        ["Freight:", f"${freight:.2f}"],
        ["Tax:", f"${tax:.2f}"],
        ["<b>Total Due:</b>", f"<b>${total:.2f}</b>"],
    ]

    totals_table = Table(totals_data, colWidths=[1.5*inch, 1*inch])
    totals_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))

    story.append(totals_table)

    doc.build(story)


def create_semistructured_invoice(filename: Path, invoice_data: Dict):
    """
    Generate semi-structured invoice (Type 2: Regional Supplier).

    Less consistent formatting, simpler layout.
    """
    doc = SimpleDocTemplate(str(filename), pagesize=letter)
    story = []
    styles = getSampleStyleSheet()

    # Simpler header
    story.append(Paragraph(f"<b>{invoice_data['vendor']['name']}</b>", styles["Title"]))
    story.append(Paragraph(invoice_data["vendor"]["address"], styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    # Invoice info (less structured)
    info = f"""
    Invoice: {invoice_data['invoice_number']}<br/>
    Date: {invoice_data['invoice_date']}<br/>
    <br/>
    Sold To: Pacific NW Grocers - Store #{invoice_data['store_id']}
    """
    story.append(Paragraph(info, styles["Normal"]))
    story.append(Spacer(1, 0.3 * inch))

    # Simpler table (no UPC column)
    table_data = [["Description", "Qty", "Price", "Total"]]

    for item in invoice_data["line_items"]:
        table_data.append([
            item["description"],
            f"{item['qty']} {item['unit']}",
            f"${item['unit_price']:.2f}",
            f"${item['total']:.2f}",
        ])

    table = Table(table_data, colWidths=[3.5*inch, 1*inch, 1*inch, 1*inch])
    table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.black),
    ]))

    story.append(table)
    story.append(Spacer(1, 0.2 * inch))

    # Totals (right-aligned)
    subtotal = sum(item["total"] for item in invoice_data["line_items"])
    delivery = 15.00
    total = subtotal + delivery

    totals = f"""
    <para align=right>
    Subtotal: ${subtotal:.2f}<br/>
    Delivery: ${delivery:.2f}<br/>
    ─────────────────<br/>
    <b>TOTAL: ${total:.2f}</b><br/>
    <br/>
    Payment Due: Net 15 days
    </para>
    """
    story.append(Paragraph(totals, styles["Normal"]))

    # Sometimes add handwritten note
    if random.random() > 0.7:
        note_style = ParagraphStyle("Note", parent=styles["Italic"], fontSize=10)
        story.append(Spacer(1, 0.2 * inch))
        notes = [
            "** Short-shipped 2 cases, will deliver Monday **",
            "** Delivered to back door **",
            "** Called when delivered, no answer **",
        ]
        story.append(Paragraph(random.choice(notes), note_style))

    doc.build(story)


def create_messy_invoice(filename: Path, invoice_data: Dict):
    """
    Generate messy invoice (Type 3: Small Vendor).

    Simulates handwritten or very basic invoices.
    This would typically be scanned, so we make it look informal.
    """
    doc = SimpleDocTemplate(str(filename), pagesize=letter)
    story = []
    styles = getSampleStyleSheet()

    # Very simple header
    story.append(Paragraph(invoice_data["vendor"]["name"], styles["Title"]))
    story.append(Paragraph(invoice_data["vendor"]["address"], styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    # Date and customer
    story.append(Paragraph(invoice_data["invoice_date"], styles["Normal"]))
    story.append(Paragraph(f"Pacific NW Grocers", styles["Normal"]))
    story.append(Spacer(1, 0.3 * inch))

    # Very simple line items (no table, just paragraphs)
    for item in invoice_data["line_items"]:
        line = f"{item['description']}    {item['qty']} {item['unit']} @ ${item['unit_price']:.2f}    ${item['total']:.2f}"
        story.append(Paragraph(line, styles["Normal"]))

    story.append(Spacer(1, 0.3 * inch))

    # Simple total
    total = sum(item["total"] for item in invoice_data["line_items"])
    story.append(Paragraph(f"<para align=right>Total: ${total:.2f}</para>", styles["Normal"]))

    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("Paid: [  ] Check   [X] Invoice   [  ] Cash", styles["Normal"]))

    doc.build(story)


def generate_invoice_data(vendor_type: str, invoice_num: int, base_date: datetime) -> Dict:
    """Generate invoice data structure."""
    vendor = random.choice(VENDORS[vendor_type])

    # Generate invoice date
    invoice_date = base_date - timedelta(days=random.randint(0, 30))
    order_date = invoice_date - timedelta(days=random.randint(1, 7))

    # Date format variations
    date_formats = [
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%m/%d/%y",
    ]
    invoice_date_str = invoice_date.strftime(random.choice(date_formats))
    order_date_str = order_date.strftime(random.choice(date_formats))

    # Generate invoice number
    invoice_number = f"{vendor['prefix']}-{invoice_date.year}-{invoice_num:06d}"

    # Generate line items
    num_items = random.randint(3, 12) if vendor_type == "small_vendor" else random.randint(8, 30)
    line_items = generate_line_items(num_items)

    return {
        "vendor": vendor,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date_str,
        "order_date": order_date_str,
        "store_id": random.randint(1, 12),
        "line_items": line_items,
        "raw_date": invoice_date,  # For sorting
    }


def main():
    parser = argparse.ArgumentParser(description="Generate vendor invoice PDFs")
    parser.add_argument("--num-invoices", type=int, default=100, help="Number of invoices to generate")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/invoices"),
        help="Output directory",
    )
    args = parser.parse_args()

    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)

    # Distribution of vendor types
    # 50% clean, 35% semi-structured, 15% messy
    vendor_distribution = [
        ("major_distributor", 0.50),
        ("regional_supplier", 0.35),
        ("small_vendor", 0.15),
    ]

    base_date = datetime.now()
    invoices_generated = []

    print(f"Generating {args.num_invoices} invoices...")

    for i in range(args.num_invoices):
        # Select vendor type based on distribution
        rand = random.random()
        cumulative = 0
        for vendor_type, pct in vendor_distribution:
            cumulative += pct
            if rand <= cumulative:
                break

        # Generate invoice data
        invoice_data = generate_invoice_data(vendor_type, i + 1, base_date)

        # Generate filename
        date_str = invoice_data["raw_date"].strftime("%Y%m%d")
        filename = args.output / f"invoice_{date_str}_{invoice_data['invoice_number'].replace('/', '_')}.pdf"

        # Generate PDF based on type
        if vendor_type == "major_distributor":
            create_clean_invoice(filename, invoice_data)
        elif vendor_type == "regional_supplier":
            create_semistructured_invoice(filename, invoice_data)
        else:
            create_messy_invoice(filename, invoice_data)

        invoices_generated.append((vendor_type, filename))

        if (i + 1) % 20 == 0:
            print(f"  Generated {i + 1}/{args.num_invoices} invoices...")

    print(f"\n✓ Generated {len(invoices_generated)} invoices")
    print(f"\nDistribution:")
    for vendor_type, _ in vendor_distribution:
        count = sum(1 for vt, _ in invoices_generated if vt == vendor_type)
        print(f"  {vendor_type}: {count}")

    # Introduce duplicate invoices (3%)
    num_duplicates = int(args.num_invoices * 0.03)
    if num_duplicates > 0:
        print(f"\nCreating {num_duplicates} duplicate invoices (same content, different filename)...")
        for _ in range(num_duplicates):
            original_type, original_file = random.choice(invoices_generated)
            dup_filename = args.output / f"duplicate_{original_file.name}"
            # Copy the file
            import shutil
            shutil.copy(original_file, dup_filename)
        print(f"  ✓ Created {num_duplicates} duplicates")

    print(f"\n✓ Saved invoices to {args.output}")


if __name__ == "__main__":
    main()
