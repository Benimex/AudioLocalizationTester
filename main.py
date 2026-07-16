"""Flask app: serves UI, plays stimuli, records trials, and reports results."""
import csv
import io
import json
import random
import threading
import webbrowser
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, request, send_from_directory

import audio
import audio_hrtf
import cmaa
import db
import metrics

app = Flask(__name__, static_folder="static", static_url_path="")
OUTPUT_MODES = {"bed71", "folddown", "stereo"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def trial_order(seed, azimuth_step, reps, output_mode="bed71"):
    """Deterministic randomized localization trial order."""
    azimuths = metrics.grid_azimuths(azimuth_step)
    if output_mode == "stereo":
        azimuths = [azimuth for azimuth in azimuths if abs(azimuth) <= 90]
    order = azimuths * reps
    random.Random(seed).shuffle(order)
    return order


def token_seed(base_seed, trial_index):
    """Return a reproducible, distinct stimulus seed for a trial."""
    return base_seed * 100003 + trial_index


def _cmaa_history(trials):
    return [(trial["delta"], bool(trial["correct"])) for trial in trials]


def _cmaa_trial_spec(seed, trial_index, posterior):
    high_side = random.Random(seed * 7919 + trial_index).choice([-1, 1])
    return {
        "done": False,
        "trial_index": trial_index,
        "delta": cmaa.next_delta(posterior),
        "high_side": high_side,
        "n": trial_index,
    }


def _cmaa_state(session_id):
    session = db.get_session(session_id)
    if not session:
        return None
    config = json.loads(session["config_json"])
    trials = db.get_cmaa_trials(session_id)
    history = _cmaa_history(trials)
    posterior = cmaa.posterior_from_history(history)
    if cmaa.is_done(history, posterior):
        return {
            "done": True,
            "estimate": cmaa.estimate(posterior),
            "n": len(history),
        }
    return _cmaa_trial_spec(config["seed"], len(history), posterior)


def _abx_x_is_a(seed, trial_index):
    return random.Random(seed * 31337 + trial_index).random() < 0.5


def _abx_result(trials):
    n = len(trials)
    k = sum(int(trial["correct"]) for trial in trials)
    return {
        "n": n,
        "k": k,
        "p_value": metrics.binom_p_one_sided(k, n) if n else None,
    }


def _ext_target_az(config, trial_index):
    pool = metrics.grid_azimuths(config["azimuth_step"])
    if config["output_mode"] == "stereo":
        pool = [azimuth for azimuth in pool if abs(azimuth) <= 90]
    return random.Random(
        config["seed"] * 104729 + trial_index
    ).choice(pool)


def _ext_result(trials):
    n = len(trials)
    ratings = [int(trial["rating"]) for trial in trials]
    return {
        "n": n,
        "mean_rating": round(sum(ratings) / n, 2) if n else None,
        "hist": [
            sum(rating == value for rating in ratings)
            for value in range(1, 6)
        ],
    }


def _width_a_first(seed, trial_index):
    return random.Random(seed * 15485863 + trial_index).random() < 0.5


def _width_result(trials):
    n = len(trials)
    k_a = sum(int(trial["chose_a"]) for trial in trials)
    return {
        "n": n,
        "k_a": k_a,
        "p_value": metrics.binom_p_two_sided(k_a, n) if n else None,
    }


# ---- static -----------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ---- setup data --------------------------------------------------------------

@app.route("/api/devices")
def devices():
    return jsonify(audio.list_output_devices())


@app.route("/api/stimuli")
def stimuli():
    return jsonify(audio.list_stimuli())


@app.route("/api/wavinfo")
def wavinfo():
    try:
        return jsonify(audio.wav_info(request.args.get("name", "")))
    except Exception as error:
        return jsonify({"error": str(error)}), 400


@app.route("/stimuli/<path:name>")
def stimuli_file(name):
    return send_from_directory("stimuli", name)


# ---- localization session lifecycle -----------------------------------------

@app.route("/api/session", methods=["POST"])
def create_session():
    data = request.get_json()
    step = float(data.get("azimuth_step", 30))
    reps = int(data.get("reps", 4))
    seed = random.randrange(1, 2**31)
    output_mode = data.get("output_mode", "bed71")
    if output_mode not in OUTPUT_MODES:
        return jsonify({"error": f"Unknown output mode '{output_mode}'."}), 400

    stimulus = data.get("stimulus", "pink")
    stim_region = data.get("stim_region")
    if stimulus == "pink" or stim_region is None:
        stim_region = None
    else:
        try:
            stim_region = [float(stim_region[0]), float(stim_region[1])]
        except (TypeError, ValueError, IndexError):
            return jsonify({"error": "stim_region must be [a, b]."}), 400

    config = {
        "seed": seed,
        "azimuth_step": step,
        "reps": reps,
        "peak_dbfs": float(data.get("peak_dbfs", -12.0)),
        "stimulus": stimulus,
        "stim_region": stim_region,
        "render_path": "bed_7.1",
        "output_mode": output_mode,
        "device_index": int(data["device_index"]),
    }
    if data["mode"] == "practice":
        order = _practice_order(step, seed, output_mode)
        config["reps"] = None
    else:
        order = trial_order(seed, step, reps, output_mode)

    session_id = db.create_session(
        data["participant"], data["condition"], data["device_name"],
        data["mode"], config, _now(),
    )
    return jsonify({
        "session_id": session_id,
        "trial_order": order,
        "config": config,
        "completed": [],
    })


def _practice_order(step, seed, output_mode="bed71"):
    """Return five practice azimuths covering available directional regions."""
    grid = metrics.grid_azimuths(step)
    if output_mode == "stereo":
        grid = [azimuth for azimuth in grid if abs(azimuth) <= 90]
        regions = {
            "R": [azimuth for azimuth in grid if 0 < azimuth <= 90],
            "L": [azimuth for azimuth in grid if -90 <= azimuth < 0],
        }
        rng = random.Random(seed)
        picks = [rng.choice(values) for values in regions.values() if values]
        remaining = list(grid)
        while len(picks) < 5 and remaining:
            picks.append(rng.choice(remaining))
        rng.shuffle(picks)
        return picks[:5]

    quadrants = {
        "FR": [azimuth for azimuth in grid if 0 < azimuth < 90],
        "BR": [azimuth for azimuth in grid if 90 < azimuth < 180],
        "BL": [azimuth for azimuth in grid if -180 < azimuth < -90],
        "FL": [azimuth for azimuth in grid if -90 < azimuth < 0],
    }
    rng = random.Random(seed)
    picks = [rng.choice(values) for values in quadrants.values() if values]
    picks.append(rng.choice(grid))
    rng.shuffle(picks)
    return picks[:5]


@app.route("/api/session/<int:sid>/resume")
def resume_session(sid):
    session = db.get_session(sid)
    if not session:
        return jsonify({"error": "not found"}), 404
    config = json.loads(session["config_json"])
    output_mode = config.get("output_mode", "bed71")
    if config["reps"] is None:
        order = _practice_order(
            config["azimuth_step"], config["seed"], output_mode
        )
    else:
        order = trial_order(
            config["seed"], config["azimuth_step"], config["reps"], output_mode
        )
    completed = db.completed_trial_indices(sid)
    return jsonify({
        "session_id": sid,
        "trial_order": order,
        "config": config,
        "completed": sorted(completed),
        "session": session,
    })


@app.route("/api/play", methods=["POST"])
def play():
    data = request.get_json()
    try:
        region = data.get("stim_region")
        region = tuple(region) if region is not None else None
        stimulus = audio.make_stimulus(
            data.get("stimulus", "pink"), int(data["seed"]), region=region
        )
        frame = audio.render_output(
            stimulus,
            float(data["target_az"]),
            float(data.get("peak_dbfs", -12.0)),
            data.get("output_mode", "bed71"),
        )
        audio.play_frame(frame, int(data["device_index"]))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop():
    audio.stop()
    return jsonify({"ok": True})


# ---- CMAA session lifecycle --------------------------------------------------

@app.route("/api/cmaa/session", methods=["POST"])
def create_cmaa_session():
    data = request.get_json()
    output_mode = data.get("output_mode", "folddown")
    if output_mode not in OUTPUT_MODES:
        return jsonify({"error": f"Unknown output mode '{output_mode}'."}), 400

    stim_a = data.get("stim_a", "band-low")
    stim_b = data.get("stim_b", "band-high")
    for stimulus in (stim_a, stim_b):
        if stimulus not in {"band-low", "band-high"} and not stimulus.lower().endswith(".wav"):
            return jsonify({"error": f"Unknown CMAA stimulus '{stimulus}'."}), 400

    seed = random.randrange(1, 2**31)
    config = {
        "seed": seed,
        "output_mode": output_mode,
        "peak_dbfs": float(data.get("peak_dbfs", -12.0)),
        "ref_az": float(data.get("ref_az", 0.0)),
        "stim_a": stim_a,
        "stim_b": stim_b,
        "test_type": "cmaa",
    }
    session_id = db.create_session(
        data["participant"],
        data["condition"],
        data["device_name"],
        "cmaa",
        config,
        _now(),
    )
    return jsonify({"session_id": session_id, "config": config})


@app.route("/api/cmaa/state/<int:sid>")
def cmaa_state(sid):
    state = _cmaa_state(sid)
    if state is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(state)


@app.route("/api/cmaa/play", methods=["POST"])
def cmaa_play():
    data = request.get_json()
    try:
        frame = audio.render_cmaa(
            float(data["ref_az"]),
            float(data["delta"]),
            int(data["high_side"]),
            float(data["peak_dbfs"]),
            data["output_mode"],
            int(data["seed"]),
            stim_a=data.get("stim_a", "band-low"),
            stim_b=data.get("stim_b", "band-high"),
        )
        audio.play_frame(frame, int(data["device_index"]))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"ok": True})


