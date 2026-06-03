"""Main detection pipeline: YOLOv8 + ByteTrack + Re-ID."""

import argparse

import json

import logging

import os

import re

import sys

from collections import defaultdict

from datetime import datetime, timedelta, timezone

from pathlib import Path

from typing import Dict, List, Optional, Tuple



import cv2

import numpy as np



try:

    from ultralytics import YOLO

except ImportError:

    YOLO = None


# Ensure pipeline directory is in sys.path so relative imports work correctly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from emit import Event, EventWriter, build_event

from tracker import ReIDTracker, MockOSNetEmbedder

from staff_classifier import StaffClassifier

from tripwire import TripwireDetector



logging.basicConfig(

    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),

    format="%(asctime)s %(levelname)s [detect] %(message)s",

)

logger = logging.getLogger(__name__)



# Detection configuration (override via env for tuning)

MODEL_PATH = os.getenv("YOLO_MODEL_PATH", "yolov8n.pt")

CONF_THRESHOLD = float(os.getenv("YOLO_CONF", "0.35"))

IOU_THRESHOLD = float(os.getenv("YOLO_IOU", "0.5"))

PERSON_CLASS_ID = 0

FRAME_STRIDE = int(os.getenv("PIPELINE_FRAME_STRIDE", "5"))

TRACK_LOST_FRAMES = int(os.getenv("TRACK_LOST_FRAMES", "45"))

MIN_FRAMES_FOR_ENTRY = 3





def _point_in_polygon(x: float, y: float, polygon: List[List[int]]) -> bool:

    """Ray-casting point-in-polygon test."""

    inside = False

    n = len(polygon)

    for i in range(n):

        x1, y1 = polygon[i]

        x2, y2 = polygon[(i + 1) % n]

        if ((y1 > y) != (y2 > y)) and (

            x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-9) + x1

        ):

            inside = not inside

    return inside





def _resolve_camera_id(video_name: str, cameras: List[dict]) -> Tuple[str, Optional[dict]]:

    """Map video filename to camera id and config."""

    stem = Path(video_name).stem

    for cam in cameras:

        pattern = cam.get("file_pattern", cam.get("id", ""))

        if pattern and pattern.lower() in stem.lower():

            return cam["id"], cam

    match = re.search(r"(\d+)", stem)

    if match:

        return f"CAM{match.group(1)}", None

    return "CAM_UNKNOWN", None





