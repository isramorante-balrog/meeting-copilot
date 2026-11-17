"""Profile-aware knowledge base loader.

Layout (one folder per profile, created/managed by electron/context_manager.js and this module):

  profiles/<name>/
    profile_config.json        {"name", "created", "claude_project": "<dir with CLAUDE.md>"|null,
                                "use_learned_memory": true, "language": "auto"|"en"|"es"|null}
    playbook.json              {"text": "...custom instructions...", "tone": "natural|executive|technical",
                                "length": "concise|medium|detailed"}
    manifest.json              file slots written by the HUD after parsing:
                               {"role": slot, "profile": slot, "experience": [slot...], "playbook": slot}
                               slot = {"file": "position_description/x.md", "source": "x.pdf", "words": 1450,
                                       "status": "ok"|"error", "error": "..."}
    position_description/      extracted text of the role description (single)
    professional_profile/      extracted text of the CV / profile (single)
    extra_experience/          one .md per supporting document
    playbook_files/            optional playbook guidelines file
    learned_memory.md          appended after every "End & Analyze" (self-referencing memory)
    logs/                      session_YYYYMMDD_HHMM.json / .md / _report.md

Everything is hot-reloaded when any file changes.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

from retrieval import BM25Index  # noqa: E402

log = logging.getLogger("context")

_EXTS = {".md", ".markdown", ".txt"}
TONES = ["natural", "executive", "technical"]
LENGTHS = ["concise", "medium", "detailed"]
SLOT_DIRS = {"role": "position_description", "profile": "professional_profile",
             "experience": "extra_experience", "playbook": "playbook_files"}


def _words(text: str) -> int:
    return len(text.split())


def _read_json(path: Path, default: dict) -> dict:
    try:
        return {**default, **json.loads(path.read_text(encoding="utf-8"))}
    except Exception:
        return dict(default)


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- profiles

class ProfileStore:
    """Enumerates profiles and owns profile_config.json / playbook.json / learned_memory.md writes."""

    DEFAULT_CONFIG = {"name": "", "created": "", "claude_project": None, "use_learned_memory": True,
                      "default_language": "en", "default_playbook": None, "job_role": "", "company": "",
                      "archived": False, "language": None}
    DEFAULT_PLAYBOOK = {"text": "", "tone": "natural", "length": "medium"}

    def __init__(self, root: Path, archive_root: Path | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.archive_root = Path(archive_root) if archive_root else self.root.parent / "profiles_archived"
        self.archive_root.mkdir(parents=True, exist_ok=True)

    def list(self, archived: bool = False) -> list[dict]:
        root = self.archive_root if archived else self.root
        out = []
        for p in sorted(root.iterdir()):
            if p.is_dir() and not p.name.startswith("."):
                cfg = _read_json(p / "profile_config.json", self.DEFAULT_CONFIG)
                out.append({"name": p.name, "created": cfg.get("created"), "archived": archived,
                            "claude_project": cfg.get("claude_project"),
                            "default_language": cfg.get("default_language") or "en",
                            "sessions": sum(1 for f in (p / "logs").glob("session_*.json")) if (p / "logs").exists() else 0})
        return out

    def dir_of(self, name: str, archived: bool = False) -> Path:
        return (self.archive_root if archived else self.root) / sanitize_name(name)

    def archive(self, name: str) -> Path:
        import shutil
        src, dst = self.root / sanitize_name(name), self.archive_root / sanitize_name(name)
        if not src.exists():
            raise FileNotFoundError(name)
        if dst.exists():
            dst = self.archive_root / f"{sanitize_name(name)}_{time.strftime('%Y%m%d_%H%M%S')}"
        shutil.move(str(src), str(dst))
        cfg = _read_json(dst / "profile_config.json", {**self.DEFAULT_CONFIG, "name": dst.name})
        cfg["archived"] = True
        cfg["archived_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _write_json(dst / "profile_config.json", cfg)
        return dst

    def restore(self, name: str) -> Path:
        import shutil
        src, dst = self.archive_root / sanitize_name(name), self.root / sanitize_name(name)
        if not src.exists():
            raise FileNotFoundError(name)
        if dst.exists():
            dst = self.root / f"{sanitize_name(name)}_restored"
        shutil.move(str(src), str(dst))
        cfg = _read_json(dst / "profile_config.json", {**self.DEFAULT_CONFIG, "name": dst.name})
        cfg["archived"] = False
        cfg.pop("archived_at", None)
        _write_json(dst / "profile_config.json", cfg)
        return dst

    def ensure(self, name: str) -> Path:
        name = sanitize_name(name)
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        for sub in list(SLOT_DIRS.values()) + ["logs"]:
            (d / sub).mkdir(exist_ok=True)
        cfg_path = d / "profile_config.json"
        if not cfg_path.exists():
            _write_json(cfg_path, {**self.DEFAULT_CONFIG, "name": name,
                                   "created": time.strftime("%Y-%m-%dT%H:%M:%S")})
        if not (d / "playbook.json").exists():
            _write_json(d / "playbook.json", dict(self.DEFAULT_PLAYBOOK))
        return d

    def config(self, name: str) -> dict:
        return _read_json(self.root / name / "profile_config.json", {**self.DEFAULT_CONFIG, "name": name})

    def save_config(self, name: str, patch: dict) -> dict:
        cfg = self.config(name)
        cfg.update({k: v for k, v in patch.items() if k in self.DEFAULT_CONFIG and k != "archived"})
        cfg["name"] = name
        _write_json(self.root / name / "profile_config.json", cfg)
        return cfg

    def playbook(self, name: str) -> dict:
        pb = _read_json(self.root / name / "playbook.json", self.DEFAULT_PLAYBOOK)
        if pb.get("tone") not in TONES:
            pb["tone"] = "natural"
        if pb.get("length") not in LENGTHS:
            pb["length"] = "medium"
        return pb

    def save_playbook(self, name: str, patch: dict) -> dict:
        pb = self.playbook(name)
        if "text" in patch:
            pb["text"] = str(patch["text"] or "").strip()
        if patch.get("tone") in TONES:
            pb["tone"] = patch["tone"]
        if patch.get("length") in LENGTHS:
            pb["length"] = patch["length"]
        _write_json(self.root / name / "playbook.json", pb)
        return pb

    def learned_memory_path(self, name: str) -> Path:
        return self.root / name / "learned_memory.md"

    def append_learned_memory(self, name: str, block: str, title: str) -> Path:
        path = self.learned_memory_path(name)
        header = "# Learned memory (auto-generated after each analyzed session)\n\n" if not path.exists() else ""
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{header}## {title}\n\n{block.strip()}\n\n")
        return path


def sanitize_name(name: str) -> str:
    name = re.sub(r"[^\w\- ]+", "", str(name or "")).strip().replace(" ", "_")
    return name[:60] or "default"


# --------------------------------------------------------------------------- context of one profile

class ContextStore:
    """Reads one profile folder into prompt sections; hot-reloads on change."""

    def __init__(self, directory: Path, max_chars: int = 180000, chunk_words: int = 300, top_chunks: int = 3):
        self.dir = Path(directory)
        self.max_chars = int(max_chars)
        self.chunk_words = int(chunk_words)
        self.top_chunks = int(top_chunks)
        self._index = BM25Index()
        self._lock = threading.Lock()
        self._mtimes: dict[str, float] = {}
        self._sections: dict = self._empty()
        self._summary: dict = {}
        self._truncated = False
        self._project_dir: Path | None = None

    @staticmethod
    def _empty() -> dict:
        return {"role": "", "profile": "", "experience": [], "playbook": "", "notes": [],
                "learned_memory": "", "project_instructions": "", "use_learned_memory": True}

    def _scan(self) -> dict[str, float]:
        found = {}
        if self.dir.exists():
            for p in sorted(self.dir.rglob("*")):
                if "logs" in p.relative_to(self.dir).parts:
                    continue
                if p.is_file() and not p.name.startswith(".") and (p.suffix.lower() in _EXTS or p.suffix == ".json"):
                    found[str(p)] = p.stat().st_mtime
        if self._project_dir:
            cm = self._project_dir / "CLAUDE.md"
            if cm.exists():
                found[str(cm)] = cm.stat().st_mtime
        return found

    @staticmethod
    def _read(path: Path) -> str:
        try:
            txt = path.read_text(encoding="utf-8", errors="replace")
            return re.sub(r"^<!--.*?-->\s*", "", txt, count=1, flags=re.S).strip()
        except Exception as exc:
            log.warning("Could not read %s: %s", path, exc)
            return ""

    def load(self, force: bool = False) -> bool:
        with self._lock:
            cfg = _read_json(self.dir / "profile_config.json", ProfileStore.DEFAULT_CONFIG)
            self._project_dir = Path(cfg["claude_project"]) if cfg.get("claude_project") else None
            current = self._scan()
            if not force and current == self._mtimes:
                return False
            self._mtimes = current

            manifest = _read_json(self.dir / "manifest.json", {"role": None, "profile": None, "experience": [], "playbook": None})
            playbook = _read_json(self.dir / "playbook.json", ProfileStore.DEFAULT_PLAYBOOK)
            sec = self._empty()

            def slot_text(slot) -> str:
                if not slot or slot.get("status") != "ok" or not slot.get("file"):
                    return ""
                return self._read(self.dir / slot["file"])

            manual = self.dir / "manual_context"
            def manual_text(name: str) -> str:
                f = manual / f"{name}.md"
                return self._read(f) if f.exists() else ""

            sec["role"] = manual_text("role") or slot_text(manifest.get("role"))
            sec["profile"] = manual_text("profile") or slot_text(manifest.get("profile"))
            for s in manifest.get("experience") or []:
                txt = slot_text(s)
                if txt:
                    sec["experience"].append((s.get("source") or Path(s["file"]).name, txt))
            exp_manual = manual_text("experience")
            if exp_manual:
                sec["experience"].append(("pasted notes", exp_manual))
            pb = [playbook.get("text", "").strip()] if playbook.get("text", "").strip() else []
            pb_file = slot_text(manifest.get("playbook"))
            if pb_file:
                pb.append(pb_file)
            sec["playbook"] = "\n\n".join(pb)
            sec["use_learned_memory"] = bool(cfg.get("use_learned_memory", True))
            lm = self.dir / "learned_memory.md"
            if lm.exists():
                sec["learned_memory"] = self._read(lm)
            if self._project_dir and (self._project_dir / "CLAUDE.md").exists():
                sec["project_instructions"] = self._read(self._project_dir / "CLAUDE.md")
            # Loose notes dropped by hand in the profile root.
            for path in sorted(current):
                p = Path(path)
                if p.parent == self.dir and p.suffix.lower() in _EXTS and p.name not in ("learned_memory.md", "README.md"):
                    txt = self._read(p)
                    if txt:
                        sec["notes"].append((p.name, txt))

            # ---- retrieval index over ALL experience + notes (full text, before any budget trimming)
            self._index.build(sec["experience"] + sec["notes"], self.chunk_words)

            # ---- budget: playbook, role, profile, project instructions, learned memory kept whole.
            fixed = sum(len(sec[k]) for k in ("playbook", "role", "profile", "project_instructions", "learned_memory"))
            budget = self.max_chars - fixed
            truncated = False
            kept = []
            for name, txt in sec["experience"] + sec["notes"]:
                if budget <= 400:
                    truncated = True
                    break
                if len(txt) > budget:
                    kept.append((name, txt[:budget] + "\n[…truncated]"))
                    budget = 0
                    truncated = True
                else:
                    kept.append((name, txt))
                    budget -= len(txt)
            n_exp = len(sec["experience"])
            sec["experience"], sec["notes"] = kept[:n_exp], kept[n_exp:]

            total = sum(_words(sec[k]) for k in ("role", "profile", "playbook", "learned_memory", "project_instructions"))
            total += sum(_words(t) for _, t in sec["experience"] + sec["notes"])
            self._summary = {
                "role": manifest.get("role"), "profile": manifest.get("profile"),
                "experience": manifest.get("experience") or [], "playbook": manifest.get("playbook"),
                "playbook_text": playbook.get("text", ""), "tone": playbook.get("tone"), "length": playbook.get("length"),
                "learned_memory_words": _words(sec["learned_memory"]), "use_learned_memory": sec["use_learned_memory"],
                "project_instructions_words": _words(sec["project_instructions"]),
                "claude_project": cfg.get("claude_project"),
                "notes": [{"source": n, "words": _words(t)} for n, t in sec["notes"]],
                "total_words": total, "total_chars": fixed + sum(len(t) for _, t in sec["experience"] + sec["notes"]),
                "max_chars": self.max_chars, "truncated": truncated,
                "chunks": self._index.size(), "chunk_words": self.chunk_words, "top_chunks": self.top_chunks,
                "manual": {k: _words(manual_text(k)) for k in ("role", "profile", "experience")},
            }
            self._sections = sec
            self._truncated = truncated
            log.info("Context [%s]: role=%d profile=%d exp=%d playbook=%d memory=%d words%s", self.dir.name,
                     _words(sec["role"]), _words(sec["profile"]), sum(_words(t) for _, t in sec["experience"]),
                     _words(sec["playbook"]), _words(sec["learned_memory"]), " (truncated)" if truncated else "")
            return True

    def sections(self) -> dict:
        self.load()
        with self._lock:
            return dict(self._sections)

    def set_manual(self, slot: str, text: str) -> int:
        """Persist pasted plain text for a slot into manual_context/<slot>.md (empty text deletes it)."""
        if slot not in ("role", "profile", "experience"):
            raise ValueError("bad slot")
        d = self.dir / "manual_context"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{slot}.md"
        text = (text or "").strip()
        if text:
            f.write_text(text + "\n", encoding="utf-8")
        elif f.exists():
            f.unlink()
        self.load(force=True)
        return _words(text)

    def get_manual(self) -> dict:
        d = self.dir / "manual_context"
        out = {}
        for k in ("role", "profile", "experience"):
            f = d / f"{k}.md"
            out[k] = f.read_text(encoding="utf-8") if f.exists() else ""
        return out

    def sections_for(self, query: str | None, boost: str | None = None, avoid: str | None = None) -> dict:
        """Prompt sections with the supporting experience reduced to the top-k BM25 chunks for this query.
        Role, profile, playbook, learned memory and project instructions are always sent whole."""
        sec = self.sections()
        if not query or not query.strip():
            sec["experience"], sec["notes"] = [], []
            sec["retrieval"] = []
            return sec
        hits = self._index.search(query, k=self.top_chunks, boost=boost, avoid=avoid or None)
        sec["experience"] = [(f"{h['name']} · part {h['chunk'] + 1}", h["text"]) for h in hits]
        sec["notes"] = []
        sec["retrieval"] = [{"name": h["name"], "chunk": h["chunk"], "score": h["score"]} for h in hits]
        return sec

    def summary(self) -> dict:
        self.load()
        with self._lock:
            return dict(self._summary)

    def files(self) -> list[str]:
        s = self.summary()
        names = [f"{k}: {s[k].get('source')}" for k in ("role", "profile", "playbook") if s.get(k) and s[k].get("status") == "ok"]
        names += [f"experience: {e.get('source')}" for e in s.get("experience", []) if e.get("status") == "ok"]
        names += [f"notes: {n['source']}" for n in s.get("notes", [])]
        if s.get("learned_memory_words"):
            names.append(f"learned memory: {s['learned_memory_words']} words")
        if s.get("project_instructions_words"):
            names.append("CLAUDE.md: project instructions")
        return names

    def truncated(self) -> bool:
        with self._lock:
            return self._truncated
