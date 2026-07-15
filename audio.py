"""Audio engine: device enumeration, 7.1 panner, stimulus synthesis/loading, WASAPI playback.

The tool does channel-based amplitude panning only. NO HRTF / binaural processing here --
the APO on the endpoint does that. LFE is always silent.
"""
import os
import wave
import numpy as np
import sounddevice as sd

SR = 48000

# Windows 7.1 channel order and the index of each speaker in the 8ch frame.
# Order: FL, FR, FC, LFE, BL, BR, SL, SR
CH_INDEX = {"FL": 0, "FR": 1, "FC": 2, "LFE": 3, "BL": 4, "BR": 5, "SL": 6, "SR": 7}
N_CH = 8

# Speaker azimuths (deg, 0=front, +clockwise/right). LFE has no azimuth.
SPEAKER_AZ = {"FC": 0, "FR": 30, "SR": 90, "BR": 135, "BL": -135, "SL": -90, "FL": -30}


def _norm180(a):
    """Normalize angle to [-180, 180)."""
    return ((a + 180.0) % 360.0) - 180.0


# Speakers sorted by azimuth; back arc (BR->BL) wraps across +-180.
_SORTED = sorted(SPEAKER_AZ.items(), key=lambda kv: kv[1])  # [(name, az), ...] by az


def pan_gains(target_az, eps=1e-9):
    """Constant-power pairwise (2D VBAP) gains for a horizontal target azimuth.

    Returns dict speaker_name -> linear gain. Exactly-on-speaker => that speaker alone.
    Sum of squares of returned gains == 1 (constant power).
    """
    t = _norm180(target_az)

    # Exact speaker hit.
    for name, az in SPEAKER_AZ.items():
        if abs(_norm180(t - az)) < 1e-6:
            return {name: 1.0}

    names = [n for n, _ in _SORTED]
    azs = [a for _, a in _SORTED]

    # Front arcs: consecutive sorted pairs.
    for i in range(len(azs) - 1):
        a, b = azs[i], azs[i + 1]
        if a <= t <= b:
            p = (t - a) / (b - a)
            return {names[i]: np.cos(p * np.pi / 2), names[i + 1]: np.sin(p * np.pi / 2)}

    # Back arc: BR (max az) -> BL (min az) crossing +-180.
    a_name, a = names[-1], azs[-1]          # BR, +135
    b_name, b = names[0], azs[0] + 360.0    # BL, +225
    tt = t if t >= a else t + 360.0         # map t into [135, 225]
    p = (tt - a) / (b - a)
    return {a_name: np.cos(p * np.pi / 2), b_name: np.sin(p * np.pi / 2)}


def pan_to_frame(mono, target_az, peak_dbfs=-12.0):
    """Expand a mono signal to an 8ch frame panned to target_az, normalized to peak_dbfs."""
    mono = np.asarray(mono, dtype=np.float32)
    peak = np.max(np.abs(mono)) or 1.0
    target_peak = 10.0 ** (peak_dbfs / 20.0)
    mono = mono * (target_peak / peak)

    frame = np.zeros((len(mono), N_CH), dtype=np.float32)
    for name, g in pan_gains(target_az).items():
        frame[:, CH_INDEX[name]] += mono * float(g)
    return frame


def folddown_71_to_stereo(frame8):
    """Fold an FL FR FC LFE BL BR SL SR frame down to stereo, dropping LFE."""
    frame8 = np.asarray(frame8, dtype=np.float32)
    if frame8.ndim != 2 or frame8.shape[1] != N_CH:
        raise ValueError("7.1 fold-down requires an (n, 8) frame.")
    stereo = np.empty((len(frame8), 2), dtype=np.float32)
    stereo[:, 0] = (frame8[:, CH_INDEX["FL"]] +
                    0.7071 * frame8[:, CH_INDEX["FC"]] +
                    0.7071 * frame8[:, CH_INDEX["SL"]] +
                    0.7071 * frame8[:, CH_INDEX["BL"]])
    stereo[:, 1] = (frame8[:, CH_INDEX["FR"]] +
                    0.7071 * frame8[:, CH_INDEX["FC"]] +
                    0.7071 * frame8[:, CH_INDEX["SR"]] +
                    0.7071 * frame8[:, CH_INDEX["BR"]])
    source_peak = np.max(np.abs(frame8)) if frame8.size else 0.0
    stereo_peak = np.max(np.abs(stereo)) if stereo.size else 0.0
    if stereo_peak > 0.0:
        stereo *= source_peak / stereo_peak
    return stereo


