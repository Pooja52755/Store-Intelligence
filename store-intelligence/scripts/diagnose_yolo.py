#!/usr/bin/env python3
"""YOLO + video diagnostic script for root-cause analysis."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

try:
    from ultralytics import YOLO
except ImportError as e:
    print(f"FATAL: ultralytics not installed: {e}")
    sys.exit(1)

CLIPS_DIR = Path(__file__).resolve().parent.parent / "pipeline" / "input_clips"
OUT_DIR = Path(__file__).resolve().parent.parent / "diagnostics"
CONF = 0.25
IOU = 0.5
PERSON_CLASS = 0


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = "yolov8n.pt"
    print("=" * 60)
    print("YOLO STARTUP DIAGNOSTICS")
    print("=" * 60)
    print(f"model_path: {model_path}")
    model = YOLO(model_path)
    print("model loaded successfully: True")
    print(f"classes available: {model.names}")
    print(f"person class id: {PERSON_CLASS} -> {model.names.get(PERSON_CLASS)}")
    print(f"confidence threshold (test): {CONF}")
    print(f"iou threshold (test): {IOU}")

    videos = sorted(CLIPS_DIR.glob("*.mp4"))
    print(f"\nFound {len(videos)} videos in {CLIPS_DIR}")
    if not videos:
        print("ERROR: No videos found")
        return 1

    summary = []
    for video_path in videos:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            print(f"\n{video_path.name}: CANNOT OPEN")
            summary.append({"video": video_path.name, "error": "cannot_open"})
            continue

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"\n--- {video_path.name} ---")
        print(f"  resolution: {w}x{h}, fps: {fps:.2f}, frames: {total}")

        sample_indices = [0, max(0, total // 4), max(0, total // 2), max(0, 3 * total // 4)]
        video_stats = {"video": video_path.name, "width": w, "height": h, "samples": []}

        for si, frame_idx in enumerate(sample_indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                print(f"  frame {frame_idx}: UNREADABLE")
                continue

            ok = bool(frame.size > 0 and frame.mean() > 1)
            out_img = OUT_DIR / f"{video_path.stem.replace(' ', '_')}_frame_{frame_idx}.jpg"
            cv2.imwrite(str(out_img), frame)

            # All classes
            res_all = model.predict(frame, conf=CONF, iou=IOU, verbose=False)[0]
            n_all = len(res_all.boxes) if res_all.boxes is not None else 0

            # Person only
            res_person = model.predict(frame, conf=CONF, iou=IOU, classes=[PERSON_CLASS], verbose=False)[0]
            persons = []
            if res_person.boxes is not None:
                for box in res_person.boxes:
                    cls_id = int(box.cls[0])
                    persons.append({
                        "class": model.names[cls_id],
                        "conf": round(float(box.conf[0]), 3),
                    })

            print(f"  frame {frame_idx}: readable={ok}, all_detections={n_all}, persons={len(persons)}")
            if persons:
                print(f"    person confidences: {[p['conf'] for p in persons[:10]]}")
            else:
                # Show what WAS detected if any
                if res_all.boxes is not None and len(res_all.boxes):
                    for box in res_all.boxes[:5]:
                        cid = int(box.cls[0])
                        print(f"    non-person: {model.names[cid]} conf={float(box.conf[0]):.3f}")

            video_stats["samples"].append({
                "frame_idx": frame_idx,
                "readable": ok,
                "all_detections": n_all,
                "person_count": len(persons),
                "persons": persons[:10],
                "saved_frame": str(out_img),
            })

        cap.release()
        summary.append(video_stats)

    out_json = OUT_DIR / "yolo_diagnostic_summary.json"
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary written to {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
