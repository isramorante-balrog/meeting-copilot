# Manual

## Profiles, session logs & self-learning (v4)

### Profiles (`profiles/<name>/`)
The top-left dropdown switches the active profile; the ▾ menu creates, duplicates (files copied, logs/memory not),
renames and deletes profiles. Each profile folder holds `profile_config.json` (Claude project, memory toggle),
`playbook.json` (custom instructions + tone/length quick-toggles), `manifest.json`, `position_description/`,
`professional_profile/`, `extra_experience/`, `playbook_files/`, `learned_memory.md` and `logs/`. The first run
migrates an existing flat `context/` into `profiles/default/`. Switching profiles swaps the knowledge base,
playbook, tone/length and starts a new session log.

**Local Claude project**: in ⚙ Settings pick one of your `~/.claude/projects` folders (or any folder with a
`CLAUDE.md`). `claude -p` then runs with that folder as its working directory, so the CLI loads the CLAUDE.md
itself, and the same text is injected as `<project_instructions>` for Gemini.

### Session logs & "End & Analyze"
Everything is logged live to `profiles/<name>/logs/session_YYYYMMDD_HHMM.json` + `.md`:
`[Remote Speaker]`, `[User Mic]`, `[Copilot Suggestion]`, `[Copilot Vision]`. **■ End & Analyze**
(`Ctrl/⌘+Shift+Enter`, tray menu) sends the whole log plus the role description and profile to Claude (Gemini
fallback) and streams a *Post-Session Insights* report into the HUD: communication / technical-accuracy /
role-fit scores, missed or weak answers with stronger model answers, pacing-clarity-structure feedback, top 3
adjustments. It is saved as `session_…_report.md`; a second, short call extracts **Key facts established /
Questions asked / Actionable adjustments** and appends it to `learned_memory.md`, which is injected as
`<learned_memory>` into every future answer under that profile (toggle in ⚙ Settings). A fresh session starts
automatically afterwards.

