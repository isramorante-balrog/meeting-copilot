'use strict';
/**
 * Meeting Copilot — Electron main process.
 *
 *  - One BrowserWindow with two modes:
 *      setup : solid dashboard (profiles, documents, bank, playbook, audio, past sessions)
 *      live  : compact frosted HUD bar at the top-center, skipTaskbar, always on top
 *  - setContentProtection(true) on creation and on every mode switch (invisible to screen share);
 *  - v15: ghost mode (click-through, Alt+G), keyboard nudge / scroll / background opacity, passive
 *    auto-vision frames every 5 s, neutral window identity ("Audio Engine Host"), no focus theft in live mode;
 *    the window is never hidden or dimmed for screen capture.
 *  - Native file dialogs run with the overlay lowered so they can never hide behind the HUD.
 *  - File parsing happens in a worker thread (context_manager.js -> parse_worker.js): the UI never blocks.
 *  - Global Document & Playbook Bank: every upload / pasted text is also saved to data/bank/<category>/.
 *  - Spawns the Python backend, relays its WebSocket events to the renderer, registers Alt+key hotkeys.
 *
 * State that IPC handlers depend on lives in a single `state` object created before any handler runs,
 * so there are no free-floating globals that can be undefined (`state.profiles`, `state.bank`).
 */
const { app, BrowserWindow, globalShortcut, ipcMain, screen, dialog, Tray, Menu, nativeImage, shell, session, desktopCapturer, clipboard } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn, spawnSync } = require('child_process');
const WebSocket = require('ws');
const { ProfileManager, listSessions, readTextFile, terminateParser, SLOT_TO_CATEGORY } = require('./context_manager');
const { Updater } = require('./updater');
const { Reporter } = require('./reporter');

// ------------------------------------------------------------------ paths & config
const ROOT = path.join(__dirname, '..');
const CONFIG_PATH = path.join(ROOT, 'config.json');
const LOG_DIR = path.join(ROOT, 'logs');
const CONTEXT_DIR = path.join(ROOT, 'context'); // legacy flat context (migrated into profiles/default)
const PROFILES_DIR = path.join(ROOT, 'profiles');
const ARCHIVED_DIR = path.join(ROOT, 'profiles_archived');
const BANK_DIR = path.join(ROOT, 'data', 'bank');
const DEBUG = process.argv.includes('--debug');
// Neutral identity for the OS: window title, taskbar/app-model id, tray tooltip, process title.
const APP_DISPLAY_NAME = 'Audio Engine Host';
const APP_USER_MODEL_ID = 'com.audioenginehost.client';
try { process.title = APP_DISPLAY_NAME; } catch {}
try { app.setName(APP_DISPLAY_NAME); } catch {}

// ---- file logging (the launcher closes the console, so keep a log on disk)
let logStream = null;
try {
  fs.mkdirSync(LOG_DIR, { recursive: true });
  logStream = fs.createWriteStream(path.join(LOG_DIR, 'copilot.log'), { flags: 'a' });
} catch {}
function logLine(...parts) {
  const line = `[${new Date().toISOString()}] ${parts.join(' ')}`;
  process.stdout.write(line + '\n');
  if (logStream) logStream.write(line + '\n');
}
console.log = logLine;
console.error = logLine;

