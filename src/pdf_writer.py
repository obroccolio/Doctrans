"""PDF Writer - Overlay translated text on original PDF using PyMuPDF"""

from pathlib import Path
import logging

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from .pdf_reader import PDFContent

logger = logging.getLogger(__name__)


class PDFWriter:
    """Overlay translated text on original PDF, preserving layout and images"""

    def __init__(self, doc, content: PDFContent):
        if fitz is None:
            raise ImportError("PyMuPDF is required for PDF writing. Install with: pip install pymupdf")

        self.doc = doc
        self.content = content
        self.translations: dict[str, str] = {}

    def apply_translations(self, translations: dict[str, str]) -> None:
        """Store translations to be applied when saving"""
        self.translations = translations

    def save(self, output_path: str | Path) -> Path:
        """Save the translated PDF by overlaying translated text on original"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        for page_content in self.content.pages:
            page = self.doc[page_content.index]

            # First pass: add redactions for all text blocks that need translation
            for block in page_content.blocks:
                original_text = block.text
                translated_text = self.translations.get(original_text)

                if translated_text and translated_text != original_text:
                    rect = fitz.Rect(block.x0, block.y0, block.x1, block.y1)
                    page.add_redact_annot(rect, fill=(1, 1, 1))

            # Apply all redactions
            page.apply_redactions()

            # Second pass: insert translated text
            for block in page_content.blocks:
                original_text = block.text
                translated_text = self.translations.get(original_text)

                if translated_text and translated_text != original_text:
                    # Expand the rect to accommodate longer translated text
                    width = block.x1 - block.x0
                    height = block.y1 - block.y0

                    # Expand width for Chinese text (usually needs more space)
                    expanded_width = max(width * 1.5, width + 100)
                    # Keep within page bounds
                    new_x1 = min(block.x0 + expanded_width, page.rect.width - 10)

                    # Expand height if text has multiple lines
                    line_count = translated_text.count('\n') + 1
                    min_height = line_count * 14  # At least 14pt per line
                    expanded_height = max(height, min_height)
                    new_y1 = min(block.y0 + expanded_height, page.rect.height - 10)

                    rect = fitz.Rect(block.x0, block.y0, new_x1, new_y1)

                    # Calculate appropriate font size
                    base_font_size = min(block.font_size, 12)

                    # Try to fit the text, reducing font size if needed
                    font_size = base_font_size
                    inserted = False

                    for attempt in range(5):
                        try:
                            rc = page.insert_textbox(
                                rect,
                                translated_text,
                                fontsize=font_size,
                                fontname="china-ss",
                                align=fitz.TEXT_ALIGN_LEFT,
                            )
                            if rc >= 0:
                                inserted = True
                                break
                            # Text overflow, try smaller font
                            font_size *= 0.85
                        except Exception:
                            font_size *= 0.85

                    if not inserted:
                        # Last resort: use helv font with small size
                        try:
                            page.insert_textbox(
                                rect,
                                translated_text,
                                fontsize=8,
                                fontname="helv",
                                align=fitz.TEXT_ALIGN_LEFT,
                            )
                        except Exception as e:
                            logger.error(f"Failed to insert text: {e}")

        # Save to new file
        self.doc.save(str(output_path), garbage=4, deflate=True)
        logger.info(f"Saved translated PDF to: {output_path}")
        return output_path


def create_pdf_output_path(input_path: Path, suffix: str = "_translated") -> Path:
    """Create output path based on input path"""
    return input_path.parent / f"{input_path.stem}{suffix}.pdf"
