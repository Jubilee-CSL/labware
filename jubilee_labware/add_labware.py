#!/usr/bin/env python3
"""
add_labware.py
Interactive wizard to add a new custom labware definition to the database.

Steps:
  1. Capture a photo via webcam (SPACE to capture, ESC to skip)
  2. Enter labware dimensions and well geometry
  3. Generate <load_name>.json + <load_name>_meta.json
  4. Save everything into labware_definition/<load_name>/

Usage:
    python add_labware.py
    python add_labware.py --no-webcam   # skip photo capture
"""

import argparse
import json
import string
import sys
from pathlib import Path
from typing import Optional

# ── Webcam capture ──────────────────────────────────────────────────────────

def capture_photo(load_name: str, out_path: Path) -> bool:
    """Show live webcam preview; SPACE saves, ESC skips. Returns True if saved."""
    try:
        import cv2  # noqa: F401 – checked here so error is informative
    except ImportError:
        print("[WARNING] opencv-python not installed – skipping photo capture.")
        print("          Install with:  pip install opencv-python")
        return False

    import cv2

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[WARNING] Could not open webcam (index 0) – skipping photo capture.")
        return False

    print("\nWebcam preview open.")
    print("  SPACE  → capture photo")
    print("  ESC    → skip (no photo)\n")

    captured = False
    while True:
        ret, frame = cap.read()
        if not ret:
            print("[WARNING] Failed to read webcam frame.")
            break

        # Overlay hint text on the preview
        import cv2 as _cv2
        hint = "SPACE: capture | ESC: skip"
        _cv2.putText(frame, hint, (10, 30), _cv2.FONT_HERSHEY_SIMPLEX,
                     0.8, (0, 255, 0), 2, _cv2.LINE_AA)
        _cv2.imshow(f"Labware photo – {load_name}", frame)

        key = _cv2.waitKey(1) & 0xFF
        if key == 32:  # SPACE
            # Save the clean frame (without overlay) by re-reading
            ret2, clean = cap.read()
            save_frame = clean if ret2 else frame
            _cv2.imwrite(str(out_path), save_frame)
            print(f"Photo saved: {out_path}")
            captured = True
            break
        elif key == 27:  # ESC
            print("Photo skipped.")
            break

    cap.release()
    cv2.destroyAllWindows()
    return captured


# ── Prompt helpers ──────────────────────────────────────────────────────────

def ask(prompt: str, default=None, cast=str):
    """Prompt the user, applying optional type cast and optional default."""
    suffix = f" [{default}]" if default is not None else ""
    full_prompt = f"  {prompt}{suffix}: "
    while True:
        raw = input(full_prompt).strip()
        if not raw and default is not None:
            return default
        if not raw:
            print("    ↳ Required, please enter a value.")
            continue
        try:
            return cast(raw)
        except (ValueError, TypeError):
            print(f"    ↳ Expected a {cast.__name__}, try again.")


def ask_choice(prompt: str, choices: list, default: Optional[str] = None) -> str:
    choices_lower = [c.lower() for c in choices]
    choices_str = "/".join(choices)
    while True:
        val = ask(f"{prompt} ({choices_str})", default=default)
        if val.lower() in choices_lower:
            return val.lower()
        print(f"    ↳ Choose one of: {choices_str}")


def section(title: str):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


# ── Well name & position helpers ────────────────────────────────────────────

ROW_LETTERS = list(string.ascii_uppercase)  # A–Z


def well_name(row: int, col: int) -> str:
    """0-indexed row/col → e.g. 'A1', 'H12'."""
    return f"{ROW_LETTERS[row]}{col + 1}"


def build_ordering(num_rows: int, num_cols: int) -> list:
    """Column-major ordering: [[A1,B1,...], [A2,B2,...], ...]."""
    return [
        [well_name(r, c) for r in range(num_rows)]
        for c in range(num_cols)
    ]


def build_wells(
    num_rows: int,
    num_cols: int,
    shape: str,
    diameter: Optional[float],
    x_dim_well: Optional[float],
    y_dim_well: Optional[float],
    depth: float,
    volume: float,
    z_bottom: float,
    x_offset: float,
    y_offset: float,
    x_spacing: float,
    y_spacing: float,
) -> dict:
    """
    Compute well positions.

    Coordinate convention (matches Opentrons format):
      x : left → right  (column 1 has lowest x)
      y : bottom → top  (last row, e.g. H, has lowest y)
      z : plate bottom → up
    """
    wells = {}
    for r in range(num_rows):
        for c in range(num_cols):
            name = well_name(r, c)
            x = round(x_offset + c * x_spacing, 4)
            # Row A (r=0) has highest y; last row has lowest y (= y_offset)
            y = round(y_offset + (num_rows - 1 - r) * y_spacing, 4)
            well: dict = {
                "depth": depth,
                "shape": shape,
                "totalLiquidVolume": volume,
                "x": x,
                "y": y,
                "z": z_bottom,
            }
            if shape == "circular":
                well["diameter"] = diameter
            else:
                well["xDimension"] = x_dim_well
                well["yDimension"] = y_dim_well
            wells[name] = well
    return wells


