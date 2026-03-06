"""Web API for Doctrans - Document Translation Tool"""

import logging
import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import yaml

from .ppt_reader import PPTReader
from .ppt_writer import PPTWriter
from .pdf_reader import PDFReader
from .pdf_writer import PDFWriter
from .translator import Translator, PDFTranslator
from .llm import OpenAIClient

app = FastAPI(title="Doctrans", description="Document Translation Tool (PPT & PDF)")
logger = logging.getLogger(__name__)

# Directories for file handling
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Store task status
tasks: dict[str, dict] = {}


def _mark_task_partial_success(task_id: str, failed_texts: list[str]):
    tasks[task_id]["status"] = "completed_with_failures"
    tasks[task_id]["failed_texts"] = failed_texts
    tasks[task_id]["failed_count"] = len(failed_texts)
    tasks[task_id]["retry_available"] = bool(failed_texts)
    tasks[task_id]["current_batch"] = []
    tasks[task_id]["progress"] = 100


def _mark_task_failed(task_id: str, message: str, *, stage: str, exc: Exception):
    logger.exception("Translation task failed", extra={"task_id": task_id, "stage": stage})
    tasks[task_id]["status"] = "failed"
    tasks[task_id]["error"] = message
    tasks[task_id]["error_stage"] = stage
    tasks[task_id]["error_type"] = exc.__class__.__name__
    tasks[task_id]["current_batch"] = []


