"""
build.py – Cold Plate Builder entry point
==========================================
All geometry is in mm.  Offsets are supplied directly in mm:

    border_offset_mm      (mm)  C3 inset from plate edge          default 1 mm
    stiffening_width_mm   (mm)  C3 rib wall thickness             default 3 mm
    peripheral_channel_mm (mm)  C4 band width                     default 5 mm

Percentage-based keys (*_pct) are still accepted for backwards
compatibility and are resolved by resolve_pcts() in components.py.

Usage:
    python build.py                          # built-in demo
    python build.py input.step               # auto-parse + 3-value prompt
    python build.py input.step overrides.json
    python build.py params.json
"""

import sys, json, time, pathlib, subprocess, webbrowser
import cadquery as cq
from components import (
    resolve_pcts,
    make_outer_plate,
    make_stiffening_frame,
    make_peripheral_channel,
    make_ports,
    make_centreline_slice,
)

_HERE      = pathlib.Path(__file__).parent
OUT_DIR    = _HERE / "output"
STATE_FILE = _HERE / "build_state.json"

# ── Demo params ───────────────────────────────────────────────────────────────
# All offsets in mm directly.  These are also the live-control defaults shown
# in the dashboard sliders and can be changed at runtime without restarting.
DEMO_PARAMS = {
    # Plate dimensions (mm)
    "length_mm":    200.0,
    "width_mm":     120.0,
    "thickness_mm":   6.0,
    # Offsets (mm) — editable live from the dashboard
    "stiffening_width_mm":   3.0,   # C3 rib wall thickness
    "peripheral_channel_mm": 5.0,   # C4 band width
    # Height of C3/C4 features (mm)
    "stiffening_height_mm": 4.0,
    # C5 – centreline slice half-width (mm)
    "centreline_extrude_mm": 10.0,
    # Ports (all mm)
    "ports": [
        {"edge": "left",  "offset": 60.0, "diameter": 10.0, "depth": 20.0},
        {"edge": "right", "offset": 60.0, "diameter": 10.0, "depth": 20.0},
    ],
}

COLOURS = {
    "C1_outer_plate":        "#4A9EFF",
    "C2_ports":              "#FF6B6B",
    "C3_stiffening_frame":   "#FFD93D",
    "C4_peripheral_channel": "#6BCB77",
    "C5_centreline_slice":   "#B48EFF",
}

# ── State ─────────────────────────────────────────────────────────────────────

def _write_state(params, built, done=False):
    # Serialise only JSON-safe keys for the dashboard
    safe = {k: v for k, v in params.items() if not k.startswith("_")}
    # Preserve build_id across writes so the dashboard can detect new builds
    try:
        prev = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except Exception:
        prev = {}
    state = {"params": safe, "components": built, "done": done}
    if "build_id" in prev:
        state["build_id"] = prev["build_id"]
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ── SVG projection ────────────────────────────────────────────────────────────

def _svg_rect(x, y, w, h, colour, label="", opacity=0.85):
    r = (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="{colour}" opacity="{opacity}" stroke="#1a1a2e" stroke-width="1.5" rx="2"/>'
    )
    if label:
        r += (f'<text x="{x+w/2:.1f}" y="{y+h/2+5:.1f}" '
              f'text-anchor="middle" font-size="11" fill="#fff" '
              f'font-family="monospace">{label}</text>')
    return r

def _svg_label(x, y, text):
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
            f'font-size="10" fill="#fff" font-family="monospace">{text}</text>')

BG_COLOUR = "#0d0f14"  # dashboard background — used for SVG cutouts

