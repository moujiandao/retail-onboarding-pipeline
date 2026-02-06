"""
CSV Extractor with Encoding Detection

Handles CSV files from heterogeneous source systems with:
- Automatic encoding detection (UTF-8, ISO-8859-1, Windows-1252)
- Delimiter detection (comma, tab, pipe, semicolon)
- Header normalization (lowercase, strip spaces)
- Metadata tracking (source file, row count, encoding used)

Why this matters:
Legacy retail systems (AS/400, mainframe) export in various encodings.
Reading with the wrong encoding causes silent data corruption that breaks
downstream joins and analytics.

Example issues this solves:
- "Jalapeño" appears as "JalapeÃ±o" (UTF-8 decoded as ISO-8859-1)
- Price "1,234.56" with comma as thousands separator vs decimal
- Missing headers requiring column position mapping

Usage:
    from src.extractors.csv_extractor import CSVExtractor

    extractor = CSVExtractor()
    df = extractor.extract("data/raw/item_master/file.csv")
    print(df.metadata)  # Shows detected encoding, delimiter, etc.
"""

import csv
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import logging

import pandas as pd
import chardet

logger = logging.getLogger(__name__)


class CSVExtractor:
    """
    Extract CSV files with automatic encoding and delimiter detection.

    Design Philosophy:
    - Be defensive: Don't assume encoding or delimiter
    - Fail informatively: If we can't parse, say why
    - Track metadata: Record what we detected for debugging
    """

    def __init__(self, sample_size: int = 10000):
        """
        Initialize CSV extractor.

        Args:
            sample_size: Number of bytes to read for encoding detection.
                        Larger = more accurate but slower.
                        10KB is usually enough.
        """
        self.sample_size = sample_size

    def detect_encoding(self, file_path: Path) -> str:
        """
        Detect file encoding using chardet.

        Why chardet?
        - Analyzes byte patterns to guess encoding
        - ~95% accurate for common encodings
        - Better than guessing or hardcoding UTF-8

        Args:
            file_path: Path to CSV file

        Returns:
            Encoding name (e.g., "utf-8", "ISO-8859-1", "Windows-1252")

        Example:
            >>> encoding = extractor.detect_encoding("file.csv")
            >>> print(encoding)
            'ISO-8859-1'
        """
        with open(file_path, "rb") as f:
            raw_data = f.read(self.sample_size)

        result = chardet.detect(raw_data)
        encoding = result["encoding"]
        confidence = result["confidence"]

        logger.info(
            f"Detected encoding: {encoding} (confidence: {confidence:.2%})"
        )

        # If confidence is low, default to UTF-8 and hope for the best
        if confidence < 0.7:
            logger.warning(
                f"Low confidence encoding detection ({confidence:.2%}). "
                f"Defaulting to utf-8. File may have corruption."
            )
            return "utf-8"

        return encoding

    def detect_delimiter(
        self, file_path: Path, encoding: str
    ) -> str:
        """
        Detect CSV delimiter using Python's csv.Sniffer.

        Common delimiters:
        - Comma (,) - Standard CSV
        - Tab (\t) - TSV files
        - Pipe (|) - Database exports
        - Semicolon (;) - European CSVs (where comma is decimal separator)

        Args:
            file_path: Path to CSV file
            encoding: File encoding (from detect_encoding)

        Returns:
            Delimiter character

        How it works:
        csv.Sniffer analyzes the first few lines and uses heuristics:
        - Delimiter appears consistently at same positions
        - Creates consistent number of fields per row
        - Doesn't appear inside quoted fields
        """
        with open(file_path, "r", encoding=encoding) as f:
            # Read first 5 lines for sniffing
            sample = "".join([f.readline() for _ in range(5)])

        try:
            sniffer = csv.Sniffer()
            delimiter = sniffer.sniff(sample).delimiter
            logger.info(f"Detected delimiter: {repr(delimiter)}")
            return delimiter
        except csv.Error:
            # If sniffing fails, default to comma
            logger.warning("Could not detect delimiter, defaulting to comma")
            return ","

    def normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize column names for consistency.

        Transformations:
        - Lowercase
        - Strip whitespace
        - Replace spaces with underscores
        - Remove special characters

        Why?
        - "UPC" vs "upc" vs "UPC " vs "UPC_Code" should all be "upc"
        - Prevents join failures from inconsistent naming
        - Easier to type (no quotes needed in SQL)

        Example:
            >>> df.columns = ["UPC ", "Product Name", "Price ($)"]
            >>> df = normalize_columns(df)
            >>> df.columns
            ['upc', 'product_name', 'price']
        """
        df = df.copy()

        # Normalize column names
        df.columns = (
            df.columns
            .str.strip()           # Remove leading/trailing spaces
            .str.lower()           # Lowercase
            .str.replace(" ", "_") # Spaces to underscores
            .str.replace(r"[^a-z0-9_]", "", regex=True)  # Remove special chars
        )

        return df

    def extract(
        self,
        file_path: Path,
        **pandas_kwargs
    ) -> pd.DataFrame:
        """
        Extract CSV file with automatic encoding and delimiter detection.

        This is the main entry point. It orchestrates:
        1. Encoding detection
        2. Delimiter detection
        3. Reading with pandas
        4. Column normalization
        5. Metadata attachment

        Args:
            file_path: Path to CSV file
            **pandas_kwargs: Additional arguments passed to pd.read_csv()
                           (e.g., dtype, parse_dates, usecols)

        Returns:
            DataFrame with extracted data and metadata attribute

        Raises:
            FileNotFoundError: If file doesn't exist
            pd.errors.ParserError: If CSV is malformed beyond recovery

        Example:
            >>> extractor = CSVExtractor()
            >>> df = extractor.extract("item_master.csv")
            >>> print(f"Read {len(df)} rows")
            >>> print(f"Encoding: {df.attrs['encoding']}")
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        logger.info(f"Extracting CSV: {file_path}")

        # Step 1: Detect encoding
        encoding = self.detect_encoding(file_path)

        # Step 2: Detect delimiter
        delimiter = self.detect_delimiter(file_path, encoding)

        # Step 3: Read CSV with pandas
        try:
            df = pd.read_csv(
                file_path,
                encoding=encoding,
                delimiter=delimiter,
                **pandas_kwargs
            )
        except UnicodeDecodeError as e:
            # Encoding detection failed, try UTF-8 with error handling
            logger.warning(
                f"Failed to read with {encoding}, retrying with utf-8 (errors='replace')"
            )
            df = pd.read_csv(
                file_path,
                encoding="utf-8",
                encoding_errors="replace",  # Replace bad chars with �
                delimiter=delimiter,
                **pandas_kwargs
            )
            encoding = "utf-8 (with errors replaced)"

        # Step 4: Normalize column names
        df = self.normalize_columns(df)

        # Step 5: Attach metadata
        # Using DataFrame.attrs (pandas 1.0+) to store metadata
        df.attrs["source_file"] = str(file_path)
        df.attrs["encoding"] = encoding
        df.attrs["delimiter"] = delimiter
        df.attrs["row_count"] = len(df)
        df.attrs["column_count"] = len(df.columns)

        logger.info(
            f"✓ Extracted {len(df):,} rows × {len(df.columns)} columns "
            f"(encoding: {encoding}, delimiter: {repr(delimiter)})"
        )

        return df

    def extract_with_schema_validation(
        self,
        file_path: Path,
        expected_columns: list,
        required_columns: Optional[list] = None,
    ) -> pd.DataFrame:
        """
        Extract CSV and validate against expected schema.

        This is useful when you know what columns should exist and
        want to fail fast if the schema is wrong.

        Args:
            file_path: Path to CSV file
            expected_columns: List of expected column names (after normalization)
            required_columns: Subset of columns that must be present

        Returns:
            DataFrame with validated schema

        Raises:
            ValueError: If required columns are missing

        Example:
            >>> extractor = CSVExtractor()
            >>> df = extractor.extract_with_schema_validation(
            ...     "item_master.csv",
            ...     expected_columns=["upc", "sku", "description", "price"],
            ...     required_columns=["upc", "sku"]
            ... )
        """
        df = self.extract(file_path)

        # Validate required columns are present
        if required_columns:
            missing = set(required_columns) - set(df.columns)
            if missing:
                raise ValueError(
                    f"Missing required columns in {file_path.name}: {missing}. "
                    f"Found columns: {list(df.columns)}"
                )

        # Warn about unexpected columns
        unexpected = set(df.columns) - set(expected_columns)
        if unexpected:
            logger.warning(
                f"Unexpected columns in {file_path.name}: {unexpected}"
            )

        # Warn about missing expected columns
        missing_expected = set(expected_columns) - set(df.columns)
        if missing_expected:
            logger.warning(
                f"Expected but missing columns in {file_path.name}: {missing_expected}"
            )

        return df
