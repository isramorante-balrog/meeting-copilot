# Meeting Copilot

A desktop copilot for live calls. It listens to a Zoom / Teams / Meet call (system audio plus your microphone),
transcribes it in real time, and streams a suggested spoken answer into a small always-on-top window (the HUD)
while the other person is still finishing their sentence. English and Spanish, switchable mid-call.

Electron (HUD) + Python (audio, transcription, prompting). Runs from source; one launcher installs what is missing.

**Version 1.0.0 · MIT licence · Windows 10/11 first-class, macOS/Linux supported with fewer audio options**

## What it does

- **Live transcription**, three engines you can switch at runtime:
  Deepgram Nova-3 streaming (two pre-warmed native sockets, `es-419` and `en-US`, switched in 0 ms),
  local faster-whisper (offline, no key), or Groq Whisper large-v3-turbo.
- **Answers from the AI you choose**: Claude (through a signed-in Claude Code CLI), ChatGPT (OpenAI API),
  Gemini, Grok (xAI) or DeepSeek. Pick one as primary; every other configured provider is an automatic fallback.
- **Turn-aware**: consecutive sentences from the same speaker are one question and one answer card. If they keep
  talking, the card is updated in place. Any utterance of 3+ words gets an answer; "ok / sí / claro" does not.
- **Your context**: profiles with role description, CV, experience notes and a playbook (PDF, DOCX, TXT, MD or
  pasted text), retrieved per question with BM25. A document bank lets several profiles share files.
- **EN / ES / AUTO** answer language, follow-ups (example, deeper, shorter, different example), screen capture
  questions (Alt+S) and optional passive screen context.
- **Session review**: every call is logged per profile; "End & Analyze" produces a scored debrief.
- **Auto-update**: checks this repository for a newer release and installs it when no call is running.

## Install and run

1. Download the repository (green **Code** button → *Download ZIP*, or `git clone`) into a folder you can write to.
2. **Windows**: double-click `Meeting Copilot.cmd`. **macOS**: double-click `Meeting Copilot.command`.
   **Linux**: `bash scripts/bootstrap.sh`.
   The launcher installs Node.js and Python 3.12 if they are missing (winget / Homebrew), creates
   `backend/.venv`, installs the packages and starts the app. The first run takes a few minutes; later runs take seconds.
3. The app opens a **setup window**: paste the API key of the AI provider you want, press **Probar** to test it,
   choose the transcription engine (and its key), and press **Guardar y continuar**.
   No keys are typed into a terminal. Reopen this window any time with **🔑 Proveedores de IA**.

| Provider | Where to get a key | Default model (editable; **Modelos** lists what your key can use) |
|---|---|---|
| ChatGPT (OpenAI) | platform.openai.com/api-keys | `gpt-4o-mini` |
| Grok (xAI) | console.x.ai | `grok-3-mini` |
| DeepSeek | platform.deepseek.com/api_keys | `deepseek-chat` (no image input) |
| Gemini | aistudio.google.com/apikey | `gemini-2.5-flash` |
| Claude | no key: install Claude Code (`npm i -g @anthropic-ai/claude-code`) and run `claude` once to sign in | `claude-sonnet-5-5` |
| Deepgram (transcription) | console.deepgram.com | Nova-3 |

Keys are written only to `config.json` in the app folder, which is git-ignored. The usual environment variables
(`OPENAI_API_KEY`, `XAI_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `DEEPGRAM_API_KEY`, `GROQ_API_KEY`) work too.

## Using it

1. **Setup → Perfil y documentos**: create a profile, add your role description and CV.
2. Pick the audio input mode: **💻 Audio PC** (the call plays on this computer) or
   **📱 Llamada externa** (a phone on speaker, heard through the laptop microphone).
3. **▶ Iniciar escucha**. The window shrinks to the HUD. Answers appear on their own; `Alt+A` forces one.

| Hotkey | Action | Hotkey | Action |
|---|---|---|---|
| `Alt+A` | Answer now | `Alt+L` | Answer language EN → ES → AUTO |
| `Alt+1/2/3/4` | Example / deeper / shorter / different example | `Alt+S` | Answer about what is on screen |
| `Alt+M` | Mute listening | `Alt+N` | Start a new turn |
| `Alt+G` | Click-through mode | `Alt+T` | Setup ⇄ HUD |
| `Alt+H` | Hide / show | `Alt+E` | End session |
| `Alt+Shift+Arrows` | Move the HUD | `Alt+↑/↓` | Scroll answers |
| `Alt+[` / `Alt+]` | Background opacity | `Alt+P` | PC audio ⇄ external call |

All hotkeys can be changed in `config.json` (`hotkeys`). `config.example.json` lists every setting with its default.

## Updates

The version is shown in the Setup header; click it to check now. With **Actualizar la app automáticamente** on
(default), a newer release is downloaded and installed when no live session is running, then the app restarts.
Your `config.json`, profiles, document bank and logs are never touched by an update. To turn it off set
`"updates": {"enabled": false}` in `config.json`. Maintainers: bump `version` in `package.json` and push a tag
`vX.Y.Z`; the release workflow publishes it.

## When something fails

A failed answer shows which provider failed and why, with the fix next to it:

| Message | What to do |
| --- | --- |
| The Claude Code session expired | Press **Iniciar sesión en Claude** (it runs `claude /login` in a terminal), then **Probar** in *Proveedores de IA* |
| The API key is wrong or was revoked | Paste a new key in *Proveedores de IA* |
| That model does not exist for this account | Press **Modelos** and pick one from the list |
| Out of quota or credit | Choose another provider as primary, or top up the account |

**Reportar problema** files a diagnostic report as an issue on this repository. Before it leaves your machine the
app removes API keys, e-mail addresses, your user folder name, profile names and every transcribed or generated
sentence. Issues on a public repository are public, so the report opens in your browser for you to read before
you submit it. To send reports somewhere else, set `reports.repo` in `config.json` (for example to a private
repository). A maintainer can add a fine-grained token with *Issues: read and write* as `reports.github_token`
in their own `config.json` to file reports without the browser step; the token is never part of the app.

## Privacy

- Audio leaves your machine only for the transcription engine you selected (Deepgram or Groq); local Whisper
  keeps it on the computer. Transcript text and your retrieved context go to the AI provider you selected.
- Nothing is sent to the authors of this project. There is no telemetry.
- Profiles, documents, session logs and keys stay in the app folder and are excluded from git.

## Responsible use

The HUD is excluded from screen capture and can run click-through, so it does not get in the way of what you are
sharing. That also means other participants cannot see it. Recording or transcribing a conversation can require the
consent of everyone on the call, depending on where you and they are. Many interviews, exams and assessments do not
allow outside assistance. Check the rules that apply to you and get consent where it is needed; how you use this
tool is your responsibility.

## Documentation

- [docs/MANUAL.md](docs/MANUAL.md): profiles and logs, audio setup, settings, manual install runbook, WebSocket protocol.
- [docs/HISTORY.md](docs/HISTORY.md): design notes from the pre-1.0 iterations.
- [CHANGELOG.md](CHANGELOG.md)

## Development

```
npm install                      # Electron, ws, pdf-parse, mammoth
python -m venv backend/.venv     # then: pip install -r backend/requirements.txt
npm start                        # or: npm run start:debug
python backend/server.py --no-audio      # backend alone; drive it with backend/tools/ws_probe.py
```

Layout: `electron/` (main process, updater, renderer), `backend/` (server, transcriber, classifier, prompts,
providers), `scripts/` (launchers), `data/bank/` (shared documents), `profiles/` (created at run time).

Issues and pull requests are welcome.
