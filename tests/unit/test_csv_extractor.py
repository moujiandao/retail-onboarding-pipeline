"""
Tests for CSV Extractor

Testing Philosophy for File Parsers:
-------------------------------------
1. Use fixture files (real examples) rather than mocking
2. Test the happy path AND edge cases
3. Verify metadata is captured correctly
4. Test error handling (malformed files, wrong encoding)

Key patterns demonstrated:
- pytest fixtures for test data
- tmpdir for temporary file creation
- Encoding tests with actual byte sequences
"""

import pytest
from pathlib import Path
import pandas as pd

from src.extractors.csv_extractor import CSVExtractor


@pytest.fixture
def extractor():
    """Fixture providing a CSVExtractor instance."""
    return CSVExtractor()


@pytest.fixture
def sample_csv_utf8(tmp_path):
    """
    Create a sample CSV file in UTF-8 encoding.

    Why use fixtures?
    - Reusable across multiple tests
    - Cleanup handled automatically (tmp_path is deleted after test)
    - Clear separation of test data setup from test logic
    """
    csv_content = """UPC,SKU,Description,Price
041220000012,GRN-001234,Organic Bananas,0.99
041220000029,GRN-001235,Honeycrisp Apples,1.99
"""
    file_path = tmp_path / "test_utf8.csv"
    file_path.write_text(csv_content, encoding="utf-8")
    return file_path


@pytest.fixture
def sample_csv_latin1(tmp_path):
    """
    Create a CSV with ISO-8859-1 encoding containing special characters.

    This tests the encoding detection logic.
    """
    csv_content = """UPC,SKU,Description,Price
041220000012,GRN-001234,Jalapeño Peppers,2.99
041220000029,GRN-001235,Café Coffee,9.99
"""
    file_path = tmp_path / "test_latin1.csv"
    # Write as ISO-8859-1 (Latin-1)
    file_path.write_text(csv_content, encoding="ISO-8859-1")
    return file_path


@pytest.fixture
def sample_csv_pipe_delimited(tmp_path):
    """
    Create a pipe-delimited file.

    Tests delimiter detection.
    """
    csv_content = """UPC|SKU|Description|Price
041220000012|GRN-001234|Organic Bananas|0.99
041220000029|GRN-001235|Honeycrisp Apples|1.99
"""
    file_path = tmp_path / "test_pipe.csv"
    file_path.write_text(csv_content, encoding="utf-8")
    return file_path


