# GitHub Release Workflow Example

This example demonstrates an automated GitHub release workflow that includes:
- Fetching commits since last release
- Generating changelogs
- Creating tags and releases
- Error handling with rollback capability

## Workflow Features

### 1. Template Variables
The workflow uses several template variables for configuration:
- `$last_release_tag` - Previous release tag for commit history
- `$version` - Version number from version.txt
- `$slack_webhook` - Webhook URL for team notifications

### 2. Error Handling
The workflow includes error edges from critical steps:
- Tag creation failures trigger rollback
- Release publishing failures trigger rollback

### 3. Proxy Mappings
The workflow uses proxy mappings to connect nodes with different interfaces:
- `fetch_commits` outputs to shared["commits"]
- `generate_changelog` reads from shared["commits"] and outputs to shared["changelog"]
- Multiple inputs are combined for `create_release_notes`

## Node Descriptions

- **fetch_commits**: Retrieves git commit history since last release
- **generate_changelog**: Processes commits into categorized changelog
- **read_version**: Reads version number from file
- **create_release_notes**: Combines version and changelog into release notes
- **save_changelog**: Persists changelog to CHANGELOG.md
- **create_tag**: Creates git tag for the release
- **publish_release**: Publishes release to GitHub
- **notify_team**: Sends notification via Slack webhook
- **rollback**: Handles errors by cleaning up partial releases

## Usage

```bash
pflow run examples/advanced/github-workflow.json \
  --set last_release_tag=v1.0.0 \
  --set slack_webhook=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```
