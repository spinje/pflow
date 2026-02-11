<table>
  <tr>
    <td><img src="assets/logo.png" alt="pflow" width="120"></td>
    <td>
      <h1>pflow</h1>
      <p>
        <a href="LICENSE"><img src="https://img.shields.io/badge/License-FSL--1.1--ALv2-blue.svg" alt="License"></a>
        <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"></a>
        <a href="https://github.com/spinje/pflow/actions/workflows/main.yml"><img src="https://github.com/spinje/pflow/actions/workflows/main.yml/badge.svg" alt="CI"></a>
        <a href="https://docs.pflow.run"><img src="https://img.shields.io/badge/docs-docs.pflow.run-blue" alt="Docs"></a>
      </p>
    </td>
  </tr>
</table>

pflow helps your agent build workflows it can reuse. It composes pre-built nodes — LLM calls, shell commands, HTTP requests, MCP tools — into a `.pflow.md` file. Save it, and it becomes a command that runs the same process every time.

Saved workflows can be published as Skills with `pflow skill save`, making them available across Claude Code, Cursor, and other platforms.

![pflow demo](assets/demo.gif)

## What a workflow looks like

I use pflow for my own releases. This workflow analyzes git commits since the last tag, classifies each one with an LLM (70 concurrent calls), and generates a CHANGELOG.md entry, a Mintlify docs update, and a release context file. It runs in about a minute.

```bash
pflow generate-changelog since_tag=v0.5.0
```

The whole thing is a `.pflow.md` file — markdown that renders as documentation on GitHub and executes as a CLI command. Here are a few steps from the [full workflow](examples/real-workflows/generate-changelog/workflow.pflow.md):

````markdown
### get-latest-tag

Detect the most recent git tag to use as the changelog baseline.

- type: shell

```shell command
git describe --tags --abbrev=0 2>/dev/null || echo 'v0.0.0'
```

### resolve-tag

Pick the starting tag: either user-provided or auto-detected.

- type: code
- inputs:
    since_tag: ${since_tag}
    latest_tag: ${get-latest-tag.stdout}

```python code
since_tag: str
latest_tag: str

result: str = since_tag.strip() if since_tag.strip() else latest_tag.strip()
```

### analyze-commits

Classify each commit as user-facing or internal. Runs in parallel.

- type: llm

```yaml batch
items: ${get-commits-enriched.result}
parallel: true
max_concurrent: 70
```

### notify-slack

Post the release summary to Slack.

- type: mcp-composio-slack-SLACK_SEND_MESSAGE
- channel: ${slack_channel}
- markdown_text: ${create-summary.result}
````

Data flows between steps through template variables — `${get-latest-tag.stdout}` feeds one step's output into the next.

Four node types in one workflow: a shell command, inline Python, 70 parallel LLM calls, and a Slack message via MCP in three lines.

More examples: [release announcements](examples/real-workflows/release-announcements/), [vision scraper](examples/real-workflows/vision-scraper/)

Once saved, this runs the same way every time — same steps, same order, same data flow between them.

## How your agent uses pflow

pflow has 8 node types: `shell`, `code` (Python), `http`, file operations, `llm` calls, `mcp` tools, and a `claude-code` node for delegating to another agent.

Before anything runs, validation catches errors — wrong template references, missing inputs, type mismatches. Your agent handles the whole lifecycle:

```bash
# Check if a workflow already exists
pflow workflow discover "generate changelog from git history"

# Nothing fits — get a step-by-step creation guide
pflow instructions create

# Find building blocks for the workflow
pflow registry discover "analyze git commits, classify with llm, post to slack"

# Build, run, iterate (validation runs automatically)
pflow workflow.pflow.md since_tag=v0.5.0

# Save to your library
pflow workflow save ./workflow.pflow.md --name generate-changelog

# Publish frequently-used workflows as Skills
pflow skill save generate-changelog
```

Workflows can call other workflows — the changelog you build today becomes a building block for a release workflow tomorrow.

```bash
# JSON output works with standard tools
pflow --output-format json generate-changelog \
  | jq -r '.result.version' | xargs git tag

# Chain workflows together
pflow -p generate-changelog | pflow -p release-announcements

# Schedule workflows like any command
0 9 * * MON pflow generate-changelog
```

## Built for agents

When something goes wrong, pflow tells the agent what to do:

```
✗ Static validation failed:
  • Node 'fetch-data' (type: http) does not output 'email'

Available outputs from 'fetch-data':
  ✓ ${fetch-data.response} (dict|str)
  ✓ ${fetch-data.status_code} (int)
  ✓ ${fetch-data.response_headers} (dict)
  ✓ ${fetch-data.response_time} (float)
  ✓ ${fetch-data.error} (str)

Tip: Try using ${fetch-data.response} instead
```

The agent sees what went wrong, sees every available output with its type, and gets a suggested fix. No stack traces, no guessing. ([source](src/pflow/runtime/template_validator.py))

I develop pflow by having agents build workflows and identifying where they get stuck. These error messages are a direct result.

pflow is CLI-first because agents in Claude Code, Cursor, and similar tools always have bash. No MCP configuration needed — just run commands. (MCP server mode is available too if you need it.)

## Honest scope

pflow is for workflows where you know the steps — tasks your agent figured out once and you want to capture. If you're exploring or need your agent to adapt on the fly, let it. pflow captures the path after you've found it.

## Getting started

Requires Python 3.10+, macOS or Linux (Windows is untested). See the [quickstart](https://docs.pflow.run/quickstart) for API key setup and detailed configuration.

```bash
# Recommended
uv tool install pflow-cli

# Or with pipx
pipx install pflow-cli

# Or with pip
pip install pflow-cli

# Verify
pflow --version
```

Tell your agent to run `pflow instructions usage` — it gets everything it needs to discover, run, and build workflows.

Or configure pflow as an MCP server for environments without terminal access:

```json
{
  "mcpServers": {
    "pflow": {
      "command": "pflow",
      "args": ["mcp", "serve"]
    }
  }
}
```

Full documentation at [docs.pflow.run](https://docs.pflow.run).

## I want your feedback

I've been building pflow since mid-2025. The thesis I'm testing: agents are more effective when they can compose known building blocks into reusable workflows, rather than writing code from scratch each time.

I might be wrong. Try it and tell me:

- Is the `.pflow.md` format helpful, or would you rather just read/write Python?
- After trying it — would you rather just let your agent handle the whole task from scratch each time? Write scripts? Use some other framework?
- What's the first workflow you'd build?

Open a [discussion](https://github.com/spinje/pflow/discussions) or file an [issue](https://github.com/spinje/pflow/issues).

Or get started → [Get started](https://docs.pflow.run/quickstart)

## License

[Functional Source License (FSL-1.1-ALv2)](LICENSE) — free for all use except offering pflow as a competing cloud hosted service. Becomes Apache-2.0 after 2 years.
