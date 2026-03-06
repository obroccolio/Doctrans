"""Translator - Coordinate translation using LLM"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from .llm.base import LLMClient
from .ppt_reader import PresentationContent

logger = logging.getLogger(__name__)

# 每批翻译的目标 token 数（约 500 tokens）
TARGET_BATCH_TOKENS = 500
# 并发请求数
MAX_CONCURRENT_REQUESTS = 5


@dataclass
class TranslationRunResult:
    """Result of translating a document."""

    translations: dict[str, str]
    failed_texts: list[str]


class BatchTranslationError(Exception):
    """Raised when some texts still fail after retrying a batch."""

    def __init__(self, failed_texts: list[str]):
        super().__init__(f"Failed to translate {len(failed_texts)} text item(s)")
        self.failed_texts = failed_texts


def estimate_tokens(text: str) -> int:
    """Estimate token count for text (rough: 1 token ≈ 4 chars for English, 1.5 chars for CJK)"""
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
    other_count = len(text) - cjk_count
    return int(cjk_count / 1.5 + other_count / 4) + 1


def is_unchanged_translation(
    original: str,
    translated: str,
    source_lang: str,
    target_lang: str,
) -> bool:
    """Check if translation result is unchanged and should be retried."""
    if not original or not original.strip():
        return False
    if source_lang == target_lang:
        return False
    return original.strip() == translated.strip()


def is_math_content(text: str) -> bool:
    """Check if text is primarily mathematical content that should not be translated.

    Returns True for:
    - Pure math formulas like "y = g(x)", "dz/dx", "Δx → Δy"
    - Single variables or short variable expressions
    - Greek letter expressions
    """
    if not text or not text.strip():
        return False

    text = text.strip()

    # Math symbols and operators
    math_symbols = set('=+-×÷·∂∫∑∏√∞≈≠≤≥<>()[]{}^_/\\|')
    # Greek letters (commonly used in math)
    greek_letters = set('αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ∆')
    # Common math variable names
    math_chars = set('xyzstuvwnmijkabcdfghpqr')

    # Count different character types
    math_symbol_count = sum(1 for c in text if c in math_symbols or c in greek_letters)
    letter_count = sum(1 for c in text.lower() if c in math_chars)
    space_count = sum(1 for c in text if c.isspace())
    digit_count = sum(1 for c in text if c.isdigit())

    # Total "math-like" characters
    math_like = math_symbol_count + letter_count + space_count + digit_count

    # If more than 80% of characters are math-related, consider it math content
    if len(text) > 0 and math_like / len(text) > 0.8:
        # Additional check: must contain at least one math symbol or be very short
        if math_symbol_count > 0 or len(text) <= 10:
            return True

    # Check for common math patterns
    import re
    math_patterns = [
        r'^[a-zA-Z]\s*=\s*[a-zA-Z]',  # x = y
        r'^\s*[Δ∂][a-zA-Z]',  # Δx, ∂x
        r'd[a-zA-Z]/d[a-zA-Z]',  # dx/dy
        r'∂[a-zA-Z]/∂[a-zA-Z]',  # ∂z/∂x
        r'^[a-zA-Z]\([a-zA-Z,\s]+\)$',  # f(x), g(x,y)
    ]
    for pattern in math_patterns:
        if re.search(pattern, text):
            return True

    return False


class Translator:
    """Coordinate translation of presentation content"""

    def __init__(
        self,
        llm_client: LLMClient,
        keep_original_terms: bool = False,
        initial_cache: dict[str, str] | None = None,
    ):
        self.llm = llm_client
        self._cache: dict[str, str] = dict(initial_cache or {})
        self.keep_original_terms = keep_original_terms

    def _build_batch_prompt(self, texts: list[str], context: str | None = None) -> str:
        """Build prompt for batch translation"""
        lang_names = {
            "en": "English", "zh": "Chinese", "ja": "Japanese",
            "ko": "Korean", "fr": "French", "de": "German", "es": "Spanish",
        }
        source = lang_names.get(self.llm.source_lang, self.llm.source_lang)
        target = lang_names.get(self.llm.target_lang, self.llm.target_lang)

        # 构建 JSON 格式的输入
        items = {str(i): text for i, text in enumerate(texts)}

        prompt = f"""You are a professional translator. Translate from {source} to {target}.

