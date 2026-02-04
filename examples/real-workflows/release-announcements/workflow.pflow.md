# Release Announcements

Generate and post platform-specific release announcements to Slack, Discord, and X.
Uses a generate → critique → improve pipeline with different LLMs for each stage.

## Inputs

### version

Version being released (e.g., 0.6.0).

- type: string
- required: true

### changelog_section

Changelog markdown for this version. Passed directly to the LLM prompts
for accurate announcement generation.

- type: string
- required: true

### project_name

Name of the project for branding in announcements.

- type: string
- required: false
- default: pflow

### project_url

Project URL for links in announcements.

- type: string
- required: false
- default: "https://github.com/spinje/pflow"

### slack_channel

Slack channel to post announcement (e.g., releases).

- type: string
- required: true

### discord_channel_id

Discord channel ID (numeric, e.g., 1458059302022549698).

- type: string
- required: true

### x_output_file

File path to save X/Twitter post for review before manual posting.

- type: string
- required: false
- default: ./x-announcement.txt

## Steps

### generate-drafts

Generate platform-specific announcement drafts using a fast model.
Each platform gets tailored instructions for formatting and voice.

- type: llm
- model: gemini-3-flash-preview

```yaml batch
items:
  - platform: slack
    instructions: "Write a Slack announcement for a software release. Use Slack markdown (*bold*, `code`). Include version number and key changes. Link to the GitHub release: github.com/spinje/pflow/releases/tag/v[VERSION]. No filler commentary or forced jokes - just the facts."
  - platform: x
    instructions: "Write a tweet announcing a software release. Max 280 characters. MUST use line breaks (\\n) between ideas. Format:\n\n[version headline]\n\n[one sentence about key feature]\n\nAsk @grok to read github.com/spinje/pflow/blob/main/releases/v[VERSION]-context.md and explain [feature]\n\nUse actual version number. Pick one compelling feature from changelog for the Grok prompt. No separate GitHub link needed."
  - platform: discord
    instructions: "Write a Discord announcement for a community server. Use Discord markdown (**bold**, `code`). Include version number and key changes. Link to the GitHub release: github.com/spinje/pflow/releases/tag/v[VERSION]. No filler commentary or forced quirky jokes - just the facts, stated plainly."
parallel: true
```

````markdown prompt
You are writing a ${item.platform} announcement for ${project_name} version ${version}.

${item.instructions}

Changelog:
${changelog_section}

Project URL: ${project_url}

VOICE: Write like a tired-but-competent engineer sharing notes. Low-ego, high-signal, no hype. Better rough and real than polished and generic. Avoid: hustle-bro energy, VC-speak, 'game changer' language, inspirational poster vibes, 'building the future' startup tone.

Respond with ONLY the announcement text, no explanations or metadata.
````

### critique-drafts

Review and critique each draft for platform fit using a different model
for diversity of perspective.

- type: llm
- model: gpt-5.2

```yaml batch
items:
  - platform: slack
    draft: ${generate-drafts.results[0].response}
    criteria: "Check: links to GitHub release (github.com/spinje/pflow/releases/tag/v[VERSION]), not just the repo. Version displayed, correct Slack markdown (*bold*), no forced jokes or filler commentary"
  - platform: x
    draft: ${generate-drafts.results[1].response}
    criteria: "Check: under 280 characters, has line breaks between sections (not one long line), includes version, Grok call-to-action starts with 'Ask @grok to read' and has correct URL format, feature is specific, no separate GitHub link"
  - platform: discord
    draft: ${generate-drafts.results[2].response}
    criteria: "Check: links to GitHub release (github.com/spinje/pflow/releases/tag/v[VERSION]), not just the repo. Version displayed, correct Discord markdown (**bold**), no forced jokes or quirky filler"
parallel: true
```

````markdown prompt
Review this ${item.platform} announcement draft for ${project_name} version ${version}.

DRAFT:
---
${item.draft}
---

SOURCE CHANGELOG:
${changelog_section}

Project URL: ${project_url}

Criteria:
${item.criteria}

VOICE CHECK: Should sound like a tired-but-competent engineer sharing notes. Low-ego, high-signal, no hype. Flag if it sounds like: hustle-bro energy, VC-speak, 'game changer' language, inspirational poster vibes, or 'building the future' startup tone.

Think hard about how this could be improved further. Don't just check boxes - really consider what would make someone stop scrolling and read this. Check if the draft accurately represents the changelog.

Format:

STRENGTHS:
- point

ISSUES:
- issue: specific fix

DEEPER IMPROVEMENTS:
- what would make this genuinely better, not just correct
````

### improve-drafts

Create final polished versions based on critique using the strongest model.

- type: llm
- model: claude-opus-4.5

```yaml batch
items:
  - platform: slack
    draft: ${generate-drafts.results[0].response}
    critique: ${critique-drafts.results[0].response}
  - platform: x
    draft: ${generate-drafts.results[1].response}
    critique: ${critique-drafts.results[1].response}
  - platform: discord
    draft: ${generate-drafts.results[2].response}
    critique: ${critique-drafts.results[2].response}
parallel: true
```

````markdown prompt
Improve this ${item.platform} announcement for ${project_name} version ${version}.

ORIGINAL DRAFT:
${item.draft}

CRITIQUE:
${item.critique}

SOURCE CHANGELOG:
${changelog_section}

Project URL: ${project_url}

VOICE: Write like a tired-but-competent engineer sharing notes. Low-ego, high-signal, no hype. Better rough and real than polished and generic. Avoid: hustle-bro energy, VC-speak, 'game changer' language, inspirational poster vibes, 'building the future' startup tone.

Create the final version. Apply valid suggestions from the critique. Ensure accuracy against the source changelog. Output ONLY the announcement text, nothing else.
````

### post-slack

Post the final Slack announcement to the specified channel.

- type: mcp-composio-slack-SLACK_SEND_MESSAGE
- channel: ${slack_channel}
- markdown_text: ${improve-drafts.results[0].response}

### prepare-discord-body

Prepare Discord message body as escaped JSON for the API call.

- type: shell
- stdin: ${improve-drafts.results[2].response}

```shell command
jq -Rs '{content: .}'
```

### post-discord

Post the final Discord announcement to the specified channel.

- type: mcp-discord-execute_action
- server_name: discord
- category_name: DISCORD_CHANNELS_MESSAGES
- action_name: create_message
- path_params: "{\"channel_id\":\"${discord_channel_id}\"}"
- body_schema: ${prepare-discord-body.stdout}

### save-x-post

Save X/Twitter post to file for manual review before posting.

- type: write-file
- file_path: ${x_output_file}
- content: ${improve-drafts.results[1].response}

### create-summary

Create execution summary with instructions for posting the X announcement.

- type: shell

```shell command
printf '## Release Announcements for ${project_name} v${version}\n\n✓ Posted to Slack: #${slack_channel}\n✓ Posted to Discord: channel ${discord_channel_id}\n✓ X post saved to: ${x_output_file}\n\nTo post to X, run:\npflow registry run mcp-twitter-x-TWITTER_CREATION_OF_A_POST text="$(cat ${x_output_file})"\n'
```

## Outputs

### summary

Summary of announcements posted and X post command.

- source: ${create-summary.stdout}

### slack_post

Final Slack announcement text.

- source: ${improve-drafts.results[0].response}

### discord_post

Final Discord announcement text.

- source: ${improve-drafts.results[2].response}

### x_post

Final X/Twitter announcement text (saved to file for review).

- source: ${improve-drafts.results[1].response}

### x_post_file

Path to saved X post file for manual posting.

- source: ${x_output_file}