### 1-click screen context (`Ctrl/⌘+Shift+S`, 📷 button)
Grabs the display under the cursor via `desktopCapturer` (JPEG, ≤1600 px), sends it to the backend over the
WebSocket, and Claude (via the CLI's `Read` tool on the temp image) or Gemini Vision explains the slide /
diagram / table / error with the transcript and your profile as context: *On screen · Key points · Likely
question · Say next · Watch out*. The HUD itself is content-protected, so it never appears in the capture.

### Hands-free follow-ups on the last answer
| Hotkey | Chip | Effect |
|--------|------|--------|
| `Alt+1` | Example | one concrete project / metric from your profile or experience files that proves the point |
| `Alt+2` | Deepen | adds architecture / implementation depth under each bullet |
| `Alt+3` | TL;DR | three ultra-short spoken sentences |

`Ctrl/⌘+Space` (and `Ctrl/⌘+Shift+Space`) = **Force Answer Now**: flushes the utterance in progress and answers
even if the silence detector or classifier did not fire. Summary moved to `Ctrl/⌘+Shift+M`.

## Audio: making sure the app actually hears the call

The **SYS** (system audio = them) and **MIC** (me) meters in the style strip move in real time. If a meter stays
flat while sound is playing, the app is not receiving that channel — fix it in ⚙ Settings → *Audio inputs*:

| Source option | How it captures | When to use |
|---------------|-----------------|-------------|
| **Default device** | Windows: WASAPI loopback of the *current default playback device* (`pyaudiowpatch`). macOS/Linux: auto-detects BlackHole / "monitor" input. | first thing to try |
| **`[Loopback]` device list** (Windows) | WASAPI loopback of a specific playback device, e.g. the headset Zoom plays through | when your meeting app plays through a non-default device |
| **System audio via Electron** (Windows) | Electron `desktopCapturer` + `getDisplayMedia({audio})` loopback inside the HUD; PCM is streamed to the backend over the WebSocket | if the Python/WASAPI path fails or you want zero native audio deps on the Python side |
| **Microphone list / Microphone via Electron** | PortAudio input, or `getUserMedia` inside the HUD | pick the headset mic explicitly |

Checklist when SYS is flat on Windows: (1) the meeting app must be playing to the *same* device you selected
(Settings → Sound → Output); (2) if you change the default playback device mid-call the capture restarts
itself within ~3 s; (3) Exclusive-mode apps block loopback — turn off "Allow applications to take exclusive
control" on the playback device. On macOS, system audio needs BlackHole + a Multi-Output Device; Electron
loopback is Windows-only.

**Push to Answer** (`▶` button or `Ctrl/⌘+Shift+Space`) force-ends the utterance in progress, transcribes it,
and generates immediately — use it when the silence detector hasn't triggered yet.

## Context & Playbook (📄 button, tray menu)

Four slots, each parsed the moment you pick a file (PDF via `pdf-parse`, DOCX via `mammoth`, TXT/MD as UTF-8)
and stored as extracted text under `context/0N_<slot>/` with a manifest. The status badge shows
*Loaded: N words*; a scanned/image-only PDF, a password-protected or corrupted file is rejected with an alert.

| Slot | Files | Goes into the prompt as |
|------|-------|-------------------------|
| 1 · Position / Role Description | single | `<role_description>` — what the audience expects; answers are mapped to it |
| 2 · Professional Profile | single | `<professional_profile>` — your background and voice |
| 3 · Supporting Experience & Projects | multiple | `<supporting_experience>` with one `<document name=…>` per file |
| 4 · Response Playbook | text area + optional file | appended to the **system prompt** as rules that override the default framing |

Loose `.md`/`.txt` files dropped in `context/` still load (as `<notes>`), so the old folder workflow keeps working.

### Live style controls (strip under the top bar)
- **Tone**: Natural (spoken, non-robotic) · Executive (bottom line + numbers) · Technical (components, protocols, trade-offs). Hotkey `Ctrl/⌘+Shift+T` cycles.
- **Length**: Concise (Q + 3 bullets, ≤55 words) · Medium (Q / Situation / Action / Impact / Say next / Watch out) · Detailed (adds sub-steps and trade-offs, ≤220 words). Hotkey `Ctrl/⌘+Shift+D` cycles.
Both apply to the next answer immediately and are saved to `config.json → style`.

## Settings (⚙ in the HUD, tray menu, or `Ctrl/⌘+Shift+,`)

Everything below is applied **live** (no restart) and saved to `config.json`:

| Setting | Options | Effect |
|---------|---------|--------|
| Answer & transcription language | Auto / Español / English | Auto follows whoever is speaking. ES/EN forces Whisper's language *and* the answer language, even if the question is in the other language. **`Ctrl/⌘+Shift+E` cycles Auto → ES → EN on the fly**; the `AUTO/ES/EN` pill shows the current mode. |
| Interface language | Same as above / Español / English | Labels, buttons, hints |
| Primary brain | Claude / Gemini | Which provider answers first; the other is the fallback |
| Claude model | `claude-fable-5-1`, `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `opus`/`sonnet`/`haiku`, or a custom id | passed as `claude --model …`. Fable/Mythos-tier models only work if your Claude plan has access; the HUD shows the CLI error if not. |
| Gemini model | `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.5-flash-lite`, … or custom; **↻** queries the API for the models your key can use | used for fallback, summaries, optional classifier |
| Auto-answer | On / Off | Off = cards only on `Ctrl/⌘+Shift+Space` |
| Max words per card | 40–300 | card length |
| HUD opacity | 40–100 % | |

## Project structure

```
meeting-copilot/
├─ Meeting Copilot.cmd          # Windows double-click launcher (self-installing)
├─ Meeting Copilot.command      # macOS/Linux double-click launcher (self-installing)
├─ config.json                  # all tunables (ports, hotkeys, audio, STT, LLM, language, context)
├─ package.json                 # Electron + ws
├─ electron/
│  ├─ main.js                   # HUD window, setContentProtection, hotkeys, backend spawn, WS relay, loopback handler
│  ├─ context_manager.js        # ProfileManager: profiles CRUD, slots, sessions listing, Claude-project discovery
│  ├─ parse_worker.js           # worker thread: pdf-parse / mammoth / text extraction off the UI thread
│  ├─ preload.js                # contextBridge: window.copilot.onEvent / send / sendAudio / context.*
│  └─ renderer/
│     ├─ index.html             # HUD layout
│     ├─ styles.css             # semi-transparent dark HUD
│     ├─ renderer.js            # streaming cards, meters, style strip, settings & context panels
│     ├─ capture.js             # Electron-side system-audio/mic capture (getDisplayMedia / getUserMedia)
│     └─ pcm-worklet.js         # AudioWorklet: mono, 16 kHz, int16 chunks + RMS
├─ backend/
│  ├─ server.py                 # orchestrator + WebSocket server (entrypoint)
│  ├─ audio_capture.py          # mic + WASAPI/PortAudio loopback capture with auto-retry, VAD segmenter
│  ├─ transcriber.py            # faster-whisper wrapper
│  ├─ classifier.py             # zero-latency EN/ES "does this need an answer?" heuristic
│  ├─ context_loader.py         # ProfileStore + ContextStore (slots, playbook.json, learned_memory, CLAUDE.md, BM25 retrieval)
│  ├─ retrieval.py              # ~300-word chunker + BM25 index (local, <1 ms per query)
│  ├─ session_logger.py         # live session .json/.md logs, report + memory extraction output
│  ├─ prompts.py                # system prompt + prompt builders (SAI format)
│  ├─ llm_claude.py             # `claude -p` stream-json streaming (primary brain)
│  ├─ llm_gemini.py             # Gemini fallback / summaries / optional classifier
│  ├─ config.py                 # config.json loader with defaults
│  ├─ requirements.txt
│  └─ tools/ws_probe.py         # pipeline probe: inject text, watch tokens stream (no audio needed)
├─ profiles/<name>/             # one folder per profile (see "Profiles" above); created at runtime
├─ context/                     # legacy flat knowledge base — migrated into profiles/default on first run
├─ scripts/
│  ├─ bootstrap.ps1             # Windows installer/launcher (PowerShell 5.1 or 7)
│  ├─ bootstrap.sh              # macOS/Linux installer/launcher
│  ├─ setup.ps1                 # manual setup (pwsh 7), used by the runbook
│  └─ start.ps1                 # manual launch
├─ logs/copilot.log             # created at runtime
└─ .copilot/                    # bootstrap markers (installed hashes, login check)
```

## Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| Node.js | 20+ | Electron 33; npm deps: `ws`, `pdf-parse` (v2), `mammoth` |
| Python | 3.10 – 3.12 | faster-whisper / CTranslate2 wheels |
| PowerShell | 7+ (`pwsh`) | for the runbook scripts; plain `python`/`npm` work too |
| Claude Code CLI | current | `npm i -g @anthropic-ai/claude-code`, then `claude` once to log in with your **Max** account |
| Gemini API key | optional | free tier at https://aistudio.google.com/apikey → env `GEMINI_API_KEY` |
| Headphones | strongly recommended | otherwise the mic hears the speakers and "ME" gets polluted with "THEM" |
| macOS only | BlackHole 2ch | virtual audio device; route Zoom/Teams output through a Multi-Output Device |

> Recording/transcribing a call may require participant consent depending on jurisdiction and company
> policy. The transcript never leaves your machine except the prompt sent to Claude/Gemini.

---

# OPERATIONAL RUNBOOK (manual path — the double-click launcher does all of this for you)

Execution order: **Phase 1 Setup → Phase 2 Claude auth check → Phase 3 Audio devices → Phase 4 Backend
dry-run (no audio) → Phase 5 Knowledge base → Phase 6 Live HUD → Phase 7 Tuning.** Each phase ends with a
*STOP & VERIFY* checkpoint; do not continue until it passes.

## Phase 1 — Setup

```pwsh
cd <path>\meeting-copilot
pwsh .\scripts\setup.ps1
# options:
#   -Python python3.12   interpreter used to create backend\.venv
#   -SkipNode            skip npm install
#   -Cuda                also install nvidia-cublas-cu12 / nvidia-cudnn-cu12 (NVIDIA GPU)
```

Parameters
- `-Python` — which interpreter builds the venv. Default `python` (Windows) / `python3` (others).
- `-SkipNode` — reuse an existing `node_modules`.
- `-Cuda` — pulls CUDA 12 runtime wheels so `stt.device = "cuda"` works without a system CUDA install.

Expected output (abridged)
```
==> Checking prerequisites
    OK  node v20.x
    OK  python 3.12 (C:\...\python.exe)
    OK  claude CLI: 1.x.y (Claude Code)
    OK  GEMINI_API_KEY is set (fallback brain enabled)      <- or a "!!" warning if not set
==> Installing Python requirements
    ... Successfully installed faster-whisper-1.x ctranslate2-4.x websockets-1x sounddevice-0.x webrtcvad-wheels-2.x google-genai-1.x pyaudiowpatch-0.2.x
==> Installing npm dependencies (electron, ws)
    added 9x packages
==> Done
```

**STOP & VERIFY:** `backend\.venv` exists and `node_modules\electron` exists. If `claude CLI not on PATH`
was printed, install it and log in before Phase 2.

## Phase 2 — Claude Max authentication & streaming check

```pwsh
Remove-Item Env:CLAUDECODE -ErrorAction SilentlyContinue   # must not run inside an active Claude Code session
claude -p "Reply with exactly: OK" --output-format stream-json --verbose --include-partial-messages --max-turns 1
```

Parameters: `-p` print/non-interactive mode · `--output-format stream-json` newline-delimited JSON events ·
`--include-partial-messages` emits `content_block_delta` token events (what the HUD streams) ·
`--max-turns 1` no tool loops.

Expected output — JSON lines including (shape, not verbatim):
```
{"type":"system","subtype":"init",...}
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"OK"}}}
{"type":"assistant","message":{"content":[{"type":"text","text":"OK"}],...}}
{"type":"result","subtype":"success","is_error":false,"result":"OK",...}
```

**STOP & VERIFY:** you see `"type":"stream_event"` lines and a final `"is_error":false`. If you get a login
prompt or `Not logged in`, run `claude` interactively and sign in with the Max account. If you see
*"cannot be launched inside Claude Code"*, open a fresh terminal (the app strips `CLAUDECODE` itself, but
this manual check must run outside it).

Optional Gemini check:
```pwsh
$env:GEMINI_API_KEY = "<your key>"        # persist with: [Environment]::SetEnvironmentVariable("GEMINI_API_KEY","<key>","User")
.\backend\.venv\Scripts\python.exe -c "from google import genai; import os; c=genai.Client(api_key=os.environ['GEMINI_API_KEY']); print(c.models.generate_content(model='gemini-2.5-flash', contents='say OK').text)"
```
Expected: `OK`.

## Phase 3 — Audio devices

```pwsh
.\backend\.venv\Scripts\python.exe .\backend\server.py --list-devices
```

Expected output (Windows example)
```
== PortAudio devices (sounddevice) ==
  [1] Microphone (Jabra Evolve2)  (in:1, 48000 Hz)
  [4] Speakers (Jabra Evolve2)    (out:2, 48000 Hz)
  default input : Microphone (Jabra Evolve2)
  default output: Speakers (Jabra Evolve2)
