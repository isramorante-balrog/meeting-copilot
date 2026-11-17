'use strict';
/* Renderer: Setup Dashboard (tabs) + compact Live HUD. All heavy work (parsing, files) happens in main/worker. */

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

// ------------------------------------------------------------------ i18n
const I18N = {
  en: {
    stealth: 'Stealth Active',
    'setup.start': '▶ Start Live Listening', 'setup.resume': '▶ Return to Live HUD', 'setup.live_running': 'Live session running',
    'tab.profile': '1 · Profile & Documents', 'tab.playbook': '2 · Playbook & Style', 'tab.audio': '3 · Audio & Hotkeys', 'tab.sessions': '4 · Past Sessions & Insights',
    'profile.active': 'Profile', 'pm.create': '＋ New', 'pm.duplicate': '⧉ Duplicate', 'pm.rename': '✎ Rename', 'pm.delete': '🗑 Delete', 'pm.folder': '📁 Folder',
    'pm.ask_name': 'Name for the new profile', 'pm.ask_dup': 'Name for the copy', 'pm.ask_rename': 'New name', 'pm.confirm_delete': (n) => `Delete profile "${n}" with all its documents, logs and memory? Type its name to confirm`,
    ok: 'OK',
    'ctx.role': 'Position / Role Description', 'ctx.role_help': 'single file — responsibilities, requirements, expectations',
    'ctx.profile': 'Professional Profile', 'ctx.profile_help': 'single file — your CV / background',
    'ctx.experience': 'Supporting Experience & Projects', 'ctx.experience_help': 'multiple files — projects, architectures, case studies',
    'ctx.playbook': 'Custom instructions (Response Playbook) — auto-saved', 'ctx.playbook_help': 'Framing rules, frameworks, phrases to use/avoid — applied to every answer',
    'ctx.playbook_ph': 'e.g. Always open with the business outcome, then the architecture. Keep it under 4 paragraphs. Never mention client names. Prefer "we" for team work…',
    'ctx.drop': 'Drop a .pdf / .docx / .txt / .md here', 'ctx.drop_multi': 'Drop several files here',
    'ctx.choose': 'Choose file…', 'ctx.add': 'Add files…', 'ctx.choose_pb': 'Guidelines file…', 'ctx.empty': 'No file loaded', 'ctx.remove': 'Remove',
    'ctx.loaded': (w) => `Loaded: ${w.toLocaleString()} words`, 'ctx.parsing': 'Parsing…', 'ctx.could_not_read': 'Could not read',
    'ctx.formats': 'Accepted: .pdf (text-based), .docx, .txt, .md. Files are parsed in a background thread and stored as text inside the profile folder; scanned, password-protected or corrupted files are rejected with a warning.',
    'ctx.total': (w, n) => `${n} file${n === 1 ? '' : 's'} · ${w.toLocaleString()} words in prompt`, 'ctx.truncated': ' · ⚠ truncated',
    'settings.memory': 'Use learned memory from past sessions', 'settings.project': 'Local Claude project (CLAUDE.md), optional',
    'project.none': '— none —', 'memory.words': (w) => (w ? `${w.toLocaleString()} words of learned memory` : 'No learned memory yet — appears after Stop & Analyze'),
    'strip.tone': 'Tone', 'strip.length': 'Length', 'tone.natural': 'Natural', 'tone.executive': 'Executive', 'tone.technical': 'Technical',
    'len.concise': 'Concise', 'len.medium': 'Medium', 'len.detailed': 'Detailed',
    'settings.language': 'Answer & transcription language', 'settings.ui_language': 'Interface language', 'lang.auto_short': 'Auto', 'lang.same': 'Same as above',
    'lang.name.auto': 'AUTO', 'lang.name.en': 'EN', 'lang.name.es': 'ES',
    'settings.brain': 'Brain', 'settings.primary': 'Primary brain', 'settings.auto': 'Auto-answer when they ask a question', on: 'On', off: 'Off (Answer Now only)', off_plain: 'Off',
    'settings.claude_model': 'Claude model', 'settings.claude_custom': 'Custom Claude model id (optional)', 'settings.gemini_model': 'Gemini model', 'settings.gemini_custom': 'Custom Gemini model id (optional)',
    'settings.words': 'Max words per card (medium length)', 'settings.opacity': 'Live HUD opacity', 'settings.save': 'Save brain settings',
    'settings.loopback': 'System audio (what they say)', 'settings.mic': 'Microphone (what I say)', 'audio.apply': 'Apply audio devices',
    'settings.audio_help': 'Play something in the meeting app and talk: both bars must move before you start. Windows: pick a "[Loopback]" device or "System audio via Electron". macOS: install BlackHole and choose it.',
    'dev.default': 'Default device', 'dev.off': 'Off', 'dev.electron': 'System audio via Electron (Windows)', 'dev.electron_mic': 'Microphone via Electron',
    'hotkeys.title': 'Global hotkeys',
    'stt.title': 'Transcription engine', 'stt.engine': 'Engine', 'stt.lang_note': 'Transcription language',
    'stt.lang_help': 'Follows the HUD [EN|ES] toggle (Alt+L). Deepgram reconnects on change; the built-in IAM vocabulary (CyberArk, SailPoint, Entra ID, SAML, OIDC, PSM…) plus terms mined from your profile are sent as keyterms.',
    'stt.dg_key': 'Deepgram API key', 'stt.dg_help': 'Stored only in config.json (local). Get one at console.deepgram.com → API Keys.',
    'stt.groq_key': 'Groq API key', 'stt.groq_help': 'console.groq.com → API Keys. Each completed utterance is sent to whisper-large-v3-turbo.',
    'stt.model': 'Local model', 'stt.device': 'Device', 'stt.vocab': 'Extra vocabulary (keyterms, comma-separated)',
    'stt.vocab_help': 'Added on top of the built-in IAM list and the terms extracted automatically from your role / CV.',
    'stt.save': 'Save transcription engine', 'toast.stt': 'Transcription engine saved — restarting STT…',
    'stt.state.ready': 'ready', 'stt.state.connecting': 'connecting…', 'stt.state.loading': 'loading model…', 'stt.state.error': 'error',
    'stt.keyterms': (n) => `${n} keyterms active`, 'stt.fallback': 'Fallback: local Whisper',
    'hk.screenshot': 'Capture screen question', 'hk.force_answer': 'Force answer now', 'hk.toggle_visibility': 'Hide / show HUD', 'hk.toggle_listening': 'Mute / unmute listening',
    'hk.followup_example': 'Follow-up: concrete example', 'hk.followup_deepen': 'Follow-up: deepen technical detail', 'hk.followup_tldr': 'Follow-up: shorter', 'hk.end_session': 'Stop & analyze session',
    'hk.summarize': 'Summarize call so far', 'hk.clear': 'Clear / cancel answer', 'hk.toggle_language': 'Cycle language', 'hk.settings': 'Setup ⇄ Live HUD', 'hk.quit': 'Quit',
    'hk.ghost': 'Ghost mode: clicks pass through the HUD', 'hk.auto_vision': 'Auto-vision: screen frame every 5 s attached to answers',
    'hk.nudge_up': 'Move HUD up 40 px', 'hk.nudge_down': 'Move HUD down 40 px', 'hk.nudge_left': 'Move HUD left 40 px', 'hk.nudge_right': 'Move HUD right 40 px',
    'hk.scroll_up': 'Scroll answers up', 'hk.scroll_down': 'Scroll answers down', 'hk.opacity_down': 'HUD background more transparent', 'hk.opacity_up': 'HUD background more opaque',
    'ghost.on': 'Ghost mode ON — clicks pass through (Alt+G to exit)', 'ghost.off': 'Ghost mode off', 'ghost.banner': 'ghost · click-through',
    'vision.on': 'Auto-vision ON — a screen frame every 5 s will be attached when a question refers to the screen', 'vision.off': 'Auto-vision off',
    'vision.err': (m) => `Auto-vision capture failed: ${m}`, 'card.vision_attached': '👁 screen', 'opacity.hint': (v) => `bg ${Math.round(v * 100)}%`,
    'card.updating': '↻ Updating with the complete question…', 'card.holding': '⏳ Waiting for the rest of the question…', 'card.segments': (n) => `${n} sentences`,
    'turn.collecting': (n) => `turn · ${n} sentence${n === 1 ? '' : 's'}`, 'turn.holding': (n) => `turn · ${n} · waiting…`, 'turn.generating': (n) => `turn · ${n} · answering`,
    'turn.answered': (n) => `turn · ${n} · answered`, 'turn.closed': 'new turn next', 'turn.reset': 'New turn: the next thing they say is a new question', 'hk.new_turn': 'New turn (close the remote turn buffer)',
    'sessions.pick': 'Select a session', 'sessions.report': 'Insights report', 'sessions.log': 'Transcript log', 'sessions.none': 'No sessions yet for this profile.',
    'sessions.noreport': 'No insights report for this session (it was not analyzed).', 'sessions.lines': (l, s) => `${l} transcript lines · ${s} suggestions`,
    'report.open': 'Open file', 'report.logs': 'Open logs folder',
    'btn.answer': 'Answer Now', 'btn.stop': '■ Stop & Analyze', 'tx.them': 'REMOTE', 'tx.me': 'ME', 'tx.interim': 'LIVE',
    'meter.sys': 'PC', 'meter.mic': 'MIC', 'btn.mute': 'Mute',
    'prov.button': 'AI providers', 'prov.title': 'Set up your copilot', 'prov.intro': 'Pick the AI brain you want to use and paste its key. You only need one; the others become automatic fallbacks. Keys are stored only on this computer (config.json).',
    'prov.stt_title': 'Transcription (speech to text)', 'prov.default_lang': "Interviewer's usual language", 'prov.auto_update': 'Update the app automatically', 'prov.save': 'Save and continue',
    'prov.primary': 'Primary', 'prov.key_ph': 'API key', 'prov.key_saved': '•••••••• (saved)', 'prov.model_ph': 'model', 'prov.test': 'Test', 'prov.models': 'Models', 'prov.get_key': 'Get a key ↗',
    'prov.ready': 'ready', 'prov.no_key': 'no key', 'prov.cli_ok': 'Claude Code installed — uses your Claude login', 'prov.cli_missing': 'not installed (npm i -g @anthropic-ai/claude-code, then run "claude" once to sign in)',
    'prov.testing': 'testing…', 'prov.test_ok': (ms, m) => `✓ works (${ms} ms, ${m})`, 'prov.test_bad': (e) => `✗ ${e}`, 'prov.need_one': 'Add a key for at least one provider (or install Claude Code).', 'prov.saved': 'Providers saved',
    'upd.checking': 'checking…', 'upd.available': (v) => `v${v} available`, 'upd.downloading': (v) => `downloading v${v}…`, 'upd.installing': (v) => `installing v${v}…`, 'upd.restarting': 'restarting…',
    'upd.staged': (v) => `v${v} ready — installs when the session ends`, 'upd.up_to_date': (v) => `v${v} ✓`, 'upd.error': (e) => `update failed: ${e}`, 'upd.unconfigured': (v) => `v${v}`,
    'stt.decoder': (l, src) => `🎙 Transcribing in ${l.toUpperCase()}${src === 'text' ? ' (auto: they switched language)' : src === 'low confidence' ? ' (auto: low confidence)' : ''}`,
    'lang.flip': (l) => `Answers now in ${l === 'auto' ? 'AUTO (mirror the question)' : l.toUpperCase()}`, 'lang.rescue': 'Re-answering the last question in the new language…', 'card.lang_auto': (l) => `AUTO·${l.toUpperCase()}`,
    'im.pc': 'PC audio (normal)', 'im.external': 'External call / speaker (via mic)', 'im.toast.pc': '💻 PC audio: system sound is the remote voice, mic is your context',
    'im.toast.external': '📱 External call: everything the laptop mic hears is the remote voice and triggers answers', 'hk.input_mode': 'Input mode: PC ⇄ external call (mic)',
    'pm.yes_delete': 'Yes, delete', 'pm.confirm_delete_bar': (n) => `Delete profile "${n}" with all its documents, logs and memory?`,
    'ctx.upload': 'Upload file', 'ctx.upload_multi': 'Upload files', 'ctx.paste_short': 'Paste text', 'latency': (f, e) => `⚡ ${f != null ? f + 's' : '–'} · ${e}s`,
    'turn.skip': (r) => `not answering: ${r}`,
    'status.listening': 'LISTENING', 'status.thinking': 'THINKING', 'status.muted': 'MUTED', 'status.paused': 'PAUSED', 'status.analyzing': 'ANALYZING', 'status.offline': 'OFFLINE',
    'answer.idle': 'Listening… questions from the call will appear here. Alt+A answers now.', 'answer.cleared': 'Cleared. Listening…', 'answer.none': 'No answer — check Claude login / GEMINI_API_KEY.',
    'meta.thinking': 'thinking…', 'meta.summarizing': 'summarizing…', 'meta.fallback': 'falling back…', 'meta.cancelled': 'cancelled', 'meta.noprovider': 'no provider answered',
    'meta.debrief': 'analyzing session…', 'meta.vision': 'reading your screen…', 'meta.followup': (k) => `follow-up: ${k}…`,
    'fu.example': 'Example', 'fu.deepen': 'Deepen', 'fu.tldr': 'Shorter', 'fu.pivot': 'Other example', 'hk.followup_pivot': 'Follow-up: pivot to a different example',
    'story.used': (e) => `used: ${e}`, 'story.none': 'no named project', 'cont.rotate': 'new example', 'cont.probe': 'same story · deeper', 'cont.pivot': 'pivoted', 'cont.first': 'first example',
    'toast.pivot': 'Pivoting to a different project example…',
    'end.confirm': 'End this session and generate the Post-Session Insights report? The transcript stays in the logs folder and the key lessons are added to this profile\'s learned memory.',
    'end.cancel': 'Cancel', 'end.ok': 'Stop & Analyze',
    'toast.ready': 'Backend ready', 'toast.saved': 'Settings applied', 'toast.devices': 'Audio devices applied', 'toast.pb': 'Playbook saved', 'toast.lang': 'Language: ',
    'toast.style': 'Style: ', 'toast.shot': (kb) => `Screen captured (${kb} KB) — analyzing`, 'toast.profile': (n) => `Profile: ${n}`,
    'toast.analyzed': (w) => `Report saved · ${w} words added to learned memory`, 'toast.files': (n) => `${n} file(s) loaded`,
    'btn.unmute': 'Unmute', 'btn.screen': 'Screen', 'btn.setup': 'Setup', 'btn.end': 'End', 'btn.exit': 'Exit', 'settings.font': 'Answer text size (px)',
    'end.noanalysis': 'Exit without analysis', 'toast.no_analysis': 'Session ended without analysis (no transcript recorded)',
    'toast.exited': 'Session ended — back to Setup', 'diag.stt': 'STT', 'diag.chunks': 'audio chunks', 'diag.seg': 'segments', 'diag.err': 'last error',
    'diag.never': 'No audio chunks received yet — check Audio devices', 'diag.notarmed': 'Audio flowing; transcription starts with ▶ Start Live Listening',
    'feed.jump': '↓ Jump to latest answer', 'end.title': 'End this session?', 'card.screen': 'Screen', 'card.summary': 'Summary',
    'card.followup': (k) => `Follow-up · ${k}`, 'card.answer': 'Answer', 'card.opener': 'opener', 'card.ctx': (n) => `${n} relevant chunk${n === 1 ? '' : 's'}`,
    'ctx.src_file': 'Upload file', 'ctx.src_text': 'Paste text', 'ctx.paste_btn': 'Paste / edit text…', 'ctx.paste_save': 'Save text', 'ctx.paste_clear': 'Clear text',
    'ctx.paste_help': 'Paste a job description, your CV, or markdown notes. Saved to profiles/<name>/manual_context/ and used instead of the uploaded file for this slot.',
    'ctx.manual': (w) => `Pasted text: ${w.toLocaleString()} words (used instead of file)`, 'ctx.words': (w) => `${w.toLocaleString()} words`, 'toast.manual': 'Text saved',
    'btn.setup': 'Setup', 'btn.end': 'End',
    'pm.archive': '🗄 Archive profile', 'pm.archived': 'Archived profiles', 'pm.bank': '🏦 Document bank',
    'pm.archived_help': 'Archived profiles keep their configuration, documents and session logs. Restore them any time.',
    'pm.restore': 'Restore', 'pm.none_archived': 'No archived profiles.', 'pm.confirm_archive': (n) => `Archive profile "${n}"? It moves to profiles_archived/ and disappears from the dropdown.`,
    'profile.job_role': 'Job role (job_role)', 'profile.company': 'Company (company)', 'profile.default_language': 'Default transcription & answer language',
    'profile.default_playbook': 'Default playbook (from bank)', 'bank.pick': 'Select from bank…', 'bank.pick_multi': 'Select from bank…', 'bank.pick_pb': 'Select playbook from bank…',
    'bank.title': 'Document bank — Supporting experience', 'bank.help': 'Tick the bank files to attach to this profile. They are combined as text in the experience slot.',
    'bank.attach': 'Attach selected', 'bank.empty': 'Bank is empty — upload or paste something first.', 'bank.attached': (n) => `${n} bank file(s) attached`, 'bank.none_pb': '— none / custom —',
    'sessions.profile_filter': 'Profile', 'sessions.archived_tag': '(archived)', 'sessions.duration': (m) => `${m} min`, 'sessions.noanalysis': 'No analysis for this session (it ended without Stop & Analyze).',
    'an.grade': 'Overall grade', 'an.clarity': 'Clarity & concision', 'an.depth': 'Technical depth', 'an.examples': 'Example structure', 'an.role': 'Role alignment',
    'an.summary': 'What the session was about', 'an.decisions': 'Decisions, agreements & next steps', 'an.qa': 'Question by question (what I said vs. ideal answer)',
    'an.said': 'What I said', 'an.good': 'Worked well', 'an.tighten': 'Tighten', 'an.ideal': 'Ideal answer', 'an.pacing': 'Pacing & clarity', 'an.well': 'What went well',
    'an.adjust': 'Top adjustments for next time', 'an.transcript': 'Full transcript', 'an.copy': 'Copy transcript', 'an.none': '(none recorded)', 'an.turns': (n, s) => `${n} turns · ${s} suggestions`,
    'bank.manage': 'Manage bank entries', 'bank.confirm_delete': (n) => `Remove "${n}" from the bank? Profiles that already attached it keep their copy.`, 'bank.cat.roles': 'Role descriptions', 'bank.cat.cvs': 'CVs / profiles', 'bank.cat.experience': 'Supporting experience', 'bank.cat.playbooks': 'Playbooks',
    'focus.label': 'Focus for this session (optional):', 'focus.tech': 'Technical interview', 'focus.exec': 'Executive / CISO interview', 'focus.incident': 'Live incident',
    'focus.roadmap': 'Strategic plan / roadmap', 'focus.client': 'Client / architecture', 'focus.pill': 'Focus', 'focus.apply': 'Apply',
    'focus.ph': 'E.g. Round 2 with the IAM Director — focus on CyberArk Privilege Cloud migration and NHI governance (can be left empty)...',
    'focus.edit_ph': 'E.g. Focus on SOX audit controls now… (Enter to apply, Esc to close)', 'focus.saved': 'Focus applied', 'focus.cleared': 'Focus cleared', 'focus.none': 'No focus (general)',
    'sessions.focus': 'Focus',
    'gemini.listed': (n) => `${n} Gemini models available`,
  },
  es: {
    stealth: 'Modo invisible activo',
    'setup.start': '▶ Iniciar escucha', 'setup.resume': '▶ Volver al HUD', 'setup.live_running': 'Sesión en vivo activa',
    'tab.profile': '1 · Perfil y documentos', 'tab.playbook': '2 · Playbook y estilo', 'tab.audio': '3 · Audio y atajos', 'tab.sessions': '4 · Análisis de sesiones',
    'profile.active': 'Perfil activo', 'pm.create': '＋ Nuevo', 'pm.duplicate': '⧉ Duplicar', 'pm.rename': '✎ Renombrar', 'pm.delete': '🗑 Eliminar', 'pm.folder': '📁 Carpeta',
    'pm.ask_name': 'Nombre del nuevo perfil', 'pm.ask_dup': 'Nombre de la copia', 'pm.ask_rename': 'Nuevo nombre', 'pm.confirm_delete': (n) => `¿Eliminar el perfil "${n}" con sus documentos, registros y memoria? Escribe su nombre para confirmar`,
    ok: 'OK',
    'ctx.role': 'Descripción del puesto / rol', 'ctx.role_help': 'un archivo — responsabilidades, requisitos, expectativas',
    'ctx.profile': 'Perfil profesional', 'ctx.profile_help': 'un archivo — tu CV / trayectoria',
    'ctx.experience': 'Experiencia y proyectos de apoyo', 'ctx.experience_help': 'varios archivos — proyectos, arquitecturas, casos',
    'ctx.playbook': 'Instrucciones personalizadas (Playbook) — se guarda solo', 'ctx.playbook_help': 'Reglas de enfoque, marcos, frases a usar/evitar — se aplica a cada respuesta',
    'ctx.playbook_ph': 'p. ej. Abre siempre con el resultado de negocio y luego la arquitectura. Máximo 4 párrafos. Nunca menciones nombres de clientes…',
    'ctx.drop': 'Suelta aquí un .pdf / .docx / .txt / .md', 'ctx.drop_multi': 'Suelta aquí varios archivos',
    'ctx.choose': 'Elegir archivo…', 'ctx.add': 'Agregar archivos…', 'ctx.choose_pb': 'Archivo de guía…', 'ctx.empty': 'Sin archivo', 'ctx.remove': 'Quitar',
    'ctx.loaded': (w) => `Cargado: ${w.toLocaleString()} palabras`, 'ctx.parsing': 'Analizando…', 'ctx.could_not_read': 'No se pudo leer',
    'ctx.formats': 'Acepta: .pdf (con texto), .docx, .txt, .md. Los archivos se analizan en segundo plano y se guardan como texto dentro de la carpeta del perfil; un PDF escaneado, protegido o corrupto se rechaza con aviso.',
    'ctx.total': (w, n) => `${n} archivo${n === 1 ? '' : 's'} · ${w.toLocaleString()} palabras en el prompt`, 'ctx.truncated': ' · ⚠ truncado',
    'settings.memory': 'Usar memoria aprendida de sesiones anteriores', 'settings.project': 'Proyecto local de Claude (CLAUDE.md), opcional',
    'project.none': '— ninguno —', 'memory.words': (w) => (w ? `${w.toLocaleString()} palabras de memoria aprendida` : 'Aún sin memoria — aparece tras Terminar y analizar'),
    'strip.tone': 'Tono', 'strip.length': 'Extensión', 'tone.natural': 'Natural', 'tone.executive': 'Ejecutivo', 'tone.technical': 'Técnico',
    'len.concise': 'Breve', 'len.medium': 'Media', 'len.detailed': 'Detallada',
    'settings.language': 'Idioma de respuestas y transcripción', 'settings.ui_language': 'Idioma de la interfaz', 'lang.auto_short': 'Auto', 'lang.same': 'Igual que arriba',
    'lang.name.auto': 'AUTO', 'lang.name.en': 'EN', 'lang.name.es': 'ES',
    'settings.brain': 'Cerebro', 'settings.primary': 'Cerebro principal', 'settings.auto': 'Responder automáticamente cuando pregunten', on: 'Sí', off: 'No (solo Responder ahora)', off_plain: 'No',
    'settings.claude_model': 'Modelo de Claude', 'settings.claude_custom': 'Id de modelo Claude personalizado (opcional)', 'settings.gemini_model': 'Modelo de Gemini', 'settings.gemini_custom': 'Id de modelo Gemini personalizado (opcional)',
    'settings.words': 'Máx. palabras por tarjeta (extensión media)', 'settings.opacity': 'Opacidad del HUD', 'settings.save': 'Guardar ajustes del cerebro',
    'settings.loopback': 'Audio del sistema (lo que dicen ellos)', 'settings.mic': 'Micrófono (lo que digo yo)', 'audio.apply': 'Aplicar dispositivos',
    'settings.audio_help': 'Reproduce algo en la app de reuniones y habla: ambas barras deben moverse antes de iniciar. Windows: elige un dispositivo "[Loopback]" o "Audio del sistema vía Electron". macOS: instala BlackHole.',
    'dev.default': 'Dispositivo predeterminado', 'dev.off': 'Apagado', 'dev.electron': 'Audio del sistema vía Electron (Windows)', 'dev.electron_mic': 'Micrófono vía Electron',
    'hotkeys.title': 'Atajos globales',
    'stt.title': 'Motor de Transcripción', 'stt.engine': 'Motor', 'stt.lang_note': 'Idioma de transcripción',
    'stt.lang_help': 'Sigue el selector [EN|ES] del HUD (Alt+L). Deepgram reconecta al cambiar; el vocabulario IAM integrado (CyberArk, SailPoint, Entra ID, SAML, OIDC, PSM…) y los términos de tu perfil se envían como keyterms.',
    'stt.dg_key': 'Deepgram API key', 'stt.dg_help': 'Se guarda solo en config.json (local). Obtén una en console.deepgram.com → API Keys.',
    'stt.groq_key': 'Groq API key', 'stt.groq_help': 'console.groq.com → API Keys. Cada frase completa se envía a whisper-large-v3-turbo.',
    'stt.model': 'Modelo local', 'stt.device': 'Dispositivo', 'stt.vocab': 'Vocabulario adicional (keyterms, separados por coma)',
    'stt.vocab_help': 'Se añade a la lista IAM integrada y a los términos extraídos automáticamente de tu rol/CV.',
    'stt.save': 'Guardar motor de transcripción', 'toast.stt': 'Motor de transcripción guardado — reiniciando STT…',
    'stt.state.ready': 'listo', 'stt.state.connecting': 'conectando…', 'stt.state.loading': 'cargando modelo…', 'stt.state.error': 'error',
    'stt.keyterms': (n) => `${n} keyterms activos`, 'stt.fallback': 'Respaldo: Whisper local',
    'hk.screenshot': 'Capturar pregunta en pantalla', 'hk.force_answer': 'Responder ahora', 'hk.toggle_visibility': 'Ocultar / mostrar HUD', 'hk.toggle_listening': 'Silenciar / reanudar',
    'hk.followup_example': 'Seguimiento: ejemplo concreto', 'hk.followup_deepen': 'Seguimiento: profundizar', 'hk.followup_tldr': 'Seguimiento: más corto', 'hk.end_session': 'Terminar y analizar',
    'hk.summarize': 'Resumen de la llamada', 'hk.clear': 'Limpiar / cancelar', 'hk.toggle_language': 'Cambiar idioma', 'hk.settings': 'Configuración ⇄ HUD', 'hk.quit': 'Salir',
    'hk.ghost': 'Modo fantasma: los clics atraviesan el HUD', 'hk.auto_vision': 'Auto-visión: frame de pantalla cada 5 s adjunto a las respuestas',
    'hk.nudge_up': 'Mover HUD 40 px arriba', 'hk.nudge_down': 'Mover HUD 40 px abajo', 'hk.nudge_left': 'Mover HUD 40 px a la izquierda', 'hk.nudge_right': 'Mover HUD 40 px a la derecha',
    'hk.scroll_up': 'Desplazar respuestas arriba', 'hk.scroll_down': 'Desplazar respuestas abajo', 'hk.opacity_down': 'Fondo del HUD más transparente', 'hk.opacity_up': 'Fondo del HUD más opaco',
    'ghost.on': 'Modo fantasma ACTIVO — los clics pasan a la app de atrás (Alt+G para salir)', 'ghost.off': 'Modo fantasma desactivado', 'ghost.banner': 'fantasma · clic a través',
    'vision.on': 'Auto-visión ACTIVA — se adjuntará un frame de pantalla (cada 5 s) cuando la pregunta se refiera a la pantalla', 'vision.off': 'Auto-visión desactivada',
    'vision.err': (m) => `Fallo al capturar auto-visión: ${m}`, 'card.vision_attached': '👁 pantalla', 'opacity.hint': (v) => `fondo ${Math.round(v * 100)}%`,
    'card.updating': '↻ Actualizando con pregunta completa…', 'card.holding': '⏳ Esperando el resto de la pregunta…', 'card.segments': (n) => `${n} frases`,
    'turn.collecting': (n) => `turno · ${n} frase${n === 1 ? '' : 's'}`, 'turn.holding': (n) => `turno · ${n} · esperando…`, 'turn.generating': (n) => `turno · ${n} · respondiendo`,
    'turn.answered': (n) => `turno · ${n} · respondido`, 'turn.closed': 'siguiente: turno nuevo', 'turn.reset': 'Turno nuevo: lo siguiente que digan es una pregunta nueva', 'hk.new_turn': 'Turno nuevo (cerrar el turno del entrevistador)',
    'sessions.pick': 'Selecciona una sesión', 'sessions.report': 'Informe de insights', 'sessions.log': 'Transcripción', 'sessions.none': 'Aún no hay sesiones para este perfil.',
    'sessions.noreport': 'Esta sesión no tiene informe (no fue analizada).', 'sessions.lines': (l, s) => `${l} líneas · ${s} sugerencias`,
    'report.open': 'Abrir archivo', 'report.logs': 'Abrir carpeta',
    'btn.answer': 'Responder', 'btn.stop': '■ Terminar y analizar', 'tx.them': 'REMOTO', 'tx.me': 'YO', 'tx.interim': 'EN VIVO',
    'meter.sys': 'PC', 'meter.mic': 'MIC', 'btn.mute': 'Silenciar',
    'prov.button': 'Proveedores de IA', 'prov.title': 'Configura tu copiloto', 'prov.intro': 'Elige el cerebro (IA) que quieres usar y pega su clave. Solo necesitas uno; los demás quedan como respaldo automático. Las claves se guardan únicamente en tu equipo (config.json).',
    'prov.stt_title': 'Transcripción (voz a texto)', 'prov.default_lang': 'Idioma habitual del entrevistador', 'prov.auto_update': 'Actualizar la app automáticamente', 'prov.save': 'Guardar y continuar',
    'prov.primary': 'Principal', 'prov.key_ph': 'Clave API', 'prov.key_saved': '•••••••• (guardada)', 'prov.model_ph': 'modelo', 'prov.test': 'Probar', 'prov.models': 'Modelos', 'prov.get_key': 'Obtener clave ↗',
    'prov.ready': 'lista', 'prov.no_key': 'sin clave', 'prov.cli_ok': 'Claude Code instalado — usa tu sesión de Claude', 'prov.cli_missing': 'no instalado (npm i -g @anthropic-ai/claude-code y ejecuta "claude" una vez para iniciar sesión)',
    'prov.testing': 'probando…', 'prov.test_ok': (ms, m) => `✓ funciona (${ms} ms, ${m})`, 'prov.test_bad': (e) => `✗ ${e}`, 'prov.need_one': 'Agrega la clave de al menos un proveedor (o instala Claude Code).', 'prov.saved': 'Proveedores guardados',
    'upd.checking': 'buscando…', 'upd.available': (v) => `v${v} disponible`, 'upd.downloading': (v) => `descargando v${v}…`, 'upd.installing': (v) => `instalando v${v}…`, 'upd.restarting': 'reiniciando…',
    'upd.staged': (v) => `v${v} lista — se instala al terminar la sesión`, 'upd.up_to_date': (v) => `v${v} ✓`, 'upd.error': (e) => `actualización falló: ${e}`, 'upd.unconfigured': (v) => `v${v}`,
    'stt.decoder': (l, src) => `🎙 Transcribiendo en ${l.toUpperCase()}${src === 'text' ? ' (auto: cambiaron de idioma)' : src === 'low confidence' ? ' (auto: baja confianza)' : ''}`,
    'lang.flip': (l) => `Respuestas ahora en ${l === 'auto' ? 'AUTO (idioma de la pregunta)' : l.toUpperCase()}`, 'lang.rescue': 'Re-respondiendo la última pregunta en el nuevo idioma…', 'card.lang_auto': (l) => `AUTO·${l.toUpperCase()}`,
    'im.pc': 'Audio PC (Normal)', 'im.external': 'Llamada externa / Altavoz (por Mic)', 'im.toast.pc': '💻 Audio PC: el sonido del sistema es la voz remota; el mic es tu contexto',
    'im.toast.external': '📱 Llamada externa: todo lo que oiga el mic de la laptop es la voz remota y dispara respuestas', 'hk.input_mode': 'Modo de entrada: PC ⇄ llamada externa (mic)',
    'pm.yes_delete': 'Sí, eliminar', 'pm.confirm_delete_bar': (n) => `¿Eliminar el perfil "${n}" con sus documentos, registros y memoria?`,
    'ctx.upload': 'Subir archivo', 'ctx.upload_multi': 'Subir archivos', 'ctx.paste_short': 'Pegar texto', 'latency': (f, e) => `⚡ ${f != null ? f + 's' : '–'} · ${e}s`,
    'turn.skip': (r) => `sin responder: ${r}`,
    'status.listening': 'ESCUCHANDO', 'status.thinking': 'PENSANDO', 'status.muted': 'SILENCIADO', 'status.paused': 'EN PAUSA', 'status.analyzing': 'ANALIZANDO', 'status.offline': 'SIN CONEXIÓN',
    'answer.idle': 'Escuchando… las preguntas aparecerán aquí. Alt+A responde ahora.', 'answer.cleared': 'Limpio. Escuchando…', 'answer.none': 'Sin respuesta — revisa el login de Claude / GEMINI_API_KEY.',
    'meta.thinking': 'pensando…', 'meta.summarizing': 'resumiendo…', 'meta.fallback': 'usando respaldo…', 'meta.cancelled': 'cancelado', 'meta.noprovider': 'ningún proveedor respondió',
    'meta.debrief': 'analizando la sesión…', 'meta.vision': 'leyendo tu pantalla…', 'meta.followup': (k) => `seguimiento: ${k}…`,
    'fu.example': 'Ejemplo', 'fu.deepen': 'Profundizar', 'fu.tldr': 'Más corto', 'fu.pivot': 'Otro ejemplo', 'hk.followup_pivot': 'Seguimiento: cambiar a otro ejemplo',
    'story.used': (e) => `usado: ${e}`, 'story.none': 'sin proyecto nombrado', 'cont.rotate': 'ejemplo nuevo', 'cont.probe': 'misma historia · más a fondo', 'cont.pivot': 'rotado', 'cont.first': 'primer ejemplo',
    'toast.pivot': 'Cambiando a un ejemplo de otro proyecto…',
    'end.confirm': '¿Terminar esta sesión y generar el informe de insights? La transcripción se conserva en registros y las lecciones clave se agregan a la memoria del perfil.',
    'end.cancel': 'Cancelar', 'end.ok': 'Terminar y analizar',
    'toast.ready': 'Backend listo', 'toast.saved': 'Ajustes aplicados', 'toast.devices': 'Dispositivos aplicados', 'toast.pb': 'Playbook guardado', 'toast.lang': 'Idioma: ',
    'toast.style': 'Estilo: ', 'toast.shot': (kb) => `Pantalla capturada (${kb} KB) — analizando`, 'toast.profile': (n) => `Perfil: ${n}`,
    'toast.analyzed': (w) => `Informe guardado · ${w} palabras añadidas a la memoria`, 'toast.files': (n) => `${n} archivo(s) cargados`,
    'btn.unmute': 'Reanudar', 'btn.screen': 'Capturar pantalla', 'btn.setup': 'Configuración', 'btn.end': 'Fin', 'btn.exit': 'Salir', 'settings.font': 'Tamaño del texto (px)',
    'end.noanalysis': 'Salir sin analizar', 'toast.no_analysis': 'Sesión terminada sin análisis (no se grabó transcripción)',
    'toast.exited': 'Sesión terminada — de vuelta a Ajustes', 'diag.stt': 'STT', 'diag.chunks': 'bloques de audio', 'diag.seg': 'segmentos', 'diag.err': 'último error',
    'diag.never': 'Aún no llega audio — revisa los dispositivos', 'diag.notarmed': 'Hay audio; la transcripción inicia con ▶ Iniciar escucha',
    'feed.jump': '↓ Ir a la última respuesta', 'end.title': '¿Terminar esta sesión?', 'card.screen': 'Pantalla', 'card.summary': 'Resumen',
    'card.followup': (k) => `Seguimiento · ${k}`, 'card.answer': 'Respuesta', 'card.opener': 'apertura', 'card.ctx': (n) => `${n} fragmento${n === 1 ? '' : 's'} relevante${n === 1 ? '' : 's'}`,
    'ctx.src_file': 'Subir archivo', 'ctx.src_text': 'Pegar texto', 'ctx.paste_btn': 'Pegar / editar texto…', 'ctx.paste_save': 'Guardar texto', 'ctx.paste_clear': 'Borrar texto',
    'ctx.paste_help': 'Pega una descripción de puesto, tu CV o notas en markdown. Se guarda en profiles/<nombre>/manual_context/ y se usa en lugar del archivo subido para este apartado.',
    'ctx.manual': (w) => `Texto pegado: ${w.toLocaleString()} palabras (se usa en vez del archivo)`, 'ctx.words': (w) => `${w.toLocaleString()} palabras`, 'toast.manual': 'Texto guardado',
    'btn.setup': 'Configuración', 'btn.end': 'Fin',
    'pm.archive': '🗄 Archivar perfil', 'pm.archived': 'Perfiles archivados', 'pm.bank': '🏦 Banco de documentos',
    'pm.archived_help': 'Los perfiles archivados conservan su configuración, documentos y registros de sesión. Restáuralos cuando quieras.',
    'pm.restore': 'Restaurar', 'pm.none_archived': 'No hay perfiles archivados.', 'pm.confirm_archive': (n) => `¿Archivar el perfil "${n}"? Se mueve a profiles_archived/ y desaparece del selector.`,
    'profile.job_role': 'Puesto (job_role)', 'profile.company': 'Empresa (company)', 'profile.default_language': 'Idioma por defecto de transcripción y respuestas',
    'profile.default_playbook': 'Playbook por defecto (del banco)', 'bank.pick': 'Elegir del Banco…', 'bank.pick_multi': 'Elegir del Banco…', 'bank.pick_pb': 'Elegir Playbook del Banco…',
    'bank.title': 'Banco de documentos — Experiencia de apoyo', 'bank.help': 'Marca los archivos del banco que quieres adjuntar a este perfil. Se combinan como texto en el apartado de experiencia.',
    'bank.attach': 'Adjuntar seleccionados', 'bank.empty': 'El banco está vacío — sube o pega algo primero.', 'bank.attached': (n) => `${n} archivo(s) del banco adjuntados`, 'bank.none_pb': '— ninguno / personalizado —',
    'sessions.profile_filter': 'Perfil', 'sessions.archived_tag': '(archivado)', 'sessions.duration': (m) => `${m} min`, 'sessions.noanalysis': 'Esta sesión no tiene análisis (terminó sin "Terminar y analizar").',
    'an.grade': 'Calificación general', 'an.clarity': 'Claridad y concisión', 'an.depth': 'Profundidad técnica', 'an.examples': 'Estructura de ejemplos', 'an.role': 'Alineación con el rol',
    'an.summary': 'De qué trató la sesión', 'an.decisions': 'Decisiones, acuerdos y próximos pasos', 'an.qa': 'Pregunta por pregunta (lo que dije vs. respuesta ideal)',
    'an.said': 'Lo que dije', 'an.good': 'Funcionó bien', 'an.tighten': 'Ajustar', 'an.ideal': 'Respuesta ideal', 'an.pacing': 'Ritmo y claridad', 'an.well': 'Qué salió bien',
    'an.adjust': 'Ajustes prioritarios para la próxima', 'an.transcript': 'Transcripción completa', 'an.copy': 'Copiar transcripción', 'an.none': '(nada registrado)', 'an.turns': (n, s) => `${n} turnos · ${s} sugerencias`,
    'bank.manage': 'Administrar el banco', 'bank.confirm_delete': (n) => `¿Quitar "${n}" del banco? Los perfiles que ya lo adjuntaron conservan su copia.`, 'bank.cat.roles': 'Descripciones de puesto', 'bank.cat.cvs': 'CVs / perfiles', 'bank.cat.experience': 'Experiencia de apoyo', 'bank.cat.playbooks': 'Playbooks',
    'focus.label': 'Enfoque de esta sesión (Opcional):', 'focus.tech': 'Entrevista Técnica', 'focus.exec': 'Entrevista Ejecutiva / CISO', 'focus.incident': 'Incidente en Vivo',
    'focus.roadmap': 'Plan Estratégico / Roadmap', 'focus.client': 'Cliente / Arquitectura', 'focus.pill': 'Enfoque', 'focus.apply': 'Aplicar',
    'focus.ph': 'Ej: Ronda 2 con el Director de IAM — enfocar en migración a CyberArk Privilege Cloud y gobierno de NHIs (puede quedar vacío)...',
    'focus.edit_ph': 'Ej: Enfocar ahora en controles de auditoría SOX… (Enter para aplicar, Esc para cerrar)', 'focus.saved': 'Enfoque aplicado', 'focus.cleared': 'Enfoque limpiado', 'focus.none': 'Sin enfoque (general)',
    'sessions.focus': 'Enfoque',
    'gemini.listed': (n) => `${n} modelos Gemini disponibles`,
  },
};
Object.assign(I18N.en, {
  'btn.screen': 'Screen', 'btn.setup': 'Setup', 'btn.end': 'End', 'setup.start': 'Start listening', 'setup.resume': 'Back to the HUD',
  'stealth': 'Hidden from screen sharing', 'prov.button': 'AI providers', 'prov.default_lang': 'Language the other person usually speaks',
  'im.pc_short': 'This computer', 'im.external_short': 'Phone', 'im.pc_tiny': 'PC', 'im.external_tiny': 'Phone',
  'chk.stt': 'Transcription', 'chk.llm': 'AI answers', 'chk.ctx': 'Your context', 'chk.audio': 'Where the call comes from',
  'chk.offline': 'The engine is not running yet…', 'chk.stt_loading': (e) => `${e} is starting…`, 'chk.stt_ok': (e) => `${e} ready`,
  'chk.llm_ok': (n, m, k) => `${n} · ${m}${k ? ` · ${k} backup${k > 1 ? 's' : ''}` : ''}`, 'chk.llm_none': 'No provider configured — click to add one',
  'chk.llm_fallback': (n, f) => `${n} is not ready; ${f} will answer`, 'chk.llm_broken': (n, why) => `${why} Click to fix.`,
  'chk.ctx_ok': (name, n, w) => `${name}: ${n} document${n === 1 ? '' : 's'}, ${w.toLocaleString()} words`, 'chk.ctx_none': (name) => `${name} has no documents — answers will be generic`,
  'err.claude_auth': 'The Claude Code session expired.', 'err.key': 'The API key is wrong or was revoked.', 'err.model': 'That model does not exist for this account. Press "Models" and pick one from the list.',
  'err.quota': 'Out of quota or credit on this account.', 'err.network': 'The service could not be reached (network or timeout).', 'err.missing': 'Not set up on this computer yet.',
  'err.empty': 'It returned an empty answer.',
  'act.login': 'Sign in to Claude', 'act.providers': 'Open AI providers', 'act.retry': 'Try again', 'act.report': 'Report',
  'fail.title': 'No answer could be generated', 'fail.none': 'No AI provider is configured.', 'fail.fallback': (n, why) => `${n} failed (${why}) — answered with the backup`,
  'login.opened': 'A terminal opened: finish the sign-in there, then press "Test" on Claude.', 'hint.echo': 'Your microphone is picking up the call from the speakers. Use headphones so your own turns are detected correctly.',
  'report.button': 'Report a problem', 'report.title': 'Report a problem',
  'report.what': 'Creates a diagnostic report and files it as an issue on the project\'s GitHub. It includes the app version, your system, the provider names and the latest error messages. API keys, e-mail addresses, your user folder, profile names and everything said or answered in a call are removed first.',
  'report.note_ph': 'What were you doing when it failed? (optional)', 'report.send': 'Create report', 'report.cancel': 'Cancel', 'report.no_errors': 'No errors recorded in this session.',
  'report.sent': (u) => `Report filed: ${u}`, 'report.opened': 'GitHub opened with the report filled in — review it and press "Submit new issue". A full copy is on your clipboard.',
  'report.saved': (f) => `Report saved to ${f}`, 'report.api_failed': (e) => `Could not file it automatically (${e}); opening GitHub instead.`,
  'prov.failed': 'failing', 'upd.none': (v) => `You already have the latest version (v${v}).`, 'upd.checking_long': 'Checking GitHub for a newer version…', 'status.listening': 'Listening', 'status.loading': 'Starting…', 'status.muted': 'Muted', 'status.paused': 'Paused', 'status.analyzing': 'Analyzing…', 'status.thinking': 'Answering…', 'status.offline': 'Offline',
});
Object.assign(I18N.es, {
  'btn.screen': 'Pantalla', 'btn.setup': 'Ajustes', 'btn.end': 'Terminar', 'setup.start': 'Empezar a escuchar', 'setup.resume': 'Volver al HUD',
  'stealth': 'Oculta al compartir pantalla', 'prov.button': 'Proveedores de IA', 'prov.default_lang': 'Idioma en que suele hablar la otra persona',
  'im.pc_short': 'Este equipo', 'im.external_short': 'Teléfono', 'im.pc_tiny': 'PC', 'im.external_tiny': 'Tel',
  'chk.stt': 'Transcripción', 'chk.llm': 'Respuestas con IA', 'chk.ctx': 'Tu contexto', 'chk.audio': 'De dónde viene la llamada',
  'chk.offline': 'El motor todavía no está en marcha…', 'chk.stt_loading': (e) => `${e} está arrancando…`, 'chk.stt_ok': (e) => `${e} lista`,
  'chk.llm_ok': (n, m, k) => `${n} · ${m}${k ? ` · ${k} de respaldo` : ''}`, 'chk.llm_none': 'Ningún proveedor configurado — haz clic para añadir uno',
  'chk.llm_fallback': (n, f) => `${n} no está listo; responderá ${f}`, 'chk.llm_broken': (n, why) => `${why} Clic para arreglarlo.`,
  'chk.ctx_ok': (name, n, w) => `${name}: ${n} documento${n === 1 ? '' : 's'}, ${w.toLocaleString()} palabras`, 'chk.ctx_none': (name) => `${name} no tiene documentos — las respuestas serán genéricas`,
  'err.claude_auth': 'La sesión de Claude Code caducó.', 'err.key': 'La clave no es válida o fue revocada.', 'err.model': 'Ese modelo no existe para esta cuenta. Pulsa «Modelos» y elige uno de la lista.',
  'err.quota': 'La cuenta se quedó sin cuota o crédito.', 'err.network': 'No se pudo conectar con el servicio (red o tiempo de espera).', 'err.missing': 'Todavía no está configurado en este equipo.',
  'err.empty': 'Devolvió una respuesta vacía.',
  'act.login': 'Iniciar sesión en Claude', 'act.providers': 'Abrir proveedores de IA', 'act.retry': 'Reintentar', 'act.report': 'Reportar',
  'fail.title': 'No se pudo generar la respuesta', 'fail.none': 'No hay ningún proveedor de IA configurado.', 'fail.fallback': (n, why) => `${n} falló (${why}) — respondió el respaldo`,
  'login.opened': 'Se abrió una terminal: termina ahí el inicio de sesión y luego pulsa «Probar» en Claude.', 'hint.echo': 'Tu micrófono está captando la llamada por los altavoces. Usa audífonos para que tus turnos se detecten bien.',
  'report.button': 'Reportar problema', 'report.title': 'Reportar un problema',
  'report.what': 'Crea un informe de diagnóstico y lo registra como incidencia (issue) en el GitHub del proyecto. Incluye la versión de la app, tu sistema, los nombres de los proveedores y los últimos mensajes de error. Antes se eliminan las claves, los correos, tu carpeta de usuario, los nombres de perfiles y todo lo que se dijo o respondió en la llamada.',
  'report.note_ph': '¿Qué estabas haciendo cuando falló? (opcional)', 'report.send': 'Crear informe', 'report.cancel': 'Cancelar', 'report.no_errors': 'No hay errores registrados en esta sesión.',
  'report.sent': (u) => `Informe registrado: ${u}`, 'report.opened': 'Se abrió GitHub con el informe ya escrito: revísalo y pulsa «Submit new issue». Tienes una copia completa en el portapapeles.',
  'report.saved': (f) => `Informe guardado en ${f}`, 'report.api_failed': (e) => `No se pudo registrar automáticamente (${e}); se abre GitHub.`,
  'prov.failed': 'con error', 'upd.none': (v) => `Ya tienes la última versión (v${v}).`, 'upd.checking_long': 'Buscando una versión más nueva en GitHub…', 'status.listening': 'Escuchando', 'status.loading': 'Arrancando…', 'status.muted': 'En silencio', 'status.paused': 'En pausa', 'status.analyzing': 'Analizando…', 'status.thinking': 'Respondiendo…', 'status.offline': 'Sin conexión',
});
let uiLang = 'en';
const t = (key, ...args) => {
  const v = (I18N[uiLang] && I18N[uiLang][key]) ?? I18N.en[key] ?? key;
  return typeof v === 'function' ? v(...args) : v;
};
function applyUiLanguage(lang) {
  uiLang = lang === 'es' ? 'es' : 'en';
  document.documentElement.lang = uiLang;
  $$('[data-i18n]').forEach((n) => {
    if (n.id === 'answer-body' && !n.classList.contains('empty')) return;
    n.textContent = t(n.getAttribute('data-i18n'));
  });
  $$('[data-i18n-ph]').forEach((n) => (n.placeholder = t(n.getAttribute('data-i18n-ph'))));
  renderHotkeys();
  renderStatus();
}
function resolveUiLang(uiLanguage, language) {
  // The interface defaults to Spanish; the transcription/answer language is a separate setting (default EN).
  if (uiLanguage === 'es' || uiLanguage === 'en') return uiLanguage;
  return /^es/i.test(navigator.language || '') ? 'es' : 'en';
}

