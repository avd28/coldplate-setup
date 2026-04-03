"""
parse_step.py – Extract cold plate parameters from a STEP file
==============================================================
Auto-detected:  length_mm, width_mm, thickness_mm, ports
Needs user:     border_offset_mm, stiffening_width_mm,
                peripheral_channel_mm, stiffening_height_mm

Port detection strategy
-----------------------
A port stub is a cylinder protruding from a plate face.
Cylindrical faces have a bounding box where two spans are equal
(the diameter) and one is longer (the depth along the axis).
The axis direction is identified as whichever span is the longest,
and the port is assigned to the nearest plate edge accordingly.
All values returned in mm.
"""

import cadquery as cq


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _bb(shape):
    b = shape.BoundingBox()
    return b.xmin, b.ymin, b.zmin, b.xmax, b.ymax, b.zmax


def _load_solid(step_path: str):
    """Load STEP and return the largest solid as a CadQuery Shape."""
    wp = cq.importers.importStep(step_path)
    solids = wp.solids().vals()
    if not solids:
        raise ValueError("No solids found in STEP file.")
    def vol(s):
        x0,y0,z0,x1,y1,z1 = _bb(s)
        return (x1-x0)*(y1-y0)*(z1-z0)
    return max(solids, key=vol)


def _orient_to_xy(solid):
    """Rotate solid so its shortest bounding-box dimension aligns with Z."""
    x0,y0,z0,x1,y1,z1 = _bb(solid)
    dims = sorted([("x",x1-x0),("y",y1-y0),("z",z1-z0)], key=lambda d: d[1])
    thin = dims[0][0]
    if thin == "z":   return solid
    elif thin == "x": return solid.rotate((0,0,0),(0,1,0), 90)
    else:             return solid.rotate((0,0,0),(1,0,0), 90)


# ── Cylindrical face → port detection ────────────────────────────────────────

def _detect_ports(solid) -> list[dict]:
    """
    Find all cylindrical faces on the solid and interpret each as a port stub.

    A cylindrical face bounding box has the form:
        axis=X:  dx=depth, dy=diameter, dz=diameter  (dy ≈ dz, dx is longest)
        axis=Y:  dx=diameter, dy=depth, dz=diameter  (dx ≈ dz, dy is longest)
        axis=Z:  dx=diameter, dy=diameter, dz=depth  (dx ≈ dy, dz is longest)

    We determine the axis from whichever span is strictly the longest,
    confirm the other two are within 5 % of each other (circularity),
    then map the face centre to the nearest plate edge.

    Returns a list of port dicts (all values in mm).
    """
    px0,py0,pz0,px1,py1,pz1 = _bb(solid)
    L, W, T = px1-px0, py1-py0, pz1-pz0
    EDGE_TOL = max(T, 10.0)  # how far outside the plate boundary a stub can reach

    ports = []
    for face in solid.Faces():
        if face.geomType() != "CYLINDER":
            continue

        fb = face.BoundingBox()
        dx = fb.xmax - fb.xmin
        dy = fb.ymax - fb.ymin
        dz = fb.zmax - fb.zmin
        spans = {"x": dx, "y": dy, "z": dz}

        # Port axis = longest span
        axis = max(spans, key=spans.get)
        depth_mm = round(spans[axis], 3)

        # The two diameter spans
        dia_keys = [k for k in spans if k != axis]
        d1, d2 = spans[dia_keys[0]], spans[dia_keys[1]]

        # Circularity check: two non-axis spans must be within 5 %
        if abs(d1 - d2) / max(d2, 1e-6) > 0.05:
            continue  # not a round port (e.g. a blend/fillet face)

        diameter_mm = round((d1 + d2) / 2.0, 3)

        # Face centre (mm, absolute)
        cx = (fb.xmin + fb.xmax) / 2
        cy = (fb.ymin + fb.ymax) / 2
        cz = (fb.zmin + fb.zmax) / 2

        # Normalised to plate origin
        nx = cx - px0
        ny = cy - py0

        # Map axis + position → edge name + offset
        if axis == "x":
            # Port enters from left or right face
            edge_name = "left" if cx < (px0 + px1) / 2 else "right"
            offset_mm = round(ny, 3)
        elif axis == "y":
            # Port enters from bottom or top face
            edge_name = "bottom" if cy < (py0 + py1) / 2 else "top"
            offset_mm = round(nx, 3)
        else:
            # axis == "z" — vertical bore through plate top/bottom, not a side port
            continue

        ports.append({
            "edge":     edge_name,
            "offset":   offset_mm,   # mm from plate origin along that edge
            "diameter": diameter_mm, # mm
            "depth":    depth_mm,    # mm (length of stub)
        })

    # Deduplicate near-identical entries (same face seen twice)
    unique = []
    for p in ports:
        if not any(p["edge"] == q["edge"] and abs(p["offset"] - q["offset"]) < 2.0
                   for q in unique):
            unique.append(p)

    return unique


