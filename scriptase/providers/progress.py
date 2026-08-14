"""Progress Writer — Phase 3.

Provides status.json writing functionality for provider jobs.
Writes normalized progress data to output directories.
"""

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from scriptase.shared.io_utils import safe_json_write


class ProgressWriter:
    """Thread-safe progress writer for job status.
    
    Writes status.json files to output directories with normalized structure.
    """
    
    def __init__(self, output_dir: str, job_id: str | None = None):
        self.output_dir = output_dir
        self.job_id = job_id or "default"
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {
            "job_id": self.job_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "progress": 0.0,
            "message": None,
            "scenes": {},
        }
    
    def _save(self) -> None:
        """Save current state to status.json."""
        os.makedirs(self.output_dir, exist_ok=True)
        status_path = os.path.join(self.output_dir, "status.json")
        safe_json_write(status_path, self._data, indent=2)
    
    def _update(self, **kwargs) -> None:
        """Update and save status atomically."""
        with self._lock:
            self._data.update(kwargs)
            self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
    
    def set_status(
        self,
        status: str,
        progress: float | None = None,
        message: str | None = None,
    ) -> None:
        """Set overall job status.
        
        Args:
            status: Status string (pending, running, completed, failed, cancelled)
            progress: Optional progress 0.0-1.0
            message: Optional status message
        """
        kwargs = {"status": status}
        if progress is not None:
            kwargs["progress"] = max(0.0, min(1.0, progress))
        if message is not None:
            kwargs["message"] = message
        self._update(**kwargs)
    
    def set_scene_status(
        self,
        scene_index: int,
        status: str,
        progress: float | None = None,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Set status for a specific scene.
        
        Args:
            scene_index: Scene index
            status: Scene status
            progress: Optional progress 0.0-1.0
            result: Optional result data
            error: Optional error message
        """
        with self._lock:
            if "scenes" not in self._data:
                self._data["scenes"] = {}
            if scene_index not in self._data["scenes"]:
                self._data["scenes"][scene_index] = {}
            
            scene_data = self._data["scenes"][scene_index]
            scene_data["status"] = status
            if progress is not None:
                scene_data["progress"] = max(0.0, min(1.0, progress))
            if result is not None:
                scene_data["result"] = result
            if error is not None:
                scene_data["error"] = error
            
            self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
    
    def complete(self, result: dict | None = None, message: str = "Completed") -> None:
        """Mark job as completed.
        
        Args:
            result: Optional final result data
            message: Completion message
        """
        kwargs = {"status": "completed", "progress": 1.0, "message": message}
        if result is not None:
            kwargs["result"] = result
        self._update(**kwargs)
    
    def fail(self, error: str, message: str | None = None) -> None:
        """Mark job as failed.
        
        Args:
            error: Error message
            message: Optional user-friendly message
        """
        self._update(
            status="failed",
            message=message or "Failed",
            error=error,
        )
    
    def get_data(self) -> dict:
        """Get current status data."""
        with self._lock:
            return dict(self._data)


def write_status_json(output_dir: str, data: dict) -> None:
    """Simple function to write status.json to an output directory.
    
    Args:
        output_dir: Directory to write status.json
        data: Status data dict
    """
    os.makedirs(output_dir, exist_ok=True)
    status_path = os.path.join(output_dir, "status.json")
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    safe_json_write(status_path, data, indent=2)
