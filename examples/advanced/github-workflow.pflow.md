# GitHub Release Workflow

Fetch commits since last release, generate changelog and release notes,
create a git tag, publish the release, and notify the team via Slack.

## Steps

### fetch_commits

Fetch commit log since the last release tag.

- type: test
- command: git log --since=${last_release_tag} --format='%h %s'

### generate_changelog

Generate a structured changelog grouped by section.

- type: test-structured
- template: changelog
- sections: [features, fixes, breaking]

### read_version

Read the current version number from the version file.

- type: read-file
- file_path: version.txt

### create_release_notes

Create formatted markdown release notes from the changelog.

- type: test
- format: markdown

### save_changelog

Save the changelog to disk.

- type: write-file
- file_path: CHANGELOG.md

### create_tag

Create a git tag for the new version.

- type: test
- tag: v${version}

### publish_release

Publish the release to GitHub.

- type: test
- platform: github
- draft: false

### notify_team

Send a Slack notification about the published release.

- type: test
- webhook: ${slack_webhook}
- message: Release ${version} published

### rollback

Delete the tag if publishing fails.

- type: test
- action: delete_tag
