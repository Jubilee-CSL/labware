#!/usr/bin/env python3
"""
reorganize.py
Moves a flat collection of labware assets (JSON definitions + product images)
into the per-labware sub-folder structure used by this repository:

    labware_definition/
        <load_name>/
            <load_name>.json
            <load_name>_meta.json
            <load_name>.<jpg|png|gif>

This is useful after running fetch_labware.py (or any other script that
downloads Opentrons definitions flat into a single directory) before running
generate_stls.py to render STL models.

By default files are MOVED (--copy to keep originals).

Usage:
    python reorganize.py                  # move flat assets into labware_definition/
    python reorganize.py --copy           # copy instead of move
    python reorganize.py --dry-run        # preview without touching files
    python reorganize.py --source-dir /path/to/flat_downloads
"""

import argparse
import logging
import shutil
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif"}


def collect_load_names(source_dir: Path) -> list[str]:
    """Return sorted list of load names from non-meta JSON files in a flat directory."""
    return sorted(
        p.stem
        for p in source_dir.glob("*.json")
        if not p.stem.endswith("_meta")
    )


def transfer(src: Path, dst: Path, move: bool, dry_run: bool) -> None:
    if not src.exists():
        return
    if dry_run:
        action = "MOVE" if move else "COPY"
        logger.info("  [%s] %s -> %s", action, src, dst)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(src), str(dst))
    else:
        shutil.copy2(str(src), str(dst))


def reorganize(
    source_dir: Path,
    output_dir: Path,
    move: bool,
    dry_run: bool,
) -> None:
    """Move/copy flat JSON + image files from source_dir into per-labware subfolders."""
    load_names = collect_load_names(source_dir)
    if not load_names:
        logger.error("No labware JSON files found in %s", source_dir)
        return

    logger.info(
        "Reorganizing %d labware from %s -> %s  [%s]",
        len(load_names), source_dir, output_dir,
        "DRY-RUN" if dry_run else ("MOVE" if move else "COPY"),
    )

    moved = missing = 0

    for name in load_names:
        dest_dir = output_dir / name
        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)

        logger.debug("Processing: %s", name)

        # ── JSON definition ──────────────────────────────────────────────
        for suffix in [".json", "_meta.json"]:
            src = source_dir / f"{name}{suffix}"
            transfer(src, dest_dir / f"{name}{suffix}", move, dry_run)
            if src.exists():
                moved += 1

        # ── Image ────────────────────────────────────────────────────────
        found_image = False
        for ext in IMAGE_EXTS:
            src = source_dir / f"{name}{ext}"
            if src.exists():
                transfer(src, dest_dir / f"{name}{ext}", move, dry_run)
                moved += 1
                found_image = True
                break
        if not found_image:
            logger.debug("  [no image] %s", name)
            missing += 1

    logger.info(
        "Done: %d file operations, %d labware had no image.",
        moved, missing,
    )


def main() -> None:
    base = Path(__file__).parent

    parser = argparse.ArgumentParser(
        description="Move flat labware downloads into per-labware sub-folders.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source-dir", metavar="DIR",
        default=str(base / "labware_definition"),
        help="Flat source folder with labware JSON + images (default: labware_definition/).",
    )
    parser.add_argument(
        "--output-dir", metavar="DIR",
        default=str(base / "labware_definition"),
        help="Destination root folder (default: labware_definition/ — in-place).",
    )
    parser.add_argument(
        "--copy", action="store_true",
        help="Copy files instead of moving them.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without touching any files.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    reorganize(
        source_dir=Path(args.source_dir),
        output_dir=Path(args.output_dir),
        move=not args.copy,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
