'use strict';
/**
 * Profile & context manager (Electron main process; plain Node, unit-testable).
 *
 * profiles/<name>/
 *   profile_config.json      written by the Python backend (claude_project, use_learned_memory, ...)
 *   playbook.json            written by the Python backend (text, tone, length)
 *   manifest.json            written HERE after parsing uploads: {role, profile, experience[], playbook}
 *   position_description/    single file  (slot "role")
 *   professional_profile/    single file  (slot "profile")
 *   extra_experience/        many files   (slot "experience")
 *   playbook_files/          single file  (slot "playbook")
 *   learned_memory.md, logs/ (backend)
 *
 * Uploads are parsed immediately (pdf-parse v2 / mammoth / utf-8) and stored as extracted .md text, so the
 * Python side never needs PDF/DOCX libraries. Legacy flat `context/` setups are migrated into
 * profiles/default/ on first run.
 */
const fs = require('fs');
const path = require('path');
const { Worker } = require('worker_threads');
const crypto = require('crypto');

const SLOT_DIRS = { role: 'position_description', profile: 'professional_profile', experience: 'extra_experience', playbook: 'playbook_files' };
const LEGACY_SLOT_DIRS = { role: '01_role', profile: '02_profile', experience: '03_experience', playbook: '04_playbook' };
const SINGLE = new Set(['role', 'profile', 'playbook']);
const MAX_BYTES = 25 * 1024 * 1024;

class ContextError extends Error {
  constructor(message, code) {
    super(message);
    this.code = code || 'read_error';
  }
}

function emptyManifest() {
  return { role: null, profile: null, experience: [], playbook: null };
}

function sanitizeName(name) {
  return String(name || '').replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '_').slice(0, 60) || 'default';
}

// ---------------------------------------------------------------- global Document & Playbook Bank
const BANK_CATEGORIES = ['roles', 'cvs', 'experience', 'playbooks'];
const SLOT_TO_CATEGORY = { role: 'roles', profile: 'cvs', experience: 'experience', playbook: 'playbooks' };

class BankStore {
  constructor(bankDir) {
    this.dir = bankDir;
    this.ensureDirs();
  }

  ensureDirs() {
    for (const c of BANK_CATEGORIES) fs.mkdirSync(path.join(this.dir, c, 'originals'), { recursive: true });
  }

  static safeStem(name) {
    const stem = String(name || 'entry').replace(/\.(md|txt|markdown|pdf|docx)$/i, '');
    return stem.replace(/[^\w.\- ]+/g, '').trim().replace(/\s+/g, '_').slice(0, 80) || 'entry';
  }

