# Changelog

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
