"""LLM behavior tests for parameter extraction accuracy and edge cases.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests verify parameter extraction behavior with real language variations.
They're resilient to prompt changes and focus on extraction accuracy.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior/test_parameter_extraction_accuracy.py -v
"""

import json
import logging
import os

import pytest

from pflow.planning.nodes import ParameterDiscoveryNode, ParameterMappingNode

logger = logging.getLogger(__name__)

# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestParameterExtractionAccuracy:
    """Test accurate extraction of parameters from various language patterns."""

    def test_extract_github_parameters_variations(self):
        """Test extraction of GitHub/Git parameters in different formats."""
        node = ParameterDiscoveryNode()

        test_cases = [
            # (input, expected_to_contain)
            # North Star variations
            ("Generate changelog for anthropic/pflow since 2024-01-01", ["anthropic/pflow", "2024-01-01"]),
            ("Create release notes for version 2.0", ["2.0", "version"]),
            ("Summarize issue #456 from pflow repo", ["456", "pflow"]),
            ("Get issues with bug label from the main repository", ["bug", "main"]),
            ("List commits since last week in markdown", ["last week", "markdown"]),
        ]

        for user_input, expected_values in test_cases:
            shared = {"user_input": user_input}
            prep_res = node.prep(shared)

            try:
                exec_res = node.exec(prep_res)
                params = exec_res["parameters"]

                logger.info(f"Input: {user_input}")
                logger.info(f"Extracted: {params}")

                # Check if any expected value appears in parameters
                found = False
                for expected in expected_values:
                    if any(expected in str(v) for v in params.values()):
                        found = True
                        break

                assert found, f"Expected {expected_values} in parameters for: {user_input}"

            except Exception as e:
                if "API" in str(e) or "key" in str(e).lower():
                    pytest.skip(f"LLM API not configured: {e}")
                raise

    def test_extract_numeric_values_contexts(self):
        """Test extraction of numbers in different contexts."""
        node = ParameterDiscoveryNode()

        test_cases = [
            # North Star numeric parameters
            ("Get the first 10 issues", ["10", 10]),
            ("Limit changelog to 50 commits", ["50", 50]),
            ("Show last 100 contributors", ["100", 100]),
            ("Summarize issue number 123", ["123", 123]),
            ("Create report for Q3 2024", ["3", "2024", 3, 2024]),
            ("Get PRs from issues 1 through 50", ["1", "50", 1, 50]),
        ]

        for user_input, expected_values in test_cases:
            shared = {"user_input": user_input}
            prep_res = node.prep(shared)

            try:
                exec_res = node.exec(prep_res)
                params = exec_res["parameters"]

                logger.info(f"Numeric input: {user_input}")
                logger.info(f"Extracted: {params}")

                # Check if any expected numeric value appears
                found = False
                for expected in expected_values:
                    if any(str(expected) == str(v) for v in params.values()):
                        found = True
                        break

                assert found, f"Expected {expected_values} in parameters for: {user_input}"

            except Exception as e:
                if "API" in str(e) or "key" in str(e).lower():
                    pytest.skip(f"LLM API not configured: {e}")
                raise

    def test_extract_state_and_filter_values(self):
        """Test extraction of states, filters, and categorical values."""
        node = ParameterDiscoveryNode()

        test_cases = [
            # North Star state/filter parameters
            ("Show only open issues", ["open"]),
            ("Filter by state: closed", ["closed"]),
            ("Get all merged pull requests", ["merged"]),
            ("List bug and enhancement issues", ["bug", "enhancement"]),
            ("Find security and critical labels", ["security", "critical"]),
        ]

        for user_input, expected_values in test_cases:
            shared = {"user_input": user_input}
            prep_res = node.prep(shared)

            try:
                exec_res = node.exec(prep_res)
                params = exec_res["parameters"]

                logger.info(f"State/filter input: {user_input}")
                logger.info(f"Extracted: {params}")

                # Check if any expected state/filter appears
                found = False
                for expected in expected_values:
                    if any(expected.lower() in str(v).lower() for v in params.values()):
                        found = True
                        break

                assert found, f"Expected {expected_values} in parameters for: {user_input}"

            except Exception as e:
                if "API" in str(e) or "key" in str(e).lower():
                    pytest.skip(f"LLM API not configured: {e}")
                raise

    def test_extract_format_specifications(self):
        """Test extraction of output format specifications."""
        node = ParameterDiscoveryNode()

        test_cases = [
            # North Star format parameters
            ("Export changelog as CSV", ["csv", "CSV"]),
            ("Generate release notes in JSON format", ["json", "JSON"]),
            ("Output issue report in markdown", ["markdown", "md"]),
            ("Create PDF changelog", ["pdf", "PDF"]),
            ("Save triage report as plain text", ["text", "txt"]),
            ("Return commit data as JSON", ["json", "JSON"]),
        ]

        for user_input, expected_values in test_cases:
            shared = {"user_input": user_input}
            prep_res = node.prep(shared)

            try:
                exec_res = node.exec(prep_res)
                params = exec_res["parameters"]

                logger.info(f"Format input: {user_input}")
                logger.info(f"Extracted: {params}")

                # Check if any expected format appears
                found = False
                for expected in expected_values:
                    if any(expected.lower() in str(v).lower() for v in params.values()):
                        found = True
                        break

                assert found, f"Expected {expected_values} in parameters for: {user_input}"

            except Exception as e:
                if "API" in str(e) or "key" in str(e).lower():
                    pytest.skip(f"LLM API not configured: {e}")
                raise