  /** Identity of a document = its words. Case, punctuation, spacing and a leading "## title" line do not count. */
  static fingerprint(text) {
    const t = String(text || '').replace(/^\s*#{1,6}[^\n]*\n/, '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
    return crypto.createHash('sha1').update(t).digest('hex');
  }

  /** The entry of `category` that already holds this exact text under another name, or null. */
  findSame(category, text, exceptFile = '') {
    const want = BankStore.fingerprint(text);
    const dir = path.join(this.dir, category);
    let names = [];
    try { names = fs.readdirSync(dir); } catch { return null; }
    for (const f of names) {
      if (!/\.(md|txt)$/i.test(f) || f.toLowerCase() === 'readme.md' || f.toLowerCase() === exceptFile.toLowerCase()) continue;
      try {
        if (BankStore.fingerprint(fs.readFileSync(path.join(dir, f), 'utf8')) === want) return f;
      } catch {}
    }
    return null;
  }

  /** Save parsed text (+ optional original file) into data/bank/<category>/. Same filename => update in place.
   *  Same TEXT under another name => nothing new is created; the existing entry is returned (duplicate: true). */
  save(category, originalName, text, { originalPath = null, source = 'upload', profile = null, pages = null } = {}) {
    if (!BANK_CATEGORIES.includes(category)) throw new ContextError(`Unknown bank category ${category}`, 'bad_category');
    this.ensureDirs();
    const stem = BankStore.safeStem(originalName);
    if (countWords(String(text || '')) >= 2 && !fs.existsSync(path.join(this.dir, category, `${stem}.md`))) {
      const same = this.findSame(category, text, `${stem}.md`);
      if (same) {
        const meta = readJson(path.join(this.dir, category, same.replace(/\.(md|txt)$/i, '.json')), null) || {};
        return { ...meta, id: same, filename: same, category, duplicate: true };
      }
    }
    const mdPath = path.join(this.dir, category, `${stem}.md`);
    const metaPath = path.join(this.dir, category, `${stem}.json`);
    const existing = readJson(metaPath, null);
    const body = normalize(String(text || ''));
    fs.writeFileSync(mdPath, body + '\n');
    let originalStored = existing ? existing.original : null;
    if (originalPath && fs.existsSync(originalPath)) {
      const ext = path.extname(originalPath).toLowerCase();
      if (ext && ext !== '.md' && ext !== '.txt') {
        const dst = path.join(this.dir, category, 'originals', `${stem}${ext}`);
        try {
          fs.copyFileSync(originalPath, dst);
          originalStored = path.relative(this.dir, dst);
        } catch (e) {
          console.error('[bank] could not copy original:', e.message);
        }
      }
    }
    const meta = {
      id: `${stem}.md`,
      filename: `${stem}.md`,
      originalName: originalName || `${stem}.md`,
      original: originalStored,
      category,
      wordCount: countWords(body),
      pages,
      source,
      profile,
      createdAt: existing && existing.createdAt ? existing.createdAt : new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    writeJson(metaPath, meta);
    return meta;
  }

  list() {
    this.ensureDirs();
    const out = {};
    for (const c of BANK_CATEGORIES) {
      const dir = path.join(this.dir, c);
      const items = [];
      for (const f of fs.readdirSync(dir)) {
        if (!/\.(md|txt)$/i.test(f) || f.toLowerCase() === 'readme.md') continue;
        const full = path.join(dir, f);
        let st;
        try {
          st = fs.statSync(full);
        } catch {
          continue;
        }
        if (!st.isFile()) continue;
        const meta = readJson(path.join(dir, f.replace(/\.(md|txt)$/i, '.json')), null);
        let wordCount = meta && meta.wordCount;
        if (wordCount == null) {
          try {
            wordCount = countWords(fs.readFileSync(full, 'utf8'));
          } catch {
            wordCount = 0;
          }
        }
        items.push({
          id: f,
          filename: f,
          originalName: (meta && meta.originalName) || f,
          category: c,
          wordCount,
          pages: meta ? meta.pages : null,
          source: (meta && meta.source) || 'file',
          profile: meta ? meta.profile : null,
          hasOriginal: Boolean(meta && meta.original),
          updatedAt: (meta && meta.updatedAt) || st.mtime.toISOString(),
          path: full,
        });
      }
      out[c] = items.sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1));
    }
    return out;
  }

  read(category, id) {
    const p = path.join(this.dir, category, path.basename(id));
    if (!fs.existsSync(p) || !/\.(md|txt)$/i.test(p)) throw new ContextError(`Bank entry not found: ${id}`, 'not_found');
    return fs.readFileSync(p, 'utf8');
  }

  remove(category, id) {
    const base = path.basename(id);
    if (category === 'playbooks' && base === 'default_playbook.md') throw new ContextError('The default playbook cannot be deleted', 'protected');
    const p = path.join(this.dir, category, base);
    const meta = readJson(p.replace(/\.(md|txt)$/i, '.json'), null);
    for (const f of [p, p.replace(/\.(md|txt)$/i, '.json')]) {
      try {
        fs.unlinkSync(f);
      } catch {}
    }
    if (meta && meta.original) {
      try {
        fs.unlinkSync(path.join(this.dir, meta.original));
      } catch {}
    }
    return this.list();
  }

