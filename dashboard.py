"""
dashboard.py  –  Live build-progress dashboard
Run alongside build.py; the dashboard reads state from a shared JSON file.

Endpoints:
    GET  /            → dashboard UI
    GET  /api/state   → current build state (params + component progress)
    POST /api/rebuild → trigger a rebuild with updated offset params
                        Body: { "border_offset_mm": 1.0,
                                "stiffening_width_mm": 3.0,
                                "peripheral_channel_mm": 5.0 }
"""

from flask import Flask, jsonify, send_from_directory, request
import json, os, pathlib, subprocess, sys, tempfile, threading, time

app = Flask(__name__, static_folder="static")
STATE_FILE  = pathlib.Path(__file__).parent / "build_state.json"
_BUILD_DIR  = pathlib.Path(__file__).parent
_BUILD_SCRIPT = _BUILD_DIR / "build.py"

_build_thread = None


def _read_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"params": {}, "components": [], "done": False}


def _run_build(params: dict):
    """
    Run in a background thread.  Spawns `python build.py <tmp>.json --no-dashboard`
    as a subprocess — the same execution path as running the build manually.
    cadquery is imported inside the subprocess, keeping Flask's process light and
    avoiding any sys.path / import-order issues.
    """
    # Write params to a temp JSON file that build.py will read
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", dir=str(_BUILD_DIR), delete=False
    )
    try:
        safe = {k: v for k, v in params.items() if not k.startswith("_")}
        json.dump(safe, tmp)
        tmp.close()

        result = subprocess.run(
            [sys.executable, str(_BUILD_SCRIPT), tmp.name, "--no-dashboard"],
            capture_output=True, text=True
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            err = result.stderr or "Unknown error (no stderr)"
            print(f"[dashboard] rebuild subprocess failed:\n{err}")
            try:
                state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
                state["error"] = err
                state["done"] = True
                STATE_FILE.write_text(json.dumps(state, indent=2))
            except Exception:
                pass
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/state")
def state():
    return jsonify(_read_state())


@app.route("/api/rebuild", methods=["POST"])
def rebuild():
    """Accept updated offset values and re-run the build pipeline."""
    global _build_thread

    # Don't queue a second rebuild while one is already running
    if _build_thread and _build_thread.is_alive():
        return jsonify({"status": "busy", "message": "Build already in progress"}), 409

    overrides = request.get_json(force=True) or {}

    # Merge overrides into the last-known params (plate dims, ports, etc.)
    base = _read_state().get("params", {})
    params = {**base, **overrides}

    # Write a fresh "starting" state with a new build_id NOW, before the thread
    # begins. This prevents poll() from re-reading the old done=True state and
    # resetting lastBuiltCount back to 4 before the build has a chance to clear it.
    build_id = int(time.time() * 1000)
    STATE_FILE.write_text(json.dumps({
        "params": {k: v for k, v in params.items() if not k.startswith("_")},
        "components": [],
        "done": False,
        "build_id": build_id,
    }, indent=2))

    _build_thread = threading.Thread(target=_run_build, args=(params,), daemon=True)
    _build_thread.start()

    return jsonify({"status": "rebuilding", "build_id": build_id})


if __name__ == "__main__":
    app.run(port=5050, debug=False)
