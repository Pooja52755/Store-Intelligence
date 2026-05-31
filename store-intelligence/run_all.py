#!/usr/bin/env python3
"""
Run the complete Store Intelligence stack using Purplle-provided resources.

Resources (defaults):
  - CCTV:     .../CCTV Footage/CAM 1.mp4 ... CAM 5.mp4
  - Layout:   .../Brigade Road - Store layoutc5f5d56.xlsx
  - Sales:    .../Brigade_Bangalore_10_April_26 (1)bc6219c.csv  (POS ground truth)

Steps:
  1. Build store_layout.json from layout xlsx
  2. Copy CCTV clips
  3. Run YOLO detection pipeline -> events/events.jsonl
  4. Ingest events into FastAPI (docker)
  5. Verify /health and /metrics

Usage:
  python run_all.py
  docker compose up -d   # if not already running
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent

DEFAULT_CCTV = Path(
    r"C:\Users\Pooja\Downloads\CCTV Footage-20260529T160731Z-3-00144614ea\CCTV Footage"
)
DEFAULT_LAYOUT = Path(r"C:\Users\Pooja\Downloads\Brigade Road - Store layoutc5f5d56.xlsx")
DEFAULT_SALES = Path(
    r"C:\Users\Pooja\Downloads\Brigade_Bangalore_10_April_26 (1)bc6219c.csv"
)
API_URL = "http://localhost:8000"
STORE_ID = "STORE_BLR_002"


def sales_summary(csv_path: Path) -> dict:
    """Summarise Purplle POS CSV (ground-truth transactions)."""
    import csv

    if not csv_path.exists():
        return {"error": f"not found: {csv_path}"}

    orders = set()
    rows = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows += 1
            oid = row.get("order_id") or row.get("invoice_number")
            if oid:
                orders.add(str(oid).strip())
    return {
        "file": str(csv_path),
        "line_items": rows,
        "unique_orders": len(orders),
        "store": "Brigade_Bangalore (ST1008)",
        "date": "2026-04-10",
    }


def run_step(cmd: list, cwd: Path) -> bool:
    print(f"\n>> {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=str(cwd))
    return r.returncode == 0


async def verify_api() -> bool:
    ok = True
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            h = await client.get(f"{API_URL}/health")
            print(f"\n[health] {h.status_code} {h.text[:200]}")
            ok = h.status_code == 200
        except Exception as e:
            print(f"\n[health] FAILED: {e}")
            return False

        try:
            m = await client.get(f"{API_URL}/stores/{STORE_ID}/metrics")
            print(f"[metrics] {m.status_code} {m.text}")
            ok = ok and m.status_code == 200
        except Exception as e:
            print(f"[metrics] FAILED: {e}")
            ok = False

        try:
            f = await client.get(f"{API_URL}/stores/{STORE_ID}/funnel")
            print(f"[funnel] {f.status_code} {f.text[:300]}")
        except Exception as e:
            print(f"[funnel] FAILED: {e}")

    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full Purplle Store Intelligence pipeline")
    parser.add_argument("--cctv-dir", type=Path, default=DEFAULT_CCTV)
    parser.add_argument("--layout-xlsx", type=Path, default=DEFAULT_LAYOUT)
    parser.add_argument("--sales-csv", type=Path, default=DEFAULT_SALES)
    parser.add_argument("--store-id", default=STORE_ID)
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--frame-stride", type=int, default=10)
    args = parser.parse_args()

    print("=" * 60)
    print("PURPLLE STORE INTELLIGENCE — FULL RUN")
    print("=" * 60)

    for label, p in [
        ("CCTV", args.cctv_dir),
        ("Layout xlsx", args.layout_xlsx),
        ("Sales CSV", args.sales_csv),
    ]:
        status = "OK" if p.exists() else "MISSING"
        print(f"  [{status}] {label}: {p}")

    pos = sales_summary(args.sales_csv)
    print(f"\n  POS ground truth: {json.dumps(pos, indent=2)}")

    if not args.cctv_dir.exists():
        print("\nERROR: CCTV folder not found.")
        return 1
    if not args.layout_xlsx.exists():
        print("\nERROR: Layout xlsx not found.")
        return 1

    # 1 — layout
    if not run_step(
        [
            sys.executable,
            "prepare_layout.py",
            str(args.layout_xlsx),
            "--output",
            "events/store_layout.json",
        ],
        ROOT,
    ):
        return 1

    # 2–3 — copy clips + detect (via run_pipeline)
    import os

    env = os.environ.copy()
    env["PIPELINE_FRAME_STRIDE"] = str(args.frame_stride)
    env["YOLO_CONF"] = "0.35"

    cmd = [
        sys.executable,
        "run_pipeline.py",
        "--clips-dir",
        str(args.cctv_dir),
        "--layout-xlsx",
        str(args.layout_xlsx),
        "--store-id",
        args.store_id,
    ]
    print(f"\n>> {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if r.returncode != 0:
        return r.returncode

    events_file = ROOT / "events" / "events.jsonl"
    if not events_file.exists() or events_file.stat().st_size == 0:
        print("\nERROR: No events generated.")
        return 1

    lines = sum(1 for _ in open(events_file, encoding="utf-8"))
    print(f"\n  Generated {lines} events in {events_file}")

    # 4 — ingest
    if not args.skip_ingest:
        if not run_step(
            [
                sys.executable,
                "ingest_events.py",
                "--events-file",
                str(events_file),
                "--api-url",
                args.api_url,
            ],
            ROOT,
        ):
            print("\nWARN: Ingest failed — is docker compose up?")
            print("  Run: docker compose up -d")
            return 1

    # 5 — verify
    if not args.skip_ingest:
        if not asyncio.run(verify_api()):
            print("\nWARN: API verification had issues.")
            return 1

    print("\n" + "=" * 60)
    print("DONE")
    print("  Dashboard: http://localhost:3000")
    print("  API docs:  http://localhost:8000/docs")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