  /** Collapse entries of one category that hold the same text into one. The copy that is kept is, in order: one
   *  with its original file, an uploaded one, one not named after a profile (<perfil>_profile …), the oldest.
   *  Nothing is deleted: the extra copies are moved to data/bank/_duplicates/<category>/. Playbooks are left
   *  alone because profiles refer to them by file name. Returns how many copies were moved. */
  dedupe() {
    let moved = 0;
    const all = this.list();
    for (const category of ['roles', 'cvs', 'experience']) {
      const groups = new Map();
      for (const it of all[category] || []) {
        let fp;
        try { fp = BankStore.fingerprint(fs.readFileSync(it.path, 'utf8')); } catch { continue; }
        if (!groups.has(fp)) groups.set(fp, []);
        groups.get(fp).push(it);
      }
      for (const items of groups.values()) {
        if (items.length < 2) continue;
        const rank = (it) => [it.hasOriginal ? 0 : 1, it.source === 'upload' || it.source === 'file' ? 0 : 1,
          /_(role|profile|experience)\.(md|txt)$/i.test(it.filename) ? 1 : 0, it.updatedAt || ''];
        items.sort((a, b) => { const x = rank(a), y = rank(b); for (let i = 0; i < x.length; i++) { if (x[i] < y[i]) return -1; if (x[i] > y[i]) return 1; } return 0; });
        const attic = path.join(this.dir, '_duplicates', category);
        fs.mkdirSync(attic, { recursive: true });
        for (const it of items.slice(1)) {
          const meta = readJson(it.path.replace(/\.(md|txt)$/i, '.json'), null);
          const files = [it.path, it.path.replace(/\.(md|txt)$/i, '.json')];
          if (meta && meta.original) files.push(path.join(this.dir, meta.original));
          for (const f of files) {
            try { if (fs.existsSync(f)) fs.renameSync(f, path.join(attic, path.basename(f))); } catch (e) { console.error('[bank] could not move duplicate', f, e.message); }
          }
          moved++;
        }
      }
    }
    if (moved) console.log(`[bank] ${moved} duplicate entr${moved === 1 ? 'y' : 'ies'} moved to data/bank/_duplicates`);
    return moved;
  }

  /** One-time import of everything already uploaded into profiles (active + archived) and the legacy context/. */
  migrateFrom(profilesDir, archivedDir, legacyContextDir) {
    let added = 0;
    const seen = new Set(Object.values(this.list()).flat().map((i) => i.filename.toLowerCase()));
    const importSlots = (root, profile, slotDirs) => {
      const manifest = readJson(path.join(root, 'manifest.json'), null);
      if (!manifest) return;
      const entries = [];
      for (const slot of ['role', 'profile', 'playbook']) if (manifest[slot] && manifest[slot].file) entries.push([slot, manifest[slot]]);
      for (const e of manifest.experience || []) if (e && e.file) entries.push(['experience', e]);
      for (const [slot, e] of entries) {
        const src = path.join(root, e.file);
        if (!fs.existsSync(src)) continue;
        const stem = BankStore.safeStem(e.source || path.basename(e.file));
        if (seen.has(`${stem}.md`.toLowerCase())) continue;
        try {
          const text = fs.readFileSync(src, 'utf8').replace(/^<!--[\s\S]*?-->\s*/, '');
          if (countWords(text) < 2) continue;
          const r = this.save(SLOT_TO_CATEGORY[slot], e.source || path.basename(e.file), text, { source: 'migrated', profile, pages: e.pages || null });
          seen.add(`${stem}.md`.toLowerCase());
          if (!r.duplicate) added++;
        } catch (err) {
          console.error('[bank] migrate failed for', src, err.message);
        }
      }
      // pasted text
      const manual = path.join(root, 'manual_context');
      if (fs.existsSync(manual)) {
        for (const slot of ['role', 'profile', 'experience']) {
          const f = path.join(manual, `${slot}.md`);
          if (!fs.existsSync(f)) continue;
          const name = `${profile}_${slot}`;
          if (seen.has(`${BankStore.safeStem(name)}.md`.toLowerCase())) continue;
          try {
            const text = fs.readFileSync(f, 'utf8');
            if (countWords(text) < 2) continue;
            const r = this.save(SLOT_TO_CATEGORY[slot], name, text, { source: 'pasted', profile });
            seen.add(`${BankStore.safeStem(name)}.md`.toLowerCase());
            if (!r.duplicate) added++;
          } catch {}
        }
      }
      // playbook text
      const pb = readJson(path.join(root, 'playbook.json'), null);
      if (pb && pb.text && countWords(pb.text) >= 3) {
        const name = `${profile}_playbook`;
        if (!seen.has(`${BankStore.safeStem(name)}.md`.toLowerCase())) {
          this.save('playbooks', name, pb.text, { source: 'migrated', profile });
          seen.add(`${BankStore.safeStem(name)}.md`.toLowerCase());
          added++;
        }
      }
    };
    for (const [dir, label] of [[profilesDir, ''], [archivedDir, ' (archived)']]) {
      if (!dir || !fs.existsSync(dir)) continue;
      for (const d of fs.readdirSync(dir, { withFileTypes: true })) {
        if (d.isDirectory() && !d.name.startsWith('.')) importSlots(path.join(dir, d.name), d.name + label, SLOT_DIRS);
      }
    }
    if (legacyContextDir && fs.existsSync(legacyContextDir)) {
      // legacy manifest (already renamed to .migrated by the profile migration) or a live one
      for (const mf of ['manifest.json', 'manifest.json.migrated']) {
        const p = path.join(legacyContextDir, mf);
        if (!fs.existsSync(p)) continue;
        const tmp = path.join(legacyContextDir, 'manifest.json');
        const had = fs.existsSync(tmp);
        if (!had) fs.copyFileSync(p, tmp);
        importSlots(legacyContextDir, 'legacy_context', LEGACY_SLOT_DIRS);
        if (!had) fs.unlinkSync(tmp);
        break;
      }
    }
    if (added) console.log(`[bank] migrated ${added} existing file(s) into the bank`);
    return added;
  }
}

