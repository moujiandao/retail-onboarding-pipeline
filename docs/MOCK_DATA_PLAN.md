# Mock Data Generation Plan

This document outlines the synthetic grocery data we'll generate for development and testing. The goal is to create **realistic data with intentional quality issues** that mirror what you encounter when onboarding real grocery retailers.

## Business Context

We're simulating data from **"Pacific Northwest Grocers"**, a fictional regional grocery chain with:
- 12 store locations across WA, OR, and Northern CA
- ~10,000-15,000 active SKUs (stock-keeping units)
- 40-50 regular vendors (distributors, local suppliers)
- Mix of modern POS systems and legacy infrastructure
- Transitioning from paper-based to digital processes

This profile is typical of mid-market grocers: large enough to have complexity, small enough that data infrastructure is inconsistent.

---

## Data Sources Overview

| Source | Format | Volume | Update Frequency | Processing Challenge |
|--------|--------|--------|------------------|---------------------|
| Vendor Invoices | PDF | ~100-150/month | Daily | Multiple formats, OCR needed for some |
| Transaction Receipts | JPEG/PNG images | ~1,500/month | Hourly batches | OCR required, faded thermal paper |
| Item Master | CSV | 15,000 rows | Weekly full refresh | Encoding issues, duplicate UPCs |
| Price Changes | CSV | ~500 changes/week | Daily incremental | Overlapping effective dates |
| Store Master | CSV | 12 rows | Rarely (only when stores open/close) | Inconsistent formatting |

---

## 1. Vendor Invoices (PDF)

### Why This Matters

Invoice processing is the **highest-value** data pipeline in retail. Invoices determine:
- **Cost of Goods Sold (COGS)**: Your largest expense
- **Inventory reconciliation**: What you ordered vs. what arrived
- **Billing disputes**: Catching overbilling saves millions annually
- **Vendor relationships**: Payment terms, discounts, rebates

### Vendor Types (Format Diversity)

We'll generate three archetypes representing real-world variation:

#### Type 1: Major National Distributors (50% of invoices)

Examples: UNFI, KeHE, C&S Wholesale

**Characteristics:**
- Clean, structured PDFs (generated from ERP systems)
- Consistent table layouts
- Machine-readable text (no OCR needed)
- Includes EDI-style codes (GTIN, GLN)

**Sample Invoice:**

```
UNFI - United Natural Foods, Inc.
Invoice Date: 2024-01-15
Invoice Number: INV-UNFI-2024-001234
Customer: Pacific NW Grocers #007

Ship To: Portland Distribution Center
Payment Terms: Net 30
Order Date: 2024-01-10

Line Items:
──────────────────────────────────────────────────────────────
Item Code | Description              | UPC          | Qty | Unit | Price  | Total
──────────────────────────────────────────────────────────────────────────────
UN-10234  | Organic Whole Milk 1gal | 041900073817 | 48  | EA   | $4.25  | $204.00
UN-10235  | Organic 2% Milk 1gal    | 041900073824 | 36  | EA   | $4.15  | $149.40
UN-20441  | Almond Milk Unsweetened | 041900074012 | 24  | EA   | $3.50  | $84.00
──────────────────────────────────────────────────────────────────────────────

Subtotal:        $437.40
Freight:          $25.00
Tax:              $0.00 (wholesale exempt)
──────────────────────────────────────────────────────────────────────────────
Total Due:       $462.40
```

#### Type 2: Regional Suppliers (35% of invoices)

Examples: Local dairy, regional bakery, produce distributor

**Characteristics:**
- Semi-structured PDFs (from QuickBooks, Excel exports)
- Inconsistent column alignment
- Sometimes includes handwritten notes ("short shipped 2 cases")
- May use vendor-specific item codes (not UPCs)

**Sample Invoice:**

```
Mountain Valley Dairy
Beaverton, OR 97005

Invoice: MV-2024-0042
Date: January 15, 2024

Sold To: Pacific NW Grocers - Store 007

  Description                    Qty    Price      Total
  ────────────────────────────────────────────────────────
  Whole Milk, 1 Gallon          48 ea   $3.45    $165.60
  2% Milk, 1 Gallon             36 ea   $3.25    $117.00
  Heavy Cream, 1 Pint           12 ea   $2.80     $33.60
  ────────────────────────────────────────────────────────

                                 Subtotal:      $316.20
                                 Delivery:       $15.00
                                 ──────────────────────
                                 TOTAL:         $331.20

  Payment Due: Net 15 days

  ** NOTE: Short-shipped 2 cases cream, will deliver Monday **
```

