"""
OCR Extractor for Receipt Images

Extracts text from scanned/photographed grocery receipts using Tesseract OCR.

Key Insight: OCR accuracy depends heavily on image preprocessing.
Raw Tesseract on faded/rotated receipts: ~50% accuracy
With preprocessing (rotation, contrast, denoising): ~80% accuracy

Preprocessing Pipeline:
1. Auto-rotation detection (fix upside-down/sideways scans)
2. Grayscale conversion (reduce noise)
3. Contrast enhancement (sharpen faded text)
4. Thresholding (convert to pure black/white)
5. Denoising (remove speckles)

Why Tesseract?
- Open source, no API costs
- Pre-trained on millions of documents
- Can be fine-tuned for domain-specific fonts
- Provides confidence scores (useful for filtering bad OCR)

Production Considerations:
- For critical production systems, use cloud OCR (AWS Textract, Google Vision)
- Cloud OCR is more accurate but costs $1-5 per 1000 pages
- Tesseract is good for batch processing historical data

Usage:
    from src.extractors.ocr_extractor import OCRExtractor

    extractor = OCRExtractor()
    result = extractor.extract("receipt.png")

    print(result["raw_text"])  # Full OCR output
    print(result["confidence"])  # Average confidence score
    print(result["structured_data"])  # Parsed line items (if successful)
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np

logger = logging.getLogger(__name__)


class OCRExtractor:
    """
    Extract text from receipt images using Tesseract OCR with preprocessing.

    Design Philosophy:
    - Preprocess aggressively (OCR quality is sensitive to image quality)
    - Return confidence scores (allow downstream filtering of low-confidence results)
    - Don't try to parse structure here (that's transformation logic)
    """

    def __init__(
        self,
        tesseract_cmd: Optional[str] = None,
        lang: str = "eng",
        preprocess: bool = True,
    ):
        """
        Initialize OCR extractor.

        Args:
            tesseract_cmd: Path to Tesseract binary (auto-detected if None)
            lang: Tesseract language pack (default: "eng" for English)
            preprocess: Whether to apply image preprocessing (default: True)
        """
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        self.lang = lang
        self.preprocess = preprocess

    def extract(self, image_path: Path) -> Dict:
        """
        Extract text from receipt image.

        Args:
            image_path: Path to image file (PNG, JPG, TIFF)

        Returns:
            Dictionary with:
            - raw_text: str (full OCR output)
            - confidence: float (0-100, average confidence across text)
            - structured_data: Dict (parsed fields like total, items)
            - preprocessing_applied: List[str] (what preprocessing was done)
            - success: bool

        Example:
            >>> result = extractor.extract("receipt.png")
            >>> if result["confidence"] > 70:
            ...     print("High confidence OCR")
            ...     print(result["raw_text"])
        """
        image_path = Path(image_path)

        if not image_path.exists():
            logger.error(f"Image file not found: {image_path}")
            return {"success": False, "error": "File not found"}

        logger.info(f"Extracting text from: {image_path.name}")

        # Load image
        image = Image.open(image_path)

        preprocessing_steps = []

        if self.preprocess:
            # Preprocessing pipeline
            image, steps = self._preprocess_image(image)
            preprocessing_steps = steps

        # Run OCR with detailed output (includes confidence scores)
        try:
            # Get OCR result with bounding boxes and confidence
            ocr_data = pytesseract.image_to_data(
                image,
                lang=self.lang,
                output_type=pytesseract.Output.DICT
            )

            # Get raw text
            raw_text = pytesseract.image_to_string(
                image,
                lang=self.lang
            )

            # Calculate average confidence (filter out -1 values which mean no text)
            confidences = [
                conf for conf in ocr_data["conf"]
                if conf != -1
            ]
            avg_confidence = (
                sum(confidences) / len(confidences)
                if confidences else 0
            )

            logger.info(f"OCR complete. Confidence: {avg_confidence:.1f}%")

            # Try to parse structured data
            structured_data = self._parse_receipt_data(raw_text)

            return {
                "raw_text": raw_text,
                "confidence": avg_confidence,
                "structured_data": structured_data,
                "preprocessing_applied": preprocessing_steps,
                "success": True,
                "word_count": len([w for w in ocr_data["text"] if w.strip()]),
            }

        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "preprocessing_applied": preprocessing_steps,
            }

    def _preprocess_image(self, image: Image.Image) -> Tuple[Image.Image, List[str]]:
        """
        Apply preprocessing to improve OCR accuracy.

        Preprocessing significantly improves OCR on degraded images:
        - Faded thermal receipts: +20-30% accuracy
        - Rotated images: +40-50% accuracy
        - Low contrast: +15-25% accuracy

        Returns:
            Tuple of (preprocessed_image, list_of_steps_applied)
        """
        steps = []

        # Step 1: Auto-rotation detection
        # Tesseract has built-in OSD (orientation and script detection)
        try:
            osd = pytesseract.image_to_osd(image)
            rotation_match = re.search(r"Rotate: (\d+)", osd)
            if rotation_match:
                rotation = int(rotation_match.group(1))
                if rotation != 0:
                    image = image.rotate(-rotation, expand=True, fillcolor="white")
                    steps.append(f"rotated_{rotation}_degrees")
                    logger.debug(f"Auto-rotated {rotation} degrees")
        except Exception as e:
            logger.debug(f"OSD failed (image might be too degraded): {e}")

        # Step 2: Convert to grayscale
        # Color information is useless for text, and adds noise
        if image.mode != "L":
            image = image.convert("L")
            steps.append("grayscale")

        # Step 3: Enhance contrast
        # Faded thermal paper has low contrast between text and background
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)  # 2x contrast boost
        steps.append("contrast_enhancement")

        # Step 4: Thresholding (convert to pure black/white)
        # This removes gray pixels that confuse OCR
        threshold = 150  # Tune this based on your images (100-200 typical)
        image = image.point(lambda x: 0 if x < threshold else 255, "1")
        steps.append("threshold")

        # Step 5: Denoise (remove salt-and-pepper noise)
        # Convert back to grayscale for filtering
        image = image.convert("L")
        image = image.filter(ImageFilter.MedianFilter(size=3))
        steps.append("denoise")

        logger.debug(f"Applied preprocessing: {', '.join(steps)}")

        return image, steps

    def _parse_receipt_data(self, text: str) -> Dict:
        """
        Parse structured data from OCR text.

        This is highly receipt-format specific. Different retailers
        have different formats, so this uses common patterns.

        Extracts:
        - Transaction ID
        - Date
        - Store number
        - Total amount
        - Line items (simplified)

        Returns:
            Dictionary with parsed fields
        """
        data = {}

        # Transaction ID patterns
        transaction_patterns = [
            r"Transaction[\s:]*(\d+)",
            r"Trans(?:action)?[\s#:]*(\d{7,})",
        ]

        for pattern in transaction_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data["transaction_id"] = match.group(1)
                break

        # Date patterns (simplified)
        date_match = re.search(
            r"Date[\s:]*(\d{1,2}/\d{1,2}/\d{2,4})",
            text,
            re.IGNORECASE
        )
        if date_match:
            data["date"] = date_match.group(1)

        # Store number
        store_match = re.search(
            r"Store\s*#?(\d+)",
            text,
            re.IGNORECASE
        )
        if store_match:
            data["store_number"] = store_match.group(1)

        # Total amount
        total_patterns = [
            r"TOTAL[\s$:]*([0-9]+\.?\d{0,2})",
            r"Amount[\s:]*\$?([0-9]+\.\d{2})",
        ]

        for pattern in total_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    data["total"] = float(match.group(1))
                except ValueError:
                    pass
                break

        # Item count (count lines that look like items)
        # Simplified heuristic: lines with a price at the end
        item_lines = re.findall(
            r"^.+\s+(\d+\.\d{2})$",
            text,
            re.MULTILINE
        )
        data["item_count"] = len(item_lines)

        return data

    def extract_batch(
        self,
        image_directory: Path,
        pattern: str = "*.png",
        min_confidence: float = 50.0,
    ) -> List[Dict]:
        """
        Extract text from multiple receipt images.

        Args:
            image_directory: Directory containing images
            pattern: Glob pattern for file selection
            min_confidence: Minimum confidence threshold (0-100)

        Returns:
            List of extraction results (only those above confidence threshold)

        Example:
            >>> extractor = OCRExtractor()
            >>> results = extractor.extract_batch(
            ...     "data/raw/receipts/",
            ...     min_confidence=60.0
            ... )
            >>> high_quality = [r for r in results if r["confidence"] > 80]
        """
        image_files = list(Path(image_directory).glob(pattern))

        if not image_files:
            logger.warning(f"No images found in {image_directory}")
            return []

        logger.info(f"Processing {len(image_files)} images...")

        results = []

        for i, image_path in enumerate(image_files):
            logger.info(f"[{i+1}/{len(image_files)}] Processing {image_path.name}")

            result = self.extract(image_path)

            if result["success"]:
                result["source_file"] = str(image_path)

                # Filter by confidence
                if result["confidence"] >= min_confidence:
                    results.append(result)
                else:
                    logger.warning(
                        f"Low confidence ({result['confidence']:.1f}%), "
                        f"excluding from results"
                    )

        logger.info(
            f"✓ Extracted {len(results)} receipts with confidence >= {min_confidence}%"
        )

        return results

    def save_preprocessed_image(
        self,
        image_path: Path,
        output_path: Path,
    ) -> None:
        """
        Save preprocessed version of image for debugging.

        Useful for:
        - Verifying preprocessing improves OCR
        - A/B testing different preprocessing strategies
        - Manual review of problem images

        Args:
            image_path: Source image
            output_path: Where to save preprocessed version

        Example:
            >>> extractor = OCRExtractor()
            >>> extractor.save_preprocessed_image(
            ...     "receipt_original.png",
            ...     "receipt_preprocessed.png"
            ... )
        """
        image = Image.open(image_path)
        preprocessed, steps = self._preprocess_image(image)
        preprocessed.save(output_path)

        logger.info(
            f"Saved preprocessed image to {output_path} "
            f"(steps: {', '.join(steps)})"
        )
