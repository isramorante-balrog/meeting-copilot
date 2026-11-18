# Changelog

## 1.0.7 — 2026-11-18

### Fixed
- Older answers could not be scrolled back to in the live HUD: the answer area grew past the window instead
  of scrolling.
- AUTO did not leave Spanish when the call was in English. It waited for a finished sentence, which the wrong
  recogniser often never produces. It now switches as soon as the live words are plainly the other language.
- "Limpio. Escuchando…" could appear twice.

### Changed
- The live HUD opens taller (520 px instead of 380). Applied once; a height you choose afterwards is kept.

## 1.0.6 — 2026-11-18

### Fixed
- Call audio was only captured from the Windows default output. Teams, Meet and Zoom play on the device chosen
  in their own settings (usually a headset), so the transcript could stay empty for a whole call. With the
  system-audio device left on "default", every output is now listened to and the one that is playing is followed.
- Windows delivers no audio at all while nothing is playing, so the recogniser never saw the pause that ends a
  sentence and held its last words until the next sound. The gap is now filled with two seconds of silence.

### Added
- If no call audio has arrived 20 seconds into a session, the HUD says so, names the device it is listening to
  and offers "Elegir dispositivo". The event is also written to the session log.

## 1.0.5 — 2026-11-17

### Fixed
- "Tu contexto" said a profile had no documents when its role, CV or experience were pasted text or attached
  from the bank instead of uploaded files. Pasted text now counts, here and in the file total of the side bar.

## 1.0.4 — 2026-11-17

### Fixed
- The document bank created a new entry every time the same document was used in another profile (for example
  one CV listed once per profile as `<perfil>_profile`). A document is now identified by its text: saving text
  that is already in the bank reuses the existing entry, whatever name it arrives under.
- Existing duplicates are merged at start-up. The copy kept is the uploaded file when there is one. Nothing is
  deleted: the extra copies are moved to `data/bank/_duplicates/`. Playbooks are not touched.

## 1.0.3 — 2026-11-17

### Fixed
- Setup could keep showing "Deepgram está arrancando…" although the engine was connected: the label came from
  a status sent while the engine was still starting. The backend now always sends a fresh status when start-up
  ends, and the app asks for one whenever the live audio diagnostics disagree with what it shows.
- The transcription check now tells "connecting" apart from a rejected key or a network error and shows the reason.
- A Deepgram connection that timed out without an error text could stop all four sockets for good.

## 1.0.2 — 2026-11-17

### Fixed
- The updater only looked at published releases and tags, so with none published it reported "up to date" and
  clicking the version did nothing visible. It now also reads the version on the default branch and takes the
  highest of the three, so a pushed version bump reaches installed copies without publishing anything.
- A manual check now says what it is doing and what it found.

## 1.0.1 — 2026-11-17

### Added
- Problem reports. "Reportar problema" (Setup title bar, and on any failed answer) builds a diagnostic report
  and files it as an issue on the project's GitHub. API keys, e-mail addresses, the user folder name, profile
  names and everything said or answered in a call are removed before anything leaves the machine. A copy is
  kept in `logs/reports/`. Without a token the browser opens a pre-filled issue to review and submit; with
  `reports.github_token` in the local `config.json` the issue is created directly.
- A failed answer now says which provider failed, why, and offers the fix: sign in to Claude again, open the
  provider settings, retry, or report it. "No provider answered" on its own is gone.
- "Sign in to Claude" button (failed answers and the provider list) opens a terminal on `claude /login` when
  the Claude Code session has expired.
- Pre-flight strip in Setup: transcription, AI answers and your context each show whether they are ready and
  what is wrong in plain words; clicking one opens the place to fix it.
- A provider that failed with a login, key, quota or model error is tried last for ten minutes, so the working
  backup answers first instead of every answer waiting on the broken one.

### Changed
- New interface for both screens: one stylesheet, a side-navigated Setup, and a live HUD with two slim control
  rows, a larger reading area and one primary action. Status labels are plain words instead of codes.

### Fixed
- When the call played through the speakers, the microphone transcribed the other person's words as yours,
  which closed their turn early. Echoed text is now dropped and the app suggests headphones.
- The readiness indicator only knew about Claude and Gemini; it now reflects whichever provider is primary.

## 1.0.0 — 2026-11-17

First public release.

### Added
- ChatGPT (OpenAI), Grok (xAI) and DeepSeek as answer providers, next to Claude and Gemini. One primary, the rest
  are automatic fallbacks.
- First-run setup window for provider keys, models, transcription engine and update preference, with a Test button
  per provider. The launchers no longer ask for anything in the terminal.
- Auto-updater: checks GitHub releases, downloads and installs when no live session is running, keeps user data.
- HUD height button (compact / medium / tall).

### Fixed (from a full review of the pre-1.0 code)
- An answer was started and cancelled repeatedly while the speaker kept talking after a pause.
- A finished answer was rewritten when the other person said "ok" or "right".
- Failed or cancelled answers were retried in a loop.
- Early parts of a long sentence could be dropped from the question.
- System audio could be captured twice, which garbled transcription.
- Late text from a cancelled answer could land in the replacement card; opener cards had no question and were
  duplicated instead of replaced.
- The backend overwrote window position, opacity and font size saved by the app, and re-applied old tuning
  values on every start.
- The live HUD showed in the taskbar when click-through was off; the End dialog could not be clicked in
  click-through mode; unsaved form fields were reset by status updates; commands sent before the backend was up
  were lost.
- The microphone could switch the transcription language of the other speaker; audio queued without limit while
  a transcription socket was down.
- A crashed app could leave the backend running and holding the port.

### Changed
- Speculative drafting is off by default.
- The profile "default language" now means the language the other person usually speaks; the answer language is
  only the EN / ES / AUTO switch.
