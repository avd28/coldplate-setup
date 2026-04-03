"""
dashboard.py  –  Live build-progress dashboard
Run alongside build.py; the dashboard reads state from a shared JSON file.
"""

from flask import Flask, jsonify, send_from_directory
import json, os, pathlib

app = Flask(__name__, static_folder="static")
STATE_FILE = pathlib.Path(__file__).parent / "build_state.json"


def _read_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"params": {}, "components": [], "done": False}


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/state")
def state():
    return jsonify(_read_state())


if __name__ == "__main__":
    app.run(port=5050, debug=False)