#### Type 3: Small Local Vendors (15% of invoices)

Examples: Farmers market suppliers, small bakeries

**Characteristics:**
- **Scanned paper invoices** (photographed or faxed)
- Handwritten amounts
- No standardized item codes
- Low resolution, sometimes rotated
- Coffee stains, folded corners

**Sample (as photographed paper):**

```
[Image of handwritten invoice]

Green Acres Farm
Fresh Produce Delivery

1/15/24

Pacific NW Grocers

Romaine Lettuce    24 heads @ $1.50    $36.00
Kale, Curly        12 bunches @ $2.00  $24.00
Cherry Tomatoes    8 flats @ $12.00    $96.00

                              Total:  $156.00

Paid: [  ] Check   [X] Invoice   [  ] Cash

[Signature]
```

### Data Quality Issues to Include

| Issue | Frequency | Example | Detection Strategy |
|-------|-----------|---------|-------------------|
| OCR errors | 10-15% of scanned invoices | `$3.45` → `$3.4S` | Validate numeric fields |
| Missing invoice totals | 5% | Subtotal present, total missing | Calculate and compare |
| Duplicate invoices | 3% | Same invoice scanned twice | Checksum + invoice number |
| Date format variation | 30% | `01/15/24` vs `January 15, 2024` vs `2024-01-15` | Parse with multiple formats |
| Multi-page invoices | 20% | Line items span 2-3 pages | Concatenate pages |
| Handwritten corrections | 8% | Price crossed out, new price written | OCR confidence thresholds |
| Missing UPCs | 25% | Only vendor item codes | Join on description/fuzzy match |

---

## 2. Transaction Receipts (Images)

### Why This Matters

Receipt data drives:
- **Sales analytics**: What's selling, when, where
- **Inventory depletion**: Real-time stock levels
- **Promotion effectiveness**: Did the sale drive volume?
- **Basket analysis**: What do customers buy together?
- **Reconciliation**: Do sales match inventory?

Modern POS systems have APIs, but during onboarding you often get **historical data as scanned images**.

### Receipt Types

#### Type 1: Thermal Paper Receipts (70%)

**Characteristics:**
- Faded text (thermal paper degrades over months)
- Narrow width (typically 40 characters)
- Logo/header at top
- Payment info at bottom
- Sometimes curled/warped

**Sample:**

```
========================================
      PACIFIC NW GROCERS
        Store #007 - Portland
        4232 NE Broadway St
        Portland, OR 97213
========================================
Date: 01/15/2024    Time: 14:32:07
Cashier: Maria T.   Register: 03
Transaction: 0070001234

BANANAS ORGANIC       1.29 lb
  @ $0.99/lb                     1.28

BREAD WHOLE WHEAT                4.29

MILK 2% GALLON                   5.49

EGGS LARGE DOZEN                 6.99
  COUPON -$1.00                 -1.00

COFFEE GROUND 12OZ               9.99

APPLES HONEYCRISP    2.45 lb
  @ $1.99/lb                     4.88

----------------------------------------
SUBTOTAL                        31.92
TAX (OR 0%)                      0.00
TOTAL                           31.92

VISA ****1234                   31.92
CHANGE DUE                       0.00

Items: 7          You Saved: $1.00

   Thank you for shopping local!
========================================
```

#### Type 2: Inkjet Register Receipts (20%)

**Characteristics:**
- Better contrast than thermal
- Wider format (80 characters possible)
- Sometimes includes color (logo, promotions)

#### Type 3: Corrupted/Degraded Receipts (10%)

**Characteristics:**
- Extreme fading (50%+ text illegible)
- Stains (coffee, water damage)
- Torn or folded (text cut off)
- Extreme skew (15+ degrees rotation)

### Data Quality Issues to Include

