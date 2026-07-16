"""Audio engine: panning, stimulus generation, parametric EQ, and playback."""
import os
import re
import wave

import numpy as np
import sounddevice as sd
from scipy.signal import sosfilt

SR = 48000
EQ_DIR = os.path.join(os.path.dirname(__file__), "eq")

CH_INDEX = {
    "FL": 0, "FR": 1, "FC": 2, "LFE": 3,
    "BL": 4, "BR": 5, "SL": 6, "SR": 7,
}
N_CH = 8
SPEAKER_AZ = {
    "FC": 0, "FR": 30, "SR": 90, "BR": 135,
    "BL": -135, "SL": -90, "FL": -30,
}
CMAA_LOW = (200.0, 1200.0)
CMAA_HIGH = (2000.0, 8000.0)

_SORTED = sorted(SPEAKER_AZ.items(), key=lambda item: item[1])

_PREAMP_RE = re.compile(
    r"^\s*Preamp\s*:\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*dB\s*$",
    re.IGNORECASE,
)
_FILTER_RE = re.compile(
    r"^\s*Filter\s+\d+\s*:\s*ON\s+"
    r"(PK|LSC|HSC|LS|HS)\s+Fc\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*Hz\s+"
    r"Gain\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*dB"
    r"(?:\s+Q\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?))?\s*$",
    re.IGNORECASE,
)


def _norm180(angle):
    """Normalize an angle to [-180, 180)."""
    return ((angle + 180.0) % 360.0) - 180.0


def pan_gains(target_az, eps=1e-9):
    """Return constant-power pairwise gains for a horizontal azimuth."""
    target = _norm180(target_az)

    for name, azimuth in SPEAKER_AZ.items():
        if abs(_norm180(target - azimuth)) < 1e-6:
            return {name: 1.0}

    names = [name for name, _ in _SORTED]
    azimuths = [azimuth for _, azimuth in _SORTED]

    for index in range(len(azimuths) - 1):
        left_az = azimuths[index]
        right_az = azimuths[index + 1]
        if left_az <= target <= right_az:
            position = (target - left_az) / (right_az - left_az)
            return {
                names[index]: np.cos(position * np.pi / 2.0),
                names[index + 1]: np.sin(position * np.pi / 2.0),
            }

    left_name = names[-1]
    left_az = azimuths[-1]
    right_name = names[0]
    right_az = azimuths[0] + 360.0
    wrapped_target = target if target >= left_az else target + 360.0
    position = (wrapped_target - left_az) / (right_az - left_az)
    return {
        left_name: np.cos(position * np.pi / 2.0),
        right_name: np.sin(position * np.pi / 2.0),
    }


def _normalize_peak(mono, peak_dbfs):
    mono = np.asarray(mono, dtype=np.float32)
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if peak <= 0.0:
        return mono.copy()
    target = 10.0 ** (float(peak_dbfs) / 20.0)
    return (mono * (target / peak)).astype(np.float32)


def _normalize_rms(mono, peak_dbfs):
    mono = np.asarray(mono, dtype=np.float32)
    rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64)))) if mono.size else 0.0
    if rms <= 0.0:
        return mono.copy()

    target_rms = 10.0 ** ((float(peak_dbfs) - 8.0) / 20.0)
    normalized = mono * (target_rms / rms)
    peak = float(np.max(np.abs(normalized))) if normalized.size else 0.0
    if peak > 0.98:
        normalized *= 0.98 / peak
    return normalized.astype(np.float32)


def pan_to_frame(mono, target_az, peak_dbfs=-12.0, pre_normalized=False):
    """Expand mono audio into an eight-channel 7.1 frame."""
    mono = np.asarray(mono, dtype=np.float32)
    if not pre_normalized:
        mono = _normalize_peak(mono, peak_dbfs)

    frame = np.zeros((len(mono), N_CH), dtype=np.float32)
    for name, gain in pan_gains(target_az).items():
        frame[:, CH_INDEX[name]] += mono * float(gain)
    return frame


