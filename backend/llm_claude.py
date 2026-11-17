"""Primary brain: Claude via the Claude Code CLI (`claude -p`) using the local
Claude Max login. Streams tokens with `--output-format stream-json`.

The entire prompt (format instructions + knowledge base + transcript) is written
to the CLI's stdin, so no long or multi-line text ever travels on the command
line (Windows `.cmd` shims and 32K command-line limits are both avoided).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from typing import Callable, Optional

log = logging.getLogger("claude")

TokenCallback = Callable[[str], None]


class ClaudeCLI:
    name = "claude"

    def __init__(self, cli: str = "claude", model: str = "", timeout_s: int = 60):
        self.cli = cli or "claude"
        self.model = (model or "").strip()
        self.timeout_s = int(timeout_s)
        self._resolved: Optional[str] = None
        # Working directory for `claude -p`: when set to a folder with a CLAUDE.md (a local Claude
        # project), the CLI loads that file's instructions automatically.
        self.cwd: Optional[str] = None
        self._pool: list[subprocess.Popen] = []
        self._warm_lock = threading.Lock()
        self.last_was_warm: Optional[bool] = None

    # -- discovery -------------------------------------------------------
    def resolve(self) -> Optional[str]:
        if self._resolved and os.path.exists(self._resolved):
            return self._resolved
        path = shutil.which(self.cli)
        if path is None and sys.platform.startswith("win"):
            for ext in (".cmd", ".exe", ".bat"):
                path = shutil.which(self.cli + ext)
                if path:
                    break
        if path is None and os.path.isabs(self.cli) and os.path.exists(self.cli):
            path = self.cli
        self._resolved = path
        return path

    def available(self) -> bool:
        return self.resolve() is not None

    def version(self) -> str:
        exe = self.resolve()
        if not exe:
            return "not found"
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                 timeout=20, env=self._env())
            return ((out.stdout or out.stderr).strip().splitlines() or ["?"])[0]
        except Exception as exc:
            return f"error: {exc}"

    # -- generation ------------------------------------------------------
    # -- warm session pool (eliminates the per-question Node cold start) ---------
    POOL_SIZE = 2

    def warm(self) -> None:
        """Keep POOL_SIZE long-lived `claude -p --input-format stream-json` processes ready. Answering is then
        one JSON line written to an already-running CLI; tokens start without any Node/auth start-up."""
        if not self.resolve():
            return
        with self._warm_lock:
            self._pool = [p for p in self._pool if p.poll() is None]
            need = self.POOL_SIZE - len(self._pool)
            spawn = []
            for _ in range(max(0, need)):
                p = self._spawn_warm()
                if p is not None:
                    self._pool.append(p)
                    spawn.append(p)
        for p in spawn:
            log.info("claude warm session started (pid %s, model %s)", p.pid, self.model or "default")

    def _spawn_warm(self) -> Optional[subprocess.Popen]:
        cmd = [self.resolve(), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--include-partial-messages", "--max-turns", "1"]
        if self.model:
            cmd += ["--model", self.model]
        cwd = self.cwd if self.cwd and os.path.isdir(self.cwd) else None
        try:
            return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                                    env=self._env(), cwd=cwd)
        except Exception as exc:
            log.warning("could not start warm claude session: %s", exc)
            return None

    def _take_warm(self) -> Optional[subprocess.Popen]:
        with self._warm_lock:
            while self._pool:
                p = self._pool.pop(0)
                if p.poll() is None:
                    return p
        return None

    def warm_count(self) -> int:
        with self._warm_lock:
            return sum(1 for p in self._pool if p.poll() is None)

    def reset_warm(self) -> None:
        """Kill pooled sessions (model / cwd changed) and start fresh ones."""
        with self._warm_lock:
            old, self._pool = self._pool, []
        for p in old:
            _kill(p)
        self.warm()

    def stream_vision(self, system_prompt: str, user_prompt: str, image_bytes: bytes, mime: str,
                      on_token: TokenCallback, cancel: threading.Event) -> str:
        """Vision via the CLI: the screenshot is written to a temp file and Claude reads it with its Read tool."""
        import tempfile

        ext = ".png" if "png" in (mime or "") else ".jpg"
        fd, path = tempfile.mkstemp(prefix="copilot_screen_", suffix=ext)
        with os.fdopen(fd, "wb") as fh:
            fh.write(image_bytes)
        try:
            prompt = (f"{user_prompt}\n\n<screenshot_file>{path}</screenshot_file>\n"
                      "First call the Read tool on the screenshot file path above to view the image, then answer.")
            return self.stream(system_prompt, prompt, on_token, cancel,
                               extra_args=["--allowedTools", "Read", "--max-turns", "3"], timeout_s=self.timeout_s + 30)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def stream(self, system_prompt: str, user_prompt: str, on_token: TokenCallback,
               cancel: threading.Event, extra_args: Optional[list] = None, timeout_s: Optional[int] = None) -> str:
        exe = self.resolve()
        if not exe:
            raise RuntimeError(f"Claude CLI '{self.cli}' not found on PATH")

        cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages"]
        cmd += extra_args if extra_args else ["--max-turns", "1"]
        if self.model:
            cmd += ["--model", self.model]
        timeout = int(timeout_s or self.timeout_s)
        cwd = self.cwd if self.cwd and os.path.isdir(self.cwd) else None

        full_prompt = f"<instructions>\n{system_prompt.strip()}\n</instructions>\n\n{user_prompt}"

        warm = self._take_warm() if not extra_args else None
        self.last_was_warm = warm is not None
        if warm is not None:
            proc = warm
            payload = json.dumps({"type": "user", "message": {"role": "user", "content": full_prompt}}) + "\n"
            log.debug("using warm claude session pid %s", proc.pid)
        else:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=self._env(),
                cwd=cwd,
            )
            payload = full_prompt
        # Pre-warm the next session while this answer streams (only for plain calls).
        if not extra_args:
            threading.Thread(target=self.warm, daemon=True).start()

        done = threading.Event()

        def watchdog():
            waited = 0.0
            while not done.is_set():
                if cancel.wait(0.1):
                    _kill(proc)
                    return
                waited += 0.1
                if waited >= timeout:
                    log.warning("claude timed out after %ss", timeout)
                    _kill(proc)
                    return

        threading.Thread(target=watchdog, daemon=True).start()

        # Feed stdin from a helper thread so a large prompt can't deadlock
        # against an un-drained stdout pipe.
        def feeder():
            try:
                assert proc.stdin is not None
                proc.stdin.write(payload)
                proc.stdin.flush()
                proc.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass

        threading.Thread(target=feeder, daemon=True).start()

        streamed: list[str] = []
        final_text: Optional[str] = None
        is_error = False
        err_msg = ""
        stderr_txt = ""
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                et = ev.get("type")
                if et == "stream_event":
                    inner = ev.get("event") or {}
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            streamed.append(delta["text"])
                            on_token(delta["text"])
                elif et == "assistant":
                    content = (ev.get("message") or {}).get("content") or []
                    texts = [c.get("text", "") for c in content
                             if isinstance(c, dict) and c.get("type") == "text"]
                    if texts:
                        final_text = "".join(texts)
                elif et == "result":
                    if ev.get("is_error"):
                        is_error = True
                        err_msg = str(ev.get("result") or ev.get("error") or "unknown error")
                    elif isinstance(ev.get("result"), str) and ev["result"].strip():
                        final_text = ev["result"]
        finally:
            done.set()
            try:
                stderr_txt = (proc.stderr.read() if proc.stderr else "") or ""
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                _kill(proc)

        if cancel.is_set():
            return "".join(streamed)
        if warm is not None and not streamed and not final_text and not is_error:
            log.warning("warm claude session produced no output (exit %s: %s) - retrying cold",
                        proc.returncode, stderr_txt.strip()[:160])
            self.last_was_warm = False
            return self.stream(system_prompt, user_prompt, on_token, cancel, extra_args=["--max-turns", "1"],
                               timeout_s=timeout_s)
        if is_error:
            raise RuntimeError(f"claude CLI error: {err_msg[:400]}")
        if proc.returncode not in (0, None) and not streamed and not final_text:
            raise RuntimeError(f"claude exited {proc.returncode}: {stderr_txt.strip()[:400]}")

        if streamed:
            return "".join(streamed)
        if final_text:
            on_token(final_text)  # older CLI without partial events: emit once
            return final_text
        return ""

    # -- internals -------------------------------------------------------
    @staticmethod
    def _env() -> dict:
        env = dict(os.environ)
        # `claude -p` refuses to start inside an active Claude Code session;
        # strip the markers in case the app was launched from one.
        for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
            env.pop(k, None)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