| Issue | Frequency | Example | Impact |
|-------|-----------|---------|--------|
| Faded text | 20% | Half the characters unreadable | OCR returns garbled text |
| Rotation | 15% | Receipt scanned upside-down or sideways | Need auto-rotation |
| Stains/marks | 10% | Coffee ring obscures amount | Partial data loss |
| Crumpled/warped | 8% | Receipt folded, text distorted | Geometric distortion |
| Partial capture | 5% | Bottom cut off in scan | Missing total/payment |
| Low resolution | 12% | Scanned at 72 DPI instead of 300 | Blurry text |

---

## 3. Item Master (CSV)

### Why This Matters

The item master is your **source of truth** for products. Every other data source references it:
- Invoices join to items by UPC or vendor code
- Receipts join to items by UPC
- Pricing joins to items by SKU

**If the item master is wrong, everything downstream is wrong.**

### Schema

```csv
upc,sku,description,brand,category,subcategory,department,unit_size,unit_measure,pack_size,vendor_id,vendor_name,cost,retail_price,margin_pct,status,created_date,modified_date
041220000012,GRN-001234,"Organic Bananas","Dole","Produce","Fruit","100",1.00,"LB",1,"VEND-001","Fresh Direct Produce",0.59,0.99,40.4,"ACTIVE","2020-03-15","2024-01-10"
```

### Data Coverage

- **Total SKUs**: 15,000
- **Active SKUs**: 12,500 (83%)
- **Inactive SKUs**: 2,500 (17% - discontinued but keep for history)
- **Categories**: 12 (Produce, Dairy, Grocery, Frozen, Meat, Bakery, etc.)
- **Vendors**: 45

### Data Quality Issues to Include

| Issue | Frequency | Example | Business Impact |
|-------|-----------|---------|-----------------|
| Missing UPCs | 5% | UPC field is NULL or empty | Can't scan at register |
| Duplicate UPCs | 2% | Same UPC, different SKUs | Inventory chaos, sales misattributed |
| Encoding issues | 8% | `Jalapeño` → `JalapeÃ±o` | Joins fail, reporting breaks |
| Inconsistent units | 15% | "LB" vs "lb" vs "pound" vs "LBS" | Aggregation errors |
| Invalid prices | 1% | cost=$0.00 or retail < cost | Margin calculations incorrect |
| Orphaned vendor IDs | 3% | vendor_id doesn't exist in vendor table | Foreign key violations |
| Stale data | 10% | status="ACTIVE" but not sold in 2+ years | Phantom inventory |
| Mixed CSV formats | Per-file | Some quoted, some not; different delimiters | Parser failures |
| Header variations | Per-file | "UPC" vs "upc" vs "UPC_Code" | Column mapping breaks |

---

## 4. Price Changes (CSV)

### Why This Matters

Retail prices change constantly:
- **Promotions**: Weekly ads, BOGO deals
- **Cost increases**: Vendor price hikes
- **Competitive pricing**: Match competitors
- **Seasonal adjustments**: Holiday pricing

Historical price data is critical for:
- **Margin analysis**: Did the promotion eat all our margin?
- **Elasticity modeling**: How much did volume increase?
- **Forecasting**: Predict impact of future price changes

### Schema

```csv
sku,effective_date,end_date,price_type,old_price,new_price,reason_code,reason_description,approved_by,approved_date
GRN-001234,2024-01-15,2024-01-21,PROMO,0.99,0.79,WEEKLY_AD,"Presidents Day Sale",jsmith,2024-01-10
GRN-001234,2024-01-22,,REGULAR,0.79,0.99,PROMO_END,"Return to regular price",system,2024-01-22
```

### Data Quality Issues to Include

| Issue | Frequency | Example | Reconciliation Challenge |
|-------|-----------|---------|-------------------------|
| Overlapping dates | 5% | Two active prices for same SKU/date | Which price applies? |
| Missing end dates | 15% | end_date is NULL on promotion | Does it last forever? |
| Future-dated changes | 2% | effective_date in the future | Accidental early application |
| Gap in history | 8% | Price jumps from $1 to $1.50 with no record | Missing audit trail |
| Invalid transitions | 3% | old_price doesn't match previous new_price | Data integrity issue |

---

## 5. Store Master (CSV)

### Why This Matters