class TranslationConfig(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str = "gpt-4o-mini"
    source_lang: str = "en"
    target_lang: str = "zh"
    keep_original_terms: bool = False


def load_default_config() -> dict:
    """Load default config from file"""
    config_path = Path("config/config.yaml")
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


def translate_file_task(
    task_id: str,
    input_path: Path,
    output_path: Path,
    config: TranslationConfig,
    retry_only: list[str] | None = None,
):
    """Background task to translate a file"""
    try:
        previous_translations = list(tasks[task_id].get("translations", []))

        tasks[task_id]["status"] = "processing"
        tasks[task_id]["progress"] = 0
        tasks[task_id]["current_batch"] = []
        tasks[task_id]["translations"] = []
        tasks[task_id]["failed_texts"] = []
        tasks[task_id]["failed_count"] = 0
        tasks[task_id]["retry_available"] = False

        reader = PPTReader(input_path)
        content = reader.extract_content()
        total_texts = len(content.all_texts)
        tasks[task_id]["total"] = total_texts

        if total_texts == 0:
            shutil.copy(input_path, output_path)
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["progress"] = 100
            return

        llm_client = OpenAIClient(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            source_lang=config.source_lang,
            target_lang=config.target_lang,
        )

        initial_cache = None
        if retry_only:
            initial_cache = {
                item["original"]: item["translated"]
                for item in previous_translations
                if item["original"] not in retry_only
            }

        translator = Translator(
            llm_client,
            keep_original_terms=config.keep_original_terms,
            initial_cache=initial_cache,
        )

        def update_progress(current, total, preview, batch, failed_texts):
            tasks[task_id]["progress"] = int((current / total) * 100) if total > 0 else 0
            tasks[task_id]["processed"] = current
            tasks[task_id]["current_batch"] = batch or ([preview] if preview else [])
            tasks[task_id]["failed_count"] = len(failed_texts)

        result = translator.translate_content(content, progress_callback=update_progress)
        tasks[task_id]["translations"] = [
            {"original": k, "translated": v}
            for k, v in result.translations.items()
        ]

        default_config = load_default_config()
        chinese_font = default_config.get("output", {}).get("chinese_font", "Microsoft YaHei")

        writer = PPTWriter(reader.get_presentation(), chinese_font=chinese_font)
        writer.apply_translations(result.translations)
        writer.save(output_path)

        if result.failed_texts:
            _mark_task_partial_success(task_id, result.failed_texts)
        else:
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["progress"] = 100
            tasks[task_id]["current_batch"] = []
    except Exception as e:
        _mark_task_failed(task_id, str(e), stage="ppt_translation", exc=e)


def translate_pdf_task(
    task_id: str,
    input_path: Path,
    output_path: Path,
    config: TranslationConfig,
    retry_only: list[str] | None = None,
):
    """Background task to translate a PDF file"""
    reader = None
    try:
        previous_translations = list(tasks[task_id].get("translations", []))

        tasks[task_id]["status"] = "processing"
        tasks[task_id]["progress"] = 0
        tasks[task_id]["current_batch"] = []
        tasks[task_id]["translations"] = []
        tasks[task_id]["failed_texts"] = []
        tasks[task_id]["failed_count"] = 0
        tasks[task_id]["retry_available"] = False

        reader = PDFReader(input_path)
        content = reader.extract_content()
        total_texts = len(content.all_texts)
        tasks[task_id]["total"] = total_texts

        if total_texts == 0:
            shutil.copy(input_path, output_path)
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["progress"] = 100
            return

        llm_client = OpenAIClient(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            source_lang=config.source_lang,
            target_lang=config.target_lang,
        )

        initial_cache = None
        if retry_only:
            initial_cache = {
                item["original"]: item["translated"]
                for item in previous_translations
                if item["original"] not in retry_only
            }

        translator = PDFTranslator(
            llm_client,
            keep_original_terms=config.keep_original_terms,
            initial_cache=initial_cache,
        )

        def update_progress(current, total, preview, failed_texts):
            tasks[task_id]["progress"] = int((current / total) * 100) if total > 0 else 0
            tasks[task_id]["processed"] = current
            tasks[task_id]["current_batch"] = [preview] if preview else []
            tasks[task_id]["failed_count"] = len(failed_texts)

        result = translator.translate_content(content, progress_callback=update_progress)
        tasks[task_id]["translations"] = [
            {"original": k, "translated": v}
            for k, v in result.translations.items()
        ]

        writer = PDFWriter(reader.get_document(), content)
        writer.apply_translations(result.translations)
        writer.save(output_path)

        if result.failed_texts:
            _mark_task_partial_success(task_id, result.failed_texts)
        else:
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["progress"] = 100
            tasks[task_id]["current_batch"] = []
    except Exception as e:
        _mark_task_failed(task_id, str(e), stage="pdf_translation", exc=e)
    finally:
        if reader is not None:
            reader.close()


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page"""
    html_path = Path(__file__).parent / "templates" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

    logger.error("Web template not found", extra={"template_path": str(html_path)})
    return HTMLResponse(content="<h1>Doctrans</h1><p>Template not found</p>", status_code=500)


@app.post("/api/translate")
async def translate(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    base_url: str = Form(None),
    api_key: str = Form(None),
    model: str = Form(None),
    source_lang: str = Form(None),
    target_lang: str = Form(None),
    keep_original_terms: str = Form(None),
):
    """Upload and translate a PPT or PDF file"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    filename_lower = file.filename.lower()
    if not filename_lower.endswith(".pptx") and not filename_lower.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pptx and .pdf files are supported")

    is_pdf = filename_lower.endswith(".pdf")

    # Load defaults from config
    default_config = load_default_config()
    llm_config = default_config.get("llm", {})

    # Generate task ID
    task_id = str(uuid.uuid4())

    # Save uploaded file
    input_path = UPLOAD_DIR / f"{task_id}_{file.filename}"
    if is_pdf:
        output_path = OUTPUT_DIR / f"{task_id}_translated_{Path(file.filename).stem}.pdf"
    else:
        output_path = OUTPUT_DIR / f"{task_id}_translated_{file.filename}"

    with open(input_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Create config with defaults
    config = TranslationConfig(
        base_url=base_url or llm_config.get("base_url"),
        api_key=api_key or llm_config.get("api_key"),
        model=model or llm_config.get("model", "gpt-4o-mini"),
        source_lang=source_lang or default_config.get("translation", {}).get("source_lang", "en"),
        target_lang=target_lang or default_config.get("translation", {}).get("target_lang", "zh"),
        keep_original_terms=keep_original_terms == "true",
    )

    # Initialize task
    tasks[task_id] = {
        "status": "queued",
        "progress": 0,
        "filename": file.filename,
        "output_path": str(output_path),
        "input_path": str(input_path),
        "config": config.model_dump(),
        "total": 0,
        "processed": 0,
        "current_batch": [],
        "translations": [],
        "failed_texts": [],
        "failed_count": 0,
        "retry_available": False,
        "file_type": "pdf" if is_pdf else "pptx",
    }

    # Start background translation
    if is_pdf:
        background_tasks.add_task(translate_pdf_task, task_id, input_path, output_path, config)
    else:
        background_tasks.add_task(translate_file_task, task_id, input_path, output_path, config)

    return {"task_id": task_id, "message": "Translation started"}


@app.post("/api/retry/{task_id}")
async def retry_failed(task_id: str, background_tasks: BackgroundTasks):
    """Retry only the texts that still failed in a previous run."""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    if task.get("status") != "completed_with_failures":
        raise HTTPException(status_code=400, detail="Retry is only available after a partial completion")

    failed_texts = task.get("failed_texts", [])
    if not failed_texts:
        raise HTTPException(status_code=400, detail="No failed texts available to retry")
    if not task.get("retry_available"):
        raise HTTPException(status_code=400, detail="Retry is not available for this task")

    config = TranslationConfig(**task["config"])
    input_path = Path(task["input_path"])
    output_path = Path(task["output_path"])

    task["error"] = None
    task["error_stage"] = None
    task["error_type"] = None

    if task.get("file_type") == "pdf":
        background_tasks.add_task(translate_pdf_task, task_id, input_path, output_path, config, failed_texts)
    else:
        background_tasks.add_task(translate_file_task, task_id, input_path, output_path, config, failed_texts)

    return {"task_id": task_id, "message": "Retry started"}


@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """Get translation task status"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    return {
        key: value
        for key, value in task.items()
        if key not in {"config"}
    }


@app.get("/api/download/{task_id}")
async def download(task_id: str):
    """Download translated file"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    if task["status"] not in {"completed", "completed_with_failures"}:
        raise HTTPException(status_code=400, detail="Translation not completed")

    output_path = Path(task["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Determine media type based on file type
    is_pdf = task.get("file_type") == "pdf"
    if is_pdf:
        media_type = "application/pdf"
    else:
        media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    return FileResponse(
        output_path,
        filename=f"translated_{task['filename']}",
        media_type=media_type,
    )


@app.get("/api/config")
async def get_config():
    """Get current configuration (without sensitive data)"""
    config = load_default_config()
    llm_config = config.get("llm", {})
    return {
        "base_url": llm_config.get("base_url", ""),
        "model": llm_config.get("model", "gpt-4o-mini"),
        "source_lang": config.get("translation", {}).get("source_lang", "en"),
        "target_lang": config.get("translation", {}).get("target_lang", "zh"),
    }