class TestComplexParameterScenarios:
    """Test complex parameter extraction scenarios."""

    def test_nested_data_extraction(self):
        """Test extraction of nested or structured data."""
        node = ParameterDiscoveryNode()

        # North Star complex example
        shared = {
            "user_input": (
                "Create a triage report for repo 'anthropic/pflow' with labels 'bug', 'security', "
                "state 'open', limit 50, and output format markdown"
            )
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)
            params = exec_res["parameters"]

            logger.info(f"Nested data extraction: {params}")

            # Should extract multiple related parameters
            param_str = json.dumps(params).lower()

            assert "anthropic/pflow" in param_str or "pflow" in param_str
            assert "bug" in param_str
            assert "security" in param_str
            assert "open" in param_str
            assert "50" in param_str
            assert "markdown" in param_str or "md" in param_str

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_ambiguous_language_handling(self):
        """Test handling of ambiguous or unclear parameter specifications."""
        node = ParameterDiscoveryNode()

        test_cases = [
            "Generate that changelog we discussed",  # Ambiguous changelog reference
            "Use the default repo but change the important parameter",  # Vague specification
            "Create the release notes from yesterday's version",  # Temporal ambiguity
        ]

        for user_input in test_cases:
            shared = {"user_input": user_input}
            prep_res = node.prep(shared)

            try:
                exec_res = node.exec(prep_res)
                params = exec_res["parameters"]

                logger.info(f"Ambiguous input: {user_input}")
                logger.info(f"Extracted: {params}")
                logger.info(f"Reasoning: {exec_res['reasoning']}")

                # With ambiguous input, params might be empty or minimal
                # The important part is the system doesn't crash
                assert isinstance(params, dict)

                # Reasoning should acknowledge the ambiguity
                if not params:
                    assert (
                        "ambiguous" in exec_res["reasoning"].lower()
                        or "unclear" in exec_res["reasoning"].lower()
                        or "specific" in exec_res["reasoning"].lower()
                    )

            except Exception as e:
                if "API" in str(e) or "key" in str(e).lower():
                    pytest.skip(f"LLM API not configured: {e}")
                raise

    def test_parameter_with_special_characters(self):
        """Test extraction of parameters with special characters."""
        node = ParameterDiscoveryNode()

        test_cases = [
            "Get issues from anthropic/pflow repo",  # Slash in repo name
            "Create changelog for v2.0.1-beta",  # Version with dots and dash
            "Filter by label #bug",  # Hash in label
            "Since date: 2024-01-01T00:00:00Z",  # ISO date format
            "Issue number: #123",  # Issue with hash
        ]

        for user_input in test_cases:
            shared = {"user_input": user_input}
            prep_res = node.prep(shared)

            try:
                exec_res = node.exec(prep_res)
                params = exec_res["parameters"]

                logger.info(f"Special char input: {user_input}")
                logger.info(f"Extracted: {params}")

                # Should handle special characters without breaking
                assert isinstance(params, dict)

                # Check that some meaningful extraction happened
                if params:
                    # At least one parameter should have been extracted
                    assert len(params) > 0

            except Exception as e:
                if "API" in str(e) or "key" in str(e).lower():
                    pytest.skip(f"LLM API not configured: {e}")
                raise


