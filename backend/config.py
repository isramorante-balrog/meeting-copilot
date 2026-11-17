"""Configuration loading for the Meeting Copilot backend.

Reads config.json from the project root and merges it over built-in defaults,
so a partial config.json is always valid.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "backend": {"host": "127.0.0.1", "port": 8765, "python": ""},
    "hud": {"width": 520, "height": 380, "max_width": 520, "top": 6, "opacity": 0.75, "font_size": 17, "setup_width": 1040, "setup_height": 720,
            "nudge_px": 40, "auto_vision": False, "auto_vision_interval_s": 5},
    "general": {"language": "auto", "primary": "claude", "ui_language": "es", "active_profile": "default",
                "onboarded": False},   # False -> the first-run wizard (AI provider + transcription keys) opens
    # Auto-updater (electron/updater.js): checks GitHub for a newer release and installs it when idle.
    "updates": {"enabled": True, "auto_install": True, "repo": "isramorante-balrog/meeting-copilot", "check_hours": 6},
    "hotkeys": {
        "screenshot": "Alt+S", "force_answer": "Alt+A", "toggle_visibility": "Alt+H", "toggle_listening": "Alt+M",
        "followup_example": "Alt+1", "followup_deepen": "Alt+2", "followup_tldr": "Alt+3", "followup_pivot": "Alt+4",
        "ghost": "Alt+G", "auto_vision": "Alt+V", "new_turn": "Alt+N", "input_mode": "Alt+P",
        "nudge_up": "Alt+Shift+Up", "nudge_down": "Alt+Shift+Down", "nudge_left": "Alt+Shift+Left", "nudge_right": "Alt+Shift+Right",
        "scroll_up": "Alt+Up", "scroll_down": "Alt+Down", "opacity_down": "Alt+[", "opacity_up": "Alt+]",
        "end_session": "Alt+E", "summarize": "Alt+U", "clear": "Alt+X", "toggle_language": "Alt+L",
        "settings": "Alt+T", "quit": "Alt+Q",
    },
    "audio": {
        "enabled": True,
        "mic_device": "default",
        "loopback_device": "default",
        "input_mode": "pc",                 # v17: "pc" = loopback is the remote voice | "external" = the laptop MIC is (phone on speaker)
        "vad_aggressiveness": 2,
        "end_silence_ms": 600,              # pause that ends a turn (utterance engines: local Whisper / Groq)
        "end_silence_incomplete_ms": 900,   # longer pause allowed when the sentence still reads unfinished
        "min_speech_ms": 350,
        "max_utterance_s": 30,              # safety ceiling only - v13 never slices speech into short chunks
        "energy_threshold": 0.015,
        "levels_hz": 10,
    },
    "stt": {
        # engine: "deepgram" (Nova-3 streaming, recommended) | "whisper_local" (faster-whisper + Silero VAD)
        #         | "groq_whisper" (whisper-large-v3-turbo on Groq). Switchable live from the Audio tab.
        "engine": "deepgram",
        "deepgram_api_key": "",             # paste in the Audio tab (stored here, locally) or set DEEPGRAM_API_KEY
        "deepgram_model": "nova-3",
        "deepgram_endpointing_ms": 750,     # v19: dual pre-warmed native sockets (es-419 + en-US), 0 ms switch, no reconnects
        "deepgram_utterance_end_ms": 1100,
        "force_language": None,             # local Whisper / Groq: pin the decoder to "en"|"es" regardless of the HUD toggle
        "groq_api_key": "",                 # or set GROQ_API_KEY
        "groq_model": "whisper-large-v3-turbo",
        "model_size": "small",              # local faster-whisper: base | small (medium/large need a GPU)
        "device": "auto",
        "compute_type": "default",          # cuda -> float16, cpu -> int8
        "language": None,                   # (legacy, ignored since v18 - see force_language)
        "beam_size": 1,
        "whisper_prompt": "",               # extra initial_prompt text (the IAM vocabulary prompt is built in)
        "vocabulary": [],                   # extra keyterms (comma list in the UI) on top of the built-in IAM list
        "max_keyterms": 60,
    },
    "llm": {
        "claude_cli": "claude",
        "claude_model": "claude-sonnet-5-5",
        "claude_models": ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5",
                          "claude-haiku-5-5", "opus", "sonnet", "haiku"],
        "claude_timeout_s": 60,
        "gemini_api_key_env": "GEMINI_API_KEY",
        "gemini_api_key": "",             # entered in the first-run wizard (or use the GEMINI_API_KEY env var)
        # OpenAI-compatible providers (ChatGPT, Grok, DeepSeek). Keys are entered in the wizard / Setup and stay
        # in this local file; the matching env var (OPENAI_API_KEY, XAI_API_KEY, DEEPSEEK_API_KEY) also works.
        "providers": {
            "openai": {"api_key": "", "model": "gpt-4o-mini", "base_url": ""},
            "xai": {"api_key": "", "model": "grok-3-mini", "base_url": ""},
            "deepseek": {"api_key": "", "model": "deepseek-chat", "base_url": ""},
        },
        "gemini_model": "gemini-2.5-flash",
        "gemini_models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
        "gemini_classifier": False,
        "auto_answer": True,
        "transcript_window": 10,
        "max_answer_words": 110,
        "auto_vision": False,             # v15: attach the HUD's buffered screen frame to answers (toggle 👁 / Alt+V)
        "auto_vision_always": False,      # False = only when the question refers to the screen ("this diagram", "on the screen"…)
        "auto_vision_max_age_s": 20,
        "language_flip_rescue_s": 15,     # v18: flipping EN/ES within this many seconds of the last question re-answers it in place
        # v16 same-speaker turn accumulation: consecutive remote segments are ONE turn until the user answers
        "turn_fast_hold_ms": 0,           # v19: ?/¿ or a conversational prompt cue (platícame, cuéntame, how did you…): ~650 ms total with the STT pause
        "turn_setup_hold_ms": 100,        # v19: any other 3+-word utterance: ~800 ms total pause, then answer - never longer
        "turn_continue_hold_ms": 2500,    # speaker resumed mid-answer: wait this long for the new sentence before re-answering the old text
        "turn_answered_stale_s": 12,      # a new sentence this long after a finished answer starts a new card instead of rewriting it
        "turn_watchdog_s": 2.5,           # safety net: a pending turn with 4+ words is always answered within this time
        "turn_me_words_reset": 4,         # the user has answered once their mic produced this many words
        "turn_max_gap_s": 25,             # remote silence after which the next segment is a new turn anyway
        "turn_max_gap_no_mic_s": 8,       # ...shorter when no microphone is configured (nothing can end a turn otherwise)
        "turn_max_words": 400,            # oldest segments are dropped beyond this (the transcript still has them)
        "fast_opener": True,
        "fast_provider": "auto",
        "fast_claude_model": "claude-haiku-5-5",
        "fast_gemini_model": "gemini-2.5-flash",
        "speculate": False,              # 1.0: off by default - drafting before the speaker finishes saved ~0.3 s but showed stale openers
        "speculate_min_words": 8,
        "speculate_min_overlap": 0.7,
    },
    "style": {"tone": "natural", "length": "medium"},
    "context": {"max_chars": 180000, "profiles_dir": "profiles", "chunk_words": 300, "top_chunks": 3},
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None) -> dict:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    user_cfg: dict = {}
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as fh:
            user_cfg = json.load(fh)
    cfg = deep_merge(DEFAULTS, user_cfg)
    _migrate(cfg)
    cfg["_config_path"] = str(cfg_path)
    return cfg


CONFIG_VERSION = 100   # 1.0.0


def _migrate(cfg: dict) -> None:
    """One-time upgrade of a config.json written by a pre-1.0 build. Runs once (config_version is then stored),
    so values the user tunes afterwards are never reverted on the next start."""
    if int(cfg.get("config_version") or 0) >= CONFIG_VERSION:
        return
    cfg["config_version"] = CONFIG_VERSION
    cfg.setdefault("llm", {})["speculate"] = False
    cfg["llm"]["turn_setup_hold_ms"] = 100
    cfg["llm"].pop("turn_question_hold_ms", None)
    a = cfg.get("audio") or {}
    a.pop("chunk_s", None)
    try:
        if float(a.get("max_utterance_s", 30)) < 5:
            a["max_utterance_s"] = 30
    except (TypeError, ValueError):
        a["max_utterance_s"] = 30
    try:
        if int(a.get("end_silence_ms", 600)) < 500:
            a["end_silence_ms"] = 600
        if int(a.get("end_silence_incomplete_ms", 900)) < 800:
            a["end_silence_incomplete_ms"] = 900
    except (TypeError, ValueError):
        pass
    hk = cfg.setdefault("hotkeys", {})
    if hk.get("settings") == "Alt+G" and hk.get("ghost", "Alt+G") == "Alt+G":   # v15 moved Setup⇄Live to Alt+T, Alt+G = ghost
        hk["settings"] = "Alt+T"
    stt = cfg.setdefault("stt", {})
    try:
        if int(stt.get("deepgram_endpointing_ms", 750)) != 750 and int(stt.get("deepgram_endpointing_ms", 750)) in (500, 800, 900):
            stt["deepgram_endpointing_ms"] = 750          # older versions wrote 500/800/900
        if int(stt.get("deepgram_utterance_end_ms", 1100)) in (1000, 1200, 1300):
            stt["deepgram_utterance_end_ms"] = 1100
        stt.pop("deepgram_language", None)              # v18 "multi" is gone
        stt["language"] = None                      # v18: STT never follows the answer-language toggle
    except (TypeError, ValueError):
        pass
    if stt.get("engine") not in ("deepgram", "whisper_local", "groq_whisper"):
        # existing installs without a Deepgram key keep working on the improved local engine
        stt["engine"] = "deepgram" if (stt.get("deepgram_api_key") or os.environ.get("DEEPGRAM_API_KEY")) else "whisper_local"


def profiles_dir(cfg: dict) -> Path:
    raw = Path(cfg["context"].get("profiles_dir", "profiles"))
    return raw if raw.is_absolute() else (ROOT_DIR / raw)


def context_dir(cfg: dict) -> Path:
    """Directory of the active profile."""
    return profiles_dir(cfg) / (cfg["general"].get("active_profile") or "default")


ELECTRON_OWNED = ("hud", "updates")


def save_config(cfg: dict) -> Path:
    """Persist the live config back to config.json (private keys stripped)."""
    path = Path(cfg.get("_config_path") or DEFAULT_CONFIG_PATH)
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    # The Electron side owns `hud` and `updates` and writes them to the same file (window position, opacity,
    # font size, updater settings). Keep whatever is on disk for those sections instead of clobbering them
    # with the copy this process loaded at startup.
    try:
        with open(path, "r", encoding="utf-8") as fh:
            disk = json.load(fh)
        for section in ELECTRON_OWNED:
            if isinstance(disk.get(section), dict):
                clean[section] = disk[section]
                cfg[section] = disk[section]
    except (OSError, ValueError):
        pass
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)
    return path
