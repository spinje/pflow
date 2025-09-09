# Feature: update_workflow_generator_tests

## Objective

Replace mock-heavy tests with real-world workflow examples.

## Requirements

* Must have access to pflow registry with real nodes
* Must have test_workflow_generator_prompt.py file to update
* Must have north star examples from architecture/vision/north-star-examples.md
* Must have pytest parametrization support
* Must have parallel execution infrastructure

## Scope

* Does not modify the workflow generator prompt itself
* Does not change test infrastructure or pytest configuration
* Does not implement missing nodes (only mocks Slack MCP)
* Does not modify test accuracy tracking system
* Does not change other prompt tests

## Inputs

* `test_file_path`: str - Path to test_workflow_generator_prompt.py
* `registry_nodes`: list[str] - Available real nodes from registry
* `north_star_examples`: list[dict] - Examples from architecture docs
* `trace_data`: dict - Real usage patterns from planner trace

## Outputs

Returns: Updated test file with 15 real-world test cases

Side effects:
* Modifies test_workflow_generator_prompt.py
* Updates test registry mock to include only real nodes plus 2 Slack MCP mocks

## Structured Formats

```python
@dataclass
class WorkflowTestCase:
    name: str                          # Test identifier
    user_input: str                    # Natural language prompt
    discovered_params: dict[str, str]  # Extracted parameters
    planning_context: str              # Available nodes
    browsed_components: dict           # Selected components
    validation_errors: Optional[list[str]]  # For recovery tests
    expected_nodes: list[str]          # Node types in order
    min_nodes: int                     # Minimum node count
    max_nodes: int                     # Maximum node count
    must_have_inputs: list[str]        # Required user inputs
    must_not_have_inputs: list[str]   # Should NOT be inputs
    node_output_refs: list[str]        # Expected ${node.output}
    category: str                      # Test category
    why_hard: str                      # Difficulty rationale
    # New fields to add during implementation:
    # user_input_brief: Optional[str]  # For reuse scenarios
    # is_north_star: bool              # Mark primary examples
    # uses_mcp: bool                   # Track MCP usage
```

## State/Flow Changes

* `existing` → `analyzed` when current tests reviewed
* `analyzed` → `designed` when new test cases created
* `designed` → `implemented` when code written
* `implemented` → `validated` when tests pass

## Constraints

* Exactly 15 test cases
* Maximum 2 Slack MCP mock nodes
* Shell workarounds only via shell node
* Target test execution < 15 seconds (requires manual pytest-xdist installation)
* Target cost < $0.50 per full run (estimate based on typical LLM usage)

## Rules

1. Use only nodes that exist in real registry
2. Mock only mcp-slack-slack_get_channel_history
3. Mock only mcp-slack-slack_post_message
4. Include changelog_from_issues as primary north star
5. Use shell node for git tag operations
6. Use shell node for gh release create
7. Use shell node for gh pr comment
8. Remove all other mock nodes
9. Each test case must solve real developer problem
10. Test prompts must be natural language
11. Include both detailed and brief prompts
12. Maintain parallel execution compatibility
13. Preserve failure reporting mechanism
14. Use pytest.mark.parametrize decorator
15. Include 5 real developer workflows
16. Include 5 MCP integration tests
17. Include 3 complex multi-step workflows
18. Include 2 edge case tests

## Edge Cases

* Node not in registry → Use shell workaround
* GitHub release needed → Use gh cli via shell
* Slack integration needed → Use mocked MCP nodes
* Git tag creation needed → Use git command via shell
* Complex file operations → Use shell commands
* Template variable stress → Test with many variables
* Validation errors → Test recovery scenarios

## Error Handling

* Missing node → Use shell node with appropriate command
* Test timeout → Fail with clear message about execution time
* LLM failure → Report via failure_reason mechanism
* Invalid workflow generated → Capture validation errors

## Non-Functional Criteria

* Test execution time target < 15 seconds (with optional pytest-xdist)
* Test cost estimate < $0.50 per full run
* Clear failure signals for debugging via report_failure()
* Maintainable test structure using pytest.mark.parametrize

## Examples

### North Star Test Case
```python
WorkflowTestCase(
    name="changelog_from_issues",
    user_input="Generate a changelog from the last 20 closed issues in github repo anthropic/pflow, categorize by type, write to CHANGELOG.md, and commit the changes",
    user_input_brief="generate changelog",
    discovered_params={"repo_owner": "anthropic", "repo_name": "pflow", "issue_count": "20", "changelog_path": "CHANGELOG.md"},
    expected_nodes=["github-list-issues", "llm", "write-file", "git-commit"],
    min_nodes=4,
    max_nodes=5,
    must_have_inputs=["repo_owner", "repo_name"],
    must_not_have_inputs=["issues", "changelog"],
    is_north_star=True,
    uses_mcp=False
)
```