class ProfileManager {
  constructor(profilesDir, legacyContextDir, bankDir) {
    this.root = profilesDir;
    this.bankDir = bankDir || null;
    this.bank = bankDir ? new BankStore(bankDir) : null;
    this.archiveRoot = path.join(path.dirname(profilesDir), 'profiles_archived');
    fs.mkdirSync(this.root, { recursive: true });
    fs.mkdirSync(this.archiveRoot, { recursive: true });
    if (legacyContextDir) this.migrateLegacy(legacyContextDir);
    if (!this.list().length) this.create('default');
  }

  // ---------------------------------------------------------------- profiles
  list() {
    return fs
      .readdirSync(this.root, { withFileTypes: true })
      .filter((d) => d.isDirectory() && !d.name.startsWith('.'))
      .map((d) => d.name)
      .sort();
  }

  dir(name, archived = false) {
    return path.join(archived ? this.archiveRoot : this.root, sanitizeName(name));
  }

  listArchived() {
    return fs
      .readdirSync(this.archiveRoot, { withFileTypes: true })
      .filter((d) => d.isDirectory() && !d.name.startsWith('.'))
      .map((d) => d.name)
      .sort();
  }

  exists(name) {
    return fs.existsSync(this.dir(name));
  }

  create(name) {
    const safe = sanitizeName(name);
    const d = this.dir(safe);
    fs.mkdirSync(d, { recursive: true });
    for (const sub of [...Object.values(SLOT_DIRS), 'logs']) fs.mkdirSync(path.join(d, sub), { recursive: true });
    const cfgPath = path.join(d, 'profile_config.json');
    if (!fs.existsSync(cfgPath)) {
      writeJson(cfgPath, { name: safe, created: new Date().toISOString(), claude_project: null, use_learned_memory: true, language: null });
    }
    if (!fs.existsSync(path.join(d, 'playbook.json'))) writeJson(path.join(d, 'playbook.json'), { text: '', tone: 'natural', length: 'medium' });
    if (!fs.existsSync(path.join(d, 'manifest.json'))) writeJson(path.join(d, 'manifest.json'), emptyManifest());
    return safe;
  }