== WASAPI loopback devices (pyaudiowpatch) ==
  [12] Speakers (Jabra Evolve2) [Loopback]  (48000 Hz, 2 ch)
  default output: Speakers (Jabra Evolve2)
```

Set devices in `config.json` → `audio`:
- `mic_device`: `null` = default input; or a name substring (`"Jabra"`) or index.
- `loopback_device`: `null` = loopback of the default output (Windows) / auto-detect BlackHole|monitor (mac/Linux);
  or a name substring / index from the loopback list.
- `vad_aggressiveness` 0–3 (3 = strictest, fewer false starts), `end_silence_ms` (how long a pause ends an
  utterance; 700 ms default), `min_speech_ms` (ignore blips), `max_utterance_s` (hard cut for long monologues).

**STOP & VERIFY:** the device Zoom/Teams *plays through* appears in the loopback list, and your headset mic
appears as an input. On macOS confirm `BlackHole 2ch` is listed and that Zoom/Teams output is set to the
Multi-Output Device that includes it.

## Phase 4 — Backend dry-run (no audio) + pipeline probe

Terminal A:
```pwsh
.\backend\.venv\Scripts\python.exe .\backend\server.py --no-audio
```
Parameters: `--no-audio` skip capture threads · `--config <path>` alternate config · `--log-level DEBUG`.

Expected (stderr log + stdout READY line):
```
10:06:02 INFO  context: Context loaded: 3 file(s), 2910 chars
10:06:02 INFO  server: Claude CLI: 1.x.y (Claude Code)
10:06:02 INFO  server: Gemini: configured
10:06:02 INFO  stt: Loading faster-whisper model 'small' (device=auto, compute=default)…   <- first run downloads ~460 MB
READY ws://127.0.0.1:8765
10:06:20 INFO  stt: faster-whisper ready
```

Terminal B — inject a "THEM" question and watch Claude stream:
```pwsh
.\backend\.venv\Scripts\python.exe .\backend\tools\ws_probe.py "Can you walk us through how you sequenced the AD trust teardown?"
```
Parameters: positional text = utterance · `--channel them|me` · `--summarize` (Gemini-first summary) ·
`--status` (print status and exit) · `--no-generate` · `--timeout 90`.

Expected
```
connecting to ws://127.0.0.1:8765 …
STATUS: {"listening": true, "audio_enabled": false, "stt_ready": true, "providers": {"claude": true, "gemini": true}, "context_files": ["README.md","example_profile.md","example_scenarios.md"], ...}
TRANSCRIPT [them]: Can you walk us through how you sequenced the AD trust teardown?
LLM_START gen=1 mode=auto
**Q:** How you sequenced the AD trust teardown
- **Situation:** …
- **Action:** …
- **Impact / Metrics:** …
- **Say next:** …
- **Watch out:** …
LLM_END provider=claude elapsed=2.9s errors=[]
```
Exit code `0` = a provider answered; `2` = no provider answered (see `errors=[...]`); `3` = timeout.

**STOP & VERIFY:** `providers.claude` is `true`, tokens stream progressively (not all at once), and
`LLM_END provider=claude`. If `provider=gemini` appears instead, Claude failed — read `errors=[...]`.
Only then stop Terminal A (`Ctrl+C`).

## Phase 5 — Knowledge base

Drop your `.md`/`.txt` files into `context\` (see `context\README.md` for a layout). Hot-reload is
automatic; the HUD pill shows `N docs`. Verify what's loaded:
```pwsh
.\backend\.venv\Scripts\python.exe .\backend\tools\ws_probe.py --status
```
Expected: `"context_files": [...]` lists your files; `"context_truncated": false`. If `true`, raise
`context.max_chars` or trim files.

**STOP & VERIFY:** every file you expect is in `context_files`, and the examples are deleted or rewritten.

## Phase 6 — Live HUD

```pwsh
pwsh .\scripts\start.ps1            # or: npm start
# options: -NoAudio (text-only test mode)   -DebugTools (DevTools + verbose)
```

What happens: Electron creates the HUD (frameless, transparent, `alwaysOnTop('screen-saver')`,
`setContentProtection(true)`, hidden from taskbar/dock), spawns `backend/server.py` with the venv python,
connects to `ws://127.0.0.1:8765` (auto-reconnect every 1 s), and registers the global hotkeys.

