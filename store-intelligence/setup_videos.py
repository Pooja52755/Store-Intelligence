#!/usr/bin/env python3
"""
Process original CCTV videos from Purplle and generate events.
"""
import os
import shutil
from pathlib import Path


def setup_videos():
    """Copy original CCTV videos to store-intelligence folder."""
    
    source_dir = r"C:\Users\Pooja\Downloads\CCTV Footage-20260529T160731Z-3-00144614ea\CCTV Footage"
    dest_dir = r"C:\Users\Pooja\Downloads\Purplle_EI_Challenge\store-intelligence\videos_input"
    
    source_path = Path(source_dir)
    dest_path = Path(dest_dir)
    
    print(f"Source: {source_dir}")
    print(f"Destination: {dest_dir}")
    
    # Create destination
    dest_path.mkdir(parents=True, exist_ok=True)
    
    # Find all MP4 files
    videos = list(source_path.glob("*.mp4"))
    
    if not videos:
        print("❌ No MP4 files found!")
        return False
    
    print(f"\n✓ Found {len(videos)} video files:")
    for video in videos:
        print(f"  - {video.name} ({video.stat().st_size / (1024**2):.2f} MB)")
    
    # Copy videos
    print(f"\nCopying videos to {dest_dir}...")
    for video in videos:
        dest_file = dest_path / video.name
        print(f"  Copying {video.name}...")
        shutil.copy2(video, dest_file)
        print(f"    ✓ {dest_file.stat().st_size / (1024**2):.2f} MB")
    
    print(f"\n✓ All {len(videos)} videos copied successfully!")
    return True


if __name__ == "__main__":
    setup_videos()