def pan_stereo_gains(az):
    """Constant-power stereo gains for the front arc, clamped to [-90, 90]."""
    az = np.clip(float(az), -90.0, 90.0)
    p = (az + 90.0) / 180.0
    return np.cos(p * np.pi / 2), np.sin(p * np.pi / 2)


def pan_to_stereo(mono, az, peak_dbfs=-12.0):
    """Expand a mono signal to a constant-power 2ch stereo frame."""
    mono = np.asarray(mono, dtype=np.float32)
    peak = np.max(np.abs(mono)) or 1.0
    target_peak = 10.0 ** (peak_dbfs / 20.0)
    mono = mono * (target_peak / peak)
    left, right = pan_stereo_gains(az)
    frame = np.empty((len(mono), 2), dtype=np.float32)
    frame[:, 0] = mono * float(left)
    frame[:, 1] = mono * float(right)
    return frame


def render_output(mono, az, peak_dbfs=-12.0, mode="bed71"):
    """Render mono to an 8ch 7.1 bed, folded-down stereo, or direct stereo."""
    if mode == "bed71":
        return pan_to_frame(mono, az, peak_dbfs)
    if mode == "folddown":
        return folddown_71_to_stereo(pan_to_frame(mono, az, peak_dbfs))
    if mode == "stereo":
        return pan_to_stereo(mono, az, peak_dbfs)
    raise ValueError(f"Unknown output mode '{mode}'.")


# ---- Stimulus synthesis / loading -------------------------------------------

def _raised_cosine_ramp(sig, ms=10.0):
    """Apply 10ms raised-cosine fade in/out to avoid clicks. In-place-safe copy."""
    sig = sig.copy()
    n = int(SR * ms / 1000.0)
    if n * 2 > len(sig):
        n = len(sig) // 2
    if n == 0:
        return sig
    ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, n)))
    sig[:n] *= ramp
    sig[-n:] *= ramp[::-1]
    return sig


def pink_noise(n, seed):
    """Voss-McCartney-ish pink noise via FFT filtering. Deterministic given seed."""
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    # 1/sqrt(f) spectral shaping.
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    freqs[0] = freqs[1] if len(freqs) > 1 else 1.0
    spec = spec / np.sqrt(freqs)
    out = np.fft.irfft(spec, n).astype(np.float32)
    out /= (np.max(np.abs(out)) or 1.0)
    return out


def burst_stimulus(source_mono, gap_ms=100.0, n_bursts=3):
    """Wrap a per-burst mono source into n_bursts with silent gaps and per-burst ramps."""
    gap = np.zeros(int(SR * gap_ms / 1000.0), dtype=np.float32)
    one = _raised_cosine_ramp(np.asarray(source_mono, dtype=np.float32))
    parts = []
    for i in range(n_bursts):
        parts.append(one)
        if i < n_bursts - 1:
            parts.append(gap)
    return np.concatenate(parts)


def make_stimulus(kind, seed, burst_ms=250.0, region=None):
    """Build a mono stimulus token. kind='pink' or a WAV filename in stimuli/.

    Pink: 3x250ms bursts, 100ms gaps, seeded fresh token.
    WAV: selected region or whole file played once, ramped (no burst wrapping).
    """
    if kind == "pink":
        per = pink_noise(int(SR * burst_ms / 1000.0), seed)
        return burst_stimulus(per)
    # WAV file.
    mono = load_wav(kind)
    if region is not None and len(region) == 2:
        a_sec, b_sec = float(region[0]), float(region[1])
        if b_sec > a_sec:
            start = max(0, min(len(mono), int(a_sec * SR)))
            end = max(0, min(len(mono), int(b_sec * SR)))
            mono = mono[start:end]
            if len(mono) < int(SR * 0.03):
                raise ValueError("Region too short.")
    return _raised_cosine_ramp(mono)


