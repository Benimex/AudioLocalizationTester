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

CMAA_LOW = (200.0, 1200.0)
CMAA_HIGH = (2000.0, 8000.0)


def _norm180(a):
    """Normalize angle to [-180, 180)."""
    return ((a + 180.0) % 360.0) - 180.0


# Speakers sorted by azimuth; back arc (BR->BL) wraps across +-180.
_SORTED = sorted(SPEAKER_AZ.items(), key=lambda kv: kv[1])


def pan_gains(target_az, eps=1e-9):
    """Constant-power pairwise (2D VBAP) gains for a horizontal target azimuth."""
    t = _norm180(target_az)

    for name, az in SPEAKER_AZ.items():
        if abs(_norm180(t - az)) < 1e-6:
            return {name: 1.0}

    names = [n for n, _ in _SORTED]
    azs = [a for _, a in _SORTED]

    for i in range(len(azs) - 1):
        a, b = azs[i], azs[i + 1]
        if a <= t <= b:
            p = (t - a) / (b - a)
            return {names[i]: np.cos(p * np.pi / 2),
                    names[i + 1]: np.sin(p * np.pi / 2)}

    a_name, a = names[-1], azs[-1]
    b_name, b = names[0], azs[0] + 360.0
    tt = t if t >= a else t + 360.0
    p = (tt - a) / (b - a)
    return {a_name: np.cos(p * np.pi / 2), b_name: np.sin(p * np.pi / 2)}


def pan_to_frame(mono, target_az, peak_dbfs=-12.0):
    """Expand a mono signal to an 8ch frame panned to target_az."""
    mono = np.asarray(mono, dtype=np.float32)
    peak = np.max(np.abs(mono)) or 1.0
    target_peak = 10.0 ** (peak_dbfs / 20.0)
    mono = mono * (target_peak / peak)

    frame = np.zeros((len(mono), N_CH), dtype=np.float32)
    for name, gain in pan_gains(target_az).items():
        frame[:, CH_INDEX[name]] += mono * float(gain)
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
    """Apply a raised-cosine fade in/out to avoid clicks."""
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
    """Pink noise via FFT filtering. Deterministic given seed."""
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    freqs[0] = freqs[1] if len(freqs) > 1 else 1.0
    spec = spec / np.sqrt(freqs)
    out = np.fft.irfft(spec, n).astype(np.float32)
    out /= (np.max(np.abs(out)) or 1.0)
    return out


def band_noise(seed, lo_hz, hi_hz, dur_ms=500.0):
    """Create a deterministic pink-noise token band-limited in the FFT domain."""
    lo_hz = float(lo_hz)
    hi_hz = float(hi_hz)
    if lo_hz < 0.0 or hi_hz <= lo_hz or hi_hz > SR / 2:
        raise ValueError("Invalid band limits.")
    n = int(SR * float(dur_ms) / 1000.0)
    if n <= 0:
        raise ValueError("dur_ms must be positive.")

    token = pink_noise(n, int(seed))
    spectrum = np.fft.rfft(token)
    frequencies = np.fft.rfftfreq(n, 1.0 / SR)
    spectrum[(frequencies < lo_hz) | (frequencies > hi_hz)] = 0.0
    out = np.fft.irfft(spectrum, n).astype(np.float32)
    out /= (np.max(np.abs(out)) or 1.0)
    return _raised_cosine_ramp(out, 10.0)


def render_cmaa(ref_az, delta_deg, high_side, peak_dbfs, mode, seed):
    """Render simultaneous low- and high-band sources separated in azimuth."""
    delta = float(delta_deg)
    side = int(high_side)
    if delta <= 0.0:
        raise ValueError("delta_deg must be positive.")
    if side not in (-1, 1):
        raise ValueError("high_side must be -1 or +1.")

    low_az = float(ref_az) - side * delta / 2.0
    high_az = float(ref_az) + side * delta / 2.0
    low = band_noise(int(seed), *CMAA_LOW)
    high = band_noise(int(seed) + 1, *CMAA_HIGH)
    low_frame = render_output(low, low_az, 0.0, mode)
    high_frame = render_output(high, high_az, 0.0, mode)
    mixed = low_frame + high_frame

    peak = np.max(np.abs(mixed)) if mixed.size else 0.0
    if peak > 0.0:
        mixed *= 10.0 ** (float(peak_dbfs) / 20.0) / peak
    return mixed.astype(np.float32)


def burst_stimulus(source_mono, gap_ms=100.0, n_bursts=3):
    """Wrap a per-burst mono source into bursts with silent gaps."""
    gap = np.zeros(int(SR * gap_ms / 1000.0), dtype=np.float32)
    one = _raised_cosine_ramp(np.asarray(source_mono, dtype=np.float32))
    parts = []
    for i in range(n_bursts):
        parts.append(one)
        if i < n_bursts - 1:
            parts.append(gap)
    return np.concatenate(parts)


