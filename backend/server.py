"""Meeting Copilot backend: audio -> STT engine (Deepgram Nova-3 streaming | local faster-whisper | Groq
whisper-large-v3-turbo, see transcriber.py) -> LLM, served over a local WebSocket.

Run:  python server.py [--config ../config.json] [--list-devices] [--no-audio]

Events sent to the HUD (JSON text frames):
  status        {listening, stt_ready, stt_engine, stt_streaming, stt:{...}, providers, context, audio, settings}
  levels        {them: 0..1, me: 0..1, diag}       ~10x per second
  audio_devices {mic:[{id,name}], loopback:[{id,name}], platform}
  interim       {channel, text}                    live preview while the speaker is still talking (streaming STT)
  stt_language  {active, decoder, mode, source}    v19: which native decoder (es/en) the audio is routed to
  transcript    {channel: "them"|"me", text, t, partial}
  llm_start {turn_id, replace, card_gen_id, continuity} / llm_reset / llm_token / llm_end {turn_id} / error / log
  turn          {turn_id, state: collecting|holding|generating|answered|closed, segments, words, text}   (v16)
  answer_hold   {turn_id, reason: context_setup|speaker_continuing, hold_ms, gen_id}   card shows "updating…" (v16)
  story         {entities, ledger}                 example the last answer was anchored on (anti-repetition ledger)

Commands from the HUD (JSON text frames):
  generate | summarize | cancel | toggle_listening | set_listening {value} | reload_context
  inject {channel, text} | status | ping | set_config {general, llm, style, stt} | restart_stt | toggle_language (EN->ES->AUTO)
  cycle_tone | cycle_length | list_gemini_models | list_audio_devices | set_audio_devices {mic, loopback}
  list_profiles | set_profile {name} | set_profile_config {claude_project, use_learned_memory}
  set_playbook {text} | followup {kind: example|deepen|tldr|pivot} | vision {image_b64, mime}
  vision_buffer {image_b64, mime} | vision_buffer {clear:true} | set_auto_vision {value}   (v15 passive screen frame)
  new_turn                                                                                  (v16: close the remote turn buffer)
  set_input_mode {value: pc|external} | toggle_input_mode                                  (v17: phone-on-speaker via laptop mic)
  end_session (End & Analyze -> report streamed as mode "debrief", memory appended to learned_memory.md)

Audio from the HUD (binary frames, when a channel is set to "electron"):
  byte 0      channel: 0 = them (system audio), 1 = me (mic)
  bytes 1..4  sample rate, uint32 little-endian
  bytes 5..   int16 little-endian mono PCM
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import hashlib
import json
import logging
import os
import queue
import struct
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audio_capture import (LoopbackCapture, MicCapture, UtteranceSegmenter, list_devices,  # noqa: E402
                           list_devices_struct, parse_device, resample_to_16k)
from classifier import needs_answer, skip_reason, trigger_class, turn_readiness  # noqa: E402
from config import load_config, profiles_dir, save_config  # noqa: E402
from context_loader import ContextStore, ProfileStore, sanitize_name  # noqa: E402
from session_logger import SessionLogger  # noqa: E402
from llm_claude import ClaudeCLI  # noqa: E402
from llm_gemini import GeminiClient
from llm_openai import COMPAT_NAMES, PRESETS as COMPAT_PRESETS, OpenAICompatClient  # noqa: E402
from prompts import (DEBRIEF_SYSTEM, MEMORY_EXTRACT_SYSTEM, SUMMARY_SYSTEM_PROMPT, VISION_SYSTEM,  # noqa: E402
                     build_debrief_prompt, build_followup_prompt, build_generation_prompt,
                     build_memory_extract_prompt, build_opener_prompt, build_summary_prompt,
                     build_system_prompt, build_vision_prompt, language_rule)
from prompts import OPENER_SYSTEM, analysis_to_markdown, focus_block, parse_analysis  # noqa: E402
from prompts import FOLLOWUP_KINDS, is_probing_followup, story_signature, wants_story  # noqa: E402
from prompts import refers_to_screen, screen_frame_note, detect_language, language_evidence  # noqa: E402
from config import ROOT_DIR  # noqa: E402
from retrieval import tokenize  # noqa: E402
from transcriber import looks_complete, build_engine, mine_vocabulary, ENGINES  # noqa: E402
import base64  # noqa: E402
import re  # noqa: E402

log = logging.getLogger("server")

TONES = ["natural", "executive", "technical"]
LENGTHS = ["concise", "medium", "detailed"]


class Copilot:
    def __init__(self, cfg: dict, loop: asyncio.AbstractEventLoop, audio_enabled: bool):
        self.cfg = cfg
        self.loop = loop
        self.audio_enabled = audio_enabled and bool(cfg["audio"]["enabled"])
        self.clients: set = set()
        self.transcript: deque[dict] = deque(maxlen=400)
        self.segments: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.listening = True   # audio flows (meters work in the Setup dashboard)
        self.armed = False      # transcription + answers only while a live session is running
        self.auto_answer = bool(cfg["llm"]["auto_answer"])
        self.profiles = ProfileStore(profiles_dir(cfg), profiles_dir(cfg).parent / "profiles_archived")
        self.bank_dir = Path(os.environ.get("COPILOT_BANK_DIR") or (ROOT_DIR / "data" / "bank"))
        for sub in ("roles", "cvs", "experience", "playbooks"):
            (self.bank_dir / sub).mkdir(parents=True, exist_ok=True)
        self.profile_name = sanitize_name(cfg["general"].get("active_profile") or "default")
        self.profile_dir = self.profiles.ensure(self.profile_name)
        cfg["general"]["active_profile"] = self.profile_name
        self.context = ContextStore(self.profile_dir, cfg["context"]["max_chars"],
                                    cfg["context"].get("chunk_words", 300), cfg["context"].get("top_chunks", 3))
        cfg["style"] = {k: self.profiles.playbook(self.profile_name)[k] for k in ("tone", "length")}
        self.session = SessionLogger(self.profile_dir, self.profile_name)
        self.last_answer: dict = {"question": None, "text": "", "mode": None}
        self.story_ledger: list[dict] = []   # examples already used this call (anti-repetition), see prompts.ledger_block
        # v15 passive auto-vision: the HUD pushes one compressed screen frame every ~5 s (rolling 1-frame buffer).
        self.auto_vision: bool = bool(cfg["llm"].get("auto_vision", False))
        self.vision_buffer: dict | None = None   # {"data": bytes, "mime": str, "t": float, "bytes": int}
        self.vision_buffer_max_age_s = float(cfg["llm"].get("auto_vision_max_age_s", 20))
        self._debrief_running = False
        llm = cfg["llm"]
        self.claude = ClaudeCLI(llm["claude_cli"], llm["claude_model"], llm["claude_timeout_s"])
        self.gemini = GeminiClient(llm["gemini_api_key_env"], llm["gemini_model"], llm.get("gemini_api_key", ""))
        self.claude_fast = ClaudeCLI(llm["claude_cli"], llm.get("fast_claude_model", "claude-haiku-5-5"), llm["claude_timeout_s"])
        self.gemini_fast = GeminiClient(llm["gemini_api_key_env"], llm.get("fast_gemini_model", "gemini-2.5-flash"), llm.get("gemini_api_key", ""))
        # ChatGPT (OpenAI) / Grok (xAI) / DeepSeek: OpenAI-compatible streaming clients
        self.compat = {n: OpenAICompatClient(n, (llm.get("providers") or {}).get(n) or {}) for n in COMPAT_NAMES}
        self.provider_errors: dict[str, dict] = {}   # name -> {message, t, sticky}: last failure, shown in the HUD
        self.use_gemini_classifier = False  # zero-latency local heuristics only (classifier.py)
        self._pending: dict[str, dict] = {}  # channel -> {"line": transcript line being assembled from rolling chunks}
        self._spec: dict | None = None       # in-flight speculative draft (see _maybe_speculate)
        # v16 same-speaker turn accumulation: consecutive remote segments are ONE turn (one answer card) until
        # the user answers through the mic, 25 s of remote silence pass, or "New turn" is pressed.
        self.turn: dict | None = None        # current_remote_turn_buffer, see _remote_segment_done
        self._turn_ids = itertools.count(1)
        self._turn_lock = threading.RLock()
        self._hold_timer: threading.Timer | None = None
        self._me_words_since_remote = 0
        self.session_focus: str = ""         # optional per-call hint (set before start or mid-call)
        self._apply_profile_config()
        # v19: the profile's default_language is the language the interviewer usually SPEAKS -> it picks the native
        # decoder AUTO routes to (stt_default_language). The answer-language mode (general.language: en|es|auto)
        # is the HUD toggle and is no longer overwritten by the profile.
        cfg["stt"]["language"] = None
        self.last_answer_lang: str | None = None      # effective language of the last answer (AUTO shows it in the HUD)
        self._last_gen: dict | None = None            # {mode, trigger_text, turn_id, card_gen_id, t, lang} for Alt+L rescue
        self._last_question_t = 0.0
        self._gen_running: set[int] = set()           # gen_ids currently streaming
        self._replace_card_gen: int | None = None     # card to overwrite on the next non-turn generation (language flip)

        self.transcriber = None              # active STT engine (see transcriber.build_engine)
        self.stt_error: str | None = None
        self._stt_gen = 0                     # bumped on every engine (re)start so stale callbacks are ignored
        self._stt_lock = threading.Lock()
        self.interim = {"them": "", "me": ""}  # live preview text from streaming engines
        self.captures: list = []
        self.segmenters: dict[str, UtteranceSegmenter] = {}
        self.levels = {"them": 0.0, "me": 0.0}
        self.diag = {"chunks": {"them": 0, "me": 0}, "segments": 0, "transcribed": 0, "dropped_not_armed": 0,
                     "dropped_no_stt": 0, "last_error": None, "stt_state": "loading"}
        self.external = {"them": False, "me": False}   # channel fed by the HUD (Electron) instead of Python
        # v17 audio input mode: "pc" (loopback = remote voice, mic = my own context) or "external" (phone on
        # speaker / room audio: the laptop MIC is the remote voice and triggers answers; loopback is ignored)
        self._last_frame: dict[str, float] = {}      # last audio frame per capture channel (any level)
        self._last_sound: dict[str, float] = {}      # last frame that was not silence
        self._armed_at = 0.0
        self._no_audio_hint = 0.0
        self._no_audio_count = 0
        self._interim_flip_at = 0.0
        self.input_mode = cfg["audio"].get("input_mode") if cfg["audio"].get("input_mode") in ("pc", "external") else "pc"
        self.last_external = {"them": 0.0, "me": 0.0}

        self._gen_lock = threading.Lock()
        self._gen_cancel: threading.Event | None = None
        self._gen_ids = itertools.count(1)
        self._audio_lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.context.load(force=True)
        threading.Thread(target=self._init_stt, name="stt-init", daemon=True).start()
        threading.Thread(target=self._transcribe_worker, name="stt-worker", daemon=True).start()
        threading.Thread(target=self._levels_worker, name="levels", daemon=True).start()
        self._build_segmenters()
        if self.audio_enabled:
            self._start_audio()
        else:
            log.info("Audio capture disabled (--no-audio or config). Use 'inject' to test.")
        log.info("Claude CLI: %s", self.claude.version() if self.claude.available() else "NOT FOUND")
        if self.claude.available():
            threading.Thread(target=self.claude.warm, daemon=True).start()
            if self.cfg["llm"].get("fast_provider") != "gemini":
                threading.Thread(target=self.claude_fast.warm, daemon=True).start()
        log.info("Gemini: %s", "configured" if self.gemini.available() else "not configured")

    # ------------------------------------------------------------------ STT engines
    def _stt_vocabulary(self) -> list[str]:
        """Built-in IAM vocabulary + terms mined from the active profile (role, CV, experience, playbook)."""
        texts = []
        try:
            secs = self.context.sections()
            for k in ("role", "profile", "experience", "playbook", "memory"):
                if secs.get(k):
                    texts.append(str(secs[k])[:60000])
        except Exception:
            pass
        pcfg = self.profiles.config(self.profile_name)
        texts.append(" ".join(str(pcfg.get(k) or "") for k in ("job_role", "company")))
        extra = [str(t) for t in (self.cfg["stt"].get("vocabulary") or []) if str(t).strip()]
        vocab = mine_vocabulary(texts + [" ".join(extra)], max_terms=int(self.cfg["stt"].get("max_keyterms", 60)))
        # user-configured terms always make the cut
        for t in extra:
            if t.lower() not in {v.lower() for v in vocab}:
                vocab.insert(0, t)
        return vocab[: int(self.cfg["stt"].get("max_keyterms", 60))]

    def _init_stt(self) -> None:
        stt = self.cfg["stt"]
        engine = (stt.get("engine") or "whisper_local").lower()
        if engine not in ENGINES:
            engine = stt["engine"] = "whisper_local"
        with self._stt_lock:
            self._stt_gen += 1
            gen = self._stt_gen
            old, self.transcriber, self.stt_error = self.transcriber, None, None
            self.diag["stt_state"] = "loading"
            self.diag["stt_engine"] = engine
        if old is not None and hasattr(old, "close"):
            try:
                old.close()
            except Exception:
                pass

        def watchdog():
            time.sleep(150)
            if gen == self._stt_gen and self.transcriber is None and not self.stt_error:
                self.diag["last_error"] = "STT still loading after 150 s (model download or a hung CUDA init?)"
                self.broadcast({"type": "error", "message": self.diag["last_error"]
                                + " - set stt.device to 'cpu' in config.json or switch to Deepgram if this persists."})

        if engine == "whisper_local":
            threading.Thread(target=watchdog, daemon=True).start()
        try:
            vocab = self._stt_vocabulary()
            cbs = dict(on_interim=lambda ch, t, g=gen: self._on_interim(g, ch, t),
                       on_piece=lambda ch, t, f, g=gen: self._on_piece(g, ch, t, f),
                       on_state=lambda st_, g=gen: self._on_stt_state(g, st_))
            try:
                eng = build_engine(stt, self.cfg["general"].get("language", "auto"), vocab,
                                   default_language=self.stt_default_language(), **cbs)
                self.diag.pop("stt_fallback", None)
            except Exception as exc:
                if engine == "whisper_local":
                    raise
                # cloud engine unavailable (no key / no network): keep transcribing locally rather than going mute
                msg = f"STT engine '{engine}' unavailable ({str(exc).splitlines()[0][:160]}) - using local Whisper for now"
                log.warning(msg)
                self.diag["stt_fallback"] = msg
                self.broadcast({"type": "error", "message": msg})
                threading.Thread(target=watchdog, daemon=True).start()
                eng = build_engine({**stt, "engine": "whisper_local"}, self.cfg["general"].get("language", "auto"), vocab,
                                   default_language=self.stt_default_language(), **cbs)
            with self._stt_lock:           # check + assign atomically: a restart cannot slip in between
                current = gen == self._stt_gen
                if current:
                    self.transcriber = eng
            if not current:  # superseded while loading
                if hasattr(eng, "close"):
                    eng.close()
                return
            self.diag["stt_state"] = "ready"
            self.diag["stt_engine"] = eng.name
            self.diag["keyterms"] = len(vocab)
            self.session.event(f"stt engine: {eng.name} ({getattr(eng, 'device', '?')}) keyterms={len(vocab)}")
            log.info("STT engine ready: %s (%s), %d keyterms", eng.name, getattr(eng, "device", "?"), len(vocab))
            err = (eng.state() or {}).get("error") if hasattr(eng, "state") else None
            if err:
                self.broadcast({"type": "error", "message": f"STT ({eng.name}): {err}"})
        except Exception as exc:
            if gen != self._stt_gen:
                return
            self.stt_error = f"{type(exc).__name__}: {exc}"
            self.diag["stt_state"] = "error"
            self.diag["last_error"] = self.stt_error
            log.exception("Failed to start STT engine %s", engine)
            self.broadcast({"type": "error", "message": f"STT engine '{engine}' failed to start: {exc}"})
        finally:
            # the UI must never be left on the "starting" status that was sent while the engine was being built
            self.broadcast_status()
            threading.Timer(2.0, self.broadcast_status).start()

    def stt_default_language(self) -> str:
        """Which native decoder AUTO routes to before any question is heard: the profile's default language,
        then stt.default_language, then the UI language, then English."""
        pcfg = self.profiles.config(self.profile_name)
        for cand in (pcfg.get("default_language"), self.cfg["stt"].get("default_language"),
                     self.cfg["general"].get("ui_language")):
            if cand in ("en", "es"):
                return cand
        return "en"

    def restart_stt(self, reason: str = "") -> None:
        """Switch engine / key / model / language at runtime (called from apply_settings)."""
        log.info("restarting STT engine (%s)", reason or "settings changed")
        for ch in ("them", "me"):
            self._set_interim(ch, "")
        for seg in self.segmenters.values():
            seg.reset()
        threading.Thread(target=self._init_stt, name="stt-init", daemon=True).start()

    @property
    def stt_streaming(self) -> bool:
        return bool(self.transcriber is not None and getattr(self.transcriber, "streaming", False))

    def stt_state(self) -> dict:
        t = self.transcriber
        if t is None:
            return {"engine": self.cfg["stt"].get("engine"), "ready": False, "error": self.stt_error,
                    "state": self.diag.get("stt_state")}
        try:
            st = dict(t.state())
        except Exception:
            st = {"engine": t.name, "ready": True}
        st["state"] = self.diag.get("stt_state")
        return st

    # -- callbacks from the engine (any thread) ------------------------------------------------
    def _set_interim(self, channel: str, text: str) -> None:
        text = (text or "").strip()
        if self.interim.get(channel) == text:
            return
        self.interim[channel] = text
        self.broadcast({"type": "interim", "channel": channel, "text": text})

    def _on_interim(self, gen: int, channel: str, text: str) -> None:
        if gen != self._stt_gen or not self.armed:
            return
        if channel == "me" and text and self._is_echo(text):
            return
        self._set_interim(channel, text)
        if channel == "them" and text:
            # Deepgram interim words = the speaker is still talking: abort/hold the answer for the open turn
            self._on_remote_activity(text)
            self._auto_flip_on_interim(text)
        elif channel == "me" and text and not self._is_echo(text):
            self._me_talking(text)

    def _on_piece(self, gen: int, channel: str, text: str, final: bool) -> None:
        if gen != self._stt_gen:
            return
        self._set_interim(channel, "")
        if not self.armed:
            self.diag["dropped_not_armed"] += 1
            return
        self.diag["transcribed"] += 1
        text = (text or "").strip()
        if text:
            self._append_piece(channel, text, final)
        elif final:
            self._finish_turn(channel)

    def _on_stt_state(self, gen: int, state: dict) -> None:
        if gen != self._stt_gen:
            return
        lang = state.get("language")
        if lang in ("en", "es") and lang != self.diag.get("stt_decoder"):
            prev = self.diag.get("stt_decoder")
            self.diag["stt_decoder"] = lang
            if prev is not None:   # the engine moved the pointer itself (low confidence) -> tell the HUD
                self.broadcast({"type": "stt_language", "active": lang, "decoder": lang, "mode": state.get("mode"),
                                "source": "low confidence" if state.get("auto_flips") else "engine"})
        err = state.get("error")
        if err and f"STT: {err}" != self.diag.get("last_error"):
            self.diag["last_error"] = f"STT: {err}"
            self.broadcast({"type": "error", "message": f"STT ({state.get('engine')}): {err}"})
        self.diag["stt_state"] = "ready" if state.get("ready") else ("error" if err else "connecting")
        self.broadcast_status()

    def _build_segmenters(self) -> None:
        a = self.cfg["audio"]
        # v13: utterance engines (local Whisper / Groq) get WHOLE utterances. The segmenter only cuts on a real
        # pause (end_silence_ms, or end_silence_incomplete_ms when the sentence reads unfinished) or at the
        # safety ceiling max_utterance_s (default 30 s) - never into 1.5 s slices that chop words in half.
        kw = dict(aggressiveness=a["vad_aggressiveness"], end_silence_ms=a["end_silence_ms"],
                  min_speech_ms=a["min_speech_ms"], max_utterance_s=float(a.get("max_utterance_s", 30)),
                  energy_threshold=a.get("energy_threshold", 0.015),
                  end_silence_incomplete_ms=a.get("end_silence_incomplete_ms", 900))
        self.segmenters = {ch: UtteranceSegmenter(ch, self.on_utterance, completeness=lambda c=ch: self._turn_complete(c), **kw)
                           for ch in ("them", "me")}

    def _start_audio(self) -> None:
        with self._audio_lock:
            a = self.cfg["audio"]
            gate = lambda: self.listening  # noqa: E731
            self.captures = []
            lb_kind, _ = parse_device(a["loopback_device"])
            mic_kind, _ = parse_device(a["mic_device"])
            self.external["them"] = lb_kind == "electron"
            self.external["me"] = mic_kind == "electron"
            if lb_kind not in ("off", "electron"):
                self.captures.append(LoopbackCapture(a["loopback_device"], self._sink, gate))
            if mic_kind not in ("off", "electron"):
                self.captures.append(MicCapture(a["mic_device"], self._sink, gate))
            for c in self.captures:
                c.start()
        threading.Timer(1.5, self.broadcast_status).start()

    def _stop_audio(self) -> None:
        with self._audio_lock:
            for c in self.captures:
                c.stop()
            self.captures = []
        for seg in self.segmenters.values():
            seg.reset()

    def restart_audio(self) -> None:
        self._stop_audio()
        self._build_segmenters()
        if self.audio_enabled:
            self._start_audio()

    def stop(self) -> None:
        self._stop_audio()
        self.cancel_generation()
        if self.transcriber is not None and hasattr(self.transcriber, "close"):
            try:
                self.transcriber.close()
            except Exception:
                pass
        self.session.event("backend stopped")

    # ------------------------------------------------------------------ audio -> text
    def _sink(self, channel: str, mono: np.ndarray, sr: int) -> None:
        """All audio (Python captures and Electron frames) lands here."""
        if not self.listening or channel not in self.segmenters:
            return
        if self.input_mode == "external":
            if channel == "them":
                return                     # phone / room call: nothing useful on the PC loopback
            channel = "them"               # whatever the laptop mic hears IS the remote speaker
        x = resample_to_16k(mono, sr)
        if len(x) == 0:
            return
        rms = float(np.sqrt(np.mean(np.square(x))))
        now = time.time()
        self._last_frame[channel] = now
        if rms > 0.004:
            self._last_sound[channel] = now
        lvl = min(1.0, rms * 6.0)
        self.levels[channel] = max(lvl, self.levels[channel] * 0.8)
        self.diag["chunks"][channel] += 1
        if not self.armed:
            self.diag["dropped_not_armed"] += 1
            return
        t = self.transcriber
        if t is not None and getattr(t, "streaming", False):
            t.feed(channel, x)          # streaming engine (Deepgram): raw PCM, no local segmentation
        else:
            self.segmenters[channel].feed(x)

    def external_audio(self, frame: bytes) -> None:
        if len(frame) < 7:
            return
        ch = "them" if frame[0] == 0 else "me"
        sr = struct.unpack_from("<I", frame, 1)[0]
        pcm = np.frombuffer(frame, dtype="<i2", offset=5).astype(np.float32) / 32768.0
        self.last_external[ch] = time.time()
        self._sink(ch, pcm, sr if 8000 <= sr <= 192000 else 48000)

    def on_utterance(self, channel: str, audio, final: bool = True) -> None:
        if audio is not None:
            self.diag["segments"] += 1
        self.segments.put((channel, audio, final))

    def flush_pending_audio(self) -> bool:
        if self.stt_streaming:
            for ch in ("them", "me"):
                try:
                    self.transcriber.finalize(ch)
                except Exception:
                    pass
            return True
        return any(seg.force_flush() for seg in self.segmenters.values())

    def _transcribe_worker(self) -> None:
        while True:
            channel, audio, final = self.segments.get()
            try:
                if audio is None:  # end-of-turn marker with nothing left to transcribe
                    self._finish_turn(channel)
                    continue
                if self.transcriber is None:
                    self.diag["dropped_no_stt"] += 1
                    if self.diag["dropped_no_stt"] in (1, 10, 50):
                        self.broadcast({"type": "error", "message": "Speech detected but STT is not ready: "
                                        + (self.stt_error or "model still loading")})
                    continue
                self.diag["stt_state"] = "transcribing"
                try:
                    text = self.transcriber.transcribe(audio)
                except Exception as exc:
                    log.exception("transcription failed")
                    self.diag["last_error"] = f"STT: {exc}"
                    self.diag["stt_state"] = "error"
                    self.broadcast({"type": "error", "message": f"STT error: {exc}"})
                    continue
                self.diag["stt_state"] = "ready"
                self.diag["transcribed"] += 1
                if text:
                    self._append_piece(channel, text, final)
                else:
                    log.debug("[%s] %.1fs of audio -> no text", channel, len(audio) / 16000)
                    if final:
                        self._finish_turn(channel)
            finally:
                self.segments.task_done()

    def _levels_worker(self) -> None:
        hz = max(2, int(self.cfg["audio"].get("levels_hz", 10)))
        while True:
            time.sleep(1.0 / hz)
            if not self.clients:
                continue
            for ch in ("them", "me"):
                self.levels[ch] *= 0.75
            try:
                self._turn_watchdog()
            except Exception as exc:  # noqa: BLE001
                log.debug("watchdog: %s", exc)
            try:
                self._audio_watchdog()
            except Exception as exc:  # noqa: BLE001
                log.debug("audio watchdog: %s", exc)
            d = self.diag
            self.broadcast({"type": "levels", "them": round(self.levels["them"], 3), "me": round(self.levels["me"], 3),
                            "diag": {"chunks": dict(d["chunks"]), "segments": d["segments"], "transcribed": d["transcribed"],
                                     "queue": self.segments.qsize(), "stt_state": d["stt_state"],
                                     "stt_busy": bool(self.transcriber and getattr(self.transcriber, "busy", False)),
                                     "stt_ms": getattr(self.transcriber, "last_ms", 0) if self.transcriber else 0,
                                     "stt_engine": d.get("stt_engine"), "keyterms": d.get("keyterms"),
                                     "first_token_s": d.get("last_first_token_s"),
                                     "speculating": self._spec is not None,
                                     "claude_warm": self.claude.warm_count() if hasattr(self.claude, "warm_count") else None,
                                     "stt_device": getattr(self.transcriber, "device", None) if self.transcriber else None,
                                     "stt_connections": (self.stt_state().get("connections") if self.stt_streaming else None),
                                     "last_error": d["last_error"], "armed": self.armed, "listening": self.listening,
                                     "in_speech": {ch: seg.in_speech() for ch, seg in self.segmenters.items()}}})

    def _audio_watchdog(self) -> None:
        """Runs ten times a second while a client is connected.

        1. Silence tail. WASAPI loopback delivers no frames at all while nothing is playing, so a streaming
           engine never sees the pause that ends a sentence and holds its last words until the next sound.
           For 2 s after the last real frame the gap is filled with silence so the sentence is finalised.
        2. No call audio. If nothing has been heard on the remote channel since the session started, say so
           with the device name instead of sitting there with an empty transcript."""
        if not self.armed:
            self._armed_at = 0.0
            return
        now = time.time()
        if not self._armed_at:
            self._armed_at = now
            self._no_audio_hint = 0.0
            self._no_audio_count = 0
        t = self.transcriber
        if t is not None and getattr(t, "streaming", False):
            for ch in ("them", "me"):
                gap = now - self._last_frame.get(ch, 0.0)
                if 0.15 < gap < 2.0:
                    t.feed(ch, np.zeros(1600, dtype=np.float32))      # 100 ms of silence at 16 kHz
        heard = self._last_sound.get("them", 0.0) >= self._armed_at    # _sink has already mapped the call to "them"
        if not heard and now - self._armed_at > 20 and now - self._no_audio_hint > 45 and self._no_audio_count < 3:
            self._no_audio_hint = now
            self._no_audio_count += 1
            source = "me" if self.input_mode == "external" else "them"  # capture thread that carries the call
            dev = next((c.device_name for c in self.captures if c.channel == source), None) or "Electron"
            log.warning("no call audio on %s since the session started (%s)", source, dev)
            self.session.event(f"no call audio since start - device: {dev}")
            self.broadcast({"type": "hint", "code": "no_remote_audio", "device": dev, "input_mode": self.input_mode,
                            "message": f"No call audio is arriving from {dev}."})

    def _turn_complete(self, channel: str) -> bool:
        """Adaptive VAD hook: does the interim transcript of this turn read as a finished sentence?
        If chunks are still waiting for Whisper, the text is behind the audio -> treat as incomplete."""
        if not self.segments.empty() or (self.transcriber is not None and getattr(self.transcriber, "busy", False)):
            return False
        pend = self._pending.get(channel)
        if pend is None:
            return True
        return looks_complete(pend["line"]["text"])

    def _is_echo(self, text: str) -> bool:
        """Mic text that repeats what the remote side just said = the call playing through the speakers.
        Without this the echo shows up as YO, closes the remote turn and pollutes the transcript."""
        words = [w for w in re.findall(r"[\wáéíóúñü']+", (text or "").lower()) if len(w) > 1]
        if len(words) < 3:
            return False
        now = time.time()
        recent = [l["text"] for l in self.transcript[-6:] if l["channel"] == "them" and now - l.get("t_last", l["t"]) < 12]
        recent.append(self.interim.get("them") or "")
        pool = set(re.findall(r"[\wáéíóúñü']+", " ".join(recent).lower()))
        if not pool:
            return False
        return sum(1 for w in words if w in pool) / len(words) >= 0.7

    # -- rolling pieces of one speaker turn are merged into a single transcript line ------------
    def _append_piece(self, channel: str, text: str, final: bool) -> None:
        if channel == "me" and self.input_mode != "external" and self._is_echo(text):
            self.diag["echo_dropped"] = self.diag.get("echo_dropped", 0) + 1
            if self.diag["echo_dropped"] == 3:
                self.broadcast({"type": "hint", "code": "echo", "message": "The microphone is picking up the call from the speakers. Use headphones for cleaner turns."})
            if final and channel in self._pending:
                self._finish_turn(channel)
            return
        pend = self._pending.get(channel)
        if pend is not None and time.time() - pend["line"]["t_last"] > 2.5:
            # the previous piece never got its end-of-utterance: close it properly (log + turn buffer) instead of
            # silently dropping it, then start a new line
            self._finish_turn(channel)
            pend = None
        if pend is None:
            line = {"t": time.time(), "t_last": time.time(), "channel": channel, "text": text.strip(), "partial": True}
            self.transcript.append(line)
            pend = self._pending[channel] = {"line": line}
        else:
            line = pend["line"]
            line["text"] = (line["text"] + " " + text.strip()).strip()
            line["t_last"] = time.time()
        self.broadcast({"type": "transcript", "t": line["t"], "channel": channel, "text": line["text"],
                        "partial": not final})
        if channel == "them" and not final:
            self._on_remote_activity(text)
        elif channel == "me" and not final:
            self._me_talking(line["text"])
        if final:
            self._finish_turn(channel)
        elif channel == "them" and self.armed and self.auto_answer:
            self._maybe_speculate(self._turn_prefix() + line["text"])

    def _finish_turn(self, channel: str) -> None:
        pend = self._pending.pop(channel, None)
        if not pend:
            return
        line = pend["line"]
        line["partial"] = False
        line.pop("t_last", None)
        log.info("[%s] %s", channel.upper(), line["text"])
        self.session.transcript(channel, line["text"])
        self.broadcast({"type": "transcript", "t": line["t"], "channel": channel, "text": line["text"], "partial": False})
        # Active listening (v16): finished remote segments are accumulated into the current remote turn; the
        # turn decides when to answer (fast trigger on a question, 1.8 s hold on context setup) and answers
        # in place when the speaker keeps talking. The user's own microphone never triggers an answer - it
        # ends the turn instead. No LLM classification call anywhere.
        if channel == "them":
            self._remote_segment_done(line["text"])
        else:
            self._me_spoke(line["text"])

    def add_transcript(self, channel: str, text: str, auto: bool = True) -> None:
        line = {"t": time.time(), "channel": channel, "text": text.strip()}
        self.transcript.append(line)
        log.info("[%s] %s", channel.upper(), line["text"])
        self.session.transcript(channel, line["text"])
        self.broadcast({"type": "transcript", **line})
        if auto and channel == "them":
            self._remote_segment_done(line["text"])
        elif auto:
            self._me_spoke(line["text"])

    # ------------------------------------------------------------------ v16: same-speaker turn accumulation
    def _turn_cfg(self, key: str, default):
        return self.cfg["llm"].get(key, default)

    def _turn_text(self, t: dict | None = None) -> str:
        t = t if t is not None else self.turn
        return " ".join(seg for seg in (t["segments"] if t else []) if seg).strip()

    def _turn_prefix(self) -> str:
        """Accumulated remote text of the open turn (for speculation on a partial segment)."""
        t = self.turn
        if t and not t.get("answered") and t["segments"]:
            return self._turn_text(t) + " "
        return ""

    def _mic_active(self) -> bool:
        if self.input_mode == "external":
            return False
        from audio_capture import parse_device
        kind, _ = parse_device(self.cfg["audio"]["mic_device"])
        return kind != "off"

    def set_input_mode(self, mode: str) -> None:
        mode = "external" if str(mode).lower() in ("external", "phone", "mic", "speaker") else "pc"
        if mode != self.input_mode:
            self.input_mode = self.cfg["audio"]["input_mode"] = mode
            self.reset_turn("input mode changed")
            for seg in self.segmenters.values():
                seg.reset()
            for ch in ("them", "me"):
                self._set_interim(ch, "")
            self.session.event(f"audio input mode: {mode}")
            log.info("audio input mode: %s", mode)
            self._save()
        self.broadcast_status()

    # ---- v17: answer watchdog - a pending remote turn with 4+ words is ALWAYS answered -------------
    def _turn_watchdog(self) -> None:
        if not self.armed or not self.auto_answer:
            return
        with self._turn_lock:
            t = self.turn
            if t is None or t.get("answered") or t["state"] not in ("collecting", "holding"):
                return
            full = self._turn_text(t)
            if not full or not needs_answer(full, "them"):
                return
            if t.get("fired_segments") == len(t["segments"]):
                return   # this exact text was already attempted (answered, failed or cancelled): never loop on it
            limit = float(self._turn_cfg("turn_watchdog_s", 2.5))
            if time.time() - t["t_last"] < limit:
                return
            log.warning("turn %d: watchdog firing after %.1fs (state=%s)", t["id"], time.time() - t["t_last"], t["state"])
            self._fire_turn(t, "auto", "watchdog")

    def _turn_payload(self, t: dict | None, state: str | None = None) -> dict:
        if t is None:
            return {"type": "turn", "turn_id": None, "state": state or "idle", "segments": 0, "words": 0, "text": ""}
        text = self._turn_text(t)
        return {"type": "turn", "turn_id": t["id"], "state": state or t["state"], "segments": len(t["segments"]),
                "words": len(text.split()), "text": text, "gen_id": t.get("gen_id"), "card_gen_id": t.get("card_gen_id"),
                "skip": t.get("skip")}

    def _cancel_hold(self) -> None:
        if self._hold_timer is not None:
            self._hold_timer.cancel()
            self._hold_timer = None

    def _schedule_hold(self, t: dict, hold_ms: int, reason: str, resume_state: str | None = None) -> None:
        """Wait `hold_ms` for more remote speech. If nothing new was finalised by then, either (re)generate the
        answer for the buffered text or (resume_state='answered') just restore the finished card."""
        self._cancel_hold()
        n_seg = len(t["segments"])
        t["state"] = "holding"
        self.broadcast(self._turn_payload(t))
        self.broadcast({"type": "answer_hold", "turn_id": t["id"], "reason": reason, "hold_ms": hold_ms,
                        "gen_id": t.get("card_gen_id")})

        def fire():
            with self._turn_lock:
                if self.turn is not t or t["state"] != "holding" or len(t["segments"]) != n_seg or t.get("answered"):
                    return
                if t.get("fired_segments") == len(t["segments"]) and not t.get("interrupted"):
                    # nothing new was said and this text already has its answer: just clear the badge
                    t["state"] = "answered" if t.get("card_gen_id") is not None else "collecting"
                    self.broadcast(self._turn_payload(t))
                    return
                self._fire_turn(t, "auto", f"hold elapsed ({reason})")

        self._hold_timer = threading.Timer(hold_ms / 1000.0, fire)
        self._hold_timer.daemon = True
        self._hold_timer.start()

    def _new_turn(self, first_segment: str, reason: str) -> dict:
        self._cancel_hold()
        t = {"id": next(self._turn_ids), "segments": [first_segment], "t_start": time.time(), "t_last": time.time(),
             "state": "collecting", "gen_id": None, "card_gen_id": None, "answered": False, "interrupted": False, "skip": None,
             "fired_segments": 0, "hold_extended": False, "t_answered": None}
        self.turn = t
        self.diag["turn_id"] = t["id"]
        log.info("turn %d started (%s)", t["id"], reason)
        return t

    def reset_turn(self, reason: str = "manual") -> None:
        """'New turn' button / Alt+N: whatever the remote speaker says next is a brand-new question."""
        with self._turn_lock:
            self._cancel_hold()
            t = self.turn
            if t is not None:
                t["answered"] = True
                t["state"] = "closed"
                self.session.event(f"turn {t['id']} closed ({reason})")
            self._me_words_since_remote = 0
            self.broadcast(self._turn_payload(None, "reset"))

    def _me_spoke(self, text: str) -> None:
        """The candidate spoke: once >= N words came through the mic, the open remote turn is answered."""
        n = len((text or "").split())
        with self._turn_lock:
            self._me_words_since_remote += n
            t = self.turn
            if t is not None and not t.get("answered") and self._me_words_since_remote >= int(self._turn_cfg("turn_me_words_reset", 4)):
                self._cancel_hold()
                t["answered"] = True
                if t["state"] in ("collecting", "holding"):
                    t["state"] = "closed"
                log.info("turn %d answered by me (%d words) - next remote segment starts a new turn", t["id"], self._me_words_since_remote)
                self.broadcast(self._turn_payload(t, "answered"))

    def _me_talking(self, text: str) -> None:
        """Interim / partial mic words: the user has started answering. Close the remote turn as soon as N
        words are heard, without waiting for the mic utterance to end (people read an answer in one breath)."""
        if len((text or "").split()) < int(self._turn_cfg("turn_me_words_reset", 4)):
            return
        with self._turn_lock:
            t = self.turn
            if t is not None and not t.get("answered") and t["state"] != "generating":
                self._cancel_hold()
                t["answered"] = True
                if t["state"] in ("collecting", "holding"):
                    t["state"] = "closed"
                self.broadcast(self._turn_payload(t, "answered"))

    def _on_remote_activity(self, interim_text: str) -> None:
        """Remote words are arriving (interim or partial piece). If an answer for the open turn is streaming or
        waiting, the speaker is still talking: abort it now and keep collecting into the same turn_id. The card
        on screen is kept (with an 'updating' badge) and replaced in place when the speaker pauses again."""
        if not self.armed or not self.auto_answer:
            return
        words = len((interim_text or "").split())
        with self._turn_lock:
            t = self.turn
            if t is None or t.get("answered"):
                return
            # How long to wait for the continued sentence to be finalised by the STT before falling back to
            # re-answering the text we already have. Must be longer than an STT endpoint (~0.75 s) or the
            # answer is re-fired and re-cancelled on every interim.
            hold_ms = int(self._turn_cfg("turn_continue_hold_ms", 2500))
            if t["state"] == "holding" and words >= 1:
                if not t.get("hold_extended"):
                    t["hold_extended"] = True
                    self._schedule_hold(t, hold_ms, "speaker_continuing")
            elif t["state"] == "generating" and words >= 3:
                t["interrupted"] = True
                with self._gen_lock:
                    if self._gen_cancel is not None:
                        self._gen_cancel.set()     # abort the in-flight LLM task immediately
                if self._spec is not None:
                    self._spec["cancel"].set()
                    self._spec = None
                log.info("turn %d: speaker kept talking - generation %s aborted, accumulating", t["id"], t.get("gen_id"))
                t["hold_extended"] = True
                self._schedule_hold(t, hold_ms, "speaker_continuing")   # safety: regenerate even if no new segment lands
            # A FINISHED answer is never touched by interim words ("ok", "right", back-channel while the user
            # reads it). Only a new finalised sentence of 3+ words re-opens it (see _remote_segment_done).

    def _remote_segment_done(self, text: str) -> None:
        """A remote segment finished (STT endpoint). Append it to the open turn (or start one) and decide:
        clear question / direct prompt -> fast trigger; statement / connector -> hold ~1.8 s for the rest."""
        text = (text or "").strip()
        if not text:
            return
        self._auto_flip_decoder(text)
        now = time.time()
        with self._turn_lock:
            t = self.turn
            gap = float(self._turn_cfg("turn_max_gap_s", 25)) if self._mic_active() else float(self._turn_cfg("turn_max_gap_no_mic_s", 8))
            stale = float(self._turn_cfg("turn_answered_stale_s", 12))
            if t is not None and t["state"] == "answered" and not t.get("answered") and skip_reason(text, "them"):
                # back-channel after a finished answer ("ok", "right", "perfecto"): not part of the question
                log.debug("turn %d: ignoring %r after the answer", t["id"], text[:30])
                return
            answered_long_ago = bool(t and t["state"] == "answered" and t.get("t_answered") and now - t["t_answered"] > stale)
            if t is None or t.get("answered") or answered_long_ago or now - t["t_last"] > gap or not self.armed:
                reason = ("first" if t is None else "answered by me" if t.get("answered") else
                          "previous answer is old" if answered_long_ago else
                          f"{int(now - t['t_last'])}s of remote silence" if now - t["t_last"] > gap else "not armed")
                t = self._new_turn(text, reason)
            else:
                t["segments"].append(text)
                t["t_last"] = now
                # keep the newest material when the turn gets very long (the transcript still holds all of it)
                max_words = int(self._turn_cfg("turn_max_words", 400))
                while len(self._turn_text(t).split()) > max_words and len(t["segments"]) > 1:
                    t["segments"].pop(0)
                log.info("turn %d extended: %d segments, %d words", t["id"], len(t["segments"]), len(self._turn_text(t).split()))
            self._me_words_since_remote = 0
            self._cancel_hold()
            if t["state"] == "generating" and len(t["segments"]) > 1:
                # utterance engines (local Whisper / Groq) have no interim words: the new segment IS the signal
                t["interrupted"] = True
                with self._gen_lock:
                    if self._gen_cancel is not None:
                        self._gen_cancel.set()
                self.broadcast({"type": "answer_hold", "turn_id": t["id"], "reason": "speaker_continuing", "gen_id": t.get("card_gen_id")})
            full = self._turn_text(t)
            skip = (None if self.armed else "listening not started") or (None if self.auto_answer else "auto-answer is OFF (Setup -> Brain)") \
                or skip_reason(full, "them")
            t["skip"] = skip
            if skip:
                t["state"] = "collecting"
                if self._spec is not None:
                    self._spec["cancel"].set()
                    self._spec = None
                log.info("turn %d: not answering yet - %s", t["id"], skip)
                self.broadcast(self._turn_payload(t))
                return
            # v19 universal auto-trigger: 3+ words ALWAYS answer. "fast" (?, ¿…?, platícame / cuéntame / how did
            # you…) fires now (~650 ms total with the STT endpoint); any other statement after a ~800 ms pause.
            klass = trigger_class(full)
            hold_ms = int(self._turn_cfg("turn_fast_hold_ms", 0)) if klass == "fast" else int(self._turn_cfg("turn_setup_hold_ms", 100))
            if hold_ms <= 0:
                self._fire_turn(t, "auto", f"fast trigger ({klass})")
                return
            self._schedule_hold(t, hold_ms, "context_setup")

    def _auto_flip_decoder(self, text: str) -> None:
        """AUTO mode: a finished remote utterance that reads as the other language moves the STT routing
        pointer (Deepgram: to the other pre-warmed socket, 0 ms; Whisper/Groq: explicit decoder language +
        prompt) so the NEXT utterance is decoded natively. A user-forced EN/ES is never overridden."""
        eng = self.transcriber
        if eng is None or self.cfg["general"].get("language") != "auto" or not hasattr(eng, "flip_auto"):
            return
        if len(text.split()) < 3:
            return
        # a low-confidence final is the WRONG decoder hearing the other language: its text is garbage, never trust it
        conf = getattr(eng, "last_confidence", None)
        conf = conf.get("them") if isinstance(conf, dict) else conf
        if isinstance(conf, (int, float)) and conf < getattr(eng, "LOW_CONF", 0.65):
            return
        det = detect_language(text)
        if det in ("en", "es") and det != getattr(eng, "language" if not getattr(eng, "streaming", False) else "active_lang", None):
            if eng.flip_auto(det, source=f"text reads as {det}"):
                self.diag["stt_auto_flips"] = self.diag.get("stt_auto_flips", 0) + 1
                self.broadcast({"type": "stt_language", "active": det, "decoder": det, "mode": "auto", "source": "text"})
                self.broadcast_status()

    def _auto_flip_on_interim(self, text: str) -> None:
        """AUTO mode, while the other person is still talking: the words coming out of the active decoder are
        plainly the other language (the Spanish decoder writing "I heard the question repeated, let's make a
        concrete one"). Waiting for a finished sentence does not work here - the wrong decoder often never
        finalises one - so the pointer moves as soon as the evidence is clear. One move per 8 s at most."""
        eng = self.transcriber
        if eng is None or self.cfg["general"].get("language") != "auto" or not getattr(eng, "streaming", False):
            return
        if getattr(eng, "mode", "auto") != "auto" or time.time() - self._interim_flip_at < 8.0:
            return
        en, es = language_evidence(text)
        active = getattr(eng, "active_lang", None)
        other, mine, theirs = ("en", es, en) if active == "es" else ("es", en, es)
        if theirs >= 4 and theirs >= 2 * mine + 2:
            self._interim_flip_at = time.time()
            if eng.flip_auto(other, source=f"live words read as {other}"):
                self.diag["stt_auto_flips"] = self.diag.get("stt_auto_flips", 0) + 1
                self.broadcast({"type": "stt_language", "active": other, "decoder": other, "mode": "auto", "source": "text"})
                self.broadcast_status()

    def _fire_turn(self, t: dict, mode: str, why: str) -> int:
        """Generate (or regenerate, replacing the card in place) the answer for the whole accumulated turn."""
        self._cancel_hold()
        full = self._turn_text(t)
        replace = t.get("card_gen_id") is not None
        spec = self._spec
        self._spec = None
        reuse = None
        if spec is not None and not replace and self._spec_matches(spec, full):
            log.info("speculation released (%.0f%% overlap)", 100 * spec["overlap"])
            reuse = spec
        elif spec is not None:
            log.info("speculation discarded (%s)", "turn replaced" if replace else "speaker pivoted")
            spec["cancel"].set()
        t["state"] = "generating"
        t["interrupted"] = False
        t["hold_extended"] = False
        t["fired_segments"] = len(t["segments"])
        t["skip"] = None
        log.info("turn %d -> %s answer (%s): %d segments, %d words", t["id"], "REPLACE" if replace else "new", why,
                 len(t["segments"]), len(full.split()))
        gen_id = self.trigger(mode, full, reuse=reuse, turn_id=t["id"], replace=replace)
        t["gen_id"] = gen_id
        if t["card_gen_id"] is None:
            t["card_gen_id"] = gen_id
        self.broadcast(self._turn_payload(t))
        return gen_id

    def _turn_generation_finished(self, gen_id: int, cancelled: bool, ok: bool) -> None:
        with self._turn_lock:
            t = self.turn
            if t is None or t.get("gen_id") != gen_id:
                return
            if t["state"] == "generating":
                t["state"] = "answered" if ok and not cancelled else "collecting"
                if t["state"] == "answered":
                    t["t_answered"] = time.time()
                self.broadcast(self._turn_payload(t))

    # ------------------------------------------------------------------ generation
    def trigger(self, mode: str, trigger_text=None, reuse: dict | None = None, turn_id: int | None = None,
                replace: bool = False) -> int:
        with self._gen_lock:
            if self._gen_cancel is not None and (reuse is None or self._gen_cancel is not reuse["cancel"]):
                self._gen_cancel.set()
            if reuse is not None:
                cancel, gen_id = reuse["cancel"], reuse["gen_id"]
            else:
                cancel, gen_id = threading.Event(), next(self._gen_ids)
            self._gen_cancel = cancel
        threading.Thread(target=self._generate, args=(gen_id, mode, trigger_text, cancel, reuse, turn_id, replace),
                         name=f"gen-{gen_id}", daemon=True).start()
        return gen_id

    # ------------------------------------------------------------------ speculative pre-drafting
    def _maybe_speculate(self, interim: str) -> None:
        """Once the remote utterance has >= N words with a clear topic, retrieve context and start the fast
        opener in the background. On turn end the draft is released (same intent) or discarded (pivot)."""
        llm = self.cfg["llm"]
        if not llm.get("speculate", True) or self._fast_provider() is None:
            return
        words = interim.split()
        if len(words) < int(llm.get("speculate_min_words", 8)):
            return
        toks = set(tokenize(interim))
        if len(toks) < 3:
            return  # no real topic yet
        if self._spec is not None:
            if self._spec["tokens"] and len(toks & self._spec["tokens"]) / max(1, len(toks)) >= 0.6:
                return  # same intent still developing - keep the running draft
            self._spec["cancel"].set()  # the speaker moved on - restart
        with self._gen_lock:
            cancel, gen_id = threading.Event(), next(self._gen_ids)
        lines = list(self.transcript)
        sections = self.context.sections_for(interim, boost=self.session_focus)
        spec = {"gen_id": gen_id, "cancel": cancel, "text": interim, "tokens": toks, "sections": sections,
                "lines": lines, "done": threading.Event(), "opener": [], "t0": time.time(), "overlap": 0.0}
        self._spec = spec
        log.info("speculating on %d words: %r", len(words), interim[:70])
        self._start_opener(gen_id, sections, lines, interim, cancel, speculative=True, sink=spec)

    _PIVOT = re.compile(r"\b(never ?mind|actually|instead|forget (that|it)|scratch that|rather than that|mejor dicho|"
                        r"olvida eso|olvídalo|en realidad|mejor|más bien|cambiando de tema)\b", re.IGNORECASE)

    def _spec_matches(self, spec: dict, final_text: str) -> bool:
        """Release the draft only if the final question is still about what we drafted on: the draft's
        tokens survive (>= min_overlap), no explicit pivot phrase was added, and the new material added
        after the draft does not outweigh the shared topic."""
        ftoks = set(tokenize(final_text))
        if not spec["tokens"] or not ftoks or spec["cancel"].is_set():
            return False
        shared = spec["tokens"] & ftoks
        overlap = len(shared) / len(spec["tokens"])
        spec["overlap"] = overlap
        if overlap < float(self.cfg["llm"].get("speculate_min_overlap", 0.7)):
            return False
        tail = final_text[len(spec["text"]):] if final_text.startswith(spec["text"]) else final_text
        if self._PIVOT.search(tail):
            return False
        new = ftoks - spec["tokens"]
        return len(new) <= max(4, int(1.5 * len(shared)))

    def push_to_answer(self) -> None:
        """Flush speech in progress, wait briefly for it to be transcribed, then generate."""
        def run():
            flushed = self.flush_pending_audio()
            if flushed and self.stt_streaming:
                # Deepgram answers a Finalize with the last is_final within ~300-600 ms
                deadline = time.time() + 1.2
                while time.time() < deadline and self.interim.get("them"):
                    time.sleep(0.05)
                time.sleep(0.15)
            elif flushed:
                deadline = time.time() + 4.0
                while not self.segments.empty() and time.time() < deadline:
                    time.sleep(0.05)
                try:
                    self.segments.join()
                except Exception:
                    pass
            self._finish_turn("them")
            with self._turn_lock:
                t = self.turn
                if t is not None and not t.get("answered") and t["segments"]:
                    if t["state"] == "generating" and not t.get("interrupted") and time.time() - t["t_last"] < 1.0:
                        return  # the fast trigger already fired on exactly this text a moment ago
                    self._fire_turn(t, "on_demand", "Answer Now (hold bypassed)")
                    return
            last_them = next((l["text"] for l in reversed(self.transcript) if l["channel"] == "them"), None)
            self.trigger("on_demand", last_them)
        threading.Thread(target=run, daemon=True).start()

    def cancel_generation(self) -> None:
        with self._gen_lock:
            if self._gen_cancel is not None:
                self._gen_cancel.set()

    def _generate(self, gen_id: int, mode: str, trigger_text, cancel: threading.Event, reuse: dict | None = None,
                  turn_id: int | None = None, replace: bool = False) -> None:
        """Wrapper: whatever happens inside, the HUD gets an llm_end and the turn leaves the 'generating' state."""
        done = {"ended": False, "ok": False}
        try:
            self._generate_inner(gen_id, mode, trigger_text, cancel, reuse, turn_id, replace, done)
        except Exception as exc:  # noqa: BLE001
            log.exception("generation %d crashed", gen_id)
            self.broadcast({"type": "error", "message": f"Answer generation failed: {type(exc).__name__}: {exc}"})
        finally:
            self._gen_running.discard(gen_id)
            if not done["ended"]:
                self.broadcast({"type": "llm_end", "gen_id": gen_id, "provider": None, "cancelled": cancel.is_set(),
                                "errors": ["generation aborted"], "elapsed_s": 0, "first_token_s": None, "mode": mode,
                                "part": "full", "turn_id": turn_id})
            if turn_id is not None:
                self._turn_generation_finished(gen_id, cancel.is_set(), done["ok"])

    def _generate_inner(self, gen_id: int, mode: str, trigger_text, cancel: threading.Event, reuse: dict | None,
                        turn_id: int | None, replace: bool, done: dict) -> None:
        llm, style, gen = self.cfg["llm"], self.cfg["style"], self.cfg["general"]
        lines = list(self.transcript)
        q_for_lang = (trigger_text if isinstance(trigger_text, str) and mode in ("auto", "on_demand") else
                      self.last_answer.get("question") if mode == "followup" else
                      next((l["text"] for l in reversed(lines) if l["channel"] == "them"), ""))
        lang = self.answer_language(q_for_lang)
        replace_gen_id = None
        if replace and turn_id is None:
            replace_gen_id, self._replace_card_gen = self._replace_card_gen, None
        if mode in ("auto", "on_demand", "followup"):
            self._last_gen = {"mode": mode, "trigger_text": trigger_text, "turn_id": turn_id, "t": time.time(), "lang": lang,
                              "gen_id": gen_id, "card_gen_id": ((self.turn or {}).get("card_gen_id") if turn_id is not None
                                                                else replace_gen_id or gen_id)}
            if mode in ("auto", "on_demand"):
                self._last_question_t = time.time()
        self._gen_running.add(gen_id)
        primary_first = self.provider_order()
        image = None
        vision_age = None
        if mode == "summary":
            if not lines:
                self.broadcast({"type": "error", "message": "No transcript yet."})
                return
            system = SUMMARY_SYSTEM_PROMPT.format(language_rule=language_rule(lang, summary=True))
            user = build_summary_prompt(lines)
            providers = primary_first
        elif mode == "vision":
            sections = self.context.sections_for(" ".join(l["text"] for l in lines[-4:]), boost=self.session_focus)
            system = focus_block(self.session_focus) + VISION_SYSTEM.format(max_words=max(90, int(llm["max_answer_words"])), language_rule=language_rule(lang))
            user = build_vision_prompt(sections, lines)
            image = trigger_text  # (bytes, mime)
            providers = primary_first
        elif mode == "followup":
            if not self.last_answer.get("text"):
                self.broadcast({"type": "error", "message": "No previous answer to follow up on."})
                return
            if trigger_text == "pivot":
                # retrieve for the QUESTION, pushing the discarded story's terms down so other projects surface
                banned = " ".join((self.last_answer.get("signature") or {}).get("entities") or [])
                sections = self.context.sections_for(self.last_answer.get("question") or self.last_answer["text"][:200],
                                                     boost=self.session_focus, avoid=banned)
            else:
                sections = self.context.sections_for(f"{self.last_answer.get('question') or ''} {self.last_answer['text'][:400]}", boost=self.session_focus)
            system = self._system_prompt(style, llm, lang, sections)
            user = build_followup_prompt(sections, lines[-int(llm["transcript_window"]):],
                                         self.last_answer.get("question"), self.last_answer["text"], trigger_text,
                                         ledger=self.story_ledger, signature=self.last_answer.get("signature"))
            providers = primary_first
        else:
            if not lines:
                self.broadcast({"type": "error", "message": "No transcript yet — nothing to answer."})
                return
            question = trigger_text or next((l["text"] for l in reversed(lines) if l["channel"] == "them"), "")
            recent = " ".join(l["text"] for l in lines[-3:] if l["channel"] == "them")
            probe = is_probing_followup(question, self.last_answer)
            if probe:
                # keep retrieving the chunks of the story being probed, not a new one
                sections = self.context.sections_for(f"{question} {self.last_answer.get('text', '')[:300]}", boost=self.session_focus)
            else:
                banned = " ".join((self.last_answer.get("signature") or {}).get("entities") or []) if self.story_ledger else ""
                sections = self.context.sections_for(f"{question} {recent}", boost=self.session_focus, avoid=banned)
            story = wants_story(question)
            self.diag["continuity"] = ("probe" if probe else "direct" if not story else "rotate" if self.story_ledger else "first")
            # v15 auto-vision: attach the buffered screen frame when the question points at the screen (or always, if configured)
            frame = self._fresh_vision_frame()
            if frame is not None and (llm.get("auto_vision_always") or refers_to_screen(f"{question} {recent}")):
                image = (frame["data"], frame["mime"])
                vision_age = time.time() - frame["t"]
                log.info("gen %d: auto-vision frame attached (%d KB, %.0fs old)", gen_id, frame["bytes"] // 1024, vision_age)
                reuse = None                       # the speculative opener never saw the screen - just don't show it
            log.info("gen %d continuity: %s", gen_id, self.diag["continuity"])
            system = self._system_prompt(style, llm, lang, sections)
            user = build_generation_prompt(sections, lines[-int(llm["transcript_window"]):],
                                           trigger_text, mode, llm["max_answer_words"], ledger=self.story_ledger,
                                           probe=probe)
            if image is not None:
                user = screen_frame_note(vision_age) + user
            providers = primary_first
            if reuse is not None:
                # Release the speculative opener: replay what already streamed, keep streaming the rest.
                self.broadcast({"type": "llm_start", "gen_id": gen_id, "mode": "opener", "part": "opener", "speculative": True,
                                "turn_id": turn_id, "replace": bool(replace), "question": question})
                for tok in list(reuse["opener"]):
                    self.broadcast({"type": "llm_token", "gen_id": gen_id, "text": tok, "part": "opener"})
                reuse["released"] = True
                if reuse["done"].is_set():
                    self.broadcast({"type": "llm_end", "gen_id": gen_id, "provider": reuse.get("provider"), "part": "opener",
                                    "cancelled": False, "errors": [], "elapsed_s": reuse.get("elapsed_s"), "mode": "opener",
                                    "speculative": True})
            elif llm.get("fast_opener", True) and image is None:   # no text-only opener when the answer depends on the screen
                self._start_opener(gen_id, sections, lines, question, cancel, probe=probe, turn_id=turn_id, replace=replace)

        self.broadcast({"type": "llm_start", "gen_id": gen_id, "mode": mode, "part": "full",
                        "kind": trigger_text if mode == "followup" else None,
                        "continuity": self.diag.get("continuity") if mode in ("auto", "on_demand") else None,
                        "vision_attached": bool(image is not None and mode in ("auto", "on_demand")),
                        "turn_id": turn_id, "replace": bool(replace), "lang": lang, "lang_mode": gen["language"],
                        "replace_gen_id": replace_gen_id,
                        "turn_segments": (len(self.turn["segments"]) if turn_id is not None and self.turn and self.turn["id"] == turn_id else None),
                        "card_gen_id": (self.turn or {}).get("card_gen_id") if turn_id is not None and self.turn and self.turn["id"] == turn_id else None,
                        "question": (trigger_text if isinstance(trigger_text, str) and mode in ("auto", "on_demand") else
                                     self.last_answer.get("question") if mode == "followup" else None),
                        "retrieval": sections.get("retrieval") if mode not in ("summary",) else None})
        t0 = time.time()
        used, text, errors = None, "", []
        first_tok = {"t": None}
        for idx, provider in enumerate(providers):
            if cancel.is_set():
                break
            if not provider.available():
                errors.append(f"{provider.name}: not available")
                continue
            if idx > 0:
                self.broadcast({"type": "llm_reset", "gen_id": gen_id})
            def emit(tok, _p=provider):
                if first_tok["t"] is None:
                    first_tok["t"] = round(time.time() - t0, 2)
                    self.diag["last_first_token_s"] = first_tok["t"]
                    log.info("gen %d first token via %s after %.2fs", gen_id, _p.name, first_tok["t"])
                self.broadcast({"type": "llm_token", "gen_id": gen_id, "text": tok, "part": "full"})
            try:
                if image is not None:
                    text = provider.stream_vision(system, user, image[0], image[1], emit, cancel)
                else:
                    text = provider.stream(system, user, emit, cancel)
                if text.strip():
                    used = provider.name
                    self.provider_errors.pop(provider.name, None)
                    break
                errors.append(f"{provider.name}: empty response")
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                self.note_provider_error(provider.name, str(exc))
                log.warning("%s failed: %s", provider.name, exc)
        log.info("gen %d (%s/%s/%s) via %s in %.1fs%s", gen_id, mode, style["tone"], style["length"], used,
                 time.time() - t0, " [cancelled]" if cancel.is_set() else "")
        if used and not cancel.is_set():
            if mode == "vision":
                self.session.vision(text, used)
            elif mode != "summary":
                question = trigger_text if mode in ("auto", "on_demand") else self.last_answer.get("question")
                if mode != "followup":
                    question = trigger_text or next((l["text"] for l in reversed(lines) if l["channel"] == "them"), None)
                sig = story_signature(text, self._stt_vocab_cache())
                self.last_answer = {"question": question, "text": text, "mode": mode, "signature": sig, "lang": lang, "t": time.time()}
                self.last_answer_lang = lang

                # tldr rewrites the same story; example/deepen/pivot and fresh answers add to the ledger
                if mode != "followup" or trigger_text in ("example", "deepen", "pivot"):
                    self.story_ledger.append({"question": question, "signature": sig, "mode": mode,
                                              "kind": trigger_text if mode == "followup" else None, "t": time.time()})
                    self.story_ledger = self.story_ledger[-12:]
                    log.info("story ledger +1 (%s): %s", mode, ", ".join(sig["entities"]) or "(no named project)")
                self.broadcast({"type": "story", "gen_id": gen_id, "entities": sig["entities"], "ledger": len(self.story_ledger),
                                "mode": mode, "kind": trigger_text if mode == "followup" else None})
                self.session.suggestion(text, (mode if mode != "followup" else f"followup:{trigger_text}")
                                        + ("+screen" if image is not None and mode in ("auto", "on_demand") else ""), used, question)
        self.broadcast({"type": "llm_end", "gen_id": gen_id, "provider": used, "cancelled": cancel.is_set(),
                        "errors": errors, "elapsed_s": round(time.time() - t0, 2), "first_token_s": first_tok["t"],
                        "mode": mode, "part": "full", "warm": getattr(provider, "last_was_warm", None) if used else None,
                        "turn_id": turn_id})
        done["ended"] = True
        done["ok"] = bool(used) and not cancel.is_set()

    # ------------------------------------------------------------------ providers
    PROVIDER_NAMES = ("claude", "gemini") + tuple(COMPAT_NAMES)

    def provider(self, name: str):
        return {"claude": self.claude, "gemini": self.gemini, **self.compat}.get(name)

    def provider_order(self) -> list:
        """The chosen primary first, then every other configured provider as automatic fallback."""
        primary = self.cfg["general"].get("primary", "claude")
        names = [primary] + [n for n in self.PROVIDER_NAMES if n != primary]
        out = [self.provider(n) for n in names if self.provider(n) is not None]
        out = [p for i, p in enumerate(out) if i == 0 or p.available()]
        # a provider that just failed for a reason retrying will not fix (expired login, bad key, no credit)
        # is tried last for 10 minutes, so every answer does not pay for the same failure first
        now = time.time()
        sick = {n for n, e in self.provider_errors.items() if e.get("sticky") and now - e["t"] < 600}
        return [p for p in out if p.name not in sick] + [p for p in out if p.name in sick]

    _STICKY_ERR = re.compile(r"authenticat|oauth|log ?in|401|403|invalid api key|api key not valid|incorrect api key|"
                             r"quota|billing|credit|not found|404|permission", re.I)

    def note_provider_error(self, name: str, message: str) -> None:
        self.provider_errors[name] = {"message": str(message)[:400], "t": time.time(),
                                      "sticky": bool(self._STICKY_ERR.search(str(message)))}

    def clear_provider_error(self, name: str) -> None:
        if self.provider_errors.pop(name, None) is not None:
            self.broadcast_status()

    def providers_info(self) -> dict:
        llm = self.cfg["llm"]
        info = {
            "claude": {"label": "Claude (Claude Code login)", "available": self.claude.available(), "model": llm["claude_model"],
                       "kind": "cli", "key_set": self.claude.available(), "keys_url": "https://claude.com/claude-code"},
            "gemini": {"label": "Gemini (Google)", "available": self.gemini.available(), "model": llm["gemini_model"],
                       "kind": "key", "key_set": bool(self.gemini.api_key), "keys_url": "https://aistudio.google.com/apikey"},
        }
        for n, c in self.compat.items():
            info[n] = {"label": c.preset["label"], "available": c.available(), "model": c.model, "kind": "key",
                       "key_set": bool(c.api_key), "keys_url": c.preset["keys_url"], "vision": c.supports_vision,
                       "base_url": c.base_url}
        for n, e in self.provider_errors.items():
            if n in info:
                info[n]["error"] = e["message"]
                info[n]["error_age_s"] = int(time.time() - e["t"])
        return info

    def set_provider(self, name: str, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        """Wizard / Setup: store a provider's key and model in config.json and rebuild its client."""
        llm = self.cfg["llm"]
        if name == "gemini":
            if api_key is not None and api_key.strip():
                llm["gemini_api_key"] = api_key.strip()
            if model and model.strip():
                llm["gemini_model"] = model.strip()
            self.gemini = GeminiClient(llm["gemini_api_key_env"], llm["gemini_model"], llm.get("gemini_api_key", ""))
            self.gemini_fast = GeminiClient(llm["gemini_api_key_env"], llm.get("fast_gemini_model", "gemini-2.5-flash"), llm.get("gemini_api_key", ""))
        elif name == "claude":
            if model and model.strip():
                self.apply_settings({"llm": {"claude_model": model.strip()}}, persist=False)
        elif name in self.compat:
            pc = llm.setdefault("providers", {}).setdefault(name, {})
            if api_key is not None and api_key.strip():
                pc["api_key"] = api_key.strip()
            if model and model.strip():
                pc["model"] = model.strip()
            if base_url is not None:
                pc["base_url"] = base_url.strip()
            self.compat[name].configure(pc)
        else:
            return
        self._save()
        self.broadcast_status()

    def test_provider(self, name: str) -> None:
        p = self.provider(name)
        if p is None:
            return
        self.broadcast({"type": "provider_test", "provider": name, "state": "running"})

        def run():
            t0 = time.time()
            if hasattr(p, "test"):
                res = p.test()
            else:
                try:
                    if not p.available():
                        raise RuntimeError("not installed" if name == "claude" else "API key not set")
                    text = p.stream("Reply with exactly: OK", "ping", lambda _t: None, threading.Event())
                    res = {"ok": bool(text.strip()), "sample": text.strip()[:40], "error": None if text.strip() else "empty response"}
                except Exception as exc:  # noqa: BLE001
                    res = {"ok": False, "sample": "", "error": str(exc).splitlines()[0][:300]}
                res["ms"] = int((time.time() - t0) * 1000)
                res["model"] = getattr(p, "model", None)
            if res.get("ok"):
                self.provider_errors.pop(name, None)
            else:
                self.note_provider_error(name, res.get("error") or "test failed")
            self.broadcast({"type": "provider_test", "provider": name, "state": "done", **res})
            self.broadcast_status()

        threading.Thread(target=run, name=f"test-{name}", daemon=True).start()

    def _fast_provider(self):
        pref = self.cfg["llm"].get("fast_provider", "auto")
        order = [self.gemini_fast, self.claude_fast] if pref in ("auto", "gemini") else [self.claude_fast, self.gemini_fast]
        primary = self.cfg["general"].get("primary")
        if primary in self.compat and pref == "auto":      # an API primary is already fast: use it for the opener too
            order = [self.compat[primary]] + order
        return next((p for p in order if p.available()), None)

    def _start_opener(self, gen_id: int, sections: dict, lines: list, question: str, cancel: threading.Event,
                      speculative: bool = False, sink: dict | None = None, probe: bool | None = None,
                      turn_id: int | None = None, replace: bool = False) -> None:
        """Stage 1 of the two-stage answer: a tiny prompt to the fastest model for the first sentence(s).
        In speculative mode the tokens are collected in `sink` (not shown) until the turn ends and the draft
        is released; if the user is already looking at it (released early) they stream straight through."""
        provider = self._fast_provider()
        if provider is None:
            return
        system = OPENER_SYSTEM.format(language_rule=language_rule(self.answer_language(question)))
        if probe is None:
            probe = is_probing_followup(question, self.last_answer)
        user = build_opener_prompt(sections, lines, question, speculative=speculative, session_focus=self.session_focus,
                                   ledger=self.story_ledger, probe=probe)

        def emit(tok):
            if sink is not None:
                sink["opener"].append(tok)
                if not sink.get("released"):
                    return
            self.broadcast({"type": "llm_token", "gen_id": gen_id, "text": tok, "part": "opener"})

        def run():
            t0 = time.time()
            if sink is None:
                self.broadcast({"type": "llm_start", "gen_id": gen_id, "mode": "opener", "part": "opener",
                                "turn_id": turn_id, "replace": bool(replace), "question": question})
            text, err = "", None
            try:
                text = provider.stream(system, user, emit, cancel)
            except Exception as exc:
                err = str(exc)
                log.warning("opener via %s failed: %s", provider.name, exc)
            el = round(time.time() - t0, 2)
            log.info("%sopener gen %d via %s/%s in %.1fs", "speculative " if speculative else "", gen_id,
                     provider.name, provider.model, el)
            if sink is not None:
                sink["provider"], sink["elapsed_s"] = provider.name, el
                sink["done"].set()
                if not sink.get("released"):
                    return  # still speculative: the end event is sent when (if) it is released
            self.broadcast({"type": "llm_end", "gen_id": gen_id, "provider": provider.name, "part": "opener",
                            "cancelled": cancel.is_set(), "errors": [err] if err else [], "elapsed_s": el,
                            "mode": "opener", "speculative": speculative})

        threading.Thread(target=run, name=f"opener-{gen_id}", daemon=True).start()

    # ------------------------------------------------------------------ vision / follow-ups / debrief
    def vision(self, image_b64: str, mime: str) -> None:
        try:
            data = base64.b64decode(image_b64.split(",", 1)[-1])
        except Exception as exc:
            self.broadcast({"type": "error", "message": f"bad screenshot payload: {exc}"})
            return
        if len(data) < 1000:
            self.broadcast({"type": "error", "message": "screenshot is empty"})
            return
        log.info("vision: %d KB %s", len(data) // 1024, mime)
        self.session.event(f"screen captured ({len(data) // 1024} KB)")
        self.trigger("vision", (data, mime or "image/jpeg"))

    # -- v15 passive auto-vision buffer ---------------------------------------------------------------
    def set_vision_buffer(self, image_b64: str | None, mime: str | None, clear: bool = False) -> None:
        if clear or not image_b64:
            self.vision_buffer = None
            return
        try:
            data = base64.b64decode(image_b64.split(",", 1)[-1])
        except Exception as exc:
            log.debug("bad vision_buffer payload: %s", exc)
            return
        if len(data) < 500:
            return
        self.vision_buffer = {"data": data, "mime": mime or "image/jpeg", "t": time.time(), "bytes": len(data)}
        self.diag["vision_frames"] = self.diag.get("vision_frames", 0) + 1

    def _fresh_vision_frame(self) -> dict | None:
        fb = self.vision_buffer
        if not self.auto_vision or fb is None:
            return None
        if time.time() - fb["t"] > self.vision_buffer_max_age_s:
            return None
        return fb

    def set_auto_vision(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled != self.auto_vision:
            self.auto_vision = self.cfg["llm"]["auto_vision"] = enabled
            self.session.event(f"auto-vision {'enabled' if enabled else 'disabled'}")
            self._save()
        if not enabled:
            self.vision_buffer = None
        self.broadcast_status()

    def followup(self, kind: str) -> None:
        """Alt+1 example · Alt+2 deepen · Alt+3 shorter · Alt+4 pivot (Cambiar ejemplo: same question, different story)."""
        kind = kind if kind in FOLLOWUP_KINDS else "tldr"
        if kind == "pivot":
            if not self.last_answer.get("text"):
                self.broadcast({"type": "error", "message": "Nothing to pivot yet — answer a question first."})
                return
            ents = (self.last_answer.get("signature") or {}).get("entities") or []
            self.session.event(f"pivot story requested (discarding: {', '.join(ents) or 'previous example'})")
            log.info("pivot: discarding example about %s", ", ".join(ents) or "(unnamed)")
        self.trigger("followup", kind)

    def _stt_vocab_cache(self) -> list[str]:
        """Profile vocabulary (same list the STT keyterms use) so story signatures prefer real product/client names."""
        now = time.time()
        cache = getattr(self, "_vocab_cache", None)
        if cache is None or now - cache[0] > 60:
            try:
                self._vocab_cache = (now, self._stt_vocabulary())
            except Exception:
                self._vocab_cache = (now, [])
        return self._vocab_cache[1]

    def end_session(self, analyze: bool = True) -> None:
        """Always stops the live session; runs the analysis only when there is something to analyze."""
        self.armed = False
        self.cancel_generation()
        self.reset_turn("session end")
        self.turn = None
        for seg in self.segmenters.values():
            seg.reset()
        if self._debrief_running:
            self.broadcast({"type": "error", "message": "Analysis already running."})
            self.broadcast_status()
            return
        if not analyze or self.session.count() < 2:
            self.session.event("session ended without analysis")
            stamp = self.session.stamp
            self.session_focus = ""
            self.session = SessionLogger(self.profile_dir, self.profile_name)
            self.transcript.clear()
            self.last_answer = {"question": None, "text": "", "mode": None}
            self.story_ledger = []
            self.broadcast({"type": "session", "state": "ended_no_analysis", "stamp": stamp,
                            "reason": "no_transcript" if analyze else "user"})
            self.broadcast_status()
            return
        self._debrief_running = True
        threading.Thread(target=self._debrief, daemon=True).start()

    def _debrief(self) -> None:
        session, gen_id = self.session, next(self._gen_ids)
        cancel = threading.Event()
        with self._gen_lock:
            if self._gen_cancel is not None:
                self._gen_cancel.set()
            self._gen_cancel = cancel
        lang = self.cfg["general"]["language"]
        sections = self.context.sections()
        providers = self.provider_order()
        self.broadcast({"type": "session", "state": "analyzing", "stamp": session.stamp})
        self.broadcast_status()
        self.broadcast({"type": "llm_start", "gen_id": gen_id, "mode": "debrief"})
        report, used, errors = "", None, []
        system = DEBRIEF_SYSTEM.format(language_rule=language_rule(lang))
        user = build_debrief_prompt(sections, session.to_markdown(max_chars=120000), session.session_focus)
        for idx, p in enumerate(providers):
            if not p.available():
                errors.append(f"{p.name}: not available")
                continue
            if idx > 0:
                self.broadcast({"type": "llm_reset", "gen_id": gen_id})
            try:
                report = p.stream(system, user, lambda tok: self.broadcast({"type": "llm_token", "gen_id": gen_id, "text": tok}),
                                  cancel, timeout_s=180) if p is self.claude else \
                    p.stream(system, user, lambda tok: self.broadcast({"type": "llm_token", "gen_id": gen_id, "text": tok}), cancel)
                if report.strip():
                    used = p.name
                    break
            except Exception as exc:
                errors.append(f"{p.name}: {exc}")
                log.warning("debrief via %s failed: %s", p.name, exc)
        memory_block = ""
        if report.strip() and not cancel.is_set():
            msys = MEMORY_EXTRACT_SYSTEM.format(language_rule=language_rule(lang))
            muser = build_memory_extract_prompt(session.transcript_only(), report)
            for p in self.provider_order():
                if not p.available():
                    continue
                try:
                    memory_block = p.stream(msys, muser, lambda _tok: None, cancel)
                    if memory_block.strip():
                        break
                except Exception as exc:
                    log.warning("memory extraction via %s failed: %s", p.name, exc)
            analysis = parse_analysis(report)
            md = analysis_to_markdown(analysis, lang if lang in ("en", "es") else "en") if analysis else report
            path = session.save_report(md, memory_block, analysis)
            if memory_block.strip():
                title = time.strftime("%Y-%m-%d %H:%M") + f" — session {session.stamp}"
                self.profiles.append_learned_memory(self.profile_name, memory_block, title)
                self.context.load(force=True)
            log.info("debrief saved: %s (memory: %d words)", path, len(memory_block.split()))
            self.broadcast({"type": "session", "state": "analyzed", "stamp": session.stamp,
                            "report_path": str(path), "memory_words": len(memory_block.split()),
                            "score": analysis.get("overall_score") if analysis else None,
                            "analysis_path": str(session.analysis_path()) if analysis else None})
            self.session_focus = ""
            self.session = SessionLogger(self.profile_dir, self.profile_name)  # fresh session (focus reset)
            self.transcript.clear()
            self.last_answer = {"question": None, "text": "", "mode": None}
            self.story_ledger = []
        self.broadcast({"type": "llm_end", "gen_id": gen_id, "provider": used, "cancelled": cancel.is_set(),
                        "errors": errors, "mode": "debrief"})
        self._debrief_running = False
        self.broadcast_status()

    def set_focus(self, focus: str) -> None:
        """Quick session focus: takes effect on the very next generation; stored in the session log."""
        focus = (focus or "").strip()[:1200]
        changed = focus != self.session_focus
        self.session_focus = focus
        self.session.set_focus(focus)
        if changed:
            log.info("session focus: %r", focus[:100])
            if self._spec is not None:  # a running speculative draft no longer reflects the hint
                self._spec["cancel"].set()
                self._spec = None
        self.broadcast_status()

    # ---- v18: answer language -------------------------------------------------------------------
    def answer_language(self, question: str | None = None, channel: str = "them") -> str:
        """EN / ES force the answer language. AUTO mirrors the question: a 0 ms stopword tally on the final
        question text, then the STT's own detection (Deepgram multi / Whisper), then the previous answer's
        language, then English."""
        mode = self.cfg["general"].get("language", "auto")
        if mode in ("en", "es"):
            return mode
        det = detect_language(question or "")
        if det is None and self.transcriber is not None:
            hint = getattr(self.transcriber, "last_detected", None)
            hint = hint.get(channel) if isinstance(hint, dict) else hint
            if hint in ("en", "es"):
                det = hint
        if det is None:
            det = self.last_answer_lang or "en"
        return det

    def _system_prompt(self, style: dict, llm: dict, lang: str, sections: dict) -> str:
        pcfg = self.profiles.config(self.profile_name)
        return build_system_prompt(style["tone"], style["length"], llm["max_answer_words"], lang,
                                   sections.get("playbook", ""), pcfg.get("job_role"), pcfg.get("company"),
                                   session_focus=self.session_focus)

    # ------------------------------------------------------------------ document & playbook bank
    def bank_list(self) -> dict:
        out = {}
        for sub in ("roles", "cvs", "experience", "playbooks"):
            items = []
            for f in sorted((self.bank_dir / sub).glob("*")):
                if f.is_file() and f.suffix.lower() in (".md", ".txt") and f.name.lower() != "readme.md":
                    try:
                        txt = f.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    items.append({"name": f.name, "path": str(f), "words": len(txt.split()),
                                  "mtime": int(f.stat().st_mtime)})
            out[sub] = sorted(items, key=lambda x: -x["mtime"])
        return out

    def bank_save(self, sub: str, name: str, text: str) -> Path:
        """Save text into data/bank/<sub>/<name>.md (overwrites a same-named entry)."""
        safe = re.sub(r"[^\w.\- ]+", "", name).strip().replace(" ", "_")[:80] or "entry"
        if not safe.lower().endswith((".md", ".txt")):
            safe += ".md"
        path = self.bank_dir / sub / safe
        if not path.exists() and len((text or "").split()) >= 2:
            # the same text already in the bank under another name (a CV attached to a second profile): reuse it
            want = self._bank_fingerprint(text)
            for other in (self.bank_dir / sub).glob("*"):
                if other.is_file() and other.suffix.lower() in (".md", ".txt") and other.name.lower() != "readme.md":
                    try:
                        if self._bank_fingerprint(other.read_text(encoding="utf-8", errors="replace")) == want:
                            return other
                    except OSError:
                        continue
        path.write_text((text or "").strip() + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _bank_fingerprint(text: str) -> str:
        """Same rule as BankStore.fingerprint in electron/context_manager.js: only the words count."""
        body = re.sub(r"^\s*#{1,6}[^\n]*\n", "", text or "")
        return hashlib.sha1(" ".join(re.findall(r"[^\W_]+", body.lower())).encode("utf-8")).hexdigest()

    def bank_read(self, sub: str, name: str) -> str:
        path = (self.bank_dir / sub / Path(name).name)
        if not path.exists() or path.suffix.lower() not in (".md", ".txt"):
            raise FileNotFoundError(name)
        return path.read_text(encoding="utf-8", errors="replace")

    # ------------------------------------------------------------------ profiles
    def _apply_profile_config(self) -> None:
        pcfg = self.profiles.config(self.profile_name)
        cwd = pcfg.get("claude_project") or None
        if cwd != self.claude.cwd:
            self.claude.cwd = cwd
            self.claude_fast.cwd = cwd
            if self.claude.available():
                threading.Thread(target=self.claude.reset_warm, daemon=True).start()
                threading.Thread(target=self.claude_fast.reset_warm, daemon=True).start()

    def set_profile(self, name: str) -> None:
        name = sanitize_name(name)
        if name == self.profile_name:
            self.broadcast_status()
            return
        self.session.event(f"profile switched to {name}")
        self.profile_name = name
        self.profile_dir = self.profiles.ensure(name)
        self.cfg["general"]["active_profile"] = name
        self.context = ContextStore(self.profile_dir, self.cfg["context"]["max_chars"],
                                    self.cfg["context"].get("chunk_words", 300), self.cfg["context"].get("top_chunks", 3))
        self.context.load(force=True)
        self.cfg["style"] = {k: self.profiles.playbook(name)[k] for k in ("tone", "length")}
        self._apply_profile_config()
        self.session = SessionLogger(self.profile_dir, name, self.session_focus)
        self.transcript.clear()
        self.last_answer = {"question": None, "text": "", "mode": None}
        self.story_ledger = []
        self._apply_profile_defaults(name)
        self._save()
        log.info("active profile: %s", name)
        if self.stt_streaming:
            self.restart_stt("profile keyterms")   # Deepgram keyterms are a connection parameter
        self.broadcast_status()

    def _apply_profile_defaults(self, name: str) -> None:
        """Per-profile defaults: transcription/answer language and the playbook template from the bank."""
        pcfg = self.profiles.config(name)
        # v19: default_language = the interviewer's usual language -> re-route the STT decoder for AUTO mode
        if self.transcriber is not None and hasattr(self.transcriber, "set_language"):
            self.transcriber.set_language(self.cfg["general"].get("language", "auto"), self.stt_default_language(), source="profile")
        pb_name = pcfg.get("default_playbook")
        if pb_name and not (self.profiles.playbook(name).get("text") or "").strip():
            try:
                self.profiles.save_playbook(name, {"text": self.bank_read("playbooks", pb_name)})
                self.context.load(force=True)
            except Exception as exc:
                log.warning("default playbook %s not found in bank: %s", pb_name, exc)

    def profiles_payload(self) -> dict:
        return {"type": "profiles", "active": self.profile_name, "profiles": self.profiles.list(),
                "archived": self.profiles.list(archived=True), "config": self.profiles.config(self.profile_name)}

    # ------------------------------------------------------------------ status / settings
    def status_payload(self) -> dict:
        audio = {}
        for c in self.captures:
            audio[c.channel] = {"device": c.device_name, "error": c.error, "active": c.active, "source": "python"}
        for ch in ("them", "me"):
            if self.external[ch]:
                fresh = time.time() - self.last_external[ch] < 3.0
                audio[ch] = {"device": "Electron capture", "error": None if fresh else "no frames from HUD yet",
                             "active": fresh, "source": "electron"}
            elif ch not in audio:
                audio[ch] = {"device": "off", "error": None, "active": False, "source": "off"}
        if self.input_mode == "external":
            mic = dict(audio.get("me") or {})
            audio["them"] = {**mic, "device": f"MIC -> REMOTO ({mic.get('device', 'mic')})", "source": "mic"}
            audio["me"] = {"device": "(external mode: mic is the remote voice)", "error": None, "active": False, "source": "off"}
        return {
            "type": "status",
            "listening": self.listening,
            "armed": self.armed,
            "audio_enabled": self.audio_enabled,
            "auto_answer": self.auto_answer,
            "stt_ready": self.transcriber is not None,
            "stt_error": self.stt_error,
            "stt_engine": self.cfg["stt"].get("engine"),
            "stt_streaming": self.stt_streaming,
            "stt_device": getattr(self.transcriber, "device", None) if self.transcriber else None,
            "stt": self.stt_state(),
            "diag": self.diag,
            "providers": {n: bool(self.provider(n) and self.provider(n).available()) for n in self.PROVIDER_NAMES},
            "providers_info": self.providers_info(),
            "onboarded": bool(self.cfg["general"].get("onboarded")),
            "context": self.context.summary(),
            "context_files": self.context.files(),
            "context_truncated": self.context.truncated(),
            "audio": audio,
            "transcript_lines": len(self.transcript),
            "settings": self.settings_snapshot(),
            "fast_provider": (lambda p: f"{p.name}/{p.model}" if p else None)(self._fast_provider()),
            "profile": {"name": self.profile_name, "config": self.profiles.config(self.profile_name),
                        "profiles": [p["name"] for p in self.profiles.list()],
                        "archived": [p["name"] for p in self.profiles.list(archived=True)]},
            "session_focus": self.session_focus,
            "auto_vision": self.auto_vision,
            "answer_language": self.last_answer_lang,
            "stt_detected": (lambda h: (h.get("them") if isinstance(h, dict) else h))(getattr(self.transcriber, "last_detected", None)) if self.transcriber else None,
            "turn": {k: v for k, v in self._turn_payload(self.turn).items() if k not in ("type", "text")},
            "vision_buffer_age_s": (round(time.time() - self.vision_buffer["t"], 1) if self.vision_buffer else None),
            "session": {"stamp": self.session.stamp, "focus": self.session_focus, "lines": self.session.count(),
                        "suggestions": self.session.count(("copilot", "vision")), "analyzing": self._debrief_running},
        }

    def settings_snapshot(self) -> dict:
        llm, gen, a, st = self.cfg["llm"], self.cfg["general"], self.cfg["audio"], self.cfg["style"]
        return {
            "language": gen["language"], "ui_language": gen.get("ui_language", "auto"), "primary": gen["primary"],
            "claude_model": llm["claude_model"], "claude_models": list(llm.get("claude_models") or []),
            "gemini_model": llm["gemini_model"], "gemini_models": list(llm.get("gemini_models") or []),
            "auto_answer": self.auto_answer, "max_answer_words": llm["max_answer_words"],
            "stt_model": self.cfg["stt"]["model_size"], "hotkeys": self.cfg["hotkeys"],
            "stt_engine": self.cfg["stt"].get("engine"), "stt_device_pref": self.cfg["stt"].get("device"),
            "deepgram_key_set": bool(self.cfg["stt"].get("deepgram_api_key") or os.environ.get("DEEPGRAM_API_KEY")),
            "groq_key_set": bool(self.cfg["stt"].get("groq_api_key") or os.environ.get("GROQ_API_KEY")),
            "stt_vocabulary": list(self.cfg["stt"].get("vocabulary") or []),
            "mic_device": a["mic_device"], "loopback_device": a["loopback_device"], "input_mode": self.input_mode,
            "tone": st["tone"], "length": st["length"],
        }

    def broadcast_status(self) -> None:
        self.broadcast(self.status_payload())

    def apply_settings(self, patch: dict, persist: bool = True) -> None:
        gen, llm, stt, st = self.cfg["general"], self.cfg["llm"], self.cfg["stt"], self.cfg["style"]
        restart_stt = ""
        sp = patch.get("stt") or {}
        if sp.get("engine") in ENGINES and sp["engine"] != stt.get("engine"):
            stt["engine"] = sp["engine"]
            restart_stt = "engine"
        for key in ("deepgram_api_key", "groq_api_key"):
            if key in sp and str(sp[key] or "").strip() != (stt.get(key) or ""):
                stt[key] = str(sp[key] or "").strip()
                if (key == "deepgram_api_key" and stt.get("engine") == "deepgram") or \
                   (key == "groq_api_key" and stt.get("engine") == "groq_whisper"):
                    restart_stt = restart_stt or "api key"
        if sp.get("model_size") and sp["model_size"] != stt.get("model_size"):
            stt["model_size"] = str(sp["model_size"])
            if stt.get("engine") == "whisper_local":
                restart_stt = restart_stt or "model"
        if sp.get("device") in ("auto", "cpu", "cuda") and sp["device"] != stt.get("device"):
            stt["device"] = sp["device"]
            if stt.get("engine") == "whisper_local":
                restart_stt = restart_stt or "device"
        if "vocabulary" in sp:
            raw = sp["vocabulary"]
            terms = [t.strip() for t in (raw.split(",") if isinstance(raw, str) else list(raw or [])) if str(t).strip()]
            if terms != list(stt.get("vocabulary") or []):
                stt["vocabulary"] = terms[:80]
                restart_stt = restart_stt or "vocabulary"
        g = patch.get("general") or {}
        lang_changed = False
        if g.get("language") in ("auto", "en", "es") and g["language"] != gen["language"]:
            gen["language"] = g["language"]
            lang_changed = True
            # v18: the answer language never touches the STT (Deepgram runs bilingual, Whisper auto-detects)
            if self.transcriber is not None and hasattr(self.transcriber, "set_language"):
                self.transcriber.set_language(g["language"], self.stt_default_language(), source="user")
                self.broadcast({"type": "stt_language", "active": getattr(self.transcriber, "language", None),
                                "decoder": (self.transcriber.state() or {}).get("language"), "mode": g["language"], "source": "user"})
        if g.get("ui_language") in ("auto", "en", "es"):
            gen["ui_language"] = g["ui_language"]
        if g.get("primary") in self.PROVIDER_NAMES:
            gen["primary"] = g["primary"]
        if "onboarded" in g:
            gen["onboarded"] = bool(g["onboarded"])
        l = patch.get("llm") or {}
        if "claude_model" in l and str(l["claude_model"]).strip() != llm["claude_model"]:
            llm["claude_model"] = str(l["claude_model"]).strip()
            self.claude.model = llm["claude_model"]
            threading.Thread(target=self.claude.reset_warm, daemon=True).start()
            if llm["claude_model"] and llm["claude_model"] not in llm["claude_models"]:
                llm["claude_models"].insert(0, llm["claude_model"])
        if str(l.get("gemini_model", "")).strip():
            llm["gemini_model"] = str(l["gemini_model"]).strip()
            self.gemini.model = llm["gemini_model"]
            if llm["gemini_model"] not in llm["gemini_models"]:
                llm["gemini_models"].insert(0, llm["gemini_model"])
        if "auto_answer" in l:
            self.auto_answer = llm["auto_answer"] = bool(l["auto_answer"])
        if "max_answer_words" in l:
            try:
                llm["max_answer_words"] = max(40, min(300, int(l["max_answer_words"])))
            except (TypeError, ValueError):
                pass
        if "gemini_classifier" in l:
            self.use_gemini_classifier = llm["gemini_classifier"] = bool(l["gemini_classifier"])
        s = patch.get("style") or {}
        if s.get("tone") in TONES or s.get("length") in LENGTHS:
            pb = self.profiles.save_playbook(self.profile_name, s)
            st["tone"], st["length"] = pb["tone"], pb["length"]
        if persist:
            self._save()
        if restart_stt:
            self.restart_stt(restart_stt)
        if lang_changed:
            self._language_flip_rescue()
        log.info("settings: lang=%s primary=%s claude=%s gemini=%s auto=%s tone=%s length=%s", gen["language"],
                 gen["primary"], llm["claude_model"], llm["gemini_model"], self.auto_answer, st["tone"], st["length"])
        self.broadcast_status()

    def _save(self) -> None:
        try:
            save_config(self.cfg)
        except Exception as exc:
            log.warning("could not save config.json: %s", exc)
            self.broadcast({"type": "error", "message": f"Settings applied but not saved: {exc}"})

    def toggle_language(self) -> None:
        """Alt+L: EN -> ES -> AUTO -> EN. Instant: no STT reconnect; a streaming / recent answer is re-done in place."""
        order = ["en", "es", "auto"]
        cur = self.cfg["general"].get("language", "auto")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "en"
        self.apply_settings({"general": {"language": nxt}})

    def _language_flip_rescue(self) -> None:
        """EN/ES flipped while an answer is streaming or within N s of the last question: abort the stream and
        re-answer the same question in the new language, into the same card."""
        lg = self._last_gen
        if not lg or lg["mode"] not in ("auto", "on_demand", "followup"):
            return
        window = float(self.cfg["llm"].get("language_flip_rescue_s", 15))
        streaming = lg.get("gen_id") in self._gen_running
        if not streaming and time.time() - self._last_question_t > window:
            return
        q = lg["trigger_text"] if lg["mode"] != "followup" else self.last_answer.get("question")
        new_lang = self.answer_language(q if isinstance(q, str) else None)
        if new_lang == lg.get("lang"):
            return  # same effective language (e.g. AUTO on a Spanish question -> ES): nothing to redo
        log.info("language flip %s -> %s: re-answering the last question in place", lg.get("lang"), new_lang)
        self.cancel_generation()
        self.broadcast({"type": "answer_hold", "turn_id": lg.get("turn_id"), "reason": "language_flip",
                        "gen_id": lg.get("card_gen_id")})
        with self._turn_lock:
            t = self.turn
            if lg.get("turn_id") is not None and t is not None and t["id"] == lg["turn_id"] and t["segments"]:
                self._fire_turn(t, "on_demand", f"language flip -> {new_lang}")
                return
        self._replace_card_gen = lg.get("card_gen_id")
        self.trigger(lg["mode"], lg["trigger_text"], replace=True)

    def cycle_style(self, key: str) -> None:
        opts = TONES if key == "tone" else LENGTHS
        cur = self.cfg["style"][key]
        self.apply_settings({"style": {key: opts[(opts.index(cur) + 1) % len(opts)] if cur in opts else opts[0]}})

    def set_audio_devices(self, mic, loopback) -> None:
        a = self.cfg["audio"]
        if mic is not None:
            a["mic_device"] = str(mic)
        if loopback is not None:
            a["loopback_device"] = str(loopback)
        self._save()
        self.restart_audio()
        log.info("audio devices: mic=%s loopback=%s", a["mic_device"], a["loopback_device"])
        self.broadcast_status()

    # ------------------------------------------------------------------ websocket
    def broadcast(self, msg: dict) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self._send_all(msg), self.loop)
        except RuntimeError:
            pass

    async def _send_all(self, msg: dict) -> None:
        if not self.clients:
            return
        data = json.dumps(msg, ensure_ascii=False)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def handle_client(self, ws) -> None:
        self.clients.add(ws)
        log.info("HUD connected (%d client(s))", len(self.clients))
        try:
            await ws.send(json.dumps(self.status_payload(), ensure_ascii=False))
            for line in list(self.transcript)[-6:]:
                await ws.send(json.dumps({"type": "transcript", "t": line["t"], "channel": line["channel"],
                                          "text": line["text"], "partial": bool(line.get("partial"))}, ensure_ascii=False))
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    self.external_audio(bytes(raw))
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._handle_command(ws, msg)
        except Exception as exc:
            log.debug("client loop ended: %s", exc)
        finally:
            self.clients.discard(ws)
            log.info("HUD disconnected")

    async def _handle_command(self, ws, msg: dict) -> None:
        cmd = msg.get("type")
        if cmd == "ping":
            await ws.send(json.dumps({"type": "pong", "t": time.time()}))
        elif cmd == "generate":
            self.push_to_answer()
        elif cmd == "summarize":
            self.trigger("summary")
        elif cmd == "cancel":
            self.cancel_generation()
        elif cmd == "set_focus":
            self.set_focus(str(msg.get("value") or ""))
        elif cmd == "start_live":
            if "focus" in msg:
                self.set_focus(str(msg.get("focus") or ""))
            self.turn = None
            self._me_words_since_remote = 0
            self.armed = True
            if not self.auto_answer:
                self.broadcast({"type": "error", "message": "Auto-answer is OFF - answers only with Alt+A. Turn it on in Setup -> Brain."})
            self.listening = True
            for seg in self.segmenters.values():
                seg.reset()
            self.session.event("live listening started")
            self.broadcast_status()
        elif cmd == "stop_live":
            self.armed = False
            self.reset_turn("stop")
            for seg in self.segmenters.values():
                seg.reset()
            for ch in ("them", "me"):
                self._set_interim(ch, "")
            self.vision_buffer = None
            self.session.event("live listening stopped")
            self.broadcast_status()
        elif cmd == "toggle_listening":
            self.listening = not self.listening
            for seg in self.segmenters.values():
                seg.reset()
            self.broadcast_status()
        elif cmd == "set_listening":
            self.listening = bool(msg.get("value", True))
            self.broadcast_status()
        elif cmd == "set_auto_answer":
            self.apply_settings({"llm": {"auto_answer": bool(msg.get("value", True))}})
        elif cmd == "reload_context":
            self.context.load(force=True)
            self.broadcast_status()
        elif cmd == "inject":
            text = str(msg.get("text", "")).strip()
            if text:
                self.add_transcript("me" if msg.get("channel") == "me" else "them", text)
        elif cmd == "status":
            self.broadcast_status()
        elif cmd == "set_config":
            self.apply_settings({"general": msg.get("general") or {}, "llm": msg.get("llm") or {},
                                 "style": msg.get("style") or {}, "stt": msg.get("stt") or {}},
                                persist=msg.get("persist", True))
        elif cmd == "restart_stt":
            self.restart_stt("requested from UI")
        elif cmd == "toggle_language":
            self.toggle_language()
        elif cmd == "cycle_tone":
            self.cycle_style("tone")
        elif cmd == "cycle_length":
            self.cycle_style("length")
        elif cmd == "list_audio_devices":
            def _list():
                devs = list_devices_struct()
                self.broadcast({"type": "audio_devices", **devs})
            threading.Thread(target=_list, daemon=True).start()
        elif cmd == "set_audio_devices":
            threading.Thread(target=self.set_audio_devices, args=(msg.get("mic"), msg.get("loopback")),
                             daemon=True).start()
        elif cmd == "list_profiles":
            await ws.send(json.dumps(self.profiles_payload(), ensure_ascii=False))
        elif cmd == "set_profile":
            threading.Thread(target=self.set_profile, args=(str(msg.get("name") or "default"),), daemon=True).start()
        elif cmd == "set_profile_config":
            patch = {k: msg[k] for k in ("claude_project", "use_learned_memory", "language", "default_language",
                                         "default_playbook", "job_role", "company") if k in msg}
            self.profiles.save_config(self.profile_name, patch)
            self._apply_profile_config()
            if "default_language" in patch and self.transcriber is not None and hasattr(self.transcriber, "set_language"):
                # the interviewer's usual language: only re-routes the STT decoder used by AUTO, never the answer toggle
                self.transcriber.set_language(self.cfg["general"].get("language", "auto"), self.stt_default_language(), source="profile")
            if patch.get("default_playbook"):
                try:
                    self.profiles.save_playbook(self.profile_name, {"text": self.bank_read("playbooks", patch["default_playbook"])})
                except Exception as exc:
                    await ws.send(json.dumps({"type": "error", "message": f"playbook not in bank: {exc}"}))
            self.context.load(force=True)
            self.broadcast_status()
        elif cmd == "bank_list":
            await ws.send(json.dumps({"type": "bank", **self.bank_list()}, ensure_ascii=False))
        elif cmd == "bank_save":
            sub, name = str(msg.get("sub")), str(msg.get("name") or "")
            if sub in ("roles", "cvs", "experience", "playbooks") and name:
                self.bank_save(sub, name, str(msg.get("text") or ""))
                await ws.send(json.dumps({"type": "bank", **self.bank_list()}, ensure_ascii=False))
        elif cmd == "bank_delete":
            sub, name = str(msg.get("sub")), Path(str(msg.get("name") or "")).name
            p = self.bank_dir / sub / name
            if sub in ("roles", "cvs", "experience", "playbooks") and p.exists() and name != "default_playbook.md":
                p.unlink()
            await ws.send(json.dumps({"type": "bank", **self.bank_list()}, ensure_ascii=False))
        elif cmd == "bank_attach":
            # Attach bank entries to a slot of the active profile as pasted text (role/profile: one; experience: many).
            sub, slot = str(msg.get("sub")), str(msg.get("slot"))
            names = [Path(str(n)).name for n in (msg.get("names") or [])]
            try:
                if slot in ("role", "profile"):
                    text = self.bank_read(sub, names[0]) if names else ""
                    self.context.set_manual(slot, text)
                elif slot == "experience":
                    parts = [f"## {Path(n).stem}\n\n{self.bank_read(sub, n).strip()}" for n in names]
                    self.context.set_manual("experience", "\n\n".join(parts))
                elif slot == "playbook":
                    text = self.bank_read("playbooks", names[0]) if names else ""
                    self.profiles.save_playbook(self.profile_name, {"text": text})
                    self.profiles.save_config(self.profile_name, {"default_playbook": names[0] if names else None})
                    self.context.load(force=True)
                await ws.send(json.dumps({"type": "bank_attached", "slot": slot, "names": names}))
            except Exception as exc:
                await ws.send(json.dumps({"type": "error", "message": f"bank attach failed: {exc}"}))
            self.broadcast_status()
        elif cmd == "archive_profile":
            name = sanitize_name(str(msg.get("name") or self.profile_name))
            try:
                if name == self.profile_name:
                    others = [p["name"] for p in self.profiles.list() if p["name"] != name]
                    if not others:
                        self.profiles.ensure("default")
                        others = ["default"]
                    self.set_profile(others[0])
                self.profiles.archive(name)
                await ws.send(json.dumps(self.profiles_payload(), ensure_ascii=False))
            except Exception as exc:
                await ws.send(json.dumps({"type": "error", "message": f"archive failed: {exc}"}))
            self.broadcast_status()
        elif cmd == "restore_profile":
            try:
                self.profiles.restore(str(msg.get("name") or ""))
                await ws.send(json.dumps(self.profiles_payload(), ensure_ascii=False))
            except Exception as exc:
                await ws.send(json.dumps({"type": "error", "message": f"restore failed: {exc}"}))
            self.broadcast_status()
        elif cmd == "set_manual_context":
            try:
                slot, text = str(msg.get("slot")), str(msg.get("text") or "")
                words = self.context.set_manual(slot, text)
                if words:  # every pasted entry is also saved in the bank
                    sub = {"role": "roles", "profile": "cvs", "experience": "experience"}[slot]
                    self.bank_save(sub, str(msg.get("bank_name") or f"{self.profile_name}_{slot}"), text)
                await ws.send(json.dumps({"type": "manual_saved", "slot": slot, "words": words}))
            except ValueError as exc:
                await ws.send(json.dumps({"type": "error", "message": str(exc)}))
            self.broadcast_status()
        elif cmd == "get_manual_context":
            await ws.send(json.dumps({"type": "manual_context", **self.context.get_manual()}, ensure_ascii=False))
        elif cmd == "set_language":
            lang = msg.get("value")
            if lang in ("en", "es", "auto"):
                self.apply_settings({"general": {"language": lang}})
        elif cmd == "set_playbook":
            pb = self.profiles.save_playbook(self.profile_name, {"text": msg.get("text", "")})
            if pb["text"].strip():
                pcfg = self.profiles.config(self.profile_name)
                bank_name = str(msg.get("bank_name") or pcfg.get("default_playbook") or f"{self.profile_name}_playbook")
                if Path(bank_name).name != "default_playbook.md":
                    self.bank_save("playbooks", bank_name, pb["text"])
                    self.profiles.save_config(self.profile_name, {"default_playbook": Path(self.bank_save("playbooks", bank_name, pb["text"])).name})
            self.context.load(force=True)
            self.broadcast_status()
            await ws.send(json.dumps({"type": "playbook_saved", "words": len(pb["text"].split())}))
        elif cmd == "followup":
            self.followup(str(msg.get("kind") or "tldr"))
        elif cmd == "vision":
            self.vision(str(msg.get("image_b64") or ""), str(msg.get("mime") or "image/jpeg"))
        elif cmd == "vision_buffer":
            self.set_vision_buffer(msg.get("image_b64"), msg.get("mime"), clear=bool(msg.get("clear")))
        elif cmd == "set_auto_vision":
            self.set_auto_vision(bool(msg.get("value", True)))
        elif cmd == "new_turn":
            self.reset_turn("manual")
        elif cmd == "set_input_mode":
            self.set_input_mode(str(msg.get("value") or "pc"))
        elif cmd == "toggle_input_mode":
            self.set_input_mode("pc" if self.input_mode == "external" else "external")
        elif cmd == "end_session":
            self.end_session(analyze=msg.get("analyze", True))
        elif cmd == "exit_session":
            self.end_session(analyze=False)
        elif cmd == "set_provider":
            self.set_provider(str(msg.get("provider") or ""), msg.get("api_key"), msg.get("model"), msg.get("base_url"))
        elif cmd == "provider_ok":
            self.clear_provider_error(str(msg.get("provider") or ""))
        elif cmd == "test_provider":
            self.test_provider(str(msg.get("provider") or ""))
        elif cmd == "list_models":
            name = str(msg.get("provider") or "")
            p = self.provider(name)
            def _lm():
                models = p.list_models() if p is not None and hasattr(p, "list_models") else []
                self.broadcast({"type": "provider_models", "provider": name, "models": models,
                                "error": None if models else (getattr(p, "last_error", None) or "no models returned (check the API key)")})
            threading.Thread(target=_lm, daemon=True).start()
        elif cmd == "list_gemini_models":
            def _models():
                models = self.gemini.list_models()
                if models:
                    self.cfg["llm"]["gemini_models"] = models
                self.broadcast({"type": "gemini_models", "models": models,
                                "error": None if models else "Gemini unavailable (set GEMINI_API_KEY)"})
            threading.Thread(target=_models, daemon=True).start()
        else:
            await ws.send(json.dumps({"type": "error", "message": f"unknown command: {cmd}"}))


# ---------------------------------------------------------------------- entrypoint

async def main_async(cfg: dict, audio_enabled: bool) -> None:
    import websockets

    loop = asyncio.get_running_loop()
    cp = Copilot(cfg, loop, audio_enabled)
    cp.start()
    host, port = cfg["backend"]["host"], int(cfg["backend"]["port"])
    async with websockets.serve(cp.handle_client, host, port, max_size=32 * 1024 * 1024, ping_interval=20):
        print(f"READY ws://{host}:{port}", flush=True)
        try:
            await asyncio.Future()
        finally:
            cp.stop()


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259                              # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _watch_parent(pid: int) -> None:
    """Exit when the app window that started this backend is gone, so a crashed/killed HUD never leaves an
    orphan holding the port (the next launch would then talk to a stale process)."""
    def run():
        while True:
            time.sleep(3)
            if not _pid_alive(pid):
                log.warning("parent process %d is gone - backend exiting", pid)
                os._exit(0)
    threading.Thread(target=run, name="parent-watch", daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser(description="Meeting Copilot backend")
    ap.add_argument("--parent-pid", type=int, default=0, help="exit when this process disappears")
    ap.add_argument("--config", default=None, help="path to config.json (default: ../config.json)")
    ap.add_argument("--list-devices", action="store_true", help="print audio devices and exit")
    ap.add_argument("--no-audio", action="store_true", help="run without audio capture (test with 'inject')")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stderr)
    if args.list_devices:
        print(list_devices())
        return
    cfg = load_config(args.config)
    if args.parent_pid:
        _watch_parent(args.parent_pid)
    try:
        asyncio.run(main_async(cfg, audio_enabled=not args.no_audio))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
