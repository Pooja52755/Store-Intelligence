"""Re-ID tracker using OSNet embeddings for re-entry detection."""
import numpy as np
from typing import Dict, Tuple, Optional
from datetime import datetime, timedelta
import hashlib


class ReIDTracker:
    """
    Re-ID tracking using appearance embeddings.
    
    Handles:
    - Generating visitor_id from appearance
    - Matching new detections to existing visitors
    - Detecting re-entries (same person after EXIT)
    - Cross-camera deduplication via embeddings
    """

    def __init__(self, similarity_threshold: float = 0.85, buffer_window_minutes: int = 10):
        """
        Initialize Re-ID tracker.
        
        Args:
            similarity_threshold: Cosine similarity threshold for matching
                                 (>= this value = same visitor)
            buffer_window_minutes: Keep embeddings for this long after last seen
        """
        self.similarity_threshold = similarity_threshold
        self.buffer_window_minutes = buffer_window_minutes
        
        # Track visitors: visitor_id → (embedding, last_seen_timestamp, session_active)
        self.visitor_buffer: Dict[str, Tuple[np.ndarray, datetime, bool]] = {}
        
        # Map track_id (YOLOv8) to visitor_id
        self.track_to_visitor: Dict[int, str] = {}
        
        # Counter for generating visitor IDs
        self.visitor_counter = 0
        
        # Keep track of visitor IDs assigned at the current timestamp to enforce physical exclusion
        self.last_timestamp = None
        self.assigned_at_timestamp = set()

    def match_or_create(
        self,
        embedding: np.ndarray,
        track_id: int,
        current_timestamp: datetime
    ) -> Tuple[str, bool]:
        """
        Match embedding to existing visitor or create new one.
        
        Args:
            embedding: Appearance embedding (typically 128-dim from OSNet)
            track_id: YOLOv8 track ID
            current_timestamp: Current frame timestamp
        
        Returns:
            (visitor_id, is_reentry) tuple
                visitor_id: Unique visitor identifier (e.g., "VIS_c8a2f1")
                is_reentry: True if visitor re-entered after prior EXIT
        """
        # Reset same-frame exclusion set if timestamp changes
        if current_timestamp != self.last_timestamp:
            self.assigned_at_timestamp = set()
            self.last_timestamp = current_timestamp

        # If this track_id already mapped, return known visitor
        if track_id in self.track_to_visitor:
            visitor_id = self.track_to_visitor[track_id]
            
            # Update embedding and timestamp
            if visitor_id in self.visitor_buffer:
                old_embedding, old_timestamp, was_active = self.visitor_buffer[visitor_id]
                self.visitor_buffer[visitor_id] = (embedding, current_timestamp, True)
            
            self.assigned_at_timestamp.add(visitor_id)
            return visitor_id, False
        
        # Clean up stale entries
        self._cleanup_buffer(current_timestamp)
        
        # Try to match against existing visitors
        best_visitor_id = None
        best_similarity = 0
        best_was_inactive = False
        
        for visitor_id, (stored_embedding, stored_timestamp, was_active) in self.visitor_buffer.items():
            # Physical constraint: a single visitor cannot have multiple active tracks in the same frame
            if visitor_id in self.assigned_at_timestamp:
                continue
                
            similarity = self._cosine_similarity(embedding, stored_embedding)
            
            if similarity >= self.similarity_threshold and similarity > best_similarity:
                best_similarity = similarity
                best_visitor_id = visitor_id
                best_was_inactive = not was_active  # is_reentry if was inactive
        
        if best_visitor_id:
            # Found matching visitor - suppress reflections/duplicates if similarity is extremely high
            self.track_to_visitor[track_id] = best_visitor_id
            self.visitor_buffer[best_visitor_id] = (embedding, current_timestamp, True)
            self.assigned_at_timestamp.add(best_visitor_id)
            
            is_reentry = best_was_inactive
            return best_visitor_id, is_reentry
        
        # Mirror/Reflection suppression: Check if another active person is physically adjacent or geometrically symmetric
        # If so, suppress the reflection detection completely and map to the closest parent track visitor_id
        # (This is implemented by finding the most similar active visitor even if slightly below threshold)
        for visitor_id, (stored_embedding, stored_timestamp, was_active) in self.visitor_buffer.items():
            if visitor_id in self.assigned_at_timestamp:
                continue
            similarity = self._cosine_similarity(embedding, stored_embedding)
            if similarity >= (self.similarity_threshold - 0.1) and was_active:
                # Highly likely a mirror reflection or duplicate double-detection - suppress
                self.track_to_visitor[track_id] = visitor_id
                self.assigned_at_timestamp.add(visitor_id)
                return visitor_id, False
        
        # No match - create new visitor
        visitor_id = self._generate_visitor_id(embedding)
        self.track_to_visitor[track_id] = visitor_id
        self.visitor_buffer[visitor_id] = (embedding, current_timestamp, True)
        self.assigned_at_timestamp.add(visitor_id)
        
        return visitor_id, False

    def mark_exit(self, visitor_id: str, current_timestamp: datetime):
        """
        Mark visitor as having exited (session closed).
        
        Keep embedding in buffer for re-entry detection.
        
        Args:
            visitor_id: Visitor identifier
            current_timestamp: Current timestamp
        """
        if visitor_id in self.visitor_buffer:
            embedding, _, _ = self.visitor_buffer[visitor_id]
            self.visitor_buffer[visitor_id] = (embedding, current_timestamp, False)

    def mark_entry(self, visitor_id: str):
        """
        Mark visitor as active (in store).
        
        Args:
            visitor_id: Visitor identifier
        """
        if visitor_id in self.visitor_buffer:
            embedding, timestamp, _ = self.visitor_buffer[visitor_id]
            self.visitor_buffer[visitor_id] = (embedding, timestamp, True)

    def _cleanup_buffer(self, current_timestamp: datetime):
        """Remove stale entries from buffer."""
        cutoff_time = current_timestamp - timedelta(minutes=self.buffer_window_minutes)
        expired_visitors = []
        
        for visitor_id, (_, last_seen, _) in self.visitor_buffer.items():
            if last_seen < cutoff_time:
                expired_visitors.append(visitor_id)
        
        for visitor_id in expired_visitors:
            del self.visitor_buffer[visitor_id]
            # Also clean up track mappings
            tracks_to_remove = [
                tid for tid, vid in self.track_to_visitor.items()
                if vid == visitor_id
            ]
            for tid in tracks_to_remove:
                del self.track_to_visitor[tid]

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """
        Compute cosine similarity between two vectors.
        
        Args:
            a: Vector 1
            b: Vector 2
        
        Returns:
            Cosine similarity (0-1)
        """
        a = np.array(a, dtype=np.float32)
        b = np.array(b, dtype=np.float32)
        
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _generate_visitor_id(self, embedding: np.ndarray) -> str:
        """
        Generate unique visitor_id from embedding.
        
        Args:
            embedding: Appearance embedding
        
        Returns:
            Visitor ID string (e.g., "VIS_c8a2f1")
        """
        # Use first 6 chars of embedding hash
        embedding_bytes = np.array(embedding, dtype=np.float32).tobytes()
        hash_hex = hashlib.md5(embedding_bytes).hexdigest()[:6]
        
        return f"VIS_{hash_hex}"

    def get_visitor_embedding(self, visitor_id: str) -> Optional[np.ndarray]:
        """Get stored embedding for a visitor."""
        if visitor_id in self.visitor_buffer:
            embedding, _, _ = self.visitor_buffer[visitor_id]
            return embedding
        return None


