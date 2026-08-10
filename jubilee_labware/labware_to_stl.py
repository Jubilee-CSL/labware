#!/usr/bin/env python3
"""
labware_to_stl.py
Converts Opentrons V2 labware JSON definitions into OpenSCAD (.scad) source
and optionally renders them to STL via the OpenSCAD CLI.

Output is written **next to the input JSON** by default (inside the per-labware
sub-folder in labware_definition/).  Pass --output-dir to override.

Usage examples
--------------
# Convert a single definition (output goes next to the JSON):
    python labware_to_stl.py --input labware_definition/corning_96_wellplate_360ul_flat/corning_96_wellplate_360ul_flat.json

# Only generate .scad files (no OpenSCAD call):
    python labware_to_stl.py --input <file> --scad-only

# Use a specific OpenSCAD binary and higher circle resolution:
    python labware_to_stl.py --input <file> --openscad "C:/Program Files/OpenSCAD/openscad.exe" --fn 128
"""

import argparse
import json
import logging
import subprocess
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SCAD generation helpers
# ---------------------------------------------------------------------------

def _circular_well_scad(wx: float, wy: float, wz: float, depth: float,
                         well: dict, geo_def: dict | None) -> str:
    """Return OpenSCAD snippet that cuts a circular (or conical) well."""
    sections = geo_def.get("sections") if geo_def else None
    fallback_r = well["diameter"] / 2

    if sections:
        inner = []
        for sec in sections:
            bot_h = sec.get("bottomHeight", 0.0)
            top_h = sec.get("topHeight", depth)
            h = max(top_h - bot_h, 0.001)
            r1 = sec.get("bottomDiameter", well["diameter"]) / 2
            r2 = sec.get("topDiameter", well["diameter"]) / 2
            inner.append(
                f"        translate([0, 0, {bot_h:.4f}])\n"
                f"            cylinder(h={h:.4f}, r1={r1:.4f}, r2={r2:.4f}, $fn=$fn);"
            )
        # punch 1 mm above the well top to avoid z-fighting at the surface
        top_r = sections[-1].get("topDiameter", well["diameter"]) / 2
        inner.append(
            f"        translate([0, 0, {depth:.4f}])\n"
            f"            cylinder(h=1, r={top_r:.4f}, $fn=$fn);"
        )
        body = "\n".join(inner)
        return (
            f"    translate([{wx:.4f}, {wy:.4f}, {wz:.4f}]) union() {{\n"
            f"{body}\n"
            f"    }}"
        )
    else:
        return (
            f"    translate([{wx:.4f}, {wy:.4f}, {wz:.4f}])\n"
            f"        cylinder(h={depth + 1:.4f}, r={fallback_r:.4f}, $fn=$fn);"
        )


def _rectangular_well_scad(wx: float, wy: float, wz: float, depth: float,
                            well: dict, geo_def: dict | None) -> str:
    """Return OpenSCAD snippet that cuts a rectangular well.

    For simplicity (and fast render times), uses the maximum X/Y dimension
    across all sections as a single bounding cuboid per well.  This produces
    a clean, 3D-printable model without thousands of hull() operations.
    """
    sections = geo_def.get("sections") if geo_def else None
    fallback_xw = well.get("xDimension", 1.0)
    fallback_yw = well.get("yDimension", 1.0)

    if sections:
        xw = max(
            (max(s.get("topXDimension", 0), s.get("bottomXDimension", 0)) for s in sections),
            default=fallback_xw,
        )
        yw = max(
            (max(s.get("topYDimension", 0), s.get("bottomYDimension", 0)) for s in sections),
            default=fallback_yw,
        )
        if xw < 0.1:
            xw = fallback_xw
        if yw < 0.1:
            yw = fallback_yw
    else:
        xw, yw = fallback_xw, fallback_yw

    return (
        f"    translate([{wx - xw/2:.4f}, {wy - yw/2:.4f}, {wz:.4f}])\n"
        f"        cube([{xw:.4f}, {yw:.4f}, {depth + 1:.4f}]);"
    )