def folddown_71_to_stereo(frame8):
    """Fold FL FR FC LFE BL BR SL SR down to stereo, dropping LFE."""
    frame8 = np.asarray(frame8, dtype=np.float32)
    if frame8.ndim != 2 or frame8.shape[1] != N_CH:
        raise ValueError("7.1 fold-down requires an (n, 8) frame.")

    stereo = np.empty((len(frame8), 2), dtype=np.float32)
    stereo[:, 0] = (
        frame8[:, CH_INDEX["FL"]]
        + 0.7071 * frame8[:, CH_INDEX["FC"]]
        + 0.7071 * frame8[:, CH_INDEX["SL"]]
        + 0.7071 * frame8[:, CH_INDEX["BL"]]
    )
    stereo[:, 1] = (
        frame8[:, CH_INDEX["FR"]]
        + 0.7071 * frame8[:, CH_INDEX["FC"]]
        + 0.7071 * frame8[:, CH_INDEX["SR"]]
        + 0.7071 * frame8[:, CH_INDEX["BR"]]
    )

    source_peak = float(np.max(np.abs(frame8))) if frame8.size else 0.0
    stereo_peak = float(np.max(np.abs(stereo))) if stereo.size else 0.0
    if stereo_peak > 0.0:
        stereo *= source_peak / stereo_peak
    return stereo


def pan_stereo_gains(az):
    """Return constant-power stereo gains for the front arc."""
    az = np.clip(float(az), -90.0, 90.0)
    position = (az + 90.0) / 180.0
    return np.cos(position * np.pi / 2.0), np.sin(position * np.pi / 2.0)


def pan_to_stereo(mono, az, peak_dbfs=-12.0, pre_normalized=False):
    """Expand mono audio into a constant-power stereo frame."""
    mono = np.asarray(mono, dtype=np.float32)
    if not pre_normalized:
        mono = _normalize_peak(mono, peak_dbfs)

    left, right = pan_stereo_gains(az)
    frame = np.empty((len(mono), 2), dtype=np.float32)
    frame[:, 0] = mono * float(left)
    frame[:, 1] = mono * float(right)
    return frame


def render_output(mono, az, peak_dbfs=-12.0, mode="bed71",
                  pre_normalized=False):
    """Render mono audio to a 7.1 bed, folded stereo, or direct stereo."""
    if mode == "bed71":
        return pan_to_frame(mono, az, peak_dbfs, pre_normalized)
    if mode == "folddown":
        frame = pan_to_frame(mono, az, peak_dbfs, pre_normalized)
        return folddown_71_to_stereo(frame)
    if mode == "stereo":
        return pan_to_stereo(mono, az, peak_dbfs, pre_normalized)
    raise ValueError(f"Unknown output mode '{mode}'.")


def list_eqs():
    """Return sorted EQ APO text filenames from eq/."""
    if not os.path.isdir(EQ_DIR):
        return []
    return sorted(
        name for name in os.listdir(EQ_DIR)
        if name.lower().endswith(".txt")
        and os.path.isfile(os.path.join(EQ_DIR, name))
    )


def parse_eqapo(name):
    """Parse an Equalizer APO/AutoEq text file."""
    path = os.path.join(EQ_DIR, name)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
    except (OSError, TypeError) as exc:
        raise ValueError(f"Unable to read EQ file '{name}'.") from exc

    preamp = 0.0
    filters = []

    for line in lines:
        preamp_match = _PREAMP_RE.match(line)
        if preamp_match:
            preamp = float(preamp_match.group(1))
            continue

        filter_match = _FILTER_RE.match(line)
        if not filter_match:
            continue

        raw_type, fc_text, gain_text, q_text = filter_match.groups()
        raw_type = raw_type.upper()
        if raw_type in ("LS", "LSC"):
            filter_type = "LS"
        elif raw_type in ("HS", "HSC"):
            filter_type = "HS"
        else:
            filter_type = "PK"

        q = float(q_text) if q_text is not None else 0.707
        fc = float(fc_text)
        gain = float(gain_text)
        if not np.isfinite(fc) or not np.isfinite(gain) or not np.isfinite(q):
            continue
        if fc <= 0.0 or fc >= SR / 2.0 or q <= 0.0:
            continue

        filters.append({
            "type": filter_type,
            "fc": fc,
            "gain": gain,
            "q": q,
        })

    if not filters and preamp == 0.0:
        raise ValueError(f"EQ file '{name}' contains no valid EQ settings.")
    return {"preamp": float(preamp), "filters": filters}


