"""Secondary brain: Google Gemini API (free tier) via the `google-genai` SDK.

Used for: fallback generation when Claude is unavailable/fails, call
summaries, and (optionally) utterance classification.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Callable, Optional

from prompts import CLASSIFIER_PROMPT

log = logging.getLogger("gemini")

TokenCallback = Callable[[str], None]


class GeminiClient:
    name = "gemini"

    def __init__(self, api_key_env: str = "GEMINI_API_KEY", model: str = "gemini-2.5-flash", api_key: str = ""):
        # key entered in the app (config.json) wins over the environment variables
        self.api_key = (api_key or "").strip() or os.environ.get(api_key_env, "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
        self.model = model or "gemini-2.5-flash"
        self._client = None
        self._types = None
        self._init_error: Optional[str] = None

    def available(self) -> bool:
        return bool(self.api_key) and self._ensure_client()

    def _ensure_client(self) -> bool:
        if self._client is not None:
            return True
        if not self.api_key:
            return False
        try:
            from google import genai
            from google.genai import types

            self._client = genai.Client(api_key=self.api_key)
            self._types = types
            return True
        except Exception as exc:
            self._init_error = str(exc)
            log.warning("google-genai unavailable: %s", exc)
            return False

    def stream(self, system_prompt: str, user_prompt: str, on_token: TokenCallback,
               cancel: threading.Event) -> str:
        if not self.available():
            raise RuntimeError(self._init_error or "GEMINI_API_KEY not set")
        types = self._types
        cfg = types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.3,
                                          max_output_tokens=600)
        out: list[str] = []
        for chunk in self._client.models.generate_content_stream(
            model=self.model, contents=user_prompt, config=cfg
        ):
            if cancel.is_set():
                break
            text = getattr(chunk, "text", None)
            if text:
                out.append(text)
                on_token(text)
        return "".join(out)

    def stream_vision(self, system_prompt: str, user_prompt: str, image_bytes: bytes, mime: str,
                      on_token: TokenCallback, cancel: threading.Event) -> str:
        if not self.available():
            raise RuntimeError(self._init_error or "GEMINI_API_KEY not set")
        types = self._types
        cfg = types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.3, max_output_tokens=700)
        contents = [types.Part.from_bytes(data=image_bytes, mime_type=mime or "image/jpeg"), user_prompt]
        out: list[str] = []
        for chunk in self._client.models.generate_content_stream(model=self.model, contents=contents, config=cfg):
            if cancel.is_set():
                break
            text = getattr(chunk, "text", None)
            if text:
                out.append(text)
                on_token(text)
        return "".join(out)

    def list_models(self) -> list[str]:
        """Names of Gemini models that support generateContent (empty if unavailable)."""
        if not self.available():
            return []
        names: list[str] = []
        try:
            for m in self._client.models.list():
                actions = getattr(m, "supported_actions", None) or []
                if actions and "generateContent" not in actions:
                    continue
                name = (getattr(m, "name", "") or "").replace("models/", "")
                if name.startswith("gemini"):
                    names.append(name)
        except Exception as exc:
            log.warning("gemini list_models failed: %s", exc)
        return sorted(set(names))

    def classify(self, text: str) -> Optional[bool]:
        """Return True/False, or None when classification failed (caller falls back)."""
        if not self.available():
            return None
        types = self._types
        try:
            resp = self._client.models.generate_content(
                model=self.model,
                contents=CLASSIFIER_PROMPT.format(text=text.strip()),
                config=types.GenerateContentConfig(
                    temperature=0.0, max_output_tokens=60, response_mime_type="application/json"
                ),
            )
            data = json.loads(resp.text or "{}")
            return bool(data.get("needs_answer"))
        except Exception as exc:
            log.debug("gemini classify failed: %s", exc)
            return None
