"""Main CLI entry point for Doctrans"""

import sys
import logging
from pathlib import Path
import click
import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel

from .ppt_reader import PPTReader
from .ppt_writer import PPTWriter, create_output_path
from .pdf_reader import PDFReader
from .pdf_writer import PDFWriter, create_pdf_output_path
from .translator import Translator, PDFTranslator, TranslationRunResult
from .llm import OpenAIClient

console = Console()
logger = logging.getLogger(__name__)


def load_config(config_path: Path | None = None) -> dict:
    """Load configuration from file"""
    if config_path is None:
        # Try to find config in common locations
        possible_paths = [
            Path("config/config.yaml"),
            Path("config.yaml"),
            Path.home() / ".doctrans" / "config.yaml",
        ]
        for path in possible_paths:
            if path.exists():
                config_path = path
                break

    if config_path and config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


def get_llm_client(base_url: str | None, api_key: str | None, model: str, source_lang: str, target_lang: str):
    """Create LLM client with custom base URL (OpenAI-compatible format)"""
    return OpenAIClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        source_lang=source_lang,
        target_lang=target_lang,
    )


def _print_translation_summary(result: TranslationRunResult) -> None:
    """Print translation summary including retry guidance for partial failures."""
    if not result.failed_texts:
        return

    console.print(
        f"  [yellow]Partial translation:[/yellow] {len(result.failed_texts)} text element(s) kept as original after retries"
    )
    console.print("  [yellow]Tip:[/yellow] Re-run the same file to retry only the remaining untranslated text")


def translate_single_file(
    input_path: Path,
    output_path: Path | None,
    llm_client,
    chinese_font: str,
    suffix: str,
) -> Path:
    """Translate a single PPT file"""
    console.print(f"\n[bold blue]Processing:[/bold blue] {input_path.name}")

    # Read PPT
    with console.status("[bold green]Reading PPT..."):
        reader = PPTReader(input_path)
        content = reader.extract_content()

    text_count = len(content.all_texts)
    console.print(f"  Found [cyan]{text_count}[/cyan] text elements to translate")

    if text_count == 0:
        console.print("  [yellow]No text to translate[/yellow]")
        return input_path

    # Translate
    translator = Translator(llm_client)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("[green]Translating...", total=text_count)

        def update_progress(current, total, preview, current_batch, failed_texts):
            description = f"[green]Translating... {current}/{total}[/green]"
            if failed_texts:
                description = (
                    f"[yellow]Translating... {current}/{total}, {len(failed_texts)} pending retry[/yellow]"
                )
            elif current_batch:
                preview = current_batch[0][:40].replace("\n", " ")
                if len(current_batch[0]) > 40:
                    preview += "..."
                description = f"[green]Translating {current}/{total}: {preview}[/green]"
            elif preview:
                description = f"[green]Translating {current}/{total}: {preview[:40]}[/green]"
            progress.update(task, completed=current, description=description)

        result = translator.translate_content(content, progress_callback=update_progress)

    # Write translated PPT
    with console.status("[bold green]Saving translated PPT..."):
        writer = PPTWriter(reader.get_presentation(), chinese_font=chinese_font)
        writer.apply_translations(result.translations)

        if output_path is None:
            output_path = create_output_path(input_path, suffix)

        writer.save(output_path)

    console.print(f"  [green]✓[/green] Saved to: [bold]{output_path}[/bold]")
    _print_translation_summary(result)
    return output_path


def translate_single_pdf(
    input_path: Path,
    output_path: Path | None,
    llm_client,
    suffix: str,
) -> Path:
    """Translate a single PDF file"""
    console.print(f"\n[bold blue]Processing:[/bold blue] {input_path.name}")

    reader = PDFReader(input_path)
    try:
        with console.status("[bold green]Reading PDF..."):
            content = reader.extract_content()

        text_count = len(content.all_texts)
        console.print(f"  Found [cyan]{text_count}[/cyan] text elements to translate")

        if text_count == 0:
            console.print("  [yellow]No text to translate[/yellow]")
            return input_path

        translator = PDFTranslator(llm_client)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task("[green]Translating...", total=text_count)

            def update_progress(current, total, preview, failed_texts):
                description = f"[green]Translating... {current}/{total}[/green]"
                if failed_texts:
                    description = (
                        f"[yellow]Translating... {current}/{total}, {len(failed_texts)} pending retry[/yellow]"
                    )
                elif preview:
                    safe_preview = preview[:40].replace("\n", " ")
                    if len(preview) > 40:
                        safe_preview += "..."
                    description = f"[green]Translating {current}/{total}: {safe_preview}[/green]"
                progress.update(task, completed=current, description=description)

            result = translator.translate_content(content, progress_callback=update_progress)

        with console.status("[bold green]Saving translated PDF..."):
            writer = PDFWriter(reader.get_document(), content)
            writer.apply_translations(result.translations)

            if output_path is None:
                output_path = create_pdf_output_path(input_path, suffix)

            writer.save(output_path)

        console.print(f"  [green]✓[/green] Saved to: [bold]{output_path}[/bold]")
        _print_translation_summary(result)
        return output_path
    finally:
        reader.close()


