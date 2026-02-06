"""
PDF Invoice Extractor using pdfplumber

Extracts structured data (line items, totals, metadata) from vendor invoice PDFs.

Approach:
1. Try pdfplumber table extraction (works for 70-80% of invoices)
2. Fall back to regex pattern matching for unstructured PDFs
3. Quarantine unparseable PDFs for manual review

Why pdfplumber over PyPDF2?
- Superior table detection algorithms
- Returns character-level positioning (useful for complex layouts)
- Better handling of multi-column invoices
- Active maintenance and large user base

Key Challenges in PDF Invoice Parsing:
---------------------------------------
1. Format variation: Each vendor uses different layouts
2. Multi-page invoices: Line items span multiple pages
3. Scanned vs digital: Some PDFs are images (need OCR separately)
4. Missing/calculated totals: Need to validate sums
5. Date format chaos: MM/DD/YYYY vs YYYY-MM-DD vs "January 15, 2024"

What this extractor does NOT do:
---------------------------------
- OCR (use OCRExtractor for scanned PDFs)
- Invoice classification (determining vendor/type)
- Deep validation (checking totals match - that's transformation logic)

Usage:
    from src.extractors.pdf_extractor import PDFExtractor

    extractor = PDFExtractor()
    result = extractor.extract("invoice.pdf")

    print(result["metadata"])  # Invoice number, date, vendor
    print(result["line_items"])  # DataFrame of products
    print(result["totals"])     # Subtotal, tax, total
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging

import pandas as pd
import pdfplumber
from PyPDF2 import PdfReader

logger = logging.getLogger(__name__)


class PDFExtractor:
    """
    Extract structured data from PDF invoices.

    Design decisions:
    - Try table extraction first (fast, structured)
    - Fall back to text extraction + regex (slower, less reliable)
    - Return None for unparseable PDFs (don't crash, quarantine them)
    """

    def __init__(self):
        """Initialize PDF extractor."""
        pass

    def extract(self, pdf_path: Path) -> Optional[Dict]:
        """
        Extract data from PDF invoice.

        This is the main entry point. It tries multiple extraction
        strategies in order of reliability.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Dictionary with keys:
            - metadata: Dict[str, Any] (invoice_number, date, vendor, etc.)
            - line_items: pd.DataFrame (product lines)
            - totals: Dict[str, float] (subtotal, tax, total)
            - extraction_method: str (how it was extracted)
            - success: bool

            Returns None if extraction completely fails.

        Example:
            >>> result = extractor.extract("invoice.pdf")
            >>> if result["success"]:
            ...     print(f"Extracted {len(result['line_items'])} line items")
            ... else:
            ...     print("Extraction failed, quarantine this file")
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            logger.error(f"PDF file not found: {pdf_path}")
            return None

        logger.info(f"Extracting PDF: {pdf_path.name}")

        # Strategy 1: pdfplumber table extraction
        result = self._extract_with_pdfplumber(pdf_path)
        if result and result["success"]:
            result["extraction_method"] = "pdfplumber_tables"
            return result

        # Strategy 2: Text extraction + regex patterns
        logger.info("Table extraction failed, trying text extraction")
        result = self._extract_with_text_patterns(pdf_path)
        if result and result["success"]:
            result["extraction_method"] = "text_patterns"
            return result

        # Strategy 3: Fail - this PDF needs manual review or OCR
        logger.warning(f"Could not extract data from {pdf_path.name}")
        return {
            "metadata": {},
            "line_items": pd.DataFrame(),
            "totals": {},
            "extraction_method": "failed",
            "success": False,
            "error": "No extraction strategy succeeded",
        }

    def _extract_with_pdfplumber(self, pdf_path: Path) -> Optional[Dict]:
        """
        Extract using pdfplumber's table detection.

        How pdfplumber works:
        1. Analyzes PDF structure for table-like layouts
        2. Detects rows/columns based on text positioning and lines
        3. Returns nested lists: [[cell1, cell2], [cell3, cell4]]

        Returns:
            Extraction result dict or None if no tables found
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Extract metadata from first page
                first_page = pdf.pages[0]
                text = first_page.extract_text()
                metadata = self._parse_metadata(text)

                # Extract tables from all pages
                all_line_items = []

                for page_num, page in enumerate(pdf.pages):
                    tables = page.extract_tables()

                    if not tables:
                        logger.debug(f"No tables found on page {page_num + 1}")
                        continue

                    # Typically the largest table is the line items
                    # (smaller tables might be headers/footers)
                    largest_table = max(tables, key=lambda t: len(t))

                    logger.debug(
                        f"Found table with {len(largest_table)} rows "
                        f"on page {page_num + 1}"
                    )

                    # Convert to DataFrame
                    if len(largest_table) > 1:
                        # First row is usually headers
                        headers = largest_table[0]
                        rows = largest_table[1:]

                        # Create DataFrame
                        df = pd.DataFrame(rows, columns=headers)

                        # Clean up None values and whitespace
                        df = df.fillna("")
                        df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)

                        all_line_items.append(df)

                if not all_line_items:
                    logger.info("No tables extracted from PDF")
                    return None

                # Concatenate all pages
                line_items = pd.concat(all_line_items, ignore_index=True)

                # Normalize column names
                line_items.columns = line_items.columns.str.lower().str.strip()

                # Extract totals from text
                totals = self._parse_totals(text)

                return {
                    "metadata": metadata,
                    "line_items": line_items,
                    "totals": totals,
                    "success": True,
                }

        except Exception as e:
            logger.error(f"pdfplumber extraction failed: {e}")
            return None

    def _extract_with_text_patterns(self, pdf_path: Path) -> Optional[Dict]:
        """
        Extract using text extraction + regex patterns.

        This is the fallback when table detection fails.
        Works for simple, text-based invoices without tables.

        Uses PyPDF2 for text extraction (lighter weight than pdfplumber
        when we don't need table detection).

        Returns:
            Extraction result dict or None if pattern matching fails
        """
        try:
            reader = PdfReader(pdf_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text()

            # Extract metadata
            metadata = self._parse_metadata(text)

            # Extract totals
            totals = self._parse_totals(text)

            # Line item extraction via regex is complex and fragile
            # For now, we'll just return metadata and totals
            # In production, you'd add regex patterns for your specific formats

            logger.info("Extracted metadata and totals via text patterns")

            return {
                "metadata": metadata,
                "line_items": pd.DataFrame(),  # Empty - regex extraction not implemented
                "totals": totals,
                "success": bool(metadata),  # Success if we at least got metadata
            }

        except Exception as e:
            logger.error(f"Text extraction failed: {e}")
            return None

    def _parse_metadata(self, text: str) -> Dict[str, str]:
        """
        Extract invoice metadata using regex patterns.

        Common metadata:
        - Invoice number (various formats: INV-2024-001234, Invoice #123, etc.)
        - Invoice date (various formats: MM/DD/YYYY, YYYY-MM-DD, etc.)
        - Vendor name (usually at top of invoice)
        - Customer/Bill To (our customer)

        This is the most fragile part because every vendor has different formats.

        Returns:
            Dictionary with metadata fields (empty dict if parsing fails)
        """
        metadata = {}

        # Invoice number patterns
        invoice_patterns = [
            r"Invoice\s*(?:Number|#|No\.?)[\s:]*([A-Z0-9-]+)",
            r"INV[- ]([A-Z0-9-]+)",
        ]

        for pattern in invoice_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                metadata["invoice_number"] = match.group(1)
                break

        # Date patterns (simplified - production would use dateparser library)
        date_patterns = [
            r"Invoice Date[\s:]*(\d{1,2}/\d{1,2}/\d{2,4})",
            r"Date[\s:]*(\d{4}-\d{2}-\d{2})",
            r"Date[\s:]*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        ]

        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                metadata["invoice_date"] = match.group(1)
                break

        # Extract first line as potential vendor name
        # (Very simplistic - production would have vendor database lookup)
        first_lines = text.split("\n")[:3]
        vendor_line = first_lines[0].strip() if first_lines else ""
        if vendor_line and len(vendor_line) < 100:  # Sanity check
            metadata["vendor_name"] = vendor_line

        return metadata

    def _parse_totals(self, text: str) -> Dict[str, float]:
        """
        Extract invoice totals (subtotal, tax, total) using regex.

        Common patterns:
        - "Total: $123.45"
        - "Amount Due: 123.45"
        - "TOTAL $1,234.56"

        Returns:
            Dictionary with total fields (may be incomplete)
        """
        totals = {}

        # Subtotal pattern
        subtotal_match = re.search(
            r"Subtotal[\s:$]*([0-9,]+\.?\d{0,2})",
            text,
            re.IGNORECASE
        )
        if subtotal_match:
            totals["subtotal"] = self._parse_currency(subtotal_match.group(1))

        # Tax pattern
        tax_match = re.search(
            r"Tax[\s:$]*([0-9,]+\.?\d{0,2})",
            text,
            re.IGNORECASE
        )
        if tax_match:
            totals["tax"] = self._parse_currency(tax_match.group(1))

        # Total pattern
        total_patterns = [
            r"Total(?:\s+Due)?[\s:$]*([0-9,]+\.?\d{0,2})",
            r"Amount\s+Due[\s:$]*([0-9,]+\.?\d{0,2})",
        ]

        for pattern in total_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                totals["total"] = self._parse_currency(match.group(1))
                break

        return totals

    def _parse_currency(self, value: str) -> float:
        """
        Parse currency string to float.

        Handles:
        - Commas: "1,234.56" → 1234.56
        - Dollar signs: "$123.45" → 123.45
        - Spaces: "1 234.56" → 1234.56

        Args:
            value: Currency string

        Returns:
            Float value
        """
        # Remove currency symbols and spaces
        cleaned = value.replace("$", "").replace(",", "").replace(" ", "")

        try:
            return float(cleaned)
        except ValueError:
            logger.warning(f"Could not parse currency value: {value}")
            return 0.0

    def extract_batch(
        self,
        pdf_directory: Path,
        pattern: str = "*.pdf",
    ) -> pd.DataFrame:
        """
        Extract data from multiple PDF files in a directory.

        This is useful for processing a batch of invoices at once.

        Args:
            pdf_directory: Directory containing PDF files
            pattern: Glob pattern for file selection (default: "*.pdf")

        Returns:
            DataFrame with one row per successfully extracted invoice

        Example:
            >>> extractor = PDFExtractor()
            >>> df = extractor.extract_batch("data/raw/invoices/")
            >>> print(f"Extracted {len(df)} invoices")
            >>> print(f"Failed: {df['success'].sum()} / {len(df)}")
        """
        pdf_files = list(Path(pdf_directory).glob(pattern))

        if not pdf_files:
            logger.warning(f"No PDF files found in {pdf_directory}")
            return pd.DataFrame()

        logger.info(f"Processing {len(pdf_files)} PDF files...")

        results = []

        for i, pdf_path in enumerate(pdf_files):
            logger.info(f"[{i+1}/{len(pdf_files)}] Processing {pdf_path.name}")

            result = self.extract(pdf_path)

            if result:
                # Flatten for DataFrame
                row = {
                    "source_file": str(pdf_path),
                    "success": result["success"],
                    "extraction_method": result.get("extraction_method", "unknown"),
                    **result["metadata"],
                    **{f"total_{k}": v for k, v in result["totals"].items()},
                    "line_item_count": len(result["line_items"]),
                }
                results.append(row)

        df = pd.DataFrame(results)

        logger.info(
            f"✓ Processed {len(df)} PDFs "
            f"(Success: {df['success'].sum()}, Failed: {(~df['success']).sum()})"
        )

        return df
