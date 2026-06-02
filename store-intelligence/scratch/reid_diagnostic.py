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

print("Loading model...")
model = YOLO(model_path)

tracker = ReIDTracker(similarity_threshold=0.75)
embedder = MockOSNetEmbedder(embedding_dim=128)

cap = cv2.VideoCapture(video_path)
if not cap.isOpened():
    print("Could not open video.")
    sys.exit(1)

frame_idx = 0
PERSON_CLASS_ID = 0
start_time = datetime.now(timezone.utc)

print("Starting video diagnostic on the first 150 frames...")
track_mappings = {}
active_embeddings = {}

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
                
            emb = embedder.extract(crop)
            visitor_id, is_reentry = tracker.match_or_create(emb, track_id, start_time)
            
            if track_id not in track_mappings:
                track_mappings[track_id] = visitor_id
                active_embeddings[track_id] = emb
                print(f"Frame {frame_idx}: New track {track_id} -> Visitor {visitor_id}")
                
                # Print similarities to all existing tracks
                for other_track_id, other_emb in active_embeddings.items():
                    if other_track_id != track_id:
                        sim = tracker._cosine_similarity(emb, other_emb)
                        print(f"  Similarity between track {track_id} and track {other_track_id}: {sim:.4f}")
                        
    frame_idx += 1

cap.release()
print("\nFinal track mappings:")
for tid, vid in track_mappings.items():
    print(f"  Track {tid} -> Visitor {vid}")
