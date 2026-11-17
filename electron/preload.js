'use strict';
const { contextBridge, ipcRenderer, webUtils } = require('electron');

function pathsFromFiles(fileList) {
  const out = [];
  for (const f of fileList || []) {
    try {
      const p = webUtils && webUtils.getPathForFile ? webUtils.getPathForFile(f) : f.path;
      if (p) out.push(p);
    } catch {}
  }
  return out;
}

contextBridge.exposeInMainWorld('copilot', {
  /** Subscribe to backend/main events. Returns an unsubscribe function. */
  onEvent(callback) {
    const handler = (_event, msg) => callback(msg);
    ipcRenderer.on('copilot:event', handler);
    return () => ipcRenderer.removeListener('copilot:event', handler);
  },
  /** Send a command to main (routed to the backend unless it is a HUD-local command). */
  send(msg) {
    ipcRenderer.send('copilot:send', msg);
  },
  /** Stream a chunk of int16 mono PCM captured in the renderer to the backend. */
  sendAudio(channel, sampleRate, int16Array) {
    ipcRenderer.send('audio:chunk', channel, sampleRate, int16Array);
  },
  /** Absolute paths for File objects from a drag-and-drop event. */
  pathsFromFiles,
  /** Context slots of a profile (file pickers + parsing run off the UI thread). */
  context: {
    get: (profile) => ipcRenderer.invoke('context:get', profile),
    pick: (slot, profile) => ipcRenderer.invoke('context:pick', slot, profile),
    addPaths: (slot, paths, profile) => ipcRenderer.invoke('context:add_paths', slot, paths, profile),
    remove: (slot, index, profile) => ipcRenderer.invoke('context:remove', slot, index, profile),
  },
  /** Profile folders under /profiles. */
  profiles: {
    list: () => ipcRenderer.invoke('profiles:list'),
    create: (name) => ipcRenderer.invoke('profiles:create', name),
    duplicate: (source, target) => ipcRenderer.invoke('profiles:duplicate', source, target),
    remove: (name) => ipcRenderer.invoke('profiles:delete', name),
    rename: (name, newName) => ipcRenderer.invoke('profiles:rename', name, newName),
    setActive: (name) => ipcRenderer.send('profiles:active', name),
    openFolder: (name) => ipcRenderer.invoke('profiles:open_folder', name),
    openLogs: (name) => ipcRenderer.invoke('profiles:open_logs', name),
    openFile: (filePath) => ipcRenderer.invoke('profiles:open_file', filePath),
    openBank: () => ipcRenderer.invoke('profiles:open_bank'),
  },
  /** Global document & playbook bank (data/bank). */
  bank: {
    list: () => ipcRenderer.invoke('bank:list'),
    saveText: (slot, name, text, profile) => ipcRenderer.invoke('bank:save_text', slot, name, text, profile),
    read: (category, id) => ipcRenderer.invoke('bank:read', category, id),
    remove: (category, id) => ipcRenderer.invoke('bank:delete', category, id),
    migrate: () => ipcRenderer.invoke('bank:migrate'),
  },
  sessions: {
    list: (profile, archived) => ipcRenderer.invoke('sessions:list', profile, archived),
    read: (filePath) => ipcRenderer.invoke('sessions:read', filePath),
    readJson: (filePath) => ipcRenderer.invoke('sessions:read_json', filePath),
  },
  claudeProjects: {
    list: () => ipcRenderer.invoke('claude_projects:list'),
    pick: () => ipcRenderer.invoke('claude_projects:pick'),
  },
  /** v15 — passive auto-vision: one compressed frame of the screen under the cursor (main-process desktopCapturer). */
  vision: {
    capture: (opts) => ipcRenderer.invoke('vision:capture', opts || {}),
  },
  /** v15 — HUD ergonomics (ghost / click-through, keyboard nudge, background opacity). */
  hud: {
    toggleGhost: () => ipcRenderer.send('copilot:send', { type: 'toggle_ghost' }),
    setGhost: (value) => ipcRenderer.send('copilot:send', { type: 'set_ghost', value: Boolean(value) }),
    ghostHole: (open) => ipcRenderer.send('copilot:send', { type: 'ghost_hole', value: Boolean(open) }),
    setOpacity: (value) => ipcRenderer.send('copilot:send', { type: 'set_hud_opacity', value }),
    nudge: (dx, dy) => ipcRenderer.send('copilot:send', { type: 'nudge', dx, dy }),
    setAutoVision: (value) => ipcRenderer.send('copilot:send', { type: 'set_auto_vision', value: Boolean(value) }),
  },
});
