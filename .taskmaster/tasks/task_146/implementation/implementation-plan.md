# Task 146: Rich Mermaid Visualization — Implementation Plan

## Context

Task 145 shipped a mermaid generator (`src/pflow/core/workflow/mermaid.py`, 163 lines) that produces topologically correct but visually flat diagrams. Testing against a complex real-world workflow (lyrics-generator: 15 steps, 7 sub-workflows, batch ops at every level) revealed 14 issues where the visualization erases critical architectural information — most importantly, all batch/parallel semantics are invisible.

**Task spec**: `.taskmaster/tasks/task_146/task-146.md`
**Test workflow**: `/Users/andfal/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md`
**Current output**: `scratchpads/mermaid-improvements/lyrics-generator.mmd`

## Files to Modify

| File | Action |
|------|--------|
| `src/pflow/core/workflow/mermaid.py` | **REWRITE** — main implementation (163→~450 lines) |
| `src/pflow/cli/commands/visualize.py` | **MODIFY** — add `--descriptions` flag (2 lines added) |
| `tests/test_core/test_mermaid.py` | **MODIFY** — add ~15 new tests, update existing assertions |
| `tests/test_cli/test_visualize.py` | **MODIFY** — add 1 test for `--descriptions` flag |

## Implementation — Phase by Phase

Each phase is independently testable. Run `uv run pytest tests/test_core/test_mermaid.py -v` after each phase. Run `make check` and `make test` after all phases.

---

### Phase 1: Edge Preprocessing

Add two new functions BEFORE `_render_workflow`. These are pure functions with no side effects.

#### Function: `_deduplicate_edges`

```python
def _deduplicate_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove redundant edges.

    When a (from, to) pair has BOTH a document-order edge (no ``action`` key)
    and a named action edge (action is not None/default/error), suppress:
    - The document-order edge (no action key)
    - Any ``action: "default"`` edge for the same pair

    This prevents visual duplication like:
        classify --> fetch-youtube           (document-order)
        classify -->|fetch-youtube| fetch-youtube  (named action)
    """
```

**Logic**:
1. Build a set of `(from, to)` pairs that have at least one named action edge (an edge where `"action" in edge` AND `edge["action"] not in ("default", "error")`)
2. Filter edges: keep an edge if:
   - It has a named action (action exists, not "default", not "error"), OR
   - It's an error edge (`action == "error"`), OR
   - Its `(from, to)` pair is NOT in the named-pairs set (no named duplicate exists)

**Key distinction**: Document-order edges have **no `action` key at all** in the dict (not `action: None`). Explicit edges always have an `action` key. Check with `"action" in edge`, NOT `edge.get("action")`.

#### Function: `_detect_decision_nodes`

```python
def _detect_decision_nodes(edges: list[dict[str, Any]]) -> set[str]:
    """Return node IDs that are decision/routing points.

    A decision node has >=2 outgoing edges with distinct named actions
    (excluding "error" and "default" actions, and excluding document-order
    edges with no action key).
    """
```

**Logic**:
1. For each edge where `"action" in edge` and `action not in ("error", "default")`: collect the `(from_id, action)` pairs
2. Group by `from_id`, count distinct actions
3. Return set of `from_id` where count >= 2

#### Tests for Phase 1

Add to `tests/test_core/test_mermaid.py`:

**`test_duplicate_edge_suppression`**: IR with edges `[{"from":"a","to":"b"}, {"from":"a","to":"b","action":"go"}]`. Assert only the named edge `-->|go|` appears, not a duplicate plain `-->`.

**`test_decision_node_diamond_shape`**: IR with node `check` having edges `{"from":"check","to":"x","action":"yes"}` and `{"from":"check","to":"y","action":"no"}`. Assert `check` renders with diamond shape syntax `{` and `}`.

**`test_error_edge_not_decision`**: Node with one named action + one error edge. Should NOT be a decision (only 1 non-error named action). Assert no diamond shape.

---

### Phase 2: Node Shape Mapping

Add helper functions for type-based shape selection and label formatting.

#### Function: `_get_node_shape`

