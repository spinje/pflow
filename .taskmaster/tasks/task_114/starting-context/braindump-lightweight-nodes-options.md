# Braindump: Lightweight Custom Node Creation - Options & Context

## Where I Am

This task emerged from a conversation about code node (Task 104) sandboxing. The user mentioned:

> "In the future we want to have a way for pflow to guide agents to create lightweight nodes (maybe mcp, maybe something else?) so that the functionality is searchable when creating other workflows but im not sure how this would work exactly yet."

The core tension: MCP is too heavy for simple code wrappers, but there's no lighter alternative.

## User's Mental Model

The user sees a progression:

```
NOW:
  Code node with inline code → users can do anything

PATTERNS EMERGE:
  "I keep writing the same YouTube transcript code"
  "I keep doing the same pandas groupby pattern"

FUTURE:
  pflow helps extract these into lightweight nodes
  - Discoverable via registry
  - Reusable across workflows
  - Searchable by agents building new workflows
```

**Key phrase**: "functionality is searchable when creating other workflows" — discoverability matters as much as reusability.

## The Problem Space

### Why MCP is Too Heavy

Current MCP node creation requires:
1. Create a Python/TS project
2. Implement stdio server protocol
3. Define tool schemas
4. Handle JSON-RPC messaging
5. Configure server in pflow settings
6. Server runs as separate process

For wrapping 10 lines of Python? Massive overkill.

### What Users Actually Want

```python
# I wrote this in a code node:
from youtube_transcript_api import YouTubeTranscriptApi
transcript = YouTubeTranscriptApi.get_transcript(video_id)
result = transcript

# I want to turn it into a reusable node called "youtube-transcript"
# that I (and agents) can use in future workflows
```

### Requirements (Inferred)

1. **Simple definition** — No boilerplate, just code + metadata
2. **Discoverable** — Shows up in `pflow registry list/discover`
3. **Documented** — Has description, inputs, outputs for agents
4. **Executable** — Works like any other node in workflows
5. **Shareable** — Can be shared with team (future: pflow cloud)

---

## Options Explored

### Option 1: Python File with Docstring Metadata

Single Python file, metadata in docstring:

```python
# ~/.pflow/custom-nodes/youtube_transcript.py
"""
Node: youtube-transcript
Description: Fetches transcript for a YouTube video
Category: media

Inputs:
  video_id: string - YouTube video ID

Outputs:
  transcript: list - List of transcript segments

Requires:
  - youtube-transcript-api
"""

def execute(video_id: str) -> list:
    from youtube_transcript_api import YouTubeTranscriptApi
    return YouTubeTranscriptApi.get_transcript(video_id)
```

**Pros:**
- Familiar Python pattern (like pytest, Flask routes)
- Existing metadata extractor can be extended
- Single file = simple to create and share
- IDE support for Python

**Cons:**
- Docstring parsing is fragile
- Limited to Python (no TS support without separate format)
- Requires specific function name (`execute`)

### Option 2: YAML + Code File

Separate metadata and code:

```yaml
# ~/.pflow/custom-nodes/youtube-transcript/node.yaml
name: youtube-transcript
description: Fetches transcript for a YouTube video
category: media
language: python
requires:
  - youtube-transcript-api

inputs:
  video_id:
    type: string
    description: YouTube video ID

outputs:
  transcript:
    type: list
    description: List of transcript segments
```

```python
# ~/.pflow/custom-nodes/youtube-transcript/execute.py
from youtube_transcript_api import YouTubeTranscriptApi

def execute(video_id: str) -> list:
    return YouTubeTranscriptApi.get_transcript(video_id)
```

**Pros:**
- Clean separation of concerns
- YAML is easy for agents to generate
- Supports multiple languages (point to .py or .ts file)
- Structured metadata, no parsing ambiguity

**Cons:**
- Two files per node
- More complex directory structure
- YAML can be verbose

### Option 3: Decorated Python Functions

Use decorators like Flask/FastAPI:

```python
# ~/.pflow/custom-nodes/media_nodes.py
from pflow import node, Input, Output

@node(
    name="youtube-transcript",
    description="Fetches transcript for a YouTube video",
    category="media",
    requires=["youtube-transcript-api"]
)
def youtube_transcript(
    video_id: Input[str, "YouTube video ID"]
) -> Output[list, "List of transcript segments"]:
    from youtube_transcript_api import YouTubeTranscriptApi
    return YouTubeTranscriptApi.get_transcript(video_id)

@node(name="youtube-metadata", ...)
def youtube_metadata(video_id: Input[str]) -> Output[dict]:
    ...
```

**Pros:**
- Pythonic, familiar pattern
- Multiple nodes per file
- Type hints provide structure
- IDE autocomplete works

**Cons:**
- Requires pflow import (circular dependency?)
- Python-only
- More magic (decorators)

### Option 4: JSON/Markdown Node Definition

Similar to workflow IR, but for nodes:

```json
{
  "name": "youtube-transcript",
  "description": "Fetches transcript for a YouTube video",
  "category": "media",
  "language": "python",
  "requires": ["youtube-transcript-api"],
  "inputs": {
    "video_id": {"type": "string", "description": "YouTube video ID"}
  },
  "outputs": {
    "transcript": {"type": "list", "description": "Transcript segments"}
  },
  "code": "from youtube_transcript_api import YouTubeTranscriptApi\nresult = YouTubeTranscriptApi.get_transcript(video_id)"
}
```

Or markdown (aligns with Task 107):

