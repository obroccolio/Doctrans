"""Abstract base class for LLM clients"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    """Result of a translation request"""
    original: str
    translated: str
    success: bool
    error: str | None = None


class LLMClient(ABC):
    """Abstract base class for LLM translation clients"""

    def __init__(
        self,
        api_key: str,
        model: str,
        source_lang: str = "en",
        target_lang: str = "zh",
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.api_key = api_key
        self.model = model
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    @abstractmethod
    def _call_api(self, prompt: str) -> str:
        """Make the actual API call. Must be implemented by subclasses."""
        pass

    def _build_translation_prompt(self, text: str, context: str | None = None) -> str:
        """Build the translation prompt"""
        lang_names = {
            "en": "English",
            "zh": "Chinese",
            "ja": "Japanese",
            "ko": "Korean",
            "fr": "French",
            "de": "German",
            "es": "Spanish",
        }
        source = lang_names.get(self.source_lang, self.source_lang)
        target = lang_names.get(self.target_lang, self.target_lang)

        prompt = f"""Translate the following text from {source} to {target}.

Rules:
1. Maintain the original formatting and structure
2. Keep proper nouns, brand names, and technical terms as appropriate
3. Do not add explanations or notes
4. Only output the translated text, nothing else
5. If the text contains numbers, dates, or code, keep them unchanged
6. Preserve line breaks and spacing

"""
        if context:
            prompt += f"Context: {context}\n\n"

        prompt += f"Text to translate:\n{text}"
        return prompt

    def translate(self, text: str, context: str | None = None) -> TranslationResult:
        """Translate a single piece of text"""
        if not text or not text.strip():
            return TranslationResult(original=text, translated=text, success=True)

        prompt = self._build_translation_prompt(text, context)

        for attempt in range(self.max_retries):
            try:
                translated = self._call_api(prompt)
                return TranslationResult(
                    original=text,
                    translated=translated.strip(),
                    success=True,
                )
            except Exception as e:
                logger.warning(f"Translation attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    return TranslationResult(
                        original=text,
                        translated=text,
                        success=False,
                        error=str(e),
                    )

        return TranslationResult(original=text, translated=text, success=False)

    def translate_batch(
        self, texts: list[str], context: str | None = None
    ) -> list[TranslationResult]:
        """Translate multiple texts. Can be overridden for batch optimization."""
        return [self.translate(text, context) for text in texts]
