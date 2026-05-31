#!/usr/bin/env python3
"""
Setup and run the store intelligence pipeline.

This script:
1. Prepares the store layout JSON from CSV
2. Copies video files to the pipeline input directory
3. Runs the detection pipeline
4. Ingests events into the API

Usage:
    python run_pipeline.py \
        --clips-dir "C:\\Users\\Pooja\\Downloads\\CCTV Footage-20260529T160731Z-3-00144614ea\\CCTV Footage" \
        --layout-xlsx "C:\\Users\\Pooja\\Downloads\\Brigade Road - Store layoutc5f5d56.xlsx" \
        --store-id STORE_BLR_002
"""
import os
import sys
import json
import subprocess
import argparse
import shutil
from pathlib import Path
from datetime import datetime, timezone


def run_command(cmd, description=""):
    """Run shell command."""
    if description:
        print(f"\n{'='*60}")
        print(f">> {description}")
        print(f"{'='*60}")
    
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode != 0:
        print(f"[FAILED] Command failed with exit code {result.returncode}")
        return False
    
    print(f"[OK] Command completed successfully")
    return True


def prepare_layout(layout_source: str, output_json: str) -> bool:
    """Prepare store_layout.json from Brigade Road layout xlsx."""
    output_path = Path(output_json)
    source = Path(layout_source)

    default_xlsx = Path(r"C:\Users\Pooja\Downloads\Brigade Road - Store layoutc5f5d56.xlsx")
    if source.suffix.lower() == ".xlsx" and source.exists():
        xlsx_path = source
    elif default_xlsx.exists():
        xlsx_path = default_xlsx
        print(f"\nUsing Brigade Road layout xlsx: {xlsx_path}")
    else:
        bundled = Path(__file__).parent / "events" / "store_layout.json"
        if bundled.exists():
            print(f"\nFallback bundled layout: {bundled}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled, output_path)
            return True
        print(f"Error: no layout xlsx at {layout_source} or {default_xlsx}")
        return False

    try:
        from prepare_layout import load_from_xlsx
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from prepare_layout import load_from_xlsx

    assets_dir = output_path.parent / "layout_assets"
    try:
        layout = load_from_xlsx(str(xlsx_path), str(output_path), str(assets_dir))
        print(f"[OK] Store layout JSON ready: {output_path}")
        print(f"  Zones: {list(layout.get('zones', {}).keys())}")
        print(f"  Cameras: {[c['id'] for c in layout.get('cameras', [])]}")
        imgs = layout.get("source", {}).get("extracted_images", [])
        if imgs:
            print(f"  Floor-plan images: {len(imgs)} extracted")
        return True
    except Exception as exc:
        print(f"Error preparing layout: {exc}")
        return False


def prepare_clips(clips_src: str, clips_dest: str = "./pipeline/input_clips") -> bool:
    """Copy video clips to pipeline input directory."""
    src_path = Path(clips_src)
    dest_path = Path(clips_dest)
    
    if not src_path.exists():
        print(f"Error: Source clips directory not found: {clips_src}")
        return False
    
    # Create destination
    dest_path.mkdir(parents=True, exist_ok=True)
    
    # Find video files
    video_files = list(src_path.glob("*.mp4"))
    
    if not video_files:
        print(f"Warning: No .mp4 files found in {clips_src}")
        return False
    
    print(f"\nCopying {len(video_files)} video files...")
    for video_file in video_files:
        dest_file = dest_path / video_file.name
        print(f"  Copying: {video_file.name}")
        shutil.copy2(video_file, dest_file)
    
    print(f"[OK] Video files copied to: {dest_path}")
    return True


def run_pipeline(clips_dir: str, layout_json: str, output_file: str, store_id: str):
    """Run the detection pipeline."""
    print(f"\n{'='*60}")
    print(f">> Running Detection Pipeline")
    print(f"{'='*60}")
    print(f"  Clips: {clips_dir}")
    print(f"  Layout: {layout_json}")
    print(f"  Output: {output_file}")
    print(f"  Store: {store_id}")
    
    # Verify paths
    if not Path(clips_dir).exists():
        print(f"Error: Clips directory not found: {clips_dir}")
        return False
    
    if not Path(layout_json).exists():
        print(f"Error: Layout JSON not found: {layout_json}")
        return False
    
    # Create output directory
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    
    # Run pipeline
    cmd = [
        sys.executable, "pipeline/detect.py",
        "--clips-dir", clips_dir,
        "--layout", layout_json,
        "--output", output_file,
        "--store-id", store_id
    ]
    
    print(f"\nCommand: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description='Setup and run the store intelligence pipeline')
    parser.add_argument(
        '--clips-dir',
        required=True,
        help='Source directory containing CCTV video files (CAM1.mp4, CAM2.mp4, etc.)'
    )
    parser.add_argument(
        '--layout-xlsx',
        default=r'C:\Users\Pooja\Downloads\Brigade Road - Store layoutc5f5d56.xlsx',
        help='Brigade Road store layout xlsx (embedded floor-plan images)'
    )
    parser.add_argument(
        '--layout-csv',
        default='',
        help='Deprecated alias for --layout-xlsx'
    )
    parser.add_argument(
        '--store-id',
        default='STORE_BLR_002',
        help='Store identifier (default: STORE_BLR_002)'
    )
    parser.add_argument(
        '--output-dir',
        default='./events',
        help='Output directory for generated events (default: ./events)'
    )
    parser.add_argument(
        '--skip-copy',
        action='store_true',
        help='Skip copying video files (use if already copied)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually running'
    )
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("STORE INTELLIGENCE PIPELINE SETUP")
    print("="*60)
    print(f"Date: {datetime.now(timezone.utc).isoformat()}")
    
    # Step 1: Prepare layout
    layout_json = Path(args.output_dir) / "store_layout.json"
    layout_src = args.layout_xlsx or args.layout_csv or str(
        Path(__file__).parent / "events" / "store_layout.json"
    )
    if not prepare_layout(layout_src, str(layout_json)):
        print("[FAILED] Failed to prepare layout")
        return 1
    
    # Step 2: Prepare clips
    clips_dest = "./pipeline/input_clips"
    if not args.skip_copy:
        if not prepare_clips(args.clips_dir, clips_dest):
            print("[FAILED] Failed to prepare clips")
            return 1
    else:
        clips_dest = args.clips_dir
        print(f"Using existing clips: {clips_dest}")
    
    if args.dry_run:
        print("\n[DRY RUN] Would run pipeline with:")
        print(f"  Clips: {clips_dest}")
        print(f"  Layout: {layout_json}")
        print(f"  Store: {args.store_id}")
        return 0
    
    # Step 3: Run pipeline
    output_file = Path(args.output_dir) / "events.jsonl"
    if not run_pipeline(clips_dest, str(layout_json), str(output_file), args.store_id):
        print("[FAILED] Pipeline execution failed")
        return 1

    print("\n" + "=" * 60)
    print("[OK] PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 60)
    print(f"\nGenerated events: {output_file}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