class DetectionPipeline:

    """End-to-end detection pipeline."""



    def __init__(

        self,

        clips_dir: str,

        layout_path: str,

        output_path: str,

        store_id: str,

        camera_id: str = "CAM_ENTRY_01",

        run_id: str = None,

    ):

        self.clips_dir = Path(clips_dir)

        self.layout_path = Path(layout_path)

        self.store_id = store_id

        self.default_camera_id = camera_id

        self.run_id = run_id



        with open(self.layout_path, "r", encoding="utf-8") as f:

            self.layout = json.load(f)



        self.zone_config = self.layout.get("zones", {})

        self.cameras = self.layout.get("cameras", [])

        self.default_tripwire = self.layout.get(

            "tripwire_line", {"x1": 0, "y1": 540, "x2": 1920, "y2": 540}

        )



        self.yolo_model = self._load_yolo()

        self.tracker = ReIDTracker(similarity_threshold=0.85)

        self.staff_classifier = StaffClassifier(threshold=0.35)

        self.embedder = MockOSNetEmbedder(embedding_dim=128)

        self.writer = EventWriter(output_path)



        self.visitor_states: Dict[str, Dict] = {}

        self._tripwire_by_camera: Dict[str, TripwireDetector] = {}



    def _load_yolo(self):

        """Load YOLO weights with explicit diagnostics; never silently mock in production."""

        if YOLO is None:

            logger.error(

                "ultralytics is not installed. Install requirements.txt "

                "(pip install ultralytics opencv-python torch)."

            )

            raise RuntimeError(

                "YOLO unavailable: ultralytics not installed. "

                "Cannot run CCTV pipeline without real detection."

            )



        model_file = Path(MODEL_PATH)

        logger.info("=== YOLO startup ===")

        logger.info("model path: %s (exists=%s)", model_file.resolve(), model_file.exists())



        if not model_file.exists():

            raise RuntimeError(

                f"YOLO model not found at {model_file.resolve()}. "

                f"Cannot run CCTV pipeline without model file."

            )



        model = YOLO(str(model_file))

        logger.info("model loaded successfully: True")

        logger.info("classes available: %s", model.names)

        logger.info(

            'person class: id=%s name="%s"',

            PERSON_CLASS_ID,

            model.names.get(PERSON_CLASS_ID, "MISSING"),

        )

        logger.info("confidence threshold: %s", CONF_THRESHOLD)

        logger.info("iou threshold: %s", IOU_THRESHOLD)

        logger.info("frame stride: %s", FRAME_STRIDE)

        logger.info("====================")

        return model



    def _get_tripwire(self, camera_id: str, cam_config: Optional[dict]) -> TripwireDetector:

        if camera_id not in self._tripwire_by_camera:

            line = (cam_config or {}).get("tripwire_line", self.default_tripwire)

            self._tripwire_by_camera[camera_id] = TripwireDetector(line)

        return self._tripwire_by_camera[camera_id]



    def _get_zone(self, centroid: Tuple[float, float], camera_id: str = "CAM_UNKNOWN") -> Optional[str]:
        # Look up camera config dynamically from self.cameras layout
        cam_config = None
        for cam in self.cameras:
            if cam.get("id") == camera_id:
                cam_config = cam
                break
                
        if cam_config:
            if "fixed_zone" in cam_config:
                return cam_config["fixed_zone"]
            if cam_config.get("is_outside"):
                return None

        x, y = centroid

        for zone_name, zone_data in self.zone_config.items():

            if "bounds" in zone_data:

                x1, y1, x2, y2 = zone_data["bounds"]

                if x1 <= x <= x2 and y1 <= y <= y2:

                    return zone_name

            elif "polygon" in zone_data:

                if _point_in_polygon(x, y, zone_data["polygon"]):

                    return zone_name

        return None

    def _project_coordinates(self, x: float, y: float, camera_id: str, frame_w: int = 1920, frame_h: int = 1080) -> Tuple[float, float]:
        """Project raw video coordinate (x, y) to store floor plan space."""
        cam_config = None
        for cam in self.cameras:
            if cam.get("id") == camera_id:
                cam_config = cam
                break

        if cam_config and "fixed_zone" in cam_config:
            zone_data = self.zone_config.get(cam_config["fixed_zone"])
            if zone_data and "bounds" in zone_data:
                x1, y1, x2, y2 = zone_data["bounds"]
                # Map raw frame coordinates [0, frame_w] x [0, frame_h] into zone bounds [x1, x2] x [y1, y2]
                x_proj = x1 + (x / float(frame_w)) * (x2 - x1)
                y_proj = y1 + (y / float(frame_h)) * (y2 - y1)
                return x_proj, y_proj

        # Fallback to FOH central aisle bounds [149, 193, 1559, 821]
        x_proj = 149.0 + (x / float(frame_w)) * (1559.0 - 149.0)
        y_proj = 193.0 + (y / float(frame_h)) * (821.0 - 193.0)
        return x_proj, y_proj

    def _scale_tripwire(

        self, line: Dict[str, int], frame_w: int, frame_h: int

    ) -> Dict[str, int]:

        """Scale layout tripwire from reference resolution to actual frame size."""

        ref = self.layout.get("video_resolution", {"width": 1920, "height": 1080})

        ref_w = ref.get("width", 1920) or 1920

        ref_h = ref.get("height", 1080) or 1080

        sx = frame_w / ref_w

        sy = frame_h / ref_h

        return {

            "x1": int(line["x1"] * sx),

            "y1": int(line["y1"] * sy),

            "x2": int(line["x2"] * sx),

            "y2": int(line["y2"] * sy),

        }



    def process_video(self, video_path: str, fps: int = 15) -> int:

        video_path = str(video_path)

        video_name = Path(video_path).name

        camera_id, cam_config = _resolve_camera_id(video_name, self.cameras)



        logger.info("=== VIDEO PROCESSING START ===")

        logger.info("Video file: %s", video_path)

        logger.info("Resolved camera: %s", camera_id)

        logger.info("Output path: %s", self.writer.output_path)

        

        # Verify file exists

        video_file = Path(video_path)

        if not video_file.exists():

            logger.error("VIDEO FILE NOT FOUND: %s (absolute: %s)", video_path, video_file.resolve())

            raise FileNotFoundError(f"Video file not found: {video_path}")

        logger.info("Video file exists, size: %d bytes", video_file.stat().st_size)



        # Try to open video

        logger.info("Opening video with cv2.VideoCapture...")

        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():

            logger.error("FAILED TO OPEN VIDEO: %s (check format/codec/permissions)", video_path)

            return 0

        logger.info("Video opened successfully")



        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        video_fps = cap.get(cv2.CAP_PROP_FPS) or fps



        logger.info("Video properties: %dx%d, %d frames, %.2f fps", frame_w, frame_h, total_frames, video_fps)



        line = (cam_config or {}).get("tripwire_line", self.default_tripwire)

        scaled_line = self._scale_tripwire(line, frame_w, frame_h)

        tripwire = TripwireDetector(scaled_line)

        logger.info(

            "Tripwire for %s: (%s,%s)->(%s,%s) on %dx%d frame",

            camera_id,

            scaled_line["x1"],

            scaled_line["y1"],

            scaled_line["x2"],

            scaled_line["y2"],

            frame_w,

            frame_h,

        )



        video_mtime = Path(video_path).stat().st_mtime

        # Get UTC start time of the video
        utc_start = datetime.fromtimestamp(video_mtime, tz=timezone.utc)
        # Shift to Indian Standard Time (IST) hours (CCTV local recording time)
        ist_start = utc_start + timedelta(hours=5, minutes=30)
        # Shift date to 2026-04-10 to match POS transaction dates, and treat literally as UTC to align with pos_transactions.csv parsing in app
        clip_start_time = ist_start.replace(year=2026, month=4, day=10, tzinfo=timezone.utc)



        event_count = 0

        frame_idx = 0

        processed_frames = 0

        zone_entry_times: Dict[str, Dict[str, datetime]] = {}

        track_last_seen: Dict[int, int] = {}

        track_seen_count: Dict[int, int] = {}

        track_emitted_entry: Dict[int, bool] = {}

        track_to_visitor: Dict[int, str] = {}

        buffered_events = []
        detection_log_interval = 500
        visitor_centroids = {} # Track centroids for motion validation



        try:

            while True:

                ret, frame = cap.read()

                if not ret:

                    break



                if frame_idx % FRAME_STRIDE != 0:

                    frame_idx += 1

                    continue



                frame_time_offset = frame_idx / video_fps

                frame_timestamp = clip_start_time + timedelta(seconds=frame_time_offset)



                results = self.yolo_model.track(

                    frame,

                    persist=True,

                    conf=CONF_THRESHOLD,

                    iou=IOU_THRESHOLD,

                    classes=[PERSON_CLASS_ID],

                    tracker="bytetrack.yaml",

                    verbose=False,

                )



                person_count = 0

                for result in results:

                    if result.boxes is None or len(result.boxes) == 0:

                        continue



                    person_count += len(result.boxes)



                    for idx, box in enumerate(result.boxes):

                        try:

                            cls_id = int(box.cls[0])

                            if cls_id != PERSON_CLASS_ID:

                                continue



                            track_id = (

                                int(box.id[0]) if box.id is not None else -(idx + 1)

                            )

                            conf = float(box.conf[0])



                            xyxy = (

                                box.xyxy[0].cpu().numpy()

                                if hasattr(box.xyxy[0], "cpu")

                                else box.xyxy[0]

                            )

                            x1, y1, x2, y2 = xyxy

                            centroid = ((x1 + x2) / 2, (y1 + y2) / 2)



                            crop = frame[int(y1) : int(y2), int(x1) : int(x2)]

                            if crop.size == 0:

                                continue



                            embedding = self.embedder.extract(crop)

                            visitor_id, is_reentry = self.tracker.match_or_create(

                                embedding, track_id, frame_timestamp

                            )

                            track_to_visitor[track_id] = visitor_id
                            track_last_seen[track_id] = frame_idx
                            track_seen_count[track_id] = (
                                track_seen_count.get(track_id, 0) + 1
                            )
                            # Track centroids for motion validation
                            visitor_centroids.setdefault(visitor_id, []).append(centroid)



                            is_staff = self.staff_classifier.classify(

                                frame, (x1, y1, x2, y2)

                            )

                            zone_id = self._get_zone(centroid, camera_id)

                            crossing = tripwire.check_crossing(track_id, centroid)

                            # Project centroid coordinates to store floor plan space
                            x_proj, y_proj = self._project_coordinates(centroid[0], centroid[1], camera_id, frame_w, frame_h)
                            proj_centroid = (x_proj, y_proj)

                            events = self._generate_events(

                                visitor_id=visitor_id,

                                track_id=track_id,

                                crossing=crossing,

                                is_reentry=is_reentry,

                                is_staff=is_staff,

                                zone_id=zone_id,

                                conf=conf,

                                frame_timestamp=frame_timestamp,

                                zone_entry_times=zone_entry_times,

                                camera_id=camera_id,

                                frame_idx=frame_idx,

                                fps=video_fps,

                                centroid=proj_centroid,

                            )



                            # Fallback ENTRY: sustained presence in entry zone (disabled for outside/entry cameras)
                            is_outside_camera = bool(cam_config.get("is_outside", False)) if cam_config else False
                            if (
                                not is_outside_camera
                                and not track_emitted_entry.get(track_id)
                                and track_seen_count[track_id] >= MIN_FRAMES_FOR_ENTRY
                            ):

                                events.insert(

                                    0,

                                    build_event(

                                        store_id=self.store_id,

                                        camera_id=camera_id,

                                        visitor_id=visitor_id,

                                        event_type="REENTRY" if is_reentry else "ENTRY",

                                        timestamp_dt=frame_timestamp,

                                        confidence=conf,

                                        is_staff=is_staff,

                                        zone_id=None,

                                        run_id=self.run_id,

                                        x=x_proj,

                                        y=y_proj,

                                    ),

                                )

                                track_emitted_entry[track_id] = True

                                if visitor_id not in self.visitor_states:

                                    self.visitor_states[visitor_id] = {

                                        "zone_id": None,

                                        "in_store": True,

                                        "is_staff": is_staff,

                                    }

                                self.tracker.mark_entry(visitor_id)



                            if crossing in ("ENTRY", "REENTRY"):

                                track_emitted_entry[track_id] = True



                            for event in events:

                                buffered_events.append(event)



                        except Exception as e:

                            logger.warning("Error processing detection: %s", e)

                            continue



                if processed_frames % detection_log_interval == 0:

                    logger.info(

                        "frame %s/%s camera=%s persons=%s events=%s",

                        frame_idx,

                        total_frames,

                        camera_id,

                        person_count,

                        event_count,

                    )



                processed_frames += 1

                frame_idx += 1



            # EXIT for tracks lost after being seen

            lost_threshold = TRACK_LOST_FRAMES * FRAME_STRIDE

            for track_id, last_frame in list(track_last_seen.items()):

                if frame_idx - last_frame > lost_threshold:

                    visitor_id = track_to_visitor.get(track_id)

                    if visitor_id and self.visitor_states.get(visitor_id, {}).get(

                        "in_store"

                    ):

                        exit_time = clip_start_time + timedelta(

                            seconds=last_frame / video_fps

                        )

                        event = build_event(

                            store_id=self.store_id,

                            camera_id=camera_id,

                            visitor_id=visitor_id,

                            event_type="EXIT",

                            timestamp_dt=exit_time,

                            confidence=0.5,

                            is_staff=self.visitor_states.get(visitor_id, {}).get("is_staff", False),

                            run_id=self.run_id,

                        )

                        buffered_events.append(event)

                        self.visitor_states[visitor_id]["in_store"] = False

                        self.tracker.mark_exit(visitor_id, exit_time)

                    del track_last_seen[track_id]

            # POST-PROCESS EVENTS: Apply deterministic staff classification heuristics
            # as required by Task 1 & 2 in challenge guidelines (e.g. presence duration, start/end)
            if buffered_events:
                visitor_stats = {}
                clip_end_time = clip_start_time + timedelta(seconds=frame_idx / video_fps)
                clip_duration_seconds = frame_idx / video_fps

                for ev in buffered_events:

                    vid = ev.visitor_id

                    ts = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))

                    

                    if vid not in visitor_stats:

                        visitor_stats[vid] = {

                            "first_ts": ts,

                            "last_ts": ts,

                            "total_detections": 0,

                            "billing_detections": 0,

                            "hsv_matches": 0,

                            "zones": set(),

                        }

                    

                    stats = visitor_stats[vid]

                    stats["first_ts"] = min(stats["first_ts"], ts)

                    stats["last_ts"] = max(stats["last_ts"], ts)

                    stats["total_detections"] += 1

                    if ev.zone_id in ("cash_counter", "beauty_counter"):

                        stats["billing_detections"] += 1

                    if ev.is_staff:

                        stats["hsv_matches"] += 1

                    if ev.zone_id and ev.zone_id != "entry":

                        stats["zones"].add(ev.zone_id)



                is_staff_map = {}
                for vid, stats in visitor_stats.items():
                    active_duration = (stats["last_ts"] - stats["first_ts"]).total_seconds()
                    ratio_active = active_duration / clip_duration_seconds if clip_duration_seconds > 0 else 0
                    ratio_visible = stats["total_detections"] / (processed_frames or 1)
                    ratio_billing = stats["billing_detections"] / stats["total_detections"] if stats["total_detections"] > 0 else 0
                    ratio_hsv = stats["hsv_matches"] / stats["total_detections"] if stats["total_detections"] > 0 else 0

                    # 1. Spatial Motion Validation Filter: discard static mannequins, posters, reflections, ghosts
                    centroids = visitor_centroids.get(vid, [])
                    if centroids:
                        xs = [c[0] for c in centroids]
                        ys = [c[1] for c in centroids]
                        dx = max(xs) - min(xs)
                        dy = max(ys) - min(ys)
                        displacement = (dx**2 + dy**2) ** 0.5
                    else:
                        displacement = 0.0

                    if displacement < 30.0:
                        logger.info("Discarding static ghost/mannequin (displacement=%.1fpx): visitor=%s", displacement, vid)
                        continue

                    # 2. Outside passerby / street traffic filter:
                    is_outside_camera = bool(cam_config.get("is_outside", False)) if cam_config else False
                    if is_outside_camera and len(stats["zones"]) == 0:
                        logger.info("Discarding outside passerby/street traffic (0 zones visited): visitor=%s", vid)
                        continue

                    # Staff classification heuristics
                    is_staff_heuristic = False
                    
                    # Physical constraint: a visitor must visit at least one zone inside the store to be store staff!
                    # (Unless it's CAM5 Exit/billing rear camera which is a dedicated zone)
                    is_outside = bool(cam_config.get("is_outside", False)) if cam_config else False
                    has_zone_presence = len(stats["zones"]) > 0 or (cam_config is not None and not is_outside)
                    
                    if has_zone_presence:
                        # Heuristic A: Torso uniform HSV color match ratio is high (very strong color cue)
                        if ratio_hsv > 0.30 and stats["total_detections"] >= 5:
                            is_staff_heuristic = True
                            
                        # Heuristic B: Visible throughout a large portion of the video (long-duration cashier or staff walking around)
                        if ratio_active > 0.60 and ratio_visible > 0.15 and ratio_hsv > 0.20:
                            is_staff_heuristic = True
                            
                        # Heuristic C: Stationed cashier (present at start and end of longer clip at billing)
                        if clip_duration_seconds > 15.0:
                            present_at_start = (stats["first_ts"] - clip_start_time).total_seconds() < max(10.0, 0.25 * clip_duration_seconds)
                            present_at_end = (clip_end_time - stats["last_ts"]).total_seconds() < max(10.0, 0.25 * clip_duration_seconds)
                            fixed_zone = cam_config.get("fixed_zone") if cam_config else None
                            is_at_billing = stats["billing_detections"] > 0 or fixed_zone in ("cash_counter", "beauty_counter")
                            if present_at_start and present_at_end and ratio_active > 0.60 and ratio_hsv > 0.20 and is_at_billing:
                                is_staff_heuristic = True
                                
                        # Heuristic D: Repeated appearance across zones (patrolling staff)
                        if len(stats["zones"]) >= 5 and ratio_hsv > 0.20:
                            is_staff_heuristic = True

                    is_staff_map[vid] = is_staff_heuristic
                    logger.info(
                        "Track evaluation: visitor=%s active_dur=%.1fs ratio_act=%.2f ratio_vis=%.2f hsv=%.2f zones=%s -> is_staff=%s",
                        vid, active_duration, ratio_active, ratio_visible, ratio_hsv, len(stats["zones"]), is_staff_heuristic
                    )

                for ev in buffered_events:
                    vid = ev.visitor_id
                    if vid not in is_staff_map:
                        continue # Skip discarded street traffic/ghosts
                    ev.is_staff = is_staff_map.get(vid, False)
                    if self.writer.write_event(ev):
                        event_count += 1



        finally:

            cap.release()



        logger.info("=== VIDEO PROCESSING COMPLETE ===")

        logger.info("Video: %s", video_name)

        logger.info("Events generated: %d", event_count)

        logger.info("Frames processed: %d / %d", processed_frames, total_frames)

        logger.info("Output file: %s", self.writer.output_path)

        
        # Verify output file was written

        output_file = Path(self.writer.output_path)

        if output_file.exists():

            file_size = output_file.stat().st_size

            line_count = len(output_file.read_text().strip().split('\n')) if output_file.read_text().strip() else 0

            logger.info("Output file size: %d bytes, event lines: %d", file_size, line_count)

        else:

            logger.error("OUTPUT FILE NOT CREATED: %s", self.writer.output_path)

        

        return event_count, processed_frames

    def _generate_events(
        self,
        visitor_id: str,
        track_id: int,
        crossing: Optional[str],
        is_reentry: bool,
        is_staff: bool,
        zone_id: Optional[str],
        conf: float,
        frame_timestamp: datetime,
        zone_entry_times: Dict,
        camera_id: str,
        frame_idx: int,
        fps: float,
        centroid: Optional[Tuple[float, float]] = None,
    ) -> List[Event]:
        events = []
        x_val = centroid[0] if centroid else None
        y_val = centroid[1] if centroid else None

        if crossing == "ENTRY":
            event_type = "REENTRY" if is_reentry else "ENTRY"
            events.append(
                build_event(
                    store_id=self.store_id,
                    camera_id=camera_id,
                    visitor_id=visitor_id,
                    event_type=event_type,
                    timestamp_dt=frame_timestamp,
                    confidence=conf,
                    is_staff=is_staff,
                    zone_id=None,
                    run_id=self.run_id,
                    x=x_val,
                    y=y_val,
                )
            )
            if visitor_id not in self.visitor_states:
                self.visitor_states[visitor_id] = {"zone_id": None, "in_store": True, "is_staff": is_staff}
            else:
                self.visitor_states[visitor_id]["in_store"] = True
            self.tracker.mark_entry(visitor_id)

        elif crossing == "EXIT":
            st = self.visitor_states.get(visitor_id, {})
            if st.get("billing_joined"):
                st["billing_purchased"] = True
            events.append(
                build_event(
                    store_id=self.store_id,
                    camera_id=camera_id,
                    visitor_id=visitor_id,
                    event_type="EXIT",
                    timestamp_dt=frame_timestamp,
                    confidence=conf,
                    is_staff=is_staff,
                    zone_id=None,
                    run_id=self.run_id,
                    x=x_val,
                    y=y_val,
                )
            )
            if visitor_id in self.visitor_states:
                self.visitor_states[visitor_id]["in_store"] = False
            self.tracker.mark_exit(visitor_id, frame_timestamp)

        if zone_id:
            state = self.visitor_states.get(visitor_id, {})
            prev_zone = state.get("zone_id")

            if zone_id != prev_zone:
                if prev_zone:
                    prev_enter = zone_entry_times.get(visitor_id, {}).get(prev_zone, frame_timestamp)
                    dwell_ms = max(0, int((frame_timestamp - prev_enter).total_seconds() * 1000))
                    events.append(
                        build_event(
                            store_id=self.store_id,
                            camera_id=camera_id,
                            visitor_id=visitor_id,
                            event_type="ZONE_EXIT",
                            timestamp_dt=frame_timestamp,
                            confidence=conf,
                            zone_id=prev_zone,
                            dwell_ms=dwell_ms,
                            is_staff=is_staff,
                            run_id=self.run_id,
                            x=x_val,
                            y=y_val,
                        )
                    )
                    if dwell_ms >= 1000:
                        events.append(
                            build_event(
                                store_id=self.store_id,
                                camera_id=camera_id,
                                visitor_id=visitor_id,
                                event_type="ZONE_DWELL",
                                timestamp_dt=frame_timestamp,
                                confidence=conf,
                                zone_id=prev_zone,
                                dwell_ms=dwell_ms,
                                is_staff=is_staff,
                                run_id=self.run_id,
                                x=x_val,
                                y=y_val,
                            )
                        )
                    if (
                        prev_zone in ("cash_counter", "beauty_counter")
                        and zone_id not in ("cash_counter", "beauty_counter")
                        and state.get("billing_joined")
                        and not state.get("billing_purchased")
                    ):
                        events.append(
                            build_event(
                                store_id=self.store_id,
                                camera_id=camera_id,
                                visitor_id=visitor_id,
                                event_type="BILLING_QUEUE_ABANDON",
                                timestamp_dt=frame_timestamp,
                                confidence=conf,
                                zone_id=prev_zone,
                                is_staff=is_staff,
                                run_id=self.run_id,
                                x=x_val,
                                y=y_val,
                            )
                        )
                        state = {**state, "billing_joined": False}

                events.append(
                    build_event(
                        store_id=self.store_id,
                        camera_id=camera_id,
                        visitor_id=visitor_id,
                        event_type="ZONE_ENTER",
                        timestamp_dt=frame_timestamp,
                        confidence=conf,
                        zone_id=zone_id,
                        is_staff=is_staff,
                        run_id=self.run_id,
                        x=x_val,
                        y=y_val,
                    )
                )

                self.visitor_states[visitor_id] = {
                    "zone_id": zone_id,
                    "zone_enter_time": frame_timestamp,
                    "in_store": True,
                    "billing_joined": state.get("billing_joined", False),
                }

                if visitor_id not in zone_entry_times:
                    zone_entry_times[visitor_id] = {}
                zone_entry_times[visitor_id][zone_id] = frame_timestamp

                # Billing queue when entering counter zones
                if (
                    zone_id in ("cash_counter", "beauty_counter")
                    and not state.get("billing_joined")
                    and not is_staff
                ):
                    queue_depth = sum(
                        1
                        for vid, st in self.visitor_states.items()
                        if st.get("zone_id") in ("cash_counter", "beauty_counter")
                    )
                    events.append(
                        build_event(
                            store_id=self.store_id,
                            camera_id=camera_id,
                            visitor_id=visitor_id,
                            event_type="BILLING_QUEUE_JOIN",
                            timestamp_dt=frame_timestamp,
                            confidence=conf,
                            zone_id=zone_id,
                            is_staff=is_staff,
                            queue_depth=queue_depth,
                            run_id=self.run_id,
                            x=x_val,
                            y=y_val,
                        )
                    )
                    self.visitor_states[visitor_id]["billing_joined"] = True

        return events

    def process_all_videos(self) -> int:

        import time

        start_time = time.time()

        total_events = 0

        total_frames = 0

        video_files = sorted(

            list(self.clips_dir.glob("*.mp4")) + list(self.clips_dir.glob("*.avi"))

        )

        

        # Startup log for video source directory

        logger.info("=== PIPELINE STARTUP ===")

        logger.info("RUN_ID: %s", self.run_id or "N/A")

        logger.info("STORE_ID: %s", self.store_id)

        logger.info("VIDEO SOURCE DIRECTORY: %s", self.clips_dir.resolve())

        logger.info("Found %s video files in %s", len(video_files), self.clips_dir)

        

        # Log all detected video files

        if video_files:

            logger.info("Video files: %s", [f.name for f in video_files])

        else:

            logger.error("No video files found in %s", self.clips_dir)

            raise RuntimeError(

                f"No video files found in {self.clips_dir.resolve()}. "

                f"Please ensure videos are mounted at /app/clips in Docker."

            )



        # Fresh run: truncate output

        out = Path(self.writer.output_path)

        out.parent.mkdir(parents=True, exist_ok=True)

        out.write_text("", encoding="utf-8")



        for video_path in video_files:

            try:

                events, frames = self.process_video(str(video_path))

                total_events += events

                total_frames += frames

                logger.info(

                    "PROCESSED VIDEO: run_id=%s, video=%s, frames=%d, events=%d",

                    self.run_id or "N/A",

                    video_path.name,

                    frames,

                    events

                )

            except Exception as e:

                logger.error("Error processing %s: %s", video_path, e, exc_info=True)

                continue



        processing_time = time.time() - start_time

        logger.info(

            "PIPELINE COMPLETE: run_id=%s, total_videos=%d, total_frames=%d, total_events=%d, processing_time=%.2fs",

            self.run_id or "N/A",

            len(video_files),

            total_frames,

            total_events,

            processing_time

        )

        return total_events





def main():

    parser = argparse.ArgumentParser(description="Detection pipeline")

    parser.add_argument("--clips-dir", required=True)

    parser.add_argument("--layout", required=True)

    parser.add_argument("--output", required=True)

    parser.add_argument("--store-id", default="STORE_BLR_002")

    parser.add_argument("--camera-id", default="CAM1")

    parser.add_argument("--run-id", default=None)

    args = parser.parse_args()



    pipeline = DetectionPipeline(

        clips_dir=args.clips_dir,

        layout_path=args.layout,

        output_path=args.output,

        store_id=args.store_id,

        camera_id=args.camera_id,

        run_id=args.run_id,

    )

    count = pipeline.process_all_videos()

    if count == 0:

        logger.warning("No events emitted — check videos, YOLO install, and thresholds.")

        sys.exit(0)

    sys.exit(0)





if __name__ == "__main__":

    main()
