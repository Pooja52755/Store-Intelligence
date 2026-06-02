#!/usr/bin/env python3
"""
Build store_layout.json from Brigade Road layout xlsx.

The xlsx (Brigade Road - Store layout*.xlsx) embeds floor-plan PNG images
with millimetre dimensions — not a zone CSV. This module:
  1. Extracts floor-plan images to events/layout_assets/
  2. Maps annotated mm regions to 1920x1080 CCTV pixel coordinates
  3. Writes store_layout.json for the detection pipeline

Usage:
  python prepare_layout.py "layouts/store_layout.xlsx"
  python prepare_layout.py --output events/store_layout.json
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Store floor dimensions derived from layout plan annotations (mm)
STORE_W_MM = 9041
STORE_H_MM = 5040
VIDEO_W = 1920
VIDEO_H = 1080


def mm_rect(x1: float, y1: float, x2: float, y2: float) -> Dict[str, Any]:
    """Convert mm rectangle to pixel bounds + polygon."""
    sx = VIDEO_W / STORE_W_MM
    sy = VIDEO_H / STORE_H_MM
    px1 = int(max(0, min(VIDEO_W, round(x1 * sx))))
    py1 = int(max(0, min(VIDEO_H, round(y1 * sy))))
    px2 = int(max(0, min(VIDEO_W, round(x2 * sx))))
    py2 = int(max(0, min(VIDEO_H, round(y2 * sy))))
    if px2 <= px1:
        px2 = min(VIDEO_W, px1 + 1)
    if py2 <= py1:
        py2 = min(VIDEO_H, py1 + 1)
    return {
        "bounds": [px1, py1, px2, py2],
        "polygon": [[px1, py1], [px2, py1], [px2, py2], [px1, py2]],
    }


def mm_line(x1: float, y1: float, x2: float, y2: float) -> Dict[str, int]:
    sx = VIDEO_W / STORE_W_MM
    sy = VIDEO_H / STORE_H_MM
    return {
        "x1": int(round(x1 * sx)),
        "y1": int(round(y1 * sy)),
        "x2": int(round(x2 * sx)),
        "y2": int(round(y2 * sy)),
    }


def brigade_road_zones_mm() -> Dict[str, Dict[str, Any]]:
    """
    Zone definitions from Brigade Road floor plan (mm, origin top-left).

    Horizontal chain (left→right): entry 2594 | nail 500 | gap 1347 | makeup 900 |
    gap 2000 | cash counter | access 900
    Vertical: top shelves 0–710 | FOH 710–3830 | bottom shelves 3830–5040
    Nail/makeup row centred at y 1820–2720 (1110 mm below top shelves).
    """
    zones: Dict[str, Dict[str, Any]] = {}

    def add(zone_id: str, name: str, x1: float, y1: float, x2: float, y2: float):
        geom = mm_rect(x1, y1, x2, y2)
        zones[zone_id] = {"name": name, **geom}

    # --- Entry (existing glass door, left wall) ---
    add("entry", "Entry / glass door", 0, 0, 2594, STORE_H_MM)
    add("backlit", "Backlit display (entry left)", 0, 4200, 700, STORE_H_MM)

    # --- Central FOH ---
    add("nail_fragrance", "Nail & fragrance gondola", 2594, 1820, 3094, 2720)
    add("makeup_unit_center", "Makeup stations (centre)", 4441, 1820, 5341, 2720)
    add(
        "central_aisle",
        "FOH central aisle",
        700,
        900,
        7341,
        3830,
    )

    # --- Top wall brand shelves (green units) ---
    top_y2 = 710
    top_brands = [
        ("eb_zone", "EB / Salm", 2594, 0, 3400, top_y2),
        ("tfs_zone", "The Face Shop", 3400, 0, 4200, top_y2),
        ("good_vibes_zone", "Good Vibes", 4200, 0, 5000, top_y2),
        ("dermdoc_zone", "DermDoc", 5000, 0, 5800, top_y2),
        ("minimalist_zone", "Minimalist", 5800, 0, 6600, top_y2),
        ("aqualogica_zone", "Aqualogica", 6600, 0, 7400, top_y2),
        ("pilgrim_zone", "Pilgrim / Foxtale", 7400, 0, 8200, top_y2),
        ("dk_zone", "D&K / JC", 8200, 0, STORE_W_MM, top_y2),
    ]
    for zid, name, x1, y1, x2, y2 in top_brands:
        add(zid, name, x1, y1, x2, y2)

    add(
        "premium_skincare_zone",
        "Premium skincare (top wall)",
        5000,
        0,
        7400,
        top_y2,
    )
    add(
        "specialty_skincare",
        "Specialty skincare (top wall)",
        4200,
        0,
        5800,
        top_y2,
    )

    # --- Bottom wall brand shelves ---
    bot_y1 = 3830
    bottom_brands = [
        ("maybelline_zone", "Maybelline", 2594, bot_y1, 3312, STORE_H_MM),
        ("faces_zone", "Faces Canada", 3312, bot_y1, 4030, STORE_H_MM),
        ("lakme_zone", "Lakme", 4030, bot_y1, 4748, STORE_H_MM),
        ("mars_nybae_zone", "Mars + Ny Bae", 4748, bot_y1, 5466, STORE_H_MM),
        ("mens_care_zone", "Mens Care", 5466, bot_y1, 6184, STORE_H_MM),
        ("alps_loreal_zone", "Alps / L'Oreal", 6184, bot_y1, 6902, STORE_H_MM),
        ("beauty_counter", "Beauty counter", 6902, bot_y1, 7620, STORE_H_MM),
    ]
    for zid, name, x1, y1, x2, y2 in bottom_brands:
        add(zid, name, x1, y1, x2, y2)

    # --- Service / staff areas (right wall) ---
    add("cash_counter", "Cash counter + billing", 7341, 710, STORE_W_MM, 3830)
    add("access", "Staff access (rear)", 7620, bot_y1, STORE_W_MM, STORE_H_MM)

    return zones


def extract_xlsx_images(xlsx_path: Path, assets_dir: Path) -> List[str]:
    """Save embedded floor-plan images from the layout workbook."""
    import openpyxl

    assets_dir.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    for i, img in enumerate(ws._images):
        data = img._data()
        ext = "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
        dest = assets_dir / f"floor_plan_{i + 1}.{ext}"
        dest.write_bytes(data)
        saved.append(str(dest))
    wb.close()
    return saved


def build_layout_json(
    xlsx_path: Optional[Path] = None,
    assets_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build full store layout JSON from Brigade Road floor plan."""
    zones = brigade_road_zones_mm()
    entry_line = mm_line(2594, 0, 2594, STORE_H_MM)  # store entry plane (mm)

    layout: Dict[str, Any] = {
        "store_name": "Brigade Road, Bangalore",
        "store_id": "STORE_BLR_002",
        "layout_version": "1.2",
        "source": {
            "type": "xlsx_floor_plan",
            "file": str(xlsx_path) if xlsx_path else None,
            "store_width_mm": STORE_W_MM,
            "store_height_mm": STORE_H_MM,
            "notes": "Zones mapped from annotated mm dimensions on embedded floor-plan images.",
        },
        "video_resolution": {"width": VIDEO_W, "height": VIDEO_H},
        "zones": zones,
        "tripwire_line": entry_line,
        "cameras": [
            {
                "id": "CAM1",
                "name": "Entry Camera",
                "file_pattern": "CAM 1",
                "tripwire_line": mm_line(600, 0, 600, STORE_H_MM),
                "entry_side": "negative",
            },
            {
                "id": "CAM2",
                "name": "Floor A (FOH wide)",
                "file_pattern": "CAM 2",
                "tripwire_line": mm_line(0, 2600, STORE_W_MM, 2600),
                "entry_side": "negative",
            },
            {
                "id": "CAM3",
                "name": "Floor B (aisle)",
                "file_pattern": "CAM 3",
                "tripwire_line": mm_line(0, 2700, STORE_W_MM, 2700),
                "entry_side": "negative",
            },
            {
                "id": "CAM4",
                "name": "Floor C (shelves)",
                "file_pattern": "CAM 4",
                "tripwire_line": mm_line(4500, 0, 4500, STORE_H_MM),
                "entry_side": "negative",
            },
            {
                "id": "CAM5",
                "name": "Exit / billing rear",
                "file_pattern": "CAM 5",
                "tripwire_line": mm_line(7341, 0, 7341, STORE_H_MM),
                "entry_side": "positive",
            },
        ],
    }

    if xlsx_path and assets_dir:
        try:
            images = extract_xlsx_images(xlsx_path, assets_dir)
            layout["source"]["extracted_images"] = images
        except Exception as exc:
            layout["source"]["extract_error"] = str(exc)

    return layout


