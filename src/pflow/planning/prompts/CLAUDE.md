# CLAUDE.md - AI Agent Instructions for Prompt Directory

## ⚠️ CRITICAL: Frontmatter is Automated

**NEVER manually edit the YAML frontmatter** in any `.md` file here. It's automatically maintained by the test accuracy tool:

```yaml
---
name: discovery           # ❌ DO NOT EDIT
test_path: ...           # ❌ DO NOT EDIT
test_command: ...        # ❌ DO NOT EDIT
version: 1.0            # ❌ DO NOT EDIT
latest_accuracy: 87.0   # ❌ DO NOT EDIT
test_runs: [...]        # ❌ DO NOT EDIT
average_accuracy: 85.3  # ❌ DO NOT EDIT
test_count: 20          # ❌ DO NOT EDIT
# ... all frontmatter fields are automated
---
```

## ✅ What You CAN Edit

Only edit the prompt content AFTER the closing `---`:
- Improve prompt instructions
- Fix typos or clarity issues
- Adjust template variables `{{variable}}`
- Add/remove prompt sections

## 🧪 Testing Prompts

To test after editing:
```bash
# Test and update metrics (default)
uv run python tools/test_prompt_accuracy.py discovery

# Test without updating (dry run)
uv run python tools/test_prompt_accuracy.py discovery --dry-run
```

The test runner:
- Sets `RUN_LLM_TESTS=1` automatically
- Updates accuracy metrics
- Tracks version changes
- Maintains test history

## 📁 Files in This Directory

```
src/pflow/planning/prompts/
├── discovery.md                # Determines if existing workflow matches request
├── component_browsing.md       # Selects nodes/workflows for generation
├── parameter_discovery.md      # Extracts parameters from user input
├── parameter_mapping.md        # Maps parameters to workflow inputs
├── workflow_generator.md       # Generates workflow IR from components
├── metadata_generation.md      # Creates searchable workflow metadata
├── loader.py                   # Loads prompts, skips frontmatter
├── README.md                   # Detailed docs: advanced usage, workflow, troubleshooting
└── CLAUDE.md                   # This file - AI agent instructions
```

## 🎯 Key Rules

1. **Edit prompt content only** - never frontmatter
2. **Run tests after changes** - verify improvements
3. **Preserve {{variables}}** - they're required by the system
4. **Test accuracy is tracked** - aim for >90%

## 📊 Understanding Metrics

- **accuracy**: % of tests passing (100% is perfect)
- **test_count**: Number of test cases (more = more robust)
- **version**: Auto-increments on significant changes
- **test_runs**: History for averaging (handles LLM variance)

---
*For detailed information, see README.md. This file is kept brief to minimize context usage.*