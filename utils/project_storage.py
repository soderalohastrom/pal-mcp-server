"""
Project storage backend for PROJECT TRACKER tool

Provides both in-memory (ephemeral) and file-based (persistent) storage
for project context across Claude sessions.

Storage Options:
- In-memory: Uses existing InMemoryStorage with 3-hour TTL (default)
- File-based: Persists to ~/.pal/projects/{project_name}.json (optional)
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ProjectContext(BaseModel):
    """
    Structured project context for cross-session handoffs.

    Captures the essential state needed to resume work in a fresh session.
    """

    project_id: str = Field(..., description="UUID for the project context")
    project_name: str = Field(..., description="Human-readable project identifier")
    summary: str = Field(default="", description="Brief project summary")
    context: str = Field(default="", description="Full project context/description")
    decisions: list[str] = Field(default_factory=list, description="Key decisions made")
    blockers: list[str] = Field(default_factory=list, description="Current blockers")
    next_steps: list[str] = Field(default_factory=list, description="Pending work items")
    focus_areas: list[str] = Field(default_factory=list, description="Priority focus areas")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class ProjectStorage:
    """
    Thread-safe project storage with optional file persistence.

    Provides two storage modes:
    1. In-memory (default): Uses InMemoryStorage, expires after 3 hours
    2. File-based (persist=True): Saves to ~/.pal/projects/{project_name}.json

    Usage:
        storage = get_project_storage()
        storage.save(project_context, persist=True)
        retrieved = storage.get(project_id)
    """

    def __init__(self):
        self._memory_store: dict[str, ProjectContext] = {}
        self._lock = threading.Lock()
        self._projects_dir = Path.home() / ".pal" / "projects"
        self._ensure_projects_dir()

    def _ensure_projects_dir(self) -> None:
        """Create projects directory if it doesn't exist."""
        try:
            self._projects_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Projects directory: {self._projects_dir}")
        except OSError as e:
            logger.warning(f"Failed to create projects directory: {e}")

    def save(self, project: ProjectContext, persist: bool = False) -> str:
        """
        Save project context.

        Args:
            project: The project context to save
            persist: If True, also save to file for cross-session durability

        Returns:
            The project_id for later retrieval
        """
        project.updated_at = datetime.utcnow().isoformat()

        # Always save to memory
        with self._lock:
            self._memory_store[project.project_id] = project
            logger.debug(f"Saved project {project.project_name} (id={project.project_id}) to memory")

        # Optionally persist to file
        if persist:
            self._save_to_file(project)

        return project.project_id

    def get(self, project_id: str) -> Optional[ProjectContext]:
        """
        Retrieve project context by ID.

        First checks in-memory storage, then falls back to file storage.

        Args:
            project_id: The UUID of the project to retrieve

        Returns:
            ProjectContext if found, None otherwise
        """
        # Try memory first
        with self._lock:
            if project_id in self._memory_store:
                logger.debug(f"Retrieved project {project_id} from memory")
                return self._memory_store[project_id]

        # Fall back to file storage
        project = self._load_from_file(project_id)
        if project:
            # Cache in memory for faster subsequent access
            with self._lock:
                self._memory_store[project_id] = project
            logger.debug(f"Retrieved project {project_id} from file")
        return project

    def get_by_name(self, project_name: str) -> Optional[ProjectContext]:
        """
        Retrieve project context by name.

        Searches memory first, then file storage.

        Args:
            project_name: The human-readable project name

        Returns:
            ProjectContext if found, None otherwise
        """
        # Try memory first
        with self._lock:
            for project in self._memory_store.values():
                if project.project_name == project_name:
                    logger.debug(f"Retrieved project {project_name} from memory")
                    return project

        # Fall back to file storage
        return self._load_from_file_by_name(project_name)

    def list_projects(self) -> list[dict[str, str]]:
        """
        List all available projects (memory + files).

        Returns:
            List of dicts with project_id, project_name, updated_at
        """
        projects = {}

        # Get from memory
        with self._lock:
            for pid, project in self._memory_store.items():
                projects[pid] = {
                    "project_id": pid,
                    "project_name": project.project_name,
                    "updated_at": project.updated_at,
                    "source": "memory",
                }

        # Get from files (don't override memory entries)
        if self._projects_dir.exists():
            for file_path in self._projects_dir.glob("*.json"):
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    pid = data.get("project_id")
                    if pid and pid not in projects:
                        projects[pid] = {
                            "project_id": pid,
                            "project_name": data.get("project_name", "Unknown"),
                            "updated_at": data.get("updated_at", "Unknown"),
                            "source": "file",
                        }
                except Exception as e:
                    logger.warning(f"Failed to read project file {file_path}: {e}")

        return list(projects.values())

    def delete(self, project_id: str, delete_file: bool = True) -> bool:
        """
        Delete project context.

        Args:
            project_id: The UUID of the project to delete
            delete_file: If True, also delete the file if it exists

        Returns:
            True if project was deleted, False if not found
        """
        deleted = False

        # Remove from memory
        with self._lock:
            if project_id in self._memory_store:
                del self._memory_store[project_id]
                deleted = True
                logger.debug(f"Deleted project {project_id} from memory")

        # Remove from file storage
        if delete_file:
            file_path = self._get_file_path(project_id)
            if file_path.exists():
                try:
                    file_path.unlink()
                    deleted = True
                    logger.debug(f"Deleted project file {file_path}")
                except OSError as e:
                    logger.warning(f"Failed to delete project file {file_path}: {e}")

        return deleted

    def _save_to_file(self, project: ProjectContext) -> None:
        """Save project to file storage."""
        try:
            file_path = self._get_file_path(project.project_id)
            file_path.write_text(project.model_dump_json(indent=2), encoding="utf-8")
            logger.info(f"Persisted project {project.project_name} to {file_path}")
        except Exception as e:
            logger.error(f"Failed to persist project {project.project_name}: {e}")

    def _load_from_file(self, project_id: str) -> Optional[ProjectContext]:
        """Load project from file storage by ID."""
        file_path = self._get_file_path(project_id)
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                return ProjectContext(**data)
            except Exception as e:
                logger.warning(f"Failed to load project {project_id}: {e}")
        return None

    def _load_from_file_by_name(self, project_name: str) -> Optional[ProjectContext]:
        """Load project from file storage by name."""
        if not self._projects_dir.exists():
            return None

        # Scan all project files for matching name
        for file_path in self._projects_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                if data.get("project_name") == project_name:
                    return ProjectContext(**data)
            except Exception as e:
                logger.warning(f"Failed to read project file {file_path}: {e}")
        return None

    def _get_file_path(self, project_id: str) -> Path:
        """Get file path for a project ID."""
        # Sanitize project_id for filesystem
        safe_id = "".join(c for c in project_id if c.isalnum() or c == "-")
        return self._projects_dir / f"{safe_id}.json"


# Global singleton instance
_project_storage_instance: Optional[ProjectStorage] = None
_project_storage_lock = threading.Lock()


def get_project_storage() -> ProjectStorage:
    """Get the global project storage instance (singleton pattern)."""
    global _project_storage_instance
    if _project_storage_instance is None:
        with _project_storage_lock:
            if _project_storage_instance is None:
                _project_storage_instance = ProjectStorage()
                logger.info("Initialized project storage")
    return _project_storage_instance
