"""Flask app: serves UI, enumerates devices, plays panned stimuli, records trials.

Run: python main.py  -> starts server and opens the browser.
Playback is server-side (blocking) so the browser never touches the 8ch audio path.
"""
import csv
import io
import random
import threading
import webbrowser
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory, Response

import audio
import audio_hrtf
import db
import metrics

app = Flask(__name__, static_folder="static", static_url_path="")


def _now():
    return datetime.now(timezone.utc).isoformat()


def trial_order(seed, azimuth_step, reps):
    """Deterministic randomized trial order: each grid azimuth repeated `reps` times, shuffled."""
    azes = metrics.grid_azimuths(azimuth_step)
    order = azes * reps
    random.Random(seed).shuffle(order)
    return order


def token_seed(base_seed, trial_index):
    """Per-trial stimulus token seed -- reproducible, distinct per trial."""
    return base_seed * 100003 + trial_index


# ---- static ----
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ---- setup data ----
@app.route("/api/devices")
def devices():
    return jsonify(audio.list_output_devices())


@app.route("/api/stimuli")
def stimuli():
    return jsonify(audio.list_stimuli())


@app.route("/stimuli/<path:name>")
def stimuli_file(name):
    """Serve a stimulus WAV for the browser panner to fetch+decode."""
    return send_from_directory("stimuli", name)


# ---- session lifecycle ----
@app.route("/api/session", methods=["POST"])
def create_session():
    d = request.get_json()
    step = float(d.get("azimuth_step", 30))
    reps = int(d.get("reps", 4))
    seed = random.randrange(1, 2**31)
    config = {
        "seed": seed, "azimuth_step": step, "reps": reps,
        "peak_dbfs": float(d.get("peak_dbfs", -12.0)),
        "stimulus": d.get("stimulus", "pink"),
        "render_path": "bed_7.1",
        "device_index": int(d["device_index"]),
    }
    # Practice: 5 azimuths, one drawn per front/back-left/right region for coverage.
    if d["mode"] == "practice":
        order = _practice_order(step, seed)
        config["reps"] = None
    else:
        order = trial_order(seed, step, reps)

    sid = db.create_session(d["participant"], d["condition"], d["device_name"],
                            d["mode"], config, _now())
    return jsonify({"session_id": sid, "trial_order": order, "config": config,
                    "completed": []})


def _practice_order(step, seed):
    """5 practice azimuths: one each from the four quadrants + one extra, randomized."""
    quads = {
        "FR": [a for a in metrics.grid_azimuths(step) if 0 < a < 90],
        "BR": [a for a in metrics.grid_azimuths(step) if 90 < a < 180],
        "BL": [a for a in metrics.grid_azimuths(step) if -180 < a < -90],
        "FL": [a for a in metrics.grid_azimuths(step) if -90 < a < 0],
    }
    rng = random.Random(seed)
    picks = [rng.choice(v) for v in quads.values() if v]
    picks.append(rng.choice(metrics.grid_azimuths(step)))
    rng.shuffle(picks)
    return picks[:5]


@app.route("/api/session/<int:sid>/resume")
def resume_session(sid):
    s = db.get_session(sid)
    if not s:
        return jsonify({"error": "not found"}), 404
    import json
    cfg = json.loads(s["config_json"])
    order = trial_order(cfg["seed"], cfg["azimuth_step"], cfg["reps"])
    done = db.completed_trial_indices(sid)
    return jsonify({"session_id": sid, "trial_order": order, "config": cfg,
                    "completed": sorted(done), "session": s})


@app.route("/api/play", methods=["POST"])
def play():
    """Play a panned stimulus (blocking). Body: device_index, target_az, stimulus,
    peak_dbfs, seed. Returns after playback finishes."""
    d = request.get_json()
    try:
        stim = audio.make_stimulus(d.get("stimulus", "pink"), int(d["seed"]))
        frame = audio.pan_to_frame(stim, float(d["target_az"]), float(d.get("peak_dbfs", -12.0)))
        audio.play_frame(frame, int(d["device_index"]))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop():
    audio.stop()
    return jsonify({"ok": True})


# ---- HRTF object-panner sandbox (backend C) ----
@app.route("/api/hrtf/play", methods=["POST"])
def hrtf_play():
    """Render a scene of positioned sources to binaural and loop it. Body:
    device_index, objects:[{az, el, dist, stim}]. Stereo out -- no 7.1 needed."""
    d = request.get_json()
    try:
        buf = audio_hrtf.render_scene(d.get("objects", []))
        audio_hrtf.LOOPER.play(buf, int(d["device_index"]))
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.route("/api/hrtf/stop", methods=["POST"])
def hrtf_stop():
    audio_hrtf.LOOPER.stop()
    return jsonify({"ok": True})