// ------------------------------------------------------------------ state
let mode = 'setup';
let debriefTarget = null;
let currentGen = null, buffer = '', streaming = false, renderTimer = null;   // debrief stream (sessions tab)
let lastStatus = {}, hotkeys = {}, platform = 'win32', lastManifest = null, lastDevices = null;
let profileList = [], projectList = [], sessionList = [], currentSession = null, sessionKind = 'report';
const localLevels = { them: 0, me: 0 };
const toastTimers = {};

// ------------------------------------------------------------------ markdown
function escapeHtml(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function inline(s) { return escapeHtml(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>'); }
function renderMarkdown(md) {
  const lines = md.replace(/\r/g, '').split('\n');
  const out = [];
  let depth = 0;
  const closeTo = (d) => { while (depth > d) { out.push('</ul>'); depth--; } };
  for (const raw of lines) {
    const m = raw.match(/^(\s*)[-*•]\s+(.*)$/);
    if (m) {
      const want = m[1].length >= 2 ? 2 : 1;
      closeTo(want);
      while (depth < want) { out.push('<ul>'); depth++; }
      const text = m[2];
      let cls = '';
      if (/^\*\*(say next|di(lo)? (ahora|siguiente)|siguiente|qué decir|que decir)/i.test(text)) cls = ' class="say"';
      else if (/^\*\*(watch out|ojo|cuidado|atenci)/i.test(text)) cls = ' class="watch"';
      out.push(`<li${cls}>${inline(text)}</li>`);
      continue;
    }
    const line = raw.trim();
    if (!line) continue;
    closeTo(0);
    if (/^\*\*(q|p):\*\*/i.test(line)) out.push(`<div class="q">${inline(line)}</div>`);
    else if (/^#{1,4}\s+/.test(line)) { const lvl = Math.min(4, line.match(/^#+/)[0].length); out.push(`<h${lvl}>${inline(line.replace(/^#{1,4}\s+/, ''))}</h${lvl}>`); }
    else if (/^\*\*[^*]+\*\*$/.test(line)) out.push(`<h4>${inline(line.replace(/\*\*/g, ''))}</h4>`);
    else out.push(`<p>${inline(line)}</p>`);
  }
  closeTo(0);
  return out.join('');
}
function scheduleRender() {   // debrief stream only (answers use the card feed below)
  if (renderTimer) return;
  renderTimer = requestAnimationFrame(() => {
    renderTimer = null;
    if (!debriefTarget) return;
    // The analysis arrives as JSON; show progress while it streams, the structured card replaces it at the end.
    const words = buffer.split(/\s+/).filter(Boolean).length;
    debriefTarget.innerHTML = `<div class="apanel"><h4>${escapeHtml(t('meta.debrief'))}</h4><p class="dim">${words} tokens${streaming ? ' <span class="cursor"></span>' : ''}</p></div>`;
  });
}

// ------------------------------------------------------------------ answer feed (scrollable cards)
const cards = new Map(); // gen_id -> { el, opener, full, openerText, fullText, timers }
const turnCards = new Map(); // v16: turn_id -> card (one card per remote turn, replaced in place when the speaker keeps talking)
let latestCard = null;
let userScrolledUp = false;
const feed = () => $('#feed');
function feedAtBottom() { const f = feed(); return f.scrollHeight - f.scrollTop - f.clientHeight < 40; }
feedInit();
function feedInit() {
  const f = feed();
  f.addEventListener('scroll', () => {
    userScrolledUp = !feedAtBottom();
    $('#jump-latest').classList.toggle('hidden', !userScrolledUp || !latestCard);
  });
  $('#jump-latest').addEventListener('click', () => { userScrolledUp = false; scrollToLatest(true); });
}
function scrollToLatest(force = false) {
  if (!latestCard) return;
  if (userScrolledUp && !force) { $('#jump-latest').classList.remove('hidden'); return; }
  const f = feed();
  f.scrollTo({ top: f.scrollHeight, behavior: 'smooth' });
  $('#jump-latest').classList.add('hidden');
}
function cardKind(ev) {
  if (ev.mode === 'vision') return t('card.screen');
  if (ev.mode === 'summary') return t('card.summary');
  if (ev.mode === 'followup') return t('card.followup', ev.kind ? t('fu.' + ev.kind) : '');
  return t('card.answer');
}
function setCardBadge(card, cls, text) {
  let b = card.el.querySelector(`.acard-head .badge.${cls}`);
  if (!text) { if (b) b.remove(); return; }
  if (!b) { b = document.createElement('span'); b.className = `badge ${cls}`; card.el.querySelector('.acard-head .kind').after(b); }
  b.textContent = text;
}
/** v16: an answer for a turn that already has a card is streamed INTO that card (same turn_id), never a new one. */
function reuseCard(card, ev) {
  if (card.gen_id !== ev.gen_id) cards.delete(card.gen_id);   // late tokens / llm_end of the aborted generation must not touch this card
  cards.set(ev.gen_id, card);
  card.gen_id = ev.gen_id;
  if (ev.turn_id != null) { card.turn_id = ev.turn_id; turnCards.set(ev.turn_id, card); }
  card.openerText = ''; card.fullText = ''; card.openerMs = null; card.storyText = ''; card.failed = false;
  card.streaming = { opener: false, full: false };
  card.retrieval = ev.retrieval || card.retrieval || [];
  card.el.classList.remove('updating');
  setCardBadge(card, 'updating', '');
  setCardBadge(card, 'continuity', '');
  setCardBadge(card, 'lang', '');
  const q = card.el.querySelector('.acard-head .q');
  if (q && ev.question) { q.textContent = ev.question; q.title = ev.question; }
  const ts = card.el.querySelector('.acard-head .ts'); if (ts) ts.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  card.meta.textContent = '';
  card.full.innerHTML = ''; card.opener.textContent = '';
  for (const c of cards.values()) c.el.classList.remove('active');
  card.el.classList.add('active');
  latestCard = card;
  scrollToLatest();
  return card;
}
function newCard(ev) {
  const idle = $('#answer-body'); if (idle) idle.remove();
  const el = document.createElement('article'); el.className = 'acard active';
  const head = document.createElement('div'); head.className = 'acard-head';
  const kind = document.createElement('span'); kind.className = 'kind'; kind.textContent = cardKind(ev);
  const q = document.createElement('span'); q.className = 'q'; q.textContent = ev.question || ''; q.title = ev.question || '';
  const ts = document.createElement('span'); ts.className = 'ts'; ts.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  head.append(kind, q, ts);
  if (ev.vision_attached) { const vb = document.createElement('span'); vb.className = 'badge vision'; vb.textContent = t('card.vision_attached'); vb.title = 'Auto-vision frame attached to this answer'; kind.after(vb); }
  const cont = ev.mode === 'followup' && ev.kind === 'pivot' ? 'pivot' : ev.continuity;
  if (cont && cont !== 'first' && cont !== 'direct') { const b = document.createElement('span'); b.className = `badge continuity ${cont}`; b.textContent = t('cont.' + cont); kind.after(b); }
  const opener = document.createElement('div'); opener.className = 'opener';
  const full = document.createElement('div'); full.className = 'full';
  const meta = document.createElement('div'); meta.className = 'acard-meta';
  el.append(head, opener, full, meta);
  feed().appendChild(el);
  for (const c of cards.values()) c.el.classList.remove('active');
  const card = { el, opener, full, meta, openerText: '', fullText: '', timer: null, streaming: { opener: false, full: false }, retrieval: ev.retrieval || [], gen_id: ev.gen_id, turn_id: ev.turn_id || null };
  cards.set(ev.gen_id, card);
  if (ev.turn_id != null) turnCards.set(ev.turn_id, card);
  latestCard = card;
  if (cards.size > 80) { const [oldId, old] = cards.entries().next().value; cards.delete(oldId); if (old !== latestCard && old.gen_id === oldId) { old.el.remove(); if (old.turn_id != null && turnCards.get(old.turn_id) === old) turnCards.delete(old.turn_id); } }
  scrollToLatest();
  return card;
}
function renderSpeech(text) {
  // Spoken prose: blank-line paragraphs. Strip any stray markdown the model might still emit.
  const clean = text.replace(/\r/g, '').replace(/^\s*[-*•]\s+/gm, '').replace(/^#{1,6}\s+/gm, '').replace(/\*\*/g, '');
  const paras = clean.split(/\n\s*\n/).map((p) => p.replace(/\n+/g, ' ').trim()).filter(Boolean);
  return paras.map((p) => `<p>${escapeHtml(p)}</p>`).join('');
}
function paintCard(card) {
  if (card.timer) return;
  card.timer = requestAnimationFrame(() => {
    card.timer = null;
    if (card.failed) return;
    card.opener.textContent = card.openerText.trim();
    card.full.innerHTML = renderSpeech(card.fullText) + (card.streaming.full ? '<span class="cursor"></span>' : '');
    if (!userScrolledUp && card === latestCard) feed().scrollTop = feed().scrollHeight;
  });
}
function cardMeta(card, ev) {
  const s = lastStatus.settings || {};
  const parts = [];
  if (ev.provider) {
    const model = ((lastStatus.providers_info || {})[ev.provider] || {}).model;
    parts.push(`${ev.provider}${model ? ' · ' + model : ''}${ev.warm === true ? ' · warm' : ev.warm === false ? ' · cold' : ''} · ${t('tone.' + (s.tone || 'natural'))}/${t('len.' + (s.length || 'medium'))} · ${ev.first_token_s != null ? 'first word ' + ev.first_token_s + 's · ' : ''}${ev.elapsed_s}s`);
  } else if (ev.cancelled) parts.push(t('meta.cancelled'));
  else parts.push(t('meta.noprovider'));
  if (ev.provider && (ev.errors || []).length) { const f = splitError(ev.errors[0]); parts.push(t('fail.fallback', provLabel(f.provider), explainError(f.provider, f.message).text.replace(/\.$/, ''))); }
  if (card.openerMs) parts.push(`${t('card.opener')} ${card.openerMs}s`);
  if (card.retrieval && card.retrieval.length) parts.push(t('card.ctx', card.retrieval.length));
  if (card.storyText) parts.push(card.storyText);
  card.meta.textContent = parts.join(' · ');
}
function clearAnswer() {
  for (const c of cards.values()) c.el.remove();
  cards.clear(); turnCards.clear(); latestCard = null; userScrolledUp = false;
  renderStory(null);
  const idle = document.createElement('div'); idle.id = 'answer-body'; idle.className = 'empty'; idle.textContent = t('answer.cleared');
  feed().appendChild(idle);
  $('#jump-latest').classList.add('hidden');
  renderStatus();
}

// ------------------------------------------------------------------ helpers
function setPill(pill, state, label) {
  if (!pill) return;
  pill.classList.remove('ok', 'warn', 'bad', 'busy');
  if (state) pill.classList.add(state);
  if (label !== undefined) pill.querySelector('span').textContent = label;
}
function toast(msg, bad = false, action = null) {
  const id = mode === 'live' ? 'toast-live' : 'toast-setup';
  const el = $('#' + id);
  el.textContent = msg;
  el.classList.toggle('bad', bad);
  if (action) el.appendChild(actionButton(action));
  clearTimeout(toastTimers[id]);
  toastTimers[id] = setTimeout(() => { el.textContent = ''; el.classList.remove('bad'); }, action ? 15000 : 7000);
}

// ------------------------------------------------------------------ 1.0.1: errors a person can act on
const recentErrors = [];
function rememberError(message) {
  const m = String(message || '').trim(); if (!m) return;
  if (recentErrors.length && recentErrors[recentErrors.length - 1] === m) return;
  recentErrors.push(m); if (recentErrors.length > 20) recentErrors.shift();
  const c = $('#report-count'); if (c) { c.textContent = String(recentErrors.length); c.classList.remove('hidden'); }
}
function provLabel(name) {
  const p = (lastStatus.providers_info || {})[name];
  return p ? String(p.label).replace(/\s*\(.*\)$/, '') : name || '';
}
function splitError(line) {
  const m = /^([a-z]+): ([\s\S]*)$/.exec(String(line || ''));
  return m && (lastStatus.providers_info || {})[m[1]] ? { provider: m[1], message: m[2] } : { provider: '', message: String(line || '') };
}
/** Turn a raw provider / backend message into: what happened, and the one action that fixes it. */
function explainError(provider, message) {
  const m = String(message || '');
  const out = (code, action) => ({ code, text: t('err.' + code), action, raw: m });
  if (/oauth|session expired|failed to authenticate|\/login|not logged in/i.test(m) && (provider === 'claude' || /claude|oauth/i.test(m))) return out('claude_auth', 'login');
  if (/\b429\b|quota|rate.?limit|billing|credit|insufficient/i.test(m)) return out('quota', 'providers');
  if (/\b401\b|\b403\b|invalid api key|api key not valid|incorrect api key|unauthori[sz]ed|authenticat|permission/i.test(m)) return out('key', 'providers');
  if (/\b404\b|model.*(not found|does not exist|not supported)|not found.*model|unknown model/i.test(m)) return out('model', 'providers');
  if (/timed? ?out|ENOTFOUND|ECONN|connection|network|getaddrinfo|unreachable|name resolution/i.test(m)) return out('network', 'retry');
  if (/not installed|not on path|no api key|not configured|missing api key|is not recognized|command not found/i.test(m)) return out('missing', 'providers');
  if (/empty response/i.test(m)) return out('empty', 'retry');
  return { code: 'other', text: m.slice(0, 220), action: provider ? 'providers' : null, raw: m };
}
const ACTIONS = {
  login: { label: 'act.login', run: () => window.copilot.send({ type: 'claude_login' }) },
  providers: { label: 'act.providers', run: () => { if (mode === 'live') window.copilot.send({ type: 'enter_setup' }); setTimeout(() => openProviders(false), mode === 'live' ? 250 : 0); } },
  retry: { label: 'act.retry', run: () => window.copilot.send({ type: 'generate' }) },
  report: { label: 'act.report', run: () => openReport() },
};
function actionButton(name, primary = false) {
  const a = ACTIONS[name], b = document.createElement('button');
  b.className = `btn small nodrag${primary ? ' primary' : ''}`; b.textContent = t(a.label);
  b.addEventListener('click', (e) => { e.stopPropagation(); a.run(); });
  return b;
}
/** A failed answer says which provider failed, why, and offers the fix — never just "no provider answered". */
function renderFailure(card, ev) {
  card.failed = true;
  const errs = (ev.errors || []).map(splitError);
  const box = document.createElement('div'); box.className = 'fail';
  const h = document.createElement('b'); h.textContent = t('fail.title'); box.appendChild(h);
  const acts = new Set();
  if (!errs.length) { const p = document.createElement('p'); p.textContent = t('fail.none'); box.appendChild(p); acts.add('providers'); }
  const ul = document.createElement('ul');
  for (const e of errs) {
    const x = explainError(e.provider, e.message);
    const li = document.createElement('li');
    const name = document.createElement('strong'); name.textContent = provLabel(e.provider) || 'App';
    const why = document.createElement('span'); why.textContent = ` ${x.text}`;
    li.append(name, why);
    if (x.code !== 'other') { const raw = document.createElement('small'); raw.textContent = x.raw.slice(0, 160); li.appendChild(raw); }
    ul.appendChild(li);
    if (x.action) acts.add(x.action);
    rememberError(`${e.provider || 'app'}: ${e.message}`);
  }
  if (errs.length) box.appendChild(ul);
  const row = document.createElement('div'); row.className = 'fail-actions';
  const order = ['login', 'providers', 'retry'].filter((a) => acts.has(a));
  if (!order.includes('retry')) order.push('retry');
  order.forEach((a, i) => row.appendChild(actionButton(a, i === 0)));
  row.appendChild(actionButton('report'));
  box.appendChild(row);
  card.opener.textContent = ''; card.full.innerHTML = ''; card.full.appendChild(box);
  card.el.classList.add('failed');
}

// ------------------------------------------------------------------ 1.0.1: problem report
function openReport() {
  const list = $('#report-errors'); list.innerHTML = '';
  const items = recentErrors.slice(-6);
  if (!items.length) { const li = document.createElement('li'); li.className = 'dim'; li.textContent = t('report.no_errors'); list.appendChild(li); }
  for (const m of items) { const li = document.createElement('li'); li.textContent = m.slice(0, 200); list.appendChild(li); }
  $('#report-result').textContent = '';
  $('#report-modal').classList.remove('hidden');
  setTimeout(() => $('#report-note').focus(), 30);
}
function onReportStatus(ev) {
  const msg = ev.state === 'sent' ? t('report.sent', ev.url) : ev.state === 'opened' ? t('report.opened') : ev.state === 'api_failed' ? t('report.api_failed', ev.error || '') : t('report.saved', ev.file || '');
  if ($('#report-modal').classList.contains('hidden')) toast(msg, ev.state === 'api_failed');
  else $('#report-result').textContent = msg;
  if (ev.state !== 'api_failed') { recentErrors.length = 0; $('#report-count').classList.add('hidden'); $('#report-note').value = ''; setTimeout(() => $('#report-modal').classList.add('hidden'), 3500); toast(msg); }
}
window.addEventListener('error', (e) => { try { window.copilot.send({ type: 'renderer_error', message: `${e.message} @ ${String(e.filename || '').split('/').pop()}:${e.lineno}` }); } catch {} });
window.addEventListener('unhandledrejection', (e) => { try { window.copilot.send({ type: 'renderer_error', message: `unhandled: ${String((e.reason && e.reason.message) || e.reason).slice(0, 300)}` }); } catch {} });
function prettyAccel(a) {
  if (!a) return '';
  return a.replace('CommandOrControl', platform === 'darwin' ? '⌘' : 'Ctrl').replace('Alt', platform === 'darwin' ? '⌥' : 'Alt').replace('Shift', '⇧');
}
function fillSelect(select, options, current) {
  const list = [...options];
  if (current && !list.some((o) => (typeof o === 'string' ? o : o.id) === current)) list.unshift(current);
  select.innerHTML = '';
  for (const o of list) {
    const opt = document.createElement('option');
    opt.value = typeof o === 'string' ? o : o.id;
    opt.textContent = typeof o === 'string' ? o : o.name;
    if (opt.value === current) opt.selected = true;
    select.appendChild(opt);
  }
}

// ------------------------------------------------------------------ modes
function setMode(m) {
  mode = m;
  document.documentElement.dataset.mode = m;
  $('#setup').classList.toggle('hidden', m !== 'setup');
  $('#live').classList.toggle('hidden', m !== 'live');
  if (m === 'live' && autoVision.enabled) autoVisionTick();
  if (m !== 'live' && ghost) { ghost = false; renderGhost(); }
  if (m === 'setup') { loadContext(); if (activeTab === 'sessions') loadSessions(); }
  renderStatus();
}
function startLive() {
  clearTimeout(focusTimer);
  focusText = ($('#focus-input').value || '').trim();
  window.copilot.send({ type: 'start_live', focus: focusText });
  window.copilot.send({ type: 'enter_live' });
  renderFocus();
}
$('#btn-start').addEventListener('click', () => {
  if (lastStatus.armed) window.copilot.send({ type: 'enter_live' });
  else startLive();
});
$('#btn-setup').addEventListener('click', () => window.copilot.send({ type: 'enter_setup' }));
$('#btn-min').addEventListener('click', () => window.copilot.send({ type: 'minimize' }));
$('#btn-quit').addEventListener('click', () => window.copilot.send({ type: 'quit' }));
$('#btn-report').addEventListener('click', () => openReport());
$('#report-cancel').addEventListener('click', () => $('#report-modal').classList.add('hidden'));
$('#report-send').addEventListener('click', () => { $('#report-result').textContent = '…'; window.copilot.send({ type: 'report_problem', note: $('#report-note').value.trim() }); });
$$('.check[data-go]').forEach((b) => b.addEventListener('click', () => { const go = b.dataset.go; if (go === 'providers') openProviders(false); else showTab(go); }));

// ------------------------------------------------------------------ tabs
let activeTab = 'profile';
$$('.tab[data-tab]').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
function showTab(name) {
  activeTab = name;
  $$('.tab[data-tab]').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
  $$('.tabpane').forEach((p) => p.classList.toggle('hidden', p.dataset.pane !== name));
  if (name === 'audio') window.copilot.send({ type: 'list_audio_devices' });
  if (name === 'sessions') loadSessions();
  if (name === 'profile') { loadContext(); loadProjects(); refreshBank(); }
  if (name === 'playbook') refreshBank();
}

// ------------------------------------------------------------------ status rendering
function renderStatus() {
  const ev = lastStatus;
  if (!ev.type) return;
  const p = ev.providers || {}, s = ev.settings || {};
  // setup header pills
  setPill($('#pill-link-setup'), ev.backend_link === false ? 'bad' : 'ok', 'LINK');
  if (ev.stt_error) setPill($('#pill-stt-setup'), 'bad', 'STT ERROR');
  else setPill($('#pill-stt-setup'), ev.stt_ready ? 'ok' : 'busy', ev.stt_ready ? 'STT' : 'STT LOADING');
  const primary = s.primary || 'claude';
  renderPreflight(ev);
  $('#live-banner').classList.toggle('hidden', !ev.armed);
  $('#btn-start').querySelector('span').textContent = ev.armed ? t('setup.resume') : t('setup.start');
  // live header
  const live = $('#pill-live');
  let st = 'ok', label = t('status.listening');
  if (!ev.stt_ready && !ev.stt_error) { st = 'busy'; label = t('status.loading'); }
  if (!ev.listening) { st = 'warn'; label = t('status.muted'); }
  if (!ev.armed) { st = 'warn'; label = t('status.paused'); }
  if (ev.session && ev.session.analyzing) { st = 'busy'; label = t('status.analyzing'); }
  if (streaming || [...cards.values()].some((c) => c.streaming.full || c.streaming.opener)) { st = 'busy'; label = t('status.thinking'); }
  if (ev.backend_link === false) { st = 'bad'; label = t('status.offline'); }
  live.classList.remove('ok', 'warn', 'bad', 'busy'); live.classList.add(st);
  $('#pill-live-text').textContent = label;
  $('#btn-mute').classList.toggle('active', !ev.listening);
  $('#btn-mute').querySelector('span').textContent = ev.listening ? t('btn.mute') : t('btn.unmute');
  $('#live-profile').textContent = (ev.profile || {}).name || '';
  if (ev.stt_error) setPill($('#pill-stt-live'), 'bad', 'STT');
  else setPill($('#pill-stt-live'), ev.stt_ready ? 'ok' : 'busy', 'STT');
  $('#pill-stt-live').title = ev.stt_error ? ev.stt_error : ev.stt_device ? `STT ${ev.stt_engine || ''} ready on ${ev.stt_device}` : 'STT loading';
  $('#pill-stt-live').querySelector('span:last-child').textContent = sttLabel(ev);
  $('#pill-stt-setup').querySelector('span:last-child').textContent = sttLabel(ev);
  if (ev.stt && ev.stt.ready === false && !ev.stt_error && ev.stt.error) setPill($('#pill-stt-live'), 'warn', sttLabel(ev));
  loadSttForm();
  if (ev.diag) { lastDiag = { ...(lastDiag || {}), ...ev.diag, queue: (lastDiag || {}).queue || 0, armed: ev.armed, chunks: ev.diag.chunks }; renderDiag(); }
  if (s.input_mode && s.input_mode !== inputMode) renderInputMode(s.input_mode, true);
  const lang = s.language || 'auto';
  $('#pill-lang').querySelector('span').textContent = t(`lang.name.${lang}`);
  $('#pill-lang').classList.toggle('ok', lang !== 'auto');
  $$('#lang-toggle button').forEach((b) => b.classList.toggle('on', b.dataset.v === lang));
  const ab = $('#lang-auto-btn'); if (ab) ab.innerHTML = lang === 'auto' && ev.answer_language ? `AUTO<small>·${String(ev.answer_language).toUpperCase()}</small>` : 'AUTO';
  // style segs
  $$('#seg-tone button').forEach((b) => b.classList.toggle('on', b.dataset.v === (s.tone || 'natural')));
  $$('#seg-length button').forEach((b) => b.classList.toggle('on', b.dataset.v === (s.length || 'medium')));
  $$('#seg-lang button').forEach((b) => b.classList.toggle('on', b.dataset.v === lang));
  // memory / project / context totals
  const cfg = (ev.profile || {}).config || {}, ctx = ev.context || {};
  $('#s-memory').value = cfg.use_learned_memory === false ? '0' : '1';
  $('#s-memory-status').textContent = t('memory.words', ctx.learned_memory_words || 0);
  $('#s-project-status').textContent = cfg.claude_project ? `${cfg.claude_project}${ctx.project_instructions_words ? ' · CLAUDE.md loaded' : ' · no CLAUDE.md found'}` : '';
  const n = (ev.context_files || []).length;
  $('#ctx-total').textContent = n ? t('ctx.total', ctx.total_words || 0, n) + (ctx.truncated ? t('ctx.truncated') : '') : '';
  renderProfileSelect();
  renderAudioState();
}
function setCheck(id, state, text) {
  const el = $('#' + id); if (!el) return;
  el.classList.remove('ok', 'warn', 'bad', 'busy'); el.classList.add(state);
  $('#' + id + '-text').textContent = text;
}
const STT_NAMES = { deepgram: 'Deepgram', whisper_local: 'Whisper local', groq_whisper: 'Groq Whisper' };
/** Setup header: the three things that must be ready before a call, each saying what is wrong in plain words. */
function renderPreflight(ev) {
  const s = ev.settings || {}, info = ev.providers_info || {};
  const eng = STT_NAMES[ev.stt_engine || s.stt_engine] || 'STT';
  if (ev.backend_link === false) setCheck('chk-stt', 'busy', t('chk.offline'));
  else if (ev.stt_error) setCheck('chk-stt', 'bad', String(ev.stt_error).slice(0, 140));
  else setCheck('chk-stt', ev.stt_ready ? 'ok' : 'busy', ev.stt_ready ? t('chk.stt_ok', eng) : t('chk.stt_loading', eng));
  const primary = s.primary || 'claude', pi = info[primary] || {};
  const healthy = PROVIDER_ORDER.filter((n) => (info[n] || {}).available && !(info[n] || {}).error);
  if (ev.backend_link === false) setCheck('chk-llm', 'busy', t('chk.offline'));
  else if (pi.error) setCheck('chk-llm', healthy.length ? 'warn' : 'bad', t('chk.llm_broken', provLabel(primary), explainError(primary, pi.error).text));
  else if (pi.available) setCheck('chk-llm', 'ok', t('chk.llm_ok', provLabel(primary), pi.model || '', healthy.filter((n) => n !== primary).length));
  else if (healthy.length) setCheck('chk-llm', 'warn', t('chk.llm_fallback', provLabel(primary), provLabel(healthy[0])));
  else setCheck('chk-llm', 'bad', t('chk.llm_none'));
  const ctx = ev.context || {}, n = (ev.context_files || []).length, name = (ev.profile || {}).name || 'default';
  setCheck('chk-ctx', n ? 'ok' : 'warn', n ? t('chk.ctx_ok', name, n, ctx.total_words || 0) : t('chk.ctx_none', name));
}
function sttLabel(ev) {
  const e = ev.stt_engine || (ev.settings || {}).stt_engine || '';
  const base = e === 'deepgram' ? 'DG' : e === 'groq_whisper' ? 'GROQ' : 'STT';
  const dec = ev.stt && typeof ev.stt.language === 'string' && /^(en|es)$/.test(ev.stt.language) ? ev.stt.language.toUpperCase() : '';
  return dec ? `${base}·${dec}` : base;   // v19: which native decoder the audio is routed to right now
}
// ---- v13: transcription engine form (Audio tab) ---------------------------------------------------
let sttFormDirty = false;
function loadSttForm() {
  const s = lastStatus.settings || {}, st = lastStatus.stt || {};
  if (!$('#s-stt-engine')) return;
  if (!sttFormDirty) {
    $('#s-stt-engine').value = s.stt_engine || 'whisper_local';
    $('#s-stt-model').value = s.stt_model || 'small';
    $('#s-stt-device').value = s.stt_device_pref || 'auto';
    if (document.activeElement !== $('#s-stt-vocab')) $('#s-stt-vocab').value = (s.stt_vocabulary || []).join(', ');
    if (document.activeElement !== $('#s-dg-key') && !$('#s-dg-key').value) $('#s-dg-key').placeholder = s.deepgram_key_set ? '•••••••• (guardada)' : 'dg_…';
    if (document.activeElement !== $('#s-groq-key') && !$('#s-groq-key').value) $('#s-groq-key').placeholder = s.groq_key_set ? '•••••••• (guardada)' : 'gsk_…';
  }
  showSttFields();
  const diag = lastStatus.diag || {};
  let state = lastStatus.stt_error ? 'error' : st.ready ? 'ready' : (st.engine === 'deepgram' ? 'connecting' : 'loading');
  let txt = `${st.engine || s.stt_engine || ''} · ${t('stt.state.' + state)}${st.device ? ` · ${st.device}` : ''}`;
  if (st.connections) txt += ` · SYS ${st.connections.them && st.connections.them.connected ? '✓' : '✗'} · MIC ${st.connections.me && st.connections.me.connected ? '✓' : '✗'}`;
  if (st.error) txt += ` · ${st.error}`;
  if (diag.stt_fallback) txt += ` · ${t('stt.fallback')}`;
  $('#s-stt-status').textContent = txt;
  $('#s-stt-status').classList.toggle('err', Boolean(st.error || lastStatus.stt_error));
  $('#s-stt-keyterms').textContent = Number.isFinite(diag.keyterms) ? t('stt.keyterms', diag.keyterms) : '';
}
function showSttFields() {
  const eng = $('#s-stt-engine').value;
  $$('.stt-only').forEach((el) => el.classList.toggle('hidden', el.dataset.engine !== eng));
}
$('#s-stt-engine').addEventListener('change', () => { sttFormDirty = true; showSttFields(); });
for (const id of ['#s-stt-model', '#s-stt-device', '#s-stt-vocab', '#s-dg-key', '#s-groq-key']) $(id).addEventListener('input', () => { sttFormDirty = true; });
$('#s-dg-show').addEventListener('click', () => { const i = $('#s-dg-key'); i.type = i.type === 'password' ? 'text' : 'password'; });
$('#s-groq-show').addEventListener('click', () => { const i = $('#s-groq-key'); i.type = i.type === 'password' ? 'text' : 'password'; });
$('#stt-save').addEventListener('click', () => {
  const stt = {
    engine: $('#s-stt-engine').value,
    model_size: $('#s-stt-model').value,
    device: $('#s-stt-device').value,
    vocabulary: $('#s-stt-vocab').value,
  };
  const dg = $('#s-dg-key').value.trim(), gq = $('#s-groq-key').value.trim();
  if (dg) stt.deepgram_api_key = dg;
  if (gq) stt.groq_api_key = gq;
  window.copilot.send({ type: 'set_config', stt });
  $('#s-dg-key').value = ''; $('#s-groq-key').value = '';
  sttFormDirty = false;
  toast(t('toast.stt'));
});

function renderAudioState() {
  const a = lastStatus.audio || {};
  for (const ch of ['them', 'me']) {
    const info = a[ch] || {};
    const electronActive = info.source === 'electron' && window.ElectronCapture.isActive(ch);
    for (const id of [`#meter-${ch}`, `#meter-${ch}-setup`]) {
      const meter = $(id);
      if (!meter) continue;
      meter.classList.toggle('active', Boolean(info.active || electronActive));
      meter.classList.toggle('error', Boolean(info.error) && !electronActive);
      meter.title = info.device ? `${info.device}${info.error ? ' — ' + info.error : ''}` : '';
    }
    const statusEl = $(ch === 'them' ? '#s-loopback-status' : '#s-mic-status');
    if (statusEl) statusEl.textContent = info.device ? `${info.device}${info.error ? ' — ' + info.error : ''}` : '';
  }
}
function renderMeters(levels) {
  for (const ch of ['them', 'me']) {
    const v = Math.min(1, Math.max(levels[ch] || 0, localLevels[ch] || 0));
    for (const id of [`#meter-${ch}`, `#meter-${ch}-setup`]) {
      const m = $(id);
      if (m) m.querySelector('.meter-fill').style.width = `${Math.round(v * 100)}%`;
    }
    localLevels[ch] *= 0.7;
  }
}
function renderHotkeys() {
  const hk = hotkeys || {};
  const list = $('#hotkey-list');
  list.innerHTML = '';
  for (const [k, v] of Object.entries(hk)) {
    const d = document.createElement('div');
    const kbd = document.createElement('kbd'); kbd.textContent = prettyAccel(v);
    const s = document.createElement('span'); s.textContent = t('hk.' + k);
    d.append(kbd, s);
    list.appendChild(d);
  }
  const badge = (id, key) => { const el = $(id); if (el) el.textContent = prettyAccel(hk[key] || ''); };
  badge('#kbd-answer', 'force_answer'); badge('#kbd-shot', 'screenshot'); badge('#kbd-mute', 'toggle_listening'); badge('#kbd-setup', 'settings'); badge('#kbd-end', 'end_session'); badge('#kbd-pivot', 'followup_pivot');
  $('#seg-follow').title = `${prettyAccel(hk.followup_example)}/${prettyAccel(hk.followup_deepen)}/${prettyAccel(hk.followup_tldr)}/${prettyAccel(hk.followup_pivot || 'Alt+4')} ${t('fu.example')}·${t('fu.deepen')}·${t('fu.tldr')}·${t('fu.pivot')} · ${prettyAccel(hk.toggle_visibility)} ${t('hk.toggle_visibility').toLowerCase()}`;
  $('#hint-setup').textContent = `${prettyAccel(hk.settings)} ${t('hk.settings')} · ${prettyAccel(hk.toggle_visibility)} ${t('hk.toggle_visibility').toLowerCase()}`;
  const bs = $('#btn-setup'); if (bs) bs.title = `${t('hk.settings')} (${prettyAccel(hk.settings || 'Alt+T')})`;
  const bv = $('#btn-autovision'); if (bv && !bv.classList.contains('on')) bv.title = `${t('hk.auto_vision')} (${prettyAccel(hk.auto_vision || 'Alt+V')})`;
  renderGhost();
}

// ------------------------------------------------------------------ profiles (inline forms, no window.prompt)
function renderProfileSelect() {
  const p = lastStatus.profile || {};
  const names = p.profiles && p.profiles.length ? p.profiles : profileList;
  if (!names.length) return;
  profileList = names;
  const sel = $('#profile-select');
  const current = p.name || sel.value;
  if ([...sel.options].map((o) => o.value).join('|') !== names.join('|')) {
    sel.innerHTML = '';
    for (const n of names) { const o = document.createElement('option'); o.value = n; o.textContent = n; sel.appendChild(o); }
  }
  sel.value = current;
  window.copilot.profiles.setActive(current);
}
$('#profile-select').addEventListener('change', () => {
  const name = $('#profile-select').value;
  window.copilot.profiles.setActive(name);
  window.copilot.send({ type: 'set_profile', name });
  toast(t('toast.profile', name));
  setTimeout(() => { loadContext(); refreshBank(); }, 400);
});
let formAction = null;
function openProfileForm(action, label, preset) {
  formAction = action;
  $('#profile-form-label').textContent = label;
  $('#profile-form-input').value = preset || '';
  $('#profile-form').classList.remove('hidden');
  $('#profile-form-input').focus();
}
function closeProfileForm() { $('#profile-form').classList.add('hidden'); formAction = null; }
$('#profile-form-cancel').addEventListener('click', closeProfileForm);
$('#profile-form-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#profile-form-ok').click(); if (e.key === 'Escape') closeProfileForm(); });
$('#profile-form-ok').addEventListener('click', async () => {
  const value = $('#profile-form-input').value.trim(), current = $('#profile-select').value;
  if (!value) return;
  try {
    let res = null;
    if (formAction === 'create') res = await window.copilot.profiles.create(value);
    else if (formAction === 'duplicate') res = await window.copilot.profiles.duplicate(current, value);
    else if (formAction === 'rename') res = await window.copilot.profiles.rename(current, value);
    closeProfileForm();
    if (res) {
      profileList = res.profiles;
      lastStatus.profile = { ...(lastStatus.profile || {}), profiles: res.profiles, name: res.active };
      renderProfileSelect();
      window.copilot.send({ type: 'set_profile', name: res.active });
      toast(t('toast.profile', res.active));
      setTimeout(loadContext, 400);
    }
  } catch (err) { toast(err.message, true); }
});
// v17: deleting a profile is a two-button confirmation bar, never a typed name
let deleteTarget = null;
function openDeleteConfirm(name) {
  deleteTarget = name;
  closeProfileForm();
  $('#profile-confirm-label').textContent = t('pm.confirm_delete_bar', name);
  $('#profile-confirm').classList.remove('hidden');
  $('#profile-confirm-yes').focus();
}
function closeDeleteConfirm() { $('#profile-confirm').classList.add('hidden'); deleteTarget = null; }
$('#profile-confirm-no').addEventListener('click', closeDeleteConfirm);
$('#profile-confirm-yes').addEventListener('click', async () => {
  const name = deleteTarget; if (!name) return;
  try {
    const res = await window.copilot.profiles.remove(name);
    closeDeleteConfirm();
    if (res) {
      profileList = res.profiles;
      lastStatus.profile = { ...(lastStatus.profile || {}), profiles: res.profiles, name: res.active };
      renderProfileSelect();
      window.copilot.send({ type: 'set_profile', name: res.active });
      toast(t('toast.profile', res.active));
      setTimeout(loadContext, 400);
    }
  } catch (err) { toast(err.message, true); }
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && deleteTarget) closeDeleteConfirm(); });
$$('[data-pm]').forEach((b) => b.addEventListener('click', async () => {
  const current = $('#profile-select').value, a = b.dataset.pm;
  if (a === 'create') openProfileForm('create', t('pm.ask_name'), '');
  else if (a === 'duplicate') openProfileForm('duplicate', t('pm.ask_dup'), `${current}_copy`);
  else if (a === 'rename') openProfileForm('rename', t('pm.ask_rename'), current);
  else if (a === 'delete') openDeleteConfirm(current);
  else if (a === 'archive') { if (confirm(t('pm.confirm_archive', current))) window.copilot.send({ type: 'archive_profile', name: current }); }
  else if (a === 'folder') await window.copilot.profiles.openFolder(current);
}));

// ---- Claude projects
async function loadProjects() {
  try { projectList = await window.copilot.claudeProjects.list(); } catch { projectList = []; }
  fillProjectSelect();
}
function fillProjectSelect() {
  const cfg = (lastStatus.profile || {}).config || {};
  const current = cfg.claude_project || '';
  const opts = [{ id: '', name: t('project.none') }, ...projectList.map((p) => ({ id: p.path, name: `${p.name}${p.hasClaudeMd ? '' : ' (no CLAUDE.md)'} — ${p.path}` }))];
  if (current && !opts.some((o) => o.id === current)) opts.push({ id: current, name: current });
  fillSelect($('#s-project'), opts, current);
}
$('#s-project-pick').addEventListener('click', async () => {
  const p = await window.copilot.claudeProjects.pick();
  if (!p) return;
  if (!projectList.some((x) => x.path === p.path)) projectList.push(p);
  fillProjectSelect();
  $('#s-project').value = p.path;
  window.copilot.send({ type: 'set_profile_config', claude_project: p.path });
});
$('#s-project').addEventListener('change', () => window.copilot.send({ type: 'set_profile_config', claude_project: $('#s-project').value || null }));
$('#s-memory').addEventListener('change', () => window.copilot.send({ type: 'set_profile_config', use_learned_memory: $('#s-memory').value === '1' }));

// ------------------------------------------------------------------ context cards (drag & drop + picker)
const parsing = {}; // slot -> Set of file names being parsed
async function loadContext() {
  try { lastManifest = await window.copilot.context.get($('#profile-select').value || undefined); } catch (e) { toast(e.message, true); return; }
  window.copilot.send({ type: 'get_manual_context' });
  renderContext(lastManifest);
}
function fileRow(slot, entry, index) {
  const row = document.createElement('div'); row.className = 'file-row';
  const name = document.createElement('span'); name.className = 'name'; name.textContent = entry.source; name.title = entry.source;
  const badge = document.createElement('span');
  badge.className = `badge ${entry.status === 'ok' ? 'ok' : 'err'}`;
  badge.textContent = entry.status === 'ok' ? t('ctx.loaded', entry.words || 0) + (entry.pages ? ` · ${entry.pages} p.` : '') : `✖ ${entry.error || 'error'}`;
  const rm = document.createElement('button'); rm.className = 'btn small danger'; rm.textContent = t('ctx.remove');
  rm.addEventListener('click', async () => { lastManifest = await window.copilot.context.remove(slot, index, $('#profile-select').value || undefined); renderContext(lastManifest); });
  row.append(name, badge, rm);
  return row;
}
function parsingRow(file) {
  const row = document.createElement('div'); row.className = 'file-row';
  const name = document.createElement('span'); name.className = 'name'; name.textContent = file;
  const badge = document.createElement('span'); badge.className = 'badge busy'; badge.innerHTML = `<span class="spinner"></span>${t('ctx.parsing')}`;
  row.append(name, badge);
  return row;
}
function manualRow(slot) {
  const words = (manualTexts[slot] || '').split(/\s+/).filter(Boolean).length;
  if (!words) return null;
  const row = document.createElement('div'); row.className = 'file-row';
  const badge = document.createElement('span'); badge.className = 'badge manual'; badge.textContent = t('ctx.manual', words);
  const edit = document.createElement('button'); edit.className = 'btn small'; edit.textContent = t('ctx.paste_btn'); edit.addEventListener('click', () => openTextModal(slot));
  row.append(badge, edit);
  return row;
}
function renderContext(m) {
  if (!m) return;
  for (const slot of ['role', 'profile', 'playbook']) {
    const box = $(`#slot-${slot}`); box.innerHTML = '';
    const mr = slot !== 'playbook' ? manualRow(slot) : null;
    if (mr) box.appendChild(mr);
    if (m[slot]) box.appendChild(fileRow(slot, m[slot], 0));
    for (const f of parsing[slot] || []) box.appendChild(parsingRow(f));
    if (!m[slot] && !mr && !(parsing[slot] || new Set()).size) { const e = document.createElement('span'); e.className = 'badge empty'; e.textContent = t('ctx.empty'); box.appendChild(e); }
  }
  const expBox = $('#slot-experience'); expBox.innerHTML = '';
  const emr = manualRow('experience'); if (emr) expBox.appendChild(emr);
  (m.experience || []).forEach((entry, i) => expBox.appendChild(fileRow('experience', entry, i)));
  for (const f of parsing.experience || []) expBox.appendChild(parsingRow(f));
  if (!(m.experience || []).length && !emr && !(parsing.experience || new Set()).size) { const e = document.createElement('span'); e.className = 'badge empty'; e.textContent = t('ctx.empty'); expBox.appendChild(e); }
}
function ctxAlert(message, warn = false) {
  const a = document.createElement('div'); a.className = `alert${warn ? ' warn' : ''}`;
  const txt = document.createElement('span'); txt.textContent = (warn ? '⚠ ' : '⛔ ') + message;
  const x = document.createElement('button'); x.className = 'x'; x.textContent = '✕'; x.addEventListener('click', () => a.remove());
  a.append(txt, x);
  $('#ctx-alerts').prepend(a);
  setTimeout(() => a.remove(), 25000);
}
function handleResults(res) {
  if (!res || res.cancelled) return;
  lastManifest = res.manifest;
  renderContext(lastManifest);
  refreshBank();
  for (const r of res.results) if (!r.ok) ctxAlert(`${t('ctx.could_not_read')} "${r.file}": ${r.error}`, r.code === 'no_text');
  const okCount = res.results.filter((r) => r.ok).length;
  if (okCount) toast(t('toast.files', okCount));
}
$$('[data-pick]').forEach((btn) => btn.addEventListener('click', async () => {
  const slot = btn.getAttribute('data-pick');
  btn.disabled = true;
  try { handleResults(await window.copilot.context.pick(slot, $('#profile-select').value || undefined)); }
  catch (e) { ctxAlert(e.message); }
  btn.disabled = false;
}));
$$('.dropzone').forEach((zone) => {
  const slot = zone.dataset.slot;
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', async (e) => {
    e.preventDefault(); zone.classList.remove('over');
    const paths = window.copilot.pathsFromFiles(e.dataTransfer.files);
    if (!paths.length) return;
    try { handleResults(await window.copilot.context.addPaths(slot, paths, $('#profile-select').value || undefined)); }
    catch (err) { ctxAlert(err.message); }
  });
});
document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('drop', (e) => e.preventDefault());

