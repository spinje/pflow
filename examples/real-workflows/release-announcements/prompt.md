Generate and post release announcements to Slack, Discord, and X.

The problem: after every release, you need to announce it in multiple places. Each platform has different formatting (Slack markdown, Discord markdown, X character limits). Writing three versions manually is tedious. Copy-pasting leads to mistakes.

Inputs:
- version (required): Version being released, e.g., "0.6.0"
- changelog_section (required): Changelog markdown for this version
- slack_channel (required): Slack channel name to post to
- discord_channel_id (required): Discord channel ID (numeric)
- project_name (optional, default: "pflow"): Project name for announcements
- project_url (optional, default: "github.com/spinje/pflow"): Project URL for links
- x_output_file (optional, default: "./x-announcement.txt"): Where to save X post

Workflow:

1. Generate platform-specific drafts in PARALLEL using gemini-3-flash-preview (fast, good at format):
   - Slack: Use Slack markdown (*bold*, `code`). Link to GitHub RELEASE (github.com/[owner]/[repo]/releases/tag/v[VERSION]), not just the repo.
   - Discord: Use Discord markdown (**bold**, `code`). Link to GitHub RELEASE, not just repo.
   - X/Twitter: Max 280 characters. MUST have line breaks between sections. Format:
     ```
     [project] [version] tagged.

     [one key feature sentence]

     Ask @grok to read github.com/[owner]/[repo]/blob/main/releases/v[VERSION]-context.md and explain [specific feature from changelog]
     ```
     No separate GitHub link needed - the Grok prompt IS the link.

2. Critique each draft in PARALLEL using gpt-5.2 (strong at analysis):
   - Slack: Check links go to /releases/tag/v[VERSION], correct markdown (*bold*), no forced jokes
   - X: Check under 280 chars, has line breaks (not one long line), Grok CTA format is exact, feature is specific
   - Discord: Check links go to /releases/tag/v[VERSION], correct markdown (**bold**), no quirky filler
   - All: Flag voice violations (hype-speak, VC-speak, "game changer" language)
   - All: Suggest deeper improvements, not just checkbox validation

3. Improve each draft in PARALLEL using claude-opus-4.5 (best at nuanced writing):
   - Apply valid suggestions from critique
   - Verify accuracy against source changelog
   - Maintain voice: "tired-but-competent engineer" - low-ego, high-signal, no hype

4. Post to Slack automatically via MCP (mcp-composio-slack)
   - Safe: internal team channel

5. Post to Discord automatically via MCP (mcp-discord)
   - Community server, but controlled environment

6. Save X post to file (NOT auto-posted)
   - Why: X is public, permanent, higher stakes - human should review first
   - Output includes command to post when ready

7. Output summary showing:
   - What was posted where
   - Path to saved X post
   - Command to run for posting X: `pflow registry run mcp-twitter-x-TWITTER_CREATION_OF_A_POST text="$(cat [x_output_file])"`

Voice guidelines (enforced in all three stages):
- Low-ego, high-signal, no hype
- Better rough and real than polished and generic
- Anti-patterns to explicitly avoid: hustle-bro energy, VC-speak, "game changer" language, inspirational poster vibes, "building the future" startup tone

Why three different models:
- Gemini: Fast, cheap, good at following format instructions → drafts
- GPT: Strong analytical capability, finds issues → critique
- Claude: Best at nuanced writing and voice consistency → final polish

End result:
Three platform-appropriate announcements from one changelog input. 9 LLM calls (3 batches × 3 platforms) across 3 providers (Gemini, OpenAI, Anthropic), 2 MCP integrations (Slack, Discord), all orchestrated in one deterministic workflow. X post saved for human review before public posting.
