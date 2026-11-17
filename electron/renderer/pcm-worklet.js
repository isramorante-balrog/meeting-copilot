/* AudioWorklet: mixes to mono, downsamples to 16 kHz, posts int16 chunks (~100 ms) plus an RMS level. */
class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.ratio = sampleRate / this.targetRate;
    this.acc = [];
    this.accLen = 0;
    this.chunkSamples = Math.round(this.targetRate * 0.1);
    this.pos = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input.length) return true;
    const n = input[0].length;
    const mono = new Float32Array(n);
    for (let c = 0; c < input.length; c++) {
      const ch = input[c];
      for (let i = 0; i < n; i++) mono[i] += ch[i];
    }
    if (input.length > 1) for (let i = 0; i < n; i++) mono[i] /= input.length;

    // Linear-interpolation downsample.
    const out = [];
    while (this.pos < n) {
      const i0 = Math.floor(this.pos);
      const i1 = Math.min(i0 + 1, n - 1);
      const frac = this.pos - i0;
      out.push(mono[i0] * (1 - frac) + mono[i1] * frac);
      this.pos += this.ratio;
    }
    this.pos -= n;

    const f32 = Float32Array.from(out);
    this.acc.push(f32);
    this.accLen += f32.length;
    if (this.accLen >= this.chunkSamples) {
      const all = new Float32Array(this.accLen);
      let o = 0;
      for (const a of this.acc) {
        all.set(a, o);
        o += a.length;
      }
      this.acc = [];
      this.accLen = 0;
      let sum = 0;
      const pcm = new Int16Array(all.length);
      for (let i = 0; i < all.length; i++) {
        const v = Math.max(-1, Math.min(1, all[i]));
        sum += v * v;
        pcm[i] = v < 0 ? v * 32768 : v * 32767;
      }
      const rms = Math.sqrt(sum / all.length);
      this.port.postMessage({ pcm, rms }, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-worklet', PcmWorklet);
