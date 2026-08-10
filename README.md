# labware

Labware library for [Science Jubilee](https://github.com/Jubilee-CSL/science-jubilee-interface) experiments.

Contains **148 Opentrons V2 labware definitions** together with product images and 3D models, plus the Python class used by the Science Jubilee control stack to address individual wells by name.

Each labware entry bundles all assets in a single named folder under `labware_definition/`:

| File | Description |
|------|-------------|
| `<name>.json` | Opentrons V2 labware definition (well positions, dimensions, …) |
| `<name>_meta.json` | Display metadata (category, brand, volume units) |
| `<name>.<jpg\|png\|gif>` | Product photo sourced from the Opentrons labware library |
| `<name>.scad` | Auto-generated OpenSCAD source (produced by `labware_to_stl.py`) |
| `<name>.stl` | 3D model rendered from the JSON definition |

> **148 labware** · **137 STL models** · **158 product images**

---

## Repository layout

```
jubilee_labware/                     ← installable Python package
│   __init__.py                      ← public API (Labware, Well, LABWARE_DEFINITION_DIR, …)
│   labware_definition/              ← junction → ../labware_definition (one sub-folder per labware)
labware_definition/                  ← canonical labware data
│   corning_96_wellplate_360ul_flat/
│   │   corning_96_wellplate_360ul_flat.json
│   │   corning_96_wellplate_360ul_flat_meta.json
│   │   corning_96_wellplate_360ul_flat.jpg
│   │   corning_96_wellplate_360ul_flat.scad
│   │   corning_96_wellplate_360ul_flat.stl
│   …
setup.cfg                            ← package metadata (pip install -e .)
Labware.py                           ← Python labware class (Science Jubilee API)
labware_to_stl.py                    ← convert one JSON → .scad / .stl
generate_stls.py                     ← parallel batch STL renderer
reorganize.py                        ← move flat downloads into per-labware folders
```

---

## Python API

The package can be installed in editable mode from the repo root:

```bash
pip install -e .
```

After installation, import via the package:

```python
from jubilee_labware import Labware, LABWARE_DEFINITION_DIR
```

Or continue using the module directly in-repo:

```python
from Labware import Labware
```

`jubilee_labware` exports: `Labware`, `Well`, `WellSet`, `Row`, `Column`, `Point`, `Location`, `labware_to_scad`, and `LABWARE_DEFINITION_DIR` (a `Path` to the bundled definitions — used by `Deck._plugin_labware_dirs()` for auto-discovery on install).

### Quick start

```python
from jubilee_labware import Labware

# Load by load-name (looks up labware_definition/<name>/<name>.json)
plate = Labware("corning_96_wellplate_360ul_flat")

# Iterate all wells (row order by default)
for well in plate:
    print(well)               # "Well A1 at coordinates (14.38, 74.24, 0.0)"

# Address wells by name or index
well_a1  = plate["A1"]
well_idx = plate[0]           # same well, first in row order

# Access rows and columns
row_a   = plate.row_data["A"]      # Row object → iterable of Well objects
col_1   = plate.column_data[1]     # Column object (1-based index)
```

### Well geometry helpers

```python
well = plate["B3"]

well.depth              # depth of the well cavity (mm)
well.totalLiquidVolume  # max volume (µL)
well.x, well.y, well.z  # well-centre coordinates in the labware frame (mm)

# Coordinates relative to well bottom / top
loc_bottom = well.bottom(2.0)   # 2 mm above well bottom → Location(coords, well)
loc_top    = well.top(-5.0)     # 5 mm below well rim    → Location(coords, well)
```

### Applying an offset

When a labware is loaded onto a deck slot its coordinates are shifted by the
slot origin.  The Science Jubilee `Deck` class calls `offset` automatically;
you can also set it manually:

```python
plate.offset = (10.0, 20.0, 3.5)    # (x, y, z) offset in mm
# All well coordinates are updated immediately
```

### Manual 3-point calibration

If the physical labware is not perfectly aligned with the nominal deck coordinates,
use three corner-well measurements to apply a rotation + translation correction:

```python
plate.add_slot("1")

# Provide measured (x, y) coordinates of three corner wells in robot frame
plate.manual_offset(
    corner_wells=[
        (upper_left_x,  upper_left_y),
        (upper_right_x, upper_right_y),
        (bottom_right_x, bottom_right_y),
    ],
    save=True      # persist to the .json file for future sessions
)

# Next time, reload without re-measuring:
plate.load_manualOffset()
```

### Tip-rack tracking

```python
tiprack = Labware("opentrons_96_tiprack_300ul")

tiprack["A1"].has_tip     # True initially
tiprack["A1"].set_has_tip(False)   # mark as used
```

### Key attributes

| Attribute / method | Returns |
|--------------------|---------|
| `plate.display_name` | Human-readable name string |
| `plate.load_name` | Machine load-name (matches folder name) |
| `plate.labware_type` | Category string (`wellPlate`, `tipRack`, `reservoir`, …) |
| `plate.brand` | Brand name string |
| `plate.dimensions` | `{"xDimension": …, "yDimension": …, "zDimension": …}` |
| `plate.shape` | `(num_rows, num_columns)` tuple |
| `plate.is_tip_rack` | `bool` |
| `plate.tip_length` | Tip length in mm (tip racks only) |
| `plate.withWellOrder("cols")` | Re-order iteration to column-first |
| `plate.get_row("A")` | `Row` object for row A |
| `plate.get_column(3)` | `Column` object for column 3 (1-based) |

### Constructor options

```python
Labware(
    labware_filename,          # load-name string or path to .json
    offset=(x, y, z),          # optional initial offset
    order="rows",              # "rows" (default) or "cols"
    path="labware_definition/" # override root search path
)
```

---

## STL generation scripts

### `labware_to_stl.py` — single-file converter

Converts one Opentrons V2 labware JSON into an OpenSCAD `.scad` source file and
optionally calls the [OpenSCAD](https://openscad.org/) CLI to render a `.stl`.

**How the 3D model is built:** the labware body is a solid rectangular block
matching the JSON `dimensions`, with all well cavities subtracted using
`difference()`.  Geometry is read from the `innerLabwareGeometry` sections when
present:

- **Circular wells** → conical frustum (`cylinder(r1=…, r2=…)`) per section
- **Rectangular wells** → bounding cuboid per well (fast, clean geometry)
- Falls back to a plain cylinder / cube when no geometry sections exist

The `$fn` circle resolution is automatically reduced for high-well-count plates
(96 / 384 wells) to keep render times sensible.

```bash
# Convert a single definition (output goes next to the JSON)
python labware_to_stl.py \
    --input labware_definition/corning_96_wellplate_360ul_flat/corning_96_wellplate_360ul_flat.json

# Generate .scad only — no OpenSCAD required
python labware_to_stl.py --input <file> --scad-only

# Custom OpenSCAD binary, higher resolution
python labware_to_stl.py \
    --input <file> \
    --openscad "C:/Program Files/OpenSCAD/openscad.exe" \
    --fn 128
```

| Option | Default | Description |
|--------|---------|-------------|
| `--input FILE` | — | Path to a labware JSON file |
| `--output-dir DIR` | same folder as `--input` | Override output location |
| `--openscad CMD` | `openscad` | OpenSCAD executable |
| `--fn N` | `32` | Max circle resolution (auto-reduced for many-well plates) |
| `--scad-only` | off | Skip OpenSCAD render step |
| `--verbose` / `-v` | off | Enable DEBUG logging |

---

### `generate_stls.py` — parallel batch renderer

Wraps `labware_to_stl.py` with a `ThreadPoolExecutor` to render all labware in
`labware_definition/` in parallel.  Already-existing STL files are skipped
unless `--force` is given.

```bash
# Render all missing STLs (uses all CPU cores)
python generate_stls.py

# Re-render every labware at high quality, excluding 96/384-well plates
python generate_stls.py --force --fn 64 --exclude "96|384"

# Re-render everything (including high-well-count plates) at default quality
python generate_stls.py --force

# Limit workers and resolution (useful on low-end hardware)
python generate_stls.py --workers 4 --fn 16
```

| Option | Default | Description |
|--------|---------|-------------|
| `--labware-dir DIR` | `labware_definition/` | Root folder with per-labware sub-folders |
| `--openscad CMD` | `openscad` | OpenSCAD executable |
| `--workers N` | CPU count | Parallel render threads |
| `--fn N` | `32` | Max circle resolution |
| `--exclude REGEX` | — | Skip labware whose name matches this pattern |
| `--force` | off | Re-render even if `.stl` already exists |
| `--verbose` / `-v` | off | Enable DEBUG logging |

STL and SCAD files are written into each labware's own sub-folder alongside its JSON.

> **Render-time note:** Plates with circular wells (tip racks, tube racks) take
> longer at higher `--fn` values.  The script auto-reduces `$fn` for 96- and
> 384-well plates — set `--fn 64` for other labware and `--fn 32` (default) for
> the full library.

---

### `reorganize.py` — organize flat downloads into per-labware folders

Use this only if you have JSON definitions and images in a **flat directory**
and want to convert them to the per-labware sub-folder layout before running
`generate_stls.py`.

```bash
# Move flat assets into labware_definition/<name>/ sub-folders (default)
python reorganize.py

# Copy instead of move (keep originals)
python reorganize.py --copy

# Preview without touching files
python reorganize.py --dry-run

# Custom source and destination
python reorganize.py --source-dir /path/to/flat --output-dir labware_definition/
```

| Option | Default | Description |
|--------|---------|-------------|
| `--source-dir DIR` | `labware_definition/` | Flat source folder (JSON + images) |
| `--output-dir DIR` | `labware_definition/` | Destination root |
| `--copy` | off | Copy instead of move |
| `--dry-run` | off | Print plan, do nothing |
| `--verbose` / `-v` | off | Enable DEBUG logging |

---

## Adding labware

Opentrons publishes all labware definitions on GitHub:
[opentrons/shared-data/labware/definitions/2](https://github.com/Opentrons/opentrons/tree/edge/shared-data/labware/definitions/2)

1. Download the JSON definition for your labware.
2. Create a sub-folder: `labware_definition/<load_name>/`
3. Place the JSON as `<load_name>.json` and optionally a product image as `<load_name>.jpg`.
4. Generate the 3D model:
   ```bash
   python labware_to_stl.py \
       --input labware_definition/<load_name>/<load_name>.json \
       --fn 64
   ```

---

## Generating all STL models from scratch

```bash
# 1. Install Python dependencies
pip install -e .

# 2. Install OpenSCAD (system package or from https://openscad.org/)

# 3. Render all missing STLs
python generate_stls.py

# 4. Re-render non-96/384-well labware at higher quality
python generate_stls.py --force --fn 64 --exclude "96|384"
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `numpy` | Required by `Labware.py` for the `ordering` property |
| [OpenSCAD](https://openscad.org/) ≥ 2021 | STL rendering — system install, not a Python package |

Install Python dependencies via `pip install -e .` (reads `setup.cfg`) or manually:

```bash
pip install numpy
```
