#!/usr/bin/env python3
"""
generate_stls.py
Parallel runner: renders STL (and .scad) for every labware in
labware_definition/, writing each output file next to its JSON.

Already-existing .stl files are skipped unless --force is given.

Usage:
    python generate_stls.py                  # all missing STLs, auto CPU count
    python generate_stls.py --force          # re-render everything
    python generate_stls.py --workers 4      # limit parallelism
    python generate_stls.py --fn 32          # lower circle resolution (faster)
    python generate_stls.py --openscad "C:/Program Files/OpenSCAD/openscad.exe"
"""

import argparse
import logging
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Import SCAD generator from the sibling script
sys.path.insert(0, str(Path(__file__).parent))
from labware_to_stl import labware_to_scad   # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def render_one(
    json_path: Path,
    openscad_cmd: str,
    fn: int,
    force: bool,
) -> tuple[str, bool, str]:
    """
    Generate .scad then render .stl for a single labware JSON.
    Output is placed next to the JSON inside its per-labware sub-folder.
    Returns (load_name, success, message).
    """
    import json as _json

    load_name = json_path.stem
    out_dir = json_path.parent
    scad_path = out_dir / f"{load_name}.scad"
    stl_path  = out_dir / f"{load_name}.stl"

    if not force and stl_path.exists() and stl_path.stat().st_size > 0:
        return load_name, True, "skipped (already exists)"

    # ── Parse JSON ──────────────────────────────────────────────────────────
    try:
        definition = _json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return load_name, False, f"JSON parse error: {exc}"

    if "wells" not in definition or "dimensions" not in definition:
        return load_name, False, "missing wells/dimensions – skipped"

    # ── Generate SCAD ───────────────────────────────────────────────────────
    try:
        scad_code = labware_to_scad(definition, fn=fn)
    except Exception as exc:
        return load_name, False, f"SCAD generation failed: {exc}"

    scad_path.write_text(scad_code, encoding="utf-8")

    # ── Render STL ──────────────────────────────────────────────────────────
    cmd = [openscad_cmd, "--render", "-o", str(stl_path), str(scad_path)]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError:
        return load_name, False, (
            f"OpenSCAD not found: '{openscad_cmd}'. "
            "Install it or pass --openscad <path>."
        )
    except subprocess.TimeoutExpired:
        return load_name, False, "OpenSCAD timed out (600 s)"

    if result.returncode != 0:
        return load_name, False, (
            f"OpenSCAD exit {result.returncode}: "
            + result.stderr.strip()[:200]
        )

    if not stl_path.exists() or stl_path.stat().st_size == 0:
        return load_name, False, "OpenSCAD produced an empty/missing STL"

    return load_name, True, f"-> {stl_path.name}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parallel STL renderer for the full labware_definition/ library.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--labware-dir", metavar="DIR",
        default=str(Path(__file__).parent / "labware_definition"),
        help="Root folder containing per-labware sub-folders (default: labware_definition/).",
    )
    parser.add_argument(
        "--openscad", metavar="CMD",
        default="openscad",
        help="OpenSCAD executable (default: openscad).",
    )
    parser.add_argument(
        "--workers", "-j", type=int,
        default=os.cpu_count() or 4,
        help="Parallel worker threads (default: CPU count).",
    )
    parser.add_argument(
        "--fn", type=int, default=32,
        help="OpenSCAD $fn – max circle resolution (default: 32; auto-reduced for many-well plates).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-render even if .stl already exists.",
    )
    parser.add_argument(
        "--exclude", metavar="REGEX",
        default=None,
        help="Skip labware whose load-name matches this regex (e.g. '96|384').",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    labware_dir = Path(args.labware_dir)

    # Each sub-folder <name>/ must contain <name>.json
    json_files = sorted(
        p for sub in labware_dir.iterdir()
        if sub.is_dir()
        for p in [sub / f"{sub.name}.json"]
        if p.exists()
    )
    if not json_files:
        logger.error(
            "No per-labware JSON files found in %s.\n"
            "Expected structure: labware_definition/<name>/<name>.json",
            labware_dir,
        )
        sys.exit(1)

    logger.info("Found %d labware in %s", len(json_files), labware_dir)

    # Apply optional name-exclusion filter
    if args.exclude:
        exclude_re = re.compile(args.exclude, re.IGNORECASE)
        before = len(json_files)
        json_files = [p for p in json_files if not exclude_re.search(p.stem)]
        logger.info(
            "--exclude '%s': dropped %d, %d remaining",
            args.exclude, before - len(json_files), len(json_files),
        )

    # Filter to only missing ones (unless --force)
    pending = (
        json_files if args.force
        else [p for p in json_files
              if not (p.parent / f"{p.stem}.stl").exists()
              or (p.parent / f"{p.stem}.stl").stat().st_size == 0]
    )

    already_done = len(json_files) - len(pending)
    if already_done:
        logger.info("%d already done, skipping.", already_done)

    if not pending:
        logger.info("All STLs up to date.")
        return

    logger.info(
        "Rendering %d labware with %d worker(s) ...",
        len(pending), args.workers,
    )

    ok = fail = 0
    failures: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        # Output goes next to the JSON inside its per-labware sub-folder
        futures = {
            pool.submit(
                render_one, p, args.openscad, args.fn, args.force
            ): p
            for p in pending
        }
        for future in as_completed(futures):
            load_name, success, msg = future.result()
            if success:
                ok += 1
                logger.info("[OK]   %s  %s", load_name, msg)
            else:
                fail += 1
                failures.append((load_name, msg))
                logger.error("[FAIL] %s  %s", load_name, msg)

    logger.info(
        "\nFinished: %d OK  |  %d failed  |  %d already existed",
        ok, fail, already_done,
    )
    if failures:
        logger.warning("Failed items:")
        for name, msg in failures:
            logger.warning("  %s: %s", name, msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
