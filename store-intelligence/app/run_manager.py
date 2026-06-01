"""Run management for pipeline execution tracking."""
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pathlib import Path
import logging
import json

logger = logging.getLogger(__name__)


class RunManager:
    """Manage pipeline runs with unique run_ids and isolated storage."""
    
    def __init__(self, base_events_dir: str = "./events"):
        """
        Initialize run manager.
        
        Args:
            base_events_dir: Base directory for event storage
        """
        self.base_events_dir = Path(base_events_dir)
        self.base_events_dir.mkdir(parents=True, exist_ok=True)
        
    def create_run(self, store_id: str) -> str:
        """
        Create a new run with unique run_id.
        
        Args:
            store_id: Store identifier
            
        Returns:
            run_id: Unique run identifier (UUID)
        """
        run_id = str(uuid.uuid4())
        run_dir = self.base_events_dir / store_id / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        # Create run metadata
        metadata = {
            "run_id": run_id,
            "store_id": store_id,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "PENDING",
            "videos_processed": [],
            "total_events": 0,
            "total_frames": 0,
            "processing_time_seconds": 0.0
        }
        
        metadata_file = run_dir / "run_metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2))
        
        logger.info("Created new run: run_id=%s, store_id=%s, path=%s", run_id, store_id, run_dir)
        return run_id
    
    def get_run_dir(self, store_id: str, run_id: str) -> Path:
        """
        Get run directory for a specific run.
        
        Args:
            store_id: Store identifier
            run_id: Run identifier
            
        Returns:
            Path to run directory
        """
        return self.base_events_dir / store_id / run_id
    
    def get_events_file(self, store_id: str, run_id: str) -> Path:
        """
        Get events.jsonl file path for a specific run.
        
        Args:
            store_id: Store identifier
            run_id: Run identifier
            
        Returns:
            Path to events.jsonl file
        """
        return self.get_run_dir(store_id, run_id) / "events.jsonl"
    
    def update_run_metadata(self, store_id: str, run_id: str, updates: Dict[str, Any]):
        """
        Update run metadata.
        
        Args:
            store_id: Store identifier
            run_id: Run identifier
            updates: Dictionary of fields to update
        """
        metadata_file = self.get_run_dir(store_id, run_id) / "run_metadata.json"
        
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            metadata.update(updates)
            metadata_file.write_text(json.dumps(metadata, indent=2))
            logger.info("Updated run metadata: run_id=%s, updates=%s", run_id, updates)
    
    def get_latest_run(self, store_id: str) -> Optional[str]:
        """
        Get the most recent run_id for a store.
        
        Args:
            store_id: Store identifier
            
        Returns:
            Latest run_id or None if no runs exist
        """
        store_dir = self.base_events_dir / store_id
        if not store_dir.exists():
            return None
        
        run_dirs = [d for d in store_dir.iterdir() if d.is_dir()]
        if not run_dirs:
            return None
        
        # Sort by creation time (from metadata)
        latest_run = None
        latest_time = None
        
        for run_dir in run_dirs:
            metadata_file = run_dir / "run_metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                    created_at = datetime.fromisoformat(metadata["created_at"].replace("Z", "+00:00"))
                    if latest_time is None or created_at > latest_time:
                        latest_time = created_at
                        latest_run = run_dir.name
                except Exception as e:
                    logger.warning("Failed to read metadata for %s: %s", run_dir, e)
        
        return latest_run
    
    def get_run_metadata(self, store_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        """
        Get run metadata.
        
        Args:
            store_id: Store identifier
            run_id: Run identifier
            
        Returns:
            Run metadata dictionary or None
        """
        metadata_file = self.get_run_dir(store_id, run_id) / "run_metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                return json.load(f)
        return None
    
    def list_runs(self, store_id: str) -> list:
        """
        List all runs for a store.
        
        Args:
            store_id: Store identifier
            
        Returns:
            List of run metadata dictionaries
        """
        store_dir = self.base_events_dir / store_id
        if not store_dir.exists():
            return []
        
        runs = []
        for run_dir in sorted(store_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            metadata = self.get_run_metadata(store_id, run_dir.name)
            if metadata:
                runs.append(metadata)
        
        return runs


# Global instance
run_manager = RunManager()
