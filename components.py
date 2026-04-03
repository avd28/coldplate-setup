"""
components.py – Cold Plate Component Generators
================================================
All geometry is in millimetres (mm).

Layer order from outside in:
  C1  Outer plate body (full solid)
  C2  Inlet / outlet port cut-outs (cylinders cut into C1)
  C3  Stiffening plates – outer edge flush with the plate edge, wall
      thickness stiffening_width_mm.  Gaps are cut where each port
      enters so fluid can flow through.
  C4  Peripheral channel – sits directly inside C3 (outer edge = C3
      inner edge), band width peripheral_channel_mm.  Leaves an open
      interior for coolant flow.
  C5  Centreline slice – a slab of thickness 2*centreline_extrude_mm
      centred on the port-to-port axis, intersected with the original
      STEP solid to expose all internal port geometry at that plane.
"""

import pathlib

import cadquery as cq


# ─────────────────────────────────────────────────────────────────────────────
# Percentage → mm resolver  (backwards-compat shim; direct _mm keys pass through)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_pcts(params: dict) -> dict:
    """
    If *_pct keys are present, convert them to *_mm using mean port diameter
    as the reference.  Direct *_mm values are left untouched.
    Returns a new dict; does not mutate input.
    """
    p = dict(params)

    ports = p.get("ports", [])
    if ports:
        ref_dia = sum(pt["diameter"] for pt in ports) / len(ports)
    else:
        ref_dia = p.get("thickness_mm", p.get("thickness", 10.0))

    def pct_to_mm(key_pct, key_mm):
        if key_pct in p and p[key_pct] is not None:
            p[key_mm] = round(p[key_pct] / 100.0 * ref_dia, 4)

    pct_to_mm("stiffening_width_pct",   "stiffening_width_mm")
    pct_to_mm("peripheral_channel_pct", "peripheral_channel_mm")

    p["_ref_dia_mm"] = ref_dia
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Component 1 – Outer plate body
# ─────────────────────────────────────────────────────────────────────────────

def make_outer_plate(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
) -> cq.Workplane:
    """Solid rectangular cold plate base."""
    return (
        cq.Workplane("XY")
        .box(length_mm, width_mm, thickness_mm)
        .translate((length_mm / 2, width_mm / 2, thickness_mm / 2))
    )


# ─────────────────────────────────────────────────────────────────────────────
# Component 2 – Inlet / outlet ports
# ─────────────────────────────────────────────────────────────────────────────

def make_ports(
    plate_length_mm: float,
    plate_width_mm: float,
    plate_thickness_mm: float,
    ports: list[dict],
) -> cq.Workplane | None:
    """
    Build port cylinders (cut-tools against the plate).

    Each port dict:
        edge     : 'left' | 'right' | 'top' | 'bottom'
        offset   : distance along that edge from the near corner (mm)
        diameter : port inner diameter (mm)
        depth    : how far the cylinder extends into the plate (mm)
    """
    if not ports:
        return None

    result = None
    for p in ports:
        edge   = p["edge"]
        offset = float(p["offset"])
        dia    = float(p["diameter"])
        depth  = float(p["depth"])
        r = dia / 2.0

        if edge == "left":
            cx, cy = 0.0,               offset
            direction = (1, 0, 0)
        elif edge == "right":
            cx, cy = plate_length_mm,   offset
            direction = (-1, 0, 0)
        elif edge == "bottom":
            cx, cy = offset,            0.0
            direction = (0, 1, 0)
        else:  # top
            cx, cy = offset,            plate_width_mm
            direction = (0, -1, 0)

        cz = plate_thickness_mm / 2.0
        cyl = (
            cq.Workplane("XY")
            .circle(r)
            .extrude(depth)
            .rotate((0, 0, 0), direction, 90)
            .translate((cx, cy, cz))
        )
        result = cyl if result is None else result.union(cyl)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Component 3 – Stiffening plates
# ─────────────────────────────────────────────────────────────────────────────

def make_stiffening_frame(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    stiffening_width_mm: float,
    stiffening_height_mm: float,
    ports: list[dict] | None = None,
) -> cq.Workplane:
    """
    Rectangular stiffening frame sitting on top of C1.

    Outer boundary is flush with the plate edge.
    Wall thickness = stiffening_width_mm.
    Box-shaped gaps are cut where each port enters so fluid can flow in/out.
    With left and right ports this leaves two intact horizontal bars
    (top and bottom stiffening plates).

    Args:
        stiffening_width_mm : wall thickness of each stiffening bar (mm)
        stiffening_height_mm: height of the frame above C1 surface (mm)
        ports               : list of port dicts (same format as make_ports)
    """
    inner_l = length_mm - 2.0 * stiffening_width_mm
    inner_w = width_mm  - 2.0 * stiffening_width_mm

    outer = cq.Workplane("XY").rect(length_mm, width_mm).extrude(stiffening_height_mm)

    if inner_l > 0 and inner_w > 0:
        inner = cq.Workplane("XY").rect(inner_l, inner_w).extrude(stiffening_height_mm)
        frame = outer.cut(inner)
    else:
        frame = outer  # plate too small to hollow — fill solid

    # Translate to sit on top of C1 (plate coords: origin at plate corner)
    frame = frame.translate((length_mm / 2, width_mm / 2, thickness_mm))

    # Cut gaps through the frame walls at each port location so fluid can pass
    for p in (ports or []):
        edge   = p["edge"]
        offset = float(p["offset"])
        dia    = float(p["diameter"])
        m      = 1.0  # margin so the cut fully clears the wall faces

        wall_t = stiffening_width_mm + 2 * m   # slightly wider than the wall
        gap_h  = stiffening_height_mm + 2 * m  # slightly taller than the frame
        gz     = thickness_mm + stiffening_height_mm / 2.0

        if edge == "left":
            cut = (cq.Workplane("XY")
                   .box(wall_t, dia, gap_h)
                   .translate((stiffening_width_mm / 2.0, offset, gz)))
        elif edge == "right":
            cut = (cq.Workplane("XY")
                   .box(wall_t, dia, gap_h)
                   .translate((length_mm - stiffening_width_mm / 2.0, offset, gz)))
        elif edge == "bottom":
            cut = (cq.Workplane("XY")
                   .box(dia, wall_t, gap_h)
                   .translate((offset, stiffening_width_mm / 2.0, gz)))
        else:  # top
            cut = (cq.Workplane("XY")
                   .box(dia, wall_t, gap_h)
                   .translate((offset, width_mm - stiffening_width_mm / 2.0, gz)))

        frame = frame.cut(cut)

    return frame


