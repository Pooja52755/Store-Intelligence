"""HSV histogram-based staff uniform detection."""
import cv2
import numpy as np
from typing import Tuple, Dict, Optional


class StaffClassifier:
    """Detect staff by HSV color histogram of torso region."""

    # Staff uniform color signatures: list of (h_center, s_center, v_center, tolerance)
    # Typical retail uniforms: dark blues, blacks, dark greens
    STAFF_COLOR_SIGNATURES = [
        # (H, S, V, tolerance)
        (100, 200, 50, 30),   # Dark blue
        (0, 100, 50, 20),      # Dark gray/black
        (80, 150, 60, 25),     # Navy
        (60, 180, 70, 30),     # Green
    ]

    def __init__(self, threshold: float = 0.35):
        """
        Initialize staff classifier.
        
        Args:
            threshold: Histogram distance threshold for staff classification.
                      If distance < threshold → is_staff=True
                      Tuned via experimentation (see CHOICES.md)
        """
        self.threshold = threshold

    def classify(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> bool:
        """
        Classify person in bounding box as staff or customer.
        
        Args:
            frame: BGR image frame from OpenCV
            bbox: (x1, y1, x2, y2) bounding box coordinates
        
        Returns:
            True if detected as staff, False otherwise
        """
        try:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            
            # Ensure valid bbox
            if x1 >= x2 or y1 >= y2 or x1 < 0 or y1 < 0:
                return False
            
            # Crop bounding box
            crop = frame[y1:y2, x1:x2]
            
            if crop.size == 0:
                return False
            
            # Extract chest/shirt region (25% to 65% of bounding box height, avoids black hair and pants)
            height = crop.shape[0]
            y_start = int(height * 0.25)
            y_end = int(height * 0.65)
            torso_crop = crop[y_start:y_end, :]
            
            if torso_crop.size == 0:
                return False
            
            # Convert to HSV
            hsv_crop = cv2.cvtColor(torso_crop, cv2.COLOR_BGR2HSV)
            
            # Compute histogram
            hist = cv2.calcHist(
                [hsv_crop],
                [0, 1, 2],  # H, S, V channels
                None,
                [8, 8, 8],  # 8 bins per channel
                [0, 180, 0, 256, 0, 256]
            )
            hist = cv2.normalize(hist, hist).flatten()
            
            # Direct check for black/dark uniform (very low saturation and brightness in torso)
            mean_s = np.mean(hsv_crop[:, :, 1])
            mean_v = np.mean(hsv_crop[:, :, 2])
            if mean_v < 68.0 and mean_s < 75.0:
                return True

            # Compare against staff signatures
            min_distance = float('inf')
            
            for h_center, s_center, v_center, tolerance in self.STAFF_COLOR_SIGNATURES:
                # Create signature histogram (simple gaussian-like)
                signature_hist = self._create_signature_histogram(h_center, s_center, v_center)
                
                # Chi-square distance
                distance = cv2.compareHist(hist, signature_hist, cv2.HISTCMP_CHISQR)
                min_distance = min(min_distance, distance)
            
            # Return True if within threshold
            return min_distance < self.threshold
            
        except Exception as e:
            print(f"Error in staff classification: {e}")
            return False

    def _create_signature_histogram(self, h: int, s: int, v: int) -> np.ndarray:
        """
        Create a simple histogram signature for a color.
        
        Args:
            h: Hue (0-180 in OpenCV HSV)
            s: Saturation (0-255)
            v: Value (0-255)
        
        Returns:
            512-element histogram (8x8x8)
        """
        hist = np.zeros(512, dtype=np.float32)
        
        # Create gaussian-like distribution around the color
        h_bin = int((h / 180) * 8)
        s_bin = int((s / 256) * 8)
        v_bin = int((v / 256) * 8)
        
        h_bin = max(0, min(7, h_bin))
        s_bin = max(0, min(7, s_bin))
        v_bin = max(0, min(7, v_bin))
        
        # Weight center bin and neighbors
        center_idx = h_bin * 64 + s_bin * 8 + v_bin
        hist[center_idx] = 1.0
        
        # Add some weight to neighbors
        for dh in [-1, 0, 1]:
            for ds in [-1, 0, 1]:
                for dv in [-1, 0, 1]:
                    nh = max(0, min(7, h_bin + dh))
                    ns = max(0, min(7, s_bin + ds))
                    nv = max(0, min(7, v_bin + dv))
                    neighbor_idx = nh * 64 + ns * 8 + nv
                    hist[neighbor_idx] += 0.1
        
        hist = cv2.normalize(hist, hist)
        return hist


def create_staff_classifier(config_path: Optional[str] = None) -> StaffClassifier:
    """
    Factory function to create staff classifier.
    
    Args:
        config_path: Optional path to config with threshold and color signatures
    
    Returns:
        StaffClassifier instance
    """
    classifier = StaffClassifier(threshold=0.35)
    
    # Could load custom signatures from config here
    if config_path:
        import json
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                classifier.threshold = config.get('threshold', 0.35)
        except Exception as e:
            print(f"Could not load config: {e}")
    
    return classifier