@app.route("/api/trial", methods=["POST"])
def save_trial():
    d = request.get_json()
    target = float(d["target_az"])
    resp = float(d["response_az"])
    trial = {
        "trial_index": int(d["trial_index"]),
        "target_az": target,
        "response_az": round(resp, 1),
        "signed_error": round(metrics.signed_error(target, resp), 2),
        "abs_error": round(metrics.abs_error(target, resp), 2),
        "front_back_confusion": metrics.front_back_confusion(target, resp),
        "left_right_confusion": metrics.left_right_confusion(target, resp),
        "replay_count": int(d.get("replay_count", 0)),
        "response_ms": int(d["response_ms"]),
    }
    db.save_trial(int(d["session_id"]), trial)
    return jsonify(trial)


@app.route("/api/session/<int:sid>/complete", methods=["POST"])
def complete(sid):
    db.mark_completed(sid)
    return jsonify({"ok": True})


# ---- reporting ----
@app.route("/api/sessions")
def sessions():
    return jsonify(db.list_sessions())


def _session_metrics(sid):
    """Compute report metrics for one session from committed trials."""
    s = db.get_session(sid)
    trials = db.get_trials(sid)
    import json
    step = json.loads(s["config_json"]).get("azimuth_step", 30)
    return _metrics_from_trials(trials, step, s), s


def _metrics_from_trials(trials, step, s=None):
    if not trials:
        return {"n": 0, "mae": None, "per_az": {}, "fb_rate": None, "lr_rate": None,
                "heatmap": [], "step": step}
    maes = [t["abs_error"] for t in trials]
    per_az = {}
    for t in trials:
        per_az.setdefault(t["target_az"], []).append(t["abs_error"])
    per_az_mae = {az: sum(v) / len(v) for az, v in per_az.items()}

    # Confusion rates use only eligible trials (rule exclusions already stored as False,
    # but rate denominators should exclude ineligible targets).
    fb_elig = [t for t in trials if abs(abs(metrics.norm180(t["target_az"])) - 90) > 1e-6]
    lr_elig = [t for t in trials if abs(metrics.norm180(t["target_az"])) > 1e-6
               and abs(abs(metrics.norm180(t["target_az"])) - 180) > 1e-6]
    fb_rate = (sum(t["front_back_confusion"] for t in fb_elig) / len(fb_elig)) if fb_elig else None
    lr_rate = (sum(t["left_right_confusion"] for t in lr_elig) / len(lr_elig)) if lr_elig else None

    # Heatmap: target bin x response bin counts.
    grid = metrics.grid_azimuths(step)
    idx = {az: i for i, az in enumerate(grid)}
    hm = [[0] * len(grid) for _ in grid]
    for t in trials:
        ti = idx.get(metrics.bin_az(t["target_az"], step))
        ri = idx.get(metrics.bin_az(t["response_az"], step))
        if ti is not None and ri is not None:
            hm[ti][ri] += 1
    return {
        "n": len(trials),
        "mae": round(sum(maes) / len(maes), 2),
        "per_az": {str(k): round(v, 2) for k, v in per_az_mae.items()},
        "fb_rate": round(fb_rate, 3) if fb_rate is not None else None,
        "lr_rate": round(lr_rate, 3) if lr_rate is not None else None,
        "heatmap": hm, "grid": grid, "step": step,
    }


@app.route("/api/report/<int:sid>")
def report(sid):
    m, s = _session_metrics(sid)
    return jsonify({"session": s, "metrics": m})


@app.route("/api/compare")
def compare():
    """?ids=1,2,3 -> per-session metrics + pooled-per-condition (same-step sessions only)."""
    ids = [int(x) for x in request.args.get("ids", "").split(",") if x]
    import json
    cols = []
    by_condition = {}
    for sid in ids:
        s = db.get_session(sid)
        if not s:
            continue
        step = json.loads(s["config_json"]).get("azimuth_step", 30)
        trials = db.get_trials(sid)
        cols.append({"label": f"#{sid} {s['participant']}/{s['condition']}",
                     "metrics": _metrics_from_trials(trials, step)})
        by_condition.setdefault((s["condition"], step), []).extend(trials)
    pooled = []
    for (cond, step), trials in by_condition.items():
        n_sessions = sum(1 for sid in ids
                         if (db.get_session(sid) or {}).get("condition") == cond)
        if n_sessions >= 2:
            pooled.append({"label": f"POOLED {cond}",
                           "metrics": _metrics_from_trials(trials, step)})
    return jsonify({"columns": cols + pooled})


@app.route("/api/export/<int:sid>")
def export_csv(sid):
    trials = db.get_trials(sid)
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["trial_index", "target_az", "response_az", "signed_error", "abs_error",
            "front_back_confusion", "left_right_confusion", "replay_count", "response_ms"]
    w.writerow(cols)
    for t in trials:
        w.writerow([t[c] for c in cols])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=session_{sid}.csv"})


def open_browser():
    webbrowser.open("http://127.0.0.1:5000/")


if __name__ == "__main__":
    db.init()
    threading.Timer(1.0, open_browser).start()
    app.run(host="127.0.0.1", port=5000, threaded=True)