```python
_SHAPE_MAP: dict[str, tuple[str, str, str]] = {
    # node_type: (open_bracket, close_bracket, css_class)
    "llm": ("([", "])", "llm"),
    "shell": ("[[", "]]", "shell"),
    "write-file": ("[(", ")]", "writefile"),
    "code": ("[", "]", "code"),
    "workflow": ("(", ")", "workflow"),
}

def _get_node_shape(node_type: str, is_decision: bool) -> tuple[str, str, str]:
    """Return (open_bracket, close_bracket, css_class) for a node's Mermaid shape.

    Decision nodes always get diamond shape regardless of type.
    MCP nodes (type starts with "mcp") get hexagon shape.
    """
```

**Logic**:
- If `is_decision`: return `("{", "}", "decision")`
- If `node_type.startswith("mcp")`: return `("{{", "}}", "mcp")`
- Otherwise: look up in `_SHAPE_MAP`, default to `("[", "]", "code")`

**Output examples**:
- `classify (code)` + is_decision → `classify{"classify (code)"}:::decision`
- `write-lyrics (llm)` → `write-lyrics(["write-lyrics (llm)"]):::llm`
- `fetch-youtube (shell)` → `fetch-youtube[["fetch-youtube (shell)"]]:::shell`
- `fetch-youtube-mcp (mcp:...)` → `fetch-youtube-mcp{{"..."}}:::mcp`

#### Function: `_format_node_type`

```python
def _format_node_type(node_type: str) -> str:
    """Format node type for display in labels.

    MCP types are long (``mcp-klavis-youtube-get_youtube_video_transcript``).
    Format as ``mcp:<br/>klavis-youtube-get_youtube_video_transcript`` for readability.
    """
```

**Logic**: If `node_type.startswith("mcp-")`: return `f"mcp:<br/>{node_type[4:]}"`. Otherwise return unchanged.

#### Function: `_format_label`

```python
def _format_label(
    node_id: str, node_type: str, descriptions: bool, purpose: str, batch_suffix: str = ""
) -> str:
    """Format the full display label for a node."""
```

**Logic**:
1. `display_type = _format_node_type(node_type)`
2. `label = f"{node_id} ({display_type}){batch_suffix}"`
3. If `descriptions` and `purpose`: append `f"<br/>{_first_sentence(purpose)}"`
4. Return `_escape_label(label)`

#### Function: `_first_sentence`

```python
def _first_sentence(text: str) -> str:
    """Extract first sentence from a purpose string, stripped of markdown formatting."""
```

**Logic**:
1. Strip `**bold**` → `bold` and `*italic*` → `italic` with `re.sub`
2. Find first sentence ending with `.`, `!`, or `?` (use `re.match(r'([^.!?]+[.!?])', clean)`)
3. Truncate to 80 chars
4. If no sentence boundary found, return first 80 chars

#### Function: `_render_classdefs`

```python
def _render_classdefs(lines: list[str]) -> None:
    """Add classDef color declarations at the top of the graph."""
```

Append these exact lines (one per `lines.append`):
```
    classDef code fill:#D5E8D4,stroke:#82B366
    classDef llm fill:#E8D5F5,stroke:#7B2D8E
    classDef shell fill:#DAE8FC,stroke:#6C8EBF
    classDef mcp fill:#FFE6CC,stroke:#D79B00
    classDef writefile fill:#F8CECC,stroke:#B85450
    classDef workflow fill:#FFF2CC,stroke:#D6B656
    classDef decision fill:#F5F5F5,stroke:#666666
    classDef input fill:#F5F5F5,stroke:#666666,stroke-dasharray:5 5
```

#### Modify `_render_workflow`: node rendering

Change the node declaration from:
```python
lines.append(f'{indent}{mermaid_id}["{label}"]')
```
To:
```python
is_decision = node_id in decision_nodes
shape_open, shape_close, css_class = _get_node_shape(node_type, is_decision)
label = _format_label(node_id, node_type, descriptions, purpose)
lines.append(f'{indent}{mermaid_id}{shape_open}"{label}"{shape_close}:::{css_class}')
```

