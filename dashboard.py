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
import json, pathlib, sys, threading

app = Flask(__name__, static_folder="static")
STATE_FILE  = pathlib.Path(__file__).parent / "build_state.json"
_BUILD_DIR  = pathlib.Path(__file__).parent

# Lock so only one rebuild runs at a time
_build_lock  = threading.Lock()
_build_thread = None


def _read_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"params": {}, "components": [], "done": False}


def _run_build(params: dict):
    """Run in a background thread; imports build lazily to avoid import-time side-effects."""
    # Ensure the coldplate directory is on the path so build/components are importable.
    # OUT_DIR and STATE_FILE in build.py are absolute (anchored to __file__), so no
    # os.chdir needed — safe to call from a thread without affecting Flask's cwd.
    pkg = str(_BUILD_DIR)
    if pkg not in sys.path:
        sys.path.insert(0, pkg)

    try:
        from build import build  # noqa: PLC0415
        build(params)
    except Exception:
        import traceback, json, pathlib
        err = traceback.format_exc()
        print(f"[dashboard] rebuild failed:\n{err}")
        # Write error into state so the dashboard can surface it
        sf = _BUILD_DIR / "build_state.json"
        try:
            state = json.loads(sf.read_text()) if sf.exists() else {}
            state["error"] = err
            state["done"] = True
            sf.write_text(json.dumps(state, indent=2))
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

    _build_thread = threading.Thread(target=_run_build, args=(params,), daemon=True)
    _build_thread.start()

    return jsonify({"status": "rebuilding", "params": params})


if __name__ == "__main__":
    app.run(port=5050, debug=False)
