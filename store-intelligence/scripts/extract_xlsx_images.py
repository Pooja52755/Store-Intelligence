#!/usr/bin/env python3
"""Extract embedded images from Brigade layout xlsx."""
import sys
from pathlib import Path

import openpyxl

XLSX = Path(r"C:\Users\Pooja\Downloads\Brigade Road - Store layoutc5f5d56.xlsx")
OUT = Path(__file__).resolve().parent.parent / "events" / "layout_assets"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.load_workbook(XLSX)
    ws = wb.active
    for i, img in enumerate(ws._images):
        data = img._data()
        ext = "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
        fp = OUT / f"floor_plan_{i + 1}.{ext}"
        fp.write_bytes(data)
        print(f"Saved {fp} ({len(data)} bytes)")
    wb.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
