"""Tripwire logic for entry/exit detection."""
import json
from typing import Dict, Tuple, Optional
from collections import deque


class TripwireDetector:
    """Detects ENTRY/EXIT events using virtual tripwire line crossing."""

    def __init__(self, tripwire_line: Dict[str, int], store_layout_path: Optional[str] = None):
        """
        Initialize tripwire detector.
        
        Args:
            tripwire_line: Dict with {'x1': int, 'y1': int, 'x2': int, 'y2': int}
                          representing line coordinates in frame
            store_layout_path: Optional path to store_layout.json for loading from config
        """
        self.tripwire_line = tripwire_line
        
        # Track last 3 centroid positions per track_id for 3-frame confirmation
        self.centroid_history: Dict[int, deque] = {}
        self.max_history = 3
        
        # Track if visitor has crossed (to avoid repeated ENTRY/EXIT on jitter)
        self.has_crossed: Dict[int, bool] = {}
        
        # Entry direction vectors
        self.entry_direction = self._get_entry_direction()

    def _get_entry_direction(self) -> Tuple[float, float]:
        """Get normalized direction vector of tripwire line."""
        x1 = self.tripwire_line['x1']
        y1 = self.tripwire_line['y1']
        x2 = self.tripwire_line['x2']
        y2 = self.tripwire_line['y2']
        
        dx = x2 - x1
        dy = y2 - y1
        length = (dx**2 + dy**2) ** 0.5
        
        if length == 0:
            return (0, 1)
        
        return (dx / length, dy / length)

    def _point_to_line_side(self, point: Tuple[float, float]) -> float:
        """
        Determine which side of line a point is on.
        
        Uses cross product: positive = one side, negative = other side
        Returns:
            Signed distance (positive/negative indicates side)
        """
        px, py = point
        x1 = self.tripwire_line['x1']
        y1 = self.tripwire_line['y1']
        x2 = self.tripwire_line['x2']
        y2 = self.tripwire_line['y2']
        
        # Cross product
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        return cross

    def check_crossing(self, track_id: int, centroid: Tuple[float, float]) -> Optional[str]:
        """
        Check if track has crossed tripwire.
        
        Uses 3-frame confirmation to avoid noise.
        
        Args:
            track_id: YOLOv8 track ID
            centroid: (x, y) centroid in frame
        
        Returns:
            "ENTRY" if crossed from outside→inside
            "EXIT" if crossed from inside→outside
            None if no crossing or insufficient history
        """
        # Initialize history for new track
        if track_id not in self.centroid_history:
            self.centroid_history[track_id] = deque(maxlen=self.max_history)
            self.has_crossed[track_id] = False
        
        # Add new centroid
        self.centroid_history[track_id].append(centroid)
        
        # Need at least 3 frames for confirmation
        if len(self.centroid_history[track_id]) < 3:
            return None
        
        # Get last 3 positions
        positions = list(self.centroid_history[track_id])
        
        # Calculate which side of line each position is on
        sides = [self._point_to_line_side(p) for p in positions]
        
        # Check for crossing: sign change across 3 frames
        if sides[0] * sides[2] < 0:  # Different signs = crossed
            
            # Determine direction based on first vs last position
            if sides[0] < 0 < sides[2]:
                # Crossed from negative to positive side
                crossing_type = "EXIT"
            else:
                # Crossed from positive to negative side
                crossing_type = "ENTRY"
            
            # Avoid repeated events on jitter - only emit if not recently crossed
            if not self.has_crossed[track_id]:
                self.has_crossed[track_id] = True
                return crossing_type
        
        # Reset crossing flag if back to consistent side
        if sides[0] * sides[2] > 0:  # Same sign = not crossing
            self.has_crossed[track_id] = False
        
        return None

    def reset_track(self, track_id: int):
        """Reset tracking state for a track (e.g., after EXIT)."""
        if track_id in self.centroid_history:
            del self.centroid_history[track_id]
        if track_id in self.has_crossed:
            del self.has_crossed[track_id]

    @staticmethod
    def load_from_layout(store_layout_path: str) -> "TripwireDetector":
        """Load tripwire coordinates from store_layout.json."""
        with open(store_layout_path, 'r') as f:
            layout = json.load(f)
        
        tripwire_line = layout.get('tripwire_line', {
            'x1': 0,
            'y1': 540,  # Mid-frame horizontally for 1080p
            'x2': 1920,
            'y2': 540
        })
        
        return TripwireDetector(tripwire_line, store_layout_path)