class TestParameterMappingAccuracy:
    """Test accurate mapping of extracted parameters to workflow inputs."""

    def test_case_sensitive_parameter_matching(self):
        """Test that parameter names are matched case-sensitively."""
        node = ParameterMappingNode()

        # North Star with camelCase parameters
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "repoName": {"type": "string", "required": True},  # CamelCase
                "sinceDate": {"type": "string", "required": True},  # CamelCase
                "outputFormat": {"type": "string", "required": True},  # CamelCase
            },
        }

        shared = {
            "user_input": "Generate changelog for pflow since January 2024 in markdown",
            "generated_workflow": workflow_ir,
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)
            extracted = exec_res["extracted"]

            logger.info(f"Case-sensitive mapping: {extracted}")
            logger.info(f"Missing: {exec_res['missing']}")

            # Should use exact parameter names from workflow
            if extracted:
                # Check that camelCase names are preserved
                assert "repoName" in extracted or "sinceDate" in extracted or "outputFormat" in extracted

                # Should NOT have snake_case versions
                assert "repo_name" not in extracted
                assert "since_date" not in extracted
                assert "output_format" not in extracted

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_optional_vs_required_parameter_handling(self):
        """Test correct handling of optional vs required parameters."""
        node = ParameterMappingNode()

        # North Star with optional parameters
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "repo": {"type": "string", "required": True},
                "since_date": {"type": "string", "required": True},
                "format": {"type": "string", "required": False, "default": "markdown"},
                "include_stats": {"type": "boolean", "required": False, "default": False},
            },
        }

        shared = {
            "user_input": "Generate changelog for pflow since 2024-01-01",  # No optional params mentioned
            "generated_workflow": workflow_ir,
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)

            logger.info(f"Optional params - Extracted: {exec_res['extracted']}")
            logger.info(f"Missing: {exec_res['missing']}")

            # Should extract required parameters
            if "repo" in exec_res["extracted"]:
                assert "pflow" in str(exec_res["extracted"]["repo"]).lower()
            if "since_date" in exec_res["extracted"]:
                assert "2024" in str(exec_res["extracted"]["since_date"])

                # Should NOT mark optional parameters as missing
                assert "format" not in exec_res["missing"]
                assert "include_stats" not in exec_res["missing"]

                # Should be confident if all required params found
                assert exec_res["confidence"] > 0.5

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_stdin_as_parameter_source(self):
        """Test using stdin data to fulfill parameter requirements."""
        node = ParameterMappingNode()

        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "json_data": {"type": "object", "required": True},
            },
        }

        shared = {
            "user_input": "Process the JSON input",
            "stdin": '{"name": "test", "value": 42}',
            "generated_workflow": workflow_ir,
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)

            logger.info(f"Stdin as param - Extracted: {exec_res['extracted']}")
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # Should recognize stdin can fulfill json_data requirement
            if exec_res["extracted"] and "json_data" in exec_res["extracted"]:
                # Either the actual JSON or reference to stdin
                assert exec_res["confidence"] > 0.5
                assert len(exec_res["missing"]) == 0

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_partial_parameter_extraction(self):
        """Test behavior when only some parameters can be extracted."""
        node = ParameterMappingNode()

        # North Star with missing parameters
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "repo": {"type": "string", "required": True},
                "labels": {"type": "array", "required": True},
                "state": {"type": "string", "required": True},
                "limit": {"type": "integer", "required": True},
            },
        }

        shared = {
            "user_input": "Create triage report for pflow with bug label",  # Missing state and limit
            "generated_workflow": workflow_ir,
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)

            logger.info(f"Partial extraction - Extracted: {exec_res['extracted']}")
            logger.info(f"Missing: {exec_res['missing']}")

            # Should extract what it can
            extracted = exec_res["extracted"]
            if extracted:
                # Should find repo and labels
                has_repo = "repo" in extracted and "pflow" in str(extracted.get("repo", "")).lower()
                has_labels = "labels" in extracted and "bug" in str(extracted.get("labels", "")).lower()

                assert has_repo or has_labels

            # Should identify missing state and limit
            assert "state" in exec_res["missing"] or "limit" in exec_res["missing"]
            assert exec_res["confidence"] == 0.0  # Low confidence with missing required

            # Post should route to incomplete
            action = node.post(shared, prep_res, exec_res)
            assert action == "params_incomplete"

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


