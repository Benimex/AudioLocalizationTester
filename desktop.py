"""Desktop launcher: serve the Flask app locally and show it in a native window.

Double-click entry point for the packaged .exe — no terminal, no browser setup.
Closing the window quits the app. If a native webview is unavailable (e.g. the
WebView2 runtime is missing), it falls back to the system default browser.
"""
import os
import shutil
import threading
import time

import paths
import db
import main

URL = "http://127.0.0.1:5000/"


def _seed_user_dirs():
    """First run next to a fresh .exe: copy bundled default eq/stimuli once."""
    for name, dst in (("eq", paths.EQ_DIR), ("stimuli", paths.STIMULI_DIR)):
        if os.path.isdir(dst):
            continue
        src = os.path.join(paths.BUNDLE, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            os.makedirs(dst, exist_ok=True)


def _serve():
    main.app.run(host="127.0.0.1", port=5000, threaded=True)


def run():
    _seed_user_dirs()
    db.init()
    threading.Thread(target=_serve, daemon=True).start()
    try:
        import webview
        webview.create_window(
            "7.1 Localization Test", URL, width=1280, height=860
        )
        webview.start()  # blocks until the window is closed
    except Exception:
        # No native webview available — use the default browser instead.
        webbrowser_open_when_ready()
        while True:
            time.sleep(3600)


def webbrowser_open_when_ready():
    import webbrowser
    threading.Timer(1.0, lambda: webbrowser.open(URL)).start()


if __name__ == "__main__":
    run()