def _build_svg(rp, built_names):
    """
    Top-down projection.  Layer order (back → front):
      C1 plate → C3 frame (outer filled, inner cut) → C4 channel (outer filled,
      inner cut) → port gap markers → port circles
    """
    L   = rp["length_mm"]
    W   = rp["width_mm"]
    sw  = rp.get("stiffening_width_mm",   3.0)
    pcw = rp.get("peripheral_channel_mm", 5.0)
    cem = rp.get("centreline_extrude_mm", 10.0)
    PAD = 30
    shapes = []

    # C1 – plate base
    if "C1_outer_plate" in built_names:
        shapes.append(_svg_rect(PAD, PAD, L, W, COLOURS["C1_outer_plate"], "C1"))

    # C3 – stiffening frame: flush with plate edge, inner cutout
    if "C3_stiffening_frame" in built_names:
        shapes.append(_svg_rect(PAD, PAD, L, W,
                                COLOURS["C3_stiffening_frame"]))
        c3i_w = L - 2*sw
        c3i_h = W - 2*sw
        if c3i_w > 0 and c3i_h > 0:
            shapes.append(_svg_rect(PAD+sw, PAD+sw, c3i_w, c3i_h,
                                    BG_COLOUR, opacity=1.0))
        # Label in the top bar of the frame
        shapes.append(_svg_label(PAD + L/2, PAD + sw/2 + 4, "C3"))

    # C4 – peripheral channel: directly inside C3
    if "C4_peripheral_channel" in built_names:
        inset = sw
        shapes.append(_svg_rect(PAD+inset, PAD+inset, L-2*inset, W-2*inset,
                                COLOURS["C4_peripheral_channel"]))
        c4i_w = L - 2*(inset+pcw)
        c4i_h = W - 2*(inset+pcw)
        if c4i_w > 0 and c4i_h > 0:
            shapes.append(_svg_rect(PAD+inset+pcw, PAD+inset+pcw, c4i_w, c4i_h,
                                    BG_COLOUR, opacity=1.0))
        shapes.append(_svg_label(PAD + L/2, PAD + inset + pcw/2 + 4, "C4"))

    # C5 – centreline slice band (top-down view: thin strip at port axis)
    if "C5_centreline_slice" in built_names:
        lrp = [p for p in rp.get("ports", []) if p["edge"] in ("left", "right")]
        tbp = [p for p in rp.get("ports", []) if p["edge"] in ("top", "bottom")]
        C5_COL = COLOURS["C5_centreline_slice"]
        if lrp:
            cy = sum(p["offset"] for p in lrp) / len(lrp)
            shapes.append(_svg_rect(PAD, PAD + cy - cem, L, cem * 2,
                                    C5_COL, opacity=0.55))
            shapes.append(_svg_label(PAD + 18, PAD + cy + 4, "C5"))
        elif tbp:
            cx = sum(p["offset"] for p in tbp) / len(tbp)
            shapes.append(_svg_rect(PAD + cx - cem, PAD, cem * 2, W,
                                    C5_COL, opacity=0.55))
            shapes.append(_svg_label(PAD + cx + 4, PAD + 14, "C5"))
        else:
            cy = W / 2.0
            shapes.append(_svg_rect(PAD, PAD + cy - cem, L, cem * 2,
                                    C5_COL, opacity=0.55))
            shapes.append(_svg_label(PAD + 18, PAD + cy + 4, "C5"))

    # Port gap markers + port circles
    if "C2_ports" in built_names:
        for p in rp.get("ports", []):
            edge = p["edge"]
            off  = float(p["offset"])
            dia  = float(p["diameter"])
            r    = dia / 2

            # Dark rectangle over the C3 wall at the port position (gap visualisation)
            if "C3_stiffening_frame" in built_names:
                if edge == "left":
                    shapes.append(f'<rect x="{PAD:.1f}" y="{PAD+off-r:.1f}" '
                                  f'width="{sw:.1f}" height="{dia:.1f}" '
                                  f'fill="{BG_COLOUR}" opacity="1"/>')
                elif edge == "right":
                    shapes.append(f'<rect x="{PAD+L-sw:.1f}" y="{PAD+off-r:.1f}" '
                                  f'width="{sw:.1f}" height="{dia:.1f}" '
                                  f'fill="{BG_COLOUR}" opacity="1"/>')
                elif edge == "bottom":
                    shapes.append(f'<rect x="{PAD+off-r:.1f}" y="{PAD+W-sw:.1f}" '
                                  f'width="{dia:.1f}" height="{sw:.1f}" '
                                  f'fill="{BG_COLOUR}" opacity="1"/>')
                else:  # top
                    shapes.append(f'<rect x="{PAD+off-r:.1f}" y="{PAD:.1f}" '
                                  f'width="{dia:.1f}" height="{sw:.1f}" '
                                  f'fill="{BG_COLOUR}" opacity="1"/>')

            # Port circle at the plate edge
            if edge == "left":    cx, cy = PAD,     PAD+off
            elif edge == "right": cx, cy = PAD+L,   PAD+off
            elif edge == "bottom":cx, cy = PAD+off,  PAD+W
            else:                 cx, cy = PAD+off,  PAD
            shapes.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
                f'fill="{COLOURS["C2_ports"]}" stroke="#1a1a2e" stroke-width="1.5"/>'
            )

    SVG_W, SVG_H = L + 2*PAD, W + 2*PAD
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {SVG_W:.1f} {SVG_H:.1f}" '
            f'width="{SVG_W:.0f}" height="{SVG_H:.0f}">'
            + "\n".join(shapes) + "</svg>")

# ── Build pipeline ────────────────────────────────────────────────────────────