def _biquad_sos(ftype, fc, gain_db, q, fs=SR):
    """Return one normalized RBJ audio-EQ-cookbook SOS row."""
    filter_type = str(ftype).upper()
    frequency = float(fc)
    gain_db = float(gain_db)
    q = float(q)
    fs = float(fs)

    if filter_type not in ("PK", "LS", "HS"):
        raise ValueError(f"Unsupported filter type '{ftype}'.")
    if frequency <= 0.0 or frequency >= fs / 2.0:
        raise ValueError("Filter frequency must be between 0 and Nyquist.")
    if q <= 0.0:
        raise ValueError("Filter Q must be positive.")

    amplitude = 10.0 ** (gain_db / 40.0)
    omega = 2.0 * np.pi * frequency / fs
    cosine = np.cos(omega)
    sine = np.sin(omega)

    if filter_type == "PK":
        alpha = sine / (2.0 * q)
        b0 = 1.0 + alpha * amplitude
        b1 = -2.0 * cosine
        b2 = 1.0 - alpha * amplitude
        a0 = 1.0 + alpha / amplitude
        a1 = -2.0 * cosine
        a2 = 1.0 - alpha / amplitude
    else:
        slope = q
        alpha = sine / 2.0 * np.sqrt(
            (amplitude + 1.0 / amplitude) * (1.0 / slope - 1.0) + 2.0
        )
        root_amplitude_alpha = 2.0 * np.sqrt(amplitude) * alpha

        if filter_type == "LS":
            b0 = amplitude * (
                (amplitude + 1.0)
                - (amplitude - 1.0) * cosine
                + root_amplitude_alpha
            )
            b1 = 2.0 * amplitude * (
                (amplitude - 1.0) - (amplitude + 1.0) * cosine
            )
            b2 = amplitude * (
                (amplitude + 1.0)
                - (amplitude - 1.0) * cosine
                - root_amplitude_alpha
            )
            a0 = (
                (amplitude + 1.0)
                + (amplitude - 1.0) * cosine
                + root_amplitude_alpha
            )
            a1 = -2.0 * (
                (amplitude - 1.0) + (amplitude + 1.0) * cosine
            )
            a2 = (
                (amplitude + 1.0)
                + (amplitude - 1.0) * cosine
                - root_amplitude_alpha
            )
        else:
            b0 = amplitude * (
                (amplitude + 1.0)
                + (amplitude - 1.0) * cosine
                + root_amplitude_alpha
            )
            b1 = -2.0 * amplitude * (
                (amplitude - 1.0) + (amplitude + 1.0) * cosine
            )
            b2 = amplitude * (
                (amplitude + 1.0)
                + (amplitude - 1.0) * cosine
                - root_amplitude_alpha
            )
            a0 = (
                (amplitude + 1.0)
                - (amplitude - 1.0) * cosine
                + root_amplitude_alpha
            )
            a1 = 2.0 * (
                (amplitude - 1.0) - (amplitude + 1.0) * cosine
            )
            a2 = (
                (amplitude + 1.0)
                - (amplitude - 1.0) * cosine
                - root_amplitude_alpha
            )

    return np.asarray(
        [b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0],
        dtype=np.float64,
    )


def apply_eq(mono, eq):
    """Apply parsed parametric EQ and preamp gain to mono audio."""
    mono = np.asarray(mono, dtype=np.float32)
    if eq is None:
        return mono

    filters = eq.get("filters", [])
    if filters:
        sos = np.vstack([
            _biquad_sos(
                item["type"], item["fc"], item["gain"], item.get("q", 0.707)
            )
            for item in filters
        ])
        output = sosfilt(sos, mono).astype(np.float32)
    else:
        output = mono.copy()

    output *= np.float32(10.0 ** (float(eq.get("preamp", 0.0)) / 20.0))
    return output.astype(np.float32)


def _raised_cosine_ramp(sig, ms=10.0):
    """Apply a raised-cosine fade-in and fade-out."""
    sig = np.asarray(sig, dtype=np.float32).copy()
    count = int(SR * ms / 1000.0)
    if count * 2 > len(sig):
        count = len(sig) // 2
    if count == 0:
        return sig

    ramp = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, count)))
    sig[:count] *= ramp
    sig[-count:] *= ramp[::-1]
    return sig


