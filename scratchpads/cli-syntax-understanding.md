# CLI Syntax Understanding - Corrected

## Key Distinction

**Natural Language** (quoted):
```bash
pflow "summarize this youtube video and create a blog post"
```

**CLI Syntax** (unquoted):
```bash
pflow read-file --path=video.txt >> llm --prompt="summarize" >> write-file
```

## Why This Matters

1. **Shell sees real commands** - Even though we send to LLM, shell can parse it
2. **Autocomplete works** - Shell can suggest node names and parameters
3. **User experience** - Feels like real CLI tool, not just text input
4. **Progressive enhancement** - Can add features incrementally

## Value Hierarchy

### HIGH Value: CLI Autocomplete
- Users can discover available nodes
- Tab completion for parameters
- Immediate feedback while typing
- Works even with LLM backend

### LOW Value: Direct CLI Parsing
- Only slightly faster (LLM still needed)
- Users rarely specify everything anyway
- LLM fills in the gaps regardless

## Implementation Phases

### Phase 1: MVP Core
```bash
# User types (with autocomplete):
pflow read-file --path=data.txt >> llm >> write-file

# System:
1. Parse as CLI args (not string)
2. Send parsed structure to LLM
3. LLM fills in missing pieces
4. Generate complete workflow
```

### Phase 2: CLI Autocomplete
```bash
# User types:
pflow read-f[TAB]
# Autocompletes to: read-file

pflow read-file --p[TAB]
# Shows: --path

pflow read-file --path=data.txt >> [TAB]
# Shows available nodes: llm, write-file, github-create-issue, etc.
```

### Phase 3: Direct Parsing (v2.0)
- Skip LLM for fully specified workflows
- Minor optimization only
- Most workflows still need LLM

## Why LLM Is Always Needed

Even with "complete" CLI syntax:
```bash
pflow github-get-issue --issue=123 >> claude-code >> git-commit >> github-create-pr
```

Missing information:
- How does issue data flow to claude-code?
- What prompt for claude-code?
- What commit message?
- What PR title and body?
- Template variables needed

LLM intelligently:
- Creates template strings
- Connects data flow
- Generates appropriate prompts
- Handles missing parameters

## Task Updates Needed

1. **Update Task #19**: Clarify CLI syntax handling
2. **Add CLI Autocomplete Task**: High priority for MVP
3. **Move Direct Parsing to v2.0**: Low priority optimization

The progression:
1. CLI syntax → LLM (MVP)
2. + Autocomplete (MVP enhancement)
3. + Direct parsing (v2.0 optimization)
