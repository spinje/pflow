# Release Notes Assistant

A small pipeline that turns raw git commits into human-readable release notes, then
branches on whether the release is major or minor. Built to show off pflow's agent
voice narration — point at a node and hear it explained.

## Steps

### gather-commits

Collect the recent commit messages — the raw material for the release notes.

- type: shell

```shell command
git log --oneline -15
```

### draft-notes

Ask an LLM to turn the raw commits into concise, user-facing release notes.

- type: llm

```text prompt
Turn these git commits into concise, user-facing release notes:

${gather-commits.stdout}
```

### classify-release

Inspect the drafted notes and decide: is this a major release or a minor one?

- type: code
- inputs: { notes: "${draft-notes.response}" }

```python code
notes: str

if "BREAKING" in notes.upper():
    next: str = "announce-major"
else:
    next: str = "announce-minor"
result: str = next
```

### announce-major

Publish a prominent announcement for a major release.

- type: shell
- next: end

```shell command
echo "MAJOR release published — read the notes!"
```

### announce-minor

Publish a quiet note for a minor release.

- type: shell
- next: end

```shell command
echo "Minor release published."
```
