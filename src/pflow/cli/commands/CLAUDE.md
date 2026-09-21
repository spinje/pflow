# CLI Commands

Commands are registered in `../main.py` with `cli.add_command`. Most filenames
match their command; these are the less obvious ownership boundaries:

| Concern | Owner |
|---|---|
| Default workflow execution | Hidden `run.py`; delegates to `WorkflowRunner` |
| Resume dispatch and paused-run listing | `resume.py:ResumeGroup`; refusal preflight in `execution/resume_preflight.py` |
| Single-node probe | `probe.py` is Click-only; `_probe_impl.py:execute_single_node` executes |
| Revisit probe output without executing | `read_fields.py`, `core/execution_cache.py` |
| Publish/list/remove skills | `skills.py` implements singular `pflow skill`; `core/workflow/skill_service.py` owns behavior |
| MCP client configuration/tools | `mcp.py`; `mcp serve` instead exposes `mcp_server/` |
| Workflow save and discovery | `save.py` → `core/workflow/save_service.py`; `find.py` → `core/workflow/discovery.py` |
| Guide composition | `guide.py` → `pflow.guide` |
| Cache analysis | `analyze_cache.py` → `core/prompt_cache_analysis/` |
| Optional web UI | `ui.py` lazily loads the `[ui]` backend; see `src/pflow/ui/CLAUDE.md` |

`resume.py` imports `run.py:execute_json_workflow` locally when dispatching to avoid
a startup import cycle. Resume refusal decisions are shared with the UI through
`preflight_resume`; interactive confirmation stays in the CLI.

`find.py` and `mcp.py`'s find command share
`cli/find_errors.py:handle_discovery_error`. Execution-start MCP auto-sync is in
`cli/mcp_sync.py`, not the MCP command handler.

## Model defaults

Workflow LLM defaults are injected by `runtime/compilation/compiler.py` through
`core/llm_config.py:get_default_workflow_model`. Discovery/filtering instead use
`get_model_for_feature` in that module. Agent nodes have separate backend defaults
in `nodes/agent/agent_node.py:prep`. Change those owners rather than duplicating
resolution chains or concrete model names in commands.