def make_stimulus(kind, seed, burst_ms=250.0, region=None):
    """Build a mono pink-noise or WAV stimulus token."""
    if kind == "pink":
        per = pink_noise(int(SR * burst_ms / 1000.0), seed)
        return burst_stimulus(per)
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


def render_spec(spec, seed):
    """Render a generic stimulus specification for listening tests."""
    stimulus = spec.get("stimulus", "pink")
    output_mode = spec.get("output_mode", "folddown")
    az = float(spec.get("az", 0.0))
    peak_dbfs = float(spec.get("peak_dbfs", -12.0))
    region = spec.get("region")
    region = tuple(region) if region is not None else None
    spread = spec.get("spread")

    if spread is None:
        mono = make_stimulus(stimulus, seed, region=region)
        return render_output(mono, az, peak_dbfs, output_mode)

    spread = float(spread)
    if spread <= 0.0:
        raise ValueError("spread must be positive.")

    left = make_stimulus(stimulus, seed, region=region)
    right = make_stimulus(stimulus, seed + 1, region=region)
    left_frame = render_output(
        left, az - spread / 2.0, peak_dbfs, output_mode
    )
    right_frame = render_output(
        right, az + spread / 2.0, peak_dbfs, output_mode
    )
    mixed = left_frame + right_frame

    peak = np.max(np.abs(mixed)) if mixed.size else 0.0
    if peak > 0.0:
        mixed *= 10.0 ** (peak_dbfs / 20.0) / peak
    return mixed.astype(np.float32)


def load_wav(name):
    """Load a mono 48kHz 16-bit PCM WAV from stimuli/."""
    path = os.path.join(os.path.dirname(__file__), "stimuli", name)
    with wave.open(path, "rb") as w:
        if w.getframerate() != SR:
            raise ValueError(f"{name}: {w.getframerate()} Hz, need 48000. Convert first.")
        if w.getnchannels() != 1:
            raise ValueError(f"{name}: {w.getnchannels()} channels, need mono. Convert first.")
        if w.getsampwidth() != 2:
            raise ValueError(f"{name}: {w.getsampwidth()*8}-bit, need 16-bit PCM. Convert first.")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


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
    """WAV files available in stimuli/, plus built-in pink noise."""
    directory = os.path.join(os.path.dirname(__file__), "stimuli")
    wavs = []
    if os.path.isdir(directory):
        wavs = sorted(f for f in os.listdir(directory) if f.lower().endswith(".wav"))
    return ["pink"] + wavs


# ---- Device enumeration / playback ------------------------------------------

def supports_8ch(device_index):
    """True if an 8ch/48k stream can be opened on this endpoint."""
    try:
        sd.check_output_settings(device=device_index, channels=N_CH,
                                 samplerate=SR, dtype="float32")
        return True
    except Exception:
        return False


def list_output_devices():
    """Return WASAPI output endpoints and their channel capabilities."""
    devices = sd.query_devices()
    try:
        wasapi = sd.query_hostapis(_wasapi_index())
        valid = set(wasapi["devices"])
    except Exception:
        valid = None
    out = []
    for i, device in enumerate(devices):
        if device["max_output_channels"] < 1:
            continue
        if valid is not None and i not in valid:
            continue
        out.append({
            "index": i,
            "name": device["name"],
            "channels": device["max_output_channels"],
            "supports_8ch": supports_8ch(i),
        })
    return out


def _wasapi_index():
    for i, host_api in enumerate(sd.query_hostapis()):
        if "WASAPI" in host_api["name"]:
            return i
    raise RuntimeError("No WASAPI host API found")


def play_frame(frame, device_index):
    """Blocking playback of an 8ch or 2ch frame to a WASAPI endpoint."""
    frame = np.asarray(frame, dtype=np.float32)
    if frame.ndim != 2 or frame.shape[1] not in (2, N_CH):
        raise ValueError("Playback frame must have 2 or 8 channels.")
    device = sd.query_devices(device_index)
    if frame.shape[1] == N_CH:
        if not supports_8ch(device_index):
            raise ValueError(
                f"Endpoint '{device['name']}' will not accept an 8-channel stream. "
                "Enable 7.1 (or a spatial-sound APO) on this endpoint before starting."
            )
    else:
        try:
            sd.check_output_settings(device=device_index, channels=2,
                                     samplerate=SR, dtype="float32")
        except Exception:
            raise ValueError(
                f"Endpoint '{device['name']}' will not accept a 2-channel 48000 Hz stream."
            )
    sd.play(frame, samplerate=SR, device=device_index, blocking=True)


def stop():
    sd.stop()


