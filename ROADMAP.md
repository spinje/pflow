# Roadmap

pflow's direction and priorities.

## Current status

See [Changelog](https://pflow.run/changelog) for release history.

Where pflow is today:

- ✅ Core workflow engine built on PocketFlow
- ✅ Node system — file, llm, http, shell, claude-code, and MCP bridge
- ✅ AI agent integration via CLI and MCP server
- ✅ Intelligent discovery — find nodes and workflows by describing what you need
- ✅ Template variables — connect node outputs to inputs
- ✅ Workflow validation with actionable error messages
- ✅ Execution traces for debugging
- ✅ Settings management — API keys, node filtering
- 🚧 Documentation
- ⏳ PyPI publication

## Now

**Getting pflow into users' hands**

Current focus is preparing for public release:

- Completing user documentation at [pflow.run](https://pflow.run)
- Publishing to PyPI for easy installation (`pip install pflow-cli`)
- Ensuring a smooth first-run experience

## Next

**Better model support**

Making pflow work seamlessly with more LLMs:

- Show available models based on configured API keys
- Unified model configuration through the `llm` library
- Support for additional providers beyond Anthropic and OpenAI

**Proving the value**

- Benchmark pflow's efficiency using MCPMark evaluation
- Quantify token savings and latency improvements

## Later

**More powerful workflows**

Expanding what workflows can express:

- Conditional branching — if/else logic in workflows
- Parallel execution — run independent nodes concurrently
- Nested workflow support in the planner

**Better output control**

- Structured output from LLM nodes (JSON schemas)
- Export workflows to standalone Python code
- Execution preview before running

**Safer execution**

- Sandbox runtime for shell commands
- Granular permission boundaries

**Workflows as products**

- Export workflows as self-hosted MCP server packages
- Share automation as installable tools

## Vision *(exploratory)*

**pflow as a platform**

Long-term ideas we're exploring:

- Discover and install MCP servers automatically
- Community registry for workflows and MCP servers
- Cloud execution for team use cases
- Workflows exposed as remote HTTP services

These are directions we find interesting, not commitments.

## Get involved

- 💬 [Discussions](https://github.com/pflow-dev/pflow/discussions) — ideas and feature requests
- 🐛 [Issues](https://github.com/pflow-dev/pflow/issues) — bug reports
- 📖 [Documentation](https://docs.pflow.run) — guides and reference

---

*Last updated: December 2025*

*This reflects current priorities. Feedback shapes what comes next.*