RULES:
- Preserve original formatting (line breaks, punctuation, spacing)
- Keep unchanged: numbers, dates, URLs, code, brand names
- Keep unchanged: ALL mathematical content including:
  - Math formulas and equations (e.g., y = g(x), dz/dx = dz/dy · dy/dx)
  - Variable names (x, y, z, s, t, n, etc.)
  - Greek letters (Δ, α, β, γ, ∂, Σ, etc.)
  - Math symbols (=, +, -, ×, ÷, ∂, ∫, √, etc.)
  - Subscripts and superscripts
- If a sentence mixes natural language and math, translate ONLY the natural language parts and keep all math expressions unchanged
- Examples:
  - "The derivative is y = g(x)" -> "导数是 y = g(x)"
  - "When Δx approaches 0, f(x) changes" -> "当 Δx 趋近于 0 时，f(x) 发生变化"
- Translate naturally, not word-by-word
- Output ONLY valid JSON, no explanation
"""
        if self.keep_original_terms:
            prompt += "- For key technical terms in this field, mark the original word in parentheses after the translation. Example: 反向传播(Backpropagation)\n"

        prompt += "\n"
        if context:
            prompt += f"CONTEXT: {context}\n\n"

        prompt += f"""INPUT:
{json.dumps(items, ensure_ascii=False)}