// ------------------------------------------------------------------ playbook & style
let pbTimer = null;
$('#playbook-text').addEventListener('input', () => {
  clearTimeout(pbTimer);
  $('#playbook-status').textContent = '…';
  pbTimer = setTimeout(async () => {
    const text = $('#playbook-text').value;
    const name = $('#pb-bank-name').value.trim() || `${$('#profile-select').value || 'default'}_playbook`;
    window.copilot.send({ type: 'set_playbook', text, bank_name: name });
    if (text.trim().split(/\s+/).length >= 3 && name !== 'default_playbook') {
      try { await window.copilot.bank.saveText('playbook', name, text, $('#profile-select').value); } catch {}
      refreshBank();
    }
  }, 800);
});
$('#seg-tone').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) window.copilot.send({ type: 'set_config', style: { tone: b.dataset.v } }); });
$('#seg-length').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) window.copilot.send({ type: 'set_config', style: { length: b.dataset.v } }); });
$('#seg-lang').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  window.copilot.send({ type: 'set_config', general: { language: b.dataset.v, ui_language: $('#s-ui-language').value } });
});
$('#s-ui-language').addEventListener('change', () => {
  const s = lastStatus.settings || {};
  window.copilot.send({ type: 'set_config', general: { ui_language: $('#s-ui-language').value } });
  applyUiLanguage(resolveUiLang($('#s-ui-language').value, s.language || 'auto'));
});
let brainDirty = false;
function loadBrainForm() {
  const s = lastStatus.settings || {};
  if (brainDirty) return;   // unsaved choices in the Brain form survive status refreshes
  $('#s-ui-language').value = s.ui_language || 'auto';
  $('#s-primary').value = s.primary || 'claude';
  $('#s-auto').value = s.auto_answer === false ? '0' : '1';
  fillSelect($('#s-claude-model'), s.claude_models || [], s.claude_model || '');
  fillSelect($('#s-gemini-model'), s.gemini_models || [], s.gemini_model || '');
  $('#s-words').value = s.max_answer_words || 110;
  if (document.activeElement !== $('#playbook-text')) $('#playbook-text').value = (lastStatus.context || {}).playbook_text || '';
}
for (const id of ['#s-primary', '#s-auto', '#s-claude-model', '#s-gemini-model', '#s-words', '#s-claude-custom', '#s-gemini-custom']) {
  const el = $(id); if (el) { el.addEventListener('change', () => { brainDirty = true; }); el.addEventListener('input', () => { brainDirty = true; }); }
}
$('#settings-save').addEventListener('click', () => {
  window.copilot.send({
    type: 'set_config',
    general: { primary: $('#s-primary').value },
    llm: {
      claude_model: $('#s-claude-custom').value.trim() || $('#s-claude-model').value,
      gemini_model: $('#s-gemini-custom').value.trim() || $('#s-gemini-model').value,
      auto_answer: $('#s-auto').value === '1',
      max_answer_words: Number($('#s-words').value) || 110,
    },
  });
  $('#s-claude-custom').value = ''; $('#s-gemini-custom').value = '';
  brainDirty = false;
  toast(t('toast.saved'));
});
$('#s-gemini-refresh').addEventListener('click', () => window.copilot.send({ type: 'list_gemini_models' }));

