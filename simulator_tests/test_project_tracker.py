#!/usr/bin/env python3
"""
Project Tracker Tool Test

Tests the project_tracker tool for cross-session context handoffs, including:
- Capture mode: Save project state with decisions, blockers, next steps
- Retrieve mode: Get project context with continuation_id
- Status mode: Quick project overview
- File persistence: Optional durable storage
"""

from pathlib import Path

from .base_test import BaseSimulatorTest


class ProjectTrackerTest(BaseSimulatorTest):
    """Test project tracker tool for baton pass context handoffs"""

    @property
    def test_name(self) -> str:
        return "project_tracker_baton_pass"

    @property
    def test_description(self) -> str:
        return "Project tracker baton pass context handoff workflow"

    def cleanup_project_files(self):
        """Clean up any test project files created during testing"""
        projects_dir = Path.home() / ".pal" / "projects"
        if projects_dir.exists():
            # Clean up all test project files (they use UUID names)
            for project_file in projects_dir.glob("*.json"):
                try:
                    project_file.unlink()
                    self.logger.debug(f"Cleaned up test project file: {project_file}")
                except OSError as e:
                    self.logger.warning(f"Failed to clean up project file {project_file}: {e}")

    def run_test(self) -> bool:
        """Test project tracker baton pass workflow"""
        try:
            self.logger.info("Test: Project Tracker Baton Pass Workflow")

            # ========================================
            # Step 1: Capture project state
            # ========================================
            self.logger.info("  1.1: Capture project state")
            response1, continuation_id = self.call_mcp_tool(
                "project_tracker",
                {
                    "mode": "capture",
                    "project_name": "test-dark-mode-feature",
                    "context": "Implementing dark mode using CSS variables for theming",
                    "decisions": [
                        "Use CSS variables for theming",
                        "Toggle in settings page",
                        "Support system preference detection",
                    ],
                    "blockers": ["Need design for toggle icon", "Color palette not finalized"],
                    "next_steps": [
                        "Create theme context provider",
                        "Add toggle component",
                        "Define color palette",
                        "Test with prefers-color-scheme",
                    ],
                    "focus_areas": ["Accessibility", "Performance"],
                    "persist": True,  # Use file persistence for cross-process simulator test
                },
            )

            if not response1:
                self.logger.error("Failed to capture project state")
                return False

            if not continuation_id:
                self.logger.error("Capture mode did not return continuation_id")
                return False

            # Verify capture response contains expected content
            if "Project Captured" not in response1:
                self.logger.error(f"Unexpected capture response: {response1[:200]}")
                return False

            self.logger.info(f"  ✅ Project captured with ID: {continuation_id[:8]}...")

            # ========================================
            # Step 2: Retrieve project state
            # ========================================
            self.logger.info("  1.2: Retrieve project state with continuation_id")
            response2, _ = self.call_mcp_tool(
                "project_tracker",
                {
                    "mode": "retrieve",
                    "continuation_id": continuation_id,
                },
            )

            if not response2:
                self.logger.error("Failed to retrieve project state")
                return False

            # Verify retrieve response contains captured content
            if "Context Restored" not in response2:
                self.logger.error(f"Unexpected retrieve response: {response2[:200]}")
                return False

            # Verify key decisions are in response
            if "CSS variables" not in response2:
                self.logger.error("Retrieved context missing key decision 'CSS variables'")
                return False

            if "toggle icon" not in response2.lower():
                self.logger.error("Retrieved context missing blocker 'toggle icon'")
                return False

            self.logger.info("  ✅ Project context retrieved successfully")

            # ========================================
            # Step 3: Check project status
            # ========================================
            self.logger.info("  1.3: Check project status")
            response3, _ = self.call_mcp_tool(
                "project_tracker",
                {
                    "mode": "status",
                    "continuation_id": continuation_id,
                },
            )

            if not response3:
                self.logger.error("Failed to get project status")
                return False

            # Verify status response contains expected summary
            if "Status" not in response3 and "dark-mode" not in response3.lower():
                self.logger.error(f"Unexpected status response: {response3[:200]}")
                return False

            self.logger.info("  ✅ Project status retrieved successfully")

            # ========================================
            # Step 4: Retrieve by project name
            # ========================================
            self.logger.info("  1.4: Retrieve by project name")
            response4, _ = self.call_mcp_tool(
                "project_tracker",
                {
                    "mode": "retrieve",
                    "project_name": "test-dark-mode-feature",
                },
            )

            if not response4:
                self.logger.error("Failed to retrieve by project name")
                return False

            if "Context Restored" not in response4:
                self.logger.error(f"Name-based retrieve failed: {response4[:200]}")
                return False

            self.logger.info("  ✅ Project retrieved by name successfully")

            # ========================================
            # Step 5: Test persistence mode
            # ========================================
            self.logger.info("  1.5: Test file persistence mode")
            response5, persist_id = self.call_mcp_tool(
                "project_tracker",
                {
                    "mode": "capture",
                    "project_name": "test-persistent-project",
                    "context": "A test project with file persistence",
                    "decisions": ["Decision A"],
                    "next_steps": ["Next step 1"],
                    "persist": True,  # Enable file persistence
                },
            )

            if not response5:
                self.logger.error("Failed to capture with persistence")
                return False

            # Check if file was created
            projects_dir = Path.home() / ".pal" / "projects"
            # Project files use sanitized project_id, so we check if any file was created recently
            if projects_dir.exists():
                project_files = list(projects_dir.glob("*.json"))
                if project_files:
                    self.logger.info(f"  ✅ Persistent project saved to: {project_files[-1].name}")
                else:
                    self.logger.warning("  ⚠️ Persistence enabled but no project file found")
            else:
                self.logger.warning("  ⚠️ Projects directory not created")

            self.logger.info("  ✅ Project tracker baton pass workflow complete")
            return True

        except Exception as e:
            self.logger.error(f"Project tracker test failed: {e}")
            import traceback

            traceback.print_exc()
            return False
        finally:
            self.cleanup_project_files()