const DEFAULT_CONFIG = {
  backend: { host: '127.0.0.1', port: 8765, python: '' },
  updates: { enabled: true, auto_install: true, repo: 'isramorante-balrog/meeting-copilot', check_hours: 6 },
  // Problem reports become GitHub issues on `repo`. Without a token the browser opens a pre-filled issue;
  // with a maintainer token (Issues: read/write) they are created directly. See electron/reporter.js.
  reports: { repo: 'isramorante-balrog/meeting-copilot', github_token: '', include_log: true },
  hud: { width: 520, height: 460, max_width: 520, top: 6, opacity: 0.75, font_size: 17, setup_width: 1040, setup_height: 720,
         nudge_px: 40, auto_vision: false, auto_vision_interval_s: 5 },
  hotkeys: {
    screenshot: 'Alt+S', force_answer: 'Alt+A', toggle_visibility: 'Alt+H', toggle_listening: 'Alt+M',
    followup_example: 'Alt+1', followup_deepen: 'Alt+2', followup_tldr: 'Alt+3', followup_pivot: 'Alt+4',
    end_session: 'Alt+E', summarize: 'Alt+U', clear: 'Alt+X', toggle_language: 'Alt+L', settings: 'Alt+T', quit: 'Alt+Q',
    ghost: 'Alt+G', auto_vision: 'Alt+V', new_turn: 'Alt+N', input_mode: 'Alt+P',
    nudge_up: 'Alt+Shift+Up', nudge_down: 'Alt+Shift+Down', nudge_left: 'Alt+Shift+Left', nudge_right: 'Alt+Shift+Right',
    scroll_up: 'Alt+Up', scroll_down: 'Alt+Down', opacity_down: 'Alt+[', opacity_up: 'Alt+]',
  },
};
function loadConfig() {
  let user = {};
  try {
    user = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch (e) {
    console.error('[main] config.json unreadable, using defaults:', e.message);
  }
  const hotkeys = { ...DEFAULT_CONFIG.hotkeys, ...(user.hotkeys || {}) };
  // v15: Alt+G became ghost mode; an old config.json still mapping Setup⇄Live to Alt+G moves to Alt+T.
  if (hotkeys.settings === 'Alt+G' && hotkeys.ghost === 'Alt+G') hotkeys.settings = 'Alt+T';
  const hud = { ...DEFAULT_CONFIG.hud, ...(user.hud || {}) };
  if (!(Number(hud.opacity) > 0) || Number(hud.opacity) > 0.95) hud.opacity = Number(hud.opacity) >= 1 ? 0.75 : DEFAULT_CONFIG.hud.opacity;
  return {
    ...DEFAULT_CONFIG,
    ...user,
    backend: { ...DEFAULT_CONFIG.backend, ...(user.backend || {}) },
    updates: { ...DEFAULT_CONFIG.updates, ...(user.updates || {}) },
    reports: { ...DEFAULT_CONFIG.reports, ...(user.reports || {}) },
    hud,
    hotkeys,
  };
}
const config = loadConfig();

// ------------------------------------------------------------------ shared state (always defined)
const state = {
  win: null,
  tray: null,
  backendProc: null,
  ws: null,
  wsReconnectTimer: null,
  wsConnected: false,
  quitting: false,
  visible: true,
  mode: 'setup', // 'setup' | 'live'
  setupBounds: null,
  dialogDepth: 0,
  lastShot: 0,
  ghost: false, // v15 click-through mode (live only)
  focusable: true,
  activeProfile: 'default',
  /** @type {import('./context_manager').ProfileManager|null} */
  profiles: null,
};

/** Profile manager + bank, created lazily so IPC handlers can never hit an undefined reference. */
function getProfiles() {
  if (!state.profiles) {
    state.profiles = new ProfileManager(PROFILES_DIR, CONTEXT_DIR, BANK_DIR);
    try {
      const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
      state.activeProfile = (cfg.general && cfg.general.active_profile) || 'default';
    } catch {}
    if (!state.profiles.exists(state.activeProfile)) state.activeProfile = state.profiles.list()[0] || 'default';
  }
  return state.profiles;
}
function getBank() {
  return getProfiles().bank;
}
function currentProfile() {
  return state.activeProfile || 'default';
}

// ------------------------------------------------------------------ window & modes
function applyStealth() {
  const win = state.win;
  if (!win || win.isDestroyed()) return;
  win.setContentProtection(true);
  if (state.mode === 'live') {
    win.setAlwaysOnTop(true, 'screen-saver');
    win.setSkipTaskbar(true);
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    applyGhost();
  } else {
    win.setAlwaysOnTop(false);
    win.setSkipTaskbar(false);
    win.setVisibleOnAllWorkspaces(false);
    win.setIgnoreMouseEvents(false);
    setFocusableSafe(win, true);
  }
  sendToRenderer({ type: 'stealth', enabled: true, mode: state.mode, ghost: state.mode === 'live' && state.ghost });
}

// ---- v15: ghost (click-through) mode ------------------------------------------------------------
/** Click-through: mouse events fall through to the app behind the HUD; `forward: true` keeps mousemove
 *  flowing to the renderer so the 👻 toggle can punch a hole for itself (see renderer `ghost_hole`). */
function applyGhost() {
  const win = state.win;
  if (!win || win.isDestroyed() || state.mode !== 'live') return;
  if (state.ghost) {
    win.setIgnoreMouseEvents(true, { forward: true });
    setFocusableSafe(win, false);           // can never steal focus from the meeting app while ghosted
    if (win.isFocused()) win.blur();
  } else {
    win.setIgnoreMouseEvents(false);
    setFocusableSafe(win, true);
  }
  // v17: whenever ghost mode is off the window must be focusable (typing in inputs, clicking buttons)
  if (!state.ghost) setFocusableSafe(win, true);
}
function setGhost(on) {
  state.ghost = Boolean(on);
  applyGhost();
  sendToRenderer({ type: 'ghost', enabled: state.ghost });
  console.log(`[main] ghost mode ${state.ghost ? 'ON (click-through)' : 'off'}`);
}
/** Build the diagnostic report, keep a copy in logs/reports/, and file it as a GitHub issue. */
async function reportProblem(note) {
  if (!reporter) return;
  const report = reporter.build(note);
  let file = '';
  try { file = reporter.save(report); } catch (e) { console.error('[report] save failed:', e.message); }
  const { repo, token } = reporter.cfg();
  try { clipboard.writeText(`# ${report.title}\n\n${report.body}`); } catch {}
  if (token) {
    try {
      const url = await reporter.postIssue(report);
      sendToRenderer({ type: 'report_status', state: 'sent', url, file });
      return;
    } catch (e) {
      console.error('[report] API failed:', e.message);
      sendToRenderer({ type: 'report_status', state: 'api_failed', error: e.message, file });
    }
  }
  if (repo) {
    shell.openExternal(reporter.issueUrl(report));
    sendToRenderer({ type: 'report_status', state: 'opened', file });
  } else sendToRenderer({ type: 'report_status', state: 'saved', file });
}

/** Open a terminal on the Claude Code login so an expired session can be renewed without knowing the CLI. */
function claudeLogin() {
  try {
    const env = { ...process.env }; delete env.CLAUDECODE; delete env.CLAUDE_CODE_ENTRYPOINT;
    if (process.platform === 'win32') {
      spawn('cmd.exe', ['/c', 'start', 'Claude login', 'cmd', '/k', 'claude /login'], { detached: true, stdio: 'ignore', env }).unref();
    } else if (process.platform === 'darwin') {
      spawn('osascript', ['-e', 'tell application "Terminal" to do script "claude /login"', '-e', 'tell application "Terminal" to activate'], { detached: true, stdio: 'ignore', env }).unref();
    } else {
      spawn('sh', ['-c', 'x-terminal-emulator -e claude /login || gnome-terminal -- claude /login || xterm -e claude /login'], { detached: true, stdio: 'ignore', env }).unref();
    }
    sendToRenderer({ type: 'claude_login', state: 'opened' });
  } catch (e) {
    sendToRenderer({ type: 'error', message: `Could not open a terminal for the Claude login: ${e.message}. Open one yourself and run: claude /login` });
  }
}

/** The End modal has buttons: leave ghost (click-through) mode first or it could never be answered. */
function askEndSession() {
  if (state.ghost) setGhost(false);
  sendToRenderer({ type: 'confirm_end_session' });
}
function toggleGhost() {
  if (state.mode !== 'live') { sendToRenderer({ type: 'toast', message: 'Ghost mode works in the Live HUD (Alt+T to return).' }); return; }
  setGhost(!state.ghost);
}

// ---- v15: keyboard positioning / scrolling / background opacity ---------------------------------
/** setFocusable() on Windows also flips skipTaskbar and blurs the window, so only call it on a real change
 *  and put the taskbar state back afterwards (the Live HUD must stay out of the taskbar and Alt+Tab). */
function setFocusableSafe(win, focusable) {
  if (state.focusable !== focusable) {
    state.focusable = focusable;
    win.setFocusable(focusable);
  }
  win.setSkipTaskbar(state.mode === 'live');
}
/** Atomic read-modify-write of ONE top-level section of config.json. Electron owns `hud` and `updates`;
 *  the backend owns everything else and preserves these two when it saves. */
function saveConfigSection(section, patch) {
  config[section] = { ...(config[section] || {}), ...patch };
  try {
    let cfg = {};
    try { cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch {}
    cfg[section] = { ...(cfg[section] || {}), ...patch };
    const tmp = `${CONFIG_PATH}.electron.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(cfg, null, 2) + '\n');
    fs.renameSync(tmp, CONFIG_PATH);
  } catch (e) { console.error('[main] could not save config.json:', e.message); }
}
function saveHudConfig(patch) { saveConfigSection('hud', patch); }
function nudge(dx, dy) {
  const win = state.win;
  if (!win || state.mode !== 'live') return;
  const step = Number(config.hud.nudge_px) || 40;
  const b = win.getBounds();
  const area = screen.getDisplayMatching(b).workArea;
  const x = Math.max(area.x - b.width + 60, Math.min(area.x + area.width - 60, b.x + dx * step));
  const y = Math.max(area.y, Math.min(area.y + area.height - 40, b.y + dy * step));
  win.setBounds({ x, y, width: b.width, height: b.height }, false);
  saveHudConfig({ x, top: y });
}
function hudAlpha() {
  const v = Number(config.hud.opacity);
  return Math.max(0.35, Math.min(0.95, Number.isFinite(v) && v > 0 ? v : 0.75));
}
function stepOpacity(delta) {
  const v = Math.round(Math.max(0.35, Math.min(0.95, hudAlpha() + delta)) * 100) / 100;
  saveHudConfig({ opacity: v });
  sendToRenderer({ type: 'hud_opacity', value: v });
}
function scrollFeed(direction) {
  // Works while ghosted / unfocused: the renderer scrolls #feed itself, no OS focus involved.
  sendToRenderer({ type: 'scroll_feed', direction });
}

function createWindow() {
  const display = screen.getPrimaryDisplay();
  const { width: screenW, height: screenH } = display.workAreaSize;
  const sw = Math.min(Number(config.hud.setup_width) || 1040, screenW - 40);
  const sh = Math.min(Number(config.hud.setup_height) || 720, screenH - 40);

  const win = new BrowserWindow({
    title: APP_DISPLAY_NAME,
    focusable: true,
    width: sw,
    height: sh,
    x: Math.round((screenW - sw) / 2),
    y: Math.round((screenH - sh) / 2),
    minWidth: 520,
    minHeight: 160,
    frame: false,
    transparent: true,
    alwaysOnTop: false,
    resizable: true,
    minimizable: true,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: false,
    hasShadow: true,
    show: false,
    icon: path.join(__dirname, 'assets', 'icon.png'),
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: DEBUG,
    },
  });
  state.win = win;
  // Invisible to screen capture from the very first frame.
  win.setContentProtection(true);
  win.setMenuBarVisibility(false);
  win.setOpacity(1);
  win.setTitle(APP_DISPLAY_NAME);
  win.on('page-title-updated', (e) => { e.preventDefault(); win.setTitle(APP_DISPLAY_NAME); });
  if (process.platform === 'darwin') app.dock && app.dock.hide();

  win.webContents.on('did-finish-load', () => {
    win.webContents.setZoomFactor(1);
    win.webContents.setVisualZoomLevelLimits(1, 1).catch(() => {});
    sendToRenderer({
      type: 'hud_config',
      hotkeys: config.hotkeys,
      platform: process.platform,
      font_size: Number(config.hud.font_size) || 17,
      mode: state.mode,
      activeProfile: currentProfile(),
      hud_alpha: hudAlpha(),
      ghost: state.ghost,
      auto_vision: Boolean(config.hud.auto_vision),
      auto_vision_interval_s: Number(config.hud.auto_vision_interval_s) || 5,
      version: updater ? updater.currentVersion() : require('../package.json').version,
      updates: config.updates,
    });
    sendToRenderer({ type: 'backend_link', connected: state.wsConnected });
    applyStealth();
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.once('ready-to-show', () => {
    win.show();
    applyStealth();
    if (DEBUG) win.webContents.openDevTools({ mode: 'detach' });
  });
  win.on('closed', () => {
    state.win = null;
  });
}

function enterLive() {
  const win = state.win;
  if (!win) return;
  if (state.mode === 'setup') state.setupBounds = win.getBounds();
  state.mode = 'live';
  const { width: screenW } = screen.getPrimaryDisplay().workAreaSize;
  const maxW = Number(config.hud.max_width) || 520;
  const w = Math.min(Number(config.hud.width) || 520, maxW, screenW - 20);
  const h = Number(config.hud.height) || 380;
  win.setMinimumSize(380, 140);
  win.setMaximumSize(maxW, 1200);
  const savedX = Number(config.hud.x);
  const x = Number.isFinite(savedX) && savedX > -w && savedX < screenW ? Math.round(savedX) : Math.round((screenW - w) / 2);
  win.setBounds({ width: w, height: h, x, y: Number(config.hud.top) || 6 }, false);
  win.setOpacity(1); // always fully visible to the user; background alpha is CSS (Alt+[ / Alt+]), text stays crisp
  applyStealth();
  state.visible = true;
  win.showInactive(); // never takes focus away from the meeting app
  sendToRenderer({ type: 'mode', mode: state.mode });
}

let updater = null;
function enterSetup() {
  setTimeout(() => updater && updater.flush(), 1500);   // apply an update that was downloaded during the live session
  const win = state.win;
  if (!win) return;
  state.mode = 'setup';
  const { width: screenW, height: screenH } = screen.getPrimaryDisplay().workAreaSize;
  const b = state.setupBounds || {
    width: Math.min(Number(config.hud.setup_width) || 1040, screenW - 40),
    height: Math.min(Number(config.hud.setup_height) || 720, screenH - 40),
  };
  if (b.x === undefined) {
    b.x = Math.round((screenW - b.width) / 2);
    b.y = Math.round((screenH - b.height) / 2);
  }
  win.setMaximumSize(10000, 10000);
  win.setMinimumSize(520, 160);
  win.setIgnoreMouseEvents(false);
  setFocusableSafe(win, true);
  win.setBounds(b, false);
  win.setOpacity(1);
  applyStealth();
  state.visible = true;
  win.show();
  win.focus();
  sendToRenderer({ type: 'mode', mode: state.mode });
}

let reporter = null;
let lastBackendStatus = null;
function sendToRenderer(msg) {
  // every error that reaches the UI is also kept for "Reportar problema"
  if (reporter && msg) {
    if (msg.type === 'error') reporter.note('app', msg.message);
    else if (msg.type === 'llm_end' && !msg.provider && !msg.cancelled && (msg.errors || []).length) reporter.note('providers', msg.errors.join(' | '));
    else if (msg.type === 'provider_test' && msg.state === 'done' && !msg.ok) reporter.note(`test:${msg.provider}`, msg.error);
    else if (msg.type === 'update_status' && msg.state === 'error') reporter.note('updater', msg.error);
    if (msg.type === 'status') lastBackendStatus = msg;
  }
  const win = state.win;
  if (win && !win.isDestroyed()) win.webContents.send('copilot:event', msg);
}

function toggleVisibility() {
  const win = state.win;
  if (!win) return;
  state.visible = !state.visible;
  if (state.visible) {
    state.mode === 'live' ? win.showInactive() : win.show();
    applyStealth();
    if (!state.ghost) setFocusableSafe(win, true);
  } else win.hide();
}

/** Run a native dialog without the overlay fighting it for focus / z-order. */
async function withDialog(fn) {
  const win = state.win;
  state.dialogDepth++;
  const wasOnTop = win && win.isAlwaysOnTop();
  try {
    if (win && wasOnTop) win.setAlwaysOnTop(false);
    return await fn();
  } finally {
    state.dialogDepth--;
    if (state.dialogDepth === 0 && state.win && !state.win.isDestroyed()) {
      applyStealth();
      if (state.mode === 'live') state.win.showInactive();
      else state.win.focus();
    }
  }
}

function createTray() {
  try {
    const img = nativeImage.createFromPath(path.join(__dirname, 'assets', 'tray.png'));
    const tray = new Tray(img.isEmpty() ? nativeImage.createEmpty() : img);
    state.tray = tray;
    tray.setToolTip(APP_DISPLAY_NAME);
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: 'Mostrar / Ocultar', click: toggleVisibility },
        { label: 'Modo fantasma (clic a través) Alt+G', click: toggleGhost },
        { label: 'Auto-visión (frame cada 5 s) Alt+V', click: () => sendToRenderer({ type: 'toggle_auto_vision' }) },
        { label: 'Modo de entrada: PC ⇄ Llamada externa (mic) Alt+P', click: () => sendToBackend({ type: 'toggle_input_mode' }) },
        { label: 'Configuración', click: enterSetup },
        { label: 'Banco de documentos', click: () => shell.openPath(BANK_DIR) },
        { label: 'Capturar pantalla (visión)', click: captureScreen },
        { label: 'Terminar y analizar sesión', click: () => askEndSession() },
        { label: 'Buscar actualizaciones', click: () => updater && updater.check({ manual: true }) },
        { label: 'Abrir carpeta del perfil', click: () => shell.openPath(getProfiles().dir(currentProfile())) },
        { label: 'Abrir log', click: () => shell.openPath(path.join(LOG_DIR, 'copilot.log')) },
        { type: 'separator' },
        { label: 'Salir', click: () => app.quit() },
      ]),
    );
    tray.on('click', toggleVisibility);
  } catch (e) {
    console.error('[main] tray failed:', e.message);
  }
}

// System-audio loopback for the HUD's own capture (Windows): answers getDisplayMedia({audio:true}).
function installLoopbackHandler() {
  try {
    session.defaultSession.setDisplayMediaRequestHandler(
      (request, callback) => {
        desktopCapturer
          .getSources({ types: ['screen'] })
          .then((sources) => {
            if (!sources.length) return callback({});
            callback({ video: sources[0], audio: process.platform === 'win32' ? 'loopback' : undefined });
          })
          .catch((e) => {
            console.error('[main] desktopCapturer failed:', e.message);
            callback({});
          });
      },
      { useSystemPicker: false },
    );
  } catch (e) {
    console.error('[main] setDisplayMediaRequestHandler unavailable:', e.message);
  }
}
function allowMediaPermissions() {
  const ok = ['media', 'display-capture', 'audioCapture', 'clipboard-sanitized-write', 'clipboard-read'];
  try {
    session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => callback(ok.includes(permission)));
    session.defaultSession.setPermissionCheckHandler((_wc, permission) => ok.includes(permission));
  } catch (e) {
    console.error('[main] permission handler:', e.message);
  }
}

// ------------------------------------------------------------------ backend process
function resolvePython() {
  if (config.backend.python && config.backend.python.trim()) return config.backend.python.trim();
  const candidates =
    process.platform === 'win32'
      ? [path.join(ROOT, 'backend', '.venv', 'Scripts', 'python.exe'), path.join(ROOT, '.venv', 'Scripts', 'python.exe')]
      : [path.join(ROOT, 'backend', '.venv', 'bin', 'python'), path.join(ROOT, '.venv', 'bin', 'python')];
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return process.platform === 'win32' ? 'python' : 'python3';
}
function startBackend() {
  const python = resolvePython();
  const args = [path.join(ROOT, 'backend', 'server.py'), '--config', CONFIG_PATH, '--parent-pid', String(process.pid)];
  if (process.argv.includes('--no-audio')) args.push('--no-audio');
  console.log(`[main] starting backend: ${python} ${args.join(' ')}`);
  const env = { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' };
  delete env.CLAUDECODE;
  delete env.CLAUDE_CODE_ENTRYPOINT;
  const proc = spawn(python, args, { cwd: path.join(ROOT, 'backend'), env, windowsHide: true });
  state.backendProc = proc;
  proc.on('error', (err) => {
    console.error('[backend] spawn error:', err.message);
    sendToRenderer({ type: 'error', message: `Backend failed to start: ${err.message}` });
  });
  const relay = (level) => (chunk) => {
    const text = chunk.toString();
    process.stdout.write(`[backend] ${text}`);
    if (logStream) logStream.write(`[backend] ${text}`);
    text.split(/\r?\n/).filter(Boolean).forEach((line) => sendToRenderer({ type: 'log', level, message: line }));
  };
  proc.stdout.on('data', relay('info'));
  proc.stderr.on('data', relay('stderr'));
  proc.on('exit', (code, signal) => {
    console.log(`[backend] exited code=${code} signal=${signal}`);
    if (state.backendProc === proc) state.backendProc = null;
    if (!state.quitting) {
      state.backendCrashes = (state.backendCrashes || 0) + 1;
      if (state.backendCrashes > 5) {
        sendToRenderer({ type: 'error', message: `Backend keeps exiting (code ${code}). See logs/copilot.log — another copy may be holding port ${config.backend.port}. Restart the app after closing it.` });
        return;
      }
      sendToRenderer({ type: 'error', message: `Backend exited (code ${code}). Restarting in 3s…` });
      setTimeout(() => !state.quitting && startBackend(), 3000);
      setTimeout(() => { state.backendCrashes = 0; }, 120000);
    }
  });
}
function stopBackend() {
  const proc = state.backendProc;
  if (!proc) return;
  try {
    if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { windowsHide: true });
    else proc.kill('SIGTERM');
  } catch (e) {
    console.error('[main] failed to stop backend:', e.message);
  }
  state.backendProc = null;
}

// ------------------------------------------------------------------ websocket link to the backend
function connectWs() {
  if (state.quitting) return;
  const cur = state.ws;
  if (cur && (cur.readyState === WebSocket.OPEN || cur.readyState === WebSocket.CONNECTING)) return;
  const ws = new WebSocket(`ws://${config.backend.host}:${config.backend.port}`);
  state.ws = ws;
  ws.on('open', () => {
    state.wsConnected = true;
    console.log('[main] backend link up');
    sendToRenderer({ type: 'backend_link', connected: true });
    flushPendingToBackend();
  });
  ws.on('message', (data) => {
    let msg;
    try {
      msg = JSON.parse(data.toString());
    } catch {
      return;
    }
    sendToRenderer(msg);
  });
  const onDown = () => {
    if (state.wsConnected) {
      state.wsConnected = false;
      sendToRenderer({ type: 'backend_link', connected: false });
    }
    if (state.ws === ws) state.ws = null;
    if (!state.quitting && !state.wsReconnectTimer) {
      state.wsReconnectTimer = setTimeout(() => {
        state.wsReconnectTimer = null;
        connectWs();
      }, 1000);
    }
  };
  ws.on('close', onDown);
  ws.on('error', onDown);
}
function sendToBackend(msg) {
  const ws = state.ws;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
    return true;
  }
  // Not connected (startup, backend restart): keep the command and deliver it when the link is up,
  // instead of dropping it with an error toast.
  pendingToBackend.push(msg);
  if (pendingToBackend.length > 100) pendingToBackend.shift();
  return false;
}
const pendingToBackend = [];
function flushPendingToBackend() {
  const ws = state.ws;
  while (pendingToBackend.length && ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(pendingToBackend.shift()));
}

// ------------------------------------------------------------------ screen capture (vision)
/** One compressed JPEG of the display under the cursor. The HUD is NOT hidden: setContentProtection(true)
 *  already keeps it out of desktopCapturer's frame. `maxWidth`/`quality` keep auto-vision frames cheap. */
async function grabFrame(maxWidth = 1600, quality = 72) {
  const cursor = screen.getCursorScreenPoint();
  const target = screen.getDisplayNearestPoint(cursor);
  const { width, height } = target.size;
  const scale = Math.min(1, maxWidth / width);
  const sources = await desktopCapturer.getSources({
    types: ['screen'],
    thumbnailSize: { width: Math.round(width * scale), height: Math.round(height * scale) },
  });
  if (!sources.length) throw new Error('no screen source');
  const src = sources.find((s) => String(s.display_id) === String(target.id)) || sources[0];
  return src.thumbnail.toJPEG(quality);
}

/** Auto-vision tick (renderer asks every N s): a low-overhead frame for the rolling 1-frame buffer. */
ipcMain.handle('vision:capture', async (_e, opts) => {
  const o = opts || {};
  const t0 = Date.now();
  const jpeg = await grabFrame(Number(o.maxWidth) || 1100, Number(o.quality) || 50);
  return { b64: jpeg.toString('base64'), mime: 'image/jpeg', bytes: jpeg.length, ms: Date.now() - t0, t: Date.now() };
});

async function captureScreen() {
  if (Date.now() - state.lastShot < 1500) return;
  state.lastShot = Date.now();
  try {
    const jpeg = await grabFrame(1600, 72);
    sendToRenderer({ type: 'screenshot', bytes: jpeg.length });
    sendToBackend({ type: 'vision', image_b64: jpeg.toString('base64'), mime: 'image/jpeg' });
    console.log(`[main] screenshot sent (${Math.round(jpeg.length / 1024)} KB)`);
  } catch (e) {
    console.error('[main] screenshot failed:', e.message);
    sendToRenderer({ type: 'error', message: `Screen capture failed: ${e.message}` });
  }
}

// ------------------------------------------------------------------ hotkeys (Alt + key)
function registerHotkeys() {
  const hk = config.hotkeys;
  const bind = (accel, fn, label) => {
    if (!accel) return false;
    let ok = false;
    try { ok = globalShortcut.register(accel, fn); } catch (e) { console.error(`[main] hotkey ${label}: ${accel} invalid: ${e.message}`); }
    console.log(`[main] hotkey ${label}: ${accel} ${ok ? 'OK' : 'FAILED (in use by another app or invalid)'}`);
    if (!ok && !/fallback/.test(label)) sendToRenderer({ type: 'error', message: `Hotkey ${accel} (${label}) could not be registered.` });
    return ok;
  };
  bind(hk.screenshot, captureScreen, 'screenshot');
  bind(hk.force_answer, () => sendToBackend({ type: 'generate' }), 'force_answer');
  bind(hk.toggle_visibility, toggleVisibility, 'toggle_visibility');
  bind(hk.toggle_listening, () => sendToBackend({ type: 'toggle_listening' }), 'toggle_listening');
  bind(hk.followup_example, () => sendToBackend({ type: 'followup', kind: 'example' }), 'followup_example');
  bind(hk.followup_deepen, () => sendToBackend({ type: 'followup', kind: 'deepen' }), 'followup_deepen');
  bind(hk.followup_tldr, () => sendToBackend({ type: 'followup', kind: 'tldr' }), 'followup_tldr');
  bind(hk.followup_pivot, () => sendToBackend({ type: 'followup', kind: 'pivot' }), 'followup_pivot');
  bind(hk.end_session, askEndSession, 'end_session');
  bind(hk.summarize, () => sendToBackend({ type: 'summarize' }), 'summarize');
  bind(hk.clear, () => { sendToBackend({ type: 'cancel' }); sendToRenderer({ type: 'clear' }); }, 'clear');
  bind(hk.toggle_language, () => sendToBackend({ type: 'toggle_language' }), 'toggle_language');
  bind(hk.settings, () => (state.mode === 'live' ? enterSetup() : sendToRenderer({ type: 'return_live' })), 'settings');
  bind(hk.quit, () => app.quit(), 'quit');
  // v15 — hands-free HUD ergonomics (all of these run without the HUD ever taking OS focus)
  bind(hk.ghost, toggleGhost, 'ghost');
  bind(hk.auto_vision, () => sendToRenderer({ type: 'toggle_auto_vision' }), 'auto_vision');
  bind(hk.new_turn, () => sendToBackend({ type: 'new_turn' }), 'new_turn');
  bind(hk.input_mode, () => sendToBackend({ type: 'toggle_input_mode' }), 'input_mode');
  bind(hk.nudge_up, () => nudge(0, -1), 'nudge_up');
  bind(hk.nudge_down, () => nudge(0, 1), 'nudge_down');
  bind(hk.nudge_left, () => nudge(-1, 0), 'nudge_left');
  bind(hk.nudge_right, () => nudge(1, 0), 'nudge_right');
  bind(hk.scroll_up, () => scrollFeed(-1), 'scroll_up');
  bind(hk.scroll_down, () => scrollFeed(1), 'scroll_down');
  // Bracket accelerators are not accepted on every keyboard layout: fall back to Alt+- / Alt+= silently.
  if (!bind(hk.opacity_down, () => stepOpacity(-0.1), 'opacity_down')) bind('Alt+-', () => stepOpacity(-0.1), 'opacity_down (fallback)');
  if (!bind(hk.opacity_up, () => stepOpacity(0.1), 'opacity_up')) bind('Alt+=', () => stepOpacity(0.1), 'opacity_up (fallback)');
}

// ------------------------------------------------------------------ IPC: renderer -> main (fire & forget)
ipcMain.on('copilot:send', (_event, msg) => {
  if (!msg || typeof msg !== 'object') return;
  switch (msg.type) {
    case 'toggle_visibility': toggleVisibility(); break;
    case 'enter_live': enterLive(); break;
    case 'enter_setup': enterSetup(); break;
    case 'clear': sendToBackend({ type: 'cancel' }); sendToRenderer({ type: 'clear' }); break;
    case 'quit': app.quit(); break;
    case 'minimize': state.win && state.win.minimize(); break;
    case 'screenshot': captureScreen(); break;
    case 'toggle_ghost': toggleGhost(); break;
    case 'set_ghost': setGhost(Boolean(msg.value)); break;
    case 'ghost_hole':
      // Renderer hovers the 👻 toggle while ghosted: let that one control receive the click, then re-arm.
      if (state.win && state.mode === 'live' && state.ghost) state.win.setIgnoreMouseEvents(!msg.value, { forward: true });
      break;
    case 'set_auto_vision': saveHudConfig({ auto_vision: Boolean(msg.value) }); sendToBackend(msg); break;
    case 'renderer_error': reporter && reporter.note('renderer', msg.message); break;
    case 'report_problem': reportProblem(String(msg.note || '')); break;
    case 'claude_login': claudeLogin(); break;
    case 'check_updates': updater && updater.check({ manual: true }); break;
    case 'install_update': updater && (updater.staged ? updater.install() : updater.check({ manual: true })); break;
    case 'set_updates': saveConfigSection('updates', { enabled: msg.enabled !== false, auto_install: msg.auto_install !== false }); updater && updater.set({}); break;
    case 'open_external': if (/^https:\/\//.test(String(msg.url || ''))) shell.openExternal(msg.url); break;
    case 'set_hud_opacity': {
      const v = Number(msg.value);
      if (Number.isFinite(v)) { saveHudConfig({ opacity: Math.max(0.35, Math.min(0.95, v)) }); sendToRenderer({ type: 'hud_opacity', value: hudAlpha() }); }
      break;
    }
    case 'nudge': nudge(Number(msg.dx) || 0, Number(msg.dy) || 0); break;
    case 'open_context_folder': shell.openPath(getProfiles().dir(currentProfile())); break;
    case 'set_font_size':
      if (Number.isFinite(msg.value)) {
        config.hud.font_size = Math.max(12, Math.min(32, Math.round(Number(msg.value))));
        saveHudConfig({ font_size: config.hud.font_size });
      }
      break;
    case 'resize_hud': {
      const win = state.win;
      if (!win || state.mode !== 'live') break;
      const [w] = win.getSize();
      const h = Math.max(200, Math.min(1000, Math.round(Number(msg.height) || config.hud.height)));
      win.setMinimumSize(w, 160); win.setMaximumSize(w, 1200);
      win.setSize(w, h);
      saveHudConfig({ height: h });
      break;
    }
    default: sendToBackend(msg);
  }
});

// Raw PCM from the HUD's Electron capture -> backend (binary frame).
ipcMain.on('audio:chunk', (_event, channel, sampleRate, pcm) => {
  const ws = state.ws;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const body = Buffer.from(pcm.buffer ? pcm.buffer : pcm, pcm.byteOffset || 0, pcm.byteLength);
  const frame = Buffer.alloc(5 + body.length);
  frame[0] = channel === 'me' ? 1 : 0;
  frame.writeUInt32LE(sampleRate >>> 0, 1);
  body.copy(frame, 5);
  ws.send(frame, { binary: true });
});

// ------------------------------------------------------------------ IPC: profiles
ipcMain.handle('profiles:list', () => ({ active: currentProfile(), profiles: getProfiles().list(), archived: getProfiles().listArchived() }));
ipcMain.handle('profiles:create', (_e, name) => ({ active: getProfiles().create(name), profiles: getProfiles().list() }));
ipcMain.handle('profiles:duplicate', (_e, source, target) => ({ active: getProfiles().duplicate(source, target), profiles: getProfiles().list() }));
ipcMain.handle('profiles:delete', (_e, name) => {
  const list = getProfiles().remove(name);
  const active = list.includes(currentProfile()) && currentProfile() !== name ? currentProfile() : list[0];
  return { active, profiles: list };
});
ipcMain.handle('profiles:rename', (_e, name, newName) => ({ active: getProfiles().rename(name, newName), profiles: getProfiles().list() }));
ipcMain.on('profiles:active', (_e, name) => {
  if (typeof name === 'string' && name) state.activeProfile = name;
});
ipcMain.handle('profiles:open_folder', (_e, name) => shell.openPath(getProfiles().dir(name || currentProfile())));
ipcMain.handle('profiles:open_logs', (_e, name) => shell.openPath(path.join(getProfiles().dir(name || currentProfile()), 'logs')));
ipcMain.handle('profiles:open_file', (_e, filePath) => shell.openPath(String(filePath || '')));
ipcMain.handle('profiles:open_bank', () => shell.openPath(BANK_DIR));
ipcMain.handle('claude_projects:list', () => ProfileManager.discoverClaudeProjects(os.homedir()));
ipcMain.handle('claude_projects:pick', () =>
  withDialog(async () => {
    const res = await dialog.showOpenDialog(state.win, { title: 'Selecciona la carpeta que contiene CLAUDE.md', properties: ['openDirectory'] });
    if (res.canceled || !res.filePaths.length) return null;
    const p = res.filePaths[0];
    return { path: p, name: path.basename(p), hasClaudeMd: fs.existsSync(path.join(p, 'CLAUDE.md')) };
  }),
);

// ------------------------------------------------------------------ IPC: global document & playbook bank
function bankChanged() {
  try {
    sendToRenderer({ type: 'bank_changed', bank: getBank().list() });
  } catch (e) {
    console.error('[bank] list failed:', e.message);
  }
}
ipcMain.handle('bank:list', () => getBank().list());
ipcMain.handle('bank:save_text', (_e, slot, name, text, profile) => {
  const category = SLOT_TO_CATEGORY[slot] || slot;
  const meta = getBank().save(category, name, text, { source: 'pasted', profile: profile || currentProfile() });
  bankChanged();
  return meta;
});
ipcMain.handle('bank:read', (_e, category, id) => getBank().read(category, id));
ipcMain.handle('bank:delete', (_e, category, id) => {
  const list = getBank().remove(category, id);
  bankChanged();
  return list;
});
ipcMain.handle('bank:migrate', () => {
  const added = getBank().migrateFrom(PROFILES_DIR, ARCHIVED_DIR, CONTEXT_DIR);
  getBank().dedupe();
  bankChanged();
  return { added, bank: getBank().list() };
});

// ------------------------------------------------------------------ IPC: context slots
// Parsing runs in a worker thread; only small manifests cross IPC (never the extracted text).
// Every upload is also saved to the bank by ProfileManager.addFile().
async function addPaths(profile, slot, filePaths) {
  const results = [];
  for (const fp of filePaths) {
    sendToRenderer({ type: 'context_progress', slot, file: path.basename(fp), state: 'parsing' });
    try {
      const entry = await getProfiles().addFile(profile, slot, fp);
      results.push({ ok: true, file: path.basename(fp), entry });
    } catch (e) {
      results.push({ ok: false, file: path.basename(fp), code: e.code || 'read_error', error: e.message });
      console.error(`[context] ${path.basename(fp)}: ${e.message}`);
    }
    sendToRenderer({ type: 'context_progress', slot, file: path.basename(fp), state: 'done' });
  }
  sendToBackend({ type: 'reload_context' });
  bankChanged();
  return { cancelled: false, results, manifest: getProfiles().load(profile) };
}
ipcMain.handle('context:get', (_e, name) => getProfiles().load(name || currentProfile()));
ipcMain.handle('context:pick', (_event, slot, name) =>
  withDialog(async () => {
    const profile = name || currentProfile();
    const res = await dialog.showOpenDialog(state.win, {
      title: `Selecciona archivo para ${slot} (perfil ${profile})`,
      properties: slot === 'experience' ? ['openFile', 'multiSelections'] : ['openFile'],
      filters: [
        { name: 'Documentos', extensions: ['pdf', 'docx', 'txt', 'md', 'markdown'] },
        { name: 'Todos los archivos', extensions: ['*'] },
      ],
    });
    if (res.canceled || !res.filePaths.length) return { cancelled: true, results: [] };
    return addPaths(profile, slot, res.filePaths);
  }),
);
ipcMain.handle('context:add_paths', (_event, slot, filePaths, name) => {
  const list = (filePaths || []).filter((p) => typeof p === 'string' && p);
  if (!list.length) return { cancelled: true, results: [] };
  return addPaths(name || currentProfile(), slot, slot === 'experience' ? list : list.slice(0, 1));
});
ipcMain.handle('context:remove', (_event, slot, index, name) => {
  const manifest = getProfiles().removeFile(name || currentProfile(), slot, index);
  sendToBackend({ type: 'reload_context' });
  return manifest;
});

// ------------------------------------------------------------------ IPC: past sessions
function assertUnderProfiles(filePath) {
  const roots = [path.resolve(PROFILES_DIR), path.resolve(ARCHIVED_DIR)];
  const target = path.resolve(String(filePath || ''));
  if (!roots.some((r) => target.startsWith(r))) throw new Error('path outside profiles folders');
  return target;
}
ipcMain.handle('sessions:list', (_e, name, archived) => listSessions(getProfiles().dir(name || currentProfile(), Boolean(archived))));
ipcMain.handle('sessions:read', (_e, filePath) => readTextFile(assertUnderProfiles(filePath)));
ipcMain.handle('sessions:read_json', (_e, filePath) => JSON.parse(fs.readFileSync(assertUnderProfiles(filePath), 'utf8')));

// ------------------------------------------------------------------ app lifecycle
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (state.win) {
      state.visible = true;
      state.win.show();
    }
  });

  app.whenReady().then(() => {
    if (process.platform === 'win32') app.setAppUserModelId(APP_USER_MODEL_ID);
    Menu.setApplicationMenu(null); // removes the default Ctrl+Plus/Minus zoom accelerators
    try {
      getProfiles();
      const added = getBank().migrateFrom(PROFILES_DIR, ARCHIVED_DIR, CONTEXT_DIR);
      if (added) console.log(`[bank] ${added} existing file(s) imported into data/bank`);
      getBank().dedupe();   // the same CV saved once per profile becomes one entry
    } catch (e) {
      console.error('[main] profile/bank initialisation failed:', e.message);
    }
    installLoopbackHandler();
    allowMediaPermissions();
    createWindow();
    createTray();
    registerHotkeys();
    startBackend();
    connectWs();
    updater = new Updater({
      root: ROOT,
      getConfig: () => config.updates,
      notify: sendToRenderer,
      isBusy: () => state.mode === 'live',
      quit: () => { state.quitting = true; app.quit(); },
    });
    updater.start();
    reporter = new Reporter({
      root: ROOT, logFile: path.join(LOG_DIR, 'copilot.log'), version: updater.currentVersion(),
      getConfig: () => { try { return { ...config, ...JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')), reports: config.reports, updates: config.updates }; } catch { return config; } },
      getStatus: () => lastBackendStatus,
      getProfileNames: () => { try { return getProfiles().list().map((x) => (typeof x === 'string' ? x : x.name)); } catch { return []; } },
    });
  });

  app.on('window-all-closed', () => app.quit());

  app.on('will-quit', () => {
    state.quitting = true;
    globalShortcut.unregisterAll();
    if (state.wsReconnectTimer) clearTimeout(state.wsReconnectTimer);
    try {
      state.ws && state.ws.close();
    } catch {}
    terminateParser();
    stopBackend();
  });

  process.on('uncaughtException', (err) => {
    console.error('[main] uncaught:', err);
    if (!state.quitting) dialog.showErrorBox(APP_DISPLAY_NAME, String(err && err.stack ? err.stack : err));
  });
}