def load_from_xlsx(xlsx_path: str, output_json: str, assets_dir: Optional[str] = None) -> Dict[str, Any]:
    """Load xlsx, extract images, write store_layout.json."""
    xlsx = Path(xlsx_path)
    if not xlsx.exists():
        raise FileNotFoundError(f"Layout xlsx not found: {xlsx_path}")

    out = Path(output_json)
    assets = Path(assets_dir) if assets_dir else out.parent / "layout_assets"

    layout = build_layout_json(xlsx, assets)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(layout, f, indent=2)

    return layout


def main() -> int:
    parser = argparse.ArgumentParser(description="Build store_layout.json from Brigade Road xlsx")
    parser.add_argument(
        "xlsx_path",
        nargs="?",
        default="layouts/store_layout.xlsx",
        help="Path to Brigade Road layout xlsx",
    )
    parser.add_argument(
        "--output",
        default="events/store_layout.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--assets-dir",
        default="events/layout_assets",
        help="Directory for extracted floor-plan images",
    )
    args = parser.parse_args()

    print(f"Reading layout xlsx: {args.xlsx_path}")
    try:
        layout = load_from_xlsx(args.xlsx_path, args.output, args.assets_dir)
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    imgs = layout.get("source", {}).get("extracted_images", [])
    print(f"[OK] store_layout.json -> {args.output}")
    print(f"  Zones ({len(layout['zones'])}): {list(layout['zones'].keys())}")
    print(f"  Cameras: {[c['id'] for c in layout['cameras']]}")
    if imgs:
        print(f"  Extracted {len(imgs)} floor-plan image(s) to {args.assets_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