// ------------------------------------------------------------------ audio tab
function fillDeviceSelects() {
  if (document.activeElement === $('#s-loopback') || document.activeElement === $('#s-mic')) return;
  const s = lastStatus.settings || {}, d = lastDevices || { mic: [], loopback: [], platform };
  const lb = [{ id: 'default', name: t('dev.default') }];
  if ((d.platform || platform) === 'win32') lb.push({ id: 'electron', name: t('dev.electron') });
  lb.push(...d.loopback, { id: 'off', name: t('dev.off') });
  const mic = [{ id: 'default', name: t('dev.default') }, { id: 'electron', name: t('dev.electron_mic') }, ...d.mic, { id: 'off', name: t('dev.off') }];
  fillSelect($('#s-loopback'), lb, s.loopback_device || 'default');
  fillSelect($('#s-mic'), mic, s.mic_device || 'default');
}
$('#s-audio-refresh').addEventListener('click', () => window.copilot.send({ type: 'list_audio_devices' }));
$('#audio-apply').addEventListener('click', () => {
  window.copilot.send({ type: 'set_audio_devices', loopback: $('#s-loopback').value, mic: $('#s-mic').value });
  toast(t('toast.devices'));
});
let captureSyncing = false, captureSyncAgain = false;
async function syncElectronCapture() {
  // status events arrive in bursts; a second call while getDisplayMedia is still pending used to start a
  // second capture and feed the backend doubled audio. One sync at a time, re-run once if state changed.
  if (captureSyncing) { captureSyncAgain = true; return; }
  captureSyncing = true;
  try {
    do {
      captureSyncAgain = false;
      const s = lastStatus.settings || {};
      const want = { them: s.loopback_device === 'electron', me: s.mic_device === 'electron' };
      for (const ch of ['them', 'me']) {
        if (want[ch] && !window.ElectronCapture.isActive(ch)) await window.ElectronCapture.start(ch);
        else if (!want[ch] && window.ElectronCapture.isActive(ch)) await window.ElectronCapture.stop(ch);
      }
    } while (captureSyncAgain);
  } finally { captureSyncing = false; }
  renderAudioState();
}
window.ElectronCapture.onLevel((ch, rms) => { localLevels[ch] = Math.max(localLevels[ch], Math.min(1, rms * 6)); });
window.ElectronCapture.onError((ch, msg) => { toast(msg, true); renderAudioState(); });