# ─────────────────────────────────────────────────────────────────────────────
# Component 4 – Peripheral channel (inside C3)
# ─────────────────────────────────────────────────────────────────────────────

def make_peripheral_channel(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    stiffening_width_mm: float,
    peripheral_channel_mm: float,
    channel_height_mm: float,
) -> cq.Workplane:
    """
    Peripheral channel band sitting inside C3 on top of C1.

    C4 outer boundary = C3 inner boundary = plate edge − stiffening_width_mm
    C4 inner boundary = C4 outer − peripheral_channel_mm on all sides.

    This leaves an open interior inside C4 for coolant flow and ensures
    C4 never extends outside the stiffening walls.

    Args:
        stiffening_width_mm   : C3 wall thickness — defines where C4 starts (mm)
        peripheral_channel_mm : radial band width of C4 (mm)
        channel_height_mm     : height of the band, typically = stiffening_height (mm)
    """
    inset = stiffening_width_mm   # C4 outer = C3 inner edge

    c4_outer_l = length_mm - 2.0 * inset
    c4_outer_w = width_mm  - 2.0 * inset
    c4_inner_l = c4_outer_l - 2.0 * peripheral_channel_mm
    c4_inner_w = c4_outer_w - 2.0 * peripheral_channel_mm

    outer = cq.Workplane("XY").rect(c4_outer_l, c4_outer_w).extrude(channel_height_mm)

    if c4_inner_l > 0 and c4_inner_w > 0:
        inner = cq.Workplane("XY").rect(c4_inner_l, c4_inner_w).extrude(channel_height_mm)
        channel = outer.cut(inner)
    else:
        channel = outer  # channel_mm too large — fill solid

    return channel.translate((length_mm / 2, width_mm / 2, thickness_mm))


# ─────────────────────────────────────────────────────────────────────────────
# Component 5 – Centreline slice
# ─────────────────────────────────────────────────────────────────────────────

def make_centreline_slice(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    ports: list[dict],
    centreline_extrude_mm: float,
    step_path: str | None = None,
) -> cq.Workplane:
    """
    C5: Mid-thickness slab spanning the FULL plate footprint, extruded
    symmetrically ±centreline_extrude_mm about the plate's Z-midplane.

    The slice plane is XY at Z = T/2 (the plate's mid-thickness centreplane).
    It spans the entire length × width so it captures the full cross-section
    of the plate at that level, including the circular port bores where the
    horizontal port cylinders pierce that plane.

    When step_path is provided the slab is intersected with the real STEP
    solid, preserving all actual geometry (port bores, fillets, etc.).
    When step_path is absent (demo mode) a parametric rectangular slab is
    returned instead.

    Args:
        length_mm             : plate length in X (mm)
        width_mm              : plate width  in Y (mm)
        thickness_mm          : plate thickness in Z (mm)
        ports                 : port list (unused in slab creation but kept
                                for API consistency)
        centreline_extrude_mm : half-thickness of the slab in Z (mm)
        step_path             : path to the original STEP file (optional)
    """
    MARGIN = 5.0   # extra so the slab fully clips the solid on all sides

    # ── STEP-based intersection (preferred) ───────────────────────────────────
    if step_path and pathlib.Path(step_path).exists():
        solid_wp = cq.importers.importStep(step_path)
        bb = solid_wp.val().BoundingBox()
        cx = (bb.xmin + bb.xmax) / 2.0
        cy = (bb.ymin + bb.ymax) / 2.0
        cz = (bb.zmin + bb.zmax) / 2.0   # true Z-midplane of the STEP solid
        BL = bb.xmax - bb.xmin
        BW = bb.ymax - bb.ymin

        # Slab: full footprint in XY, thin in Z (±extrude_mm around midplane)
        slab = (cq.Workplane("XY")
                .box(BL + 2 * MARGIN, BW + 2 * MARGIN, centreline_extrude_mm * 2)
                .translate((cx, cy, cz)))

        return solid_wp.intersect(slab)

    # ── Parametric fallback (demo / no STEP) ──────────────────────────────────
    # Plate body: (0,0,0) → (L,W,T) in plate coordinates.
    return (cq.Workplane("XY")
            .box(length_mm, width_mm, centreline_extrude_mm * 2)
            .translate((length_mm / 2.0, width_mm / 2.0, thickness_mm / 2.0)))
