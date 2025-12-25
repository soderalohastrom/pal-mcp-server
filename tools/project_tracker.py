"""
Project Tracker tool - Cross-session context capture and retrieval

This tool enables "baton pass" handoffs between Claude sessions by capturing,
storing, and retrieving structured project context. It supports both
ephemeral (in-memory) and persistent (file-based) storage.

Modes:
- capture: Save current project state with decisions, blockers, next steps
- retrieve: Get project context to prime a fresh session
- status: Quick overview of tracked project state
"""

import logging
import uuid
from typing import TYPE_CHECKING, Any, Literal, Optional

from pydantic import Field

if TYPE_CHECKING:
    from tools.models import ToolModelCategory

from config import TEMPERATURE_BALANCED
from systemprompts import PROJECT_TRACKER_PROMPT
from tools.models import ContinuationOffer, ToolOutput
from tools.shared.base_models import COMMON_FIELD_DESCRIPTIONS, ToolRequest
from utils.project_storage import ProjectContext, get_project_storage

from .simple.base import SimpleTool

logger = logging.getLogger(__name__)


# Field descriptions for Project Tracker
PROJECT_TRACKER_FIELD_DESCRIPTIONS = {
    "mode": (
        "Operation mode: 'capture' to save project state, "
        "'retrieve' to get context for a fresh session, "
        "'status' for quick project overview."
    ),
    "project_name": (
        "Human-readable project identifier. Required for capture mode. "
        "For retrieve/status, can use this OR continuation_id."
    ),
    "context": "Full project context/description to capture (for capture mode).",
    "decisions": "List of key decisions made during the session.",
    "blockers": "List of current blockers or challenges.",
    "next_steps": "List of pending work items and next actions.",
    "focus_areas": "List of priority focus areas.",
    "persist": (
        "If True, save to file (~/.pal/projects/) for cross-session durability. "
        "Default False uses in-memory storage with 3-hour TTL."
    ),
}


class ProjectTrackerRequest(ToolRequest):
    """Request model for Project Tracker tool"""

    mode: Literal["capture", "retrieve", "status"] = Field(..., description=PROJECT_TRACKER_FIELD_DESCRIPTIONS["mode"])
    project_name: Optional[str] = Field(None, description=PROJECT_TRACKER_FIELD_DESCRIPTIONS["project_name"])
    context: Optional[str] = Field(None, description=PROJECT_TRACKER_FIELD_DESCRIPTIONS["context"])
    decisions: Optional[list[str]] = Field(
        default_factory=list, description=PROJECT_TRACKER_FIELD_DESCRIPTIONS["decisions"]
    )
    blockers: Optional[list[str]] = Field(
        default_factory=list, description=PROJECT_TRACKER_FIELD_DESCRIPTIONS["blockers"]
    )
    next_steps: Optional[list[str]] = Field(
        default_factory=list, description=PROJECT_TRACKER_FIELD_DESCRIPTIONS["next_steps"]
    )
    focus_areas: Optional[list[str]] = Field(
        default_factory=list, description=PROJECT_TRACKER_FIELD_DESCRIPTIONS["focus_areas"]
    )
    persist: Optional[bool] = Field(False, description=PROJECT_TRACKER_FIELD_DESCRIPTIONS["persist"])