// ------------------------------------------------------------------ sessions tab (grouped by profile)
async function loadSessions() {
  fillSessionProfiles();
  const [prof, archived] = sessionProfileArgs();
  const list = $('#session-list');
  try { sessionList = await window.copilot.sessions.list(prof, archived); } catch (e) { toast(e.message, true); return; }
  list.innerHTML = '';
  if (!sessionList.length) { list.appendChild(el('div', 'dim', t('sessions.none'))); return; }
  for (const s of sessionList) {
    const d = el('div', 'session-item' + (currentSession && currentSession.stamp === s.stamp ? ' on' : ''));
    const col = el('div', 'col');
    col.appendChild(el('b', null, fmtStamp(s.stamp)));
    const mins = s.duration_s != null ? Math.max(1, Math.round(s.duration_s / 60)) : null;
    col.appendChild(el('span', 'dim', `${mins != null ? t('sessions.duration', mins) + ' · ' : ''}${t('an.turns', s.lines ?? '?', s.suggestions ?? '?')}`));
    if (s.focus) { const fb = el('span', 'focus-badge', `${t('sessions.focus')}: ${s.focus}`); fb.title = s.focus; col.appendChild(fb); }
    const badge = el('span', `score-badge ${scoreClass(s.score)}`, s.score != null ? `${s.score}` : '—');
    d.append(col, badge);
    d.addEventListener('click', () => openSession(s));
    list.appendChild(d);
  }
}
async function openSession(s) {
  currentSession = s;
  $$('.session-item').forEach((x) => x.classList.remove('on'));
  $('#session-title').textContent = `${fmtStamp(s.stamp)}${s.score != null ? ` · ${s.score}/100` : ''}${s.focus ? ` · 🎯 ${s.focus.slice(0, 60)}` : ''}`;
  await renderAnalysis(s);
  loadSessions();
}
$('#session-open').addEventListener('click', () => currentSession && window.copilot.profiles.openFile(currentSession.report || currentSession.log_md));
$('#session-logs').addEventListener('click', () => { const [p] = sessionProfileArgs(); window.copilot.profiles.openLogs(p); });