  duplicate(source, target) {
    const src = this.dir(source);
    const safe = sanitizeName(target);
    const dst = this.dir(safe);
    if (!fs.existsSync(src)) throw new ContextError(`Profile "${source}" does not exist`, 'not_found');
    if (fs.existsSync(dst)) throw new ContextError(`Profile "${safe}" already exists`, 'exists');
    fs.cpSync(src, dst, { recursive: true, filter: (p) => !p.includes(`${path.sep}logs${path.sep}`) && path.basename(p) !== 'learned_memory.md' });
    fs.mkdirSync(path.join(dst, 'logs'), { recursive: true });
    const cfg = readJson(path.join(dst, 'profile_config.json'), {});
    writeJson(path.join(dst, 'profile_config.json'), { ...cfg, name: safe, created: new Date().toISOString() });
    return safe;
  }

  remove(name) {
    const safe = sanitizeName(name);
    if (this.list().length <= 1) throw new ContextError('Cannot delete the last profile', 'last_profile');
    fs.rmSync(this.dir(safe), { recursive: true, force: true });
    return this.list();
  }

  rename(name, newName) {
    const safe = sanitizeName(newName);
    if (this.exists(safe)) throw new ContextError(`Profile "${safe}" already exists`, 'exists');
    fs.renameSync(this.dir(name), this.dir(safe));
    const cfgPath = path.join(this.dir(safe), 'profile_config.json');
    writeJson(cfgPath, { ...readJson(cfgPath, {}), name: safe });
    return safe;
  }

  migrateLegacy(legacyDir) {
    const legacyManifest = path.join(legacyDir, 'manifest.json');
    if (!fs.existsSync(legacyManifest) || this.list().length) return;
    try {
      const safe = this.create('default');
      const dst = this.dir(safe);
      const m = readJson(legacyManifest, emptyManifest());
      const out = emptyManifest();
      const moveSlot = (slot, entry) => {
        if (!entry || !entry.file) return null;
        const srcFile = path.join(legacyDir, entry.file);
        if (!fs.existsSync(srcFile)) return null;
        const rel = path.posix.join(SLOT_DIRS[slot], path.basename(entry.file));
        fs.copyFileSync(srcFile, path.join(dst, rel));
        return { ...entry, file: rel };
      };
      for (const slot of ['role', 'profile', 'playbook']) out[slot] = moveSlot(slot, m[slot]);
      out.experience = (m.experience || []).map((e) => moveSlot('experience', e)).filter(Boolean);
      writeJson(path.join(dst, 'manifest.json'), out);
      if (m.playbook_text) writeJson(path.join(dst, 'playbook.json'), { text: m.playbook_text, tone: 'natural', length: 'medium' });
      fs.renameSync(legacyManifest, legacyManifest + '.migrated');
      console.log(`[context] migrated legacy context/ into profiles/${safe}`);
    } catch (e) {
      console.error('[context] legacy migration failed:', e.message);
    }
  }

  // ---------------------------------------------------------------- manifest
  load(name) {
    const m = readJson(path.join(this.dir(name), 'manifest.json'), emptyManifest());
    return { ...emptyManifest(), ...m, experience: Array.isArray(m.experience) ? m.experience : [] };
  }

  save(name, manifest) {
    writeJson(path.join(this.dir(name), 'manifest.json'), manifest);
    return manifest;
  }

  // ---------------------------------------------------------------- parsing (worker thread)
  /** Parse a file in a worker thread so the main process event loop (and the UI) never blocks. */
  extractText(filePath) {
    return parseInWorker(filePath);
  }

