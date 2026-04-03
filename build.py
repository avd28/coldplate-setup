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
)

OUT_DIR    = pathlib.Path("output")
STATE_FILE = pathlib.Path("build_state.json")

# ── Demo params ───────────────────────────────────────────────────────────────
# All offsets in mm directly.  These are also the live-control defaults shown
# in the dashboard sliders and can be changed at runtime without restarting.
DEMO_PARAMS = {
    # Plate dimensions (mm)
    "length_mm":    200.0,
    "width_mm":     120.0,
    "thickness_mm":   6.0,
    # Offsets (mm) — editable live from the dashboard
    "border_offset_mm":      1.0,   # C3 inset from plate edge
    "stiffening_width_mm":   3.0,   # C3 rib wall thickness
    "peripheral_channel_mm": 5.0,   # C4 band width
    # Height of C3/C4 features (mm)
    "stiffening_height_mm": 4.0,
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
}

# ── State ─────────────────────────────────────────────────────────────────────

def _write_state(params, built, done=False):
    # Serialise only JSON-safe keys for the dashboard
    safe = {k: v for k, v in params.items() if not k.startswith("_")}
    STATE_FILE.write_text(json.dumps(
        {"params": safe, "components": built, "done": done}, indent=2))

# ── SVG projection ────────────────────────────────────────────────────────────

def _svg_rect(x, y, w, h, colour, label, opacity=0.85):
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="{colour}" opacity="{opacity}" stroke="#1a1a2e" stroke-width="1.5" rx="2"/>'
        f'<text x="{x+w/2:.1f}" y="{y+h/2+5:.1f}" '
        f'text-anchor="middle" font-size="11" fill="#fff" font-family="monospace">{label}</text>'
    )

def _build_svg(rp, built_names):
    """rp = resolved params dict (all _mm keys present)."""
    L   = rp["length_mm"]
    W   = rp["width_mm"]
    bo  = rp["border_offset_mm"]
    pcw = rp["peripheral_channel_mm"]
    PAD = 30
    shapes = []

    if "C4_peripheral_channel" in built_names:
        ol = L - 2*bo + 2*pcw
        ow = W - 2*bo + 2*pcw
        shapes.append(_svg_rect(PAD+(L-ol)/2, PAD+(W-ow)/2, ol, ow,
                                COLOURS["C4_peripheral_channel"], "C4"))

    if "C1_outer_plate" in built_names:
        shapes.append(_svg_rect(PAD, PAD, L, W, COLOURS["C1_outer_plate"], "C1"))

    if "C3_stiffening_frame" in built_names:
        shapes.append(_svg_rect(PAD+bo, PAD+bo, L-2*bo, W-2*bo,
                                COLOURS["C3_stiffening_frame"], "C3"))

    if "C2_ports" in built_names:
        for p in rp.get("ports", []):
            edge, off, dia = p["edge"], float(p["offset"]), float(p["diameter"])
            r = dia / 2
            if edge == "left":    cx, cy = PAD,    PAD+off
            elif edge == "right": cx, cy = PAD+L,  PAD+off
            elif edge == "bottom":cx, cy = PAD+off, PAD+W
            else:                 cx, cy = PAD+off, PAD
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
    bo  = rp["border_offset_mm"]
    sw  = rp["stiffening_width_mm"]
    pcw = rp["peripheral_channel_mm"]
    sh  = rp["stiffening_height_mm"]

    print(f"\n  Units: all geometry in mm")
    print(f"  border_offset_mm      = {bo:.2f} mm")
    print(f"  stiffening_width_mm   = {sw:.2f} mm")
    print(f"  peripheral_channel_mm = {pcw:.2f} mm\n")

    OUT_DIR.mkdir(exist_ok=True)
    built = []
    _write_state(rp, built)

    steps = [
        ("C1_outer_plate",
         lambda: make_outer_plate(L, W, T)),
        ("C2_ports",
         lambda: make_ports(L, W, T, rp.get("ports", []))),
        ("C3_stiffening_frame",
         lambda: make_stiffening_frame(L, W, T, bo, sw, sh)),
        ("C4_peripheral_channel",
         lambda: make_peripheral_channel(L, W, T, bo, pcw, sh)),
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
        "border_offset_mm":      "C3 border offset (mm) — inset from plate edge",
        "stiffening_width_mm":   "C3 rib wall thickness (mm)",
        "peripheral_channel_mm": "C4 band width (mm)",
        "stiffening_height_mm":  "C3/C4 feature height (mm)",
    }
    DEFAULTS = {
        "border_offset_mm":      DEMO_PARAMS["border_offset_mm"],
        "stiffening_width_mm":   DEMO_PARAMS["stiffening_width_mm"],
        "peripheral_channel_mm": DEMO_PARAMS["peripheral_channel_mm"],
        "stiffening_height_mm":  DEMO_PARAMS["stiffening_height_mm"],
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

# ── Dashboard launcher ────────────────────────────────────────────────────────

def _launch_dashboard():
    subprocess.Popen([sys.executable, "dashboard.py"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    webbrowser.open("http://localhost:5050")

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        params = DEMO_PARAMS

    elif args[0].lower().endswith((".step", ".stp")):
        from parse_step import extract_params_from_step, merge_user_inputs
        print(f"Parsing {args[0]}…")
        auto = extract_params_from_step(args[0])

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

    elif args[0].lower().endswith(".json"):
        with open(args[0]) as f:
            params = json.load(f)

    else:
        print("Usage: python build.py [input.step [overrides.json] | params.json]")
        sys.exit(1)

    print("Launching dashboard → http://localhost:5050")
    _launch_dashboard()

    print("\nBuilding cold plate components…")
    build(params)