### MCP Integration Test
```python
WorkflowTestCase(
    name="slack_qa_automation",
    user_input="Get the last 10 messages from slack channel C09C16NAU5B, use AI to answer any questions asked, send answer back to the channel",
    expected_nodes=["mcp-slack-slack_get_channel_history", "llm", "mcp-slack-slack_post_message"],
    uses_mcp=True
)
```

## Test Criteria

1. All 15 test cases defined with complete WorkflowTestCase structure
2. Exactly 2 Slack MCP nodes mocked
3. No other mock nodes present in test registry
4. changelog_from_issues test marked as north star
5. Shell workarounds used for git tag
6. Shell workarounds used for GitHub release
7. Test execution completes in under 15 seconds
8. All tests use pytest.mark.parametrize
9. 13 tests use only real nodes
10. 2 tests use Slack MCP mocks
11. Test categories properly distributed
12. Natural language prompts used
13. Brief reuse prompts included where applicable
14. Failure reporting mechanism preserved
15. Cost tracking remains functional

## Notes (Why)

* Mock nodes give false confidence about system capabilities
* Real-world examples better validate actual functionality
* Shell workarounds provide practical solutions for missing features
* MCP integration tests validate extensibility
* North star examples represent proven valuable workflows
* Natural language prompts match actual user behavior

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 9                          |
| 2      | 2, 10                      |
| 3      | 2, 10                      |
| 4      | 4                          |
| 5      | 5                          |
| 6      | 6                          |
| 7      | 6                          |
| 8      | 2, 3                       |
| 9      | 1, 12                      |
| 10     | 12                         |
| 11     | 13                         |
| 12     | 7, 14                      |
| 13     | 14                         |
| 14     | 8                          |
| 15     | 1, 11                      |
| 16     | 1, 10, 11                  |
| 17     | 1, 11                      |
| 18     | 1, 11                      |

## Versioning & Evolution

* **Version:** 1.0.0
* **Changelog:**
  * **1.0.0** — Initial spec for replacing mock-heavy tests with real-world examples

## Epistemic Appendix

### Assumptions & Unknowns

* Verified: Shell node can execute git and gh commands without restrictions
* Verified: MCP nodes require mocking since they depend on external server config
* Verified: 13 tests currently exist, expanding to 15 for better coverage
* Unknown: Exact execution time without pytest-xdist installed
* Unknown: Exact cost per run (estimated based on token usage)

### Conflicts & Resolutions

* Conflict: Need GitHub release functionality but node doesn't exist
  * Resolution: Use shell node with gh cli command
* Conflict: Tests require Slack integration but no core Slack nodes
  * Resolution: Mock only the 2 specific MCP Slack nodes from trace

### Decision Log / Tradeoffs

* Chose shell workarounds over extensive mocking for maintainability
* Limited to 2 Slack MCP mocks based on real trace evidence
* Selected 15 tests as balance between coverage and execution time
* Prioritized north star examples over edge cases

### Ripple Effects / Impact Map

* Test execution may depend on shell command availability
* CI environment needs git and gh cli installed
* Future node additions may obsolete shell workarounds
* Test maintenance required when nodes are implemented

### Residual Risks & Confidence

* Risk: Shell commands may behave differently across platforms (Low - git/gh are standard)
* Risk: gh cli may require authentication in CI (Medium - needs GH_TOKEN env var)
* Risk: Test execution time may exceed 15 seconds without pytest-xdist (Low - can install if needed)
* Risk: WorkflowTestCase structure changes needed (Low - can extend dataclass)
* Confidence: High for core functionality, High for shell workarounds (verified no restrictions)

### Epistemic Audit (Checklist Answers)

1. Verified: Shell node has no restrictions on git/gh commands; Assumed: Cross-platform compatibility
2. If wrong: CI may need platform-specific workarounds for shell commands
3. Prioritized practicality (shell workarounds) over waiting for missing nodes
4. All rules mapped to test criteria with bi-directional traceability
5. Changes isolated to test_workflow_generator_prompt.py and test registry mock
6. Remaining uncertainty: pytest-xdist performance gain, exact costs; Confidence: High (verified all core assumptions)