// ------------------------------------------------------------------ live controls
$('#btn-mute').addEventListener('click', () => window.copilot.send({ type: 'toggle_listening' }));
$$('[data-cmd]').forEach((b) => b.addEventListener('click', () => window.copilot.send({ type: b.getAttribute('data-cmd') })));
$('#seg-follow').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  window.copilot.send({ type: 'followup', kind: b.dataset.f });
  if (b.dataset.f === 'pivot') { toast(t('toast.pivot')); b.classList.add('busy'); setTimeout(() => b.classList.remove('busy'), 2500); }
});
// ---- story ledger pill: which example the last answer spent (rotated automatically on the next question)
function renderStory(ev) {
  // v17: the footer stays clean - the example used goes into the card's meta line and the 🔄 button title
  const pv = $('#btn-pivot');
  if (!ev || !ev.ledger) { if (pv) pv.title = `${t('fu.pivot')} (Alt+4)`; return; }
  const ents = (ev.entities || []).slice(0, 4).join(', ');
  if (pv) pv.title = `${t('story.used', ents || t('story.none'))} — ${t('fu.pivot')}: Alt+4`;
  const card = cards.get(ev.gen_id);
  if (card && ents) { card.storyText = `📚 ${t('story.used', ents)}`; if (card.meta.textContent) card.meta.textContent += ` · ${card.storyText}`; }
}
function askEndSession() { $('#end-modal').classList.remove('hidden'); }
$('#btn-end').addEventListener('click', askEndSession);
$('#end-cancel').addEventListener('click', () => $('#end-modal').classList.add('hidden'));
$('#end-ok').addEventListener('click', () => { $('#end-modal').classList.add('hidden'); window.copilot.send({ type: 'end_session' }); });
$('#end-modal').addEventListener('click', (e) => { if (e.target.id === 'end-modal') $('#end-modal').classList.add('hidden'); });
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') { if (!$('#focus-edit').classList.contains('hidden')) $('#focus-edit').classList.add('hidden'); else if (!$('#text-modal').classList.contains('hidden')) $('#text-modal').classList.add('hidden'); else if (!$('#end-modal').classList.contains('hidden')) $('#end-modal').classList.add('hidden'); else if (!$('#providers-modal').classList.contains('hidden')) closeProviders(); else if (mode === 'live') window.copilot.send({ type: 'cancel' }); } });

// ------------------------------------------------------------------ instant EN | ES toggle (Alt+L)
$('#lang-toggle').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  window.copilot.send({ type: 'set_language', value: b.dataset.v });
  $$('#lang-toggle button').forEach((x) => x.classList.toggle('on', x === b));
});

// ------------------------------------------------------------------ plain-text context (paste instead of file)
let manualTexts = { role: '', profile: '', experience: '' };
let textSlot = null;
const SLOT_TITLE = { role: 'ctx.role', profile: 'ctx.profile', experience: 'ctx.experience' };
function openTextModal(slot) {
  textSlot = slot;
  $('#text-modal-title').textContent = t(SLOT_TITLE[slot]);
  $('#text-modal-area').value = manualTexts[slot] || '';
  updateTextCount();
  $('#text-modal').classList.remove('hidden');
  setTimeout(() => $('#text-modal-area').focus(), 30);
}
function updateTextCount() { $('#text-modal-count').textContent = t('ctx.words', $('#text-modal-area').value.split(/\s+/).filter(Boolean).length); }
$('#text-modal-area').addEventListener('input', updateTextCount);
$('#text-modal-cancel').addEventListener('click', () => $('#text-modal').classList.add('hidden'));
$('#text-modal').addEventListener('click', (e) => { if (e.target.id === 'text-modal') $('#text-modal').classList.add('hidden'); });
$('#text-modal-clear').addEventListener('click', () => { $('#text-modal-area').value = ''; updateTextCount(); });
$('#text-modal-save').addEventListener('click', async () => {
  const text = $('#text-modal-area').value;
  const slot = textSlot;
  manualTexts[slot] = text;
  const profile = $('#profile-select').value || 'default';
  window.copilot.send({ type: 'set_manual_context', slot, text, bank_name: `${profile}_${slot}` });
  $('#text-modal').classList.add('hidden');
  if (lastManifest) renderContext(lastManifest);
  if (text.trim().split(/\s+/).length >= 2) {
    try { await window.copilot.bank.saveText(slot, `${profile}_${slot}`, text, profile); } catch (e) { toast(e.message, true); }
  }
  refreshBank();
});
$$('[data-paste]').forEach((b) => b.addEventListener('click', () => openTextModal(b.dataset.paste)));
// (v17) the per-card source toggle is gone: 📁 Subir archivo · ✏️ Pegar texto · 📚 Elegir del Banco live in one row

// ------------------------------------------------------------------ font size (CSS var, persisted)
let fontSize = 17;
function applyFontSize(px, persist = true) {
  fontSize = Math.max(12, Math.min(32, Math.round(px)));
  document.documentElement.style.setProperty('--answer-font-size', `${fontSize}px`);
  const inp = $('#s-font'); if (inp && document.activeElement !== inp) inp.value = fontSize;
  try { localStorage.setItem('answerFontSize', String(fontSize)); } catch {}
  if (persist) window.copilot.send({ type: 'set_font_size', value: fontSize });
}
$('#font-inc').addEventListener('click', () => applyFontSize(fontSize + 1));
$('#font-dec').addEventListener('click', () => applyFontSize(fontSize - 1));
$('#s-font').addEventListener('change', () => applyFontSize(Number($('#s-font').value) || 17));
window.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  if (e.key === '=' || e.key === '+' || e.code === 'NumpadAdd') { e.preventDefault(); applyFontSize(fontSize + 1); }
  else if (e.key === '-' || e.code === 'NumpadSubtract') { e.preventDefault(); applyFontSize(fontSize - 1); }
  else if (e.key === '0') { e.preventDefault(); applyFontSize(17); }
}, true);
try { const saved = Number(localStorage.getItem('answerFontSize')); if (saved) applyFontSize(saved, false); } catch {}

// ------------------------------------------------------------------ v15: ghost mode (click-through) ------------------
let ghost = false;
function renderGhost() {
  document.documentElement.dataset.ghost = ghost ? '1' : '0';
  const b = $('#btn-ghost');
  if (b) { b.classList.toggle('on', ghost); b.title = (ghost ? t('ghost.on') : t('hk.ghost')) + ` (${prettyAccel((hotkeys || {}).ghost || 'Alt+G')})`; }
  let banner = $('#ghost-banner');
  if (ghost && !banner) { banner = document.createElement('span'); banner.id = 'ghost-banner'; banner.className = 'ghost-banner'; banner.textContent = t('ghost.banner'); $('#live').appendChild(banner); }
  if (!ghost && banner) banner.remove();
}
$('#btn-ghost').addEventListener('click', () => window.copilot.hud.toggleGhost());
// While ghosted, every mouse event falls through to the app behind — except over the 👻 button itself:
// main forwards mousemove, so hovering it punches a hole (setIgnoreMouseEvents(false)) and leaving re-arms it.
$('#btn-ghost').addEventListener('mouseenter', () => { if (ghost) window.copilot.hud.ghostHole(true); });
$('#btn-ghost').addEventListener('mouseleave', () => { if (ghost) window.copilot.hud.ghostHole(false); });

// ------------------------------------------------------------------ v15: HUD background opacity (Alt+[ / Alt+]) -------
function applyHudOpacity(v, announce = true) {
  const a = Math.max(0.35, Math.min(0.95, Number(v) || 0.75));
  document.documentElement.style.setProperty('--hud-alpha', String(a));
  let hint = $('#opacity-hint');
  if (!hint) { hint = document.createElement('span'); hint.id = 'opacity-hint'; hint.className = 'opacity-hint dim'; $('.live-foot').appendChild(hint); }
  hint.textContent = t('opacity.hint', a);
  if (announce) toast(t('opacity.hint', a));
}

// ------------------------------------------------------------------ v15: scroll the answer feed from a global hotkey ----
function scrollFeedBy(direction) {
  const f = feed(); if (!f) return;
  userScrolledUp = true;
  f.scrollBy({ top: direction * Math.max(80, Math.round(f.clientHeight * 0.6)), behavior: 'smooth' });
  setTimeout(() => { if (f.scrollTop + f.clientHeight >= f.scrollHeight - 8) { userScrolledUp = false; $('#jump-latest').classList.add('hidden'); } }, 400);
}

// ------------------------------------------------------------------ v15: passive auto-vision (rolling 1-frame buffer) --
// Every `autoVision.intervalMs` (5 s) while live, one compressed frame (~40-120 KB JPEG, ≤1100 px wide) of the display
// under the cursor is captured in the main process and kept here as the ONLY buffered frame; it is mirrored to the
// backend (`vision_buffer`), which attaches it to the next answer when the question refers to the screen
// ("this diagram", "on the screen", "this slide", "this code", "looking at this"…) or when llm.auto_vision_always is set.
const autoVision = { enabled: false, timer: null, intervalMs: 5000, busy: false, frame: null, failures: 0 };
function visionBufferedFrame() { return autoVision.frame; } // {b64, mime, bytes, t}
async function autoVisionTick() {
  if (!autoVision.enabled || mode !== 'live' || autoVision.busy) return;
  autoVision.busy = true;
  const btn = $('#btn-autovision');
  try {
    const f = await window.copilot.vision.capture({ maxWidth: 1100, quality: 50 });
    if (f && f.b64) {
      autoVision.frame = f;                       // rolling buffer: the newest frame replaces the previous one
      autoVision.failures = 0;
      window.copilot.send({ type: 'vision_buffer', image_b64: f.b64, mime: f.mime, bytes: f.bytes, t: f.t });
      if (btn) { btn.classList.add('capturing'); setTimeout(() => btn.classList.remove('capturing'), 450); }
      if (btn) btn.title = `${t('hk.auto_vision')} · ${Math.round(f.bytes / 1024)} KB · ${f.ms} ms (${prettyAccel((hotkeys || {}).auto_vision || 'Alt+V')})`;
    }
  } catch (e) {
    autoVision.failures += 1;
    if (autoVision.failures === 1 || autoVision.failures % 12 === 0) toast(t('vision.err', e && e.message ? e.message : String(e)), true);
  } finally { autoVision.busy = false; }
}
function setAutoVision(on, persist = true, announce = true) {
  autoVision.enabled = Boolean(on);
  clearInterval(autoVision.timer); autoVision.timer = null;
  const btn = $('#btn-autovision');
  if (btn) btn.classList.toggle('on', autoVision.enabled);
  window.copilot.send({ type: 'set_auto_vision', value: autoVision.enabled });          // backend: attach-on-answer switch
  if (persist) window.copilot.hud.setAutoVision(autoVision.enabled);                   // config.json: hud.auto_vision
  if (autoVision.enabled) { autoVisionTick(); autoVision.timer = setInterval(autoVisionTick, autoVision.intervalMs); }
  else { autoVision.frame = null; window.copilot.send({ type: 'vision_buffer', clear: true }); }
  if (announce) toast(autoVision.enabled ? t('vision.on') : t('vision.off'));
}
$('#btn-autovision').addEventListener('click', () => setAutoVision(!autoVision.enabled));

// ------------------------------------------------------------------ 1.0: first-run wizard + AI providers ----------------
const PROVIDER_ORDER = ['claude', 'gemini', 'openai', 'xai', 'deepseek'];
let onboardingShown = false, provPrimary = null, provBuilt = false, provWizard = false;
const provResults = {};
function provRow(name) { return $(`#prov-list .prov-row[data-p="${name}"]`); }
function buildProviders() {
  const info = lastStatus.providers_info || {};
  const list = $('#prov-list'); list.innerHTML = '';
  for (const name of PROVIDER_ORDER) {
    const p = info[name]; if (!p) continue;
    const row = document.createElement('div'); row.className = 'prov-row'; row.dataset.p = name;
    const cli = p.kind === 'cli';
    row.innerHTML = `<input type="radio" name="prov-primary" value="${name}" title="${t('prov.primary')}" />
      <div class="name"><span>${escapeHtml(p.label)}</span><small class="st"></small></div>
      ${cli ? '<span class="dim cli-note"></span>' : `<input type="password" class="key" spellcheck="false" autocomplete="off" />`}
      <input type="text" class="model" spellcheck="false" list="prov-models-${name}" placeholder="${t('prov.model_ph')}" /><datalist id="prov-models-${name}"></datalist>
      <button class="btn small models">${t('prov.models')}</button><button class="btn small test">${t('prov.test')}</button>
      <div class="result"></div><div class="problem hidden"></div>`;
    list.appendChild(row);
    row.querySelector('.model').value = p.model || '';
    row.querySelector('input[type="radio"]').addEventListener('change', () => { provPrimary = name; paintProviders(); });
    row.querySelector('.test').addEventListener('click', () => { pushProvider(name); window.copilot.send({ type: 'test_provider', provider: name }); });
    row.querySelector('.models').addEventListener('click', () => { pushProvider(name); window.copilot.send({ type: 'list_models', provider: name }); });
    if (cli) row.querySelector('.models').classList.add('hidden');
    const res = row.querySelector('.result');
    if (p.keys_url) { const a = document.createElement('a'); a.href = '#'; a.dataset.ext = p.keys_url; a.textContent = t('prov.get_key'); res.appendChild(a); }
  }
  provBuilt = true;
  paintProviders();
}
function paintProviders() {
  const info = lastStatus.providers_info || {};
  for (const name of PROVIDER_ORDER) {
    const row = provRow(name), p = info[name]; if (!row || !p) continue;
    row.classList.toggle('primary', provPrimary === name);
    row.querySelector('input[type="radio"]').checked = provPrimary === name;
    const st = row.querySelector('.st');
    st.textContent = p.available ? t('prov.ready') : t('prov.no_key'); st.className = `st ${p.available ? 'ok' : ''}`;
    const key = row.querySelector('.key');
    if (key && document.activeElement !== key && !key.value) key.placeholder = p.key_set ? t('prov.key_saved') : t('prov.key_ph');
    const note = row.querySelector('.cli-note'); if (note) note.textContent = p.available ? t('prov.cli_ok') : t('prov.cli_missing');
    const prob = row.querySelector('.problem');
    prob.classList.toggle('hidden', !p.error); prob.textContent = '';
    row.classList.toggle('broken', Boolean(p.error));
    if (p.error) {
      const x = explainError(name, p.error);
      st.textContent = t('prov.failed'); st.className = 'st bad';
      const txt = document.createElement('span'); txt.textContent = x.text; prob.appendChild(txt);
      if (x.code !== 'other') { const raw = document.createElement('small'); raw.textContent = x.raw.slice(0, 180); prob.appendChild(raw); }
      if (x.action === 'login') prob.appendChild(actionButton('login', true));
    }
  }
}
function renderProviders() {
  if ($('#providers-modal').classList.contains('hidden')) return;
  if (!provBuilt) buildProviders(); else paintProviders();
}
/** Send one provider's key/model to the backend (stored in config.json). Empty key = keep the saved one. */
function pushProvider(name) {
  const row = provRow(name); if (!row) return;
  const key = row.querySelector('.key'), model = row.querySelector('.model').value.trim();
  const msg = { type: 'set_provider', provider: name, model };
  if (key && key.value.trim()) { msg.api_key = key.value.trim(); key.value = ''; }
  window.copilot.send(msg);
}
function onProviderTest(ev) {
  const row = provRow(ev.provider); if (!row) return;
  const res = row.querySelector('.result');
  if (ev.state === 'running') { res.className = 'result'; res.textContent = t('prov.testing'); return; }
  provResults[ev.provider] = ev.ok;
  res.className = `result ${ev.ok ? 'ok' : 'bad'}`;
  res.textContent = ev.ok ? t('prov.test_ok', ev.ms, ev.model || '') : '';   // a failure is explained in the row's problem box (from status)
  if (!ev.ok && !((lastStatus.providers_info || {})[ev.provider] || {}).error) res.textContent = t('prov.test_bad', ev.error || 'failed');
}
function onProviderModels(ev) {
  const row = provRow(ev.provider); if (!row) return;
  const dl = row.querySelector('datalist'); dl.innerHTML = '';
  (ev.models || []).forEach((m) => { const o = document.createElement('option'); o.value = m; dl.appendChild(o); });
  const res = row.querySelector('.result');
  res.className = `result ${ev.models && ev.models.length ? 'ok' : 'bad'}`;
  res.textContent = ev.models && ev.models.length ? `${ev.models.length}: ${ev.models.slice(0, 8).join(', ')}${ev.models.length > 8 ? '…' : ''}` : (ev.error || '');
}
function openProviders(wizard = false) {
  provWizard = wizard;
  const s = lastStatus.settings || {}, info = lastStatus.providers_info || {};
  provPrimary = s.primary || 'claude';
  if (wizard && !(info[provPrimary] || {}).available) provPrimary = PROVIDER_ORDER.find((n) => (info[n] || {}).available) || provPrimary;
  $('#w-stt-engine').value = s.stt_engine || 'deepgram';
  $('#w-default-lang').value = ((lastStatus.profile || {}).config || {}).default_language === 'en' ? 'en' : 'es';
  $('#w-dg-key').placeholder = s.deepgram_key_set ? t('prov.key_saved') : '…';
  $('#w-groq-key').placeholder = s.groq_key_set ? t('prov.key_saved') : 'gsk_…';
  showWizardStt();
  $('#prov-hint').textContent = '';
  $('#providers-modal').classList.remove('hidden');
  provBuilt = false; buildProviders();
}
function closeProviders() {
  $('#providers-modal').classList.add('hidden');
  if (provWizard) window.copilot.send({ type: 'set_config', general: { onboarded: true } });   // never nag again
  provWizard = false;
}
function showWizardStt() { const e = $('#w-stt-engine').value; $$('.w-stt').forEach((el) => el.classList.toggle('hidden', el.dataset.engine !== e)); }
$('#w-stt-engine').addEventListener('change', showWizardStt);
$('#btn-providers').addEventListener('click', () => openProviders(false));
$('#prov-close').addEventListener('click', closeProviders);
$('#providers-modal').addEventListener('click', (e) => {
  const a = e.target.closest('a[data-ext]'); if (a) { e.preventDefault(); window.copilot.send({ type: 'open_external', url: a.dataset.ext }); }
});
$('#prov-save').addEventListener('click', () => {
  const info = lastStatus.providers_info || {};
  let usable = false;
  for (const name of PROVIDER_ORDER) {
    const row = provRow(name); if (!row) continue;
    const key = row.querySelector('.key');
    if ((info[name] || {}).available || (key && key.value.trim())) usable = true;
    pushProvider(name);
  }
  if (!usable) { $('#prov-hint').textContent = t('prov.need_one'); return; }
  const stt = { engine: $('#w-stt-engine').value };
  if ($('#w-dg-key').value.trim()) stt.deepgram_api_key = $('#w-dg-key').value.trim();
  if ($('#w-groq-key').value.trim()) stt.groq_api_key = $('#w-groq-key').value.trim();
  window.copilot.send({ type: 'set_config', general: { primary: provPrimary, onboarded: true }, stt });
  window.copilot.send({ type: 'set_profile_config', default_language: $('#w-default-lang').value });
  window.copilot.send({ type: 'set_updates', enabled: $('#w-auto-update').checked, auto_install: $('#w-auto-update').checked });
  $('#w-dg-key').value = ''; $('#w-groq-key').value = '';
  brainDirty = false; sttFormDirty = false; provWizard = false;
  $('#providers-modal').classList.add('hidden');
  toast(t('prov.saved'));
});

