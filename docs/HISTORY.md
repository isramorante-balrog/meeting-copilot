# Development history (pre-1.0 iterations)

Design notes from the iterations that led to 1.0.0, newest first. Kept for contributors who want to know why a mechanism exists; the README describes the current behaviour.

## v19: native Spanish — dual pre-warmed Deepgram sockets, Spanish Whisper prompt, universal auto-trigger

**1. Dual pre-warmed native sockets (`transcriber.py`).** `language=multi` is gone (English acoustic bias on IAM
jargon + keyterm conflicts wrecked Spanish). Every channel (them / me) now keeps **two** native Nova-3 sockets open:
`language=es-419` (falls back to `es` on a 400) and `language=en-US`, both with
`smart_format=true&punctuate=true&interim_results=true&endpointing=750&utterance_end_ms=1100` (+ `no_delay`,
`filler_words=false`; keyterms only on the English socket). PCM goes to the **active** language socket only; the
standby one receives `{"type":"KeepAlive"}` every 5 s (no audio credits, never closes). `EN`/`ES` in the HUD or
`Alt+L` moves the routing pointer — measured 0.16 ms, no handshake — and sends `Finalize` to the socket it left so
its last words are flushed. `AUTO` routes to the **profile's default language** (`default_language` in the profile
now means "the language the interviewer usually speaks"; it no longer overwrites the answer-language toggle), the
server flips the pointer when a finished utterance reads as the other language (`prompts.detect_language`, ignored
when that final's confidence < 0.65 because a low-confidence final is the wrong decoder's garbage), and the engine
flips itself after two consecutive finals with `confidence < 0.65`. The HUD STT pill shows the active decoder
(`DG·ES`), auto flips toast *🎙 Transcribiendo en EN (auto: cambiaron de idioma)*. The keyterm 400 guard stays.
**Local Whisper / Groq**: `ES` passes `language="es"` and the **Spanish** `initial_prompt` (*"Entrevista técnica en
español sobre ciberseguridad, IAM, PAM, CyberArk, Privilege Cloud, Conjur, SailPoint, Saviynt, Entra ID, Active
Directory, Kerberos, SAML, OIDC, SOX ITGC, ISO 27001."*); `EN` the English one; the English prompt is never sent with
`language="es"` (that was the English-hallucination cause). `AUTO` = profile default, flipped by the server on text.
`condition_on_previous_text=False` + the repetition filter stay. `stt.force_language` still pins the decoder.

**2. Universal auto-trigger (`classifier.py`, `server.py`).** `needs_answer` is true for **any** remote utterance of
**3+ words** — Spanish or English, `?` or not. Only isolated 1–2-word fillers are ignored (*sí, ok, claro, gracias,
perfecto, ajá, entiendo, okay, right, got it, exacto, de acuerdo, órale…*, alone or in pairs). `trigger_class()`
returns **fast** when the text ends with `?`/`¿…?` or contains a conversational cue — the Mexican/LatAm list
(*qué, cómo, cuál, cuándo, dónde, por qué, quién, platícame, cuéntame, háblame, dime, explícame, describe, menciona,
comparte, tendrás, tienes experiencia, has trabajado, cómo manejas, qué harías, imaginemos, supongamos, me gustaría
entender, y en la parte de…*) plus the English equivalents — and fires at the STT endpoint (~650–750 ms pause);
everything else fires after `llm.turn_setup_hold_ms` = 100 ms more (~800 ms). The 2.5 s watchdog still backs it up.
"Platícame de tu experiencia con CyberArk", "Cuéntame cómo resolviste ese incidente", "Y en la parte de Active
Directory qué hicieron", "Háblame un poco de ti", "Me gustaría entender cómo manejas…" all auto-answer in the e2e run
(0.0–0.1 s after the pause); "sí claro" / "ok gracias" / "perfecto" / "ajá" / "entiendo" / "got it" are skipped.

### v19 runbook (pwsh 7)

```
Phase 1  Drop in ...................................... unzip meeting-copilot-v19-changed-files.zip over the project
         STOP & VERIFY: backend\.venv\Scripts\python -c "import classifier as c; print(c.needs_answer('Platícame de tu experiencia con CyberArk'), c.trigger_class('Háblame un poco de ti'), c.needs_answer('sí claro'))"
                        prints: True fast False

Phase 2  Sockets ...................................... backend\.venv\Scripts\python backend\server.py --no-audio
         expected log (4 lines): "deepgram [them:es] connected (es-419)", "deepgram [them:en] connected (en-US, N keyterms) [warm standby]",
                                  and the same pair for [me:…]. "connected (es)" instead of es-419 means the fallback tag was used - fine.
         STOP & VERIFY: Alt+L flips produce "deepgram routing es -> en (user)" lines and NO new "connected" lines.

Phase 3  Spanish auto-answer ........................... Perfil -> idioma por defecto = Español; HUD on AUTO; interviewer says
         "Platícame de tu experiencia con CyberArk" -> card within ~0.8 s, STT pill "DG·ES"; "Now tell me about Entra ID" ->
         toast "🎙 Transcribiendo en EN (auto…)", card badge AUTO·EN. "sí claro" -> no card, pill says "sin responder: acknowledgement only".
         STOP & VERIFY: every 3+-word sentence produced a card without Alt+A.

Phase 4  Local Whisper (offline) ....................... Audio tab -> Local Faster-Whisper; HUD ES -> log "faster-whisper decoder language -> es (user)"
         Spanish speech transcribes in Spanish; EN -> "-> en". No "si si si" on English speech while on EN.
```

## v18: instant EN | ES | AUTO — bilingual Deepgram stream, 0 ms switch, mid-turn rescue

**1. The audio never reconnects (`transcriber.py`).** Deepgram now runs Nova-3's native bilingual mode on one
socket per channel: `model=nova-3&language=multi&encoding=linear16&sample_rate=16000&channels=1&interim_results=true
&endpointing=800&utterance_end_ms=1200&smart_format=true&punctuate=true&no_delay=true` (+ `filler_words=false`
and the profile `keyterm`s). Spanish, English and mid-sentence code-switching are transcribed on the same open
connection, so the EN/ES toggle is a pure answer-language change — `DeepgramStreamingEngine.set_language()` is a
no-op for the stream and nothing is ever closed or re-opened (the e2e run shows exactly 2 connects for a whole
session with three flips). **HTTP 400 guard**: if Deepgram rejects the connection *with* keyterms, each channel
reconnects immediately without them (`keyterms_rejected: true` in the status) instead of backing off. Detected
language per result (`alternatives[].languages`) is kept as a hint. Offline fallback: faster-whisper now runs with
`condition_on_previous_text=False`, `compression_ratio_threshold=2.2`, a repetition filter (`squash_repetitions`:
any token repeated more than 4 times in a row is collapsed; a segment that is >60 % one token is dropped — no more
"si, si, si"), and **per-utterance language detection** — the decoder is never forced to Spanish/English by the
toggle (pin it only with `stt.force_language`). Groq gets the same filter.

**2. `[ EN | ES | AUTO ]` in the HUD and `Alt+L`** (`server.py`, `prompts.py`, `renderer.js`). `general.language` is
now the **answer** language only: `en` / `es` force it; `auto` mirrors each question with
`prompts.detect_language()` — a stopword tally (*what, how, tell, would, experience…* vs *cómo, cuál, cuéntame, qué,
experiencia, para…*, accents and ¿¡ count as Spanish) that costs < 0.1 ms, then the STT's own detection, then the
previous answer's language. `Alt+L` cycles EN → ES → AUTO; the AUTO button shows the language it resolved to
(`AUTO·ES`) and every card carries an `ES` / `EN` / `AUTO·EN` badge. The opener uses the same resolution, and the
profile's `default_language` may be `auto`.

**3. Mid-turn rescue.** Flipping EN/ES (click or `Alt+L`) while an answer is streaming, or within
`llm.language_flip_rescue_s` = 15 s of the last question, aborts the stream and re-answers the *same* question in the
new language **into the same card** (`answer_hold {reason: language_flip}` → `llm_start {replace: true}`; turn cards
by `turn_id`, follow-up/Answer-Now cards by `replace_gen_id`). If the flip does not change the effective language
(AUTO → ES on a Spanish question) nothing is redone. Flipping before they speak simply applies to the next turn.

### v18 runbook (pwsh 7)

```
Phase 1  Drop in ...................................... unzip meeting-copilot-v18-changed-files.zip over the project
         STOP & VERIFY: backend\.venv\Scripts\python -c "import prompts as p; print(p.detect_language('Cuéntame cómo lo hiciste'), p.detect_language('Tell me how you did it'))"
                        prints: es en

Phase 2  Stream check ................................. backend\.venv\Scripts\python backend\server.py --no-audio
         expected log: "deepgram [them] connected (multi, N keyterms)" and the same for [me]. If you see
                       "400 with keyterms … reconnecting without keyterm" that is the guard working (status shows keyterms_rejected).
         STOP & VERIFY: press Alt+L three times in the HUD — the log must NOT contain "restarting STT engine" or new
                        "deepgram [...] connected" lines; the EN/ES/AUTO toast appears instantly.

Phase 3  AUTO mirroring ............................... HUD toggle on AUTO; interviewer asks in Spanish -> card badge "AUTO·ES";
                                                         next question in English -> "AUTO·EN", no click.
Phase 4  Rescue ....................................... while an answer streams in Spanish press Alt+L to EN:
         expected: toast "Re-respondiendo la última pregunta en el nuevo idioma…", the SAME card is overwritten in English,
                   log "language flip es -> en: re-answering the last question in place". Also works up to 15 s after the answer.
         STOP & VERIFY: no new card appeared and the REMOTO transcript kept flowing during the flip (0 ms audio drop).
```

## v17: auto-answer always fires, 📱 external-call mode, delete fix, HUD/Setup cleanup

**1. Auto-answer that never waits for a button.** `classifier.needs_answer` now returns true for any finished remote
utterance of **4+ words** (no `?` required; only pure acknowledgements like "ok, gracias" are skipped) and
`skip_reason()` says why when it does not (shown in the 🗣️ turn pill and the log: *"not answering yet — too short"*,
*"auto-answer is OFF"*). Turn merging is kept but can no longer block: a clear question fires the moment the STT
pause ends (~0.9 s), a dangling statement waits only `llm.turn_setup_hold_ms` = **600 ms** more (v16's 1800 is
migrated down), and a **watchdog** in the 10 Hz levels loop fires any pending 4+-word turn that is still unanswered
after `turn_watchdog_s` = 2.5 s — whatever state the turn machine is in. If the speaker continues before you talk,
the card is still updated in place (v16). Starting a live session with auto-answer off now shows a red toast.

**2. 📱 Llamada externa / Altavoz (por Mic).** One switch in the Setup header and a 💻/📱 mini-switch in HUD row 1
(`Alt+P`, tray menu). `audio.input_mode = "external"` makes `_sink()` treat everything the laptop mic hears as the
remote speaker (`REMOTO`, triggers answers) and ignore the PC loopback; the PC meter shows *PC ·📱*. Because nothing
can close a turn through the mic in this mode, turns close after 8 s of silence or ⏭/Alt+N. `"pc"` is the normal
mode: loopback = remote voice, mic = your own context only.

**3. Profile deletion.** 🗑 Eliminar opens a red confirmation bar — **[Sí, eliminar] [Cancelar]** (Esc cancels) — no
typed name. The typing bug itself was the drag region: `styles.css` now forces `-webkit-app-region: no-drag` on every
`button, input, select, textarea, a, label, .seg, .inline-form`, and `main.js` creates the window `focusable: true`
and re-asserts `setFocusable(true)` whenever ghost mode is off (mode switch, show/hide).

**4. UI cleanup.** HUD header rows are `box-sizing: border-box; width: 100%; flex-wrap: wrap; padding: 6px 10px;
gap: 6px` so Responder / Finalizar never clip; the raw `meter.sys` / `meter.mic` / `btn.mute` keys were missing from
both i18n tables → now **PC / MIC / Silenciar** (Mute in EN); the answer feed (and Setup panes) use a 5 px dark
scrollbar; the footer keeps only *Ejemplo · Profundizar · Más corto · 🔄 Otro ejemplo*, the 🗣️ turn pill + ⏭, a
⚡ latency pill (*first word · total* of the last answer, green ≤ 1.5 s) and the *fondo NN %* opacity pill — the
chunk/segment diagnostics moved to Setup → Audio only. In *1 · Perfil y documentos* the duplicate top-right
*Subir archivo | Pegar texto* toggle is gone; each card has one action row **📁 Subir archivo · ✏️ Pegar texto ·
📚 Elegir del Banco ▾** under the loaded-file badge (*📄 name · N palabras · ✕ Quitar*).

### v17 runbook (pwsh 7)

```
Phase 1  Drop in ...................................... unzip meeting-copilot-v17-changed-files.zip over the project
         STOP & VERIFY: backend\.venv\Scripts\python -c "import classifier as c; print(c.needs_answer('We use CyberArk here today.'), c.skip_reason('Okay thanks.'))"
                        prints: True too short (2 words, need 4+ or a question)

Phase 2  Auto-answer offline ........................... backend\.venv\Scripts\python backend\server.py --no-audio; inject as [them]:
           "We use CyberArk here today."              -> "turn 1 -> new answer (fast trigger …)" within ~0.1 s, no button
           "So in that role we had three forests and" -> "holding 600 ms" then "turn 2 -> new answer (hold elapsed …)"
           "Okay thanks."                             -> "not answering yet - too short (2 words …)"
         STOP & VERIFY: every 4+-word line produced an llm_start without pressing Alt+A. If you see
                        "auto-answer is OFF", turn it on in Setup -> Cerebro (Auto-responder) and save.

Phase 3  📱 external call ............................. Setup header -> "📱 Llamada externa / Altavoz (por Mic)" (or Alt+P)
         expected: toast "📱 Llamada externa: …", PC meter label reads "PC ·📱" and moves with the room audio;
                   speak near the laptop -> REMOTO line + answer card. Switch back to 💻 for Zoom/Teams.
         STOP & VERIFY: in 📱 mode your own voice also triggers answers (the mic cannot tell you apart) — mute with Alt+M
                        while you speak, or use ⏭ to close a turn.

Phase 4  Delete + UI .................................. Setup -> 🗑 Eliminar -> red bar -> [Sí, eliminar]; HUD: all buttons visible at
         520 px, labels PC / MIC / Silenciar, thin scrollbar, footer pills only.
```

## v16: same-speaker turn accumulation + in-place answer replacement

**Why.** A 0.5 s breathing pause used to end the remote "turn", so a three-sentence question produced three
half-answer cards. v16 treats everything the interviewer says **until you answer** as one turn with one card.

- **`current_remote_turn_buffer`** (`server.py`, `self.turn`): every finished `[Remote]` segment is appended to the
  open turn unless (a) your mic produced ≥ 4 words since the last remote segment (`llm.turn_me_words_reset`),
  (b) more than 25 s of remote silence passed (`turn_max_gap_s`; 8 s when no mic is configured, because nothing
  else could ever end a turn), or (c) you pressed **⏭ Turno nuevo / `Alt+N`** (`new_turn`). Each turn has a
  `turn_id`; the prompt always receives the whole accumulated text (context + final question).
- **Fast trigger vs context-setup hold** (`classifier.turn_readiness`): if the accumulated text ends with `?` / `¿`
  or its last sentence is a direct prompt (*tell me about, how did you, what would you, walk me through, why did,
  cuéntame, cómo manejaste…*) the answer starts immediately after the STT pause (~0.9 s). If it ends on a statement,
  a connector (*and, so, because, when we, in that role, y, pero, porque, en ese rol…*), a comma or an ellipsis, the
  server holds **1.8 s** (`turn_setup_hold_ms`) for more; a new segment re-evaluates, and the hold fires on its own
  otherwise. `Alt+A` always bypasses the hold and answers the buffer as it stands.
- **Abort & replace in place**: Deepgram interim words from `[Remote]` (or, for local/Groq engines, the next
  finalised segment) arriving while the turn's answer is streaming cancel that LLM task at once
  (`answer_hold {reason: speaker_continuing}`), keep accumulating into the same `turn_id`, and the next pause
  regenerates with `llm_start {turn_id, replace: true}`. A finished answer is replaced the same way if they keep
  adding context before you speak. If the interim words were noise and nothing new is finalised, a 1.8 s safety
  hold regenerates anyway, so a turn can never be left without an answer.
- **Renderer** (`renderer.js`): cards are indexed by `turn_id` (`turnCards`); an `llm_start` for a known turn streams
  into the existing card (question line updated to the full text, a *N frases* badge) instead of creating a new one.
  `answer_hold` shows **↻ Actualizando con pregunta completa…** (or **⏳ Esperando el resto de la pregunta…** during a
  setup hold) with the previous text dimmed until the replacement arrives. Footer: a 🗣️ turn pill
  (*turno · 3 frases · esperando… / respondiendo / respondido*) and the ⏭ button.
- **Endpointing** (`transcriber.py`): Deepgram `endpointing=900`, `utterance_end_ms=1300` (old 500/1000 values in
  `config.json` are migrated), so clause pauses do not split sentences in the first place.
- Speculative drafting now drafts on *accumulated turn + partial segment*, and a draft is only released for a
  brand-new card (a replacement is always generated fresh).

### v16 runbook (pwsh 7)

```
Phase 1  Drop in ...................................... unzip meeting-copilot-v16-changed-files.zip over the project
         STOP & VERIFY: backend\.venv\Scripts\python -c "import classifier; print(classifier.turn_readiness('we had three forests and'), classifier.turn_readiness('How did you sequence it?'))"
                        prints: setup question

Phase 2  Offline turn check .......................... backend\.venv\Scripts\python backend\server.py --no-audio, then inject (ws_probe) as [them]:
           "So in my last role we had three forests and"            -> log: turn 1 started … holding 1800 ms   (no card yet)
           "we were migrating two hundred apps under a TSA deadline." -> turn 1 extended: 2 segments … holding
           "How did you sequence the trust teardown?"                -> turn 1 -> new answer (fast trigger (question)): 3 segments
           "And what about the service accounts?" (while streaming)  -> turn 1 -> REPLACE answer …: 4 segments
           inject as [me] a 10-word answer                           -> turn 1 answered by me … next remote segment starts a new turn
         STOP & VERIFY: exactly ONE llm_start per turn_id with replace=false, replacements carry replace=true.

Phase 3  Live ........................................ Iniciar escucha; ask the remote side a 3-sentence question with pauses
         expected: one card; its question line grows to the full text; 🗣️ pill "turno · 3 frases · esperando…" while
                   they are still setting up, "respondiendo" on the trigger; if they keep talking during the answer the
                   card shows "↻ Actualizando con pregunta completa…" and is overwritten, never duplicated.
         STOP & VERIFY: after you answer out loud (≥ 4 words on the mic), the pill shows "respondido" and the next
                        remote sentence opens a NEW card. If your mic is off, turns close after 8 s of remote silence
                        or ⏭ / Alt+N - keep the mic on for the best segmentation.
```

## v15: ghost mode, hands-free HUD control, auto-vision, neutral window identity

| Feature | Hotkey | What it does |
|---|---|---|
| **👻 Ghost mode (click-through)** | `Alt+G` (or the 👻 button) | `setIgnoreMouseEvents(true, {forward:true})`: every click lands on the app behind the HUD while the HUD stays fully readable. The window is also made non-focusable, so nothing you do can pull OS focus away from Zoom/Teams. Only the 👻 button itself stays clickable (it punches a hole under the cursor on hover) so you can leave ghost mode with the mouse; `Alt+G` always works. Live HUD only — switching to Setup clears it. *Setup ⇄ Live moved from `Alt+G` to `Alt+T`* (an old `config.json` is migrated automatically). |
| **Nudge window** | `Alt+Shift+↑ ↓ ← →` | Moves the HUD 40 px (`hud.nudge_px`) in that direction, clamped to the work area; the position is saved (`hud.x`, `hud.top`) and restored next launch. |
| **Scroll answers** | `Alt+↑` / `Alt+↓` | Scrolls the answer feed by 60 % of its height, smoothly, from the main process — works while ghosted / unfocused; reaching the bottom re-enables auto-follow. |
| **Background opacity** | `Alt+[` / `Alt+]` (fallback `Alt+-` / `Alt+=` on layouts where brackets can't be registered) | Steps `hud.opacity` 0.35 → 0.95 in 0.1 — the HUD **background** alpha (CSS `--hud-alpha`), never the window alpha, so the text stays 100 % crisp. Current value shows in the footer. |
| **👁️ Auto-vision** | `Alt+V` (or the 👁️ button) | Every 5 s (`hud.auto_vision_interval_s`) while live, the renderer asks main for one compressed frame (`desktopCapturer`, ≤1100 px, JPEG q50, ~40-120 KB, ~30 ms) of the display under the cursor, keeps it as a **rolling 1-frame buffer** and mirrors it to the backend (`vision_buffer`). When the next answer triggers and the question refers to the screen — "this diagram", "on the screen", "this slide", "this code", "looking at this", "como ven", "esta gráfica"… (`prompts.refers_to_screen`) — the frame is attached to the LLM request with a `<screen_frame>` note (age included); no `Alt+S` needed. Frames older than 20 s (`llm.auto_vision_max_age_s`) are never attached; set `llm.auto_vision_always: true` to attach on every answer. The fast opener and any speculative draft are skipped for a vision answer (they never saw the screen). Card badge: **👁 pantalla**. Persisted in `hud.auto_vision`; `Alt+S` still forces an immediate capture + dedicated screen answer. |
| **Neutral identity** | — | Window title, `app.setName`, Windows AppUserModelID (`com.audioenginehost.client`), tray tooltip, error dialogs and `process.title` all read **Audio Engine Host**; `<title>` in `index.html` too. `setContentProtection(true)` is re-applied on every mode switch and `skipTaskbar(true)` is enforced whenever the Live HUD is shown. |

Focus policy in Live mode: the window is shown with `showInactive()`, hotkeys only send messages (never `focus()`), dialogs only focus in Setup, and in ghost mode the window is non-focusable outright. The HUD takes focus only when you click into it yourself (e.g. the 🎯 focus editor).

### v15 runbook (pwsh 7)

```
Phase 1  Drop in ...................................... unzip meeting-copilot-v15-changed-files.zip over the project
         STOP & VERIFY: logs\copilot.log after launch shows "hotkey ghost: Alt+G OK", "hotkey settings: Alt+T OK",
                        "hotkey nudge_up: Alt+Shift+Up OK", "hotkey scroll_up: Alt+Up OK" and either
                        "opacity_down: Alt+[ OK" or "opacity_down (fallback): Alt+- OK".

Phase 2  Identity ..................................... Task Manager / Alt+Tab while the Setup window is open
         expected: the process window is "Audio Engine Host"; in Live mode it is absent from the taskbar and from
                   any screen share (content protection). STOP & VERIFY before joining a real call.

Phase 3  Ghost + keyboard control ...................... Iniciar escucha → Alt+G
         expected: toast "Modo fantasma ACTIVO", thin blue outline, "fantasma · clic a través" label; clicking on the
                   HUD body hits the app behind it; hovering 👻 makes it clickable again. Alt+Shift+← moves the HUD
                   40 px; Alt+↓ scrolls the feed; Alt+[ dims the background ("fondo 65%" in the footer), text unchanged.
         STOP & VERIFY: Zoom/Teams keeps keyboard focus during all of the above (type in the chat box to confirm).

Phase 4  Auto-vision .................................. Alt+V (or 👁️) → share a slide in the meeting app
         expected: 👁️ blinks every 5 s (title shows "… KB · … ms"); ask aloud from the remote side "what do you think
                   of this diagram?" → the answer card carries the 👁 pantalla badge and the log reads
                   "auto-vision frame attached (NN KB, Ns old)". A plain question ("what is SCIM?") attaches nothing.
         STOP & VERIFY: the Deepgram/LLM latency on vision answers is higher (cold vision call); keep Auto-vision off
                        for calls with no screen sharing.
```

## v14.1: conditional storytelling (no more stories in every turn)

**Why.** v14 made the model rotate stories — but it was still shoehorning a past-project story into greetings,
definitions, opinions and status answers. v14.1 adds a **CONDITIONAL STORYTELLING RULE** as the very first,
highest-priority block of the system prompt (above the playbook) and at the top of the default playbook:

- **No example for**: greetings/small talk, self-introductions, clarifying questions, high-level opinions, direct
  technical definitions, quick status updates, yes/no or factual questions, presentations, any direct question →
  one or two crisp sentences, zero past-project stories, zero dates, zero old metrics (at most one clause of credential).
- **Story only when explicitly requested** with behavioral/situational cues ("Tell me about a time…", "Give me an
  example of…", "How did you handle a situation where…", "Describe a project where…", "Cuéntame de una vez que…",
  "Dame un ejemplo de…") or when the interviewer is probing a story already told.
- When a story is requested: rich, original, from the Story Bank — tools, metrics, team size, technical depth — in
  the 6-beat order (situation, task, decision, action, result, lesson) as prose, never the same story twice in a row.

The backend does not leave the verdict to the model's mood: `prompts.wants_story()` (EN/ES cue regexes, <1 ms;
"tell me about yourself", "what is X", "what's your opinion", "where are we on" are never stories) decides and every
generation carries `<story_request>NO STORY | STORY REQUESTED | PROBING A STORY</story_request>`; the ledger and the
rotation/continuity blocks are only injected when a story is in play, so a greeting prompt stays tiny. The opener
prompt gets the same verdict, so the first sentence can't start with "Back in 2024…" either. Ejemplo (Alt+1) is an
explicit request and still tells one; Profundizar (Alt+2) deepens the *content* of a direct answer without bolting
a story onto it. The answer card shows no continuity badge for direct answers (`llm_start.continuity = "direct"`).

## v14: story rotation, Cambiar ejemplo (Alt+4), follow-up depth

**Why.** The model kept latching onto one flagship project (e.g. a bank M&A integration or the Saviynt IGA rollout) and
reused it for every question. v14 makes rotation a hard rule *and* gives the backend a memory of which examples
were already spent in this call.

- **Anti-repetition rule** (`prompts.py`): the CRITICAL ANTI-REPETITION RULE is now in the hard `STORY ROTATION`
  section of the system prompt (applies even with a custom playbook) and in the default playbook, together with the
  credibility rule (specific tools, measurable metrics, realistic team sizes, cross-functional pushback, relative
  timelines like "Back in late 2024…") and the 6-beat follow-up depth formula.
- **Story ledger** (`server.py`): after every answer the backend extracts a *story signature* — named entities
  (products, clients, people), years and headline metrics — with `prompts.story_signature`, preferring the same
  product/client vocabulary the STT keyterms use. The last 12 are kept in `story_ledger` (reset at End/Exit and on
  profile switch) and injected into every generation as `<examples_already_used_this_call>` (newest last). The
  retrieval query also *penalises* the newest story's terms (`BM25Index.search(avoid=…)`), so chunks about other
  projects surface for the next question.
- **Continuity detection** (`prompts.is_probing_followup`, EN/ES, <1 ms): a remote turn that reads as a probe
  ("Can you go deeper on how you handled that pushback?", "What was the alternative option?", "¿Cuál fue la
  alternativa?", or a short question reusing the last story's names) is sent with `<continuity>PROBING</continuity>`:
  keep the same project/people/numbers and expand with the 6-beat formula (decision point → constraint →
  alternatives rejected → trade-off accepted → measurable result → lesson). Anything else is `NEW TOPIC`: the newest
  entry's project/client/domain is off-limits. Explicit new-topic markers ("different question", "otro tema") always
  win. The speculative opener receives the same hint (`<do_not_reuse>` / `<same_story_as_before>`), so the first
  sentence does not open with the stale story either. `llm_start.continuity` = `first | rotate | probe`; the answer
  card shows it as a badge (*ejemplo nuevo* / *misma historia · más a fondo* / *rotado*).
- **🔄 Cambiar ejemplo [Alt+4]** (`followup {kind: "pivot"}`): re-runs the last question with the task *"Discard the
  previous project example entirely. Take the exact same technical concept/question, but pivot immediately to a
  completely different project or past experience from my resume/story bank, using a new set of metrics and
  tools."* The discarded story's entities, years and metrics are listed in `<discarded_example>` and penalised in
  retrieval; the new answer joins the ledger. Button in the HUD footer next to Ejemplo / Profundizar / Más corto;
  hotkey `hotkeys.followup_pivot` (default `Alt+4`). Ejemplo / Profundizar (Alt+1/2) now carry an explicit
  "same story, go deeper" continuity note; Más corto (Alt+3) rewrites without touching the ledger.
- **📚 story pill** (HUD footer): `3 · usado: Saviynt IGA, ExampleCo` — how many examples the call has spent and what
  the last one was anchored on; `story {entities, ledger}` event.

### v14 runbook (pwsh 7)

```
Phase 1  Drop in the files ........................ unzip meeting-copilot-v14-changed-files.zip over the project (6 backend/electron files + README)
         STOP & VERIFY: backend\.venv\Scripts\python -c "import prompts; print(prompts.FOLLOWUP_KINDS)" prints ('example', 'deepen', 'tldr', 'pivot').

Phase 2  Offline prompt check ...................... backend\.venv\Scripts\python backend\server.py --no-audio
         in another pwsh:  (see "Event protocol") send {"type":"inject","channel":"them","text":"Walk me through a PAM migration you led."}
         expected log:  gen 1 continuity: first  →  story ledger +1 (auto): <entities of the answer>
         then inject "Can you go deeper on how you handled that pushback?"  →  gen 2 continuity: probe
         then inject "Tell me about a time you remediated audit findings." →  gen 3 continuity: rotate
         STOP & VERIFY: the three continuity values appear in that order before using it live.

Phase 3  Live ...................................... Iniciar escucha; after the first answer the footer shows "📚 1 · usado: …".
         - interviewer probes → card badge "misma historia · más a fondo", same project in the text
         - new question → badge "ejemplo nuevo", different project than the pill
         - Alt+4 / 🔄 Cambiar ejemplo → toast "Cambiando a un ejemplo de otro proyecto…", new card badge "rotado",
           none of the pill's names appear in it.
         STOP & VERIFY: if the knowledge base has only ONE project, the model is told to use a different phase/system
         of it — add more experience documents to the bank for real rotation.
```

## v13: 3-engine transcription pipeline (no more chopped words)

**Why.** v12 sliced the audio into 1.5 s rolling chunks for local Whisper; Whisper has no idea where a word
boundary is inside a slice, so words were cut in half and accuracy collapsed. v13 removes the slicing entirely and
lets you pick the engine in **Audio y atajos → Motor de Transcripción** (saved to `config.json`, switchable live):

| Engine | How it works | Latency to first words | Needs |
|---|---|---|---|
| **Deepgram Nova-3 Streaming [Recomendado]** | one WebSocket per channel (SYS / MIC); 16 kHz PCM streamed as it is captured; `interim_results` every ~200 ms are shown on the new **EN VIVO** line of the HUD; `is_final` pieces are merged into the turn and `speech_final` / `UtteranceEnd` (endpointing 500 ms, utterance_end 1000 ms) triggers the answer. Built-in IAM vocabulary + terms mined from your profile are sent as `keyterm` (EN). `language=en|es` follows the `[EN|ES]` toggle (reconnects). | ~0.2–0.4 s | `DEEPGRAM_API_KEY` (paste it in the Audio tab) |
| **Local Faster-Whisper [Mejorado]** | the WebRTC segmenter now ends a turn only on a real pause (600 ms, 900 ms when the sentence reads unfinished, 30 s ceiling) → the *whole utterance* goes to faster-whisper with Silero `vad_filter` (`min_silence_duration_ms=600, speech_pad_ms=300`), a domain `initial_prompt` (*"Technical discussion covering IAM, PAM, CyberArk PAS, Privilege Cloud, Conjur, SailPoint, Saviynt, Entra ID, Active Directory, Kerberos, SAML, OIDC, SCIM, SOX ITGC, ISO 27001."* + your keyterms), `condition_on_previous_text=True`, `beam_size=1, best_of=1, temperature=0`. CUDA→CPU fallback unchanged. | 0.6–2 s after the pause (CPU `small`) | nothing (offline) |
| **Groq Whisper Large-v3-Turbo** | same whole-utterance segmenter, the WAV is POSTed to `api.groq.com` (`whisper-large-v3-turbo`, `prompt` = vocabulary, `language`). | ~0.3–0.6 s after the pause | `GROQ_API_KEY` |

- **Keyterm boosting** (`transcriber.mine_vocabulary`): the built-in list (`CyberArk, SailPoint, Saviynt, Entra ID,
  Okta, Conjur, SAML, OIDC, SCIM, Kerberos, NTLM, gMSA, SOX ITGC, ISO 27001, Privilege Cloud, PVWA, CPM, PSM, PSMP,
  EPM, Splunk, ArcSight, NIST, …`) + acronyms / product names mined from the active profile's role, CV, experience
  and playbook (+ job role / company) + the *Vocabulario adicional* field — capped at 60 terms. Switching profile
  reconnects Deepgram with the new terms. The count shows in the Audio tab and the diagnostics line.
- **Safety net**: if Deepgram/Groq cannot start (no key, no network, 401) the backend logs the reason, shows it in the
  Audio tab (*Respaldo: Whisper local*) and keeps transcribing locally — the call is never silent.
- **Settings**: `stt.engine` (`deepgram | whisper_local | groq_whisper`), `stt.deepgram_api_key`, `stt.groq_api_key`
  (or the `DEEPGRAM_API_KEY` / `GROQ_API_KEY` environment variables), `stt.model_size`, `stt.device`, `stt.vocabulary`,
  `stt.whisper_prompt`, `stt.deepgram_endpointing_ms`, `stt.deepgram_utterance_end_ms`. Old `audio.chunk_s` /
  `max_utterance_s: 1.5` values in an existing `config.json` are migrated automatically.
- **HUD**: new third transcript line **EN VIVO** (*Transcripción en Vivo — interim preview*) shows the words Deepgram
  is still forming; it clears when the piece is final. The STT pill reads `DG` / `GROQ` / `STT` by engine.
- **Protocol**: new `interim {channel,text}` event, `set_config {stt:{…}}`, `restart_stt`; `status.stt` carries the
  engine state (`ready`, `device`, `keyterms`, per-channel `connections`, `error`).
- `backend/requirements.txt`: `websockets>=13`, `requests` (Groq), `faster-whisper>=1.1` (Silero VAD parameters).
  Re-run the bootstrap once (it reinstalls when `requirements.txt` changes).


### v13 runbook (pwsh 7)

```
Phase 1  Install the new requirements .............. pwsh .\scripts\bootstrap.ps1 -NoLaunch
         expected: "installing Python requirements" … "requirements OK"; no pip errors.
         STOP & VERIFY: backend\.venv\Scripts\python -c "import websockets, requests, faster_whisper; print('ok')" prints ok.

Phase 2  Dry-run the backend without audio ......... backend\.venv\Scripts\python backend\server.py --no-audio --log-level INFO
         expected (Deepgram): "deepgram [them] connected (en, N keyterms)" and "deepgram [me] connected" then
                              "STT engine ready: deepgram (deepgram/nova-3), N keyterms"
         expected (local):    "Loading faster-whisper 'small' (device=cpu, compute=int8)…" then
                              "STT engine ready: whisper_local (cpu/int8), N keyterms"
         If you see "STT engine 'deepgram' unavailable (…) - using local Whisper for now": the key is missing/invalid.
         STOP & VERIFY: the line "STT engine ready: <engine you selected>" is present before continuing. Ctrl+C.

Phase 3  Pick the engine in the app ................ .\Meeting Copilot.cmd → Audio y atajos → Motor de Transcripción
         - choose the engine, paste the API key (Deepgram or Groq), optional extra keyterms, "Guardar motor de transcripción"
         expected: status line under the selector reads "deepgram · listo · deepgram/nova-3 · SYS ✓ · MIC ✓" (or
                   "whisper_local · listo · cpu/int8"); "N keyterms activos" next to the button.
         STOP & VERIFY: SYS ✓ and MIC ✓ both green before starting a call (each channel has its own stream).

Phase 4  Live check .................................. Iniciar escucha → play a video with speech in the meeting app
         expected: HUD line "EN VIVO" fills word by word (Deepgram), REMOTO turns final on the pause, answer streams.
         Diagnostics (footer): "Deepgram: Streaming" or "Whisper: Ready 850ms"; "segments 1/1" per sentence (no more 3–4 per sentence).
         STOP & VERIFY: product names (CyberArk, PSM, Entra ID…) appear spelled correctly in REMOTO.

Phase 5  Switch language mid-call ................... Alt+L (EN⇄ES)
         expected: Deepgram reconnects within ~1 s (SYS/MIC ✓ again); local engines switch instantly.
```

## v12: Enfoque de la sesión (quick session focus, optional)

- **Setup**: a compact bar under the header — *Enfoque de esta sesión (Opcional)* — with five toggle chips (🎯 Entrevista Técnica, 👔 Ejecutiva / CISO, 🚨 Incidente en Vivo, 🗺️ Roadmap, 🤝 Cliente / Arquitectura) that append/remove a preset line, a free-text box, and ✕ to clear. Empty is fine: *Iniciar escucha* starts immediately.
- **Live HUD**: a 🎯 *Enfoque* pill in row 1 opens an inline editor; Enter sends `set_focus` over the WebSocket and the next generation uses it. The pill shows the current hint.
- **Backend**: when non-empty, `[IMMEDIATE SESSION FOCUS & HINTS FOR THIS CALL]` is injected at the very top of the full-answer system prompt, the opener prompt and the vision prompt (omitted entirely when empty); focus terms also act as a 0.6-weight BM25 boost in `retrieval.py`, so experience chunks matching today's focus rank higher. A focus change cancels any speculative draft.
- **Logs & analysis**: `session_focus` is stored in `session_<stamp>.json` and the analysis JSON, shown as a header line in the `.md`, as a badge in the session list and in the session title; the grader receives it as `<session_focus>` and scores role alignment / summary against it. The focus resets after each call ends.

## v11.2: `bankStore is not defined` crash fix

`main.js` was rewritten as a single clean file: all IPC-visible state lives in one `state` object and the
profile manager / bank are reached through `getProfiles()` / `getBank()` (lazily created), so no handler can
hit an undefined global again. A headless audit (`scripts`-free: load `main.js` against an Electron shim and
invoke every `ipcMain.handle` channel) runs all 21 handlers without errors; `context:pick` → PDF parsed → bank
entry written was part of it.

## v11.1: Bank fix — auto-save, live refresh, migration, delete

- The bank is now an Electron-side module (`BankStore` in `context_manager.js`, IPC `bank:list / save_text / read / delete / migrate`). Every upload saves the **original file** (`data/bank/<cat>/originals/`), the parsed **`.md`** and a **`.json`** sidecar (`{id, filename, originalName, wordCount, pages, source, profile, updatedAt}`); same filename = updated in place. Pasted text and playbooks are saved to the bank from the renderer too, independent of the backend.
- Dropdowns refresh on startup, on profile switch, and the instant an upload/paste/playbook save finishes (`bank_changed` push from main + explicit `refreshBank()`).
- On startup `migrateFrom()` imports everything already in `profiles/*`, `profiles_archived/*` and the legacy `context/` (uploaded slots, pasted `manual_context`, playbook texts) into the bank once.
- 🗑️ next to each bank selector opens the category with per-entry delete (the default playbook is protected).

## v11: Banco de documentos, perfiles archivados, UI en español, contexto del micrófono, análisis 0–100

- **Banco (`data/bank/`)** — `roles/`, `cvs/`, `experience/`, `playbooks/`. Every upload (extracted text) and every pasted entry or saved playbook is copied there automatically. Each card has an *Elegir del Banco…* dropdown (experience: a checkbox modal for several files; playbook: dropdown + name field); attaching from the bank fills the slot as text without touching your PC. `default_playbook.md` is the built-in default (not deletable).
- **Archivar / Restaurar** — *Archivar perfil* moves `profiles/<name>/` to `profiles_archived/<name>/` (config, documents, logs intact) and out of the selector; *Perfiles archivados* lists them with *Restaurar* and a shortcut to their session logs. Archived profiles appear in the analysis tab's profile filter.
- **Spanish UI by default**, transcription/answer language **EN by default**. `profile_config.json` now holds `default_language`, `default_playbook`, `job_role`, `company` (all editable in tab 1): switching to a profile applies its language to Whisper and the answers and loads its playbook from the bank; the `[EN|ES]` toggle still flips mid-call.
- **Mic on by default; [Me] as context** — both channels are transcribed and logged. The prompt transcript is labelled `[Interviewer / Remote said]` / `[Candidate / Me said]`, with a hard rule never to contradict what you already said and to build on it for follow-ups. Your mic still never triggers an answer. The exact default playbook from your spec is hardcoded in `backend/prompts.py` (`DEFAULT_PLAYBOOK`) and shipped as `data/bank/playbooks/default_playbook.md`; `{{job_role}}`/`{{company}}` come from the profile, the other placeholders map to the prompt sections.
- **Análisis de sesiones** — transcript saved continuously; *Terminar y analizar* now asks the model for a structured JSON (overall 0–100, sub-scores Claridad y concisión / Profundidad técnica / Estructura de ejemplos / Alineación con el rol, summary, decisions & next steps, question-by-question review with ideal answers, pacing, strengths, top adjustments), saved as `session_<stamp>_analysis.json` + markdown report. Tab 4: profile filter (incl. archived) → chronological list with date, duration and score badge → score card, executive summary, decisions, Q-by-Q review, collapsible full transcript with copy.

## v10: length ceilings, adaptive VAD, speculative drafting

- **Ceilings, no quotas.** Length settings are now absolute upper limits with zero minimum plus an explicit policy: answer a simple question in one or two crisp sentences and stop; use a structured walkthrough only when they ask for a scenario, an architecture breakdown or a multi-step process; never pad or add generic follow-ups. The opener prompt also stops when two sentences fully answer the question.
- **Adaptive VAD.** `transcriber.looks_complete()` judges the interim transcript (EN/ES): ends on a preposition, conjunction, article, auxiliary or comma → mid-clause. The segmenter ends a turn after `end_silence_ms` (450) only when the sentence looks complete, otherwise it waits up to `end_silence_incomplete_ms` (700). While Whisper is still behind the audio the turn is treated as incomplete. Rolling interim chunks every 1.5 s (`chunk_s`).
- **Speculative pre-drafting.** From `llm.speculate_min_words` (8) words of a remote turn with a clear topic, the backend runs BM25 retrieval and starts the fast opener in the background with a "may be cut off" note. On turn end: if ≥70 % of the draft's tokens are still in the final question (`speculate_min_overlap`) the draft is released instantly (already-generated tokens replayed, the rest streams) and the full answer starts from the final text; if the speaker pivoted, the draft is cancelled and both stages regenerate. If the speaker keeps adding clauses on the same topic the running draft is kept; a topic change restarts it. Diagnostics line shows `speculating`.

## v9: spoken-prose answers, active listening, warm Claude pool

- **No more template.** `prompts.py` has no `Situation / Action / Impact / Say next / Watch out` structure anywhere. The hard delivery rules are: flowing spoken prose, zero bullets/labels/headers/bold, 1–2-sentence paragraphs separated by blank lines, first person with contractions. Your **Playbook is placed first** in the system prompt as the highest-priority delivery rule (only "prose, no bullets" and "facts only" rank above it); tone/length are defaults below it. Follow-ups, opener and vision answers are prose too. The HUD renders paragraphs (and strips any stray markdown).
- **Active listening.** `classifier.py`: any finished remote turn with more than 5 words triggers an answer — question or statement — and short turns still trigger when they look like a question/request; pure acknowledgements ("ok", "thanks") are skipped; the user's mic never triggers. Pause threshold is 450 ms (`audio.end_silence_ms`). No LLM classification call exists.
- **Latency.** `llm_claude.py` keeps a pool of **two warm `claude -p --input-format stream-json` sessions** (re-filled while each answer streams, reset on model/profile change, cold retry if a warm one dies). Tokens are forwarded to the HUD as they arrive (`llm_token` per delta, no buffering). Each card's footer now shows `warm/cold · first word 0.xx s · total`, and the diagnostics line carries `first_token_s` so you can see exactly where time goes. If a card says *cold*, the pool was empty (e.g. right after startup or a model change).

## v8: paste-text context, instant EN|ES, strict 2-row HUD, warm Claude session

- **Paste instead of upload.** Each context card has an `Upload file | Paste text` toggle; *Paste text* opens a modal textarea. The text is saved to `profiles/<name>/manual_context/{role,profile,experience}.md`, shown as a green "Pasted text: N words" badge, takes precedence over the uploaded file for that slot, and is indexed for retrieval like any other document. Markdown/text files are read as-is by `context_loader.py` (no document parser involved).
- **`[EN | ES]` toggle** in HUD row 1 and `Alt+L`. No language detection: the choice injects a fixed directive into both the opener and the full-answer system prompts — ES: *"Responde exclusivamente en Español profesional y natural, adaptando la terminología técnica de ciberseguridad/IAM al contexto corporativo"*; EN: natural professional English — and applies to the very next generation. Default is now `en` (set `general.language` to `auto` to go back to follow-the-speaker).
- **Strict 2-row HUD, 520 px max.** Row 1: profile · `[EN|ES]` · LISTEN · STT · SYS/MIC bars · 🛡️. Row 2: Answer (Alt+A) · Screen (Alt+S) · Mute (Alt+M) · A-/A+ · ⚙ Setup · ⏹ End · ✕ exit. The window is capped at `hud.max_width` while live (resizable below it) and answer cards render as short teleprompter paragraphs with each label on its own line.
- **Latency.** Besides the v7 opener/retrieval/local-VAD work (pause now 0.5 s): `llm_claude.py` keeps a **warm `claude -p --input-format stream-json` process** pre-spawned (and re-spawned while each answer streams, also after model/profile changes), so a question is a single line written to an already-running CLI — the ~1–2 s Node cold start is gone from both the opener (`claude-haiku-5-5`) and the full answer. Gemini Flash remains the opener when a key is set.

## v7: sub-2-second answers, dual-speaker transcript, answer feed, fixed End modal

**Latency** (measured on the stub harness; your numbers depend on the model and CPU):
1. **Per-turn retrieval instead of the whole story bank** — `backend/retrieval.py` splits every supporting-experience file into ~300-word chunks on headings/paragraphs and ranks them with BM25 (EN/ES stopwords, light stemming, <1 ms). Each answer sends the role description, the resume, playbook, learned memory and only the **top 3 chunks** (`context.top_chunks`, ~900 words) chosen from the live question + the last remote turns. The card footer shows "N relevant chunks".
2. **Local classifier only** — no LLM classification call; `classifier.py` decides in <5 ms (question marks, interrogatives, request/challenge phrases, and any remote turn ≥ 28 words). It never fires on your own microphone.
3. **Rolling early transcription** — Whisper runs on 2 s chunks while the remote speaker is still talking (`audio.chunk_s`), the pieces are merged into one *REMOTE* line shown in italics with "…" while partial, and the turn is finalized 0.6 s after they stop (`audio.end_silence_ms`). When the pause lands, at most the last 2 s remain to transcribe.
4. **Two-stage answer** — the instant the turn ends, a tiny prompt (role head, resume head, best chunk, last 4 lines, question) goes to the fastest model — Gemini 2.5 Flash if `GEMINI_API_KEY` is set, otherwise `claude-haiku-5-5` (`llm.fast_provider`, `llm.fast_gemini_model`, `llm.fast_claude_model`) — and streams a one-to-two-sentence **opener** in green italics at the top of the card; the full tailored answer streams below it from your primary brain. Caveat: `claude -p` starts a new Node process per call (~1–2 s to first token), so for true sub-second openers keep a Gemini key set, or make Gemini the primary brain.

**Dual-speaker transcript** — both channels are transcribed and logged as `[Remote Speaker]` / `[User Mic]` in `logs/session_*.json|md`. In the HUD the *ME* line is smaller and dimmed so it only confirms the mic is recording.

**Answer feed** — answers are appended as cards (kind · detected question · time) in a scrollable feed; nothing is overwritten. Auto-scroll follows the newest card unless you scrolled up, in which case a "↓ Jump to latest answer" pill appears. Alt+X clears the feed.

**End session** — the confirmation is a fixed, centered modal (z-index 9999) with Cancel / Exit without analysis / End & Analyze; it never depends on scroll position.

## v6.1: the real reason nothing was transcribed 

`RuntimeError: Library cublas64_12.dll is not found or cannot be loaded` was raised **inside `transcribe()`**, not at load.
With `stt.device: auto` CTranslate2 picks CUDA and only touches cuBLAS on the first encode, so the model looked
"ready" and every 3.5 s chunk then failed. `transcriber.py` now (1) warms the model up with 1 s of silence at load
and drops to the next option (`cuda/float16` → `cpu/int8`) if that fails, (2) catches CUDA runtime errors
mid-session and reloads on `cpu/int8` automatically, and (3) on Windows registers the DLL folders of the
`nvidia-cublas-cu12` / `nvidia-cudnn-cu12` pip wheels so a GPU install (`bootstrap.ps1 -Cuda`) really works.
To stay on CPU explicitly set `"stt": {"device": "cpu", "compute_type": "int8"}`; `small` on CPU transcribes a
3.5 s chunk in roughly 1–2 s on a modern laptop (`base` is faster, `medium` more accurate).


- **Why nothing was transcribed.** Two silent failure paths were closed: (1) if faster-whisper failed to load — typically `device: auto` choosing CUDA on a PC without cuDNN — every speech segment was discarded with no UI signal; `transcriber.py` now falls back `configured → cuda/float16 → cpu/int8` and the error is surfaced. (2) Transcription only runs while a live session is armed (▶ Start Live Listening); in the Setup dashboard the meters work but nothing is transcribed by design — the diagnostics line now says so.
- **Rolling chunks.** `audio_capture.py` flushes every **3.5 s of continuous speech** (`audio.chunk_s`) and on **0.8 s of silence** (`audio.end_silence_ms`); frames count as speech when WebRTC VAD *or* an RMS energy gate (`audio.energy_threshold`) says so, so YouTube/TTS that never pauses is transcribed every few seconds. Everything is resampled to 16 kHz mono float32 in `server._sink` (Python WASAPI/PortAudio: int16 stereo → mono → 16 k; Electron path: the AudioWorklet already emits 16 kHz mono int16). Quiet audio is normalized before Whisper.
- **Diagnostics.** Footer line in the HUD and a box in *Audio & Hotkeys*: audio chunks per channel, speech segments → transcribed, queue depth, STT state (Loading / Ready / Transcribing / Error) with device and last latency, and the last error. STT exceptions and "speech detected but STT not ready" are toasted.
- **Narrow HUD (540 px, resizable).** Row 1: profile, LISTENING/THINKING pill, STT and MODEL dots, language, SYS/MIC bars, 🛡️. Row 2: Answer [Alt+A] · Screen [Alt+S] · Mute [Alt+M] · Setup · End · Exit · A- / A+.
- **Text size.** Answer panel defaults to 17 px / 1.5 line-height via `--answer-font-size`; A-/A+ buttons, `Ctrl +` / `Ctrl -` / `Ctrl 0` (intercepted in-window; the default browser zoom menu is removed and the zoom factor pinned to 1), persisted in localStorage and `config.json → hud.font_size`.
- **Always visible to you.** The window is never hidden or dimmed for Alt+S or screen share; `setContentProtection(true)` alone keeps it out of Zoom/Teams/Meet and screenshots. Opacity is fixed at 100 %.
- **Never trapped.** End always stops the session: with fewer than 2 transcript turns it skips the LLM call, toasts *"Session ended without analysis"* and returns to Setup. *Exit* (and *Exit without analysis* in the confirm box) leaves instantly. When analysis does run, the HUD closes immediately and the report streams into tab 4.

## v5: Setup Dashboard ⇄ Live HUD, Alt hotkeys, no-freeze parsing

- **Two modes.** The app opens as a solid **Setup Dashboard** (tabs: Profile & Documents · Playbook & Style · Audio & Hotkeys · Past Sessions & Insights) with a big **▶ Start Live Listening** button. Starting arms transcription and morphs the window into the compact frosted **Live HUD** at the top-center (status pill, two meters, streaming answer, Answer Now / 📷 / 🎙 / ⚙ / ■ Stop & Analyze). ⚙ (or `Alt+G`) returns to the dashboard while the session keeps running; ■ ends it, streams the insights report and lists it in tab 4.
- **Freeze fix.** PDF/DOCX parsing now runs in a `worker_threads` worker (`electron/parse_worker.js`), so a 44-page PDF never blocks the UI; a spinner badge shows per file. Native file dialogs run with the overlay lowered (`withDialog`) so they can't hide behind the always-on-top HUD. Only small manifests cross IPC; the extracted text stays on disk in the profile folder and is loaded by the Python backend. Profile actions use inline forms (Electron has no `window.prompt`). Drag & drop onto the cards works too.
- **Stealth.** `setContentProtection(true)` is applied on window creation and on every mode switch; Live mode also sets `skipTaskbar` and `alwaysOnTop('screen-saver')`. The 🛡️ *Stealth Active* badge confirms it. Alt+Tab/taskbar show nothing while live.
- **Hotkeys (2-key, global):** `Alt+S` capture screen question · `Alt+A` force answer now · `Alt+H` hide/show · `Alt+M` mute/unmute · `Alt+1/2/3` example / deepen / shorter · `Alt+E` stop & analyze · `Alt+U` summary · `Alt+X` clear · `Alt+L` language · `Alt+G` setup ⇄ HUD · `Alt+Q` quit. All editable in `config.json → hotkeys`; the buttons show the badges.

