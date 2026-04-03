"""
components.py – Cold Plate Component Generators
================================================
All internal geometry is computed in **millimetres (mm)**.

User-facing inputs use a mix of mm and percentages:
  - Plate dimensions (length, width, thickness)  → mm
  - Port dimensions (diameter, depth)             → mm
  - Port offset along edge                        → mm
  - border_offset_pct   (C3 inset from edge)      → % of port diameter
  - stiffening_width_pct (C3 rib wall thickness)  → % of port diameter
  - peripheral_channel_pct (C4 band width)        → % of port diameter

The helper `resolve_pcts(params)` converts percentages → mm before
any geometry function is called. All make_* functions work in pure mm.

Why percentages?
  Offsets that are proportional to port size stay sensible when you
  scale the plate or swap port diameters — no magic mm numbers to retune.
"""

import cadquery as cq


# ─────────────────────────────────────────────────────────────────────────────
# Percentage → mm resolver
# ─────────────────────────────────────────────────────────────────────────────

def resolve_pcts(params: dict) -> dict:
    """
    Convert percentage-based offset params to mm using the mean port diameter
    as the reference length.  Returns a new dict; does not mutate input.

    Input keys expected:
        border_offset_pct        (float, %)   e.g. 150  → 1.5 × port_dia
        stiffening_width_pct     (float, %)   e.g.  80  → 0.8 × port_dia
        peripheral_channel_pct   (float, %)   e.g. 120  → 1.2 × port_dia

    Output keys added (mm):
        border_offset_mm
        stiffening_width_mm
        peripheral_channel_mm

    If a port list is present, reference diameter = mean of all port diameters.
    If no ports, falls back to thickness as reference (safe default).
    """
    p = dict(params)

    ports = p.get("ports", [])
    if ports:
        ref_dia = sum(pt["diameter"] for pt in ports) / len(ports)  # mm
    else:
        ref_dia = p.get("thickness", 10.0)  # mm fallback

    def pct_to_mm(key_pct, key_mm):
        if key_pct in p and p[key_pct] is not None:
            p[key_mm] = round(p[key_pct] / 100.0 * ref_dia, 4)  # mm

    pct_to_mm("border_offset_pct",      "border_offset_mm")
    pct_to_mm("stiffening_width_pct",   "stiffening_width_mm")
    pct_to_mm("peripheral_channel_pct", "peripheral_channel_mm")

    p["_ref_dia_mm"] = ref_dia  # keep for diagnostics
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Component 1 – Outer plate body
# ─────────────────────────────────────────────────────────────────────────────

def make_outer_plate(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
) -> cq.Workplane:
    """
    Solid rectangular cold plate base.

    Args:
        length_mm    : plate X extent (mm)
        width_mm     : plate Y extent (mm)
        thickness_mm : plate Z extent / depth (mm)

    Returns CadQuery Workplane with origin at (0, 0, 0).
    """
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
    Build port cylinders (to be used as cut-tools against the plate).

    Each port dict:
        edge     (str)   : 'left' | 'right' | 'top' | 'bottom'
        offset   (float) : distance along that edge from the near corner (mm)
        diameter (float) : port inner diameter (mm)
        depth    (float) : how far the cylinder extends into the plate (mm)

    Returns a union of all cylinders, or None if ports list is empty.
    """
    if not ports:
        return None

    result = None
    for p in ports:
        edge   = p["edge"]
        offset = float(p["offset"])    # mm
        dia    = float(p["diameter"])  # mm
        depth  = float(p["depth"])     # mm
        r = dia / 2.0

        if edge == "left":
            cx, cy = 0.0,              offset
            direction = (1, 0, 0)
        elif edge == "right":
            cx, cy = plate_length_mm,  offset
            direction = (-1, 0, 0)
        elif edge == "bottom":
            cx, cy = offset,           0.0
            direction = (0, 1, 0)
        else:  # top
            cx, cy = offset,           plate_width_mm
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
# Component 3 – Solid stiffening frame
# ─────────────────────────────────────────────────────────────────────────────

def make_stiffening_frame(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    border_offset_mm: float,
    stiffening_width_mm: float,
    stiffening_height_mm: float,
) -> cq.Workplane:
    """
    Rectangular frame sitting on top of the plate (Component 1).

    Args:
        border_offset_mm    : gap between plate outer edge and frame outer edge (mm).
                              Derived from border_offset_pct × port_diameter.
                              Leaves room for I/O port ingress.
        stiffening_width_mm : wall thickness of the frame rib (mm).
                              Derived from stiffening_width_pct × port_diameter.
        stiffening_height_mm: height of the frame above the plate surface (mm).

    The frame outer boundary = plate boundary − border_offset on all sides.
    The frame inner boundary = frame outer − stiffening_width on all sides.
    """
    outer_l = length_mm  - 2.0 * border_offset_mm
    outer_w = width_mm   - 2.0 * border_offset_mm
    inner_l = outer_l    - 2.0 * stiffening_width_mm
    inner_w = outer_w    - 2.0 * stiffening_width_mm

    outer = (
        cq.Workplane("XY")
        .rect(outer_l, outer_w)
        .extrude(stiffening_height_mm)
    )

    if inner_l > 0 and inner_w > 0:
        inner = (
            cq.Workplane("XY")
            .rect(inner_l, inner_w)
            .extrude(stiffening_height_mm)
        )
        frame = outer.cut(inner)
    else:
        frame = outer  # plate too small to hollow; fill solid

    return frame.translate((length_mm / 2, width_mm / 2, thickness_mm))


# ─────────────────────────────────────────────────────────────────────────────
# Component 4 – 90° peripheral channel
# ─────────────────────────────────────────────────────────────────────────────

def make_peripheral_channel(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    border_offset_mm: float,
    peripheral_channel_mm: float,
    channel_height_mm: float,
) -> cq.Workplane:
    """
    Outer channel band surrounding Component 3 (no stiffening ribs).

    Args:
        border_offset_mm      : same inset as C3 — defines C4's inner boundary (mm).
        peripheral_channel_mm : radial width of the C4 band (mm).
                                Derived from peripheral_channel_pct × port_diameter.
        channel_height_mm     : height of the band (mm). Typically = stiffening_height.

    C4 inner boundary = C3 outer boundary (plate − border_offset).
    C4 outer boundary = C4 inner boundary + peripheral_channel on all sides.
    """
    c4_inner_l = length_mm - 2.0 * border_offset_mm
    c4_inner_w = width_mm  - 2.0 * border_offset_mm
    c4_outer_l = c4_inner_l + 2.0 * peripheral_channel_mm
    c4_outer_w = c4_inner_w + 2.0 * peripheral_channel_mm

    outer = cq.Workplane("XY").rect(c4_outer_l, c4_outer_w).extrude(channel_height_mm)
    inner = cq.Workplane("XY").rect(c4_inner_l, c4_inner_w).extrude(channel_height_mm)

    return outer.cut(inner).translate((length_mm / 2, width_mm / 2, thickness_mm))