def pink_noise(n, seed):
    """Generate deterministic pink noise using FFT filtering."""
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    spectrum = np.fft.rfft(white)
    frequencies = np.fft.rfftfreq(n, 1.0 / SR)
    frequencies[0] = frequencies[1] if len(frequencies) > 1 else 1.0
    spectrum /= np.sqrt(frequencies)
    output = np.fft.irfft(spectrum, n).astype(np.float32)
    output /= np.max(np.abs(output)) or 1.0
    return output


def band_noise(seed, lo_hz, hi_hz, dur_ms=500.0):
    """Generate deterministic FFT-band-limited pink noise."""
    lo_hz = float(lo_hz)
    hi_hz = float(hi_hz)
    if lo_hz < 0.0 or hi_hz <= lo_hz or hi_hz > SR / 2.0:
        raise ValueError("Invalid band limits.")

    count = int(SR * float(dur_ms) / 1000.0)
    if count <= 0:
        raise ValueError("dur_ms must be positive.")

    token = pink_noise(count, int(seed))
    spectrum = np.fft.rfft(token)
    frequencies = np.fft.rfftfreq(count, 1.0 / SR)
    spectrum[(frequencies < lo_hz) | (frequencies > hi_hz)] = 0.0
    output = np.fft.irfft(spectrum, count).astype(np.float32)
    output /= np.max(np.abs(output)) or 1.0
    return _raised_cosine_ramp(output)


def _cmaa_token(kind, seed_for_side):
    """Build one CMAA source token."""
    if kind == "band-low":
        return band_noise(seed_for_side, *CMAA_LOW)
    if kind == "band-high":
        return band_noise(seed_for_side, *CMAA_HIGH)
    if kind.lower().endswith(".wav"):
        return make_stimulus(kind, seed_for_side)
    raise ValueError(f"Unknown CMAA stimulus '{kind}'.")


def render_cmaa(ref_az, delta_deg, high_side, peak_dbfs, mode, seed,
                stim_a="band-low", stim_b="band-high"):
    """Render simultaneous distinguishable sources separated in azimuth."""
    delta = float(delta_deg)
    side = int(high_side)
    if delta <= 0.0:
        raise ValueError("delta_deg must be positive.")
    if side not in (-1, 1):
        raise ValueError("high_side must be -1 or +1.")

    a_az = float(ref_az) - side * delta / 2.0
    b_az = float(ref_az) + side * delta / 2.0
    token_a = _cmaa_token(stim_a, int(seed))
    token_b = _cmaa_token(stim_b, int(seed) + 1)

    count = min(len(token_a), len(token_b), SR)
    token_a = _raised_cosine_ramp(token_a[:count])
    token_b = _raised_cosine_ramp(token_b[:count])

    a_frame = render_output(token_a, a_az, 0.0, mode)
    b_frame = render_output(token_b, b_az, 0.0, mode)
    mixed = a_frame + b_frame

    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    if peak > 0.0:
        mixed *= 10.0 ** (float(peak_dbfs) / 20.0) / peak
    return mixed.astype(np.float32)


def burst_stimulus(source_mono, gap_ms=100.0, n_bursts=3):
    """Wrap a mono source in bursts separated by silence."""
    gap = np.zeros(int(SR * gap_ms / 1000.0), dtype=np.float32)
    burst = _raised_cosine_ramp(source_mono)
    parts = []
    for index in range(n_bursts):
        parts.append(burst)
        if index < n_bursts - 1:
            parts.append(gap)
    return np.concatenate(parts)


def make_stimulus(kind, seed, burst_ms=250.0, region=None):
    """Build a mono pink-noise or WAV stimulus token."""
    if kind == "pink":
        burst = pink_noise(int(SR * burst_ms / 1000.0), seed)
        return burst_stimulus(burst)

    mono = load_wav(kind)
    if region is not None and len(region) == 2:
        start_sec, end_sec = float(region[0]), float(region[1])
        if end_sec > start_sec:
            start = max(0, min(len(mono), int(start_sec * SR)))
            end = max(0, min(len(mono), int(end_sec * SR)))
            mono = mono[start:end]
            if len(mono) < int(SR * 0.03):
                raise ValueError("Region too short.")
    return _raised_cosine_ramp(mono)


def _prepare_spec_token(stimulus, seed, region, eq, level_mode, peak_dbfs):
    mono = make_stimulus(stimulus, seed, region=region)
    mono = apply_eq(mono, eq)
    if level_mode == "peak":
        return _normalize_peak(mono, peak_dbfs)
    if level_mode == "rms":
        return _normalize_rms(mono, peak_dbfs)
    raise ValueError("level_mode must be 'peak' or 'rms'.")