@app.route("/api/cmaa/trial", methods=["POST"])
def save_cmaa_trial():
    data = request.get_json()
    response_side = int(data["response_side"])
    high_side = int(data["high_side"])
    if response_side not in (-1, 1):
        return jsonify({"error": "response_side must be -1 or +1."}), 400
    if high_side not in (-1, 1):
        return jsonify({"error": "high_side must be -1 or +1."}), 400

    session_id = int(data["session_id"])
    trial = {
        "trial_index": int(data["trial_index"]),
        "delta": float(data["delta"]),
        "high_side": high_side,
        "response_side": response_side,
        "correct": int(response_side == high_side),
        "response_ms": int(data["response_ms"]),
    }
    db.save_cmaa_trial(session_id, trial)
    state = _cmaa_state(session_id)
    if state is None:
        return jsonify({"error": "not found"}), 404

    result = {"correct": trial["correct"], **state}
    return jsonify(result)


@app.route("/api/cmaa/report/<int:sid>")
def cmaa_report(sid):
    session = db.get_session(sid)
    if not session:
        return jsonify({"error": "not found"}), 404
    trials = db.get_cmaa_trials(sid)
    posterior = cmaa.posterior_from_history(_cmaa_history(trials))
    estimate = cmaa.estimate(posterior) if trials else None
    columns = [
        "trial_index", "delta", "high_side", "response_side", "correct", "response_ms"
    ]
    return jsonify({
        "session": session,
        "n": len(trials),
        "estimate": estimate,
        "trials": [
            {column: trial[column] for column in columns}
            for trial in trials
        ],
    })