// ------------------------------------------------------------------ 1.0: auto-updater pill ------------------------------
let appVersion = '', lastUpdate = null;
function renderUpdate(ev) {
  lastUpdate = ev;
  const btn = $('#btn-update'), txt = $('#update-text'); if (!btn) return;
  const cur = ev.current || appVersion || '', v = ev.latest || '';
  const label = { checking: t('upd.checking'), available: t('upd.available', v), downloading: t('upd.downloading', v), installing: t('upd.installing', v),
    restarting: t('upd.restarting'), staged: t('upd.staged', v), up_to_date: t('upd.up_to_date', cur), error: t('upd.error', ev.error || '') }[ev.state] || t('upd.unconfigured', cur);
  txt.textContent = label;
  btn.className = `linkbtn nodrag update-pill ${ev.state || ''}`;
  btn.title = ev.state === 'error' ? ev.error : `${ev.repo || ''} · v${cur}${ev.notes ? '\n\n' + ev.notes : ''}`;
  if (['available', 'staged', 'restarting', 'error'].includes(ev.state)) toast(label, ev.state === 'error');
  if (ev.state === 'up_to_date' && ev.manual) toast(t('upd.none', cur));
  if (ev.state === 'checking' && ev.manual) toast(t('upd.checking_long'));
}
$('#btn-update').addEventListener('click', () => window.copilot.send({ type: lastUpdate && ['available', 'staged'].includes(lastUpdate.state) ? 'install_update' : 'check_updates' }));

// ------------------------------------------------------------------ 1.0: HUD height (compact / medium / tall) ------------
const HUD_HEIGHTS = [380, 520, 700];
$('#btn-hud-size').addEventListener('click', () => {
  const cur = window.innerHeight, next = HUD_HEIGHTS.find((h) => h > cur + 20) || HUD_HEIGHTS[0];
  window.copilot.send({ type: 'resize_hud', height: next });
});

// ------------------------------------------------------------------ v17: audio input mode (💻 PC / 📱 external call via mic)
let inputMode = 'pc';
function renderInputMode(mode, announce = false) {
  const prev = inputMode;
  inputMode = mode === 'external' ? 'external' : 'pc';
  document.documentElement.dataset.inputMode = inputMode;
  $$('#input-mode-setup button, #input-mode-live button').forEach((b) => b.classList.toggle('on', b.dataset.im === inputMode));
  if (announce && prev !== inputMode) toast(t(inputMode === 'external' ? 'im.toast.external' : 'im.toast.pc'));
}
$$('#input-mode-setup, #input-mode-live').forEach((seg) => seg.addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  window.copilot.send({ type: 'set_input_mode', value: b.dataset.im });
  renderInputMode(b.dataset.im, true);
}));

// ------------------------------------------------------------------ v17: latency pill (footer) ------------------------
function renderLatency(ev) {
  const pill = $('#latency-pill'); if (!pill) return;
  if (!ev || ev.elapsed_s == null) { pill.classList.add('hidden'); return; }
  pill.textContent = t('latency', ev.first_token_s, ev.elapsed_s);
  pill.className = `latency-pill ${ev.first_token_s != null && ev.first_token_s <= 1.5 ? 'fast' : ev.first_token_s > 4 ? 'slow' : ''}`;
}

// ------------------------------------------------------------------ v16: remote turn pill + "new turn" ------------------
let lastTurn = null;
function renderTurn(ev) {
  lastTurn = ev;
  const pill = $('#turn-pill'), txt = $('#turn-pill-text');
  if (!pill) return;
  const n = Number(ev.segments) || 0;
  if (!ev.turn_id || ev.state === 'idle' || ev.state === 'reset') { pill.classList.add('hidden'); pill.className = 'turn-pill hidden'; if (ev.state === 'reset') toast(t('turn.reset')); return; }
  const key = ['holding', 'generating', 'answered', 'closed'].includes(ev.state) ? ev.state : 'collecting';
  txt.textContent = key === 'closed' ? t('turn.closed') : ev.skip && key === 'collecting' ? `${t('turn.collecting', n)} · ${t('turn.skip', ev.skip)}` : t('turn.' + key, n);
  pill.className = `turn-pill ${key}`;
  pill.title = ev.text ? ev.text : pill.title;
  const card = turnCards.get(ev.turn_id);
  if (card && ev.state === 'answered') { card.el.classList.remove('updating'); setCardBadge(card, 'updating', ''); }
  if (card && ev.text) { const q = card.el.querySelector('.acard-head .q'); if (q) { q.textContent = ev.text; q.title = ev.text; } }
}
$('#btn-newturn').addEventListener('click', () => window.copilot.send({ type: 'new_turn' }));

// ------------------------------------------------------------------ live interim preview (streaming STT)
const interim = { channel: null, text: '' };
function renderInterim(channel, text) {
  const line = $('#interim-line'), span = $('#tx-interim');
  if (!line) return;
  if (!text) {
    if (interim.channel === channel || !channel) { interim.channel = null; interim.text = ''; line.classList.add('hidden'); span.textContent = ''; }
    return;
  }
  interim.channel = channel; interim.text = text;
  span.textContent = (channel === 'me' ? `(${t('tx.me')}) ` : '') + text;
  line.classList.remove('hidden');
}

// ------------------------------------------------------------------ pipeline diagnostics
let lastDiag = null;
function renderDiag() {
  const d = lastDiag, ev = lastStatus;
  const live = $('#diag-live'), box = $('#diag-setup');
  if (!d) { live.textContent = ''; return; }
  const chunks = (d.chunks.them || 0) + (d.chunks.me || 0);
  let stt = d.stt_state === 'transcribing' || d.stt_busy ? 'Transcribing…' : d.stt_state === 'ready' ? 'Ready' : d.stt_state === 'error' ? 'Error' : 'Loading…';
  if (!ev.stt_ready && ev.stt_error) stt = 'Failed';
  const eng = d.stt_engine === 'deepgram' ? 'Deepgram' : d.stt_engine === 'groq_whisper' ? 'Groq' : 'Whisper';
  if (d.stt_engine === 'deepgram' && d.stt_connections) { const c = d.stt_connections; stt = (c.them && c.them.connected) || (c.me && c.me.connected) ? 'Streaming' : 'Reconnecting…'; }
  const short = `${t('diag.chunks')}: ${chunks} · ${t('diag.seg')}: ${d.segments}/${d.transcribed} · ${eng}: ${stt}${d.stt_ms ? ` ${d.stt_ms}ms` : ''}${d.last_error ? ` · ${t('diag.err')}: ${d.last_error}` : ''}`;
  live.textContent = short;
  live.classList.toggle('bad', Boolean(d.last_error) || d.stt_state === 'error');
  let hint = '';
  if (!chunks) hint = t('diag.never');
  else if (!d.armed) hint = t('diag.notarmed');
  box.innerHTML = `<b>SYS</b> ${d.chunks.them} chunks · <b>MIC</b> ${d.chunks.me} chunks · speech segments ${d.segments} → transcribed ${d.transcribed} (queue ${d.queue})<br>` +
    `<b>STT</b> ${eng} ${stt}${d.stt_device ? ` on ${d.stt_device}` : ''}${d.stt_ms ? ` · last ${d.stt_ms} ms` : ''}${Number.isFinite(d.keyterms) ? ` · ${d.keyterms} keyterms` : ''}${ev.stt_error ? ` <span class="err">${escapeHtml(ev.stt_error)}</span>` : ''}` +
    (d.last_error ? `<br><span class="err">${escapeHtml(d.last_error)}</span>` : '') + (hint ? `<br><span class="dim">${escapeHtml(hint)}</span>` : '');
}

// ------------------------------------------------------------------ session exit
function exitSession() {
  $('#end-modal').classList.add('hidden');
  window.copilot.send({ type: 'exit_session' });
  window.copilot.send({ type: 'enter_setup' });
}
$('#btn-exit').addEventListener('click', exitSession);
$('#end-noanalysis').addEventListener('click', exitSession);

// ------------------------------------------------------------------ per-profile defaults (job role, company, language, playbook)
let bank = { roles: [], cvs: [], experience: [], playbooks: [] };
function loadProfileForm() {
  const cfg = (lastStatus.profile || {}).config || {};
  if (document.activeElement !== $('#p-job-role')) $('#p-job-role').value = cfg.job_role || '';
  if (document.activeElement !== $('#p-company')) $('#p-company').value = cfg.company || '';
  if (document.activeElement !== $('#p-default-language')) $('#p-default-language').value = cfg.default_language || 'en';
  fillPlaybookSelects(cfg.default_playbook || '');
}
let pfTimer = null;
for (const id of ['#p-job-role', '#p-company']) {
  $(id).addEventListener('input', () => {
    clearTimeout(pfTimer);
    pfTimer = setTimeout(() => window.copilot.send({ type: 'set_profile_config', job_role: $('#p-job-role').value.trim(), company: $('#p-company').value.trim() }), 700);
  });
}
$('#p-default-language').addEventListener('change', () => window.copilot.send({ type: 'set_profile_config', default_language: $('#p-default-language').value }));
$('#p-default-playbook').addEventListener('change', () => {
  const v = $('#p-default-playbook').value;
  window.copilot.send({ type: 'set_profile_config', default_playbook: v || null });
  if (v) window.copilot.send({ type: 'bank_attach', sub: 'playbooks', slot: 'playbook', names: [v] });
});

// ------------------------------------------------------------------ document & playbook bank
async function refreshBank() {
  try {
    const b = await window.copilot.bank.list();
    bank = { roles: b.roles || [], cvs: b.cvs || [], experience: b.experience || [], playbooks: b.playbooks || [] };
    fillBankSelects();
  } catch (e) { toast(e.message, true); }
}
function bankLabel(it) {
  const name = (it.originalName || it.filename).replace(/\.(md|txt)$/i, '');
  return `${name} · ${(it.wordCount || 0).toLocaleString()} w`;
}
function fillBankSelects() {
  for (const sel of $$('select.bank-select')) {
    const sub = sel.dataset.bankSub;
    const first = sel.querySelector('option');
    sel.innerHTML = '';
    sel.appendChild(first);
    for (const it of bank[sub] || []) {
      const o = document.createElement('option'); o.value = it.filename; o.textContent = bankLabel(it); sel.appendChild(o);
    }
    renderBankDelete(sel);
  }
  fillPlaybookSelects(((lastStatus.profile || {}).config || {}).default_playbook || '');
}
function fillPlaybookSelects(current) {
  const sel = $('#p-default-playbook');
  sel.innerHTML = '';
  const none = document.createElement('option'); none.value = ''; none.textContent = t('bank.none_pb'); sel.appendChild(none);
  for (const it of bank.playbooks || []) { const o = document.createElement('option'); o.value = it.filename; o.textContent = (it.originalName || it.filename).replace(/\.(md|txt)$/i, ''); if (it.filename === current) o.selected = true; sel.appendChild(o); }
  if (current && !(bank.playbooks || []).some((x) => x.filename === current)) { const o = document.createElement('option'); o.value = current; o.textContent = current; o.selected = true; sel.appendChild(o); }
}
$$('select.bank-select').forEach((sel) => sel.addEventListener('change', () => {
  if (!sel.value) return;
  window.copilot.send({ type: 'bank_attach', sub: sel.dataset.bankSub, slot: sel.dataset.bankSlot, names: [sel.value] });
  if (sel.dataset.bankSlot === 'playbook') $('#pb-bank-name').value = sel.value.replace(/\.(md|txt)$/i, '');
  sel.value = '';
}));
/** 🗑️ next to a bank selector: opens a small list of that category's entries with delete buttons. */
function renderBankDelete(sel) {
  const sub = sel.dataset.bankSub;
  let btn = sel.parentElement.querySelector(`[data-bank-trash="${sub}"]`);
  if (!btn) {
    btn = document.createElement('button'); btn.className = 'btn small ghost'; btn.title = t('bank.manage'); btn.textContent = '🗑️';
    btn.dataset.bankTrash = sub;
    sel.insertAdjacentElement('afterend', btn);
    btn.addEventListener('click', () => openBankManage(sub));
  }
  btn.classList.toggle('hidden', !(bank[sub] || []).length);
}
function openBankManage(sub) {
  bankPickSlot = null;
  $('#bank-modal-title').textContent = `${t('pm.bank')} — ${t('bank.cat.' + sub)}`;
  const list = $('#bank-modal-list'); list.innerHTML = '';
  const items = bank[sub] || [];
  if (!items.length) list.appendChild(el('div', 'dim', t('bank.empty')));
  for (const it of items) {
    const row = el('div', 'bank-item');
    row.appendChild(el('span', 'name', bankLabel(it)));
    row.appendChild(el('span', 'dim', `${it.source || ''}${it.profile ? ' · ' + it.profile : ''} · ${(it.updatedAt || '').slice(0, 10)}`));
    const del = el('button', 'btn small danger', '🗑️');
    const protectedEntry = sub === 'playbooks' && it.filename === 'default_playbook.md';
    del.disabled = protectedEntry;
    del.addEventListener('click', async () => {
      if (!confirm(t('bank.confirm_delete', it.originalName || it.filename))) return;
      try { await window.copilot.bank.remove(sub, it.filename); } catch (e) { toast(e.message, true); }
      await refreshBank(); openBankManage(sub);
    });
    row.appendChild(del); list.appendChild(row);
  }
  $('#bank-modal-attach').classList.add('hidden');
  $('#bank-modal').classList.remove('hidden');
}
let bankPickSlot = null;
$$('[data-bank-open]').forEach((b) => b.addEventListener('click', () => {
  bankPickSlot = b.dataset.bankOpen;
  $('#bank-modal-title').textContent = t('bank.title');
  $('#bank-modal-attach').classList.remove('hidden');
  const list = $('#bank-modal-list'); list.innerHTML = '';
  const items = bank.experience || [];
  if (!items.length) { const d = document.createElement('div'); d.className = 'dim'; d.textContent = t('bank.empty'); list.appendChild(d); }
  for (const it of items) {
    const row = document.createElement('label'); row.className = 'bank-item';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.value = it.filename;
    const nm = document.createElement('span'); nm.className = 'name'; nm.textContent = (it.originalName || it.filename).replace(/\.(md|txt)$/i, '');
    const w = document.createElement('span'); w.className = 'dim'; w.textContent = `${(it.wordCount || 0).toLocaleString()} w`;
    row.append(cb, nm, w); list.appendChild(row);
  }
  $('#bank-modal').classList.remove('hidden');
}));
$('#bank-modal-cancel').addEventListener('click', () => $('#bank-modal').classList.add('hidden'));
$('#bank-modal').addEventListener('click', (e) => { if (e.target.id === 'bank-modal') $('#bank-modal').classList.add('hidden'); });
$('#bank-modal-attach').addEventListener('click', () => {
  const names = $$('#bank-modal-list input:checked').map((c) => c.value);
  $('#bank-modal').classList.add('hidden');
  if (names.length) window.copilot.send({ type: 'bank_attach', sub: 'experience', slot: bankPickSlot || 'experience', names });
});
$('#btn-bank').addEventListener('click', () => window.copilot.profiles.openBank());
$('#bank-trash-experience').addEventListener('click', () => openBankManage('experience'));

// ------------------------------------------------------------------ archived profiles
function renderArchived(list) {
  const box = $('#archived-list'); box.innerHTML = '';
  if (!list.length) { const d = document.createElement('div'); d.className = 'dim'; d.textContent = t('pm.none_archived'); box.appendChild(d); return; }
  for (const p of list) {
    const row = document.createElement('div'); row.className = 'bank-item';
    const nm = document.createElement('span'); nm.className = 'name'; nm.textContent = typeof p === 'string' ? p : p.name;
    const meta = document.createElement('span'); meta.className = 'dim'; meta.textContent = p.sessions != null ? t('an.turns', p.sessions, 0).split(' · ')[0].replace(/turnos|turns/, 'sesiones') : '';
    const logs = document.createElement('button'); logs.className = 'btn small'; logs.textContent = t('sessions.log');
    logs.addEventListener('click', () => { $('#archived-modal').classList.add('hidden'); showTab('sessions'); $('#session-profile').value = `archived:${nm.textContent}`; loadSessions(); });
    const rs = document.createElement('button'); rs.className = 'btn small primary'; rs.textContent = t('pm.restore');
    rs.addEventListener('click', () => window.copilot.send({ type: 'restore_profile', name: nm.textContent }));
    row.append(nm, meta, logs, rs); box.appendChild(row);
  }
}
$('#btn-archived').addEventListener('click', () => { window.copilot.send({ type: 'list_profiles' }); $('#archived-modal').classList.remove('hidden'); });
$('#archived-close').addEventListener('click', () => $('#archived-modal').classList.add('hidden'));
$('#archived-modal').addEventListener('click', (e) => { if (e.target.id === 'archived-modal') $('#archived-modal').classList.add('hidden'); });

