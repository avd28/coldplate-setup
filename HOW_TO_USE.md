# How to Use – Cold Plate Builder

---

## What this tool does

Given a cold plate STEP file, it auto-extracts geometry and generates
four output components, each exported as its own STEP file:

| Component | What it is |
|-----------|------------|
| **C1** – Outer plate | Base solid from your input footprint |
| **C2** – I/O ports | Inlet/outlet port stubs, detected from geometry |
| **C3** – Stiffening frame | Solid border frame, inset from the plate edge |
| **C4** – Peripheral channel | 90° channel band surrounding C3 |

A live browser dashboard shows each component appearing to scale as it builds.

---

## Install

```bash
pip install cadquery flask
```

---

## Running

### Option A – Supply your STEP file *(recommended)*

```bash
python build.py your_plate.step
```

The script auto-detects plate dimensions and all port positions, diameters
and depths from cylindrical faces in the geometry. It then prompts you for
the **4 design-intent values** it cannot read from geometry:

```
  C3 border offset, as % of port diameter  (%): 150
  C3 rib wall width, as % of port diameter (%):  80
  C4 band width, as % of port diameter     (%): 120
  C3/C4 feature height (mm, not %)         (mm):  4
```

That's it — everything else is automatic.

---

### Option B – STEP + overrides JSON *(zero prompts, good for pipelines)*

Create a small JSON with just the 4 design-intent values:

```json
{
  "border_offset_pct":      150.0,
  "stiffening_width_pct":    80.0,
  "peripheral_channel_pct": 120.0,
  "stiffening_height_mm":     4.0
}
```

```bash
python build.py your_plate.step overrides.json
```

---

### Option C – Full manual JSON *(no STEP file needed)*

```json
{
  "length_mm": 200.0,
  "width_mm":  120.0,
  "thickness_mm": 6.0,
  "border_offset_pct":      150.0,
  "stiffening_width_pct":    80.0,
  "peripheral_channel_pct": 120.0,
  "stiffening_height_mm":    4.0,
  "ports": [
    { "edge": "left",  "offset": 60.0, "diameter": 10.0, "depth": 18.0 },
    { "edge": "right", "offset": 60.0, "diameter": 10.0, "depth": 18.0 }
  ]
}
```

```bash
python build.py params.json
```

---

### Option D – Demo mode *(no files needed)*

```bash
python build.py
```

---

## Units and parameters

| Parameter | Unit | Meaning |
|-----------|------|---------|
| `length_mm` / `width_mm` / `thickness_mm` | mm | Plate footprint and depth |
| `border_offset_pct` | % of mean port diameter | C3 frame inset from plate edge — clears the port ingress zone |
| `stiffening_width_pct` | % of mean port diameter | Wall thickness of the C3 stiffening rib |
| `peripheral_channel_pct` | % of mean port diameter | Radial width of the C4 outer channel band |
| `stiffening_height_mm` | mm | Physical height of C3/C4 features above the plate surface |
| `ports[].edge` | — | `left` / `right` / `top` / `bottom` |
| `ports[].offset` | mm | Distance from the nearest corner along that edge |
| `ports[].diameter` | mm | Port inner diameter |
| `ports[].depth` | mm | Length of port stub |

**Why percentages for offsets?**
Offsets relative to port diameter stay proportionally correct when you
swap port sizes or scale the plate — no magic mm numbers to retune.

Example: `border_offset_pct = 150` with a 10 mm port → 15 mm inset.
The same 150% with a 12 mm port → 18 mm inset automatically.

---

## Output files

```
output/
├── C1_outer_plate.step
├── C2_ports.step
├── C3_stiffening_frame.step
└── C4_peripheral_channel.step
```

---

## Sample geometries

Three test STEP files are included in `sample_geometries/`:

| File | Plate | Ports |
|------|-------|-------|
| `sample_A_200x120_2port.step` | 200×120×6 mm | 2 side ports, ø10 mm |
| `sample_B_300x180_4port.step` | 300×180×8 mm | 4 side ports, ø12 mm |
| `sample_C_150x100_bottom_ports.step` | 150×100×5 mm | 2 bottom ports, ø8 mm |

Try them:
```bash
python build.py sample_geometries/sample_A_200x120_2port.step
```

---

## How port detection works

The parser scans all **cylindrical faces** in the STEP solid.
A cylindrical face bounding box has the pattern:
- Two spans roughly equal → the port diameter
- One span longer → the depth of the stub along the port axis

The axis direction (X/Y) determines which plate edge the port belongs to.
Port stubs are then subtracted from the overall bounding box to recover
the true plate dimensions without the stubs included.

**Note:** Port stubs must be represented as solid cylinders attached to the
plate face (the typical output of most CAD tools). Holes-only geometry
(no stub) will still give correct plate dimensions but ports will not
be auto-detected; supply them manually via `params.json` in that case.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "No solids found" | Re-export from CAD as a solid body, not surface-only |
| Ports not detected | Ensure ports are modelled as cylinder stubs on the face, not just holes |
| Wrong plate orientation | Tool auto-rotates shortest axis to Z; override with manual `params.json` if plate is near-cubic |
| Dashboard doesn't open | Go to http://localhost:5050 manually; check port 5050 is free |
