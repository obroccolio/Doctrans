"""OpenAI-compatible LLM client implementation"""

import os
from openai import OpenAI
from .base import LLMClient


class OpenAIClient(LLMClient):
    """OpenAI-compatible API client for translation (works with any OpenAI-format API)"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4o-mini",
        source_lang: str = "en",
        target_lang: str = "zh",
        **kwargs,
    ):
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or api_key
        if not api_key:
            raise ValueError("API key is required (set LLM_API_KEY or OPENAI_API_KEY)")

        super().__init__(
            api_key=api_key,
            model=model,
            source_lang=source_lang,
            target_lang=target_lang,
            **kwargs,
        )
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def _call_api(self, prompt: str) -> str:
        """Make OpenAI-compatible API call"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional translator. Translate accurately while preserving formatting.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("OpenAI-compatible API returned empty content")
        return content