# ---- ABX session lifecycle ---------------------------------------------------

@app.route("/api/abx/session", methods=["POST"])
def create_abx_session():
    data = request.get_json()
    spec_a = dict(data.get("spec_a") or {})
    spec_b = dict(data.get("spec_b") or {})

    for spec in (spec_a, spec_b):
        output_mode = spec.get("output_mode", "folddown")
        if output_mode not in OUTPUT_MODES:
            return jsonify({
                "error": f"Unknown output mode '{output_mode}'."
            }), 400

    seed = random.randrange(1, 2**31)
    n_trials = max(5, min(50, int(data.get("n_trials", 16))))
    config = {
        "seed": seed,
        "spec_a": spec_a,
        "spec_b": spec_b,
        "n_trials": n_trials,
        "test_type": "abx",
    }
    session_id = db.create_session(
        data["participant"],
        data["condition"],
        data["device_name"],
        "abx",
        config,
        _now(),
    )
    return jsonify({"session_id": session_id, "config": config})


@app.route("/api/abx/state/<int:sid>")
def abx_state(sid):
    session = db.get_session(sid)
    if not session:
        return jsonify({"error": "not found"}), 404

    config = json.loads(session["config_json"])
    trials = db.get_abx_trials(sid)
    n = len(trials)
    if n >= config["n_trials"]:
        result = _abx_result(trials)
        result["done"] = True
        return jsonify(result)

    return jsonify({
        "done": False,
        "trial_index": n,
        "n_trials": config["n_trials"],
    })