# ── Public API ────────────────────────────────────────────────────────────────

def extract_params_from_step(step_path: str) -> dict:
    """
    Load a STEP file and return a params dict ready for build.py.

    Auto-filled (mm):   length_mm, width_mm, thickness_mm
    Auto-filled (list): ports  [{edge, offset(mm), diameter(mm), depth(mm)}]
    Set to None:        border_offset_mm, stiffening_width_mm,
                        peripheral_channel_mm, stiffening_height_mm
    """
    solid = _load_solid(step_path)
    solid = _orient_to_xy(solid)

    x0,y0,z0,x1,y1,z1 = _bb(solid)
    ports = _detect_ports(solid)

    # Bounding box includes port stubs. Subtract max stub depth per edge
    # to recover the true flat plate dimensions.
    def _max_depth(edge_name):
        return max((p["depth"] for p in ports if p["edge"] == edge_name), default=0.0)

    plate_length = round((x1-x0) - _max_depth("left")   - _max_depth("right"),  3)
    plate_width  = round((y1-y0) - _max_depth("bottom")  - _max_depth("top"),    3)
    plate_thick  = round(z1-z0, 3)

    return {
        "length_mm":               plate_length,
        "width_mm":                plate_width,
        "thickness_mm":            plate_thick,
        "border_offset_mm":        None,
        "stiffening_width_mm":     None,
        "peripheral_channel_mm":   None,
        "stiffening_height_mm":    None,
        "ports":                   ports,
        "_inferred":    ["length_mm","width_mm","thickness_mm","ports"],
        "_needs_input": ["border_offset_mm","stiffening_width_mm",
                         "peripheral_channel_mm","stiffening_height_mm"],
    }


def merge_user_inputs(auto: dict, overrides: dict) -> dict:
    """Merge auto-extracted params with user overrides. User always wins. Strips _keys."""
    merged = {k: v for k, v in auto.items() if not k.startswith("_")}
    merged.update(overrides)
    return merged


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: python parse_step.py input.step [overrides.json]")
        sys.exit(1)

    auto = extract_params_from_step(sys.argv[1])

    print("\n── Auto-inferred from STEP ──────────────────────────────────────")
    for k in ["length_mm","width_mm","thickness_mm"]:
        print(f"  {k:30s} {auto[k]:.3f} mm")
    print(f"  {'ports detected':30s} {len(auto['ports'])}")
    for i, p in enumerate(auto["ports"]):
        print(f"    [{i}] edge={p['edge']:6s}  offset={p['offset']:.1f} mm  "
              f"dia={p['diameter']:.1f} mm  depth={p['depth']:.1f} mm")

    print("\n── Needs user input (all in mm) ─────────────────────────────────")
    for k in auto["_needs_input"]:
        print(f"  {k}")

    if len(sys.argv) > 2:
        with open(sys.argv[2]) as f:
            ov = json.load(f)
        final = merge_user_inputs(auto, ov)
        print("\n── Merged params ────────────────────────────────────────────────")
        print(json.dumps({k:v for k,v in final.items() if not k.startswith("_")}, indent=2))
