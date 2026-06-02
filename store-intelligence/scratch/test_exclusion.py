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
            
            # Use frame_idx as a proxy for timestamp to strictly group same-frame detections
            frames_data.append((frame_idx, track_id, crop))
            
    frame_idx += 1

cap.release()

def run_exclusion_simulation(threshold, enable_mirror_suppression=True, enforce_same_frame_exclusion=True):
    tracker = ReIDTracker(similarity_threshold=threshold)
    embedder = MockOSNetEmbedder(embedding_dim=128)
    
    track_to_visitor = {}
    visitor_buffer = {} # visitor_id -> (embedding, timestamp, was_active)
    
    last_frame_idx = -1
    assigned_this_frame = set()
    
    for f_idx, track_id, crop in frames_data:
        if f_idx != last_frame_idx:
            assigned_this_frame = set()
            last_frame_idx = f_idx
            
        emb = embedder.extract(crop)
        
        if track_id in track_to_visitor:
            vid = track_to_visitor[track_id]
            visitor_buffer[vid] = (emb, f_idx, True)
            assigned_this_frame.add(vid)
            continue
            
        # Try to match
        best_visitor_id = None
        best_similarity = 0
        
        for vid, (stored_emb, stored_ts, was_active) in visitor_buffer.items():
            # Physical constraint: do not match if already assigned to another track in this frame
            if enforce_same_frame_exclusion and vid in assigned_this_frame:
                continue
                
            sim = tracker._cosine_similarity(emb, stored_emb)
            if sim >= threshold and sim > best_similarity:
                best_similarity = sim
                best_visitor_id = vid
                
        if best_visitor_id:
            track_to_visitor[track_id] = best_visitor_id
            visitor_buffer[best_visitor_id] = (emb, f_idx, True)
            assigned_this_frame.add(best_visitor_id)
            continue
            
        # Mirror suppression
        if enable_mirror_suppression:
            suppressed = False
            for vid, (stored_emb, stored_ts, was_active) in visitor_buffer.items():
                if enforce_same_frame_exclusion and vid in assigned_this_frame:
                    continue
                sim = tracker._cosine_similarity(emb, stored_emb)
                if sim >= (threshold - 0.1) and was_active:
                    track_to_visitor[track_id] = vid
                    assigned_this_frame.add(vid)
                    suppressed = True
                    break
            if suppressed:
                continue
                
        # Create new
        vid = tracker._generate_visitor_id(emb)
        track_to_visitor[track_id] = vid
        visitor_buffer[vid] = (emb, f_idx, True)
        assigned_this_frame.add(vid)
        
    unique_vids = set(track_to_visitor.values())
    return track_to_visitor, unique_vids

print("\n--- SIMULATION WITH SAME-FRAME EXCLUSION ---")
for thresh in [0.75, 0.80, 0.85, 0.88]:
    for mirror in [True, False]:
        for excl in [True, False]:
            t_map, u_vids = run_exclusion_simulation(thresh, enable_mirror_suppression=mirror, enforce_same_frame_exclusion=excl)
            print(f"Thresh: {thresh} | Mirror: {mirror} | Excl: {excl} -> Unique Visitors: {len(u_vids)}")
            if len(u_vids) > 1:
                print(f"  Mappings: {dict(sorted(t_map.items()))}")
