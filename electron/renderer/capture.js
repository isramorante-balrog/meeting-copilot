'use strict';
/* Renderer-side audio capture (used when a channel's device is set to "electron").
 *   them -> getDisplayMedia({audio:true}) : system-audio loopback (Windows; answered by main.js)
 *   me   -> getUserMedia({audio:true})    : default microphone
 * PCM (16 kHz int16) goes to main -> backend over the WebSocket; RMS feeds the local meter. */
window.ElectronCapture = (() => {
  const active = {}; // channel -> { stream, ctx, node }
  const listeners = { level: () => {}, error: () => {} };

  async function start(channel) {
    await stop(channel);
    let stream;
    try {
      if (channel === 'them') {
        stream = await navigator.mediaDevices.getDisplayMedia({
          audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
          video: true, // Chromium requires video for loopback; the track is stopped immediately below.
        });
        stream.getVideoTracks().forEach((t) => t.stop());
      } else {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          video: false,
        });
      }
    } catch (e) {
      listeners.error(channel, `Electron capture failed (${channel}): ${e.message}`);
      return false;
    }
    if (!stream.getAudioTracks().length) {
      listeners.error(channel, `Electron capture (${channel}): no audio track (system-audio loopback is Windows-only).`);
      stream.getTracks().forEach((t) => t.stop());
      return false;
    }
    const ctx = new AudioContext();
    await ctx.audioWorklet.addModule('pcm-worklet.js');
    const src = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, 'pcm-worklet');
    node.port.onmessage = (ev) => {
      const { pcm, rms } = ev.data;
      listeners.level(channel, rms);
      window.copilot.sendAudio(channel, 16000, pcm);
    };
    src.connect(node);
    // Do not connect to ctx.destination (would echo the audio back out).
    active[channel] = { stream, ctx, node };
    stream.getAudioTracks()[0].addEventListener('ended', () => {
      listeners.error(channel, `Electron capture (${channel}) ended by the system.`);
      stop(channel);
    });
    return true;
  }

  async function stop(channel) {
    const a = active[channel];
    if (!a) return;
    delete active[channel];
    try {
      a.node.disconnect();
      a.stream.getTracks().forEach((t) => t.stop());
      await a.ctx.close();
    } catch {}
  }

  return {
    start,
    stop,
    isActive: (channel) => Boolean(active[channel]),
    onLevel: (fn) => (listeners.level = fn),
    onError: (fn) => (listeners.error = fn),
  };
})();