def load_wav(name):
    """Load a mono 48kHz WAV from stimuli/. Refuse non-conforming files (no silent resample)."""
    path = os.path.join(os.path.dirname(__file__), "stimuli", name)
    with wave.open(path, "rb") as w:
        if w.getframerate() != SR:
            raise ValueError(f"{name}: {w.getframerate()} Hz, need 48000. Convert first.")
        if w.getnchannels() != 1:
            raise ValueError(f"{name}: {w.getnchannels()} channels, need mono. Convert first.")
        if w.getsampwidth() != 2:
            raise ValueError(f"{name}: {w.getsampwidth()*8}-bit, need 16-bit PCM. Convert first.")
        frames = w.readframes(w.getnframes())
    return (np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0)


def wav_info(name):
    """Return duration and a compact 600-bin peak overview for a WAV stimulus."""
    mono = load_wav(name)
    n = len(mono)
    peaks = []
    for i in range(600):
        start = i * n // 600
        end = (i + 1) * n // 600
        peak = float(np.max(np.abs(mono[start:end]))) if end > start else 0.0
        peaks.append(round(peak, 3))
    return {"duration": n / SR, "peaks": peaks}


def list_stimuli():
    """WAV files available in stimuli/, plus built-in 'pink'."""
    d = os.path.join(os.path.dirname(__file__), "stimuli")
    wavs = []
    if os.path.isdir(d):
        wavs = sorted(f for f in os.listdir(d) if f.lower().endswith(".wav"))
    return ["pink"] + wavs


# ---- Device enumeration / playback ------------------------------------------

def supports_8ch(device_index):
    """True if an 8ch/48k stream can actually be opened on this endpoint.

    Spatial-sound endpoints (Atmos/Sonic) often report max_output_channels=2 (the physical
    mix format) yet accept a 7.1 stream that the APO virtualizes -- so probe, don't trust
    the reported count.
    """
    try:
        sd.check_output_settings(device=device_index, channels=N_CH,
                                 samplerate=SR, dtype="float32")
        return True
    except Exception:
        return False


def list_output_devices():
    """WASAPI output endpoints. [{index, name, channels, supports_8ch}].

    `channels` is the reported count (may understate spatial endpoints); `supports_8ch`
    is the real gate -- whether a 7.1 stream opens.
    """
    devices = sd.query_devices()
    try:
        wasapi = sd.query_hostapis(_wasapi_index())
        valid = set(wasapi["devices"])
    except Exception:
        valid = None
    out = []
    for i, d in enumerate(devices):
        if d["max_output_channels"] < 1:
            continue
        if valid is not None and i not in valid:
            continue
        out.append({"index": i, "name": d["name"], "channels": d["max_output_channels"],
                    "supports_8ch": supports_8ch(i)})
    return out


def _wasapi_index():
    for i, ha in enumerate(sd.query_hostapis()):
        if "WASAPI" in ha["name"]:
            return i
    raise RuntimeError("No WASAPI host API found")


def play_frame(frame, device_index):
    """Blocking playback of an 8ch or 2ch frame to a WASAPI endpoint (shared mode)."""
    frame = np.asarray(frame, dtype=np.float32)
    if frame.ndim != 2 or frame.shape[1] not in (2, N_CH):
        raise ValueError("Playback frame must have 2 or 8 channels.")
    dev = sd.query_devices(device_index)
    if frame.shape[1] == N_CH:
        if not supports_8ch(device_index):
            raise ValueError(
                f"Endpoint '{dev['name']}' will not accept an 8-channel stream. "
                "Enable 7.1 (or a spatial-sound APO) on this endpoint before starting."
            )
    else:
        try:
            sd.check_output_settings(device=device_index, channels=2,
                                     samplerate=SR, dtype="float32")
        except Exception:
            raise ValueError(
                f"Endpoint '{dev['name']}' will not accept a 2-channel 48000 Hz stream."
            )
    sd.play(frame, samplerate=SR, device=device_index, blocking=True)


def stop():
    sd.stop()


# ---- Self-check -------------------------------------------------------------

