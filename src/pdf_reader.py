"""PDF Reader - Extract text content from PDF files using PyMuPDF"""

from dataclasses import dataclass, field
from pathlib import Path
import logging

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

logger = logging.getLogger(__name__)


@dataclass
class PDFTextBlock:
    """A text block from a PDF page with position info"""
    page_index: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float = 11
    block_no: int = 0


@dataclass
class PDFPageContent:
    """Content extracted from a single PDF page"""
    index: int
    blocks: list[PDFTextBlock] = field(default_factory=list)
    width: float = 0
    height: float = 0


@dataclass
class PDFContent:
    """Content extracted from a PDF"""
    file_path: Path
    pages: list[PDFPageContent] = field(default_factory=list)

    @property
    def all_texts(self) -> list[str]:
        """Get all unique texts for translation"""
        texts = set()
        for page in self.pages:
            for block in page.blocks:
                if block.text and block.text.strip():
                    texts.add(block.text)
        return list(texts)


class PDFReader:
    """Read and extract text from PDF files using PyMuPDF"""

    def __init__(self, file_path: str | Path):
        if fitz is None:
            raise ImportError("PyMuPDF is required for PDF support. Install with: pip install pymupdf")

        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")
        if not self.file_path.suffix.lower() == ".pdf":
            raise ValueError("Only .pdf files are supported")

        self.doc = fitz.open(str(self.file_path))

    def extract_content(self) -> PDFContent:
        """Extract all text content from the PDF with position info"""
        content = PDFContent(file_path=self.file_path)

        for page_idx, page in enumerate(self.doc):
            page_content = PDFPageContent(
                index=page_idx,
                width=page.rect.width,
                height=page.rect.height
            )

            # Get text blocks with position info
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

            for block_no, block in enumerate(blocks):
                # Only process text blocks (type 0), skip images (type 1)
                if block.get("type") != 0:
                    continue

                # Extract text from all lines in the block
                block_text = ""
                font_size = 11
                for line in block.get("lines", []):
                    line_text = ""
                    for span in line.get("spans", []):
                        line_text += span.get("text", "")
                        font_size = span.get("size", 11)
                    if line_text:
                        if block_text:
                            block_text += "\n"
                        block_text += line_text

                if block_text and block_text.strip():
                    text_block = PDFTextBlock(
                        page_index=page_idx,
                        text=block_text,
                        x0=block["bbox"][0],
                        y0=block["bbox"][1],
                        x1=block["bbox"][2],
                        y1=block["bbox"][3],
                        font_size=font_size,
                        block_no=block_no,
                    )
                    page_content.blocks.append(text_block)

            content.pages.append(page_content)

        return content

    def get_document(self):
        """Get the underlying fitz Document object"""
        return self.doc

    def close(self):
        """Close the PDF file"""
        if self.doc:
            self.doc.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