  // ---------------------------------------------------------------- slots
  async addFile(profile, slot, filePath) {
    if (!SLOT_DIRS[slot]) throw new ContextError(`Unknown slot ${slot}`, 'bad_slot');
    if (!this.exists(profile)) this.create(profile);
    const { text, pages } = await this.extractText(filePath);
    const source = path.basename(filePath);
    const safe = source.replace(/[^\w.\-]+/g, '_').replace(/\.[^.]+$/, '');
    const rel = path.posix.join(SLOT_DIRS[slot], `${Date.now().toString(36)}_${safe}.md`);
    const header = `<!-- source: ${source}; slot: ${slot}; imported: ${new Date().toISOString()} -->\n`;
    fs.writeFileSync(path.join(this.dir(profile), rel), header + text + '\n');
    // Every upload is also saved into the global bank (parsed .md + .json metadata + the original file),
    // so any profile can attach it later with one click.
    let bankEntry = null;
    try {
      if (this.bank) bankEntry = this.bank.save(SLOT_TO_CATEGORY[slot], source, text, { originalPath: filePath, source: 'upload', profile, pages });
    } catch (e) {
      console.error('[bank] could not save upload to bank:', e.message);
    }
    const manifest = this.load(profile);
    const entry = { file: rel, source, words: countWords(text), chars: text.length, pages, status: 'ok', imported: new Date().toISOString(), bank: bankEntry ? bankEntry.id : null };
    if (SINGLE.has(slot)) {
      if (manifest[slot] && manifest[slot].file) this._unlink(profile, manifest[slot].file);
      manifest[slot] = entry;
    } else manifest.experience.push(entry);
    this.save(profile, manifest);
    return entry;
  }

  removeFile(profile, slot, index) {
    const manifest = this.load(profile);
    if (SINGLE.has(slot)) {
      if (manifest[slot] && manifest[slot].file) this._unlink(profile, manifest[slot].file);
      manifest[slot] = null;
    } else {
      const [removed] = manifest.experience.splice(Number(index), 1);
      if (removed && removed.file) this._unlink(profile, removed.file);
    }
    return this.save(profile, manifest);
  }

  _unlink(profile, rel) {
    try {
      fs.unlinkSync(path.join(this.dir(profile), rel));
    } catch {}
  }

  // ---------------------------------------------------------------- Claude projects
  /** Local Claude projects: folders with a CLAUDE.md, discovered from ~/.claude/projects/* encoded paths. */
  static discoverClaudeProjects(homeDir) {
    const out = [];
    const root = path.join(homeDir, '.claude', 'projects');
    if (!fs.existsSync(root)) return out;
    for (const d of fs.readdirSync(root, { withFileTypes: true })) {
      if (!d.isDirectory()) continue;
      // Encoded like "-Users-isra-code-myproj" -> try to resolve back to a real path.
      const candidates = decodeProjectDir(d.name);
      const found = candidates.find((p) => fs.existsSync(p));
      if (found) {
        out.push({ path: found, name: path.basename(found), hasClaudeMd: fs.existsSync(path.join(found, 'CLAUDE.md')) });
      }
    }
    return out.sort((a, b) => Number(b.hasClaudeMd) - Number(a.hasClaudeMd) || a.name.localeCompare(b.name));
  }
}

function decodeProjectDir(encoded) {
  // Claude Code encodes the absolute path by replacing path separators (and ':') with '-'.
  // Dashes inside folder names are ambiguous, so try a few reconstructions.
  const parts = encoded.replace(/^-/, '').split('-');
  const candidates = [];
  const isWin = process.platform === 'win32';
  if (isWin && parts.length) {
    candidates.push(parts[0] + ':\\' + parts.slice(1).join('\\'));
  }
  candidates.push('/' + parts.join('/'));
  // Greedy merge: progressively join trailing segments with '-' (folders like "my-project").
  for (let i = parts.length - 1; i > 0; i--) {
    const merged = [...parts.slice(0, i - 1), parts.slice(i - 1).join('-')];
    candidates.push(isWin ? merged[0] + ':\\' + merged.slice(1).join('\\') : '/' + merged.join('/'));
  }
  return candidates;
}