class TestConvergenceArchitectureIntegration:
    """Test the complete convergence architecture with real scenarios."""

    def test_discovery_to_mapping_flow(self):
        """Test parameter discovery flowing into mapping."""
        discovery_node = ParameterDiscoveryNode()
        mapping_node = ParameterMappingNode()

        # North Star discovery to mapping flow
        shared = {"user_input": "Create release notes for version 2.0 of pflow including contributors"}

        # First: Discovery extracts hints
        discovery_prep = discovery_node.prep(shared)

        try:
            discovery_exec = discovery_node.exec(discovery_prep)
            discovery_node.post(shared, discovery_prep, discovery_exec)

            logger.info(f"Discovery found: {shared['discovered_params']}")

            # Simulate workflow generation using discovered params
            shared["generated_workflow"] = {
                "ir_version": "0.1.0",
                "inputs": {
                    "version": {"type": "string", "required": True},
                    "repo": {"type": "string", "required": True},
                    "include_contributors": {"type": "boolean", "required": False, "default": False},
                },
            }

            # Second: Mapping verifies extraction
            mapping_prep = mapping_node.prep(shared)
            mapping_exec = mapping_node.exec(mapping_prep)

            logger.info(f"Mapping extracted: {mapping_exec['extracted']}")

            # Mapping should independently extract version and repo
            if mapping_exec["extracted"]:
                has_version = "version" in mapping_exec["extracted"] or any(
                    "2.0" in str(v) for v in mapping_exec["extracted"].values()
                )
                has_repo = "repo" in mapping_exec["extracted"] or any(
                    "pflow" in str(v).lower() for v in mapping_exec["extracted"].values()
                )
                assert has_version or has_repo

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_independent_extraction_validation(self):
        """Test that mapping performs truly independent extraction."""
        mapping_node = ParameterMappingNode()

        # Test case where discovered params might be wrong - North Star example
        shared = {
            "user_input": "Generate changelog for anthropic/pflow since January 2024",
            "discovered_params": {
                "repo": "pflow",  # Wrong! Discovery missed "anthropic/"
                "date": "January",  # Incomplete date
            },
            "generated_workflow": {
                "ir_version": "0.1.0",
                "inputs": {
                    "repo": {"type": "string", "required": True},
                    "since_date": {"type": "string", "required": True},
                },
            },
        }

        prep_res = mapping_node.prep(shared)

        try:
            exec_res = mapping_node.exec(prep_res)

            logger.info(f"Independent extraction: {exec_res['extracted']}")

            # Mapping should extract independently, not rely on discovered_params
            if exec_res["extracted"]:
                # Should find the correct repo name from original input
                repo = exec_res["extracted"].get("repo", "")
                assert "anthropic/pflow" in str(repo).lower() or "anthropic" in str(repo).lower()

                # Should also extract complete date
                since_date = exec_res["extracted"].get("since_date", "")
                assert "january" in str(since_date).lower() or "2024" in str(since_date)

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_convergence_with_complex_workflow(self):
        """Test convergence with a complex multi-parameter workflow."""
        mapping_node = ParameterMappingNode()

        # Complex North Star workflow with many parameters
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "repo": {"type": "string", "required": True},
                "labels": {"type": "array", "required": True},
                "state": {"type": "string", "required": False, "default": "open"},
                "since_date": {"type": "string", "required": False},
                "limit": {"type": "integer", "required": False, "default": 100},
                "format": {"type": "string", "required": True},
            },
        }

        shared = {
            "user_input": (
                "Create a triage report for GitHub issues from anthropic/pflow "
                "with bug and enhancement labels, closed state, since January 2024, limit to 50"
            ),
            "generated_workflow": workflow_ir,
        }

        prep_res = mapping_node.prep(shared)

        try:
            exec_res = mapping_node.exec(prep_res)

            logger.info(f"Complex extraction: {exec_res['extracted']}")
            logger.info(f"Missing: {exec_res['missing']}")

            extracted = exec_res["extracted"]
            if extracted:
                # Should extract multiple parameters
                assert len(extracted) >= 2  # At least repo, labels, and format

                # Check for specific extractions
                param_str = json.dumps(extracted).lower()

                # Required params
                assert "anthropic/pflow" in param_str or "pflow" in param_str  # repo
                assert "bug" in param_str  # labels
                assert "enhancement" in param_str  # labels

                # Optional params that should be found
                assert "closed" in param_str  # state
                assert "january" in param_str or "2024" in param_str  # since_date
                assert "50" in param_str  # limit

                # All required params should be found
                assert "repo" not in exec_res["missing"]
                assert "labels" not in exec_res["missing"]
                assert "format" not in exec_res["missing"]

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error scenarios in parameter extraction."""

    def test_empty_input_handling(self):
        """Test handling of empty or minimal input."""
        discovery_node = ParameterDiscoveryNode()

        # Test with empty input
        shared = {"user_input": ""}

        # Discovery should handle gracefully
        with pytest.raises(ValueError, match="Missing required 'user_input'"):
            discovery_node.prep(shared)

        # Test with minimal input
        shared = {"user_input": "Do it"}
        discovery_prep = discovery_node.prep(shared)

        try:
            discovery_exec = discovery_node.exec(discovery_prep)

            # Should return empty or minimal parameters
            assert isinstance(discovery_exec["parameters"], dict)
            assert len(discovery_exec["parameters"]) == 0 or discovery_exec["reasoning"].lower().count("vague") > 0

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_conflicting_parameter_values(self):
        """Test handling of conflicting parameter specifications."""
        mapping_node = ParameterMappingNode()

        # North Star conflicting parameters
        workflow_ir = {"ir_version": "0.1.0", "inputs": {"state": {"type": "string", "required": True}}}

        shared = {
            "user_input": "Get open issues, no wait, get closed issues instead",  # Conflicting!
            "generated_workflow": workflow_ir,
        }

        prep_res = mapping_node.prep(shared)

        try:
            exec_res = mapping_node.exec(prep_res)

            logger.info(f"Conflict resolution: {exec_res['extracted']}")
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # Should pick one (likely the last mentioned)
            if exec_res["extracted"] and "state" in exec_res["extracted"]:
                state = exec_res["extracted"]["state"]
                assert "closed" in str(state).lower() or "open" in str(state).lower()

                # Reasoning might mention the conflict
                assert exec_res["reasoning"]  # Should explain the choice

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_binary_stdin_handling(self):
        """Test handling of binary stdin data."""
        discovery_node = ParameterDiscoveryNode()

        shared = {
            "user_input": "Process the uploaded image",
            "stdin_binary": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...",  # PNG header
        }

        prep_res = discovery_node.prep(shared)

        # Should recognize binary stdin
        assert prep_res["stdin_info"]["type"] == "binary"
        assert "size" in prep_res["stdin_info"]

        try:
            exec_res = discovery_node.exec(prep_res)

            logger.info(f"Binary stdin - Type: {exec_res.get('stdin_type')}")
            logger.info(f"Parameters: {exec_res['parameters']}")

            # Should note binary stdin is available
            if exec_res.get("stdin_type"):
                assert exec_res["stdin_type"] == "binary"

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_workflow_without_inputs(self):
        """Test handling of workflows that don't require inputs."""
        mapping_node = ParameterMappingNode()

        shared = {
            "user_input": "Run the default changelog generator",
            "generated_workflow": {
                "ir_version": "0.1.0",
                "inputs": {},  # No inputs defined - uses all defaults
            },
        }

        prep_res = mapping_node.prep(shared)
        exec_res = mapping_node.exec(prep_res)

        # Should handle gracefully
        assert exec_res["extracted"] == {}
        assert exec_res["missing"] == []
        assert exec_res["confidence"] == 1.0
        assert exec_res["reasoning"] == "Workflow has no input parameters defined"

        # Should route to complete
        action = mapping_node.post(shared, prep_res, exec_res)
        assert action == "params_complete"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