def build(params: dict):
    """
    params must contain either:
      - *_mm keys (already resolved), OR
      - *_pct keys (will be resolved here via resolve_pcts)
    """
    rp = resolve_pcts(params)   # ensures all _mm keys exist

    L   = rp["length_mm"]
    W   = rp["width_mm"]
    T   = rp["thickness_mm"]
    sw  = rp["stiffening_width_mm"]
    pcw = rp["peripheral_channel_mm"]
    sh  = rp["stiffening_height_mm"]
    cem = rp.get("centreline_extrude_mm", 10.0)
    sp  = rp.get("step_path")

    print(f"\n  Units: all geometry in mm")
    print(f"  stiffening_width_mm   = {sw:.2f} mm")
    print(f"  peripheral_channel_mm = {pcw:.2f} mm")
    print(f"  centreline_extrude_mm = {cem:.2f} mm\n")

    OUT_DIR.mkdir(exist_ok=True)
    built = []
    _write_state(rp, built)

    steps = [
        ("C1_outer_plate",
         lambda: make_outer_plate(L, W, T)),
        ("C2_ports",
         lambda: make_ports(L, W, T, rp.get("ports", []))),
        ("C3_stiffening_frame",
         lambda: make_stiffening_frame(L, W, T, sw, sh, rp.get("ports", []))),
        ("C4_peripheral_channel",
         lambda: make_peripheral_channel(L, W, T, sw, pcw, sh)),
        ("C5_centreline_slice",
         lambda: make_centreline_slice(L, W, T, rp.get("ports", []), cem, sp)),
    ]

    for name, fn in steps:
        print(f"  Building {name}…")
        shape = fn()
        if shape is not None:
            cq.exporters.export(shape, str(OUT_DIR / f"{name}.step"))
        built.append({
            "name":   name,
            "colour": COLOURS[name],
            "svg":    _build_svg(rp, [b["name"] for b in built] + [name]),
        })
        _write_state(rp, built)
        time.sleep(0.4)

    _write_state(rp, built, done=True)
    print(f"\n✓  All components written to ./{OUT_DIR}/")

# ── Interactive prompt ────────────────────────────────────────────────────────

def _prompt_missing(params: dict, missing_keys: list) -> dict:
    PROMPTS = {
        "stiffening_width_mm":    "C3 rib wall thickness (mm)",
        "peripheral_channel_mm":  "C4 band width (mm)",
        "stiffening_height_mm":   "C3/C4 feature height (mm)",
        "centreline_extrude_mm":  "C5 centreline slice half-width (mm)",
    }
    DEFAULTS = {
        "stiffening_width_mm":   DEMO_PARAMS["stiffening_width_mm"],
        "peripheral_channel_mm": DEMO_PARAMS["peripheral_channel_mm"],
        "stiffening_height_mm":  DEMO_PARAMS["stiffening_height_mm"],
        "centreline_extrude_mm": DEMO_PARAMS["centreline_extrude_mm"],
    }

    print("\n── Auto-inferred from STEP ─────────────────────────────────────")
    for k in ["length_mm", "width_mm", "thickness_mm"]:
        print(f"  {k:30s} {params[k]:.3f} mm")
    ports = params.get("ports", [])
    if ports:
        print(f"  {'ports':30s} {len(ports)} detected")
        for i, p in enumerate(ports):
            print(f"    [{i}] edge={p['edge']:6s}  offset={p['offset']:.1f} mm  "
                  f"dia={p['diameter']:.1f} mm  depth={p['depth']:.1f} mm")
    else:
        print(f"  {'ports':30s} none detected")

    print("\n── Supply remaining design-intent values (all in mm) ───────────")
    print("   Press Enter to accept the default shown in brackets.\n")
    for key in missing_keys:
        label   = PROMPTS.get(key, key)
        default = DEFAULTS.get(key)
        hint    = f"  {label} [{default} mm]: "
        raw     = input(hint).strip()
        params[key] = float(raw) if raw else default
    return params

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import threading
    args = sys.argv[1:]

    # --no-dashboard: just run the build and exit (used by dashboard rebuild subprocess)
    no_dashboard = "--no-dashboard" in args
    args = [a for a in args if a != "--no-dashboard"]

    if not args:
        params = DEMO_PARAMS

    elif args[0].lower().endswith((".step", ".stp")):
        from parse_step import extract_params_from_step, merge_user_inputs
        step_abs = str(pathlib.Path(args[0]).resolve())
        print(f"Parsing {args[0]}…")
        auto = extract_params_from_step(step_abs)

        if len(args) > 1:
            with open(args[1]) as f:
                overrides = json.load(f)
            params = merge_user_inputs(auto, overrides)
        else:
            params = dict(auto)
            missing = auto.get("_needs_input", [])
            if missing:
                params = _prompt_missing(params, missing)
            params = {k: v for k, v in params.items() if not k.startswith("_")}

        # Store the absolute STEP path so C5 and rebuilds can find it
        params["step_path"] = step_abs

    elif args[0].lower().endswith(".json"):
        with open(args[0]) as f:
            params = json.load(f)

    else:
        print("Usage: python build.py [input.step [overrides.json] | params.json]")
        sys.exit(1)

    if no_dashboard:
        # Called by the dashboard's rebuild endpoint — just build and exit
        print("\nBuilding cold plate components…")
        build(params)
    else:
        # Normal run: build in a background thread, Flask in the main thread.
        # This keeps the process alive so the dashboard stays up for rebuilds.
        build_thread = threading.Thread(target=build, args=(params,), daemon=True)
        build_thread.start()

        # Open the browser shortly after Flask starts
        threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5050")).start()

        print("Dashboard → http://localhost:5050")
        print("Press Ctrl+C to stop.\n")

        from dashboard import app
        app.run(port=5050, debug=False, use_reloader=False)
