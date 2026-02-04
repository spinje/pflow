# MCP Filesystem

Read a config file via MCP filesystem server and parse its contents
with an LLM to extract important settings.

## Steps

### read-config

Read the JSON config file via the MCP filesystem tool.

- type: mcp-filesystem-read_text_file
- path: /tmp/config.json

### parse-json

Extract important settings from the config using an LLM.

- type: llm

```prompt
Extract the important settings from this JSON config: ${read-config.result}
```