def _selfcheck():
    # Constant power everywhere.
    for t in range(-180, 180):
        g = pan_gains(t)
        power = sum(v * v for v in g.values())
        assert abs(power - 1.0) < 1e-6, f"power {power} at {t}"
        assert 1 <= len(g) <= 2, f"{len(g)} speakers at {t}"

    # Exact speaker hits -> single speaker, gain 1.
    for name, az in SPEAKER_AZ.items():
        g = pan_gains(az)
        assert list(g) == [name] and abs(g[name] - 1.0) < 1e-9, f"exact {name} {g}"

    # Midpoint between FC(0) and FR(30) at 15 deg -> equal gains.
    g = pan_gains(15)
    assert abs(g["FC"] - g["FR"]) < 1e-6 and set(g) == {"FC", "FR"}, g

    # Back arc midpoint at 180 -> BR and BL, equal.
    g = pan_gains(180)
    assert set(g) == {"BR", "BL"} and abs(g["BR"] - g["BL"]) < 1e-6, g

    # Frame: LFE always silent.
    frame = pan_to_frame(pink_noise(4800, 1), 45.0, peak_dbfs=-12.0)
    assert np.max(np.abs(frame[:, CH_INDEX["LFE"]])) == 0.0, "LFE not silent"

    # On-speaker target (gain 1) => frame peak equals the configured source peak.
    frame = pan_to_frame(pink_noise(4800, 1), 30.0, peak_dbfs=-12.0)  # FR exactly
    peak = np.max(np.abs(frame))
    assert abs(20 * np.log10(peak) - (-12.0)) < 0.5, f"peak {20*np.log10(peak):.2f} dBFS"

    # FC folds equally to left and right.
    fc = np.zeros((16, N_CH), dtype=np.float32)
    fc[:, CH_INDEX["FC"]] = 0.5
    folded = folddown_71_to_stereo(fc)
    assert np.allclose(folded[:, 0], folded[:, 1]), "FC fold-down not equal"

    # Direct stereo panning is constant-power, with equal gains at the center.
    for az in range(-90, 91):
        left, right = pan_stereo_gains(az)
        assert abs(left * left + right * right - 1.0) < 1e-6, f"stereo power at {az}"
    left, right = pan_stereo_gains(0)
    assert abs(left - right) < 1e-6, "stereo center not equal"

    # All render modes have the required channel count.
    mono = pink_noise(4800, 2)
    assert render_output(mono, 0, -12.0, "bed71").shape == (4800, 8)
    assert render_output(mono, 0, -12.0, "folddown").shape == (4800, 2)
    assert render_output(mono, 0, -12.0, "stereo").shape == (4800, 2)

    # BL folds entirely to the left.
    bl = np.zeros((16, N_CH), dtype=np.float32)
    bl[:, CH_INDEX["BL"]] = 0.5
    folded = folddown_71_to_stereo(bl)
    assert np.max(np.abs(folded[:, 0])) > 0.0
    assert np.max(np.abs(folded[:, 1])) == 0.0

    # Pink noise deterministic given seed.
    assert np.array_equal(pink_noise(1000, 42), pink_noise(1000, 42)), "seed not deterministic"

    # Burst stimulus length: 3x250ms + 2x100ms = 950ms.
    stim = make_stimulus("pink", 7)
    assert abs(len(stim) - int(SR * 0.95)) <= 1, f"stim len {len(stim)}"

    # WAV regions and waveform information.
    tmp_name = "_selfcheck_tmp.wav"
    tmp_path = os.path.join(os.path.dirname(__file__), "stimuli", tmp_name)
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    try:
        samples = (np.sin(2 * np.pi * 440 * np.arange(SR * 2) / SR) * 32767).astype(np.int16)
        with wave.open(tmp_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(samples.tobytes())
        stim = make_stimulus(tmp_name, 0, region=(0.5, 1.0))
        assert len(stim) == 24000, f"region len {len(stim)}"
        info = wav_info(tmp_name)
        assert abs(info["duration"] - 2.0) < 1e-6, info["duration"]
        assert len(info["peaks"]) == 600, len(info["peaks"])
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    print("audio.py selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
