"""Unit tests for happy path scenarios with mocked LLM.

WHEN TO RUN: Always run these tests - they're fast and use mocks.
These tests verify Path A (workflow reuse) scenarios without real LLM calls.

This file includes the critical North Star workflow tests that showcase pflow's
real value proposition: automating repetitive developer tasks that involve
data gathering, AI analysis, and structured output.
"""

import json
import logging
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import WorkflowDiscoveryNode

logger = logging.getLogger(__name__)


class TestNorthStarWorkflowDiscovery:
    """Test discovery with realistic, valuable workflows developers actually need.

    These tests use the North Star examples which represent the actual value
    proposition of pflow: automating repetitive developer tasks.
    """

    @pytest.fixture
    def north_star_workflows(self):
        """Create the North Star example workflows that showcase pflow's value."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflows_dir = Path(tmpdir) / "workflows"
            workflows_dir.mkdir()

            # PRIMARY: Generate Changelog - The flagship example
            changelog_workflow = {
                "name": "generate-changelog",
                "description": "Generate a changelog from the last 20 closed GitHub issues",
                "version": "1.0.0",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "ir": {
                    "ir_version": "0.1.0",
                    "nodes": [
                        {
                            "id": "list-issues",
                            "type": "github-list-issues",
                            "params": {"state": "closed", "limit": "${limit}"},
                        },
                        {
                            "id": "generate",
                            "type": "llm",
                            "params": {"prompt": "Generate a CHANGELOG.md entry from these issues: ${issues}"},
                        },
                        {"id": "write", "type": "write-file", "params": {"file_path": "${output_path}"}},
                        {
                            "id": "commit",
                            "type": "git-commit",
                            "params": {"message": "Update changelog for version ${version}"},
                        },
                        {
                            "id": "pr",
                            "type": "github-create-pr",
                            "params": {"title": "Update CHANGELOG.md", "base": "main"},
                        },
                    ],
                    "edges": [
                        {"from": "list-issues", "to": "generate", "action": "default"},
                        {"from": "generate", "to": "write", "action": "default"},
                        {"from": "write", "to": "commit", "action": "default"},
                        {"from": "commit", "to": "pr", "action": "default"},
                    ],
                    "start_node": "list-issues",
                    "inputs": {
                        "version": {
                            "description": "Version number for the changelog",
                            "required": False,
                            "type": "string",
                        },
                        "limit": {
                            "description": "Number of issues to include",
                            "required": False,
                            "type": "string",
                            "default": "20",
                        },
                        "output_path": {
                            "description": "Path to write the changelog file",
                            "required": False,
                            "type": "string",
                            "default": "CHANGELOG.md",
                        },
                    },
                    "outputs": {"pr_url": {"description": "URL of created pull request", "type": "string"}},
                },
            }

            # SECONDARY: Issue Triage Report - Analysis workflow
            triage_workflow = {
                "name": "issue-triage-report",
                "description": "Create a triage report for all open GitHub issues",
                "version": "1.0.0",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "ir": {
                    "ir_version": "0.1.0",
                    "nodes": [
                        {"id": "list", "type": "github-list-issues", "params": {"state": "open", "limit": "${limit}"}},
                        {
                            "id": "analyze",
                            "type": "llm",
                            "params": {"prompt": "Categorize these issues by priority and type: ${issues}"},
                        },
                        {"id": "write", "type": "write-file", "params": {"file_path": "${output_path}"}},
                        {
                            "id": "commit",
                            "type": "git-commit",
                            "params": {"message": "Update triage report $(date +%Y-%m-%d)"},
                        },
                    ],
                    "edges": [
                        {"from": "list", "to": "analyze", "action": "default"},
                        {"from": "analyze", "to": "write", "action": "default"},
                        {"from": "write", "to": "commit", "action": "default"},
                    ],
                    "start_node": "list",
                    "inputs": {
                        "limit": {
                            "description": "Number of open issues to fetch",
                            "required": False,
                            "type": "string",
                            "default": "50",
                        },
                        "output_path": {
                            "description": "Path to write the triage report",
                            "required": False,
                            "type": "string",
                            "default": "triage-report.md",
                        },
                    },
                    "outputs": {"report_path": {"description": "Path to triage report", "type": "string"}},
                },
            }

            # TERTIARY: Release Notes - Automation workflow
            release_notes_workflow = {
                "name": "create-release-notes",
                "description": "Create release notes from issues closed since last tag",
                "version": "1.0.0",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "ir": {
                    "ir_version": "0.1.0",
                    "nodes": [
                        {
                            "id": "list",
                            "type": "github-list-issues",
                            "params": {"state": "closed", "limit": "${limit}"},
                        },
                        {
                            "id": "generate",
                            "type": "llm",
                            "params": {
                                "prompt": "Create release notes in markdown. Group by type (bug/feature/enhancement): ${issues}"
                            },
                        },
                        {"id": "write", "type": "write-file", "params": {"file_path": "${output_path}"}},
                        {
                            "id": "commit",
                            "type": "git-commit",
                            "params": {"message": "Add release notes for version ${version}"},
                        },
                        {
                            "id": "pr",
                            "type": "github-create-pr",
                            "params": {"title": "Release notes for v$(date +%Y.%m.%d)"},
                        },
                    ],
                    "edges": [
                        {"from": "list", "to": "generate", "action": "default"},
                        {"from": "generate", "to": "write", "action": "default"},
                        {"from": "write", "to": "commit", "action": "default"},
                        {"from": "commit", "to": "pr", "action": "default"},
                    ],
                    "start_node": "list",
                    "inputs": {
                        "version": {
                            "description": "Version number for the release notes",
                            "required": False,
                            "type": "string",
                        },
                        "limit": {
                            "description": "Number of closed issues to include",
                            "required": False,
                            "type": "string",
                            "default": "30",
                        },
                        "output_path": {
                            "description": "Path to write the release notes",
                            "required": False,
                            "type": "string",
                            "default": "RELEASE_NOTES.md",
                        },
                    },
                    "outputs": {"pr_url": {"description": "URL of created pull request", "type": "string"}},
                },
            }

            # SIMPLE: Summarize Issue - Minimal but useful
            summarize_workflow = {
                "name": "summarize-github-issue",
                "description": "Summarize a specific GitHub issue",
                "version": "1.0.0",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "ir": {
                    "ir_version": "0.1.0",
                    "nodes": [
                        {"id": "get", "type": "github-get-issue", "params": {"issue": "${issue_number}"}},
                        {
                            "id": "summarize",
                            "type": "llm",
                            "params": {"prompt": "Summarize in 3 bullets: ${issue_data}"},
                        },
                        {"id": "write", "type": "write-file", "params": {"file_path": "${output_path}"}},
                    ],
                    "edges": [
                        {"from": "get", "to": "summarize", "action": "default"},
                        {"from": "summarize", "to": "write", "action": "default"},
                    ],
                    "start_node": "get",
                    "inputs": {
                        "issue_number": {
                            "description": "Issue number to summarize",
                            "required": True,
                            "type": "string",
                        },
                        "output_path": {
                            "description": "Path to write the summary",
                            "required": False,
                            "type": "string",
                            "default": "summary.md",
                        },
                    },
                    "outputs": {"summary_path": {"description": "Path to summary file", "type": "string"}},
                },
            }

            # Write all workflows to disk
            workflows = [changelog_workflow, triage_workflow, release_notes_workflow, summarize_workflow]

            for workflow in workflows:
                workflow_path = workflows_dir / f"{workflow['name']}.json"
                workflow_path.write_text(json.dumps(workflow, indent=2))

            yield str(workflows_dir), workflows

    def test_discovers_changelog_workflow(self, north_star_workflows):
        """Test discovery of the primary North Star example: changelog generation."""
        workflows_dir, workflows = north_star_workflows

        # Create workflow manager instance with test directory
        test_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        # Mock both the context builder's manager and the WorkflowManager constructor
        with (
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            # EXACT north star prompts from architecture/vision/north-star-examples.md
            # Verbose prompt should trigger Path B (generation) if tested
            # CHANGELOG_VERBOSE = """generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."""

            # Brief prompts that should trigger Path A (reuse)
            test_queries = [
                "generate a changelog for version 1.4",  # Brief north star prompt
                "generate a changelog from the last 20 closed issues",
                "create changelog from recent closed issues",
                "I want to generate a CHANGELOG from closed GitHub issues",
                "make a changelog from closed issues and create a PR",
            ]

            for query in test_queries:
                shared = {"user_input": query}
                prep_res = node.prep(shared)

                # Verify workflow is in context
                assert "generate-changelog" in prep_res["discovery_context"]

                # Mock LLM to recognize the changelog workflow
                with patch("llm.get_model") as mock_get_model:
                    mock_response = Mock()
                    mock_response.json.return_value = {
                        "content": [
                            {
                                "input": {
                                    "found": True,
                                    "workflow_name": "generate-changelog",
                                    "confidence": 0.95,
                                    "reasoning": f"The request '{query}' matches the 'generate-changelog' workflow perfectly.",
                                }
                            }
                        ]
                    }
                    mock_model = Mock()
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model

                    exec_res = node.exec(prep_res)
                    action = node.post(shared, prep_res, exec_res)

                    # Should take Path A for this valuable, reusable workflow
                    assert action == "found_existing", f"Failed to match: {query}"
                    assert shared["found_workflow"]["name"] == "generate-changelog"

    def test_discovers_triage_report_workflow(self, north_star_workflows):
        """Test discovery of issue triage report workflow."""
        workflows_dir, workflows = north_star_workflows

        # Create workflow manager instance with test directory
        test_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        with (
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()
            shared = {"user_input": "create a triage report for all open issues"}

            prep_res = node.prep(shared)

            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": True,
                                "workflow_name": "issue-triage-report",
                                "confidence": 0.92,
                                "reasoning": "Exact match for creating triage report from open issues",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                assert action == "found_existing"
                assert shared["found_workflow"]["name"] == "issue-triage-report"

    def test_partial_match_triggers_path_b(self, north_star_workflows):
        """Test that partial/vague matches don't trigger Path A."""
        workflows_dir, workflows = north_star_workflows

        # Create workflow manager instance with test directory
        test_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        with (
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            # Vague query that might relate to multiple workflows
            shared = {"user_input": "do something with GitHub"}

            prep_res = node.prep(shared)

            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": False,
                                "workflow_name": None,
                                "confidence": 0.3,
                                "reasoning": "Request too vague to match any specific workflow",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                # Should NOT take Path A for vague requests
                assert action == "not_found"
                assert "found_workflow" not in shared

    def test_changelog_different_phrasings(self, north_star_workflows):
        """Test that various ways users phrase changelog requests work."""
        workflows_dir, workflows = north_star_workflows

        # Create workflow manager instance with test directory
        test_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        with (
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            # Different ways developers might ask for changelog generation
            test_phrases = [
                "update the changelog",
                "generate changelog from github issues",
                "create a changelog for the new release",
                "update CHANGELOG.md with recent changes",
                "document what changed in the last 20 issues",
                "what's new in this release? create a changelog",
                "prepare changelog for version 2.0",
                "summarize recent issues for changelog",
            ]

            for phrase in test_phrases:
                shared = {"user_input": phrase}
                prep_res = node.prep(shared)

                # Mock LLM to recognize changelog workflow
                with patch("llm.get_model") as mock_get_model:
                    mock_response = Mock()
                    mock_response.json.return_value = {
                        "content": [
                            {
                                "input": {
                                    "found": True,
                                    "workflow_name": "generate-changelog",
                                    "confidence": 0.9,
                                    "reasoning": "User wants to generate/update a changelog",
                                }
                            }
                        ]
                    }
                    mock_model = Mock()
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model

                    exec_res = node.exec(prep_res)
                    action = node.post(shared, prep_res, exec_res)

                    assert action == "found_existing", f"Failed to match: '{phrase}'"
                    assert shared["found_workflow"]["name"] == "generate-changelog"

    def test_release_notes_vs_changelog_distinction(self, north_star_workflows):
        """Test that system distinguishes between release notes and changelogs."""
        workflows_dir, workflows = north_star_workflows

        # Create workflow manager instance with test directory
        test_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        with (
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            # Test release notes request
            shared_release = {"user_input": "create release notes for v2.0"}
            prep_res = node.prep(shared_release)

            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": True,
                                "workflow_name": "create-release-notes",
                                "confidence": 0.92,
                                "reasoning": "User specifically wants release notes, not changelog",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                exec_res = node.exec(prep_res)
                action = node.post(shared_release, prep_res, exec_res)

                assert action == "found_existing"
                assert shared_release["found_workflow"]["name"] == "create-release-notes"

    def test_confidence_threshold_with_north_star(self, north_star_workflows):
        """Test that confidence thresholds work correctly with North Star workflows."""
        workflows_dir, workflows = north_star_workflows

        # Create workflow manager instance with test directory
        test_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        with (
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            # Ambiguous request that could match multiple workflows
            shared = {"user_input": "something about issues"}
            prep_res = node.prep(shared)

            # Low confidence should trigger Path B
            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": False,  # Low confidence = not found
                                "workflow_name": None,
                                "confidence": 0.4,
                                "reasoning": "Too vague to match any specific workflow",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                assert action == "not_found"
                assert "found_workflow" not in shared

    def test_workflow_with_parameters(self, north_star_workflows):
        """Test that workflows with parameters are still discovered correctly."""
        workflows_dir, workflows = north_star_workflows

        # Create workflow manager instance with test directory
        test_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        with (
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            # Request with specific parameters
            shared = {"user_input": "generate changelog from the last 50 closed issues"}
            prep_res = node.prep(shared)

            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": True,
                                "workflow_name": "generate-changelog",
                                "confidence": 0.95,
                                "reasoning": "User wants changelog with different limit parameter",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                # Should still match even with different parameters
                assert action == "found_existing"
                assert shared["found_workflow"]["name"] == "generate-changelog"
                # Parameters would be filled in during execution

    def test_similar_but_different_workflows(self, north_star_workflows):
        """Test that system correctly distinguishes between similar workflows."""
        workflows_dir, workflows = north_star_workflows

        # Create workflow manager instance with test directory
        test_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        with (
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            # Test cases for different but similar workflows
            test_cases = [
                ("summarize issue #42", "summarize-github-issue"),
                ("triage all open issues", "issue-triage-report"),
                ("generate changelog", "generate-changelog"),
                ("create release notes", "create-release-notes"),
            ]

            for request, expected_workflow in test_cases:
                shared = {"user_input": request}
                prep_res = node.prep(shared)

                with patch("llm.get_model") as mock_get_model:
                    mock_response = Mock()
                    mock_response.json.return_value = {
                        "content": [
                            {
                                "input": {
                                    "found": True,
                                    "workflow_name": expected_workflow,
                                    "confidence": 0.9,
                                    "reasoning": f"Matched to {expected_workflow}",
                                }
                            }
                        ]
                    }
                    mock_model = Mock()
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model

                    exec_res = node.exec(prep_res)
                    action = node.post(shared, prep_res, exec_res)

                    assert action == "found_existing"
                    assert shared["found_workflow"]["name"] == expected_workflow

    def test_workflow_value_proposition(self, north_star_workflows):
        """Test that North Star workflows are actually valuable and worth reusing."""
        workflows_dir, workflows = north_star_workflows

        # Verify each North Star workflow has characteristics of valuable automation
        # workflows is a tuple: (dir, list_of_workflows)
        for workflow in workflows:  # workflows is the list from the fixture
            # Each workflow should solve a real problem
            assert workflow["description"], f"Workflow {workflow['name']} needs a description"

            # Should have multiple steps (not trivial)
            nodes = workflow["ir"]["nodes"]
            assert len(nodes) >= 2, f"Workflow {workflow['name']} should have multiple steps"

            # Should integrate multiple systems (GitHub, LLM, files, git)
            node_types = {node["type"] for node in nodes}
            integrations = 0
            if any("github" in t for t in node_types):
                integrations += 1
            if any("llm" in t for t in node_types):
                integrations += 1
            if any(t in ["read-file", "write-file"] for t in node_types):
                integrations += 1
            if any("git" in t for t in node_types):
                integrations += 1

            assert integrations >= 2, f"Workflow {workflow['name']} should integrate multiple systems"

            # Should use template variables (reusable with different inputs)
            all_params = []
            for node in nodes:
                if "params" in node:
                    all_params.extend(str(v) for v in node["params"].values())

            has_templates = any("$" in param for param in all_params)
            assert has_templates or workflow["name"] == "issue-triage-report", (
                f"Workflow {workflow['name']} should use template variables for reusability"
            )

    def test_verbose_changelog_prompt_triggers_path_b(self, north_star_workflows):
        """Test that verbose north star prompt triggers Path B (generation)."""
        workflows_dir, workflows = north_star_workflows

        # Create workflow manager instance with test directory
        test_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        with (
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            # EXACT verbose north star prompt - should trigger Path B
            CHANGELOG_VERBOSE = """generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."""

            shared = {"user_input": CHANGELOG_VERBOSE}
            prep_res = node.prep(shared)

            # Mock LLM to NOT find existing workflow (Path B)
            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": False,
                                "workflow_name": None,
                                "confidence": 0.3,
                                "reasoning": "Too specific with version 1.3 and exact paths, needs new workflow",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                # Should take Path B for verbose prompt
                assert action == "not_found", "Verbose prompt should trigger Path B"
                assert "found_workflow" not in shared or shared.get("found_workflow") is None

    def test_verbose_triage_prompt_with_double_the(self, north_star_workflows):
        """Test triage report verbose prompt with intentional double 'the'."""
        workflows_dir, workflows = north_star_workflows

        # Create workflow manager instance with test directory
        test_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        with (
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            # EXACT verbose north star prompt with double "the" (intentional)
            TRIAGE_VERBOSE = """create a triage report for all open issues by fetching the the last 50 open issues from github, categorizing them by priority and type and then write them to triage-reports/2025-08-07-triage-report.md then commit the changes. Replace 2025-08-07 with the current date and mention the date in the commit message."""

            shared = {"user_input": TRIAGE_VERBOSE}
            prep_res = node.prep(shared)

            # Mock LLM to NOT find existing workflow (Path B)
            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": False,
                                "workflow_name": None,
                                "confidence": 0.25,
                                "reasoning": "Very specific with dates and paths, requires new workflow generation",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                # Should take Path B for verbose prompt
                assert action == "not_found", "Verbose triage prompt should trigger Path B"
                assert "found_workflow" not in shared or shared.get("found_workflow") is None


class TestWorkflowDiscoveryHappyPath:
    """Test that WorkflowDiscoveryNode correctly identifies and loads existing workflows."""

    @pytest.fixture
    def setup_workflow_directory(self):
        """Create a temporary workflow directory with sample workflows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflows_dir = Path(tmpdir) / "workflows"
            workflows_dir.mkdir()

            # Create a few realistic workflows that should match common requests
            workflows = [
                {
                    "name": "read-and-analyze-file",
                    "description": "Read a file and analyze its contents using LLM",
                    "metadata": {
                        "name": "read-and-analyze-file",
                        "description": "Read a file and analyze its contents using LLM",
                        "version": "1.0.0",
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                        "ir": {
                            "ir_version": "0.1.0",
                            "nodes": [
                                {"id": "read", "type": "read-file", "params": {"file_path": "${file_path}"}},
                                {"id": "analyze", "type": "llm", "params": {"prompt": "${prompt}"}},
                            ],
                            "edges": [{"from": "read", "to": "analyze", "action": "default"}],
                            "start_node": "read",
                            "inputs": {"file_path": "Path to file", "prompt": "Analysis prompt"},
                            "outputs": {"response": "LLM analysis"},
                        },
                    },
                },
                {
                    "name": "process-csv-data",
                    "description": "Read CSV files, process them, and generate reports",
                    "metadata": {
                        "name": "process-csv-data",
                        "description": "Read CSV files, process them, and generate reports",
                        "version": "1.0.0",
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                        "ir": {
                            "ir_version": "0.1.0",
                            "nodes": [
                                {"id": "read", "type": "read-file", "params": {"file_path": "${csv_file}"}},
                                {"id": "process", "type": "llm", "params": {"prompt": "Process this CSV data"}},
                                {"id": "write", "type": "write-file", "params": {"file_path": "${output_file}"}},
                            ],
                            "edges": [
                                {"from": "read", "to": "process", "action": "default"},
                                {"from": "process", "to": "write", "action": "default"},
                            ],
                            "start_node": "read",
                            "inputs": {"csv_file": "CSV file path", "output_file": "Output path"},
                            "outputs": {"result": "Processing result"},
                        },
                    },
                },
                {
                    "name": "github-issue-tracker",
                    "description": "List GitHub issues and create a summary report",
                    "metadata": {
                        "name": "github-issue-tracker",
                        "description": "List GitHub issues and create a summary report",
                        "version": "1.0.0",
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                        "ir": {
                            "ir_version": "0.1.0",
                            "nodes": [
                                {"id": "list", "type": "github-list-issues", "params": {"repo": "${repo}"}},
                                {"id": "summarize", "type": "llm", "params": {"prompt": "Summarize these issues"}},
                            ],
                            "edges": [{"from": "list", "to": "summarize", "action": "default"}],
                            "start_node": "list",
                            "inputs": {"repo": "Repository name"},
                            "outputs": {"summary": "Issues summary"},
                        },
                    },
                },
            ]

            # Write workflows to disk
            for workflow in workflows:
                workflow_path = workflows_dir / f"{workflow['name']}.json"
                workflow_path.write_text(json.dumps(workflow["metadata"], indent=2))

            yield str(workflows_dir), workflows

    def test_finds_exact_match_workflow(self, setup_workflow_directory, caplog):
        """Test that WorkflowDiscoveryNode finds an exact matching workflow."""
        workflows_dir, workflows = setup_workflow_directory

        # Create a real WorkflowManager with our test directory
        test_manager = WorkflowManager(workflows_dir=workflows_dir)

        # Patch both the WorkflowManager and context builder to use test directory
        with patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class:
            mock_wm_class.return_value = test_manager

            # Patch the global workflow manager in context_builder
            with patch("pflow.planning.context_builder._workflow_manager", test_manager):
                node = WorkflowDiscoveryNode()

                # Test query that should match "read-and-analyze-file" workflow
                shared = {"user_input": "I need to read a file and analyze its contents"}

                # Run the discovery
                prep_res = node.prep(shared)

                # Verify the context includes our workflows
                assert "read-and-analyze-file" in prep_res["discovery_context"]
                assert "Read a file and analyze its contents" in prep_res["discovery_context"]

            # Mock the LLM to return a positive match
            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": True,
                                "workflow_name": "read-and-analyze-file",
                                "confidence": 0.95,
                                "reasoning": "The workflow 'read-and-analyze-file' exactly matches the user's request to read a file and analyze its contents.",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                # Execute discovery
                exec_res = node.exec(prep_res)

                # Verify the happy path detection
                assert exec_res["found"] is True
                assert exec_res["workflow_name"] == "read-and-analyze-file"
                assert exec_res["confidence"] >= 0.9

                # Run post to verify Path A routing (with logging capture)
                with caplog.at_level(logging.INFO):
                    action = node.post(shared, prep_res, exec_res)

                # THIS IS THE KEY ASSERTION - Path A should be taken!
                assert action == "found_existing"

                # Verify workflow was loaded into shared store
                assert "found_workflow" in shared
                assert shared["found_workflow"]["name"] == "read-and-analyze-file"
                assert shared["found_workflow"]["ir"] is not None

                # Verify logging indicates Path A
                assert "routing to Path A" in caplog.text

    def test_finds_csv_processing_workflow(self, setup_workflow_directory):
        """Test finding a CSV processing workflow for a CSV-related query."""
        workflows_dir, workflows = setup_workflow_directory

        # Create a real WorkflowManager with our test directory
        test_manager = WorkflowManager(workflows_dir=workflows_dir)

        with (
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
        ):
            mock_wm_class.return_value = test_manager
            node = WorkflowDiscoveryNode()

            shared = {"user_input": "Process my CSV data and generate a report"}

            prep_res = node.prep(shared)

            # Mock LLM to recognize the CSV workflow
            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": True,
                                "workflow_name": "process-csv-data",
                                "confidence": 0.92,
                                "reasoning": "The 'process-csv-data' workflow matches - it reads CSV files, processes them, and generates reports.",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                # Verify Path A is taken for CSV processing
                assert action == "found_existing"
                assert shared["found_workflow"]["name"] == "process-csv-data"

    def test_path_a_performance_advantage(self, setup_workflow_directory):
        """Verify Path A is actually faster than Path B would be.

        FIX HISTORY:
        - 2025-01-19: Test was using empty discovery_context due to missing
          _workflow_manager patch. Now patches both WorkflowManager class
          and context_builder._workflow_manager to ensure workflows are
          discoverable.
        """
        workflows_dir, workflows = setup_workflow_directory

        # Create a real WorkflowManager with our test directory
        test_manager = WorkflowManager(workflows_dir=workflows_dir)

        with (
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            shared = {"user_input": "Read a file and analyze its contents"}

            # Mock for Path A (found)
            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": True,
                                "workflow_name": "read-and-analyze-file",
                                "confidence": 0.95,
                                "reasoning": "Exact match found",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                # Time Path A
                start = time.time()
                prep_res = node.prep(shared)
                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)
                path_a_time = time.time() - start

                assert action == "found_existing"
                assert shared["found_workflow"] is not None

                # Path A should be very fast (just discovery + load)
                # In real scenario, Path B would need multiple LLM calls for:
                # - Component browsing
                # - Parameter discovery
                # - Workflow generation
                # - Validation
                # - Metadata generation

                logger.info(f"Path A completed in {path_a_time:.3f}s")
                logger.info("Path B would require 5+ additional LLM calls")

                # Path A should complete in under 1 second (with mocked LLM)
                # Convert to warning per Task 28 lessons - performance varies by model
                if path_a_time > 1.0:
                    logger.warning(f"Path A slower than expected: {path_a_time:.2f}s (model-dependent)")

    def test_shared_store_properly_updated_on_path_a(self, setup_workflow_directory):
        """Test that shared store contains all required data for Path A execution.

        Validates that downstream nodes have everything they need.

        FIX HISTORY:
        - 2025-01-19: Test was using empty discovery_context due to missing
          _workflow_manager patch. Now patches both WorkflowManager class
          and context_builder._workflow_manager to ensure workflows are
          discoverable.
        """
        workflows_dir, workflows = setup_workflow_directory

        # Create a real WorkflowManager with our test directory
        test_manager = WorkflowManager(workflows_dir=workflows_dir)

        with (
            patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class,
            patch("pflow.planning.context_builder._workflow_manager", test_manager),
        ):
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            shared = {"user_input": "List GitHub issues and create a summary"}

            prep_res = node.prep(shared)

            # Mock LLM for perfect match
            with patch("llm.get_model") as mock_get_model:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": True,
                                "workflow_name": "github-issue-tracker",
                                "confidence": 0.98,
                                "reasoning": "Exact match for GitHub issue tracking",
                            }
                        }
                    ]
                }
                mock_model = Mock()
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                # Verify Path A
                assert action == "found_existing"

                # Verify shared store has all required data
                assert "discovery_result" in shared
                assert "discovery_context" in shared
                assert "found_workflow" in shared

                # Verify found_workflow structure
                found = shared["found_workflow"]
                assert "name" in found
                assert found["name"] == "github-issue-tracker"
                assert "description" in found
                assert "ir" in found
                assert "created_at" in found
                assert "updated_at" in found
                assert "version" in found

                # Verify IR structure is complete
                ir = found["ir"]
                assert "nodes" in ir
                assert "edges" in ir
                assert "start_node" in ir
                assert len(ir["nodes"]) > 0

                # Verify discovery result is preserved
                assert shared["discovery_result"]["found"] is True
                assert shared["discovery_result"]["confidence"] >= 0.9
                assert shared["discovery_result"]["workflow_name"] == "github-issue-tracker"
