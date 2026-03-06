"""Math Renderer - Convert math text to LaTeX and render as images"""

import io
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# LaTeX conversion prompt
LATEX_CONVERSION_PROMPT = """Convert the following mathematical expression to LaTeX format.

RULES:
- Output ONLY the LaTeX code, no explanation
- Do NOT include $ or $$ delimiters
- Use standard LaTeX math notation
- Preserve the exact mathematical meaning

Input: {text}

LaTeX:"""


def convert_to_latex(text: str, llm_client) -> str:
    """Convert math text to LaTeX using LLM."""
    prompt = LATEX_CONVERSION_PROMPT.format(text=text)
    try:
        response = llm_client._call_api(prompt)
        latex = response.strip()
        # Remove any $ delimiters if present
        latex = latex.strip('$').strip()
        return latex
    except Exception as e:
        logger.error(f"Failed to convert to LaTeX: {e}")
        return text


def render_latex_to_image(latex: str, output_path: Path | str, fontsize: int = 14, dpi: int = 300) -> Path:
    """Render LaTeX formula to PNG image using matplotlib."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        output_path = Path(output_path)

        fig, ax = plt.subplots(figsize=(0.1, 0.1))
        ax.axis('off')

        # Render the LaTeX
        text = ax.text(
            0.5, 0.5, f'${latex}$',
            fontsize=fontsize,
            ha='center', va='center',
            transform=ax.transAxes
        )

        # Get the bounding box and resize figure
        fig.canvas.draw()
        bbox = text.get_window_extent(renderer=fig.canvas.get_renderer())
        bbox = bbox.transformed(fig.dpi_scale_trans.inverted())

        # Add some padding
        padding = 0.1
        fig.set_size_inches(bbox.width + padding, bbox.height + padding)

        # Save to file
        fig.savefig(
            output_path,
            dpi=dpi,
            bbox_inches='tight',
            pad_inches=0.05,
            transparent=True
        )
        plt.close(fig)

        return output_path
    except ImportError:
        logger.error("matplotlib is required for LaTeX rendering. Install with: pip install matplotlib")
        raise
    except Exception as e:
        logger.error(f"Failed to render LaTeX: {e}")
        raise


def render_math_text(text: str, llm_client, output_dir: Path, fontsize: int = 14) -> Path | None:
    """Convert math text to LaTeX and render as image.

    Args:
        text: The math text to render
        llm_client: LLM client for LaTeX conversion
        output_dir: Directory to save the rendered image
        fontsize: Font size for the rendered formula

    Returns:
        Path to the rendered image, or None if rendering failed
    """
    try:
        # Convert to LaTeX
        latex = convert_to_latex(text, llm_client)
        logger.info(f"Converted '{text}' to LaTeX: {latex}")

        # Create unique filename based on text hash
        import hashlib
        text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
        output_path = output_dir / f"math_{text_hash}.png"

        # Render to image
        render_latex_to_image(latex, output_path, fontsize=fontsize)
        logger.info(f"Rendered math formula to: {output_path}")

        return output_path
    except Exception as e:
        logger.error(f"Failed to render math text '{text}': {e}")
        return None
