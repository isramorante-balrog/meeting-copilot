"""OpenAI-compatible chat-completions providers: ChatGPT (OpenAI), Grok (xAI) and DeepSeek.

All three speak the same `/chat/completions` SSE protocol, so one small client covers them — no SDKs,
only `requests`. Keys come from config.json (`llm.providers.<name>.api_key`, entered in the first-run
wizard / Setup → Proveedores de IA) or from the usual environment variable.

    name       base_url                      env var            vision
    openai     https://api.openai.com/v1     OPENAI_API_KEY     yes
    xai        https://api.x.ai/v1           XAI_API_KEY        yes
    deepseek   https://api.deepseek.com/v1   DEEPSEEK_API_KEY   no

Default model names are only starting points: the wizard's "Modelos" button lists what the key can
actually use (GET /models) and "Probar" sends a one-line prompt, so a wrong name is caught before a call.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from typing import Callable

log = logging.getLogger("openai-compat")

TokenCallback = Callable[[str], None]

PRESETS: dict[str, dict] = {
    "openai": {"label": "ChatGPT (OpenAI)", "base_url": "https://api.openai.com/v1", "env": "OPENAI_API_KEY",
               "model": "gpt-4o-mini", "vision": True, "keys_url": "https://platform.openai.com/api-keys"},
    "xai": {"label": "Grok (xAI)", "base_url": "https://api.x.ai/v1", "env": "XAI_API_KEY",
            "model": "grok-3-mini", "vision": True, "keys_url": "https://console.x.ai"},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "env": "DEEPSEEK_API_KEY",
                 "model": "deepseek-chat", "vision": False, "keys_url": "https://platform.deepseek.com/api_keys"},
}
COMPAT_NAMES = tuple(PRESETS.keys())


class OpenAICompatClient:
    """Streaming chat client with the same surface as ClaudeCLI / GeminiClient (available, stream, stream_vision)."""

    def __init__(self, name: str, cfg: dict | None = None):
        if name not in PRESETS:
            raise ValueError(f"unknown provider {name!r}")
        self.name = name
        self.preset = PRESETS[name]
        self.configure(cfg or {})

    def configure(self, cfg: dict) -> None:
        self.api_key = (cfg.get("api_key") or os.environ.get(self.preset["env"], "")).strip()
        self.base_url = (cfg.get("base_url") or self.preset["base_url"]).rstrip("/")
        self.model = (cfg.get("model") or self.preset["model"]).strip()
        self.supports_vision = bool(cfg.get("vision", self.preset["vision"]))
        self.timeout_s = float(cfg.get("timeout_s", 60))
        self.last_error: str | None = None

    def available(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------ internals
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _chat(self, messages: list[dict], on_token: TokenCallback, cancel: threading.Event, max_tokens: int = 700) -> str:
        import requests

        if not self.available():
            raise RuntimeError(f"{self.preset['env']} not set ({self.preset['label']})")
        body = {"model": self.model, "messages": messages, "stream": True, "temperature": 0.3, "max_tokens": max_tokens}
        out: list[str] = []
        with requests.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body, stream=True,
                           timeout=(10, self.timeout_s)) as r:
            if r.status_code == 400 and "max_tokens" in r.text:
                # newer OpenAI reasoning models only accept max_completion_tokens and a default temperature
                r.close()
                body.pop("max_tokens", None)
                body.pop("temperature", None)
                body["max_completion_tokens"] = max_tokens * 4
                return self._chat_raw(body, on_token, cancel)
            if r.status_code != 200:
                raise RuntimeError(self._error_text(r))
            r.encoding = "utf-8"
            for text in self._iter_sse(r, cancel):
                out.append(text)
                on_token(text)
        self.last_error = None
        return "".join(out)

    def _chat_raw(self, body: dict, on_token: TokenCallback, cancel: threading.Event) -> str:
        import requests

        out: list[str] = []
        with requests.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body, stream=True,
                           timeout=(10, self.timeout_s)) as r:
            if r.status_code != 200:
                raise RuntimeError(self._error_text(r))
            r.encoding = "utf-8"
            for text in self._iter_sse(r, cancel):
                out.append(text)
                on_token(text)
        return "".join(out)

    @staticmethod
    def _iter_sse(r, cancel: threading.Event):
        for line in r.iter_lines(decode_unicode=True):
            if cancel.is_set():
                break
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = (json.loads(data).get("choices") or [{}])[0].get("delta") or {}
            except (ValueError, IndexError, AttributeError):
                continue
            text = delta.get("content")
            if text:
                yield text

    def _error_text(self, r) -> str:
        try:
            err = r.json().get("error")
            msg = err.get("message") if isinstance(err, dict) else str(err)
        except Exception:  # noqa: BLE001
            msg = r.text[:200]
        hint = {401: "invalid API key", 403: "key not allowed for this model", 404: f"model '{self.model}' not found",
                429: "rate limit or no credit on the account"}.get(r.status_code, "")
        self.last_error = f"{self.preset['label']} HTTP {r.status_code}: {msg or hint}" + (f" ({hint})" if hint and msg else "")
        return self.last_error

    # ------------------------------------------------------------------ public surface
    def stream(self, system_prompt: str, user_prompt: str, on_token: TokenCallback, cancel: threading.Event) -> str:
        return self._chat([{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                          on_token, cancel)

    def stream_vision(self, system_prompt: str, user_prompt: str, image_bytes: bytes, mime: str,
                      on_token: TokenCallback, cancel: threading.Event) -> str:
        if not self.supports_vision:
            raise RuntimeError(f"{self.preset['label']} has no image input - falling back to the next provider")
        url = f"data:{mime or 'image/jpeg'};base64,{base64.b64encode(image_bytes).decode()}"
        return self._chat([{"role": "system", "content": system_prompt},
                           {"role": "user", "content": [{"type": "text", "text": user_prompt},
                                                        {"type": "image_url", "image_url": {"url": url}}]}],
                          on_token, cancel, max_tokens=800)

    def list_models(self) -> list[str]:
        import requests

        if not self.available():
            return []
        try:
            r = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=15)
            if r.status_code != 200:
                self._error_text(r)
                return []
            ids = sorted({m.get("id", "") for m in (r.json().get("data") or []) if m.get("id")})
            skip = ("embedding", "whisper", "tts", "dall-e", "moderation", "audio", "realtime", "image", "transcribe")
            return [i for i in ids if not any(s in i for s in skip)]
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            return []

    def test(self) -> dict:
        """One short round-trip for the wizard's Probar button."""
        t0 = time.time()
        try:
            text = self.stream("Reply with exactly: OK", "ping", lambda _t: None, threading.Event())
            return {"ok": bool(text.strip()), "ms": int((time.time() - t0) * 1000), "sample": text.strip()[:40],
                    "model": self.model, "error": None if text.strip() else "empty response"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "ms": int((time.time() - t0) * 1000), "sample": "", "model": self.model,
                    "error": str(exc).splitlines()[0][:300]}
