import cv2
import numpy as np
from datetime import datetime, timezone
import sys
import os

# Include pipeline directory in sys.path
sys.path.append(os.path.abspath('pipeline'))
from tracker import ReIDTracker, MockOSNetEmbedder
from ultralytics import YOLO

video_path = 'uploads/STORE_BLR_002/5dfb6818-c85e-4541-9be9-f8815ab80b00/CAM2.mp4'
model_path = 'yolov8n.pt'

model = YOLO(model_path)
cap = cv2.VideoCapture(video_path)

# Collect all tracks, frames, and crops
frames_data = []
frame_idx = 0
PERSON_CLASS_ID = 0

print("Extracting track crops from first 150 frames...")
while frame_idx < 150:
    ret, frame = cap.read()
    if not ret:
        break
    
    if frame_idx % 5 != 0:
        frame_idx += 1
        continue
        
    results = model.track(
        frame,
        persist=True,
        conf=0.35,
        iou=0.5,
        classes=[PERSON_CLASS_ID],
        tracker="bytetrack.yaml",
        verbose=False,
    )
    
    for result in results:
        if result.boxes is None or len(result.boxes) == 0:
            continue
            
        for idx, box in enumerate(result.boxes):
            if box.id is None:
                continue
            track_id = int(box.id[0])
            xyxy = box.xyxy[0].cpu().numpy()
            x1, y1, x2, y2 = xyxy
            
            crop = frame[int(y1):int(y2), int(x1):int(x2)]
            if crop.size == 0:
                continue
            
            frames_data.append((frame_idx, track_id, crop))
            
    frame_idx += 1

cap.release()

def run_tracker_simulation(threshold, enable_mirror_suppression=True, active_only_matching=False):
    tracker = ReIDTracker(similarity_threshold=threshold)
    embedder = MockOSNetEmbedder(embedding_dim=128)
    start_time = datetime.now(timezone.utc)
    
    # Custom match_or_create logic to test variations
    track_to_visitor = {}
    visitor_buffer = {} # visitor_id -> (embedding, timestamp, was_active, active_track_id)
    
    for f_idx, track_id, crop in frames_data:
        emb = embedder.extract(crop)
        
        if track_id in track_to_visitor:
            vid = track_to_visitor[track_id]
            visitor_buffer[vid] = (emb, start_time, True, track_id)
            continue
            
        # Try to match
        best_visitor_id = None
        best_similarity = 0
        best_was_inactive = False
        
        for vid, (stored_emb, stored_ts, was_active, active_tid) in visitor_buffer.items():
            # If active_only_matching is True and the visitor currently has an active track in the same frame/recently,
            # we shouldn't match a new track to it.
            if active_only_matching and was_active:
                continue
                
            sim = tracker._cosine_similarity(emb, stored_emb)
            if sim >= threshold and sim > best_similarity:
                best_similarity = sim
                best_visitor_id = vid
                best_was_inactive = not was_active
                
        if best_visitor_id:
            track_to_visitor[track_id] = best_visitor_id
            visitor_buffer[best_visitor_id] = (emb, start_time, True, track_id)
            continue
            
        # Mirror suppression
        if enable_mirror_suppression:
            suppressed = False
            for vid, (stored_emb, stored_ts, was_active, active_tid) in visitor_buffer.items():
                sim = tracker._cosine_similarity(emb, stored_emb)
                if sim >= (threshold - 0.1) and was_active:
                    track_to_visitor[track_id] = vid
                    suppressed = True
                    break
            if suppressed:
                continue
                
        # Create new
        vid = tracker._generate_visitor_id(emb)
        track_to_visitor[track_id] = vid
        visitor_buffer[vid] = (emb, start_time, True, track_id)
        
    unique_vids = set(track_to_visitor.values())
    return track_to_visitor, unique_vids

print("\n--- SIMULATION RESULTS ---")
for thresh in [0.75, 0.80, 0.85, 0.88, 0.90]:
    for mirror in [True, False]:
        for active_only in [True, False]:
            # Skip redundant combinations
            if not mirror and active_only:
                continue
            t_map, u_vids = run_tracker_simulation(thresh, enable_mirror_suppression=mirror, active_only_matching=active_only)
            print(f"Threshold: {thresh} | Mirror Suppress: {mirror} | Active-Only: {active_only} -> Unique Visitors: {len(u_vids)}")
            if len(u_vids) > 1:
                print(f"  Mappings: {dict(sorted(t_map.items()))}")