OUTPUT (JSON only):"""
        return prompt

    def _create_batches_by_slide(self, content: PresentationContent, texts_to_translate: set[str]) -> list[list[str]]:
        """Split texts into batches by slide - each slide's content stays together"""
        batches = []

        for slide in content.slides:
            slide_texts = []
            for element in slide.elements:
                if element.text in texts_to_translate:
                    slide_texts.append(element.text)

            if slide_texts:
                # Remove duplicates while preserving order
                seen = set()
                unique_texts = []
                for text in slide_texts:
                    if text not in seen:
                        seen.add(text)
                        unique_texts.append(text)
                batches.append(unique_texts)

        return batches

    def _parse_batch_response(self, response: str, original_texts: list[str]) -> dict[str, str]:
        """Parse batch translation response"""
        try:
            # 清理响应，提取 JSON
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            result = json.loads(response)
            translations = {}
            for i, text in enumerate(original_texts):
                translated = result.get(str(i), text)
                translations[text] = translated
            return translations
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse batch response: {e}")
            # 返回原文
            return {text: text for text in original_texts}

    def _parse_batch_response_with_failures(
        self, response: str, original_texts: list[str]
    ) -> tuple[dict[str, str], list[str]]:
        """Parse batch translation response and return missing items."""
        try:
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            result = json.loads(response)
            if not isinstance(result, dict):
                raise ValueError("Batch response JSON is not an object")

            translations: dict[str, str] = {}
            failed: list[str] = []
            for i, text in enumerate(original_texts):
                key = str(i)
                if key in result:
                    translations[text] = str(result[key])
                else:
                    failed.append(text)

            return translations, failed
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse batch response: {e}")
            return {}, list(original_texts)

    def translate_batch(self, texts: list[str], context: str | None = None) -> tuple[dict[str, str], list[str]]:
        """Translate a batch of texts in one API call."""
        if not texts:
            return {}, []

        # Keep only pure formula-like content unchanged; mixed text should still go to LLM
        math_texts = {
            text: text
            for text in texts
            if is_math_content(text) and not any(c.isalpha() for c in text)
        }
        pending_texts = [text for text in texts if text not in math_texts]
        results: dict[str, str] = dict(math_texts)

        if not pending_texts:
            return results, []

        max_retries = max(1, self.llm.max_retries)

        for attempt in range(max_retries):
            try:
                prompt = self._build_batch_prompt(pending_texts, context)
                response = self.llm._call_api(prompt)
                parsed, parse_failures = self._parse_batch_response_with_failures(
                    response, pending_texts
                )

                retry_texts: list[str] = []
                for text in pending_texts:
                    if text in parse_failures:
                        retry_texts.append(text)
                        continue

                    translated = parsed.get(text, text)
                    if is_unchanged_translation(
                        text, translated, self.llm.source_lang, self.llm.target_lang
                    ):
                        retry_texts.append(text)
                        continue

                    results[text] = translated

                pending_texts = retry_texts
                if not pending_texts:
                    break
            except Exception as e:
                logger.warning(f"Batch translation attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    break

        failed_texts = list(pending_texts)
        for text in failed_texts:
            results[text] = text

        return results, failed_texts

    def translate_content(
        self, content: PresentationContent, progress_callback=None
    ) -> TranslationRunResult:
        """
        Translate all unique texts in the presentation using batch API calls.
        Returns translations and a list of texts that still failed after retries.
        """
        all_texts = content.all_texts
        total = len(all_texts)
        translations: dict[str, str] = {}
        failed_texts: list[str] = []

        # Use presentation title as context if available
        context = None
        if content.slides and content.slides[0].title:
            context = f"This is a presentation titled: {content.slides[0].title}"

        # 分离已缓存和未缓存的文本
        texts_to_translate = []
        for text in all_texts:
            if text in self._cache:
                translations[text] = self._cache[text]
            else:
                texts_to_translate.append(text)

        # 按幻灯片分批（保证同一幻灯片内容在同一批次）
        batches = self._create_batches_by_slide(content, set(texts_to_translate))
        processed = len(translations)

        if progress_callback:
            progress_callback(processed, total, "", [], [])

        # 并发翻译
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
            future_to_batch = {
                executor.submit(self.translate_batch, batch, context): batch
                for batch in batches
            }

            if progress_callback and batches:
                all_pending = [text for batch in batches for text in batch]
                progress_callback(processed, total, "", all_pending[:20], failed_texts)

            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                batch_result, batch_failures = future.result()
                for text, translated in batch_result.items():
                    translations[text] = translated
                    self._cache[text] = translated
                    processed += 1

                if batch_failures:
                    failed_texts.extend(batch_failures)

                if progress_callback:
                    progress_callback(processed, total, "", [], failed_texts)

        return TranslationRunResult(translations=translations, failed_texts=failed_texts)

    def clear_cache(self) -> None:
        """Clear the translation cache"""
        self._cache.clear()


class PDFTranslator(Translator):
    """Translator for PDF content - translates by page"""

    def _create_batches_by_page(self, content, texts_to_translate: set[str]) -> list[list[str]]:
        """Split texts into batches by page - each page's content stays together"""
        batches = []

        for page in content.pages:
            page_texts = []
            for block in page.blocks:
                if block.text in texts_to_translate:
                    page_texts.append(block.text)

            if page_texts:
                # Remove duplicates while preserving order
                seen = set()
                unique_texts = []
                for text in page_texts:
                    if text not in seen:
                        seen.add(text)
                        unique_texts.append(text)
                batches.append(unique_texts)

        return batches

    def translate_content(self, content, progress_callback=None) -> TranslationRunResult:
        """Translate all unique texts in the PDF using batch API calls."""
        all_texts = content.all_texts
        total = len(all_texts)
        translations: dict[str, str] = {}
        failed_texts: list[str] = []

        # Use first page text as context
        context = None
        if content.pages and content.pages[0].blocks:
            first_text = content.pages[0].blocks[0].text[:100]
            context = f"This is a PDF document. First content: {first_text}"

        # Separate cached and uncached texts
        texts_to_translate = []
        for text in all_texts:
            if text in self._cache:
                translations[text] = self._cache[text]
            else:
                texts_to_translate.append(text)

        # Batch by page
        batches = self._create_batches_by_page(content, set(texts_to_translate))
        processed = len(translations)

        if progress_callback:
            progress_callback(processed, total, "", failed_texts)

        # Concurrent translation
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
            future_to_batch = {
                executor.submit(self.translate_batch, batch, context): batch
                for batch in batches
            }

            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                batch_result, batch_failures = future.result()
                for text, translated in batch_result.items():
                    translations[text] = translated
                    self._cache[text] = translated
                    processed += 1

                if batch_failures:
                    failed_texts.extend(batch_failures)

                if progress_callback:
                    progress_callback(processed, total, "", failed_texts)

        return TranslationRunResult(translations=translations, failed_texts=failed_texts)