# ── SBS/ANSI standard hints ─────────────────────────────────────────────────

# Common standard spacing values keyed by (num_rows, num_cols)
_SBS_HINTS = {
    (8, 12):  dict(x_offset=14.38, y_offset=11.24, x_spacing=9.0,  y_spacing=9.0),
    (16, 24): dict(x_offset=12.13, y_offset=8.99,  x_spacing=4.5,  y_spacing=4.5),
    (4, 6):   dict(x_offset=24.76, y_offset=23.16, x_spacing=19.3, y_spacing=19.3),
    (2, 3):   dict(x_offset=35.5,  y_offset=23.8,  x_spacing=39.0, y_spacing=39.0),
    (1, 12):  dict(x_offset=14.38, y_offset=42.74, x_spacing=9.0,  y_spacing=0.0),
}


def sbs_hint(num_rows: int, num_cols: int) -> Optional[dict]:
    return _SBS_HINTS.get((num_rows, num_cols))


# ── Main wizard ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Add a new labware definition.")
    parser.add_argument("--no-webcam", action="store_true",
                        help="Skip webcam photo capture.")
    args = parser.parse_args()

    repo_root = Path(__file__).parent
    labware_dir = repo_root / "labware_definition"

    print()
    print("=" * 60)
    print("   Labware Definition Wizard")
    print("=" * 60)

    # ── Identity ────────────────────────────────────────────────────────────
    section("Identity")
    print("  Load name must be lowercase, no spaces, underscores only.")
    print("  Convention: <brand>_<wells>_<type>_<volume>  e.g. acme_96_wellplate_200ul")
    load_name = ask("Load name")
    load_name = load_name.lower().replace(" ", "_")

    out_dir = labware_dir / load_name
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"\n[WARNING] Directory already exists: {out_dir}")
        if ask_choice("Overwrite existing files?", ["y", "n"], default="n") == "n":
            sys.exit(0)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Photo ───────────────────────────────────────────────────────────────
    section("Photo")
    photo_saved = False
    if not args.no_webcam:
        photo_path = out_dir / f"{load_name}.jpg"
        photo_saved = capture_photo(load_name, photo_path)
    else:
        print("  Webcam capture skipped (--no-webcam).")

    # ── Metadata ────────────────────────────────────────────────────────────
    section("Metadata")
    brand       = ask("Brand name (e.g. Corning)")
    brand_id    = ask("Catalog / brand ID (optional)", default="")
    display_name = ask("Display name (e.g. Acme 96 Well Plate 200 µL Flat)")
    category    = ask_choice(
        "Category",
        ["wellPlate", "reservoir", "tubeRack", "tipRack", "aluminumBlock", "trash"],
        default="wellPlate",
    )

    # ── Container type ────────────────────────────────────────────────────────
    section("Container type")
    is_cylinder = ask_choice(
        "Is this a single cylindrical container (glass, beaker, tube, flask…)?  y/n",
        ["y", "n"], default="n",
    ) == "y"

    if is_cylinder:
        # ── Cylindrical container shortcut ───────────────────────────────────
        section("Cylindrical container dimensions")
        print("  Measure the object with calipers or a ruler.")
        print()
        outer_diam = ask("Outer diameter (mm)",  cast=float)
        inner_diam = ask("Opening / inner diameter (mm)", cast=float)
        total_h    = ask("Total height (mm)",    cast=float)
        liquid_d   = ask("Max liquid depth (mm) [<= total height]", cast=float)
        vol_ml     = ask("Approximate volume (mL)", cast=float)

        # Derived plate-level fields
        x_dim_plate = round(outer_diam, 4)
        y_dim_plate = round(outer_diam, 4)
        z_dim_plate = round(total_h, 4)

        # Single well in the centre
        num_rows   = 1
        num_cols   = 1
        shape      = "circular"
        diameter   = round(inner_diam, 4)
        x_dim_well = None
        y_dim_well = None
        depth      = round(liquid_d, 4)
        volume     = round(vol_ml * 1000, 2)   # mL → µL

        # Well centre is the geometric centre of the footprint
        x_offset  = round(outer_diam / 2, 4)
        y_offset  = round(outer_diam / 2, 4)
        # z_bottom: base of the liquid cavity above the plate bottom
        z_bottom  = round(total_h - liquid_d, 4)
        x_spacing = 0.0
        y_spacing = 0.0

        print(f"\n  Computed plate footprint : {x_dim_plate} × {y_dim_plate} mm")
        print(f"  Well centre              : ({x_offset}, {y_offset}) mm")
        print(f"  z_bottom (cavity floor)  : {z_bottom} mm")
        print(f"  Volume                   : {volume} µL")

    else:
        # ── Standard multi-well flow ──────────────────────────────────────────
        section("Plate outer dimensions (mm)")
        print("  Standard SBS footprint: xDimension=127.76  yDimension=85.47")
        x_dim_plate = ask("xDimension (left-right / width)", default=127.76, cast=float)
        y_dim_plate = ask("yDimension (front-back / depth)", default=85.47,  cast=float)
        z_dim_plate = ask("zDimension (total height)",       cast=float)

        section("Well layout")
        num_rows = ask("Number of rows  (e.g. 8 for A–H)", cast=int)
        num_cols = ask("Number of columns (e.g. 12)",       cast=int)

        section("Well geometry")
        shape = ask_choice("Well shape", ["circular", "rectangular"], default="circular")
        if shape == "circular":
            diameter   = ask("Well diameter (mm)", cast=float)
            x_dim_well = None
            y_dim_well = None
        else:
            diameter   = None
            x_dim_well = ask("Well xDimension (mm)", cast=float)
            y_dim_well = ask("Well yDimension (mm)", cast=float)

        depth  = ask("Well depth (mm)",                   cast=float)
        volume = ask("Total liquid volume per well (µL)",  cast=float)

        section("Well positions")
        hint = sbs_hint(num_rows, num_cols)
        if hint:
            print(f"  SBS/ANSI standard defaults detected for {num_rows}×{num_cols}:")
            print(f"    x_offset={hint['x_offset']}  y_offset={hint['y_offset']}")
            print(f"    x_spacing={hint['x_spacing']}  y_spacing={hint['y_spacing']}")

        print()
        print("  x_offset  = distance from LEFT edge of plate to centre of column 1 (mm)")
        x_offset = ask("x_offset",
                       default=hint["x_offset"] if hint else None, cast=float)

        print("  y_offset  = distance from BOTTOM edge of plate to centre of LAST row (mm)")
        y_offset = ask("y_offset",
                       default=hint["y_offset"] if hint else None, cast=float)

        print("  z_bottom  = height from plate bottom to bottom of well interior (mm)")
        z_bottom = ask("z_bottom", cast=float)

        if num_cols > 1:
            x_spacing = ask("Column spacing centre-to-centre (mm)",
                            default=hint["x_spacing"] if hint else None, cast=float)
        else:
            x_spacing = 0.0

        if num_rows > 1:
            y_spacing = ask("Row spacing centre-to-centre (mm)",
                            default=hint["y_spacing"] if hint else None, cast=float)
        else:
            y_spacing = 0.0

    # ── Build JSON ───────────────────────────────────────────────────────────
    section("Generating files")

    ordering = build_ordering(num_rows, num_cols)
    wells    = build_wells(
        num_rows, num_cols, shape, diameter, x_dim_well, y_dim_well,
        depth, volume, z_bottom, x_offset, y_offset, x_spacing, y_spacing,
    )

    brand_obj: dict = {"brand": brand}
    if brand_id:
        brand_obj["brandId"] = [brand_id]

    all_well_names = [w for col in ordering for w in col]

    definition = {
        "ordering": ordering,
        "brand": brand_obj,
        "metadata": {
            "displayName": display_name,
            "displayCategory": category,
            "displayVolumeUnits": "µL",
            "tags": [],
        },
        "dimensions": {
            "xDimension": x_dim_plate,
            "yDimension": y_dim_plate,
            "zDimension": z_dim_plate,
        },
        "cornerOffsetFromSlot": {"x": 0, "y": 0, "z": 0},
        "wells": wells,
        "groups": [
            {
                "metadata": {
                    "wellBottomShape": "flat",
                    "displayName": display_name,
                },
                "wells": all_well_names,
            }
        ],
        "parameters": {
            "format": "irregular",
            "quirks": [],
            "isTiprack": category == "tiprack",
            "isMagneticModuleCompatible": False,
            "loadName": load_name,
        },
        "namespace": "custom_beta",
        "version": 1,
        "schemaVersion": 2,
    }

    meta = {
        "loadName": load_name,
        "displayName": display_name,
        "displayCategory": category,
        "brand": brand,
        "wellCount": num_rows * num_cols,
        "maxVolume": volume,
        "xDimension": x_dim_plate,
        "yDimension": y_dim_plate,
    }

    # ── Write files ──────────────────────────────────────────────────────────
    json_path = out_dir / f"{load_name}.json"
    meta_path = out_dir / f"{load_name}_meta.json"

    json_path.write_text(
        json.dumps(definition, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n  Written: {json_path.relative_to(repo_root)}")
    print(f"  Written: {meta_path.relative_to(repo_root)}")
    if photo_saved:
        print(f"  Written: {(out_dir / (load_name + '.jpg')).relative_to(repo_root)}")

    print(f"\n  Labware folder: {out_dir}")
    print()
    print("Next steps:")
    print("  1. Open the JSON and verify well positions look correct.")
    print("  2. Run  python generate_stls.py  to render an STL preview.")
    print()


if __name__ == "__main__":
    main()
