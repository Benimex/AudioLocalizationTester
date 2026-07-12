# stimuli/

Drop game-style localization cues here as **mono, 48 kHz, 16-bit PCM WAV** files
(e.g. `footstep.wav`, `gunshot.wav`, `reload.wav`). They appear in the Setup and
Manual Probe stimulus dropdowns automatically.

Non-conforming files are refused with a message telling you to convert — the tool
never silently resamples or downmixes, to keep the stimulus objective.

Provide your own assets and mind their licensing.

## Object Panner (HRTF sandbox)

The Object Panner also loads these WAVs (fetched + decoded in the browser, looped as a
point source). Good game-relevant localization cues to drop in:

- `footstep.wav` — the classic FPS localization cue
- `gunshot.wav` / `reload.wav` — broadband transients, localize sharply
- `radar_ping.wav` / `ui_blip.wav` — short tonal-ish pings

The panner also ships built-in generated stimuli that need no file: **pink pulse /
white pulse** (pulsed broadband — less fatiguing and better for localization than a
continuous drone), **click** (sharp azimuth), and **pink cont / white cont** (steady).
The 7.1 main test uses `pink` (3-burst pink noise) built in.