Hotkeys (change in `config.json → hotkeys`, Electron accelerator syntax):

| Action | Default | Effect |
|--------|---------|--------|
| Toggle HUD visibility | `Ctrl/⌘+Shift+H` | hide/show without stopping capture (tray icon click does the same) |
| Cycle language | `Ctrl/⌘+Shift+E` | Auto → ES → EN for transcription, answers and UI |
| Settings | `Ctrl/⌘+Shift+,` | open/close the settings panel |
| Answer now | `Ctrl/⌘+Shift+Space` | generate a card for the latest THEM turn (or best talking point) |
| Summarize call | `Ctrl/⌘+Shift+S` | decisions / open questions / action items / risks (Gemini-first) |
| Mute / unmute listening | `Ctrl/⌘+Shift+L` | pauses both channels, resets VAD |
| Clear | `Ctrl/⌘+Shift+X` | cancels in-flight generation (kills the `claude` subprocess) and clears the card |
| Quit | `Ctrl/⌘+Shift+Q` | stops backend tree and exits |

Expected on screen: pills `LINK ● LISTEN ● STT ● CLAUDE ● N docs` all green (STT goes amber→green while the
model loads). Speak a question through the *other* side (e.g. join a test meeting from your phone, or play a
recorded question through the speakers): `THEM` line updates, then a card streams within ~2–4 s.

