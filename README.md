# 7.1 Localization Test Tool

Internal listening-test instrument for evaluating virtual 7.1 spatial-audio APOs
(e.g. ROG virtual surround vs Dolby Atmos for Headphones) on gaming headsets.

The tool outputs raw 8-channel 7.1 audio to a Windows audio endpoint and does
**channel-based amplitude panning only** — the APO on that endpoint performs the
binauralization. The tool itself does no HRTF/binaural processing. A listener wears
the headset, hears a stimulus panned to a target azimuth, and clicks the perceived
direction. Errors and confusions are recorded to SQLite.

## Requirements

- Windows 10/11, Python 3.10+
- `pip install flask sounddevice numpy`

## Run

```
python main.py
```

Starts a local server and opens `http://127.0.0.1:5000/` in the browser.

## Windows setup checklist (do this before every test session)

The tool's data is only valid if exactly **one** virtualizer is in the signal path —
the APO under test. Double-processing (Windows Sonic + your APO) invalidates results.

1. **Enable 7.1 on the target endpoint.** Settings → System → Sound → (device) →
   Properties, or Control Panel → Sound → Playback → (device) → Configure →
   **7.1 Surround**. The tool refuses to start on an endpoint exposing fewer than
   8 channels and never downmixes.
2. **Enable the APO under test** on that endpoint (your virtual-surround driver, or
   Dolby Access → Dolby Atmos for Headphones on the endpoint).
3. **Disable any other spatial sound.** In the endpoint's Spatial sound dropdown,
   make sure only the APO under test is active — set Windows Sonic / Atmos to **Off**
   if it would double-process. Only one virtualizer may be live.
4. **Fixed reference volume.** Set Windows master volume to a fixed reference level
   (recommend 100% in Windows, and control loudness only via the tool's Peak dBFS,
   default −12 dBFS) and keep it identical across every condition you compare.
5. Confirm playback: open **Manual Probe**, set azimuth 45°, Play — you should hear
   a right-front pink-noise burst with no clicks.

## Test flow

- **Setup:** pick endpoint (channel count shown), participant ID, condition label,
  stimulus, azimuth step (30° = 12 positions default, 15° = 24), repetitions
  (default 4), peak dBFS. Estimated duration is shown.
- **Practice:** 5 trials with visual feedback (target vs response) after each.
- **Main:** no feedback. Randomized order, one replay per trial, 1 s between-trial
  gap, pause supported. Default 12 × 4 = 48 trials (~5–6 min). Each trial commits
  to SQLite immediately, so a crash loses at most the current trial. Interrupted
  main sessions are **resumable** from the Reports tab.
- **Manual Probe:** set an exact azimuth (0.1°) and play/loop any stimulus, for
  subjective spot-checks. Not recorded. Elevation is disabled (Phase 2 — see below).

## Reports

Per session and via the Reports browser: overall + per-azimuth mean absolute error
(polar plot), front-back and left-right confusion rates, target×response confusion
heatmap, multi-session comparison table (with pooled columns per shared condition
label), and CSV export of raw trials.

## Stimulus

Pink noise (3 × 250 ms bursts, 100 ms gaps, 10 ms raised-cosine ramps) is built in.
Fresh seeded token per trial (reproducible from the logged seed). Add game-style
cues (footsteps, gunshots) as mono 48 kHz WAV files in `stimuli/` — see that folder's
README.

## Elevation / Z-axis (Phase 2, not yet built)

A 7.1 bed is a horizontal format and carries no height information, so the bed→APO
path used here physically cannot reproduce elevation. Height requires the **Windows
Spatial Sound object API** (dynamic audio objects with xyz coordinates), which
measures the Atmos/Sonic **object renderer** — a different signal path whose data is
**not comparable** to the 7.1-bed results. It is scoped as a separate Phase 2 spike;
the elevation control is present but disabled until that path is validated.

## Data model

`sessions(id, participant, condition, device_name, mode, created_at, config_json,
completed)` and `trials(id, session_id, trial_index, target_az, response_az,
signed_error, abs_error, front_back_confusion, left_right_confusion, replay_count,
response_ms)`. `config_json` records seed, azimuth_step, reps, peak_dbfs, stimulus,
render_path, device_index.

## Self-checks

```
python audio.py     # panner constant-power, LFE silent, seeded stimulus
python metrics.py   # signed error, FB/LR confusion, binning
python db.py        # per-trial commit / resume / list
```