@click.command()
@click.argument("inputs", nargs=-1, type=click.Path(exists=True))
@click.option("-o", "--output", type=click.Path(), help="Output file or directory")
@click.option("--base-url", default=None, help="Custom API base URL (OpenAI-compatible)")
@click.option("--api-key", default=None, help="API key (or set LLM_API_KEY env var)")
@click.option("--model", default=None, help="Model name to use")
@click.option("--source", default=None, help="Source language code (e.g., en)")
@click.option("--target", default=None, help="Target language code (e.g., zh)")
@click.option("--config", type=click.Path(exists=True), help="Config file path")
def main(inputs, output, base_url, api_key, model, source, target, config):
    """Translate PowerPoint and PDF files using LLM.

    INPUTS: One or more .pptx/.pdf files or directories containing them.

    Examples:

        python -m src.main presentation.pptx

        python -m src.main document.pdf

        python -m src.main slides/ -o translated/

        python -m src.main file1.pptx --base-url https://api.example.com/v1
    """
    if not inputs:
        console.print("[red]Error:[/red] No input files specified")
        console.print("Usage: python -m src.main <file.pptx|file.pdf> [options]")
        sys.exit(1)

    # Load config
    config_data = load_config(Path(config) if config else None)
    llm_config = config_data.get("llm", {})
    trans_config = config_data.get("translation", {})
    output_config = config_data.get("output", {})

    # Merge CLI options with config
    base_url = base_url or llm_config.get("base_url")
    api_key = api_key or llm_config.get("api_key") or None
    model = model or llm_config.get("model", "gpt-4o-mini")
    source_lang = source or trans_config.get("source_lang", "en")
    target_lang = target or trans_config.get("target_lang", "zh")
    chinese_font = output_config.get("chinese_font", "Microsoft YaHei")
    suffix = output_config.get("suffix", "_translated")

    console.print(Panel.fit(
        f"[bold]Doctrans - Document Translation Tool[/bold]\n\n"
        f"API: [cyan]{base_url or 'OpenAI default'}[/cyan]\n"
        f"Model: [cyan]{model}[/cyan]\n"
        f"Direction: [cyan]{source_lang} → {target_lang}[/cyan]",
        border_style="blue",
    ))

    # Create LLM client
    try:
        llm_client = get_llm_client(base_url, api_key, model, source_lang, target_lang)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    # Collect all supported files
    ppt_files: list[Path] = []
    pdf_files: list[Path] = []
    for input_path in inputs:
        path = Path(input_path)
        if path.is_dir():
            ppt_files.extend(path.glob("**/*.pptx"))
            pdf_files.extend(path.glob("**/*.pdf"))
        elif path.suffix.lower() == ".pptx":
            ppt_files.append(path)
        elif path.suffix.lower() == ".pdf":
            pdf_files.append(path)
        else:
            console.print(f"[yellow]Skipping unsupported file:[/yellow] {path}")

    all_files = ppt_files + pdf_files
    if not all_files:
        console.print("[red]Error:[/red] No .pptx or .pdf files found")
        sys.exit(1)

    console.print(f"\nFound [bold]{len(ppt_files)}[/bold] PPT and [bold]{len(pdf_files)}[/bold] PDF file(s) to translate")

    # Determine output directory
    output_dir = Path(output) if output else None
    if output_dir and len(all_files) > 1:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Translate each file
    results = []
    for ppt_file in ppt_files:
        try:
            if output_dir and output_dir.is_dir():
                out_path = output_dir / f"{ppt_file.stem}{suffix}.pptx"
            elif output and len(all_files) == 1:
                out_path = Path(output)
            else:
                out_path = None

            result = translate_single_file(
                ppt_file, out_path, llm_client, chinese_font, suffix
            )
            results.append((ppt_file, result, True))
        except Exception:
            console.print(f"[red]Error processing {ppt_file}:[/red] See log for traceback")
            logger.exception("Failed to process PPT file", extra={"file": str(ppt_file)})
            results.append((ppt_file, None, False))

    for pdf_file in pdf_files:
        try:
            if output_dir and output_dir.is_dir():
                out_path = output_dir / f"{pdf_file.stem}{suffix}.pdf"
            elif output and len(all_files) == 1:
                out_path = Path(output)
            else:
                out_path = None

            result = translate_single_pdf(
                pdf_file, out_path, llm_client, suffix
            )
            results.append((pdf_file, result, True))
        except Exception:
            console.print(f"[red]Error processing {pdf_file}:[/red] See log for traceback")
            logger.exception("Failed to process PDF file", extra={"file": str(pdf_file)})
            results.append((pdf_file, None, False))

    # Summary
    console.print("\n" + "=" * 50)
    success_count = sum(1 for _, _, ok in results if ok)
    console.print(f"[bold]Completed:[/bold] {success_count}/{len(results)} files translated")


if __name__ == "__main__":
    main()