def labware_to_scad(definition: dict, fn: int = 64) -> str:
    """Generate a complete OpenSCAD source string from a labware definition dict.

    The model is a solid rectangular block (outer dimensions) with all well
    cavities subtracted.  Well geometry uses `innerLabwareGeometry` sections
    when available (conical frustums, tapered cuboids) and falls back to simple
    cylinders / boxes otherwise.
    """
    dims = definition["dimensions"]
    x_dim = dims["xDimension"]
    y_dim = dims["yDimension"]
    z_dim = dims["zDimension"]

    display_name = definition.get("metadata", {}).get("displayName", "labware")
    load_name = definition.get("parameters", {}).get("loadName", "labware")
    inner_geo = definition.get("innerLabwareGeometry", {})
    wells = definition.get("wells", {})

    well_count = len(wells)
    # For high-well-count labware, cap fn to keep render time reasonable
    effective_fn = min(fn, max(8, fn // max(1, well_count // 24)))

    lines = [
        f"// {display_name}",
        f"// loadName: {load_name}",
        f"// Auto-generated by labware_to_stl.py from Opentrons V2 labware definition",
        "",
        f"$fn = {effective_fn};",
        "",
        "difference() {",
        "    // ── Labware body ──────────────────────────────────────────────",
        f"    cube([{x_dim:.4f}, {y_dim:.4f}, {z_dim:.4f}]);",
        "",
        "    // ── Well cutouts ──────────────────────────────────────────────",
    ]

    seen: set = set()
    for name, w in wells.items():
        # Deduplicate overlapping wells (some definitions list duplicates)
        key = (round(w["x"], 3), round(w["y"], 3), round(w["z"], 3))
        if key in seen:
            continue
        seen.add(key)

        geo_id = w.get("geometryDefinitionId")
        geo_def = inner_geo.get(geo_id) if geo_id else None
        shape = w.get("shape", "circular")

        lines.append(f"    // Well {name}")
        if shape == "circular":
            lines.append(_circular_well_scad(
                w["x"], w["y"], w["z"], w["depth"], w, geo_def
            ))
        else:
            lines.append(_rectangular_well_scad(
                w["x"], w["y"], w["z"], w["depth"], w, geo_def
            ))

    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-file pipeline
# ---------------------------------------------------------------------------

def process_file(json_path: Path, output_dir: Path | None,
                 openscad_cmd: str, fn: int, scad_only: bool) -> bool:
    """Parse one JSON, write .scad, optionally render .stl.  Returns True on success.

    If output_dir is None, files are written next to json_path (same folder).
    """
    load_name = json_path.stem

    if load_name.endswith("_meta"):
        logger.debug("Skipping meta file: %s", json_path.name)
        return True

    # ── Parse ----------------------------------------------------------------
    try:
        definition = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("[%s] JSON parse error: %s", load_name, exc)
        return False

    if "wells" not in definition or "dimensions" not in definition:
        logger.warning("[%s] Missing wells/dimensions – skipped", load_name)
        return False

    # ── Determine output location ----------------------------------------
    out = output_dir if output_dir is not None else json_path.parent

    # ── Generate SCAD --------------------------------------------------------
    scad_path = out / f"{load_name}.scad"
    stl_path = out / f"{load_name}.stl"

    try:
        scad_code = labware_to_scad(definition, fn=fn)
    except Exception as exc:
        logger.error("[%s] SCAD generation failed: %s", load_name, exc)
        return False

    scad_path.write_text(scad_code, encoding="utf-8")
    logger.debug("[%s] .scad written to %s", load_name, scad_path)

    if scad_only:
        logger.info("[%s] .scad OK (--scad-only, skipping render)", load_name)
        return True

    # ── Render STL -----------------------------------------------------------
    cmd = [openscad_cmd, "-o", str(stl_path), str(scad_path)]
    logger.info("[%s] Rendering STL ...", load_name)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600
        )
    except FileNotFoundError:
        logger.error(
            "OpenSCAD executable not found: '%s'\n"
            "  Install OpenSCAD and make sure it is on your PATH, or pass "
            "--openscad /absolute/path/to/openscad",
            openscad_cmd,
        )
        raise SystemExit(1)
    except subprocess.TimeoutExpired:
        logger.error("[%s] OpenSCAD render timed out (600 s)", load_name)
        return False

    if result.returncode != 0:
        logger.error(
            "[%s] OpenSCAD returned exit code %d:\n%s",
            load_name, result.returncode, result.stderr.strip(),
        )
        return False

    logger.info("[%s] -> %s", load_name, stl_path.name)
    return True


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a single Opentrons V2 labware JSON to .scad / .stl via OpenSCAD."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--input", metavar="FILE", required=True,
        help="Path to a labware JSON file inside labware_definition/<name>/.",
    )
    parser.add_argument(
        "--output-dir", metavar="DIR", default=None,
        help="Output directory for .scad and .stl (default: same folder as --input).",
    )
    parser.add_argument(
        "--openscad", metavar="CMD",
        default="openscad",
        help="Path or name of the OpenSCAD executable (default: openscad).",
    )
    parser.add_argument(
        "--fn", type=int, default=32,
        metavar="N",
        help="OpenSCAD $fn – max circle/cylinder resolution (default: 32; auto-reduced for many-well plates).",
    )
    parser.add_argument(
        "--scad-only", action="store_true",
        help="Generate .scad file only; do not call OpenSCAD to render STL.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging.",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    output_dir = Path(args.output_dir) if args.output_dir else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    json_path = Path(args.input)
    ok = process_file(json_path, output_dir, args.openscad, args.fn, args.scad_only)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