@app.route("/api/abx/play", methods=["POST"])
def abx_play():
    data = request.get_json()
    session = db.get_session(int(data["session_id"]))
    if not session:
        return jsonify({"error": "not found"}), 404

    config = json.loads(session["config_json"])
    trial_index = int(data["trial_index"])
    which = data["which"]
    if which not in ("a", "b", "x"):
        return jsonify({"error": "which must be 'a', 'b', or 'x'."}), 400

    if which == "a":
        spec = config["spec_a"]
    elif which == "b":
        spec = config["spec_b"]
    elif _abx_x_is_a(config["seed"], trial_index):
        spec = config["spec_a"]
    else:
        spec = config["spec_b"]

    try:
        frame = audio.render_spec(
            spec, token_seed(config["seed"], trial_index)
        )
        audio.play_frame(frame, int(data["device_index"]))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"ok": True})


@app.route("/api/abx/trial", methods=["POST"])
def save_abx_trial():
    data = request.get_json()
    response_is_a = int(data["response_is_a"])
    if response_is_a not in (0, 1):
        return jsonify({"error": "response_is_a must be 0 or 1."}), 400

    session_id = int(data["session_id"])
    session = db.get_session(session_id)
    if not session:
        return jsonify({"error": "not found"}), 404

    config = json.loads(session["config_json"])
    trial_index = int(data["trial_index"])
    x_is_a = _abx_x_is_a(config["seed"], trial_index)
    trial = {
        "trial_index": trial_index,
        "x_is_a": int(x_is_a),
        "response_is_a": response_is_a,
        "correct": int(bool(response_is_a) == x_is_a),
        "response_ms": int(data["response_ms"]),
    }
    db.save_abx_trial(session_id, trial)

    trials = db.get_abx_trials(session_id)
    answered = len(trials)
    if answered >= config["n_trials"]:
        db.mark_completed(session_id)
        result = _abx_result(trials)
        result["done"] = True
        return jsonify(result)

    return jsonify({
        "done": False,
        "trial_index": answered,
        "n_trials": config["n_trials"],
    })


@app.route("/api/abx/report/<int:sid>")
def abx_report(sid):
    session = db.get_session(sid)
    if not session:
        return jsonify({"error": "not found"}), 404

    trials = db.get_abx_trials(sid)
    result = _abx_result(trials)
    return jsonify({
        "session": session,
        **result,
        "trials": trials,
    })


# ---- externalization session lifecycle --------------------------------------

