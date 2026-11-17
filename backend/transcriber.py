"""Speech-to-text engines (switchable at runtime via stt.engine in config.json).

  deepgram       Deepgram Nova-3 live streaming (primary / recommended). v19: two pre-warmed native sockets per
                 channel (es-419 + en-US); EN/ES/AUTO moves the audio routing pointer in 0 ms, never reconnects.
                 Raw 16 kHz int16 PCM is streamed per channel; interim results come back every ~200 ms,
                 `is_final` segments are merged into the turn, `speech_final` / UtteranceEnd ends it.
                 v16: endpointing / utterance_end tuned so breathing pauses do not split a sentence; the server
                 accumulates consecutive remote segments into one turn.
                 v18: `language=multi` — Nova-3 native bilingual mode. Spanish, English and mid-sentence
                 code-switching are transcribed on the SAME open socket; the EN|ES|AUTO toggle changes only the
                 answer language and never reconnects (0 ms audio drop). A 400 on connect retries without
                 `keyterm` at once, so the stream stays up even if keyterm prompting is rejected.
                 Domain keyterms (built-in IAM vocabulary + terms mined from the profile) are passed as
                 `keyterm` so product names and acronyms are recognised reliably.
  whisper_local  faster-whisper on the local machine. Whole utterances only (no mid-word slicing): the
                 audio_capture segmenter ends a turn on a real pause and faster-whisper's Silero VAD
                 (vad_filter) trims it; a domain `initial_prompt` helps technical terms. Anti-hallucination:
                 condition_on_previous_text=False and a repetition filter (any token repeated more than 4 times
                 in a row is collapsed; a segment that is mostly one repeated token is dropped). Language is
                 auto-detected per utterance unless stt.force_language is set, so English is never forced
                 through a Spanish decoder ("si, si, si"). Falls back cuda -> cpu/int8 safely.
  groq_whisper   Groq's whisper-large-v3-turbo endpoint for whole utterances (large-v3 accuracy, ~0.2-0.5 s).

All engines report into the same callbacks so server.py does not care which one is active:
  on_interim(channel, text)             live preview while the speaker is still talking (streaming engines)
  on_piece(channel, text, final)        a finalised piece of the current turn; final=True ends the turn
  on_state(engine_state: dict)          connection / health changes
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import site
import sys
import threading
import time
import urllib.parse
import wave
from pathlib import Path
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("stt")

ENGINES = ("deepgram", "whisper_local", "groq_whisper")

# ---- built-in cybersecurity / IAM vocabulary (always boosted) ---------------------------------
BUILTIN_VOCAB = [
    "CyberArk", "SailPoint", "Saviynt", "Entra ID", "Okta", "Conjur", "SAML", "OIDC", "SCIM", "Kerberos", "NTLM",
    "gMSA", "SOX ITGC", "ISO 27001", "Privilege Cloud", "PVWA", "CPM", "PSM", "PSMP", "EPM", "Splunk", "ArcSight",
    "NIST", "Active Directory", "PAM", "IAM", "IGA", "MFA", "SSO", "LDAP", "Azure AD", "Delinea", "Secret Server",
    "BeyondTrust", "HashiCorp Vault", "OAuth", "JWT", "RBAC", "ABAC", "PIM", "JIT", "break glass", "zero trust",
    "NHI", "non-human identities", "service accounts", "workload identity", "AD forest", "domain trust", "GPO",
]

WHISPER_INITIAL_PROMPT = ("Technical discussion covering IAM, PAM, CyberArk PAS, Privilege Cloud, Conjur, SailPoint, "
                          "Saviynt, Entra ID, Active Directory, Kerberos, SAML, OIDC, SCIM, SOX ITGC, ISO 27001.")
# v19: the Spanish decoder gets a SPANISH prompt - an English initial_prompt made Whisper hallucinate English
WHISPER_INITIAL_PROMPT_ES = ("Entrevista técnica en español sobre ciberseguridad, IAM, PAM, CyberArk, Privilege Cloud, "
                             "Conjur, SailPoint, Saviynt, Entra ID, Active Directory, Kerberos, SAML, OIDC, SOX ITGC, ISO 27001.")
WHISPER_PROMPTS = {"en": WHISPER_INITIAL_PROMPT, "es": WHISPER_INITIAL_PROMPT_ES}


def whisper_prompt(lang: str | None, vocabulary: list[str] | None = None, extra: str = "") -> str:
    base = WHISPER_PROMPTS.get(lang or "en", WHISPER_INITIAL_PROMPT)
    if extra and extra.strip():
        base = f"{base} {extra.strip()}"
    if vocabulary:
        terms = ", ".join(v for v in vocabulary if v.lower() not in base.lower())[:400]
        if terms:
            base = f"{base} {'Términos' if lang == 'es' else 'Terms'}: {terms}."
    return base

_NOISE_PHRASES = {
    "thank you.", "thanks for watching.", "thank you for watching.", "you", "you.", "bye.", ".",
    "subtítulos realizados por la comunidad de amara.org", "gracias.", "gracias por ver.",
}

InterimCb = Callable[[str, str], None]
PieceCb = Callable[[str, str, bool], None]
StateCb = Callable[[dict], None]


# ---- "did the sentence finish?" heuristic for the adaptive VAD (EN/ES, <0.1 ms) -------------------
_DANGLING = {
    "and", "or", "but", "so", "because", "if", "when", "while", "that", "which", "who", "where", "how", "what",
    "why", "with", "without", "to", "of", "for", "from", "in", "on", "at", "by", "about", "into", "through",
    "between", "than", "the", "a", "an", "my", "your", "our", "their", "this", "these", "those", "is", "are",
    "was", "were", "be", "been", "have", "has", "had", "do", "does", "did", "can", "could", "would", "should",
    "will", "not", "very", "really", "also", "then", "versus", "vs",
    "y", "o", "pero", "porque", "si", "cuando", "mientras", "que", "cual", "cuál", "quien", "quién", "donde",
    "dónde", "como", "cómo", "qué", "con", "sin", "de", "del", "para", "por", "en", "a", "al", "sobre", "entre",
    "hasta", "desde", "el", "la", "los", "las", "un", "una", "mi", "tu", "su", "nuestro", "nuestra", "este",
    "esta", "esto", "es", "son", "fue", "era", "está", "están", "hay", "no", "muy", "también", "entonces", "o sea",
}
_ENDS_COMPLETE = re.compile(r"[.!?…]['\")\]]?\s*$")


def looks_complete(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if s.endswith((",", ";", ":", "-", "—")):
        return False
    if _ENDS_COMPLETE.search(s):
        return True
    last = re.sub(r"[^\wáéíóúñü]", "", s.split()[-1].lower()) if s.split() else ""
    if last in _DANGLING:
        return False
    return True


# ---- vocabulary mining ---------------------------------------------------------------------------
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
_PRODUCT = re.compile(r"\b(?:[A-Z][a-z]+[A-Z][A-Za-z]+|[A-Z][a-z]{2,}(?: [A-Z][a-z]{2,}){1,2})\b")
_STOP_CAPS = {"THE", "AND", "FOR", "WITH", "THIS", "THAT", "FROM", "INTO", "OVER", "YOUR", "OUR", "NOT", "ALL", "ANY",
              "NEW", "ONE", "TWO", "USA", "EU", "CV", "PDF", "ETC", "I", "II", "III", "IV", "Q1", "Q2", "Q3", "Q4"}


def mine_vocabulary(texts: list[str], max_terms: int = 60) -> list[str]:
    """Technical terms / acronyms / product names mined from the profile documents + the built-in list.
    Deterministic, <5 ms; capped so the Deepgram URL stays short."""
    freq: dict[str, int] = {}
    for text in texts:
        for m in _ACRONYM.findall(text or ""):
            if m not in _STOP_CAPS and not m.isdigit():
                freq[m] = freq.get(m, 0) + 1
        for m in _PRODUCT.findall(text or ""):
            if 4 <= len(m) <= 32:
                freq[m] = freq.get(m, 0) + 1
    mined = [t for t, _ in sorted(freq.items(), key=lambda kv: -kv[1])]
    seen, out = set(), []
    for t in BUILTIN_VOCAB + mined:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
        if len(out) >= max_terms:
            break
    return out


def pcm16(audio_16k: np.ndarray) -> bytes:
    return (np.clip(np.asarray(audio_16k, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2").tobytes()


def wav_bytes(audio_16k: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm16(audio_16k))
    return buf.getvalue()


def _clean(text: str) -> str:
    t = (text or "").strip()
    if not t or t.lower() in _NOISE_PHRASES or len(t) < 2:
        return ""
    return t


_WORD_RE = re.compile(r"[\wáéíóúñü']+", re.I)


def squash_repetitions(text: str, max_run: int = 4) -> str:
    """Whisper anti-hallucination: collapse any token repeated more than `max_run` times in a row
    ("si si si si si si" -> "si si si si") and drop a segment that is mostly one repeated token."""
    t = (text or "").strip()
    if not t:
        return ""
    toks = t.split()
    if len(toks) < max_run + 1:
        return t
    out, run, prev = [], 0, None
    for tok in toks:
        key = tok.lower().strip(".,;:!?¿¡")
        if key == prev:
            run += 1
            if run > max_run:
                continue
        else:
            prev, run = key, 1
        out.append(tok)
    squashed = " ".join(out)
    words = [w.lower() for w in _WORD_RE.findall(squashed)]
    if len(words) >= 6:
        top = max(words.count(w) for w in set(words))
        if top / len(words) > 0.6:          # "yeah yeah yeah yeah, yeah." -> garbage
            return ""
    return squashed


# ==================================================================================================
# Option B — local faster-whisper (whole utterances, Silero VAD, vocabulary prompt)
# ==================================================================================================
def _register_nvidia_dlls() -> int:
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return 0
    n = 0
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        root = Path(sp) / "nvidia"
        if not root.is_dir():
            continue
        for d in root.iterdir():
            b = d / "bin"
            if b.is_dir():
                try:
                    os.add_dll_directory(str(b))
                    os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
                    n += 1
                except OSError:
                    pass
    return n


def _cuda_usable() -> bool:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() <= 0:
            return False
    except Exception as exc:  # noqa: BLE001
        log.info("CUDA not available: %s", exc)
        return False
    import ctypes.util

    names = ["cublas64_12"] if sys.platform == "win32" else ["cublas"]
    found = any(ctypes.util.find_library(n) for n in names)
    if not found:
        log.warning("GPU detected but the CUDA runtime (cuBLAS 12) is not installed - using CPU. "
                    "For GPU: pwsh .\\scripts\\bootstrap.ps1 -Cuda")
    return found


def _is_cuda_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("cublas", "cudnn", "cuda", "cudart", "nvrtc"))


class WhisperLocalEngine:
    name = "whisper_local"
    streaming = False

    def __init__(self, model_size: str = "small", device: str = "auto", compute_type: str = "default",
                 language: str | None = None, vocabulary: list[str] | None = None, initial_prompt: str = ""):
        _register_nvidia_dlls()
        from faster_whisper import WhisperModel

        self._WhisperModel = WhisperModel
        self.model_size = model_size
        self.vocabulary = list(vocabulary or [])
        self.extra_prompt = (initial_prompt or "").strip()
        self.mode = "auto"
        self.default_language = "en"
        self.last_detected: str | None = None
        self.language = language or None          # explicit decoder language; set_language() keeps it in sync
        self.initial_prompt = whisper_prompt(self.language or "en", self.vocabulary, self.extra_prompt)
        self._lock = threading.Lock()
        self.busy = False
        self.count = 0
        self.last_ms = 0
        self.fallbacks = 0
        self.model = None
        self._last_load_error: Exception | None = None
        if device == "auto":
            attempts = ([("cuda", "float16" if compute_type in ("auto", "default") else compute_type)] if _cuda_usable() else []) + \
                       [("cpu", "int8" if compute_type in ("auto", "default") else compute_type)]
        elif device == "cuda":
            attempts = [("cuda", "float16" if compute_type in ("auto", "default") else compute_type), ("cpu", "int8")]
        else:
            ct = compute_type if compute_type not in ("auto", "default") else "int8"
            attempts = [("cpu", ct)] + ([("cpu", "int8")] if ct != "int8" else [])
        cuda_failed = False
        for dev, ct in attempts:
            if dev == "cuda" and cuda_failed:
                continue
            if self._try_load(dev, ct):
                break
            if dev == "cuda":
                cuda_failed = True
        if self.model is None:
            raise RuntimeError(f"faster-whisper could not load '{model_size}': {self._last_load_error}")
        log.info("faster-whisper ready on %s/%s (prompt: %d chars)", self.device, self.compute_type, len(self.initial_prompt))

    def set_language(self, lang: str | None, default: str | None = None, source: str = "user") -> bool:
        """EN / ES: decode in that language with that language's prompt. AUTO: the profile default language
        (the server flips it when a finished utterance reads as the other language)."""
        if default in ("en", "es"):
            self.default_language = default
        if lang in ("en", "es", "auto"):
            self.mode = lang
        target = self.mode if self.mode in ("en", "es") else self.default_language
        changed = target != self.language
        self.language = target
        self.initial_prompt = whisper_prompt(target, self.vocabulary, self.extra_prompt)
        if changed:
            log.info("faster-whisper decoder language -> %s (%s)", target, source)
        return changed

    def flip_auto(self, lang: str, source: str = "auto") -> bool:
        if self.mode != "auto" or lang not in ("en", "es") or lang == self.language:
            return False
        self.language = lang
        self.initial_prompt = whisper_prompt(lang, self.vocabulary, self.extra_prompt)
        log.info("faster-whisper decoder language -> %s (%s)", lang, source)
        return True

    def _try_load(self, dev: str, ct: str) -> bool:
        try:
            log.info("Loading faster-whisper '%s' (device=%s, compute=%s)…", self.model_size, dev, ct)
            model = self._WhisperModel(self.model_size, device=dev, compute_type=ct)
            segs, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language=self.language or "en", beam_size=1,
                                       vad_filter=False, without_timestamps=True)
            for _ in segs:
                pass
            self.model, self.device, self.compute_type = model, dev, ct
            self._last_load_error = None
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_load_error = exc
            log.warning("faster-whisper unusable on %s/%s: %s", dev, ct, str(exc).splitlines()[0][:200])
            return False

    def _fallback_to_cpu(self, exc: Exception) -> bool:
        if self.device == "cpu" and self.compute_type == "int8":
            return False
        log.warning("CUDA runtime error (%s) — reloading faster-whisper on cpu/int8", str(exc).splitlines()[0][:120])
        self.fallbacks += 1
        return self._try_load("cpu", "int8")

    def transcribe(self, audio_16k: np.ndarray) -> str:
        """Whole utterance in, text out. Silero VAD trims leading/trailing silence and bridges short pauses
        (min_silence 600 ms, pad 300 ms) so words are never cut."""
        if audio_16k is None or len(audio_16k) < 1600:
            return ""
        audio = np.asarray(audio_16k, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        if peak < 1e-4:
            return ""
        if peak < 0.1:
            audio = audio * (0.5 / peak)
        t0 = time.time()
        with self._lock:
            self.busy = True
            try:
                try:
                    text = self._run(audio)
                except RuntimeError as exc:
                    if _is_cuda_error(exc) and self._fallback_to_cpu(exc):
                        text = self._run(audio)
                    else:
                        raise
            finally:
                self.busy = False
        self.last_ms = int((time.time() - t0) * 1000)
        self.count += 1
        return _clean(text)

    def _run(self, audio: np.ndarray) -> str:
        segments, info = self.model.transcribe(
            audio, language=self.language, beam_size=1, best_of=1, temperature=0.0,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 600, "speech_pad_ms": 300},
            initial_prompt=self.initial_prompt, condition_on_previous_text=False, without_timestamps=True,
            compression_ratio_threshold=2.2, no_speech_threshold=0.6,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        self.last_detected = getattr(info, "language", None) or self.language
        return squash_repetitions(text)

    def state(self) -> dict:
        return {"engine": self.name, "ready": True, "device": f"{self.device}/{self.compute_type}", "busy": self.busy,
                "last_ms": self.last_ms, "language": self.language or "auto", "mode": self.mode,
                "default_language": self.default_language, "detected": self.last_detected}


# ==================================================================================================
# Option C — Groq whisper-large-v3-turbo (whole utterances over HTTPS)
# ==================================================================================================
class GroqWhisperEngine:
    name = "groq_whisper"
    streaming = False
    URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(self, api_key: str, language: str | None = None, vocabulary: list[str] | None = None,
                 model: str = "whisper-large-v3-turbo"):
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set (stt.groq_api_key in config.json)")
        import requests  # noqa: F401  (dependency check)

        self.api_key = api_key
        self.language = language or None
        self.model = model
        self.vocabulary = list(vocabulary or [])[:40]
        self.mode, self.default_language = "auto", "en"
        self.prompt = whisper_prompt(self.language or "en", self.vocabulary)[:800]
        self.busy = False
        self.count = 0
        self.last_ms = 0
        self.last_error: str | None = None
        self.device = "groq"
        self.compute_type = model

    def set_language(self, lang: str | None, default: str | None = None, source: str = "user") -> bool:
        if default in ("en", "es"):
            self.default_language = default
        if lang in ("en", "es", "auto"):
            self.mode = lang
        target = self.mode if self.mode in ("en", "es") else self.default_language
        changed = target != self.language
        self.language = target
        self.prompt = whisper_prompt(target, self.vocabulary)[:800]
        return changed

    def flip_auto(self, lang: str, source: str = "auto") -> bool:
        if self.mode != "auto" or lang not in ("en", "es") or lang == self.language:
            return False
        self.language = lang
        self.prompt = whisper_prompt(lang, self.vocabulary)[:800]
        return True

    def transcribe(self, audio_16k: np.ndarray) -> str:
        import requests

        if audio_16k is None or len(audio_16k) < 1600:
            return ""
        t0 = time.time()
        self.busy = True
        try:
            data = {"model": self.model, "response_format": "json", "temperature": "0", "prompt": self.prompt}
            if self.language:
                data["language"] = self.language
            r = requests.post(self.URL, headers={"Authorization": f"Bearer {self.api_key}"}, data=data,
                              files={"file": ("utterance.wav", wav_bytes(audio_16k), "audio/wav")}, timeout=30)
            if r.status_code != 200:
                raise RuntimeError(f"Groq {r.status_code}: {r.text[:200]}")
            text = squash_repetitions((r.json().get("text") or "").strip())
            self.last_error = None
        finally:
            self.busy = False
            self.last_ms = int((time.time() - t0) * 1000)
        self.count += 1
        return _clean(text)

    def state(self) -> dict:
        return {"engine": self.name, "ready": True, "device": self.model, "busy": self.busy, "last_ms": self.last_ms,
                "error": self.last_error, "language": self.language, "mode": self.mode, "default_language": self.default_language}


# ==================================================================================================
# Option A — Deepgram Nova-3 live streaming: DUAL PRE-WARMED SOCKETS per channel (es-419 + en-US)
# ==================================================================================================
class DeepgramStreamingEngine:
    """v19: `language=multi` is gone (English acoustic bias on technical jargon + keyterm conflicts ruined
    Spanish). Instead every channel (them / me) keeps TWO native sockets open and warm:
        es-419  model=nova-3&language=es-419 (fallback es)   no keyterms (they conflict with Spanish)
        en-US   model=nova-3&language=en-US                  + profile keyterms
    both with smart_format=true&punctuate=true&interim_results=true&endpointing=750&utterance_end_ms=1100.
    PCM is routed to the ACTIVE language socket only; the inactive one receives {"type":"KeepAlive"} every 5 s
    (zero audio credits, never closes). Switching EN/ES moves the routing pointer: 0 ms, no handshake. The
    socket that just lost the audio gets a Finalize so its last words are not lost.
    AUTO mode routes to the profile's default language; the server flips the pointer when the finished text
    reads as the other language, and the engine flips itself when two consecutive finals come back with
    confidence < 0.65 (wrong decoder for what is being said)."""

    name = "deepgram"
    streaming = True
    BASE = os.environ.get("DEEPGRAM_WS_URL", "wss://api.deepgram.com/v1/listen")  # override for tests / proxies
    LANG_PARAMS = {"es": ["es-419", "es"], "en": ["en-US", "en"]}   # first that connects wins (400 -> next)
    KEEPALIVE_S = 5.0
    LOW_CONF = 0.65

    def __init__(self, api_key: str, language: str | None, vocabulary: list[str], on_interim: InterimCb,
                 on_piece: PieceCb, on_state: StateCb, model: str = "nova-3", endpointing_ms: int = 750,
                 utterance_end_ms: int = 1100, channels=("them", "me"), default_language: str = "en"):
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY not set (stt.deepgram_api_key in config.json)")
        import websockets  # noqa: F401

        self.api_key = api_key
        self.vocabulary = list(vocabulary or [])
        self.model = model
        self.endpointing_ms = int(endpointing_ms)
        self.utterance_end_ms = int(utterance_end_ms)
        self.on_interim, self.on_piece, self.on_state = on_interim, on_piece, on_state
        self.channels = tuple(channels)
        self.default_language = default_language if default_language in ("en", "es") else "en"
        self.mode = language if language in ("en", "es", "auto") else "auto"      # the HUD toggle
        self.active_lang = self.mode if self.mode in ("en", "es") else self.default_language
        self.language = self.mode                                                 # reported to the server
        self.auto_flips = 0
        self.dropped = 0
        self._last_flip_t = 0.0
        self.busy = False
        self.count = 0
        self.last_ms = 0
        self.device = f"deepgram/{model}/es-419+en-US"
        self.compute_type = self.active_lang
        self.last_detected: dict[str, str | None] = {ch: None for ch in self.channels}
        self.last_confidence: dict[str, float | None] = {ch: None for ch in self.channels}
        self._low_conf_runs: dict[str, int] = {ch: 0 for ch in self.channels}
        self._keyterms_ok = True
        self._queues: dict[tuple[str, str], asyncio.Queue] = {}
        self._conn: dict[str, dict] = {f"{ch}:{lg}": {"connected": False, "error": None, "reconnects": 0, "param": None}
                                       for ch in self.channels for lg in ("es", "en")}
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._run_loop, name="deepgram", daemon=True)
        self._thread.start()
        for _ in range(50):   # wait briefly for the active-language sockets so the UI shows a truthful state
            if all(self._conn[f"{ch}:{self.active_lang}"]["connected"] for ch in self.channels) or \
               any(c["error"] for c in self._conn.values()):
                break
            time.sleep(0.1)

    # -- public API --------------------------------------------------------------------------
    def feed(self, channel: str, audio_16k: np.ndarray) -> None:
        """Audio thread: 16 kHz float32 mono -> int16 PCM on the ACTIVE language socket of this channel."""
        loop, q = self._loop, self._queues.get((channel, self.active_lang))
        if loop is None or q is None or self._stop.is_set():
            return
        if not self._conn[f"{channel}:{self.active_lang}"]["connected"]:
            self.dropped += 1          # socket down: drop instead of queueing a backlog that would replay stale speech
            return
        loop.call_soon_threadsafe(q.put_nowait, pcm16(audio_16k))

    def set_language(self, lang: str | None, default: str | None = None, source: str = "user") -> bool:
        """EN / ES: route audio to that socket now (0 ms). AUTO: route to the profile default. Returns True
        when the routing pointer actually moved."""
        if default in ("en", "es"):
            self.default_language = default
        if lang in ("en", "es", "auto"):
            self.mode = lang
            self.language = lang
        target = self.mode if self.mode in ("en", "es") else self.default_language
        return self._route_to(target, source)

    def flip_auto(self, lang: str, source: str = "auto") -> bool:
        """AUTO mode only: the server (text looked like the other language) or the engine (low confidence)
        moves the pointer; a user-forced EN/ES is never overridden."""
        if self.mode != "auto" or lang not in ("en", "es"):
            return False
        return self._route_to(lang, source)

    def _route_to(self, lang: str, source: str) -> bool:
        if lang == self.active_lang:
            return False
        prev, self.active_lang = self.active_lang, lang
        self._last_flip_t = time.time()
        self.compute_type = lang
        if source != "user":
            self.auto_flips += 1
        for ch in self.channels:               # flush what the old decoder still holds, then clear previews
            self._send_ctrl((ch, prev), {"type": "Finalize"})
            self._low_conf_runs[ch] = 0
            try:
                self.on_interim(ch, "")
            except Exception:
                pass
        log.info("deepgram routing %s -> %s (%s)", prev, lang, source)
        self._emit_state()
        return True

    def _send_ctrl(self, key: tuple[str, str], msg: dict) -> None:
        loop, q = self._loop, self._queues.get(key)
        if loop and q:
            loop.call_soon_threadsafe(q.put_nowait, json.dumps(msg))

    def finalize(self, channel: str) -> None:
        """Ask the active socket to flush what it has (Answer Now while the speaker is mid-sentence)."""
        self._send_ctrl((channel, self.active_lang), {"type": "Finalize"})

    def close(self) -> None:
        self._stop.set()
        loop = self._loop
        if loop:
            for q in self._queues.values():
                loop.call_soon_threadsafe(q.put_nowait, None)
        self._thread.join(timeout=3)

    def state(self) -> dict:
        active_ok = all(self._conn[f"{ch}:{self.active_lang}"]["connected"] for ch in self.channels)
        return {"engine": self.name, "ready": active_ok, "dropped_chunks": self.dropped,
                "device": self.device, "language": self.active_lang, "mode": self.mode, "default_language": self.default_language,
                "answer_language": self.language, "detected": dict(self.last_detected), "confidence": dict(self.last_confidence),
                "auto_flips": self.auto_flips, "keyterms": len(self.vocabulary) if self._keyterms_ok else 0,
                "keyterms_rejected": not self._keyterms_ok, "busy": False, "last_ms": self.last_ms,
                "sockets": {k: dict(v) for k, v in self._conn.items()},
                "connections": {ch: dict(self._conn[f"{ch}:{self.active_lang}"]) for ch in self.channels},
                "error": next((c["error"] for c in self._conn.values() if c["error"]), None)}

    def url(self, lang: str, param: str, with_keyterms: bool | None = None) -> str:
        params = [("model", self.model), ("language", param), ("encoding", "linear16"), ("sample_rate", "16000"),
                  ("channels", "1"), ("smart_format", "true"), ("punctuate", "true"), ("interim_results", "true"),
                  ("endpointing", str(self.endpointing_ms)), ("utterance_end_ms", str(self.utterance_end_ms)),
                  ("no_delay", "true"), ("filler_words", "false")]
        use_kt = self._keyterms_ok if with_keyterms is None else with_keyterms
        if lang == "en" and use_kt and self.vocabulary:          # keyterms only on the English decoder
            params += [("keyterm", t) for t in self.vocabulary[:60]]
        return self.BASE + "?" + urllib.parse.urlencode(params)

    # -- internals ---------------------------------------------------------------------------
    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        for ch in self.channels:
            for lg in ("es", "en"):
                self._queues[(ch, lg)] = asyncio.Queue()
        try:
            self._loop.run_until_complete(asyncio.gather(*(self._socket_task(ch, lg) for ch in self.channels for lg in ("es", "en"))))
        finally:
            self._loop.close()

    async def _socket_task(self, channel: str, lang: str) -> None:
        import websockets

        key = f"{channel}:{lang}"
        backoff = 1.0
        while not self._stop.is_set():
            try:
                headers = {"Authorization": f"Token {self.api_key}"}

                async def connect(url):
                    try:
                        return await websockets.connect(url, additional_headers=headers, max_size=None, ping_interval=None)
                    except TypeError:  # websockets < 13
                        return await websockets.connect(url, extra_headers=headers, max_size=None, ping_interval=None)

                ws, used_param = None, None
                last_exc: Exception | None = None
                for param in self.LANG_PARAMS[lang]:                  # es-419 -> es, en-US -> en
                    used_kt = lang == "en" and self._keyterms_ok and bool(self.vocabulary)
                    try:
                        ws = await connect(self.url(lang, param, with_keyterms=used_kt))
                        used_param = param
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        if used_kt and "400" in str(exc):
                            log.warning("deepgram [%s] 400 with keyterms - reconnecting without keyterm", key)
                            self._keyterms_ok = False
                            try:
                                ws = await connect(self.url(lang, param, with_keyterms=False))
                                used_param = param
                                break
                            except Exception as exc2:  # noqa: BLE001
                                last_exc = exc2
                        if "400" not in str(exc) and "404" not in str(exc):
                            break                                     # auth / network: no point trying the fallback tag
                if ws is None:
                    raise last_exc or RuntimeError("connect failed")
                self._conn[key].update(connected=True, error=None, param=used_param)
                self._emit_state()
                log.info("deepgram [%s] connected (%s%s)%s", key, used_param,
                         f", {len(self.vocabulary)} keyterms" if lang == "en" and self._keyterms_ok and self.vocabulary else "",
                         "" if lang == self.active_lang else " [warm standby]")
                backoff = 1.0
                await self._pump(channel, lang, ws)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).splitlines()[0][:200]
                if "401" in msg or "403" in msg:
                    msg = "Deepgram rejected the API key (401/403) — check stt.deepgram_api_key"
                self._conn[key].update(connected=False, error=msg)
                self._conn[key]["reconnects"] += 1
                self._emit_state()
                log.warning("deepgram [%s] %s — retrying in %.0fs", key, msg, backoff)
                deadline = time.time() + backoff
                while time.time() < deadline and not self._stop.is_set():
                    await asyncio.sleep(0.1)
                if self._stop.is_set():
                    break
                backoff = min(backoff * 2, 15.0)
            else:
                self._conn[key]["connected"] = False
                self._emit_state()
                if self._stop.is_set():
                    break

    async def _pump(self, channel: str, lang: str, ws) -> None:
        q = self._queues[(channel, lang)]
        turn = {"open": False}

        async def sender():
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=self.KEEPALIVE_S)
                except asyncio.TimeoutError:
                    await ws.send(json.dumps({"type": "KeepAlive"}))   # standby socket: stays open, bills nothing
                    continue
                if item is None:
                    await ws.send(json.dumps({"type": "CloseStream"}))
                    return
                await ws.send(item)

        def piece(text: str, final: bool) -> None:
            if text:
                self.count += 1
            if text or (final and turn["open"]):
                self.on_piece(channel, text, final)
            turn["open"] = not final and (turn["open"] or bool(text))
            self.on_interim(channel, "")

        async def receiver():
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "Results":
                    if lang != self.active_lang and not msg.get("is_final"):
                        continue                                   # stray interim from the socket we just left
                    chan = msg.get("channel") or {}
                    alt = (chan.get("alternatives") or [{}])[0]
                    text = (alt.get("transcript") or "").strip()
                    if text:
                        self.last_detected[channel] = lang
                    if msg.get("is_final"):
                        conf = alt.get("confidence")
                        if text and isinstance(conf, (int, float)):
                            self.last_confidence[channel] = round(float(conf), 3)
                            self._watch_confidence(channel, lang, float(conf), text)
                        piece(text, bool(msg.get("speech_final")))
                    elif text:
                        self.on_interim(channel, text)
                elif mtype == "UtteranceEnd":
                    if lang == self.active_lang or turn["open"]:
                        piece("", True)
                elif mtype == "Error":
                    raise RuntimeError(f"Deepgram error: {msg.get('description') or msg}")

        send_task = asyncio.ensure_future(sender())
        try:
            await receiver()
        finally:
            send_task.cancel()
            try:
                await ws.close()
            except Exception:
                pass

    def _watch_confidence(self, channel: str, lang: str, conf: float, text: str) -> None:
        """AUTO mode: two consecutive low-confidence finals on the active decoder (>= 3 words) = probably the
        other language is being spoken -> flip the routing pointer."""
        if channel != "them" or self.mode != "auto" or lang != self.active_lang or len(text.split()) < 3:
            return   # only the remote speaker's audio decides the decoder; the mic never re-routes it
        if time.time() - self._last_flip_t < 20:
            return   # cooldown: no ping-pong between decoders on jargon-heavy speech
        if conf < self.LOW_CONF:
            self._low_conf_runs[channel] += 1
            if self._low_conf_runs[channel] >= 2:
                other = "en" if lang == "es" else "es"
                log.info("deepgram [%s] confidence %.2f < %.2f twice on %s - auto-flipping to %s", channel, conf,
                         self.LOW_CONF, lang, other)
                self.flip_auto(other, source="low confidence")
        else:
            self._low_conf_runs[channel] = 0

    def _emit_state(self) -> None:
        try:
            self.on_state(self.state())
        except Exception:
            pass


# ==================================================================================================
def build_engine(cfg_stt: dict, language: str | None, vocabulary: list[str], on_interim: InterimCb,
                 on_piece: PieceCb, on_state: StateCb, default_language: str = "en"):
    """Factory used by server.py; raises with a clear message when the chosen engine cannot start.
    `language` is the HUD toggle (en|es|auto); `default_language` is the profile default used by AUTO."""
    engine = (cfg_stt.get("engine") or "whisper_local").lower()
    if engine == "deepgram":
        key = cfg_stt.get("deepgram_api_key") or os.environ.get("DEEPGRAM_API_KEY", "")
        return DeepgramStreamingEngine(key, language, vocabulary, on_interim, on_piece, on_state,
                                       model=cfg_stt.get("deepgram_model", "nova-3"),
                                       endpointing_ms=cfg_stt.get("deepgram_endpointing_ms", 750),
                                       utterance_end_ms=cfg_stt.get("deepgram_utterance_end_ms", 1100),
                                       default_language=default_language)
    forced = cfg_stt.get("force_language") if cfg_stt.get("force_language") in ("en", "es") else None
    if engine == "groq_whisper":
        key = cfg_stt.get("groq_api_key") or os.environ.get("GROQ_API_KEY", "")
        eng = GroqWhisperEngine(key, forced, vocabulary, model=cfg_stt.get("groq_model", "whisper-large-v3-turbo"))
    else:
        eng = WhisperLocalEngine(cfg_stt.get("model_size", "small"), cfg_stt.get("device", "auto"),
                                 cfg_stt.get("compute_type", "default"), forced, vocabulary,
                                 cfg_stt.get("whisper_prompt", ""))
    if forced:
        eng.set_language(forced, default_language)
    else:
        eng.set_language(language, default_language)
    return eng


# Backwards compatibility for older imports.
Transcriber = WhisperLocalEngine