# ---- Self-check -------------------------------------------------------------

def _selfcheck():
    for target in range(-180, 180):
        gains = pan_gains(target)
        power = sum(value * value for value in gains.values())
        assert abs(power - 1.0) < 1e-6, f"power {power} at {target}"
        assert 1 <= len(gains) <= 2, f"{len(gains)} speakers at {target}"

    for name, azimuth in SPEAKER_AZ.items():
        gains = pan_gains(azimuth)
        assert list(gains) == [name] and abs(gains[name] - 1.0) < 1e-9

    gains = pan_gains(15)
    assert abs(gains["FC"] - gains["FR"]) < 1e-6 and set(gains) == {"FC", "FR"}

    gains = pan_gains(180)
    assert set(gains) == {"BR", "BL"} and abs(gains["BR"] - gains["BL"]) < 1e-6

    frame = pan_to_frame(pink_noise(4800, 1), 45.0, peak_dbfs=-12.0)
    assert np.max(np.abs(frame[:, CH_INDEX["LFE"]])) == 0.0

    frame = pan_to_frame(pink_noise(4800, 1), 30.0, peak_dbfs=-12.0)
    peak = np.max(np.abs(frame))
    assert abs(20 * np.log10(peak) - (-12.0)) < 0.5

    fc = np.zeros((16, N_CH), dtype=np.float32)
    fc[:, CH_INDEX["FC"]] = 0.5
    folded = folddown_71_to_stereo(fc)
    assert np.allclose(folded[:, 0], folded[:, 1])

    for azimuth in range(-90, 91):
        left, right = pan_stereo_gains(azimuth)
        assert abs(left * left + right * right - 1.0) < 1e-6
    left, right = pan_stereo_gains(0)
    assert abs(left - right) < 1e-6

    mono = pink_noise(4800, 2)
    assert render_output(mono, 0, -12.0, "bed71").shape == (4800, 8)
    assert render_output(mono, 0, -12.0, "folddown").shape == (4800, 2)
    assert render_output(mono, 0, -12.0, "stereo").shape == (4800, 2)

    bl = np.zeros((16, N_CH), dtype=np.float32)
    bl[:, CH_INDEX["BL"]] = 0.5
    folded = folddown_71_to_stereo(bl)
    assert np.max(np.abs(folded[:, 0])) > 0.0
    assert np.max(np.abs(folded[:, 1])) == 0.0

    assert np.array_equal(pink_noise(1000, 42), pink_noise(1000, 42))

    stim = make_stimulus("pink", 7)
    assert abs(len(stim) - int(SR * 0.95)) <= 1

    low_a = band_noise(3, 200, 1200)
    low_b = band_noise(3, 200, 1200)
    assert len(low_a) == 24000
    assert np.array_equal(low_a, low_b)

    cmaa_folded = render_cmaa(0, 20, 1, -12, "folddown", 5)
    cmaa_bed = render_cmaa(0, 20, 1, -12, "bed71", 5)
    assert cmaa_folded.shape[1] == 2
    assert cmaa_bed.shape[1] == 8
    mix_peak = np.max(np.abs(cmaa_folded))
    assert abs(20 * np.log10(mix_peak) - (-12.0)) < 0.5

    assert render_spec({}, 1).shape[1] == 2
    assert render_spec({"output_mode": "bed71"}, 1).shape[1] == 8
    spread_mix = render_spec({"spread": 40.0}, 2)
    assert spread_mix.shape[1] == 2
    mix_peak = np.max(np.abs(spread_mix))
    assert abs(20 * np.log10(mix_peak) - (-12.0)) < 0.5
    assert render_spec({"spread": 40.0, "output_mode": "stereo"}, 3).shape[1] == 2
    assert np.array_equal(render_spec({}, 5), render_spec({}, 5))

    high = band_noise(6, *CMAA_HIGH)
    high_frame = pan_to_stereo(high, 10.0, -12.0)
    left_energy = np.sum(high_frame[:, 0] ** 2)
    right_energy = np.sum(high_frame[:, 1] ** 2)
    assert right_energy > left_energy

    tmp_name = "_selfcheck_tmp.wav"
    tmp_path = os.path.join(os.path.dirname(__file__), "stimuli", tmp_name)
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    try:
        samples = (np.sin(2 * np.pi * 440 * np.arange(SR * 2) / SR) * 32767).astype(np.int16)
        with wave.open(tmp_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SR)
            wav.writeframes(samples.tobytes())
        stim = make_stimulus(tmp_name, 0, region=(0.5, 1.0))
        assert len(stim) == 24000
        info = wav_info(tmp_name)
        assert abs(info["duration"] - 2.0) < 1e-6
        assert len(info["peaks"]) == 600
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    print("audio.py selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
