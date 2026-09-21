# Node Implementation Guide

Nodes own business logic. The engine owns template resolution, namespacing, and
instrumentation; see `runtime/engine/CLAUDE.md`.

## Inputs, outputs, and lifecycle

Author-provided inputs—static or resolved from `${...}`—arrive in `self.params`
before `prep()`. Do not read author inputs from `shared` as a fallback. `shared`
still carries injected runtime infrastructure such as MCP pools/cancellation, and
`post()` writes node outputs there.

Production nodes inherit `core/node.py:Node`. Exceptions escaping `exec()` enter
`Node._exec`'s retry loop; non-retriable failures or exhausted attempts reach
`exec_fallback`. The engine owns graph traversal, not these retries. Translate
failures inside exec deliberately when they are valid routable results, known
non-retriable failures, or unsafe to repeat. Keep exec/fallback/post result shapes
and returned actions consistent. Examples: `llm/llm.py` selective retry suppression
and `http/http.py` routing of valid HTTP error responses.

Store natural output types. Do not add convenience JSON auto-parsing to ordinary
nodes; template coercion owns that behavior. See
`architecture/core-concepts/data-type-coercion.md`.

## Navigation

| Concern | Owner |
|---|---|
| Lifecycle/retry primitives | `src/pflow/core/node.py` |
| Shell and HTTP behavior | `shell/shell.py`, `http/http.py` |
| LLM invocation and schema handling | `llm/llm.py`, `llm/schema_validation.py` |
| File operations | `file/` (one implementation per operation) |
| Python code execution and next-action routing | `python/python_code.py:PythonCodeNode` |
| Agent orchestration and schema retries | `agent/agent_node.py:AgentNode` |
| Provider contract/adapters | `agent/backend.py:AgentBackend`, `agent/claude_backend.py`, `agent/codex_backend.py` |
| MCP tool bridge/result extraction | `mcp/node.py:MCPNode`, `_extract_result`; client sessions in `src/pflow/mcp/pool.py` |
| Machine-read interfaces | `registry/metadata_extractor.py:PflowMetadataExtractor` |

## Interface Documentation Format

Node docstrings are parsed as interface metadata. Use one annotated entry per
line, `#` descriptions, and required/optional/default information in descriptions:

```python
Interface:
- Params: file_path: str  # Path to read (required)
- Params: encoding: str  # File encoding (optional, default: utf-8)
- Writes: shared["content"]: str  # File contents
- Writes: shared["error"]: str  # Failure description
- Actions: default (success), error (failure)
```

Inputs use Params; outputs use Writes. Nested output structures use indented
children under the output entry. The full syntax is in
`architecture/reference/enhanced-interface-format.md`; parsing belongs to
`registry/metadata_extractor.py`, rendered structure/path references to
`registry/context_builder.py:_add_enhanced_structure_display`. Do not maintain a
second rendered-output specification here.

## Execution-state and diagnostic gotchas

- Keep per-execution results out of instance attributes: compiled child nodes can
  be reused across sequential batch items (`runtime/workflow_executor.py`). Pass
  state through prep/exec return values or shared output instead. Engine-assigned
  `self.params` and deliberate infrastructure/cache objects are different from
  per-item results. See `tests/test_nodes/test_node_stateless_invariant.py`.
- Authoritative per-run metadata must replace prior same-node evidence (`=`);
  supplementary evidence can use `setdefault`. Make the choice explicit when
  writing `shared["__warnings__"]`, so node reuse cannot retain a stale signal.
- Never use process-global `redirect_stdout`/`redirect_stderr` inside worker
  threads. A timed-out thread may outlive its caller and corrupt later streams;
  see `python/python_code.py:_execute_code`.
- Use logging for runtime diagnostics, not direct stderr writes. The logging
  filter in `core/output_controller.py` closes partial progress lines; raw
  print/click/sys.stderr writes bypass it and corrupt live progress rendering.
- Agent-facing errors describe the authoring surface (`- prompt:`, `${node.output}`),
  not shared-store or lifecycle internals. Follow `core/CLAUDE.md` →
  “Agent-facing messages speak the authoring surface” and the root exception rule.