**STOP & VERIFY (screen share):** start a Zoom/Teams screen share of your whole desktop and confirm the HUD
is **not** visible in the shared preview (Windows: `SetWindowDisplayAffinity`; macOS: capture exclusion).
Note: content protection hides the window from capture but it stays visible on your own monitor; it does
not survive OBS "display capture" on Linux.

## Phase 7 — Tuning

| Symptom | Fix |
|---------|-----|
| Cards fire on every sentence | `llm.auto_answer=false` (hotkey-only), or `llm.gemini_classifier=true` for an LLM classifier |
| Utterances split mid-sentence | raise `audio.end_silence_ms` to 900–1200 |
| Long delay before transcript | `stt.model_size="base"` (faster) or `"cuda"` device; `beam_size` stays 1 |
| Poor Spanish/English accuracy | `stt.model_size="medium"`; set `stt.language="es"` or `"en"` if the call is monolingual |
| "ME" contains the other side's words | use headphones; or raise `vad_aggressiveness` to 3 |
| Claude slow / rate-limited | set `llm.claude_model="haiku"` for the card and keep summaries on Gemini |
| Card too long to scan | lower `llm.max_answer_words` (80 is comfortable) |
| HUD too tall/short | `hud.height`; it is also resizable and draggable by the top bar |