Store-level analysis drives operational decisions:
- **P&L by store**: Which locations are profitable?
- **Regional performance**: West Coast vs. East Coast
- **Comparable store sales**: Same-store growth metric
- **Allocation**: How much inventory to send where

### Schema

```csv
store_id,store_name,address,city,state,zip,region,district,format,open_date,close_date,square_feet,manager_name,phone
007,Portland Broadway,4232 NE Broadway St,Portland,OR,97213,Pacific Northwest,OR-Metro,Full Service,2015-06-01,,45000,Sarah Chen,503-555-0187
```

### Data Quality Issues to Include

| Issue | Example | Impact |
|-------|---------|--------|
| Inconsistent state formats | "OR" vs "Oregon" vs "Ore." | Grouping fails |
| Missing coordinates | No lat/long for mapping | Can't do geo analysis |
| Closed stores still "active" | close_date is NULL for closed store | Overstated store count |
| Duplicate store IDs | Same store_id in multiple rows | Primary key violation |

---

## File Format Variations

To demonstrate robust parsing, we'll generate files with these variations:

### CSV Variations

| Variation | Frequency | Example |
|-----------|-----------|---------|
| **Encoding** | Various | UTF-8, UTF-8 with BOM, ISO-8859-1, Windows-1252 |
| **Delimiter** | Various | Comma, tab, pipe (`|`), semicolon |
| **Quoting** | Various | All fields quoted, only text quoted, no quotes, inconsistent |
| **Line endings** | Various | Unix (LF), Windows (CRLF), old Mac (CR) |
| **Header row** | 90% present | Some files have headers, some don't |
| **Trailing commas** | 10% | `sku,price,` vs `sku,price` |

### PDF Variations

| Variation | Frequency | Example |
|-----------|-----------|---------|
| **Structure** | Various | Clean tables, no tables (flowing text), multi-column layout |
| **Text layer** | 70% has text | Searchable PDF vs. scanned image-only PDF |
| **Orientation** | Various | Portrait, landscape, mixed |
| **Pages** | Various | Single-page, multi-page (2-5 pages) |

### Image Variations (Receipts)

| Variation | Frequency | Example |
|-----------|-----------|---------|
| **Format** | Various | JPEG, PNG |
| **Resolution** | Various | 72 DPI (poor), 150 DPI (acceptable), 300 DPI (good) |
| **Color** | Various | Full color, grayscale, black & white |
| **Rotation** | 15% | 0°, 90°, 180°, 270° |
| **Quality** | Various | Pristine, slight fade, heavy fade, stained |

---

## Generation Approach

### Phase 1: Templates

1. **Invoice templates**: Create 5-6 invoice designs (HTML/CSS → PDF)
2. **Receipt generator**: Programmatically generate receipt images with configurable noise
3. **Item master**: Build realistic grocery taxonomy, seed with real product types

### Phase 2: Variation Engine

1. **Quality degradation**: Apply random fading, stains, rotations to images
2. **Format variations**: Export CSVs with different encodings/delimiters
3. **Systematic errors**: Introduce duplicates, missing values at configured rates

### Phase 3: Scenarios

1. **Clean baseline set** (20%): Happy path data for initial development
2. **Realistic set** (70%): Typical quality issues
3. **Edge case set** (10%): Worst-case scenarios for stress testing

---

## Validation Strategy

How do we know our generated data is realistic?

1. **Statistical profiling**: Run Great Expectations profiler to generate baseline expectations
2. **Manual review**: Spot-check generated files for realism
3. **Edge case coverage**: Ensure each quality issue type is represented
4. **Volume testing**: Generate enough data to test at scale (10k+ items, 100+ invoices)

---

## Summary: What This Demonstrates

| Skill | How Mock Data Proves It |
|-------|-------------------------|
| **Understanding retail operations** | Knew what data sources exist and why they matter |
| **Data quality awareness** | Intentionally seeded realistic issues, not random garbage |
| **Format handling** | Demonstrated CSV encoding detection, PDF parsing, OCR |
| **Defensive coding** | Built quarantine logic for unparseable files |
| **Testing mindset** | Created clean, messy, and edge-case datasets |

The mock data isn't just test fixtures—it's a demonstration of domain knowledge and engineering discipline.
