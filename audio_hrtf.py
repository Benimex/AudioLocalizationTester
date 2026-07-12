"""Backend C: HRTF object-panner sandbox. Renders sound sources placed at
azimuth/elevation/distance to binaural stereo via the KEMAR HRTF, and plays them
looping so positions can be auditioned live. Pure Python (slab), stereo out --
works on any 2ch endpoint, no 7.1 needed.

This is an AUDITION sandbox using a generic (non-individualized) reference HRTF, NOT a
test of a product APO. Elevation/front-back fidelity is inherently HRTF-limited.
"""
import threading
import numpy as np
import sounddevice as sd
import slab

SR = 48000
_H = None


def hrtf():
    global _H
    if _H is None:
        _H = slab.HRTF.kemar()
    return _H


def render_object(our_az, elevation, distance, kind, dur=1.0):
    """Render one mono source at a listener-relative position to a 2ch buffer.

    our_az: 0=front, +=clockwise/right (our convention). slab is CCW-positive, so negate.
    distance: metres-ish; level-only inverse-distance (KEMAR is a fixed-radius set).
    kind: 'white' | 'pink' | a WAV filename in stimuli/.
    """
    h = hrtf()
    sr = int(h.samplerate)
    if kind == "white":
        s = slab.Sound.whitenoise(duration=dur, samplerate=sr)
    elif kind == "pink":
        s = slab.Sound.pinknoise(duration=dur, samplerate=sr)
    else:
        import os
        s = slab.Sound(os.path.join(os.path.dirname(__file__), "stimuli", kind))
        if int(s.samplerate) != sr:
            s = s.resample(sr)
        if s.n_channels > 1:
            s = slab.Sound(s.data[:, :1], samplerate=sr)
    s = s.ramp(when="both", duration=0.01)                 # 10ms anti-click

    az = (360 - our_az) % 360                                # our right+ -> slab left+
    out = h.interpolate(azimuth=az, elevation=elevation, method="nearest").apply(s)
    out = out.resample(SR)
    data = np.asarray(out.data, dtype=np.float32)
    # ponytail: distance = inverse-distance gain only (no near-field HRTF in KEMAR),
    #           upgrade to a distance-cue model if externalization matters.
    gain = 1.0 / max(float(distance), 0.3)
    return data * min(gain, 1.5)


def render_scene(objects, dur=1.0):
    """Mix multiple objects into one looping 2ch buffer, normalized to avoid clipping."""
    if not objects:
        return np.zeros((int(SR * dur), 2), dtype=np.float32)
    rendered = [render_object(o["az"], o["el"], o.get("dist", 1.4),
                              o.get("stim", "white"), dur) for o in objects]
    n = min(len(r) for r in rendered)
    mix = np.sum([r[:n] for r in rendered], axis=0).astype(np.float32)
    peak = float(np.max(np.abs(mix)) or 1.0)
    if peak > 0.9:
        mix *= 0.9 / peak
    return mix


class Looper:
    """Gapless looping playback of a 2ch buffer that can be hot-swapped live."""

    def __init__(self):
        self.stream = None
        self.buf = None
        self.pos = 0
        self.device = None
        self.lock = threading.Lock()

    def _callback(self, outdata, frames, time_info, status):
        with self.lock:
            b = self.buf
            if b is None:
                outdata.fill(0)
                return
            end = self.pos + frames
            if end <= len(b):
                outdata[:] = b[self.pos:end]
                self.pos = end % len(b)
            else:                                            # wrap around the loop
                first = len(b) - self.pos
                outdata[:first] = b[self.pos:]
                outdata[first:] = b[:frames - first]
                self.pos = frames - first

    def play(self, buf, device):
        with self.lock:
            self.buf = buf
            self.pos = 0
        if self.stream is None or self.device != device:
            self._open(device)

    def _open(self, device):
        self.stop()
        self.device = device
        self.stream = sd.OutputStream(samplerate=SR, channels=2, dtype="float32",
                                      device=device, callback=self._callback)
        self.stream.start()

    def stop(self):
        if self.stream is not None:
            self.stream.stop(); self.stream.close()
            self.stream = None
        with self.lock:
            self.buf = None
            self.pos = 0


LOOPER = Looper()


def _selfcheck():
    d = render_object(90, 0, 1.4, "white")
    assert d.ndim == 2 and d.shape[1] == 2, d.shape
    # az +90 (our right) -> right ear louder than left.
    le, re = np.sum(d[:, 0] ** 2), np.sum(d[:, 1] ** 2)
    assert re > le, f"right louder expected: L={le:.3f} R={re:.3f}"
    # scene mix of 2 objects stays within range.
    m = render_scene([{"az": 0, "el": 0, "dist": 1.4, "stim": "white"},
                      {"az": 180, "el": 0, "dist": 1.4, "stim": "pink"}])
    assert np.max(np.abs(m)) <= 0.91, np.max(np.abs(m))
    print("audio_hrtf.py selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