## Event protocol (for extending)

Backend → HUD: `status`, `transcript{channel,text,t}`, `llm_start{gen_id,mode}`, `llm_reset{gen_id}`,
`llm_token{gen_id,text}`, `llm_end{gen_id,provider,cancelled,errors,elapsed_s}`, `error{message}`, `log`.
HUD → backend: `generate`, `summarize`, `cancel`, `toggle_listening`, `set_listening{value}`,
`set_auto_answer{value}`, `reload_context`, `inject{channel,text}`, `status`, `ping`,
`set_config{general:{language,ui_language,primary}, llm:{claude_model,gemini_model,auto_answer,max_answer_words}, style:{tone,length}}`,
`toggle_language`, `cycle_tone`, `cycle_length`, `list_gemini_models` (→ `gemini_models{models}`),
`list_audio_devices` (→ `audio_devices{mic,loopback}`), `set_audio_devices{mic,loopback}`,
`list_profiles`, `set_profile{name}`, `set_profile_config{claude_project,use_learned_memory}`, `set_playbook{text}`,
`followup{kind}`, `vision{image_b64,mime}`, `end_session` (→ `session{state,report_path,memory_words}`).
Binary frames from HUD → backend: `[channel u8][sampleRate u32le][int16 PCM…]` (Electron capture). Backend → HUD
`levels{them,me}` at 10 Hz.
