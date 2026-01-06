# Release Announcements Workflow

Generate and post release announcements to Slack, Discord, and X using a multi-model LLM pipeline.

## What it does

1. **Generate drafts** (Gemini) - Creates platform-specific announcements from your changelog
2. **Critique drafts** (GPT) - Reviews each draft for accuracy, voice, and platform fit
3. **Improve drafts** (Claude) - Produces final versions incorporating critique feedback
4. **Post to Slack** - Auto-posts to your team channel
5. **Post to Discord** - Auto-posts to your community server
6. **Save X post** - Saves to file for review before posting

## Why three models?

Each model has different strengths:
- **Gemini** (draft): Fast, good at following format instructions
- **GPT** (critique): Strong at analysis and finding issues
- **Claude** (final): Best at nuanced writing and voice consistency

The draft→critique→improve loop catches errors a single pass would miss.

## Voice

All outputs follow a "tired-but-competent engineer" voice:
- Low-ego, high-signal
- No hype, no buzzwords
- Facts over filler
- Better rough and real than polished and generic

Anti-patterns explicitly avoided: hustle-bro energy, VC-speak, "game changer" language, inspirational poster vibes.

## Usage

```bash
pflow release-announcements \
  version="0.6.0" \
  changelog_section="- Added multi-model LLM orchestration
- New batch processing with parallel execution
- Discord and Slack integration via MCP" \
  slack_channel="releases" \
  discord_channel_id="1458059302022549698"
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `version` | Yes | - | Version being released (e.g., 0.6.0) |
| `changelog_section` | Yes | - | Changelog markdown for this version |
| `slack_channel` | Yes | - | Slack channel name |
| `discord_channel_id` | Yes | - | Discord channel ID (numeric) |
| `project_name` | No | pflow | Project name |
| `project_url` | No | github.com/spinje/pflow | Project URL |
| `x_output_file` | No | ./x-announcement.txt | Where to save X post |

## Outputs

- **Slack**: Posted automatically, links to GitHub release
- **Discord**: Posted automatically, links to GitHub release
- **X**: Saved to file with Grok call-to-action for AI-assisted Q&A

### X Post Format

```
pflow 0.6.0 tagged.

Multi-model orchestration: Gemini → GPT → Claude in one run.

Ask @grok to read github.com/spinje/pflow/blob/main/releases/v0.6.0-context.md and explain [feature]
```

The Grok prompt lets readers ask X's AI about specific features using the release context file.

## Prerequisites

MCP servers configured:
- `mcp-composio-slack` - Slack integration
- `mcp-discord` - Discord integration
- `mcp-twitter-x` - X/Twitter integration (for manual posting)

## Posting to X

The workflow saves the X post to a file for review. To post:

```bash
pflow registry run mcp-twitter-x-TWITTER_CREATION_OF_A_POST text="$(cat ./x-announcement.txt)"
```

Or have your AI agent offer to post after reviewing the content.

## Cost

~9 LLM calls per run:
- 3× Gemini (draft generation)
- 3× GPT (critique)
- 3× Claude (final improvement)

Estimated: $0.10-0.30 per run depending on changelog length.

---

## Future Enhancements

### Character limit enforcement
X posts sometimes exceed 280 characters. Could add stricter enforcement in critique criteria or a validation step that loops until under limit.

### Platform-specific context files
Currently all platforms reference the same context file. Could generate platform-appropriate context (e.g., shorter for X, more technical for Discord).

### Configurable voice profiles
The "tired engineer" voice is hardcoded. Could make voice configurable via input parameter with presets (casual, formal, technical, marketing).

### Draft preview mode
Add option to output drafts without posting, for review before committing to social media.

### Retry on critique failure
If critique identifies major issues, could loop back to generation instead of proceeding to improve step.

### Multi-language support
Generate announcements in multiple languages for international communities.

### Image/media attachments
Support attaching release graphics or screenshots to Discord/Slack posts.

### Scheduled posting
Integration with platform scheduling APIs to post at optimal times.