@app.route("/api/ext/session", methods=["POST"])
def create_ext_session():
    data = request.get_json()
    output_mode = data.get("output_mode", "folddown")
    if output_mode not in OUTPUT_MODES:
        return jsonify({"error": f"Unknown output mode '{output_mode}'."}), 400

    stimulus = data.get("stimulus", "pink")
    stim_region = data.get("stim_region")
    if stimulus == "pink" or stim_region is None:
        stim_region = None
    else:
        try:
            stim_region = [float(stim_region[0]), float(stim_region[1])]
        except (TypeError, ValueError, IndexError):
            return jsonify({"error": "stim_region must be [a, b]."}), 400

    seed = random.randrange(1, 2**31)
    n_trials = max(5, min(40, int(data.get("n_trials", 12))))
    config = {
        "seed": seed,
        "output_mode": output_mode,
        "stimulus": stimulus,
        "peak_dbfs": float(data.get("peak_dbfs", -12.0)),
        "azimuth_step": float(data.get("azimuth_step", 30)),
        "stim_region": stim_region,
        "n_trials": n_trials,
        "test_type": "extern",
    }
    session_id = db.create_session(
        data["participant"],
        data["condition"],
        data["device_name"],
        "extern",
        config,
        _now(),
    )
    return jsonify({"session_id": session_id, "config": config})


@app.route("/api/ext/state/<int:sid>")
def ext_state(sid):
    session = db.get_session(sid)
    if not session:
        return jsonify({"error": "not found"}), 404

    config = json.loads(session["config_json"])
    trials = db.get_ext_trials(sid)
    n = len(trials)
    if n >= config["n_trials"]:
        result = _ext_result(trials)
        result["done"] = True
        return jsonify(result)

    return jsonify({
        "done": False,
        "trial_index": n,
        "target_az": _ext_target_az(config, n),
        "n_trials": config["n_trials"],
    })


@app.route("/api/ext/play", methods=["POST"])
def ext_play():
    data = request.get_json()
    session = db.get_session(int(data["session_id"]))
    if not session:
        return jsonify({"error": "not found"}), 404

    config = json.loads(session["config_json"])
    trial_index = int(data["trial_index"])
    spec = {
        "stimulus": config["stimulus"],
        "output_mode": config["output_mode"],
        "az": _ext_target_az(config, trial_index),
        "peak_dbfs": config["peak_dbfs"],
        "region": config["stim_region"],
    }
    try:
        frame = audio.render_spec(
            spec, token_seed(config["seed"], trial_index)
        )
        audio.play_frame(frame, int(data["device_index"]))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"ok": True})


@app.route("/api/ext/trial", methods=["POST"])
def save_ext_trial():
    data = request.get_json()
    try:
        rating = int(data["rating"])
    except (TypeError, ValueError):
        return jsonify({"error": "rating must be an integer from 1 to 5."}), 400
    if not 1 <= rating <= 5:
        return jsonify({"error": "rating must be an integer from 1 to 5."}), 400

    session_id = int(data["session_id"])
    session = db.get_session(session_id)
    if not session:
        return jsonify({"error": "not found"}), 404

    config = json.loads(session["config_json"])
    trial_index = int(data["trial_index"])
    trial = {
        "trial_index": trial_index,
        "target_az": _ext_target_az(config, trial_index),
        "rating": rating,
        "response_ms": int(data["response_ms"]),
    }
    db.save_ext_trial(session_id, trial)

    trials = db.get_ext_trials(session_id)
    answered = len(trials)
    if answered >= config["n_trials"]:
        db.mark_completed(session_id)
        result = _ext_result(trials)
        result["done"] = True
        return jsonify(result)

    return jsonify({
        "done": False,
        "trial_index": answered,
        "target_az": _ext_target_az(config, answered),
        "n_trials": config["n_trials"],
    })


@app.route("/api/ext/report/<int:sid>")
def ext_report(sid):
    session = db.get_session(sid)
    if not session:
        return jsonify({"error": "not found"}), 404

    trials = db.get_ext_trials(sid)
    result = _ext_result(trials)
    return jsonify({
        "session": session,
        **result,
        "trials": trials,
    })


# ---- soundstage-width session lifecycle -------------------------------------

