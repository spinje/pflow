# Task 121: Workflow Testability — Mock Nodes, Assert Outputs, `pflow test`

## Description

Enable users and agents to write automated, repeatable tests for `.pflow.md` workflows. Workflows have declared inputs and outputs, and nodes communicate through a shared store — this architecture naturally supports mocking at the node level and asserting on workflow outputs. Without testability, modifying and re-publishing workflows is reckless rather than confident.

## Status

not started

## Priority

medium

## Problem

There is no way to automatically test a pflow workflow. A developer who builds a workflow and wants to verify it keeps working after modifications has zero tooling support. This matters because:

1. **Modification safety:** pflow workflows are meant to be living artifacts — agents modify and re-publish them as needs change. Without tests, every modification is a gamble.
2. **Developer trust:** Developers evaluating pflow will ask "can I write tests for this?" immediately. No testing story is a credibility gap.
3. **LLM non-determinism:** Most workflows include LLM nodes whose outputs vary between runs. Testing requires mocking these to get repeatable assertions.
4. **CI integration:** Workflows that run in production need automated verification in CI pipelines, not just manual spot-checking.

Task 76 (`pflow registry run`) addresses a different problem: testing individual nodes in isolation during workflow creation. This task is about testing complete workflows with mocked dependencies after they're built.

## Solution

A `pflow test` command that runs workflows with mocked node responses and asserts on outputs. Two complementary approaches:

### 1. Declarative mocks and assertions (primary)

Mocks and assertions defined in YAML/markdown — no Python needed, agents can author them.

```markdown
## Tests

### basic_usage
- mocks:
    analyze_text: {result: "Positive sentiment detected"}
    fetch_data: {response: {status: 200, body: '{"items": [1, 2, 3]}'}}
- input: {url: "https://example.com"}
- assert:
    sentiment: "positive"
    item_count: 3
```

Mocks keyed by node ID. pflow intercepts execution at that node and returns the mock data to the shared store instead of running the real node.

### 2. Snapshot/record-replay

Run a workflow once against real services, capture each node's output from the shared store, save as a test fixture. Re-run with captured responses as mocks.

```bash
pflow test --record workflow.pflow.md input=value    # Run real, save snapshots
pflow test workflow.pflow.md                          # Replay with saved mocks
```

Solves the "what should my LLM mock look like?" problem — don't invent it, capture it.

### Assertion types

- Exact match: `{key: "value"}`
- Contains: `{key: "contains:substring"}`
- Non-empty: `{key: "non_empty"}`
- Pattern/regex: `{key: "matches:pattern"}`
- Type check: `{key: "type:list"}`

LLM outputs need fuzzy assertions since exact matching is meaningless for non-deterministic responses.

## Design Decisions

- **Mock at node level, not service level:** pflow controls the execution pipeline via the wrapper chain. Intercepting at the node boundary (before `exec()`) is architecturally clean — the node interface is declared, so mock shape is known. This is simpler than mocking HTTP/MCP/LLM services individually.
- **Tests can live in the .pflow.md file:** A `## Tests` section in the workflow file itself. Same file, can't drift apart. But also support external test files for complex cases.
- **Declarative first, pytest as escape hatch:** Simple cases should be simple (YAML mocks + assertions). Complex cases (parametrized inputs, custom assertion logic, edge case coverage for code nodes) can use pytest integration, but that's a power-user path, not the default.
- **Code nodes run for real against mocked inputs:** When upstream nodes are mocked, the code node receives controlled inputs from the shared store. This tests the actual code logic without needing to mock the code node itself. Only mock code nodes when testing downstream behavior in isolation.
- **No overlap with Task 76:** Task 76 = run a single real node to explore its output during development. Task 121 = run a full workflow with mocked nodes to verify correctness. Task 76's structure mode output is useful for knowing what shape mocks should be, but they're different execution paths.

## Dependencies

None strictly required. These would enhance the feature:

- Task 108: Smart Trace Debug Output — Better trace output would improve test failure messages
- Task 106: Workflow Iteration Cache — Related caching infrastructure, may share patterns

## Implementation Notes

### Interception point

The wrapper chain (InstrumentedWrapper → BatchWrapper → NamespacedWrapper → TemplateAwareWrapper → ActualNode) is the natural place to insert mocking. A MockWrapper could sit at the top, short-circuiting `exec()` when a mock is defined for that node, writing mock data directly to the shared store.

### Snapshot storage

Recorded snapshots could live alongside the workflow:
```
my-workflow.pflow.md
my-workflow.pflow-snapshots/
  basic_usage/
    fetch_data.json
    analyze_text.json
```

Or in a `## Tests` section with inline mock data for simple cases.

### What gets mocked

Every node type should be mockable. The most common mocking needs:
- **LLM nodes:** Always mock in tests (non-deterministic, costs money)
- **HTTP nodes:** Usually mock (external dependency)
- **MCP nodes:** Usually mock (requires running MCP server)
- **Shell nodes:** Sometimes mock (side effects), sometimes run real (pure transforms)
- **Code nodes:** Usually run real (that's the logic you're testing)
- **File nodes:** Sometimes mock (test without filesystem), sometimes real

### Test output

```
$ pflow test my-workflow.pflow.md

  basic_usage .............. PASS
  handles_404 .............. PASS
  empty_input .............. FAIL
    Expected: {items: "non_empty"}
    Got: {items: []}
    Node 'fetch_data' returned empty response

2 passed, 1 failed
```

## Verification

- `pflow test workflow.pflow.md` runs all tests defined in the workflow file
- Mocked nodes don't execute real logic (no LLM calls, no HTTP requests)
- Non-mocked nodes execute normally against mocked upstream data in shared store
- Snapshot recording captures real execution, replay produces same assertions
- Tests can run in CI without credentials or external services
- Agents can author tests (declarative format, no Python required)
- Test failures show which node produced unexpected output and what was expected vs actual
