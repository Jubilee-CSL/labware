# labware

Labware library for [Science Jubilee](https://github.com/Jubilee-CSL/science-jubilee-interface) experiments.

Each labware entry bundles all assets in a single named folder under `labware_definition/`:

| File | Description |
|------|-------------|
| `<name>.json` | Opentrons V2 labware definition (well positions, dimensions, …) |
| `<name>_meta.json` | Display metadata (category, brand, volume units) |
| `<name>.<jpg\|png>` | Product photo fetched from the Opentrons labware library |
| `<name>.scad` | Auto-generated OpenSCAD source |
| `<name>.stl` | 3D model rendered from the JSON definition |

> **150 labware** · **128 STL models** · **158 product images**

---

## Repository layout

```
labware_definition/          ← one sub-folder per labware (definition + image + STL)
│   corning_96_wellplate_360ul_flat/
│   │   corning_96_wellplate_360ul_flat.json
│   │   corning_96_wellplate_360ul_flat_meta.json
│   │   corning_96_wellplate_360ul_flat.jpg
│   │   corning_96_wellplate_360ul_flat.scad
│   │   corning_96_wellplate_360ul_flat.stl
│   …
fetch_labware.py             ← downloads definitions + images from Opentrons
labware_to_stl.py            ← converts one JSON definition to a .scad / .stl
generate_stls.py             ← parallel runner: renders STLs for all definitions
reorganize.py                ← moves flat downloads into per-labware folders
Labware.py                   ← Python labware class (used by Science Jubilee)
```

---

## Scripts

### `fetch_labware.py` — download from Opentrons

Fetches all Opentrons V2 labware definitions and their product images from
the [Opentrons GitHub repository](https://github.com/Opentrons/opentrons) and
caches them locally in `labware_definition/`.

```bash
pip install requests Pillow

# Download all definitions + images
python fetch_labware.py

# Download a single labware
python fetch_labware.py --name corning_96_wellplate_360ul_flat

# Re-download everything (ignore cache)
python fetch_labware.py --force
```

Each labware produces three files in `labware_definition/<name>/`:
- `<name>.json` — full definition
- `<name>_meta.json` — extracted display metadata
- `<name>.<jpg|png|gif>` — product photo (if available)

---

### `labware_to_stl.py` — JSON → STL via OpenSCAD

Converts a single Opentrons V2 labware JSON into an OpenSCAD `.scad` file then
calls the [OpenSCAD](https://openscad.org/) CLI to render a `.stl`.

The 3D model is a solid rectangular block (outer dimensions) with all well
cavities subtracted using `difference()`. Well geometry uses the
`innerLabwareGeometry` sections from the JSON when available:

- **Circular wells** — conical frustum cylinders (`cylinder(r1=…, r2=…)`)
- **Rectangular wells** — tapered cuboids via `hull()` of two thin slabs
- Falls back to simple cylinder / cube when no geometry sections are present

The `$fn` (circle resolution) is automatically reduced for high-well-count
plates (96 / 384 wells) to keep render times reasonable.

```bash
# Convert a single file
python labware_to_stl.py --input labware_definition/corning_96_wellplate_360ul_flat.json

# Generate .scad only (no OpenSCAD required)
python labware_to_stl.py --scad-only

# Custom OpenSCAD path, higher resolution
python labware_to_stl.py \
    --openscad "C:/Program Files/OpenSCAD/openscad.exe" \
    --fn 128
```

| Option | Default | Description |
|--------|---------|-------------|
| `--input FILE` | — | Single JSON file to convert |
| `--input-dir DIR` | `labware_definition/` | Batch input folder |
| `--openscad CMD` | `openscad` | OpenSCAD executable |
| `--fn N` | `32` | Max circle resolution (auto-reduced for many-well plates) |
| `--scad-only` | off | Skip OpenSCAD render step |

Output is written into the same folder as the input JSON (next to `<name>.json`).

---

### `generate_stls.py` — parallel batch renderer

Wraps `labware_to_stl.py` with a `ThreadPoolExecutor` to render all labware
definitions in parallel (default: one worker per CPU core). Already-existing
STL files are skipped unless `--force` is given.

```bash
# Render all missing STLs (auto CPU count)
python generate_stls.py

# Re-render everything
python generate_stls.py --force

# Limit to 4 workers, lower resolution
python generate_stls.py --workers 4 --fn 16
```

| Option | Default | Description |
|--------|---------|-------------|
| `--labware-dir DIR` | `labware_definition/` | Root folder with per-labware sub-folders |
| `--openscad CMD` | `openscad` | OpenSCAD executable |
| `--workers N` | CPU count | Parallel render threads |
| `--fn N` | `32` | Max circle resolution |
| `--force` | off | Re-render even if STL exists |

STL and SCAD files are written into each labware's own sub-folder alongside its JSON.

---

### `reorganize.py` — collect flat downloads into per-labware folders

Moves (or copies) flat JSON + image files from a source directory into
per-labware sub-folders.  Run this once after a fresh `fetch_labware.py`
download if the files landed flat rather than in sub-folders.

```bash
# Move flat assets into labware_definition/<name>/ sub-folders
python reorganize.py

# Copy instead of move (keep originals)
python reorganize.py --copy

# Preview without touching files
python reorganize.py --dry-run
```

| Option | Default | Description |
|--------|---------|-------------|
| `--source-dir DIR` | `labware_definition/` | Flat source folder (JSON + images) |
| `--output-dir DIR` | `labware_definition/` | Destination root (may be the same folder) |
| `--copy` | off | Copy instead of move |
| `--dry-run` | off | Print plan, do nothing |

---

## Typical full workflow

```bash
# 1. Install dependencies
pip install requests Pillow

# 2. Download all Opentrons labware definitions + product images
#    Files land directly in labware_definition/<name>/ sub-folders
python fetch_labware.py

# 3. Render STL models for every definition (requires OpenSCAD)
#    STL + SCAD are written next to each JSON, inside its sub-folder
python generate_stls.py
```

`labware_definition/` then contains one folder per labware with all assets
ready to use.  Run `python reorganize.py` first only if you downloaded
definitions into a flat directory and need to organize them into sub-folders.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP downloads in `fetch_labware.py` |
| `Pillow` | Image handling in `fetch_labware.py` |
| [OpenSCAD](https://openscad.org/) ≥ 2021 | STL rendering (system install) |
| `numpy` | Used by `Labware.py` |