```markdown
# youtube-transcript

Fetches transcript for a YouTube video

## Inputs
- video_id: string - YouTube video ID

## Outputs
- transcript: list - Transcript segments

## Code
```python
from youtube_transcript_api import YouTubeTranscriptApi
result = YouTubeTranscriptApi.get_transcript(video_id)
```​
```

**Pros:**
- Consistent with workflow IR/markdown format
- Easy for agents to generate
- Self-contained single file
- Markdown is human-readable

**Cons:**
- Code as string (escaping issues in JSON)
- No IDE support for embedded code
- New format to learn

### Option 5: "Save Script as Node" Command

Don't define format upfront. Let users extract from code nodes:

```bash
# User runs workflow with code node
pflow run workflow.json

# User likes the script, wants to make it reusable
pflow node extract workflow.json --node transform-data --name my-transform

# pflow generates the node definition automatically
# Saved to ~/.pflow/custom-nodes/my-transform.py
```

**Pros:**
- Zero learning curve for creation
- Metadata inferred from code node params
- Natural "pave the cowpaths" approach
- Agents can do this too

**Cons:**
- Requires code node to be well-structured
- Magic extraction might miss nuances
- Still need underlying format (Options 1-4)

### Option 6: Inline in Workflow + Registry Sync

Nodes defined inline in workflows, then synced to registry:

```json
{
  "nodes": [...],
  "custom_nodes": {
    "youtube-transcript": {
      "description": "...",
      "code": "...",
      "inputs": {...}
    }
  }
}
```

When workflow is saved:
```bash
pflow workflow save my-workflow --publish-nodes
# Extracts custom_nodes to ~/.pflow/custom-nodes/
```

**Pros:**
- Nodes defined where they're used
- Natural extraction workflow
- Version controlled with workflow

**Cons:**
- Nodes coupled to specific workflow initially
- Publishing step required
- Potential naming conflicts

---

## Options NOT Explored (But Might Matter)

### Option 7: MCP-Lite (Simplified MCP)

Subset of MCP protocol, in-process:

```python
# Instead of stdio server, just register a function
pflow.register_tool(
    name="youtube-transcript",
    fn=my_function,
    schema={...}
)
```

**Consideration**: Bridges gap between "too simple" and "full MCP". Could be a stepping stone.

### Option 8: WebAssembly Modules

Package nodes as .wasm files:

**Consideration**: Language-agnostic, sandboxed, portable. But complex to implement and unfamiliar to users.

### Option 9: Container Images

Each custom node is a Docker image:

**Consideration**: Maximum isolation, but even heavier than MCP. Probably wrong direction.

### Option 10: Git-Based Node Registry

Nodes live in git repos, installed like packages:

```bash
pflow node install github.com/user/youtube-nodes
```

**Consideration**: Good for sharing, but doesn't solve the "lightweight creation" problem.

---

## Key Design Decisions Needed

1. **Single file vs directory per node?**
   - Single file: simpler, but limits complexity
   - Directory: cleaner separation, supports assets

2. **Metadata format?**
   - Docstring: familiar but fragile
   - YAML/JSON: structured but verbose
   - Decorators: Pythonic but magic

3. **Multi-language support?**
   - Python-only for MVP?
   - How to support TS nodes?

4. **Discovery mechanism?**
   - Scan directory on startup?
   - Explicit registration?
   - Lazy loading?

5. **Execution model?**
   - In-process (like code node)?
   - Subprocess (like shell node)?
   - Depends on sandboxing needs?

6. **Relationship to MCP?**
   - Coexist (simple nodes + MCP for complex)?
   - Replace MCP for local nodes?
   - Convert custom nodes to MCP for sharing?

---

## Assumptions & Uncertainties

**ASSUMPTION**: Users want to create nodes from code they've already written (extraction), not define nodes from scratch.

**ASSUMPTION**: Discoverability is critical — nodes must show up in registry commands for agents to find them.

**UNCLEAR**: Should custom nodes support the full node interface (prep/exec/post) or simplified (just execute)?

**UNCLEAR**: How do custom nodes handle dependencies? `requires` field is documentation, but who installs packages?

**NEEDS VERIFICATION**: Can existing metadata extractor handle custom node files, or does it need extension?

---

## Unexplored Territory

**UNEXPLORED**: Versioning. What happens when a custom node changes? Do workflows break?

**UNEXPLORED**: Namespacing. If two users define `youtube-transcript`, what happens? Prefix with username?

**UNEXPLORED**: Testing. How do users test custom nodes before using in workflows?

**UNEXPLORED**: Validation. How do we validate that custom node code is safe/correct before execution?

**CONSIDER**: Task 74 (Knowledge Base) integration. When a custom node is created, should learnings be attached?

**MIGHT MATTER**: Performance. Scanning custom nodes directory on every `pflow` invocation could be slow.

---

## For the Next Agent

**This task is exploratory** — no implementation yet. The user wants options documented.

**Start by**: Understanding the full landscape. Read this braindump, then consider if there are options I missed.

**Don't bother with**: Implementation details. This is design phase.

**The user cares most about**:
1. Simple creation (not MCP-level complexity)
2. Discoverability (agents can find and use custom nodes)
3. Natural workflow (extract from code nodes, not define from scratch)

**My recommendation** (not confirmed with user):
- **Option 5 (extract command) + Option 1 (Python file with docstring)** as MVP
- Users write code nodes, extract to custom nodes when patterns emerge
- Simple single-file format that existing tooling can extend

---

**Note to next agent**: Read this document fully before taking any action. This task is in early exploration phase — the user explicitly said "we dont know exactly what we should implement yet." When ready, confirm you've read and understood by summarizing the key options, then discuss with user before proceeding.
