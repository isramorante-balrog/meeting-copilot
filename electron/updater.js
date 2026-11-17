'use strict';
/**
 * Auto-updater for the source distribution (the app runs from its own folder via the launcher, it is not
 * a packaged installer, so electron-updater does not apply).
 *
 *   check    GET https://api.github.com/repos/<repo>/releases/latest  (falls back to /tags when the repo
 *            has tags but no published release) and compare with package.json "version" (semver).
 *   download the release source tarball to a temp folder and unpack it with the system `tar`
 *            (present on Windows 10 1803+, macOS and Linux).
 *   install  copy the new files over the app folder. User data is never touched:
 *            config.json, profiles/, profiles_archived/, data/, logs/, context/, node_modules/,
 *            backend/.venv/, .state/ and anything else listed in PRESERVE.
 *   restart  re-run the launcher (bootstrap re-syncs npm / pip when package.json or requirements.txt
 *            changed) and quit this instance.
 *
 * Nothing is installed while a live session is running: the update is staged and applied when the HUD
 * returns to Setup or on the next start. Only https://api.github.com / github.com for the configured
 * repository is contacted, and only a tarball whose package.json carries a higher version is applied.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');
const { spawn, spawnSync } = require('child_process');

const PRESERVE = new Set(['config.json', 'profiles', 'profiles_archived', 'data', 'logs', 'context', 'node_modules',
  '.copilot', '.state', '.git', '.github', 'package-lock.json']);
const PRESERVE_NESTED = new Set([path.join('backend', '.venv'), path.join('backend', '__pycache__')]);
const UA = 'meeting-copilot-updater';

function parseVersion(v) {
  const m = String(v || '').trim().replace(/^v/i, '').match(/^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}
function isNewer(remote, local) {
  const a = parseVersion(remote), b = parseVersion(local);
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) { if (a[i] !== b[i]) return a[i] > b[i]; }
  return false;
}

function request(url, { json = false, dest = null, redirects = 5 } = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    if (u.protocol !== 'https:' || !/(^|\.)github(usercontent)?\.com$/.test(u.hostname)) {
      reject(new Error(`refusing to fetch ${u.hostname}`)); return;
    }
    const req = https.get(u, { headers: { 'User-Agent': UA, Accept: json ? 'application/vnd.github+json' : '*/*' }, timeout: 30000 }, (res) => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location) {
        res.resume();
        if (redirects <= 0) { reject(new Error('too many redirects')); return; }
        resolve(request(new URL(res.headers.location, u).toString(), { json, dest, redirects: redirects - 1 }));
        return;
      }
      if (res.statusCode !== 200) {
        res.resume();
        const e = new Error(`HTTP ${res.statusCode} for ${u.pathname}`); e.status = res.statusCode; reject(e); return;
      }
      if (dest) {
        const out = fs.createWriteStream(dest);
        res.pipe(out);
        out.on('finish', () => out.close(() => resolve(dest)));
        out.on('error', reject);
        return;
      }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        if (!json) { resolve(text); return; }
        try { resolve(JSON.parse(text)); } catch (e) { reject(e); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

class Updater {
  /**
   * @param {object} o
   * @param {string} o.root           app folder (contains package.json)
   * @param {() => object} o.getConfig returns the `updates` block of config.json
   * @param {(ev: object) => void} o.notify  forwards update_status events to the renderer
   * @param {() => boolean} o.isBusy  true while a live session is running (install is deferred)
   * @param {() => void} o.quit       quits the app after the launcher was re-spawned
   */
  constructor(o) {
    this.root = o.root;
    this.getConfig = o.getConfig;
    this.notify = o.notify || (() => {});
    this.isBusy = o.isBusy || (() => false);
    this.quit = o.quit || (() => {});
    this.state = { state: 'idle', current: this.currentVersion(), latest: null, notes: '', error: null, checked_at: null };
    this.staged = null; // { dir, version }
    this.timer = null;
    this.working = false;
  }

  currentVersion() {
    try { return JSON.parse(fs.readFileSync(path.join(this.root, 'package.json'), 'utf8')).version || '0.0.0'; } catch { return '0.0.0'; }
  }
  cfg() {
    const c = this.getConfig() || {};
    return { enabled: c.enabled !== false, auto_install: c.auto_install !== false, repo: c.repo || '', check_hours: Number(c.check_hours) || 6 };
  }
  set(patch) {
    this.state = { ...this.state, ...patch, current: this.currentVersion() };
    this.notify({ type: 'update_status', ...this.state, repo: this.cfg().repo, auto_install: this.cfg().auto_install });
    return this.state;
  }

  start() {
    const c = this.cfg();
    if (!c.enabled || !c.repo) { this.set({ state: c.repo ? 'disabled' : 'unconfigured' }); return; }
    setTimeout(() => this.check().catch(() => {}), 8000);
    this.timer = setInterval(() => this.check().catch(() => {}), c.check_hours * 3600 * 1000);
    if (this.timer.unref) this.timer.unref();
  }

  /** Latest version on GitHub: published release first, highest semver tag otherwise. */
  async latest() {
    const { repo } = this.cfg();
    if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) throw new Error('updates.repo must look like "owner/name"');
    const api = `https://api.github.com/repos/${repo}`;
    try {
      const rel = await request(`${api}/releases/latest`, { json: true });
      if (rel && parseVersion(rel.tag_name)) {
        return { version: rel.tag_name.replace(/^v/i, ''), tag: rel.tag_name, notes: String(rel.body || '').slice(0, 2000),
                 tarball: rel.tarball_url || `${api}/tarball/${rel.tag_name}`, url: rel.html_url };
      }
    } catch (e) { if (e.status !== 404) throw e; }
    const tags = await request(`${api}/tags?per_page=50`, { json: true });
    const best = (Array.isArray(tags) ? tags : []).filter((t) => parseVersion(t.name))
      .sort((a, b) => (isNewer(a.name, b.name) ? -1 : isNewer(b.name, a.name) ? 1 : 0))[0];
    if (!best) return null;
    return { version: best.name.replace(/^v/i, ''), tag: best.name, notes: '', tarball: `${api}/tarball/${best.name}`,
             url: `https://github.com/${repo}/releases/tag/${best.name}` };
  }

  /** Check; when a newer version exists and auto_install is on, download + stage (+ install when idle). */
  async check({ manual = false } = {}) {
    if (this.working) return this.state;
    const c = this.cfg();
    if (!c.repo) return this.set({ state: 'unconfigured' });
    if (!c.enabled && !manual) return this.set({ state: 'disabled' });
    this.working = true;
    try {
      this.set({ state: 'checking', error: null });
      const latest = await this.latest();
      const now = new Date().toISOString();
      if (!latest || !isNewer(latest.version, this.currentVersion())) {
        return this.set({ state: 'up_to_date', latest: latest ? latest.version : null, checked_at: now });
      }
      this.set({ state: 'available', latest: latest.version, notes: latest.notes, url: latest.url, checked_at: now });
      if (!c.auto_install && !manual) return this.state;
      await this.download(latest);
      if (this.isBusy()) return this.set({ state: 'staged' });   // applied when the live session ends
      return this.install();
    } catch (e) {
      // a background check that cannot reach GitHub (offline, rate limit) stays quiet; a manual one reports it
      return this.set({ state: manual ? 'error' : 'idle', error: String(e.message || e).slice(0, 300) });
    } finally { this.working = false; }
  }

  async download(latest) {
    this.set({ state: 'downloading', latest: latest.version });
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-update-'));
    const tarball = path.join(tmp, 'update.tar.gz');
    await request(latest.tarball, { dest: tarball });
    const dir = path.join(tmp, 'src');
    fs.mkdirSync(dir);
    const r = spawnSync('tar', ['-xzf', tarball, '-C', dir, '--strip-components=1'], { windowsHide: true });
    if (r.status !== 0) throw new Error(`tar failed: ${String(r.stderr || r.error || '').slice(0, 200)}`);
    // sanity: it must be this app, and really newer
    let pkg;
    try { pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8')); } catch { throw new Error('downloaded archive has no package.json'); }
    if (!fs.existsSync(path.join(dir, 'electron', 'main.js')) || !fs.existsSync(path.join(dir, 'backend', 'server.py'))) {
      throw new Error('downloaded archive is not a Meeting Copilot source tree');
    }
    if (!isNewer(pkg.version, this.currentVersion())) throw new Error(`archive version ${pkg.version} is not newer than ${this.currentVersion()}`);
    this.staged = { dir, version: pkg.version, tmp };
    return this.staged;
  }

  /** Copy the staged tree over the app folder (never the PRESERVE entries), then restart via the launcher. */
  install() {
    if (!this.staged) return this.state;
    if (this.isBusy()) return this.set({ state: 'staged' });
    const { dir, version, tmp } = this.staged;
    this.set({ state: 'installing', latest: version });
    const copyTree = (src, dst, rel = '') => {
      fs.mkdirSync(dst, { recursive: true });
      for (const ent of fs.readdirSync(src, { withFileTypes: true })) {
        const r = path.join(rel, ent.name);
        if ((rel === '' && PRESERVE.has(ent.name)) || PRESERVE_NESTED.has(r)) continue;
        if (r === path.join('data', 'bank')) continue;
        const s = path.join(src, ent.name), d = path.join(dst, ent.name);
        if (ent.isDirectory()) copyTree(s, d, r);
        else if (ent.isFile()) fs.copyFileSync(s, d);
      }
    };
    try {
      copyTree(dir, this.root);
      // bundled defaults that live under data/ are only added when missing, never overwritten
      const defPb = path.join('data', 'bank', 'playbooks', 'default_playbook.md');
      if (fs.existsSync(path.join(dir, defPb)) && !fs.existsSync(path.join(this.root, defPb))) {
        fs.mkdirSync(path.dirname(path.join(this.root, defPb)), { recursive: true });
        fs.copyFileSync(path.join(dir, defPb), path.join(this.root, defPb));
      }
    } catch (e) {
      return this.set({ state: 'error', error: `install failed: ${String(e.message || e).slice(0, 200)}` });
    }
    try { fs.rmSync(tmp, { recursive: true, force: true }); } catch {}
    this.staged = null;
    this.set({ state: 'restarting', latest: version });
    setTimeout(() => this.restart(), 1500);
    return this.state;
  }

  /** Called when the HUD returns to Setup: apply an update that was staged during a live session. */
  flush() { if (this.staged && !this.isBusy()) this.install(); }

  restart() {
    const win = process.platform === 'win32';
    const launcher = win ? path.join(this.root, 'Meeting Copilot.cmd')
      : process.platform === 'darwin' ? path.join(this.root, 'Meeting Copilot.command') : path.join(this.root, 'scripts', 'bootstrap.sh');
    try {
      if (win) spawn('cmd.exe', ['/c', 'start', '""', '/min', launcher], { cwd: this.root, detached: true, stdio: 'ignore', windowsHide: true }).unref();
      else spawn('/bin/sh', [launcher], { cwd: this.root, detached: true, stdio: 'ignore' }).unref();
    } catch (e) {
      this.set({ state: 'error', error: `updated to the new version, but the relaunch failed (${e.message}). Start the app again.` });
      return;
    }
    this.quit();
  }
}

module.exports = { Updater, isNewer, parseVersion, PRESERVE };
