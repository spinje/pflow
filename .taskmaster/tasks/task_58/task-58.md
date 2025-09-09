# Task 58: Update workflow generator prompt-tests to use better real world test cases

## ID
58

## Title
Update workflow generator prompt-tests to use better real world test cases

## Description
Replace the current workflow generator test cases with realistic, real-world examples that validate actual system capabilities. The current tests use many non-existent mock nodes, making them poor validators of real functionality. This task focuses on creating test cases that use actual available nodes, follow north star examples, and include MCP integration testing.

## Status
in progress

## Dependencies
None

## Priority
high

## Details
The workflow generator prompt tests currently suffer from several critical issues that need to be addressed:

### Current Problems
- **Mock node pollution**: Tests use non-existent nodes like `slack-notify`, `build-project`, `backup-database`
- **Zero MCP coverage**: Despite 22+ MCP nodes available, no tests exercise them
- **Unrealistic prompts**: User inputs are overly verbose and unlike actual usage patterns
- **False confidence**: Tests pass with fictional nodes, giving misleading success signals

### Implementation Approach (Option C with minimal mocks)
Based on our analysis and the user's preference, we will:
1. Use **only real nodes** from the registry (git, github, llm, file operations)
2. Employ **shell workarounds** for missing functionality (e.g., `git tag` via shell node)
3. Mock **only Slack MCP nodes** based on proven real-world usage from trace analysis
4. Focus on **north star examples** from architecture/vision/north-star-examples.md

### Test Case Distribution (15 tests total)
- **5 real developer workflows** (changelog generation, PR summaries, test generation)
- **5 MCP integration tests** (including Slack automation from real trace)
- **3 complex multi-step workflows** (full release pipelines)
- **2 edge cases** (template variable stress, validation recovery)

### Key Design Decisions
- **87% real tests** (13/15 use only actual nodes)
- **Minimal mocking** (only 2 Slack MCP nodes based on trace evidence)
- **Shell creativity** for missing features (`gh release create`, `git tag`)
- **Progressive complexity** showing first-time detailed prompts vs brief reuse
- **Real value focus** - each test solves an actual developer problem

### Technical Implementation
- Complete rewrite of `test_workflow_generator_prompt.py`
- Update test registry to include only real nodes + 2 Slack MCP mocks
- Maintain parallel execution compatibility
- Preserve failure reporting mechanisms
- Target ~10-15 second execution time

## Test Strategy
The test strategy focuses on behavioral validation with realistic scenarios:

### Unit Test Coverage
- Each test case validates complete workflow generation
- Template variable resolution and data flow between nodes
- Proper input/output declarations
- Linear workflow structure (no branching)

### Integration Testing
- Tests work with actual registry (no fake nodes except Slack MCP)
- Shell command integration for workarounds
- Cross-node data flow validation
- Real parameter extraction patterns

### Key Test Scenarios
- **North star workflows**: Changelog generation from GitHub issues
- **MCP integration**: Slack Q&A automation (from real trace)
- **Shell workarounds**: Git tagging, GitHub releases via CLI
- **Template complexity**: Heavy variable usage and cross-references
- **Error recovery**: Validation error fixing

### Success Criteria
- All tests use real available nodes (except 2 Slack MCP)
- Tests complete in under 15 seconds with parallelization
- Cost remains under $0.50 per full test run
- Clear failure signals for debugging
- Coverage of actual developer workflows