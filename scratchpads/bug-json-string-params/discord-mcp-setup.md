# Discord MCP Setup for Bug Reproduction

## Overview

The Discord MCP uses a **generic execute_action pattern** rather than direct tool names. This means parameters like `path_params` and `body_schema` are JSON-encoded strings, not objects.

## Discord MCP Configuration

The Discord MCP should already be configured in `~/.pflow/mcp-servers.json`. If not, you'll need to set it up with appropriate Discord bot credentials.

## Discord Server/Channel Information

For testing, use the "pflow" Discord server:

| Resource | ID |
|----------|-----|
| Guild (server) | `1458059301472960659` |
| #general channel | `1458059302022549698` |

## How Discord MCP Works

Unlike simple MCPs (like Slack), Discord uses a multi-step pattern:

1. **Discover categories**: `mcp-discord-discover_server_categories_or_actions`
2. **Get action details**: `mcp-discord-get_action_details`
3. **Execute action**: `mcp-discord-execute_action`

The `execute_action` tool expects JSON-encoded strings for complex parameters:

```
path_params: str  → '{"channel_id": "123456789"}'
body_schema: str  → '{"content": "Hello world"}'
query_params: str → '{"limit": "10"}'
```

## Testing Discord MCP Manually

### List Guilds (No JSON params needed)

```bash
uv run pflow registry run mcp-discord-execute_action \
  server_name=discord \
  category_name=DISCORD_USERS_GUILDS \
  action_name=list_my_guilds
```

### List Channels (Requires JSON param - demonstrates bug)

```bash
# This FAILS (bug)
uv run pflow registry run mcp-discord-execute_action \
  server_name=discord \
  category_name=DISCORD_GUILDS_CHANNELS \
  action_name=list_guild_channels \
  path_params='{"guild_id":"1458059301472960659"}'

# This WORKS (hacky workaround - leading space)
uv run pflow registry run mcp-discord-execute_action \
  server_name=discord \
  category_name=DISCORD_GUILDS_CHANNELS \
  action_name=list_guild_channels \
  'path_params= {"guild_id":"1458059301472960659"}'
```

### Post Message (Requires two JSON params)

```bash
# This FAILS (bug)
uv run pflow registry run mcp-discord-execute_action \
  server_name=discord \
  category_name=DISCORD_CHANNELS_MESSAGES \
  action_name=create_message \
  path_params='{"channel_id":"1458059302022549698"}' \
  body_schema='{"content":"test message"}'

# This WORKS (hacky workaround)
uv run pflow registry run mcp-discord-execute_action \
  server_name=discord \
  category_name=DISCORD_CHANNELS_MESSAGES \
  action_name=create_message \
  'path_params= {"channel_id":"1458059302022549698"}' \
  'body_schema= {"content":"test message"}'
```

## Why Discord MCP is a Good Test Case

1. **Clear type mismatch**: Param type is `str` but value should be JSON
2. **Multiple affected params**: `path_params`, `body_schema`, `query_params`
3. **Real-world MCP**: Not a contrived test case
4. **Easy to verify**: Messages appear in Discord immediately

## Checking the Registry Schema

```bash
uv run python -c "
from pflow.registry import Registry
r = Registry()
nodes = r.load()
node = nodes.get('mcp-discord-execute_action')
print('=== Discord execute_action params ===')
for p in node['interface']['params']:
    print(f\"{p['key']}: {p['type']} - {p.get('description', '')[:50]}\")"
```

Expected output:
```
=== Discord execute_action params ===
server_name: str - The name of the server
category_name: str - The name of the category to execute the action
action_name: str - The name of the action/operation to execute
path_params: str - JSON string containing path parameters for the
query_params: str - JSON string containing query parameters for the
body_schema: str - JSON string containing request body for actions
include_output_fields: list - Optional but strongly recommended when you know
maximum_output_characters: int - Optional: Maximum number of characters to retu
```

Note: `path_params`, `query_params`, and `body_schema` all have type `str` but expect JSON content.