def render_spec(spec, seed):
    """Render a generic stimulus specification for listening tests."""
    stimulus = spec.get("stimulus", "pink")
    output_mode = spec.get("output_mode", "folddown")
    az = float(spec.get("az", 0.0))
    peak_dbfs = float(spec.get("peak_dbfs", -12.0))
    region = spec.get("region")
    region = tuple(region) if region is not None else None
    spread = spec.get("spread")
    level_mode = str(spec.get("level_mode", "peak")).lower()
    eq_name = spec.get("eq")
    eq = parse_eqapo(eq_name) if eq_name else None

    if spread is None:
        mono = _prepare_spec_token(
            stimulus, seed, region, eq, level_mode, peak_dbfs
        )
        return render_output(
            mono, az, 0.0, output_mode, pre_normalized=True
        ).astype(np.float32)

    spread = float(spread)
    if spread <= 0.0:
        raise ValueError("spread must be positive.")

    left = _prepare_spec_token(
        stimulus, seed, region, eq, level_mode, peak_dbfs
    )
    right = _prepare_spec_token(
        stimulus, seed + 1, region, eq, level_mode, peak_dbfs
    )
    left_frame = render_output(
        left, az - spread / 2.0, 0.0, output_mode, pre_normalized=True
    )
    right_frame = render_output(
        right, az + spread / 2.0, 0.0, output_mode, pre_normalized=True
    )
    mixed = left_frame + right_frame

    if level_mode == "peak":
        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        if peak > 0.0:
            mixed *= 10.0 ** (peak_dbfs / 20.0) / peak
    else:
        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        if peak > 0.98:
            mixed *= 0.98 / peak
    return mixed.astype(np.float32)


def _fit_length_loop(token, count):
    token = np.asarray(token, dtype=np.float32)
    if len(token) == 0:
        return np.zeros(count, dtype=np.float32)
    if len(token) >= count:
        return token[:count].copy()
    repeats = int(np.ceil(count / len(token)))
    return np.tile(token, repeats)[:count].astype(np.float32)


def render_masked(has_target, masker_stim, masker_dbfs, target_stim,
                  target_dbfs, masker_az, target_az, mode, seed):
    """Render a 1.5-second masker with an optional embedded target."""
    total_count = int(1.5 * SR)
    masker = make_stimulus(masker_stim, int(seed))
    masker = _fit_length_loop(masker, total_count)
    masker = _raised_cosine_ramp(masker)
    masker = _normalize_peak(masker, masker_dbfs)
    frame = render_output(
        masker, masker_az, 0.0, mode, pre_normalized=True
    )

    if has_target:
        target = make_stimulus(target_stim, int(seed) + 1)
        target = target[:int(0.8 * SR)]
        target = _raised_cosine_ramp(target)
        target = _normalize_peak(target, target_dbfs)
        target_frame = render_output(
            target, target_az, 0.0, mode, pre_normalized=True
        )
        start = int(0.4 * SR)
        available = min(len(target_frame), len(frame) - start)
        if available > 0:
            frame[start:start + available] += target_frame[:available]

    return np.clip(frame, -0.99, 0.99).astype(np.float32)


