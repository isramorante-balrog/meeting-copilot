"""Dual-channel audio capture (microphone + system loopback) with VAD segmentation.

Captures hand raw mono float32 blocks to a *sink* callback `(channel, samples, sample_rate)`;
the server resamples to 16 kHz, measures levels and feeds the UtteranceSegmenter.

Loopback (what the other participants say), without virtual cables:
  * Windows  -> pyaudiowpatch WASAPI loopback of the default (or chosen) output device.
               Alternative: "electron" = the HUD captures system audio via Electron's
               desktopCapturer/getDisplayMedia loopback and streams PCM over the WebSocket.
  * macOS    -> sounddevice input device named like "BlackHole" (virtual device).
  * Linux    -> sounddevice input device whose name contains "monitor" (PulseAudio/PipeWire).

Device ids used in config.json / the UI:
  "default" | None       -> platform default
  "off"                  -> channel disabled
  "electron"             -> captured by the HUD (Electron), not by Python
  "sd:<index>"           -> PortAudio (sounddevice) device index
  "wasapi:<index>"       -> pyaudiowpatch loopback device index (Windows)
  "<name substring>"     -> first device whose name contains it
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from collections import deque
from typing import Callable, Optional

import numpy as np
import webrtcvad

log = logging.getLogger("audio")

FRAME_MS = 30
TARGET_SR = 16000
FRAME_SAMPLES = TARGET_SR * FRAME_MS // 1000  # 480 samples
RETRY_S = 3.0

SinkCallback = Callable[[str, np.ndarray, int], None]
UtteranceCallback = Callable[[str, np.ndarray, bool], None]  # (channel, audio16k, final)


def resample_to_16k(x: np.ndarray, src_sr: int) -> np.ndarray:
    """Linear-interpolation resampler; adequate for speech going into Whisper."""
    x = np.asarray(x, dtype=np.float32)
    if src_sr == TARGET_SR or len(x) == 0:
        return x
    n_out = int(round(len(x) * TARGET_SR / src_sr))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    src_idx = np.linspace(0, len(x) - 1, n_out)
    return np.interp(src_idx, np.arange(len(x)), x).astype(np.float32)


# --------------------------------------------------------------------------- VAD segmenter

class UtteranceSegmenter:
    """Feed 16 kHz float32 audio; emits complete utterances via callback."""

    def __init__(self, channel: str, on_utterance: UtteranceCallback, aggressiveness: int = 2,
                 end_silence_ms: int = 450, min_speech_ms: int = 350, max_utterance_s: float = 1.5,
                 energy_threshold: float = 0.015, end_silence_incomplete_ms: int = 700,
                 completeness: Callable[[], bool] | None = None):
        self.channel = channel
        self.on_utterance = on_utterance
        self.vad = webrtcvad.Vad(int(max(0, min(3, aggressiveness))))
        # Frames are "voiced" when WebRTC VAD says so OR their RMS energy is above this gate, so continuous
        # TTS / video speech (and codecs that confuse the VAD) still gets transcribed.
        self.energy_threshold = float(energy_threshold)
        self.frames_in = 0
        self.utterances_out = 0
        self._buf = np.zeros(0, dtype=np.float32)
        self._speech_frames: list[np.ndarray] = []
        self._pre_roll: deque[np.ndarray] = deque(maxlen=8)  # ~240 ms lead-in
        self._in_speech = False
        self._silence_frames = 0
        self._voiced_count = 0
        self._end_silence_frames = max(1, int(end_silence_ms // FRAME_MS))
        # Adaptive window: when the interim transcript ends mid-clause (preposition, conjunction, comma…)
        # we wait this long instead, so slow speakers and multi-clause questions are not cut off.
        self._end_silence_incomplete_frames = max(self._end_silence_frames, int(end_silence_incomplete_ms // FRAME_MS))
        self._completeness = completeness  # callable -> True when the sentence so far looks finished
        self._min_speech_frames = max(1, int(min_speech_ms // FRAME_MS))
        self._max_frames = max(10, int(float(max_utterance_s) * 1000 // FRAME_MS))
        self._lock = threading.Lock()

    def feed(self, samples_16k: np.ndarray) -> None:
        with self._lock:
            self._buf = np.concatenate([self._buf, samples_16k.astype(np.float32)])
            while len(self._buf) >= FRAME_SAMPLES:
                frame = self._buf[:FRAME_SAMPLES]
                self._buf = self._buf[FRAME_SAMPLES:]
                self._process(frame)

    def reset(self) -> None:
        with self._lock:
            self._clear()

    def force_flush(self) -> bool:
        """Emit whatever speech is in progress right now (push-to-answer). Returns True if something was emitted."""
        with self._lock:
            if self._in_speech and self._voiced_count >= 3:
                if len(self._buf):
                    self._speech_frames.append(self._buf.copy())
                    self._buf = np.zeros(0, dtype=np.float32)
                return self._flush(force=True, final=True)
            return False

    def in_speech(self) -> bool:
        return self._in_speech

    def _clear(self) -> None:
        self._buf = np.zeros(0, dtype=np.float32)
        self._speech_frames = []
        self._pre_roll.clear()
        self._in_speech = False
        self._silence_frames = 0
        self._voiced_count = 0

    def _process(self, frame: np.ndarray) -> None:
        self.frames_in += 1
        pcm = (np.clip(frame, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        try:
            voiced = self.vad.is_speech(pcm, TARGET_SR)
        except Exception:
            voiced = False
        if not voiced and self.energy_threshold > 0:
            voiced = float(np.sqrt(np.mean(np.square(frame)))) > self.energy_threshold
        if not self._in_speech:
            self._pre_roll.append(frame)
            if voiced:
                self._in_speech = True
                self._speech_frames = list(self._pre_roll)
                self._voiced_count = 1
                self._silence_frames = 0
            return
        self._speech_frames.append(frame)
        if voiced:
            self._voiced_count += 1
            self._silence_frames = 0
        else:
            self._silence_frames += 1
        # Flush on a pause (end_silence) OR every max_utterance_s of continuous speech (rolling chunks),
        # so a speaker who never pauses (YouTube, TTS) is still transcribed every few seconds.
        if self._silence_frames >= self._end_silence_frames:
            complete = True
            if self._completeness is not None and self._silence_frames < self._end_silence_incomplete_frames:
                try:
                    complete = self._completeness()
                except Exception:
                    complete = True
            if complete:
                self._flush(force=False, final=True)      # pause after a finished sentence -> turn complete
            # else: mid-clause pause -> keep buffering until the longer window elapses
        elif len(self._speech_frames) >= self._max_frames:
            self._flush(force=True, final=False)          # rolling chunk while they keep talking

    def _flush(self, force: bool = False, final: bool = True) -> bool:
        frames = self._speech_frames
        voiced = self._voiced_count
        if final:
            self._clear()
        else:
            # Rolling chunk while they keep talking: emit the voiced part, keep the trailing silence
            # (so the pause detector keeps counting) plus ~150 ms of overlap so no word is cut.
            trailing = self._silence_frames
            emit = frames[:-trailing] if trailing else frames
            keep = (emit[-5:] if emit else []) + (frames[-trailing:] if trailing else [])
            self._speech_frames = list(keep)
            self._voiced_count = 1
            frames = emit
        if frames and (force or voiced >= self._min_speech_frames):
            audio = np.concatenate(frames)
            # Drop near-silent chunks the VAD mistook for speech (saves Whisper calls / hallucinations).
            if float(np.sqrt(np.mean(np.square(audio)))) >= self.energy_threshold * 0.3:
                self.utterances_out += 1
                try:
                    self.on_utterance(self.channel, audio, final)
                except Exception:
                    log.exception("utterance callback failed")
                return True
        if final:
            # Nothing worth transcribing in the tail, but the turn DID end: tell the server so the
            # rolling pieces already transcribed get merged and classified now.
            try:
                self.on_utterance(self.channel, None, True)
            except Exception:
                log.exception("utterance callback failed")
        return False


# --------------------------------------------------------------------------- device spec

def parse_device(spec) -> tuple[str, object]:
    """Return (kind, value): kind in {default, off, electron, sd, wasapi, name}."""
    if spec is None or spec == "" or str(spec).lower() == "default":
        return "default", None
    s = str(spec).strip()
    low = s.lower()
    if low == "off":
        return "off", None
    if low == "electron":
        return "electron", None
    if low.startswith("sd:") and s[3:].isdigit():
        return "sd", int(s[3:])
    if low.startswith("wasapi:") and s[7:].isdigit():
        return "wasapi", int(s[7:])
    if s.isdigit():
        return "sd", int(s)
    return "name", s


# --------------------------------------------------------------------------- captures

class _BaseCapture(threading.Thread):
    kind_label = "capture"

    def __init__(self, name: str, channel: str, device, sink: SinkCallback, gate: Callable[[], bool]):
        super().__init__(name=name, daemon=True)
        self.channel = channel
        self.spec = device
        self.sink = sink
        self.gate = gate
        self.stop_event = threading.Event()
        self.device_name: str = "(not started)"
        self.error: Optional[str] = None
        self.active = False

    def stop(self) -> None:
        self.stop_event.set()

    def _push(self, mono: np.ndarray, sr: int) -> None:
        if self.gate():
            self.sink(self.channel, mono, sr)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self._run_once()
                self.active = False
                if self.stop_event.is_set():
                    return
                self.error = "stream ended; retrying"
            except Exception as exc:
                self.active = False
                self.error = f"{type(exc).__name__}: {exc}"
                log.error("%s failed: %s", self.name, self.error)
            self.stop_event.wait(RETRY_S)

    def _run_once(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class MicCapture(_BaseCapture):
    """Microphone capture via sounddevice (PortAudio)."""

    def __init__(self, device, sink: SinkCallback, gate: Callable[[], bool], channel: str = "me"):
        super().__init__("mic-capture", channel, device, sink, gate)

    def _run_once(self) -> None:
        import sounddevice as sd

        kind, value = parse_device(self.spec)
        dev = None
        if kind == "sd":
            dev = value
        elif kind == "name":
            dev = _find_sd_device_index(sd, value, kind="input")
            if dev is None:
                raise RuntimeError(f"no input device matching '{value}'")
        info = sd.query_devices(dev, "input") if dev is not None else sd.query_devices(kind="input")
        sr = int(info["default_samplerate"]) or 48000
        self.device_name = str(info["name"])
        log.info("Mic: %s @ %d Hz", self.device_name, sr)

        def cb(indata, frames, _time, status):
            mono = indata[:, 0] if indata.ndim > 1 else indata
            self._push(np.ascontiguousarray(mono, dtype=np.float32), sr)

        with sd.InputStream(device=dev, channels=1, samplerate=sr, dtype="float32",
                            blocksize=int(sr * FRAME_MS / 1000), callback=cb):
            self.error = None
            self.active = True
            while not self.stop_event.is_set():
                time.sleep(0.1)


class LoopbackCapture(_BaseCapture):
    """System-audio (what the other participants say) capture."""

    def __init__(self, device, sink: SinkCallback, gate: Callable[[], bool], channel: str = "them"):
        super().__init__("loopback-capture", channel, device, sink, gate)

    def _run_once(self) -> None:
        kind, _ = parse_device(self.spec)
        if sys.platform.startswith("win") and kind != "sd":
            if kind == "default" and not getattr(self, "_follow_failed", False):
                try:
                    self._run_wasapi_follow()
                    return
                except Exception as exc:  # noqa: BLE001 - never worse than before: fall back to the one default device
                    self._follow_failed = True
                    log.warning("Loopback: following all outputs failed (%s) - using the default output only", exc)
            self._run_wasapi()
        else:
            self._run_sounddevice()

    # -- Windows, device = default: listen to EVERY output and follow the one that is playing ------------
    HOT_RMS = 0.003          # a device counts as "playing" above this level
    HOT_RELEASE_S = 0.6      # the followed device must be quiet this long before another one takes over

    def _run_wasapi_follow(self) -> None:
        """A call does not always play on the Windows default output: Teams / Meet / Zoom use the device chosen
        in their own settings (usually the headset), so the loopback of the default device can be silent for the
        whole call. With the device left on "default" every output's loopback is opened and the frames of the one
        that actually carries sound are forwarded; the others are ignored."""
        import pyaudiowpatch as pyaudio

        p = pyaudio.PyAudio()
        streams: dict[int, object] = {}
        names: dict[int, str] = {}
        state = {"hot": None, "loud": {}}
        try:
            try:
                default_idx = int(p.get_default_wasapi_loopback()["index"])
            except Exception:  # noqa: BLE001
                default_idx = None
            devices = list(p.get_loopback_device_info_generator())
            if not devices:
                raise RuntimeError("no WASAPI loopback device found (is any playback device enabled?)")

            def make_cb(idx: int, ch: int, sr: int):
                def cb(in_data, frame_count, _time_info, _status):
                    data = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
                    if ch > 1:
                        data = data.reshape(-1, ch).mean(axis=1)
                    now = time.time()
                    if len(data) and float(np.sqrt(np.mean(np.square(data)))) > self.HOT_RMS:
                        state["loud"][idx] = now
                        hot = state["hot"]
                        if hot != idx and (hot is None or now - state["loud"].get(hot, 0.0) > self.HOT_RELEASE_S):
                            state["hot"] = idx
                            self.device_name = f"{names[idx]} (auto)"
                            log.info("Loopback: following %s", names[idx])
                    if state["hot"] == idx:
                        self._push(data, sr)
                    return (None, pyaudio.paContinue)
                return cb

            for d in devices:
                idx = int(d["index"])
                sr = int(d["defaultSampleRate"]) or 48000
                ch = max(1, int(d["maxInputChannels"]))
                names[idx] = str(d["name"])
                try:
                    st = p.open(format=pyaudio.paInt16, channels=ch, rate=sr, input=True, input_device_index=idx,
                                frames_per_buffer=int(sr * FRAME_MS / 1000), stream_callback=make_cb(idx, ch, sr))
                    st.start_stream()
                    streams[idx] = st
                except Exception as exc:  # noqa: BLE001 - a device that cannot be opened is skipped, not fatal
                    log.info("Loopback: skipping %s (%s)", names[idx], exc)
            if not streams:
                raise RuntimeError("no WASAPI loopback device could be opened")
            state["hot"] = default_idx if default_idx in streams else next(iter(streams))
            self.device_name = f"{names[state['hot']]} (auto)"
            self.outputs = [names[i] for i in streams]
            log.info("Loopback (WASAPI, following %d outputs): %s", len(streams), "; ".join(self.outputs))
            self.error = None
            self.active = True
            known = sorted(names.values())
            checked = time.time()
            while not self.stop_event.is_set() and any(st.is_active() for st in streams.values()):
                time.sleep(0.2)
                if time.time() - checked > 5.0:        # a headset plugged in / removed: reopen with the new list
                    checked = time.time()
                    try:
                        q = pyaudio.PyAudio()
                        try:
                            current = sorted(str(d["name"]) for d in q.get_loopback_device_info_generator())
                        finally:
                            q.terminate()
                    except Exception:  # noqa: BLE001
                        current = known
                    if current != known:
                        log.info("Loopback: the list of outputs changed - reopening")
                        return
        finally:
            for st in streams.values():
                try:
                    st.stop_stream()
                    st.close()
                except Exception:  # noqa: BLE001
                    pass
            p.terminate()

    # -- Windows ---------------------------------------------------------
    def _run_wasapi(self) -> None:
        import pyaudiowpatch as pyaudio

        kind, value = parse_device(self.spec)
        p = pyaudio.PyAudio()
        try:
            target = None
            if kind == "wasapi":
                target = p.get_device_info_by_index(value)
            elif kind == "name":
                for lb in p.get_loopback_device_info_generator():
                    if value.lower() in lb["name"].lower():
                        target = lb
                        break
                if target is None:
                    raise RuntimeError(f"no WASAPI loopback device matching '{value}'")
            else:
                # Default output device -> its loopback twin.
                try:
                    target = p.get_default_wasapi_loopback()
                except Exception:
                    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                    default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
                    for lb in p.get_loopback_device_info_generator():
                        if default_out["name"] in lb["name"]:
                            target = lb
                            break
            if target is None:
                raise RuntimeError("no WASAPI loopback device found (is any playback device enabled?)")

            sr = int(target["defaultSampleRate"]) or 48000
            ch = max(1, int(target["maxInputChannels"]))
            self.device_name = str(target["name"])
            log.info("Loopback (WASAPI): %s @ %d Hz, %d ch", self.device_name, sr, ch)

            def cb(in_data, frame_count, _time_info, _status):
                data = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
                if ch > 1:
                    data = data.reshape(-1, ch).mean(axis=1)
                self._push(data, sr)
                return (None, pyaudio.paContinue)

            stream = p.open(format=pyaudio.paInt16, channels=ch, rate=sr, input=True,
                            input_device_index=int(target["index"]),
                            frames_per_buffer=int(sr * FRAME_MS / 1000), stream_callback=cb)
            try:
                stream.start_stream()
                self.error = None
                self.active = True
                # WASAPI loopback goes silent/inactive if the output device is removed or the default
                # device changes -> leave the loop; the outer retry re-resolves the device.
                while not self.stop_event.is_set() and stream.is_active():
                    time.sleep(0.2)
            finally:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
        finally:
            p.terminate()

    # -- macOS / Linux / explicit PortAudio device ----------------------
    def _run_sounddevice(self) -> None:
        import sounddevice as sd

        kind, value = parse_device(self.spec)
        dev = None
        if kind == "sd":
            dev = value
        elif kind == "name":
            dev = _find_sd_device_index(sd, value, kind="input")
        else:
            for cand in ["blackhole", "monitor", "loopback", "stereo mix", "what u hear", "soundflower"]:
                dev = _find_sd_device_index(sd, cand, kind="input")
                if dev is not None:
                    break
        if dev is None:
            raise RuntimeError(
                "No loopback input device found. macOS: install BlackHole (brew install blackhole-2ch) and route "
                "the meeting app's output to a Multi-Output Device; Linux: pick the '...monitor' source. "
                "Or choose 'System audio via Electron' on Windows.")
        info = sd.query_devices(dev, "input")
        sr = int(info["default_samplerate"]) or 48000
        ch = max(1, min(2, int(info["max_input_channels"])))
        self.device_name = str(info["name"])
        log.info("Loopback (sounddevice): %s @ %d Hz, %d ch", self.device_name, sr, ch)

        def cb(indata, frames, _time, status):
            mono = indata.mean(axis=1) if indata.ndim > 1 and indata.shape[1] > 1 else indata[:, 0]
            self._push(np.ascontiguousarray(mono, dtype=np.float32), sr)

        with sd.InputStream(device=dev, channels=ch, samplerate=sr, dtype="float32",
                            blocksize=int(sr * FRAME_MS / 1000), callback=cb):
            self.error = None
            self.active = True
            while not self.stop_event.is_set():
                time.sleep(0.1)


# --------------------------------------------------------------------------- helpers

def _find_sd_device_index(sd, needle: str, kind: str) -> Optional[int]:
    needle = needle.lower()
    for idx, d in enumerate(sd.query_devices()):
        chans = d["max_input_channels"] if kind == "input" else d["max_output_channels"]
        if chans > 0 and needle in str(d["name"]).lower():
            return idx
    return None


def list_devices_struct() -> dict:
    """Device inventory for the UI: {"mic": [{id,name}], "loopback": [{id,name}], "platform": ...}."""
    out = {"mic": [], "loopback": [], "platform": sys.platform, "errors": []}
    try:
        import sounddevice as sd

        hostapis = sd.query_hostapis()
        for idx, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] <= 0:
                continue
            api = hostapis[d["hostapi"]]["name"] if d["hostapi"] < len(hostapis) else ""
            entry = {"id": f"sd:{idx}", "name": f"{d['name']} ({api})" if api else d["name"]}
            out["mic"].append(entry)
            if not sys.platform.startswith("win"):
                out["loopback"].append(entry)
    except Exception as exc:
        out["errors"].append(f"sounddevice: {exc}")
    if sys.platform.startswith("win"):
        try:
            import pyaudiowpatch as pyaudio

            p = pyaudio.PyAudio()
            try:
                for lb in p.get_loopback_device_info_generator():
                    out["loopback"].append({"id": f"wasapi:{lb['index']}", "name": lb["name"]})
            finally:
                p.terminate()
        except Exception as exc:
            out["errors"].append(f"pyaudiowpatch: {exc}")
    return out


def list_devices() -> str:
    """Human-readable device inventory used by `server.py --list-devices`."""
    s = list_devices_struct()
    lines = ["== Microphone / input devices =="] + [f"  {d['id']:<10} {d['name']}" for d in s["mic"]]
    lines += ["== System-audio (loopback) devices =="] + [f"  {d['id']:<10} {d['name']}" for d in s["loopback"]]
    if sys.platform.startswith("win"):
        lines.append("  electron   System audio via Electron desktopCapturer (no driver needed)")
    lines += [f"  !! {e}" for e in s["errors"]]
    return "\n".join(lines)
