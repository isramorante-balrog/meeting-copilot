'use strict';
/**
 * Problem reports.
 *
 * The app keeps the last errors it saw (backend, providers, renderer, main process). "Reportar problema"
 * turns them into a diagnostic report and files it as a GitHub issue on the project repository:
 *
 *   - default, works for every user, no secrets in the app: the report is saved under logs/reports/,
 *     copied to the clipboard, and the browser opens a pre-filled "new issue" page. The person reviews it
 *     and presses Submit with their own GitHub account.
 *   - optional, for a maintainer's own machines: put a fine-grained token with "Issues: read and write" on
 *     the reports repository in config.json -> reports.github_token and the issue is created directly
 *     through the API. The token is never shipped with the app; it exists only in that local file.
 *
 * What a report contains: app version, OS, the transcription engine and provider names with their state,
 * the recent error messages and the tail of logs/copilot.log. What is removed before anything leaves the
 * machine: API keys and tokens, e-mail addresses, the user's home-folder name, profile names, and every
 * transcribed or generated sentence (log lines with call content are reduced to a word count).
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');

const MAX_ERRORS = 60;

function scrub(text, extraNames = []) {
  let s = String(text || '');
  s = s.replace(/\b(sk-|gsk_|xai-|dg_|AIza|ghp_|github_pat_)[A-Za-z0-9_\-]{8,}/g, '$1<redacted>');
  s = s.replace(/\b[0-9a-f]{32,}\b/gi, '<hex-redacted>');
  s = s.replace(/(Bearer|Token|api[_-]?key["']?\s*[:=])\s*["']?[A-Za-z0-9_\-.]{12,}/gi, '$1 <redacted>');
  s = s.replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, '<email>');
  // call content: "[THEM] ...", "[ME] ...", speculation / question previews
  s = s.replace(/(\[(?:THEM|ME)\]\s)(.*)$/gm, (_m, tag, rest) => `${tag}<${rest.trim().split(/\s+/).length} words>`);
  s = s.replace(/(speculating on \d+ words: ).*$/gm, '$1<redacted>');
  s = s.replace(/(story ledger \+1 \([^)]*\): ).*$/gm, '$1<redacted>');
  s = s.replace(/(ignoring |discarding example about ).*$/gm, '$1<redacted>');
  const home = os.homedir();
  if (home) s = s.split(home).join('~');
  const user = path.basename(home || '');
  if (user && user.length > 2) s = s.replace(new RegExp(user.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), '<user>');
  for (const n of extraNames) {
    if (n && n.length > 2 && n !== 'default') s = s.split(n).join('<profile>');
  }
  return s;
}

class Reporter {
  /**
   * @param {object} o
   * @param {string} o.root        app folder
   * @param {string} o.logFile     logs/copilot.log
   * @param {() => object} o.getConfig     whole config object (keys are never copied into the report)
   * @param {() => object} o.getStatus     last backend status (engine, providers)
   * @param {() => string[]} o.getProfileNames
   * @param {string} o.version
   */
  constructor(o) {
    Object.assign(this, o);
    this.errors = [];
  }

  /** Remember an error (deduplicated, newest last). */
  note(source, message) {
    const msg = String(message || '').slice(0, 600);
    if (!msg) return;
    const last = this.errors[this.errors.length - 1];
    if (last && last.message === msg && last.source === source) { last.count += 1; last.t = Date.now(); return; }
    this.errors.push({ t: Date.now(), source, message: msg, count: 1 });
    if (this.errors.length > MAX_ERRORS) this.errors.shift();
  }
  count() { return this.errors.length; }
  clear() { this.errors = []; }

  cfg() {
    const c = (this.getConfig() || {}).reports || {};
    const upd = (this.getConfig() || {}).updates || {};
    return { repo: c.repo || upd.repo || '', token: c.github_token || '', include_log: c.include_log !== false };
  }

  build(userNote = '') {
    const cfg = this.getConfig() || {};
    const st = this.getStatus() || {};
    const names = this.getProfileNames ? this.getProfileNames() : [];
    const prov = st.providers_info || {};
    const provLines = Object.keys(prov).map((n) => `- ${n}: ${prov[n].available ? 'configured' : 'not configured'}, model \`${prov[n].model || '?'}\`${prov[n].error ? `, last error: ${prov[n].error}` : ''}`);
    const errLines = this.errors.slice(-25).map((e) => `- ${new Date(e.t).toISOString().slice(11, 19)} [${e.source}]${e.count > 1 ? ` ×${e.count}` : ''} ${e.message}`);
    let logTail = '';
    if (this.cfg().include_log) {
      try {
        const buf = fs.readFileSync(this.logFile, 'utf8');
        logTail = buf.split(/\r?\n/).slice(-120).join('\n');
      } catch {}
    }
    const title = (this.errors.length ? this.errors[this.errors.length - 1].message : (userNote || 'Problem report')).replace(/\s+/g, ' ').slice(0, 90);
    const body = [
      userNote ? `**What happened**\n${userNote}\n` : '**What happened**\n(describe what you were doing)\n',
      '**Environment**',
      `- app ${this.version} on ${process.platform} ${os.release()} (${process.arch}), Electron ${process.versions.electron || '?'}`,
      `- transcription: ${(st.stt || {}).engine || (cfg.stt || {}).engine || '?'}${(st.stt || {}).error ? `, error: ${(st.stt || {}).error}` : ''}`,
      `- primary provider: ${(cfg.general || {}).primary || '?'}, answer language: ${(cfg.general || {}).language || '?'}, input mode: ${(cfg.audio || {}).input_mode || 'pc'}`,
      '',
      '**Providers**',
      ...(provLines.length ? provLines : ['- (backend not connected)']),
      '',
      '**Recent errors**',
      ...(errLines.length ? errLines : ['- none recorded']),
      '',
      logTail ? `<details><summary>Log tail (call content removed)</summary>\n\n\`\`\`\n${logTail}\n\`\`\`\n</details>` : '',
    ].join('\n');
    return { title: scrub(`[report] ${title}`, names), body: scrub(body, names) };
  }

  save(report) {
    const dir = path.join(this.root, 'logs', 'reports');
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, `report_${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}.md`);
    fs.writeFileSync(file, `# ${report.title}\n\n${report.body}\n`);
    return file;
  }

  /** Create the issue through the API (maintainer token). Resolves with the issue URL. */
  postIssue(report) {
    const { repo, token } = this.cfg();
    return new Promise((resolve, reject) => {
      if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) { reject(new Error('reports.repo must look like "owner/name"')); return; }
      const data = JSON.stringify({ title: report.title, body: report.body.slice(0, 60000), labels: ['report'] });
      const req = https.request({ hostname: 'api.github.com', path: `/repos/${repo}/issues`, method: 'POST', timeout: 20000,
        headers: { 'User-Agent': 'meeting-copilot-reporter', Accept: 'application/vnd.github+json', Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } }, (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          let j = {};
          try { j = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch {}
          if (res.statusCode === 201 && j.html_url) resolve(j.html_url);
          else reject(new Error(`GitHub ${res.statusCode}: ${j.message || 'could not create the issue'}`));
        });
      });
      req.on('timeout', () => req.destroy(new Error('timeout')));
      req.on('error', reject);
      req.end(data);
    });
  }

  /** URL of a pre-filled "new issue" page; the body is shortened to stay inside browser URL limits. */
  issueUrl(report) {
    const { repo } = this.cfg();
    let body = report.body;
    if (body.length > 5500) body = `${body.slice(0, 5300)}\n\n…(shortened — the full report is on your clipboard: paste it here)`;
    return `https://github.com/${repo}/issues/new?title=${encodeURIComponent(report.title)}&body=${encodeURIComponent(body)}`;
  }
}

module.exports = { Reporter, scrub };
