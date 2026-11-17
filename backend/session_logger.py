"""Structured session logging + post-session analysis (self-learning loop).

A session = everything that happens between the backend start (or a profile switch / 'End & Analyze')
and the next 'End & Analyze'. Entries are appended to
  profiles/<profile>/logs/session_YYYYMMDD_HHMM.json   (machine readable)
  profiles/<profile>/logs/session_YYYYMMDD_HHMM.md     (human readable)
as they happen, so a crash never loses the log. The analysis report is written next to them as
  session_YYYYMMDD_HHMM_report.md
and the extracted memory block is appended to profiles/<profile>/learned_memory.md.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("session")

ROLE_LABELS = {"them": "Remote", "me": "Me", "copilot": "Copilot", "vision": "Copilot Vision", "event": "Event"}


class SessionLogger:
    def __init__(self, profile_dir: Path, profile_name: str, session_focus: str = ""):
        self.profile_dir = Path(profile_dir)
        self.profile_name = profile_name
        self.session_focus = (session_focus or "").strip()
        self.logs_dir = self.profile_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.started = time.time()
        base = time.strftime("%Y%m%d_%H%M", time.localtime(self.started))
        self.stamp = base
        n = 2
        while (self.logs_dir / f"session_{self.stamp}.json").exists():  # two sessions in the same minute
            self.stamp = f"{base}_{n}"
            n += 1
        self.json_path = self.logs_dir / f"session_{self.stamp}.json"
        self.md_path = self.logs_dir / f"session_{self.stamp}.md"
        self.entries: list[dict] = []
        self._dirty = False
        self._files_created = False

    # ------------------------------------------------------------------ recording
    def _add(self, kind: str, text: str, **extra) -> None:
        entry = {"t": time.time(), "ts": time.strftime("%H:%M:%S"), "kind": kind, "text": text.strip(), **extra}
        with self._lock:
            self.entries.append(entry)
            self._dirty = True
        self._flush()

    def set_focus(self, focus: str) -> None:
        focus = (focus or "").strip()
        if focus != self.session_focus:
            self.session_focus = focus
            self._add("event", f"session focus set: {focus}" if focus else "session focus cleared")

    def transcript(self, channel: str, text: str) -> None:
        self._add("them" if channel == "them" else "me", text)

    def suggestion(self, text: str, mode: str, provider: str | None, question: str | None = None) -> None:
        if text.strip():
            self._add("copilot", text, mode=mode, provider=provider, question=question)

    def vision(self, text: str, provider: str | None) -> None:
        if text.strip():
            self._add("vision", text, provider=provider)

    def event(self, text: str) -> None:
        self._add("event", text)

    def count(self, kinds=("them", "me")) -> int:
        with self._lock:
            return sum(1 for e in self.entries if e["kind"] in kinds)

    def _flush(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            payload = {"profile": self.profile_name, "started": self.started, "session_focus": self.session_focus,
                       "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.started)),
                       "duration_s": int(self.entries[-1]["t"] - self.started) if self.entries else 0,
                       "entries": self.entries}
            try:
                self.logs_dir.mkdir(parents=True, exist_ok=True)
                tmp = self.json_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.json_path)
                self.md_path.write_text(self.to_markdown(), encoding="utf-8")
                self._files_created = True
            except Exception as exc:
                log.warning("could not write session log: %s", exc)
            self._dirty = False

    # ------------------------------------------------------------------ rendering
    def to_markdown(self, max_chars: int | None = None) -> str:
        lines = [f"# Session {self.stamp} — profile `{self.profile_name}`"]
        if self.session_focus:
            lines.append(f"**Enfoque de la sesión:** {self.session_focus}")
        lines.append("")
        for e in self.entries:
            label = ROLE_LABELS.get(e["kind"], e["kind"])
            if e["kind"] == "copilot":
                body = e["text"].replace("\n", "\n    ")
                lines.append(f"- {e['ts']} **[{label}]** ({e.get('mode')}/{e.get('provider')})\n    {body}")
            else:
                lines.append(f"- {e['ts']} **[{label}]** {e['text']}")
        text = "\n".join(lines) + "\n"
        if max_chars and len(text) > max_chars:
            text = "…(earlier part omitted)…\n" + text[-max_chars:]
        return text

    def transcript_only(self, max_chars: int = 60000) -> str:
        lines = [f"[{e['ts']}] {ROLE_LABELS[e['kind']]}: {e['text']}" for e in self.entries if e["kind"] in ("them", "me")]
        text = "\n".join(lines)
        return text[-max_chars:] if len(text) > max_chars else text

    def report_path(self) -> Path:
        return self.logs_dir / f"session_{self.stamp}_report.md"

    def analysis_path(self) -> Path:
        return self.logs_dir / f"session_{self.stamp}_analysis.json"

    def duration_s(self) -> int:
        with self._lock:
            if not self.entries:
                return 0
            return int(self.entries[-1]["t"] - self.started)

    def save_report(self, report: str, memory_block: str | None, analysis: dict | None = None) -> Path:
        """Always writes the markdown report; when the structured analysis parsed, also writes the JSON
        (with session metadata) so the dashboard can show the score without re-parsing markdown."""
        path = self.report_path()
        body = f"# Post-session analysis — {self.stamp} — profile `{self.profile_name}`\n\n{report.strip()}\n"
        if memory_block:
            body += f"\n\n---\n## Extracted memory (appended to learned_memory.md)\n\n{memory_block.strip()}\n"
        path.write_text(body, encoding="utf-8")
        if analysis is not None:
            meta = {"stamp": self.stamp, "profile": self.profile_name, "session_focus": self.session_focus,
                    "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.started)),
                    "duration_s": self.duration_s(), "turns": self.count(), "suggestions": self.count(("copilot", "vision")),
                    "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self.analysis_path().write_text(json.dumps({**meta, "analysis": analysis, "memory_block": memory_block or ""},
                                                       indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def has_files(self) -> bool:
        return self._files_created