def load_wav(name):
    """Load a mono 48-kHz 16-bit PCM WAV from stimuli/."""
    path = os.path.join(os.path.dirname(__file__), "stimuli", name)
    with wave.open(path, "rb") as wav:
        if wav.getframerate() != SR:
            raise ValueError(
                f"{name}: {wav.getframerate()} Hz, need 48000. Convert first."
            )
        if wav.getnchannels() != 1:
            raise ValueError(
                f"{name}: {wav.getnchannels()} channels, need mono. Convert first."
            )
        if wav.getsampwidth() != 2:
            raise ValueError(
                f"{name}: {wav.getsampwidth() * 8}-bit, "
                "need 16-bit PCM. Convert first."
            )
        frames = wav.readframes(wav.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def wav_info(name):
    """Return duration and a compact 600-bin peak overview."""
    mono = load_wav(name)
    count = len(mono)
    peaks = []
    for index in range(600):
        start = index * count // 600
        end = (index + 1) * count // 600
        peak = float(np.max(np.abs(mono[start:end]))) if end > start else 0.0
        peaks.append(round(peak, 3))
    return {"duration": count / SR, "peaks": peaks}


def list_stimuli():
    """Return WAV files available in stimuli/, plus built-in pink noise."""
    directory = os.path.join(os.path.dirname(__file__), "stimuli")
    wavs = []
    if os.path.isdir(directory):
        wavs = sorted(
            name for name in os.listdir(directory)
            if name.lower().endswith(".wav")
        )
    return ["pink"] + wavs


def supports_8ch(device_index):
    """Return whether an endpoint accepts an eight-channel 48-kHz stream."""
    try:
        sd.check_output_settings(
            device=device_index, channels=N_CH,
            samplerate=SR, dtype="float32",
        )
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

    output = []
    for index, device in enumerate(devices):
        if device["max_output_channels"] < 1:
            continue
        if valid is not None and index not in valid:
            continue
        output.append({
            "index": index,
            "name": device["name"],
            "channels": device["max_output_channels"],
            "supports_8ch": supports_8ch(index),
        })
    return output


def _wasapi_index():
    for index, host_api in enumerate(sd.query_hostapis()):
        if "WASAPI" in host_api["name"]:
            return index
    raise RuntimeError("No WASAPI host API found")


def play_frame(frame, device_index):
    """Play an eight-channel or stereo frame through a WASAPI endpoint."""
    frame = np.asarray(frame, dtype=np.float32)
    if frame.ndim != 2 or frame.shape[1] not in (2, N_CH):
        raise ValueError("Playback frame must have 2 or 8 channels.")

    device = sd.query_devices(device_index)
    if frame.shape[1] == N_CH:
        if not supports_8ch(device_index):
            raise ValueError(
                f"Endpoint '{device['name']}' will not accept an 8-channel "
                "stream. Enable 7.1 (or a spatial-sound APO) on this endpoint "
                "before starting."
            )
    else:
        try:
            sd.check_output_settings(
                device=device_index, channels=2,
                samplerate=SR, dtype="float32",
            )
        except Exception as exc:
            raise ValueError(
                f"Endpoint '{device['name']}' will not accept a "
                "2-channel 48000 Hz stream."
            ) from exc

    sd.play(
        frame, samplerate=SR, device=device_index, blocking=True
    )


def stop():
    sd.stop()


def _selfcheck():
    for target in range(-180, 180):
        gains = pan_gains(target)
        power = sum(value * value for value in gains.values())
        assert abs(power - 1.0) < 1e-6
        assert 1 <= len(gains) <= 2

    for name, azimuth in SPEAKER_AZ.items():
        gains = pan_gains(azimuth)
        assert list(gains) == [name]
        assert abs(gains[name] - 1.0) < 1e-9

    gains = pan_gains(15)
    assert set(gains) == {"FC", "FR"}
    assert abs(gains["FC"] - gains["FR"]) < 1e-6

    gains = pan_gains(180)
    assert set(gains) == {"BR", "BL"}
    assert abs(gains["BR"] - gains["BL"]) < 1e-6

    frame = pan_to_frame(pink_noise(4800, 1), 45.0, -12.0)
    assert np.max(np.abs(frame[:, CH_INDEX["LFE"]])) == 0.0

    frame = pan_to_frame(pink_noise(4800, 1), 30.0, -12.0)
    peak = np.max(np.abs(frame))
    assert abs(20.0 * np.log10(peak) + 12.0) < 0.5

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
    assert abs(len(make_stimulus("pink", 7)) - int(SR * 0.95)) <= 1

    low_a = band_noise(3, 200, 1200)
    low_b = band_noise(3, 200, 1200)
    assert len(low_a) == 24000
    assert np.array_equal(low_a, low_b)

    cmaa_folded = render_cmaa(0, 20, 1, -12, "folddown", 5)
    cmaa_bed = render_cmaa(0, 20, 1, -12, "bed71", 5)
    assert cmaa_folded.shape[1] == 2
    assert cmaa_bed.shape[1] == 8
    assert abs(
        20.0 * np.log10(np.max(np.abs(cmaa_folded))) + 12.0
    ) < 0.5

    assert render_spec({}, 1).shape[1] == 2
    assert render_spec({"output_mode": "bed71"}, 1).shape[1] == 8

    spread_mix = render_spec({"spread": 40.0}, 2)
    assert spread_mix.shape[1] == 2
    assert abs(
        20.0 * np.log10(np.max(np.abs(spread_mix))) + 12.0
    ) < 0.5

    assert render_spec(
        {"spread": 40.0, "output_mode": "stereo"}, 3
    ).shape[1] == 2
    assert np.array_equal(render_spec({}, 5), render_spec({}, 5))

    high = band_noise(6, *CMAA_HIGH)
    high_frame = pan_to_stereo(high, 10.0, -12.0)
    assert np.sum(high_frame[:, 1] ** 2) > np.sum(high_frame[:, 0] ** 2)

    tmp_wav_name = "_selfcheck_tmp.wav"
    tmp_wav_path = os.path.join(
        os.path.dirname(__file__), "stimuli", tmp_wav_name
    )
    os.makedirs(os.path.dirname(tmp_wav_path), exist_ok=True)
    try:
        samples = (
            np.sin(2.0 * np.pi * 440.0 * np.arange(SR * 2) / SR) * 32767
        ).astype(np.int16)
        with wave.open(tmp_wav_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SR)
            wav.writeframes(samples.tobytes())

        stim = make_stimulus(tmp_wav_name, 0, region=(0.5, 1.0))
        assert len(stim) == 24000
        info = wav_info(tmp_wav_name)
        assert abs(info["duration"] - 2.0) < 1e-6
        assert len(info["peaks"]) == 600

        cmaa_wav = render_cmaa(
            0, 20, 1, -12.0, "folddown", 5,
            stim_a=tmp_wav_name, stim_b="band-high",
        )
        assert cmaa_wav.shape[1] == 2
        assert len(cmaa_wav) <= SR
    finally:
        if os.path.exists(tmp_wav_path):
            os.remove(tmp_wav_path)

    tmp_eq_name = "_selfcheck_tmp.txt"
    tmp_eq_path = os.path.join(EQ_DIR, tmp_eq_name)
    os.makedirs(EQ_DIR, exist_ok=True)
    try:
        with open(tmp_eq_path, "w", encoding="utf-8") as handle:
            handle.write(
                "Preamp: -3.0 dB\n"
                "Filter 1: ON PK Fc 1000 Hz Gain 6 dB Q 1.2\n"
                "Filter 2: ON LS Fc 150 Hz Gain 3 dB\n"
                "Filter 3: OFF HS Fc 8000 Hz Gain -2 dB Q 0.7\n"
                "garbage line\n"
            )

        parsed = parse_eqapo(tmp_eq_name)
        assert parsed["preamp"] == -3.0
        assert len(parsed["filters"]) == 2
        assert parsed["filters"][0]["type"] == "PK"
        assert parsed["filters"][1]["type"] == "LS"
        assert tmp_eq_name in list_eqs()

        test_signal = pink_noise(12000, 23)
        filtered = apply_eq(test_signal, parsed)
        assert len(filtered) == len(test_signal)
        assert not np.allclose(filtered, test_signal)

        unity_eq = {
            "preamp": 0.0,
            "filters": [{
                "type": "PK",
                "fc": 1000.0,
                "gain": 0.0,
                "q": 1.0,
            }],
        }
        assert np.allclose(
            apply_eq(test_signal, unity_eq), test_signal, atol=1e-4
        )

        rms_frame = render_spec({
            "stimulus": "pink",
            "output_mode": "bed71",
            "az": 30.0,
            "peak_dbfs": -12.0,
            "eq": tmp_eq_name,
            "level_mode": "rms",
        }, 31)
        assert np.all(np.isfinite(rms_frame))
        active = rms_frame[:, CH_INDEX["FR"]]
        measured_rms = np.sqrt(np.mean(active.astype(np.float64) ** 2))
        target_rms = 10.0 ** ((-12.0 - 8.0) / 20.0)
        assert abs(20.0 * np.log10(measured_rms / target_rms)) <= 1.0

        masked_yes = render_masked(
            True, "pink", -12.0, "pink", -30.0,
            0.0, 30.0, "folddown", 41,
        )
        masked_no = render_masked(
            False, "pink", -12.0, "pink", -30.0,
            0.0, 30.0, "folddown", 41,
        )
        assert masked_yes.shape == masked_no.shape
        assert not np.array_equal(masked_yes, masked_no)
    finally:
        if os.path.exists(tmp_eq_path):
            os.remove(tmp_eq_path)

    print("audio.py selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