class MockOSNetEmbedder:
    """
    Mock OSNet embedder for testing without torchreid dependency.
    
    In production, replace with actual torchreid model:
    ```python
    from torchreid.utils import FeatureExtractor
    extractor = FeatureExtractor(
        model_name='osnet_x0_25',
        device='cuda'
    )
    ```
    """

    def __init__(self, embedding_dim: int = 128):
        """Initialize mock embedder."""
        self.embedding_dim = embedding_dim

    def extract(self, crop: np.ndarray) -> np.ndarray:
        """
        Extract appearance embedding from image crop.
        
        Args:
            crop: BGR image crop (should be ~64x128 for best results)
        
        Returns:
            128-dimensional appearance embedding (normalized)
        """
        # Mock: use color histogram as embedding
        # In production, use actual OSNet forward pass
        
        crop_hsv = np.mean(crop, axis=(0, 1))  # Average color
        
        # Deterministic padding from crop pixels (no random — stable Re-ID per appearance)
        flat = crop.astype(np.float32).flatten()
        if len(flat) < self.embedding_dim - 6:
            pad = np.resize(flat, self.embedding_dim - 6)
        else:
            step = max(1, len(flat) // (self.embedding_dim - 6))
            pad = flat[::step][: self.embedding_dim - 6]

        embedding = np.concatenate([
            crop_hsv,
            [crop.shape[0], crop.shape[1], float(crop.mean())],
            pad,
        ])[: self.embedding_dim]
        
        # Normalize
        embedding = embedding / (np.linalg.norm(embedding) + 1e-8)
        
        return embedding.astype(np.float32)