class ProjectTrackerTool(SimpleTool):
    """
    Project context capture and retrieval tool for cross-session handoffs.

    This tool enables "baton pass" workflows where context is captured
    before closing a Claude session and retrieved in a fresh session.

    Modes:
    - capture: Save structured project state (decisions, blockers, next steps)
    - retrieve: Get project context to prime a new session
    - status: Quick overview of current project state
    """

    def get_name(self) -> str:
        return "project_tracker"

    def get_description(self) -> str:
        return (
            "Capture, store, and retrieve project context for cross-session handoffs. "
            "Use 'capture' mode before closing a session to save state, "
            "'retrieve' mode in a fresh session to restore context, "
            "or 'status' for a quick project overview."
        )

    def get_annotations(self) -> Optional[dict[str, Any]]:
        """Project tracker may write files when persist=True."""
        return {"readOnlyHint": False}

    def get_system_prompt(self) -> str:
        return PROJECT_TRACKER_PROMPT

    def get_default_temperature(self) -> float:
        return TEMPERATURE_BALANCED

    def get_model_category(self) -> "ToolModelCategory":
        """Project tracker prioritizes fast responses and cost efficiency"""
        from tools.models import ToolModelCategory

        return ToolModelCategory.FAST_RESPONSE

    def requires_model(self) -> bool:
        """
        Project tracker doesn't require model resolution at the MCP boundary.

        This tool does pure data processing (capture/retrieve/status) without
        calling external AI models.
        """
        return False

    def get_request_model(self):
        """Return the Project Tracker-specific request model"""
        return ProjectTrackerRequest

    def get_input_schema(self) -> dict[str, Any]:
        """Generate input schema for the tool."""
        required_fields = ["mode"]
        if self.is_effective_auto_mode():
            required_fields.append("model")

        schema = {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["capture", "retrieve", "status"],
                    "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["mode"],
                },
                "project_name": {
                    "type": "string",
                    "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["project_name"],
                },
                "context": {
                    "type": "string",
                    "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["context"],
                },
                "decisions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["decisions"],
                },
                "blockers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["blockers"],
                },
                "next_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["next_steps"],
                },
                "focus_areas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["focus_areas"],
                },
                "persist": {
                    "type": "boolean",
                    "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["persist"],
                },
                "model": self.get_model_field_schema(),
                "temperature": {
                    "type": "number",
                    "description": COMMON_FIELD_DESCRIPTIONS["temperature"],
                    "minimum": 0,
                    "maximum": 1,
                },
                "thinking_mode": {
                    "type": "string",
                    "enum": ["minimal", "low", "medium", "high", "max"],
                    "description": COMMON_FIELD_DESCRIPTIONS["thinking_mode"],
                },
                "continuation_id": {
                    "type": "string",
                    "description": COMMON_FIELD_DESCRIPTIONS["continuation_id"],
                },
            },
            "required": required_fields,
            "additionalProperties": False,
        }

        return schema

    def get_tool_fields(self) -> dict[str, dict[str, Any]]:
        """Tool-specific field definitions."""
        return {
            "mode": {
                "type": "string",
                "enum": ["capture", "retrieve", "status"],
                "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["mode"],
            },
            "project_name": {
                "type": "string",
                "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["project_name"],
            },
            "context": {
                "type": "string",
                "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["context"],
            },
            "decisions": {
                "type": "array",
                "items": {"type": "string"},
                "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["decisions"],
            },
            "blockers": {
                "type": "array",
                "items": {"type": "string"},
                "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["blockers"],
            },
            "next_steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["next_steps"],
            },
            "focus_areas": {
                "type": "array",
                "items": {"type": "string"},
                "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["focus_areas"],
            },
            "persist": {
                "type": "boolean",
                "description": PROJECT_TRACKER_FIELD_DESCRIPTIONS["persist"],
            },
        }

    def get_required_fields(self) -> list[str]:
        """Required fields for Project Tracker tool"""
        return ["mode"]

    async def prepare_prompt(self, request: ProjectTrackerRequest) -> str:
        """
        Prepare prompt for AI model.

        Note: ProjectTrackerTool doesn't use the AI model for its core operations.
        This method is required by the SimpleTool base class but won't be called
        since execute() is overridden to handle operations directly.
        """
        return f"Project tracker operation: {request.mode}"

    async def execute(self, arguments: dict[str, Any]) -> list:
        """
        Execute the project tracker operation.

        Handles capture, retrieve, and status modes directly without
        AI model calls for efficiency.

        Returns list of TextContent for MCP protocol compatibility.
        """
        from mcp.types import TextContent

        try:
            # Validate and parse request
            request = ProjectTrackerRequest(**arguments)
            storage = get_project_storage()

            if request.mode == "capture":
                tool_output = self._handle_capture(request, storage)
            elif request.mode == "retrieve":
                tool_output = self._handle_retrieve(request, storage)
            elif request.mode == "status":
                tool_output = self._handle_status(request, storage)
            else:
                tool_output = ToolOutput(
                    status="error",
                    content=f"Unknown mode: {request.mode}. Valid modes: capture, retrieve, status",
                    content_type="text",
                )

            # Convert ToolOutput to MCP-compatible response
            return [TextContent(type="text", text=tool_output.model_dump_json())]

        except Exception as e:
            logger.error(f"Project tracker error: {e}", exc_info=True)
            error_output = ToolOutput(
                status="error",
                content=f"Project tracker error: {str(e)}",
                content_type="text",
            )
            return [TextContent(type="text", text=error_output.model_dump_json())]

    def _handle_capture(self, request: ProjectTrackerRequest, storage) -> ToolOutput:
        """Handle capture mode - save project context."""
        if not request.project_name:
            return ToolOutput(
                status="error",
                content="project_name is required for capture mode",
                content_type="text",
            )

        # Generate project ID (use continuation_id if provided, else new UUID)
        project_id = request.continuation_id or str(uuid.uuid4())

        # Create project context
        project = ProjectContext(
            project_id=project_id,
            project_name=request.project_name,
            context=request.context or "",
            decisions=request.decisions or [],
            blockers=request.blockers or [],
            next_steps=request.next_steps or [],
            focus_areas=request.focus_areas or [],
        )

        # Save with optional persistence
        storage.save(project, persist=request.persist or False)

        # Build response
        persistence_note = ""
        if request.persist:
            persistence_note = "\n\n*Persisted to ~/.pal/projects/ for cross-session durability.*"

        content = f"""## Project Captured: {request.project_name}

**Project ID**: `{project_id}`
**Captured At**: {project.created_at}

### Summary
- **Decisions**: {len(project.decisions)} recorded
- **Blockers**: {len(project.blockers)} identified
- **Next Steps**: {len(project.next_steps)} planned
- **Focus Areas**: {len(project.focus_areas)} prioritized
{persistence_note}

---

Use this continuation_id to retrieve context in a fresh session:
```
continuation_id: {project_id}
```"""

        return ToolOutput(
            status="continuation_available",
            content=content,
            content_type="markdown",
            metadata={
                "project_id": project_id,
                "project_name": request.project_name,
                "captured_at": project.created_at,
                "persisted": request.persist or False,
            },
            continuation_offer=ContinuationOffer(
                continuation_id=project_id,
                note="Use this ID to retrieve project context in a new session",
                remaining_turns=50,
            ),
        )

    def _handle_retrieve(self, request: ProjectTrackerRequest, storage) -> ToolOutput:
        """Handle retrieve mode - get project context."""
        project = None

        # Try to find project by continuation_id first
        if request.continuation_id:
            project = storage.get(request.continuation_id)

        # Fall back to project_name
        if not project and request.project_name:
            project = storage.get_by_name(request.project_name)

        if not project:
            # List available projects
            projects = storage.list_projects()
            if projects:
                project_list = "\n".join(
                    f"- **{p['project_name']}** (id: `{p['project_id'][:8]}...`, updated: {p['updated_at']})"
                    for p in projects[:10]
                )
                content = f"""## No Project Found

Could not find project with the provided continuation_id or project_name.

### Available Projects:
{project_list}

Provide a valid `continuation_id` or `project_name` to retrieve context."""
            else:
                content = """## No Projects Found

No projects have been captured yet. Use `mode: "capture"` to save project context first."""

            return ToolOutput(
                status="error",
                content=content,
                content_type="markdown",
            )

        # Format project context for retrieval
        decisions_list = (
            "\n".join(f"- {d}" for d in project.decisions) if project.decisions else "*No decisions recorded*"
        )
        blockers_list = (
            "\n".join(f"- {b}" for b in project.blockers) if project.blockers else "*No blockers identified*"
        )
        next_steps_list = (
            "\n".join(f"{i+1}. {s}" for i, s in enumerate(project.next_steps))
            if project.next_steps
            else "*No next steps defined*"
        )
        focus_list = "\n".join(f"- {f}" for f in project.focus_areas) if project.focus_areas else "*No focus areas set*"

        content = f"""## Context Restored: {project.project_name}

*This context was captured on {project.created_at} to enable cross-session continuity.*

### Project Summary
{project.context if project.context else "*No summary provided*"}

### Key Decisions
{decisions_list}

### Current Blockers
{blockers_list}

### Next Steps
{next_steps_list}

### Focus Areas
{focus_list}

---

**Ready to continue.** What would you like to work on?"""

        return ToolOutput(
            status="continuation_available",
            content=content,
            content_type="markdown",
            metadata={
                "project_id": project.project_id,
                "project_name": project.project_name,
                "last_updated": project.updated_at,
            },
            continuation_offer=ContinuationOffer(
                continuation_id=project.project_id,
                note="Continue using this project context",
                remaining_turns=50,
            ),
        )

    def _handle_status(self, request: ProjectTrackerRequest, storage) -> ToolOutput:
        """Handle status mode - quick project overview."""
        project = None

        # Try to find project
        if request.continuation_id:
            project = storage.get(request.continuation_id)
        if not project and request.project_name:
            project = storage.get_by_name(request.project_name)

        if not project:
            # List all projects
            projects = storage.list_projects()
            if projects:
                project_list = "\n".join(
                    f"| {p['project_name']} | `{p['project_id'][:8]}...` | {p['updated_at'][:10]} | {p['source']} |"
                    for p in projects[:10]
                )
                content = f"""## Project Tracker Status

| Project | ID | Updated | Source |
|---------|-----|---------|--------|
{project_list}

*Showing up to 10 most recent projects*"""
            else:
                content = "## Project Tracker Status\n\nNo projects tracked yet."

            return ToolOutput(
                status="success",
                content=content,
                content_type="markdown",
            )

        # Quick status for specific project
        blocker_text = f"{len(project.blockers)} blockers" if project.blockers else "No blockers"
        next_up = project.next_steps[0] if project.next_steps else "No next steps defined"

        content = f"""## {project.project_name} Status

**Summary**: {project.context[:100] + '...' if project.context and len(project.context) > 100 else project.context or 'No summary'}
**Blockers**: {blocker_text}
**Next Up**: {next_up}
**Updated**: {project.updated_at}"""

        return ToolOutput(
            status="success",
            content=content,
            content_type="markdown",
            metadata={
                "project_id": project.project_id,
                "project_name": project.project_name,
            },
        )