@app.route("/api/width/session", methods=["POST"])
def create_width_session():
    data = request.get_json()
    outmode_a = data.get("outmode_a", "folddown")
    outmode_b = data.get("outmode_b", "folddown")
    for output_mode in (outmode_a, outmode_b):
        if output_mode not in OUTPUT_MODES:
            return jsonify({
                "error": f"Unknown output mode '{output_mode}'."
            }), 400

    stimulus = data.get("stimulus", "pink")
    stim_region = data.get("stim_region")
    if stimulus == "pink" or stim_region is None:
        stim_region = None
    else:
        try:
            stim_region = [float(stim_region[0]), float(stim_region[1])]
        except (TypeError, ValueError, IndexError):
            return jsonify({"error": "stim_region must be [a, b]."}), 400

    seed = random.randrange(1, 2**31)
    peak_dbfs = float(data.get("peak_dbfs", -12.0))
    n_trials = max(5, min(40, int(data.get("n_trials", 12))))
    config = {
        "seed": seed,
        "spec_a": {
            "stimulus": stimulus,
            "output_mode": outmode_a,
            "az": 0.0,
            "peak_dbfs": peak_dbfs,
            "region": stim_region,
            "spread": float(data.get("spread_a", 30.0)),
        },
        "spec_b": {
            "stimulus": stimulus,
            "output_mode": outmode_b,
            "az": 0.0,
            "peak_dbfs": peak_dbfs,
            "region": stim_region,
            "spread": float(data.get("spread_b", 60.0)),
        },
        "n_trials": n_trials,
        "test_type": "width",
    }
    session_id = db.create_session(
        data["participant"],
        data["condition"],
        data["device_name"],
        "width",
        config,
        _now(),
    )
    return jsonify({"session_id": session_id, "config": config})


@app.route("/api/width/state/<int:sid>")
def width_state(sid):
    session = db.get_session(sid)
    if not session:
        return jsonify({"error": "not found"}), 404

    config = json.loads(session["config_json"])
    trials = db.get_width_trials(sid)
    n = len(trials)
    if n >= config["n_trials"]:
        result = _width_result(trials)
        result["done"] = True
        return jsonify(result)

    return jsonify({
        "done": False,
        "trial_index": n,
        "n_trials": config["n_trials"],
    })


@app.route("/api/width/play", methods=["POST"])
def width_play():
    data = request.get_json()
    session = db.get_session(int(data["session_id"]))
    if not session:
        return jsonify({"error": "not found"}), 404

    interval = int(data["interval"])
    if interval not in (1, 2):
        return jsonify({"error": "interval must be 1 or 2."}), 400

    config = json.loads(session["config_json"])
    trial_index = int(data["trial_index"])
    a_first = _width_a_first(config["seed"], trial_index)
    if (interval == 1) == a_first:
        spec = config["spec_a"]
    else:
        spec = config["spec_b"]

    try:
        frame = audio.render_spec(
            spec, token_seed(config["seed"], trial_index)
        )
        audio.play_frame(frame, int(data["device_index"]))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"ok": True})


@app.route("/api/width/trial", methods=["POST"])
def save_width_trial():
    data = request.get_json()
    chose_first = int(data["chose_first"])
    if chose_first not in (0, 1):
        return jsonify({"error": "chose_first must be 0 or 1."}), 400

    session_id = int(data["session_id"])
    session = db.get_session(session_id)
    if not session:
        return jsonify({"error": "not found"}), 404

    config = json.loads(session["config_json"])
    trial_index = int(data["trial_index"])
    a_first = _width_a_first(config["seed"], trial_index)
    trial = {
        "trial_index": trial_index,
        "a_first": int(a_first),
        "chose_a": int(bool(chose_first) == a_first),
        "response_ms": int(data["response_ms"]),
    }
    db.save_width_trial(session_id, trial)

    trials = db.get_width_trials(session_id)
    answered = len(trials)
    if answered >= config["n_trials"]:
        db.mark_completed(session_id)
        result = _width_result(trials)
        result["done"] = True
        return jsonify(result)

    return jsonify({
        "done": False,
        "trial_index": answered,
        "n_trials": config["n_trials"],
    })


@app.route("/api/width/report/<int:sid>")
def width_report(sid):
    session = db.get_session(sid)
    if not session:
        return jsonify({"error": "not found"}), 404

    trials = db.get_width_trials(sid)
    result = _width_result(trials)
    return jsonify({
        "session": session,
        **result,
        "trials": trials,
    })


# ---- HRTF object-panner sandbox ---------------------------------------------