And change the subgraph label from:
```python
label = _escape_label(f"{node_id} ({node_type})")
lines.append(f'{indent}subgraph {mermaid_id} ["{label}"]')
```
To use `_escape_label` on just the subgraph label string (shapes don't apply to subgraphs).

#### Tests for Phase 2

**`test_llm_node_stadium_shape`**: LLM node renders with `([` and `])` brackets.

**`test_shell_node_subroutine_shape`**: Shell node renders with `[[` and `]]`.

**`test_mcp_node_hexagon_shape`**: MCP node renders with `{{` and `}}`.

**`test_mcp_type_line_break`**: MCP node type `mcp-server-tool` renders with `mcp:<br/>server-tool` in the label.

**`test_code_node_default_rectangle`**: Code node renders with `[` and `]`.

**`test_write_file_cylinder_shape`**: `write-file` node renders with `[(` and `)]`.

**`test_classdefs_present`**: Output contains `classDef llm`, `classDef code`, etc.

Update ALL existing tests: the shape syntax changes mean existing assertions like `'a["a (shell)"]'` now become `'a[["a (shell)"]]:::shell'`. Go through every existing test and update the expected node declaration format.

---

### Phase 3: Batch Rendering

This is the most complex phase. Add batch detection and rendering logic.

#### Function: `_get_item_label`

```python
_LABEL_KEYS = ("name", "label", "focus", "lens")
_SKIP_KEYS = ("workflow", "prompt", "command", "model")

def _get_item_label(item: dict[str, Any], index: int) -> str:
    """Extract a meaningful short label from a batch item dict."""
```

**Logic**:
1. If not a dict: return `f"#{index + 1}"`
2. Try keys in `_LABEL_KEYS` order — return first that exists and is a string
3. Fallback: iterate item keys, return first string value ≤30 chars not in `_SKIP_KEYS`
4. Final fallback: return `f"#{index + 1}"`

#### Function: `_render_batch_inline`

```python
def _render_batch_inline(
    node: dict[str, Any],
    items: list[Any],
    is_parallel: bool,
    lines: list[str],
    indent: str,
    prefix: str,
    node_type: str,
    descriptions: bool,
    fork_join_map: dict[str, list[str]],
) -> None:
    """Render a batch node with inline items as fork/join or 2+ellipsis subgraph.

    - ≤4 items: show ALL items by name (fork/join pattern)
    - >4 items: show first 2 items + ellipsis node with count

    Populates ``fork_join_map`` so edge rendering can fan-out/fan-in.
    """
```

**Logic**:
1. Extract node_id from `node["id"]`
2. Compute mermaid_id: `_to_mermaid_id(prefix + node_id)`
3. Determine render items: all if `len(items) <= 4`, else first 2
4. Compute subgraph label:
   - parallel: `f"{node_id} (parallel ×{len(items)})"`
   - not parallel: `f"{node_id} (×{len(items)})"`
5. Open subgraph: `f'{indent}subgraph {mermaid_id} ["{_escape_label(subgraph_label)}"]'`
6. Inner indent = `indent + "    "`
7. For each render item:
   - `item_label = _get_item_label(item, i)`
   - `item_mermaid_id = _to_mermaid_id(prefix + node_id + "__" + item_label)`
   - Get shape from `_get_node_shape(node_type, False)` (use PARENT node's type)
   - Display label: `_escape_label(f"{item_label} ({_format_node_type(node_type)})")`
   - Append: `f'{inner_indent}{item_mermaid_id}{open}"{display_label}"{close}:::{css}'`
   - Collect item_mermaid_id in list
8. If `len(items) > 4`: add ellipsis node:
   - `dots_id = _to_mermaid_id(prefix + node_id + "__dots")`
   - `f'{inner_indent}{dots_id}["⋯ ×{len(items)}"]'`
   - Append dots_id to the collected list
9. Close subgraph: `f"{indent}end"`
10. Store in fork_join_map: `fork_join_map[mermaid_id] = collected_item_ids`

#### Modify `_render_workflow`: batch handling in node loop

In the node iteration loop, BEFORE the sub-workflow expansion check, add batch detection:

```python
batch = node.get("batch")
purpose = node.get("purpose", "")

if batch:
    items = batch.get("items")
    is_parallel = batch.get("parallel", False)

    if isinstance(items, list):
        # Inline items: fork/join rendering (replaces single node)
        _render_batch_inline(node, items, is_parallel, lines, indent, prefix,
                             node_type, descriptions, fork_join_map)
        continue
    else:
        # Dynamic batch: will add ×N to label or subgraph label
        batch_suffix = " ×N" if not is_parallel else ""
        parallel_prefix = "parallel " if is_parallel else ""
        dynamic_batch_label = f" ({parallel_prefix}×N)"
```

For dynamic batch + workflow expansion: modify the subgraph label to include batch info:
```python
if batch and isinstance(batch.get("items"), str):
    subgraph_label = f"{node_id}{dynamic_batch_label}"
else:
    subgraph_label = f"{node_id} ({node_type})"
```

For dynamic batch + opaque node: modify the label:
```python
if batch and isinstance(batch.get("items"), str):
    label = _format_label(node_id, node_type, descriptions, purpose, dynamic_batch_label)
else:
    label = _format_label(node_id, node_type, descriptions, purpose)
```

#### Modify `_render_workflow`: edge rerouting

In the edge rendering section, add fork/join rerouting:

```python
for edge in deduped_edges:
    from_id = _to_mermaid_id(prefix + edge["from"])
    to_id = _to_mermaid_id(prefix + edge["to"])
    action = edge.get("action")

    # Determine arrow style
    if action == "error":
        arrow = " -.->|error| "
    elif "action" in edge and action not in (None, "default"):
        arrow = f" -->|{_escape_label(action)}| "
    else:
        arrow = " --> "

    # Fan-out/fan-in through fork_join_map
    from_ids = fork_join_map.get(from_id, [from_id])
    to_ids = fork_join_map.get(to_id, [to_id])

    for fid in from_ids:
        for tid in to_ids:
            lines.append(f"{indent}{fid}{arrow}{tid}")
```

#### Tests for Phase 3

**`test_batch_inline_small_fork_join`**: Node with `batch: {items: [{focus: "a"}, {focus: "b"}, {focus: "c"}], parallel: true}`. Assert: subgraph with label containing "parallel ×3", three item nodes named "a", "b", "c", NO standalone node for the batch node ID.

**`test_batch_inline_large_ellipsis`**: Node with 6 inline items. Assert: subgraph with "×6", only 2 item nodes + ellipsis node "⋯ ×6".

**`test_batch_dynamic_label`**: Node with `batch: {items: "${ref}", parallel: true}`. Assert: node label contains "×N".

**`test_batch_fork_join_edge_rerouting`**: Three-node pipeline `a → batch_node → c` where batch_node has 2 inline items. Assert: edges `a --> item1`, `a --> item2`, `item1 --> c`, `item2 --> c`. No edge to/from the original batch node ID.

**`test_batch_workflow_dynamic_subgraph_label`**: Workflow node with dynamic batch that expands. Assert subgraph label contains "parallel ×N", internal nodes still rendered.

**`test_item_label_extraction`**: Test `_get_item_label` with dicts containing `focus`, `lens`, `name`, and fallback cases.

---

### Phase 4: Terminal End Nodes

#### Function: `_find_terminal_nodes`

```python
def _find_terminal_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> set[str]:
    """Find nodes with no non-error outgoing edges.

    A node with ``- next: end`` has zero outgoing edges in the IR.
    A node with only an error edge (``on-error``) but ``next: end``
    has no non-error outgoing edges and is terminal for its success path.
    """
```

**Logic**:
1. Build set of node IDs that have at least one non-error outgoing edge: `{e["from"] for e in edges if e.get("action") != "error"}`
2. Return `{n["id"] for n in nodes if n["id"] not in that_set}`

#### Modify `_render_workflow`: add end nodes

After rendering all nodes, before rendering edges:

```python
# End nodes: only for workflows with decision points
terminals: set[str] = set()
if decision_nodes:
    terminals = _find_terminal_nodes(nodes, edges)
    if terminals:
        end_id = f"{prefix}pflow_end"
        lines.append(f'{indent}{end_id}(("end"))')
```

After rendering all regular edges, add end-node edges:

```python
if terminals:
    end_id = f"{prefix}pflow_end"
    for t in sorted(terminals):
        t_mermaid = _to_mermaid_id(prefix + t)
        # If this terminal is a fork/join node, connect items to end
        t_ids = fork_join_map.get(t_mermaid, [t_mermaid])
        for tid in t_ids:
            lines.append(f"{indent}{tid} --> {end_id}")
```

#### Tests for Phase 4

**`test_end_node_in_branching_workflow`**: IR with decision node (2+ named action edges) and terminal nodes (no outgoing edges). Assert: `(("end"))` node present, terminal nodes connected to it.

**`test_no_end_node_in_linear_pipeline`**: Simple `a → b → c` pipeline with no decision nodes. Assert: no `(("end"))` in output.

**`test_error_only_node_is_terminal`**: Node with only an error edge outgoing. Assert: connected to end node (it's terminal for the success path).

---

### Phase 5: Input Nodes

#### Function: `_render_inputs`

```python
def _render_inputs(ir: dict[str, Any], lines: list[str]) -> None:
    """Render top-level workflow inputs as parallelogram nodes."""
```

**Logic**:
1. Get `inputs = ir.get("inputs", {})`
2. If empty, return
3. Get `start_node = ir.get("start_node") or ir["nodes"][0]["id"]` (first node)
4. For each input `(name, config)`:
   - `input_type = config.get("type", "")`
   - `required = config.get("required", False)`
   - `req_str = ", required" if required else ""`
   - `label = _escape_label(f"{name} ({input_type}{req_str})")`
   - `mermaid_id = _to_mermaid_id(f"input_{name}")`
   - Append: `f'    {mermaid_id}[/"{label}"/]:::input'`
5. Connect all inputs to start node:
   - For each input name: `f"    input_{name} --> {_to_mermaid_id(start_node)}"`

**Note**: Always use indent `"    "` (depth 0) since inputs are top-level.

#### Tests for Phase 5

**`test_inputs_rendered_as_parallelogram`**: IR with `inputs: {name: {type: "string", required: true}}`. Assert: parallelogram syntax `[/"name (string, required)"/]` present, connected to first node.

**`test_no_inputs_section_when_empty`**: IR with no `inputs` key. Assert: no `[/` in output.

---

### Phase 6: Legend

#### Function: `_render_legend`

```python
def _render_legend(lines: list[str]) -> None:
    """Add a disconnected legend subgraph showing node type shapes."""
```

Append these exact lines:
```
    subgraph Legend
        legend_code["code"]:::code
        legend_llm(["llm"]):::llm
        legend_shell[["shell"]]:::shell
        legend_mcp{{"mcp"}}:::mcp
        legend_writefile[("write-file")]:::writefile
        legend_workflow("workflow"):::workflow
        legend_decision{"decision"}:::decision
        legend_input[/"input"/]:::input
    end
```

#### Tests for Phase 6

**`test_legend_present`**: Any generated output contains `subgraph Legend` and example nodes for each type.

---

### Phase 7: CLI `--descriptions` Flag

#### Modify `visualize.py`

Add a new click option after the `--output` option:

```python
@click.option(
    "--descriptions",
    is_flag=True,
    default=False,
    help="Add first sentence of node descriptions to labels",
)
```

Update the function signature to include `descriptions: bool`.

Pass `descriptions=descriptions` to the `generate_mermaid()` call.

#### Modify `generate_mermaid` signature

Add `descriptions: bool = False` parameter. Pass it to `_render_workflow`.

#### Modify `_render_workflow` signature

Add `descriptions: bool` parameter. Use it in `_format_label` calls and pass to recursive `_render_workflow` calls.

#### Tests for Phase 7

**`test_descriptions_flag`**: Node with `purpose: "This is the first sentence. And more."`. With `descriptions=True`, assert label contains `<br/>This is the first sentence.`. With `descriptions=False`, assert no `<br/>`.

**CLI test** `test_descriptions_cli_flag` in `test_visualize.py`: Invoke with `--descriptions`, assert output contains `<br/>`.

---

### Phase 8: Back-Edge Test

No code changes needed — back-edges already work. Just add test coverage.

#### Test

**`test_back_edge_renders`**: IR with edge `{"from": "b", "to": "a"}` (back-edge). Assert: the edge `b --> a` appears in output. Assert: no error raised.

---

### Phase 9: Putting It All Together

#### Rewritten `generate_mermaid` function

```python
def generate_mermaid(
    ir: dict[str, Any],
    *,
    resolve_child: Optional[...] = None,
    base_path: Optional[Path] = None,
    max_depth: int = 1,
    direction: str = "LR",
    descriptions: bool = False,
) -> str:
    lines: list[str] = [f"graph {direction}"]
    seen: set[str] = set()

    # Style declarations
    _render_classdefs(lines)

    # Top-level inputs (only at depth 0)
    _render_inputs(ir, lines)

    # Main workflow rendering
    _render_workflow(ir, lines, resolve_child, base_path, max_depth, 0, "", seen, direction, descriptions)

    # Legend
    _render_legend(lines)

    return "\n".join(lines) + "\n"
```

#### Rewritten `_render_workflow` function

Full signature:
```python
def _render_workflow(
    ir: dict[str, Any],
    lines: list[str],
    resolve_child: Optional[...],
    base_path: Optional[Path],
    max_depth: int,
    current_depth: int,
    prefix: str,
    seen: set[str],
    direction: str,
    descriptions: bool,
) -> None:
```

Full flow:
1. Extract `nodes`, `edges` from IR
2. Compute `indent = "    " * (current_depth + 1)`
3. `deduped_edges = _deduplicate_edges(edges)`
4. `decision_nodes = _detect_decision_nodes(edges)`
5. `fork_join_map: dict[str, list[str]] = {}`
6. **Node loop**: for each node:
   a. Extract `node_id`, `node_type`, `batch`, `purpose`
   b. If batch with inline items (list): call `_render_batch_inline`, `continue`
   c. Compute batch suffix for dynamic batch (or empty string)
   d. If workflow type + can expand: subgraph with batch label, recurse, `continue`
   e. Else: render node with shape + css class
7. **End nodes**: if `decision_nodes` exist, find terminals, render `(("end"))` node
8. **Edge loop**: for each deduplicated edge, render with fork/join rerouting
9. **End edges**: connect terminals to end node (through fork_join_map if applicable)

#### Functions preserved unchanged

- `_try_resolve_child` — no changes
- `_to_mermaid_id` — no changes
- `_escape_label` — no changes

---

## Critical Implementation Details

### Edge rerouting cross-product

When both `from_id` and `to_id` are in `fork_join_map`, the rendering produces a cross-product of edges (N×M). This is visually correct for fan-out-to-fan-in but could be noisy. In practice, consecutive fork/join nodes don't occur in real workflows (a fork/join always has a regular node before/after it).

### Batch inline items + sub-workflow expansion are mutually exclusive

When a node has `batch.items` as a list (inline), it renders as fork/join. Sub-workflow expansion does NOT happen for these nodes — the fork/join replaces the node entirely. Sub-workflow expansion only applies to nodes with dynamic batch items (template string) or no batch at all.

### The `fork_join_map` is scoped to `_render_workflow`

Each call to `_render_workflow` (including recursive calls for sub-workflows) has its own `fork_join_map`. Fork/join rerouting only applies to edges within the same workflow scope.

### `re` module import

`_first_sentence` uses `re.sub` and `re.match`. Add `import re` to the top of the file.

### Node ordering in fork/join subgraphs

Items render in the order they appear in `batch.items`. This preserves the author's intended ordering.

### The `purpose` field may not exist

Not all nodes have `purpose` (it comes from prose in the markdown). Always use `node.get("purpose", "")`.

---

## Verification

### Automated

```bash
# After each phase:
uv run pytest tests/test_core/test_mermaid.py -v

# After all phases:
make check   # ruff + mypy + deptry
make test    # full test suite
```

### Manual — lyrics-generator

```bash
uv run pflow visualize /Users/andfal/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md \
  --depth 5 --direction TD \
  -o scratchpads/mermaid-improvements/lyrics-generator-v2.mmd
```

Verify the output shows:
1. Input nodes `sources` and `output_base` at top as parallelograms
2. `fetch-sources` subgraph labeled "(parallel ×N)" with internal decision diamond for `classify`, 4 named branches, error fallback, end node — NO duplicate `classify-->fetch-youtube` edge
3. `analyze-sources` subgraph labeled "(parallel ×N)" with `analyze` inside as a subgraph "(parallel ×6)" showing 2 named specialists + `⋯ ×6`
4. `choose-concepts` expanded with `generate-concepts` showing fork/join for 4 lenses (heart, mind, body, full)
5. `create-songs` subgraph labeled "(parallel ×N)" with:
   - `choose-chorus` nested subgraph expanded
   - `emotional-reviews` as fork/join "(parallel ×3)" with 3 named reviewers
   - `craft-reviews` as fork/join "(parallel ×3)" with 3 named reviewers
6. All LLM nodes as stadium `([...])`, shell as `[[...]]`, MCP as `{{...}}`
7. classDef declarations at top
8. Legend subgraph at bottom
9. `:::css_class` suffixes on all nodes

### Manual — descriptions flag

```bash
uv run pflow visualize /Users/andfal/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md \
  --depth 1 --direction TD --descriptions \
  -o scratchpads/mermaid-improvements/lyrics-generator-v2-descriptions.mmd
```

Verify labels contain `<br/>` with first sentence of node descriptions.
