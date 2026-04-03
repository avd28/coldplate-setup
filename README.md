# Cold Plate Builder

Generates the 4 cold plate components from your sketch, with a live 2D dashboard.

## Structure

```
coldplate/
├── components.py        # modular geometry functions (one per component)
├── build.py             # entry point – runs build + launches dashboard
├── dashboard.py         # Flask server serving the progress page
├── static/index.html    # dashboard UI
├── params.json          # (optional) your custom inputs
└── output/              # generated STEP files land here
```

## Quickstart

```bash
pip install cadquery flask
python build.py              # uses built-in demo params
# or
python build.py params.json  # use your own params
```

The dashboard opens automatically at http://localhost:5050

## Minimum inputs (params.json)

```json
{
  "length": 200.0,
  "width":  120.0,
  "thickness": 6.0,
  "border_offset": 12.0,
  "stiffening_height": 4.0,
  "peripheral_channel_width": 8.0,
  "ports": [
    {"edge": "left",  "offset": 60.0, "diameter": 10.0, "depth": 20.0},
    {"edge": "right", "offset": 60.0, "diameter": 10.0, "depth": 20.0}
  ]
}
```

| Key | Meaning |
|-----|---------|
| `length / width / thickness` | Plate footprint + depth (mm) |
| `border_offset` | C3 inset from plate edge – clears I/O ports |
| `stiffening_height` | Height of C3 stiffening ribs (mm) |
| `peripheral_channel_width` | Radial width of C4 outer band (mm) |
| `ports[].edge` | `left / right / top / bottom` |
| `ports[].offset` | Distance from near corner along that edge (mm) |
| `ports[].diameter` | Port inner diameter (mm) |
| `ports[].depth` | How far the port cuts into the plate (mm) |

## Component map

| Component | What it is |
|-----------|------------|
| C1 | Solid outer plate body (design plane) |
| C2 | Inlet / outlet port cut-outs |
| C3 | Stiffening frame – solid rectangular border, inset by `border_offset` |
| C4 | 90° peripheral channel surrounding C3 – no stiffening ribs |