@app.route("/api/hrtf/play", methods=["POST"])
def hrtf_play():
    data = request.get_json()
    try:
        buffer = audio_hrtf.render_scene(data.get("objects", []))
        audio_hrtf.LOOPER.play(buffer, int(data["device_index"]))
    except Exception as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"ok": True})


@app.route("/api/hrtf/stop", methods=["POST"])
def hrtf_stop():
    audio_hrtf.LOOPER.stop()
    return jsonify({"ok": True})


@app.route("/api/trial", methods=["POST"])
def save_trial():
    data = request.get_json()
    target = float(data["target_az"])
    response = float(data["response_az"])
    trial = {
        "trial_index": int(data["trial_index"]),
        "target_az": target,
        "response_az": round(response, 1),
        "signed_error": round(metrics.signed_error(target, response), 2),
        "abs_error": round(metrics.abs_error(target, response), 2),
        "front_back_confusion": metrics.front_back_confusion(target, response),
        "left_right_confusion": metrics.left_right_confusion(target, response),
        "replay_count": int(data.get("replay_count", 0)),
        "response_ms": int(data["response_ms"]),
    }
    db.save_trial(int(data["session_id"]), trial)
    return jsonify(trial)


@app.route("/api/session/<int:sid>/complete", methods=["POST"])
def complete(sid):
    db.mark_completed(sid)
    return jsonify({"ok": True})


# ---- reporting ---------------------------------------------------------------

@app.route("/api/sessions")
def sessions():
    return jsonify(db.list_sessions())


def _session_metrics(sid):
    session = db.get_session(sid)
    trials = db.get_trials(sid)
    step = json.loads(session["config_json"]).get("azimuth_step", 30)
    return _metrics_from_trials(trials, step, session), session


def _metrics_from_trials(trials, step, session=None):
    if not trials:
        return {
            "n": 0,
            "mae": None,
            "per_az": {},
            "fb_rate": None,
            "lr_rate": None,
            "heatmap": [],
            "step": step,
        }

    absolute_errors = [trial["abs_error"] for trial in trials]
    per_az = {}
    for trial in trials:
        per_az.setdefault(trial["target_az"], []).append(trial["abs_error"])
    per_az_mae = {
        azimuth: sum(values) / len(values)
        for azimuth, values in per_az.items()
    }

    fb_eligible = [
        trial for trial in trials
        if abs(abs(metrics.norm180(trial["target_az"])) - 90) > 1e-6
    ]
    lr_eligible = [
        trial for trial in trials
        if abs(metrics.norm180(trial["target_az"])) > 1e-6
        and abs(abs(metrics.norm180(trial["target_az"])) - 180) > 1e-6
    ]
    fb_rate = (
        sum(trial["front_back_confusion"] for trial in fb_eligible)
        / len(fb_eligible)
        if fb_eligible else None
    )
    lr_rate = (
        sum(trial["left_right_confusion"] for trial in lr_eligible)
        / len(lr_eligible)
        if lr_eligible else None
    )

    grid = metrics.grid_azimuths(step)
    index = {azimuth: i for i, azimuth in enumerate(grid)}
    heatmap = [[0] * len(grid) for _ in grid]
    for trial in trials:
        target_index = index.get(metrics.bin_az(trial["target_az"], step))
        response_index = index.get(metrics.bin_az(trial["response_az"], step))
        if target_index is not None and response_index is not None:
            heatmap[target_index][response_index] += 1

    return {
        "n": len(trials),
        "mae": round(sum(absolute_errors) / len(absolute_errors), 2),
        "per_az": {
            str(key): round(value, 2) for key, value in per_az_mae.items()
        },
        "fb_rate": round(fb_rate, 3) if fb_rate is not None else None,
        "lr_rate": round(lr_rate, 3) if lr_rate is not None else None,
        "heatmap": heatmap,
        "grid": grid,
        "step": step,
    }


@app.route("/api/report/<int:sid>")
def report(sid):
    session_metrics, session = _session_metrics(sid)
    return jsonify({"session": session, "metrics": session_metrics})