// ---------------------------------------------------------------- worker pool (single reusable worker)
let worker = null;
let nextId = 1;
const pending = new Map();
function getWorker() {
  if (worker) return worker;
  worker = new Worker(path.join(__dirname, 'parse_worker.js'));
  worker.on('message', (msg) => {
    const p = pending.get(msg.id);
    if (!p) return;
    pending.delete(msg.id);
    if (msg.ok) p.resolve({ text: msg.text, pages: msg.pages });
    else p.reject(new ContextError(msg.message, msg.code));
  });
  const die = (err) => {
    for (const p of pending.values()) p.reject(new ContextError(`Parser crashed: ${err && err.message ? err.message : err}`, 'worker'));
    pending.clear();
    worker = null;
  };
  worker.on('error', die);
  worker.on('exit', (code) => die(new Error(`exit ${code}`)));
  return worker;
}
function parseInWorker(filePath) {
  return new Promise((resolve, reject) => {
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new ContextError('Parsing timed out after 120 s.', 'timeout'));
    }, 120000);
    pending.set(id, {
      resolve: (v) => { clearTimeout(timer); resolve(v); },
      reject: (e) => { clearTimeout(timer); reject(e); },
    });
    try {
      getWorker().postMessage({ id, filePath });
    } catch (e) {
      pending.delete(id);
      clearTimeout(timer);
      reject(new ContextError(e.message, 'worker'));
    }
  });
}
function terminateParser() {
  if (worker) { worker.terminate(); worker = null; }
}

// ---------------------------------------------------------------- sessions (logs) listing
function listSessions(profileDir) {
  const dir = path.join(profileDir, 'logs');
  if (!fs.existsSync(dir)) return [];
  const byStamp = new Map();
  for (const f of fs.readdirSync(dir)) {
    const m = f.match(/^session_(\d{8}_\d{4}(?:_\d+)?)(_report|_analysis)?\.(json|md)$/);
    if (!m) continue;
    const stamp = m[1];
    const e = byStamp.get(stamp) || { stamp, log_md: null, log_json: null, report: null, analysis: null, mtime: 0, lines: null, score: null, duration_s: null };
    const full = path.join(dir, f);
    const st = fs.statSync(full);
    e.mtime = Math.max(e.mtime, st.mtimeMs);
    if (m[2] === '_report') e.report = full;
    else if (m[2] === '_analysis') e.analysis = full;
    else if (m[3] === 'md') e.log_md = full;
    else e.log_json = full;
    byStamp.set(stamp, e);
  }
  const out = [...byStamp.values()];
  for (const e of out) {
    if (e.log_json) {
      try {
        const j = JSON.parse(fs.readFileSync(e.log_json, 'utf8'));
        e.lines = (j.entries || []).filter((x) => x.kind === 'them' || x.kind === 'me').length;
        e.suggestions = (j.entries || []).filter((x) => x.kind === 'copilot' || x.kind === 'vision').length;
        e.duration_s = j.duration_s ?? null;
        e.started_iso = j.started_iso || null;
        e.focus = j.session_focus || null;
      } catch {}
    }
    if (e.analysis) {
      try {
        const a = JSON.parse(fs.readFileSync(e.analysis, 'utf8'));
        e.score = a.analysis && Number.isFinite(a.analysis.overall_score) ? a.analysis.overall_score : null;
        if (!e.focus && a.session_focus) e.focus = a.session_focus;
        e.sub_scores = (a.analysis && a.analysis.sub_scores) || null;
      } catch {}
    }
  }
  return out.sort((a, b) => b.stamp.localeCompare(a.stamp));
}
function readTextFile(p, maxBytes = 400000) {
  const buf = fs.readFileSync(p);
  const text = buf.toString('utf8', 0, Math.min(buf.length, maxBytes));
  return buf.length > maxBytes ? text + '\n\n…(truncated)' : text;
}

function readJson(p, fallback) {
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return fallback;
  }
}
function writeJson(p, data) {
  const tmp = p + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + '\n');
  fs.renameSync(tmp, p);
}
function normalize(text) {
  return text.replace(/\r\n?/g, '\n').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
}
function countWords(text) {
  return text ? text.split(/\s+/).filter(Boolean).length : 0;
}

module.exports = { ProfileManager, BankStore, ContextError, SLOT_DIRS, LEGACY_SLOT_DIRS, BANK_CATEGORIES, SLOT_TO_CATEGORY, countWords, sanitizeName, listSessions, readTextFile, terminateParser };