// ------------------------------------------------------------------ analysis dashboard
function scoreClass(n) { return n == null ? 'none' : n >= 75 ? 'hi' : n >= 60 ? 'mid' : 'lo'; }
function fillSessionProfiles() {
  const sel = $('#session-profile');
  const cur = sel.value || $('#profile-select').value;
  const p = lastStatus.profile || {};
  sel.innerHTML = '';
  for (const n of p.profiles || profileList) { const o = document.createElement('option'); o.value = n; o.textContent = n; sel.appendChild(o); }
  for (const n of p.archived || []) { const o = document.createElement('option'); o.value = `archived:${n}`; o.textContent = `${n} ${t('sessions.archived_tag')}`; sel.appendChild(o); }
  if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
}
$('#session-profile').addEventListener('change', () => { currentSession = null; loadSessions(); });
function sessionProfileArgs() {
  const v = $('#session-profile').value || $('#profile-select').value;
  return v.startsWith('archived:') ? [v.slice(9), true] : [v, false];
}
function fmtStamp(stamp) { return stamp.replace(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2}).*$/, '$1-$2-$3 $4:$5'); }
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
async function renderAnalysis(s) {
  const body = $('#analysis-body'); body.innerHTML = '';
  let data = null;
  if (s.analysis) { try { data = await window.copilot.sessions.readJson(s.analysis); } catch (e) { toast(e.message, true); } }
  const a = data && data.analysis;
  if (a) {
    const card = el('div', 'scorecard');
    const big = el('div', `score-big ${scoreClass(a.overall_score)}`); big.append(el('div', 'num', String(a.overall_score)), el('div', 'den', `/ 100 · ${t('an.grade')}`)); card.appendChild(big);
    const subs = el('div', 'subscores');
    for (const [k, label] of [['clarity_concision', 'an.clarity'], ['technical_depth', 'an.depth'], ['example_structure', 'an.examples'], ['role_alignment', 'an.role']]) {
      const v = (a.sub_scores || {})[k] ?? 0;
      const row = el('div', 'subscore'); const bar = el('div', 'bar'); const fill = el('i'); fill.style.width = `${v}%`; bar.appendChild(fill);
      row.append(el('span', null, t(label)), bar, el('b', null, String(v))); subs.appendChild(row);
    }
    if (a.score_rationale) subs.appendChild(el('p', 'dim', a.score_rationale));
    card.appendChild(subs); body.appendChild(card);
    const p1 = el('div', 'apanel'); p1.appendChild(el('h4', null, t('an.summary'))); p1.appendChild(el('p', null, a.session_summary || t('an.none')));
    p1.appendChild(el('h4', null, t('an.decisions')));
    const ul = el('ul'); for (const d of a.decisions_next_steps || []) ul.appendChild(el('li', null, d)); if (!(a.decisions_next_steps || []).length) ul.appendChild(el('li', null, t('an.none'))); p1.appendChild(ul);
    body.appendChild(p1);
    const p2 = el('div', 'apanel'); p2.appendChild(el('h4', null, t('an.qa')));
    for (const q of a.qa_review || []) {
      const d = el('div', 'qa'); d.appendChild(el('div', 'q', q.question || ''));
      for (const [lbl, key, cls] of [['an.said', 'what_i_said', ''], ['an.good', 'worked_well', ''], ['an.tighten', 'tighten', ''], ['an.ideal', 'ideal_answer', 'ideal']]) {
        if (!q[key]) continue;
        const p = el('p', cls); p.appendChild(el('span', 'lbl', t(lbl))); p.appendChild(document.createTextNode(q[key])); d.appendChild(p);
      }
      p2.appendChild(d);
    }
    body.appendChild(p2);
    const p3 = el('div', 'apanel');
    for (const [h, key] of [['an.pacing', 'pacing_clarity'], ['an.well', 'went_well'], ['an.adjust', 'top_adjustments']]) {
      p3.appendChild(el('h4', null, t(h))); const l = el(key === 'top_adjustments' ? 'ol' : 'ul'); for (const x of a[key] || []) l.appendChild(el('li', null, x)); p3.appendChild(l);
    }
    body.appendChild(p3);
  } else {
    body.appendChild(el('p', 'dim', t('sessions.noanalysis')));
  }
  // full transcript (collapsible, copyable)
  if (s.log_md) {
    const det = document.createElement('details'); det.className = 'apanel transcript';
    const sum = el('summary', null, t('an.transcript')); det.appendChild(sum);
    const pre = el('pre'); det.appendChild(pre);
    const copy = el('button', 'btn small', t('an.copy')); copy.addEventListener('click', () => navigator.clipboard.writeText(pre.textContent)); det.appendChild(copy);
    det.addEventListener('toggle', async () => { if (det.open && !pre.textContent) { try { pre.textContent = await window.copilot.sessions.read(s.log_md); } catch (e) { pre.textContent = e.message; } } });
    body.appendChild(det);
  }
}

// ------------------------------------------------------------------ quick session focus (optional)
const FOCUS_PRESETS = {
  tech: 'Entrevista técnica: priorizar arquitectura práctica (hands-on), herramientas concretas, decisiones de diseño y métricas.',
  exec: 'Entrevista ejecutiva / CISO: priorizar estrategia, reducción de riesgo, ROI, gobierno y liderazgo de equipos.',
  incident: 'Incidente en vivo: priorizar triage, contención, análisis de causa raíz (RCA) y pasos de mitigación inmediatos.',
  roadmap: 'Plan estratégico / roadmap: priorizar planes 30-60-90 días, modelos de madurez, gobierno y secuenciación.',
  client: 'Cliente / arquitectura: priorizar discovery, trade-offs, patrones de integración y criterios de decisión.',
};
let focusText = '';
let focusTimer = null;
function focusSend(value) {
  focusText = (value || '').trim();
  window.copilot.send({ type: 'set_focus', value: focusText });
}
function renderFocus() {
  const inp = $('#focus-input');
  if (document.activeElement !== inp) inp.value = focusText;
  $$('#focus-chips .chip').forEach((c) => c.classList.toggle('on', focusText.includes(FOCUS_PRESETS[c.dataset.chip])));
  $('#focus-status').textContent = focusText ? `${focusText.split(/\s+/).filter(Boolean).length} w` : '';
  const pill = $('#pill-focus');
  pill.classList.toggle('on', Boolean(focusText));
  $('#pill-focus-text').textContent = focusText ? focusText.slice(0, 28) + (focusText.length > 28 ? '…' : '') : t('focus.pill');
  pill.title = focusText || t('focus.none');
}
$('#focus-input').addEventListener('input', () => {
  clearTimeout(focusTimer);
  focusTimer = setTimeout(() => { focusSend($('#focus-input').value); renderFocus(); }, 500);
});
$('#focus-input').addEventListener('blur', () => { clearTimeout(focusTimer); focusSend($('#focus-input').value); renderFocus(); });
$('#focus-clear').addEventListener('click', () => { focusSend(''); renderFocus(); toast(t('focus.cleared')); });
$('#focus-chips').addEventListener('click', (e) => {
  const chip = e.target.closest('.chip'); if (!chip) return;
  const preset = FOCUS_PRESETS[chip.dataset.chip];
  let txt = $('#focus-input').value;
  if (txt.includes(preset)) txt = txt.replace(preset, '').replace(/\n{2,}/g, '\n').trim();
  else txt = (txt.trim() ? txt.trim() + '\n' : '') + preset;
  $('#focus-input').value = txt;
  focusSend(txt); renderFocus();
});
// live HUD: pill opens an inline editor; Enter applies immediately
$('#pill-focus').addEventListener('click', () => {
  const box = $('#focus-edit');
  box.classList.toggle('hidden');
  if (!box.classList.contains('hidden')) { $('#focus-edit-input').value = focusText; setTimeout(() => $('#focus-edit-input').focus(), 20); }
});
function applyLiveFocus() {
  focusSend($('#focus-edit-input').value); renderFocus();
  $('#focus-edit').classList.add('hidden');
  toast(focusText ? t('focus.saved') : t('focus.cleared'));
}
$('#focus-edit-apply').addEventListener('click', applyLiveFocus);
$('#focus-edit-clear').addEventListener('click', () => { $('#focus-edit-input').value = ''; applyLiveFocus(); });
$('#focus-edit-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); applyLiveFocus(); }
  if (e.key === 'Escape') { e.preventDefault(); $('#focus-edit').classList.add('hidden'); }
});

// ------------------------------------------------------------------ events
window.copilot.onEvent((ev) => {
  switch (ev.type) {
    case 'hud_config':
      hotkeys = ev.hotkeys || {}; platform = ev.platform || platform;
      if (Number.isFinite(ev.font_size) && !localStorage.getItem('answerFontSize')) applyFontSize(ev.font_size, false);
      if (Number.isFinite(ev.hud_alpha)) applyHudOpacity(ev.hud_alpha, false);
      if (ev.version) { appVersion = ev.version; if (!lastUpdate) renderUpdate({ state: 'idle', current: ev.version }); }
      if (ev.updates) $('#w-auto-update').checked = ev.updates.enabled !== false && ev.updates.auto_install !== false;
      if (Number.isFinite(ev.auto_vision_interval_s)) autoVision.intervalMs = Math.max(2000, ev.auto_vision_interval_s * 1000);
      ghost = Boolean(ev.ghost); renderGhost();
      if (ev.mode) setMode(ev.mode);
      if (ev.auto_vision && !autoVision.enabled) setAutoVision(true, false, false);
      renderHotkeys();
      break;
    case 'ghost': ghost = Boolean(ev.enabled); renderGhost(); toast(ghost ? t('ghost.on') : t('ghost.off')); break;
    case 'hud_opacity': applyHudOpacity(ev.value); break;
    case 'scroll_feed': scrollFeedBy(Number(ev.direction) || 1); break;
    case 'toggle_auto_vision': setAutoVision(!autoVision.enabled); break;
    case 'toast': toast(ev.message || ''); break;
    case 'mode': setMode(ev.mode); break;
    case 'stealth':
      $('#stealth-setup').classList.toggle('hidden', !ev.enabled);
      $('#stealth-live').classList.toggle('hidden', !ev.enabled);
      if (typeof ev.ghost === 'boolean' && ev.ghost !== ghost) { ghost = ev.ghost; renderGhost(); }
      break;
    case 'backend_link':
      lastStatus.backend_link = ev.connected;
      renderStatus();
      if (ev.connected) setTimeout(() => { try { loadContext(); } catch {} }, 300);
      break;
    case 'update_status': renderUpdate(ev); break;
    case 'provider_test': onProviderTest(ev); break;
    case 'provider_models': onProviderModels(ev); break;
    case 'status': {
      const prev = lastStatus.settings || {};
      lastStatus = { ...ev, backend_link: lastStatus.backend_link };
      const s = ev.settings || {};
      const wanted = resolveUiLang(s.ui_language || 'auto', s.language || 'auto');
      if (wanted !== uiLang) applyUiLanguage(wanted); else renderStatus();
      if (ev.hotkeys && !hotkeys.force_answer) { hotkeys = ev.hotkeys; renderHotkeys(); }
      if (prev.language && prev.language !== s.language) toast(t('lang.flip', s.language || 'auto'));
      if (prev.tone && (prev.tone !== s.tone || prev.length !== s.length)) toast(`${t('toast.style')}${t('tone.' + s.tone)} · ${t('len.' + s.length)}`);
      if (ev.stt_error) toast(`STT: ${ev.stt_error}`, true);
      if (typeof ev.session_focus === 'string' && ev.session_focus !== focusText && document.activeElement !== $('#focus-input') && document.activeElement !== $('#focus-edit-input')) { focusText = ev.session_focus; renderFocus(); }
      loadBrainForm();
      loadProfileForm();
      fillDeviceSelects();
      syncElectronCapture();
      renderProviders();
      if (ev.onboarded === false && !onboardingShown && mode === 'setup') { onboardingShown = true; openProviders(true); }
      break;
    }
    case 'levels': renderMeters(ev); if (ev.diag) { lastDiag = ev.diag; renderDiag(); } break;
    case 'audio_devices': lastDevices = ev; fillDeviceSelects(); if ((ev.errors || []).length) toast(ev.errors.join(' | '), true); break;
    case 'gemini_models':
      if (ev.models && ev.models.length) { lastStatus.settings = { ...(lastStatus.settings || {}), gemini_models: ev.models }; fillSelect($('#s-gemini-model'), ev.models, $('#s-gemini-model').value); toast(t('gemini.listed', ev.models.length)); }
      else toast(ev.error || 'Gemini: no models', true);
      break;
    case 'context_progress': {
      parsing[ev.slot] = parsing[ev.slot] || new Set();
      if (ev.state === 'parsing') parsing[ev.slot].add(ev.file); else parsing[ev.slot].delete(ev.file);
      if (lastManifest) renderContext(lastManifest);
      break;
    }
    case 'manual_context': manualTexts = { role: ev.role || '', profile: ev.profile || '', experience: ev.experience || '' }; if (lastManifest) renderContext(lastManifest); break;
    case 'manual_saved': toast(t('toast.manual')); refreshBank(); break;
    case 'bank_changed': if (ev.bank) { bank = { roles: ev.bank.roles || [], cvs: ev.bank.cvs || [], experience: ev.bank.experience || [], playbooks: ev.bank.playbooks || [] }; fillBankSelects(); } else refreshBank(); break;
    case 'bank_attached': toast(t('bank.attached', (ev.names || []).length)); loadContext(); break;
    case 'profiles': if (ev.profiles) { profileList = ev.profiles.map((p) => p.name); lastStatus.profile = { ...(lastStatus.profile || {}), profiles: profileList, archived: (ev.archived || []).map((p) => p.name) }; renderProfileSelect(); renderArchived(ev.archived || []); fillSessionProfiles(); } break;
    case 'playbook_saved': $('#playbook-status').textContent = `✓ ${t('toast.pb')}`; break;
    case 'transcript': {
      const target = ev.channel === 'me' ? $('#tx-me') : $('#tx-them'), line = ev.channel === 'me' ? $('#transcript .me') : $('#transcript .them');
      target.textContent = ev.text; target.title = ev.text;
      line.classList.toggle('partial', Boolean(ev.partial));
      $$('#transcript .line:not(.interim)').forEach((l) => l.classList.remove('fresh')); line.classList.add('fresh');
      if (interim.channel === ev.channel && !ev.partial) renderInterim(ev.channel, '');
      break;
    }
    case 'interim': renderInterim(ev.channel, ev.text || ''); break;
    case 'story': renderStory(ev); break;
    case 'stt_language': if (ev.decoder) { lastStatus.stt = { ...(lastStatus.stt || {}), language: ev.decoder }; renderStatus(); if (ev.source !== 'user') toast(t('stt.decoder', ev.decoder, ev.source)); } break;
    case 'turn': renderTurn(ev); break;
    case 'answer_hold': {
      const card = (ev.gen_id != null && cards.get(ev.gen_id)) || (ev.turn_id != null && turnCards.get(ev.turn_id));
      if (card) { card.el.classList.add('updating'); setCardBadge(card, 'updating', ev.reason === 'context_setup' ? t('card.holding') : ev.reason === 'language_flip' ? t('lang.rescue') : t('card.updating')); }
      if (ev.reason === 'language_flip') toast(t('lang.rescue'));
      else renderTurn({ ...(lastTurn || {}), turn_id: ev.turn_id, state: 'holding' });
      break;
    }
    case 'llm_start': {
      if (ev.mode === 'debrief') { currentGen = ev.gen_id; buffer = ''; streaming = true; renderStatus(); scheduleRender(); break; }
      let card = cards.get(ev.gen_id);
      if (!card && ev.turn_id != null && turnCards.has(ev.turn_id)) card = reuseCard(turnCards.get(ev.turn_id), ev);   // v16 in-place replacement
      if (!card && ev.replace_gen_id != null && cards.has(ev.replace_gen_id)) card = reuseCard(cards.get(ev.replace_gen_id), ev);   // v18 language flip on a non-turn card
      if (!card) card = newCard(ev);
      if (ev.turn_id != null && card.turn_id == null) { card.turn_id = ev.turn_id; turnCards.set(ev.turn_id, card); }
      if (ev.question) { const qel = card.el.querySelector('.acard-head .q'); if (qel && !qel.textContent) { qel.textContent = ev.question; qel.title = ev.question; } }
      if (ev.turn_id != null && ev.turn_segments) setCardBadge(card, 'turnseg', ev.turn_segments > 1 ? t('card.segments', ev.turn_segments) : '');
      if (ev.part === 'full' && ev.lang) { setCardBadge(card, 'lang', ev.lang_mode === 'auto' ? t('card.lang_auto', ev.lang) : ev.lang.toUpperCase()); card.el.querySelector('.badge.lang').classList.toggle('auto', ev.lang_mode === 'auto'); }
      if (ev.part === 'opener') card.streaming.opener = true; else card.streaming.full = true;
      if (ev.retrieval && !card.retrieval.length) card.retrieval = ev.retrieval;
      renderStatus();
      break;
    }
    case 'llm_reset': {
      if (ev.gen_id === currentGen) { buffer = ''; scheduleRender(); break; }
      const card = cards.get(ev.gen_id); if (card) { card.fullText = ''; paintCard(card); }
      break;
    }
    case 'llm_token': {
      if (ev.gen_id === currentGen) { buffer += ev.text; scheduleRender(); break; }
      const card = cards.get(ev.gen_id); if (!card) break;
      if (ev.part === 'opener') card.openerText += ev.text; else card.fullText += ev.text;
      paintCard(card);
      break;
    }
    case 'llm_end': {
      if (ev.gen_id === currentGen) {
        streaming = false; scheduleRender(); renderStatus();
        if (!ev.provider && !ev.cancelled) { const f = splitError((ev.errors || [])[0] || 'Analysis failed'), x = explainError(f.provider, f.message); (ev.errors || []).forEach(rememberError); toast([provLabel(f.provider), x.text].filter(Boolean).join(': '), true, x.action); }
        break;
      }
      const card = cards.get(ev.gen_id); if (!card) break;
      if (ev.part === 'opener') { card.streaming.opener = false; card.openerMs = ev.elapsed_s; if (!ev.provider || ev.errors.length) card.openerText = ''; paintCard(card); break; }
      card.streaming.full = false; paintCard(card); renderStatus();
      if (ev.cancelled && card.turn_id != null && card.el.classList.contains('updating')) break;   // v16: aborted, a replacement is coming
      if (ev.provider || ev.cancelled) cardMeta(card, ev); else card.meta.textContent = '';
      if (ev.provider) renderLatency(ev);
      if (!ev.provider && !ev.cancelled) renderFailure(card, ev);
      else if (ev.provider && (ev.errors || []).length) {
        const f = splitError(ev.errors[0]), x = explainError(f.provider, f.message);
        rememberError(`${f.provider}: ${f.message}`);
        toast(t('fail.fallback', provLabel(f.provider), x.text.replace(/\.$/, '')), true, x.action === 'login' ? 'login' : null);
      }
      break;
    }
    case 'session':
      if (ev.state === 'ended_no_analysis') {
        clearAnswer();
        window.copilot.send({ type: 'enter_setup' });
        setTimeout(() => toast(ev.reason === 'user' ? t('toast.exited') : t('toast.no_analysis')), 50);
        if (activeTab === 'sessions') loadSessions();
      }
      if (ev.state === 'analyzing') {
        // Analysis streams into the Sessions tab of the dashboard; the live HUD is closed immediately.
        window.copilot.send({ type: 'enter_setup' });
        showTab('sessions');
        currentSession = null;
        $('#session-title').textContent = `${ev.stamp} — ${t('meta.debrief')}`;
        $('#analysis-body').innerHTML = '';
        debriefTarget = $('#analysis-body');
      }
      if (ev.state === 'analyzed') {
        toast(t('toast.analyzed', ev.memory_words || 0) + (ev.score != null ? ` · ${ev.score}/100` : ''));
        clearAnswer();
        currentSession = null; showTab('sessions');
        $('#tx-them').textContent = '…'; $('#tx-me').textContent = '…';
        debriefTarget = null;
        loadSessions();
      }
      break;
    case 'clear': clearAnswer(); break;
    case 'screenshot': toast(t('toast.shot', Math.round(ev.bytes / 1024))); break;
    case 'confirm_end_session': askEndSession(); break;
    case 'return_live': window.copilot.send({ type: 'enter_live' }); break;
    case 'open_settings': window.copilot.send({ type: 'enter_setup' }); break;
    case 'error': { rememberError(ev.message); const f = splitError(ev.message), x = explainError(f.provider, f.message); toast(x.code === 'other' ? ev.message : [provLabel(f.provider), x.text].filter(Boolean).join(': '), true, x.code === 'other' ? null : x.action); break; }
    case 'report_status': onReportStatus(ev); break;
    case 'claude_login': toast(t('login.opened')); break;
    case 'hint': if (ev.code === 'echo') toast(t('hint.echo'), true); else if (ev.message) toast(ev.message); break;
    case 'log': if (/^READY/.test(ev.message)) toast(t('toast.ready')); break;
    default: break;
  }
});

applyUiLanguage('es');
showTab('profile');
refreshBank();