@app.route("/api/compare")
def compare():
    """Return per-session metrics and pooled localization conditions."""
    ids = [
        int(value)
        for value in request.args.get("ids", "").split(",")
        if value
    ]
    columns = []
    by_condition = {}
    localization_sessions = []

    for sid in ids:
        session = db.get_session(sid)
        if not session:
            continue

        mode = session["mode"]
        if mode == "cmaa":
            trials = db.get_cmaa_trials(sid)
            posterior = cmaa.posterior_from_history(_cmaa_history(trials))
            result = cmaa.estimate(posterior) if trials else None
            session_metrics = {
                "type": "cmaa",
                "n": len(trials),
                "threshold": result["threshold"] if result else None,
                "ci_lo": result["ci_lo"] if result else None,
                "ci_hi": result["ci_hi"] if result else None,
            }
        elif mode == "abx":
            trials = db.get_abx_trials(sid)
            result = _abx_result(trials)
            session_metrics = {
                "type": "abx",
                "n": result["n"],
                "k": result["k"],
                "p_value": result["p_value"],
            }
        elif mode == "extern":
            trials = db.get_ext_trials(sid)
            result = _ext_result(trials)
            session_metrics = {
                "type": "extern",
                "n": result["n"],
                "mean_rating": result["mean_rating"],
            }
        elif mode == "width":
            trials = db.get_width_trials(sid)
            result = _width_result(trials)
            session_metrics = {
                "type": "width",
                "n": result["n"],
                "k_a": result["k_a"],
                "p_value": result["p_value"],
            }
        else:
            step = json.loads(session["config_json"]).get(
                "azimuth_step", 30
            )
            trials = db.get_trials(sid)
            session_metrics = _metrics_from_trials(trials, step)
            session_metrics["type"] = "loc"
            by_condition.setdefault(
                (session["condition"], step), []
            ).extend(trials)
            localization_sessions.append((session["condition"], step))

        columns.append({
            "label": f"#{sid} {session['participant']}/{session['condition']}",
            "metrics": session_metrics,
        })

    pooled = []
    for (condition, step), trials in by_condition.items():
        n_sessions = sum(
            1 for key in localization_sessions
            if key == (condition, step)
        )
        if n_sessions >= 2:
            pooled_metrics = _metrics_from_trials(trials, step)
            pooled_metrics["type"] = "loc"
            pooled.append({
                "label": f"POOLED {condition}",
                "metrics": pooled_metrics,
            })
    return jsonify({"columns": columns + pooled})


# Per-mode raw-trial CSV: (fetcher, column list).
_EXPORTERS = {
    "practice": (db.get_trials, ["trial_index", "target_az", "response_az", "signed_error",
                                 "abs_error", "front_back_confusion", "left_right_confusion",
                                 "replay_count", "response_ms"]),
    "cmaa": (db.get_cmaa_trials, ["trial_index", "delta", "high_side", "response_side",
                                  "correct", "response_ms"]),
    "abx": (db.get_abx_trials, ["trial_index", "x_is_a", "response_is_a", "correct",
                                "response_ms"]),
    "extern": (db.get_ext_trials, ["trial_index", "target_az", "rating", "response_ms"]),
    "width": (db.get_width_trials, ["trial_index", "a_first", "chose_a", "response_ms"]),
}
_EXPORTERS["main"] = _EXPORTERS["practice"]


@app.route("/api/export/<int:sid>")
def export_csv(sid):
    session = db.get_session(sid)
    if not session:
        return jsonify({"error": "not found"}), 404
    fetcher, columns = _EXPORTERS.get(session["mode"], _EXPORTERS["main"])
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for trial in fetcher(sid):
        writer.writerow([trial[column] for column in columns])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                f"attachment; filename=session_{sid}_{session['mode']}.csv"
        },
    )


def open_browser():
    webbrowser.open("http://127.0.0.1:5000/")


if __name__ == "__main__":
    db.init()
    threading.Timer(1.0, open_browser).start()
    app.run(host="127.0.0.1", port=5000, threaded=True)