class TestCSVExtractor:
    """Tests for CSVExtractor class."""

    def test_extract_basic_csv(self, extractor, sample_csv_utf8):
        """
        Test extraction of a basic UTF-8 CSV.

        This is the "happy path" - everything works as expected.
        """
        df = extractor.extract(sample_csv_utf8)

        # Verify data was read
        assert len(df) == 2
        assert len(df.columns) == 4

        # Verify column names were normalized
        assert list(df.columns) == ["upc", "sku", "description", "price"]

        # Verify data content
        assert df["description"].iloc[0] == "Organic Bananas"
        assert df["price"].iloc[0] == "0.99"

    def test_metadata_attached(self, extractor, sample_csv_utf8):
        """
        Test that metadata is attached to DataFrame.

        Metadata is crucial for debugging:
        - What file did this data come from?
        - What encoding was detected?
        - How many rows were in the original file?
        """
        df = extractor.extract(sample_csv_utf8)

        # Verify metadata exists
        assert "source_file" in df.attrs
        assert "encoding" in df.attrs
        assert "delimiter" in df.attrs
        assert "row_count" in df.attrs
        assert "column_count" in df.attrs

        # Verify metadata values
        assert df.attrs["row_count"] == 2
        assert df.attrs["column_count"] == 4
        assert df.attrs["delimiter"] == ","

    def test_encoding_detection_utf8(self, extractor, sample_csv_utf8):
        """Test that UTF-8 encoding is detected correctly."""
        encoding = extractor.detect_encoding(sample_csv_utf8)
        # Note: chardet might return 'ascii' for simple UTF-8 files
        # because ASCII is a subset of UTF-8
        assert encoding.lower() in ["utf-8", "ascii"]

    def test_encoding_detection_latin1(self, extractor, sample_csv_latin1):
        """
        Test that ISO-8859-1 (Latin-1) encoding is detected.

        This is critical because misreading Latin-1 as UTF-8 causes
        mojibake: "Jalapeño" → "JalapeÃ±o"
        """
        encoding = extractor.detect_encoding(sample_csv_latin1)
        # chardet should detect ISO-8859-1 or Windows-1252 (similar)
        assert encoding.lower() in ["iso-8859-1", "windows-1252"]

    def test_extract_latin1_file(self, extractor, sample_csv_latin1):
        """
        Test that Latin-1 encoded files are read correctly.

        Verifies that special characters (ñ, é) are preserved.
        """
        df = extractor.extract(sample_csv_latin1)

        # Verify special characters are preserved
        assert "Jalapeño" in df["description"].iloc[0]
        assert "Café" in df["description"].iloc[1]

        # Not corrupted mojibake
        assert "JalapeÃ±o" not in df["description"].iloc[0]

    def test_delimiter_detection_pipe(self, extractor, sample_csv_pipe_delimited):
        """
        Test that pipe delimiter is detected correctly.

        Database exports often use pipe (|) delimiter instead of comma.
        """
        delimiter = extractor.detect_delimiter(sample_csv_pipe_delimited, "utf-8")
        assert delimiter == "|"

    def test_extract_pipe_delimited_file(self, extractor, sample_csv_pipe_delimited):
        """Test extraction of pipe-delimited file."""
        df = extractor.extract(sample_csv_pipe_delimited)

        assert len(df) == 2
        assert df["description"].iloc[0] == "Organic Bananas"

    def test_column_normalization(self, extractor, tmp_path):
        """
        Test that column names are normalized correctly.

        Common issues:
        - Trailing spaces: "UPC " vs "UPC"
        - Mixed case: "UPC" vs "upc" vs "Upc"
        - Special characters: "Price ($)" → "price"
        - Spaces: "Product Name" → "product_name"
        """
        csv_content = """UPC ,Product Name,Price ($),SKU
041220000012,Bananas,0.99,GRN-001234
"""
        file_path = tmp_path / "test_normalization.csv"
        file_path.write_text(csv_content, encoding="utf-8")

        df = extractor.extract(file_path)

        # Verify normalized column names
        assert list(df.columns) == ["upc", "product_name", "price", "sku"]

    def test_extract_nonexistent_file(self, extractor):
        """Test that FileNotFoundError is raised for missing files."""
        with pytest.raises(FileNotFoundError):
            extractor.extract(Path("/nonexistent/file.csv"))

    def test_schema_validation_success(self, extractor, sample_csv_utf8):
        """
        Test schema validation with valid file.

        Schema validation ensures files have expected columns before
        processing, enabling fail-fast behavior.
        """
        df = extractor.extract_with_schema_validation(
            sample_csv_utf8,
            expected_columns=["upc", "sku", "description", "price"],
            required_columns=["upc", "sku"]
        )

        assert len(df) == 2

    def test_schema_validation_missing_required_column(self, extractor, tmp_path):
        """
        Test that missing required columns raise ValueError.

        This catches schema mismatches early instead of failing later
        in the pipeline when trying to join on missing columns.
        """
        csv_content = """Description,Price
Bananas,0.99
"""
        file_path = tmp_path / "test_missing_cols.csv"
        file_path.write_text(csv_content, encoding="utf-8")

        with pytest.raises(ValueError, match="Missing required columns"):
            extractor.extract_with_schema_validation(
                file_path,
                expected_columns=["upc", "sku", "description", "price"],
                required_columns=["upc", "sku"]
            )

    def test_empty_csv_file(self, extractor, tmp_path):
        """
        Test handling of empty CSV file.

        Should return empty DataFrame with correct columns.
        """
        csv_content = """UPC,SKU,Description,Price
"""  # Header only, no data rows
        file_path = tmp_path / "test_empty.csv"
        file_path.write_text(csv_content, encoding="utf-8")

        df = extractor.extract(file_path)

        assert len(df) == 0
        assert list(df.columns) == ["upc", "sku", "description", "price"]

    def test_csv_with_quoted_fields(self, extractor, tmp_path):
        """
        Test handling of quoted fields (important for fields containing commas).

        Example: "Seattle, WA" shouldn't be split into two columns.
        """
        csv_content = """City,State,Population
"Seattle, WA",Washington,750000
"Portland, OR",Oregon,650000
"""
        file_path = tmp_path / "test_quoted.csv"
        file_path.write_text(csv_content, encoding="utf-8")

        df = extractor.extract(file_path)

        # Quoted fields should preserve commas
        assert df["city"].iloc[0] == "Seattle, WA"
        assert df["city"].iloc[1] == "Portland, OR"
