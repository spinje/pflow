# Revised Improvement Plan for cli-agent-instructions.md

**Based on:** User feedback revealing the TRUE root cause
**Date:** 2025-11-13
**Key Insight:** The examples are correct, but missing preventative warnings

---

## The Real Problem (Not What We Thought)

### Initial Analysis Was Partially Wrong:

We thought: "The document doesn't show saved format examples"
**Reality:** The development format examples are CORRECT. The issue is psychological/intuitive.

### The Actual Root Cause:

**Developers add metadata by intuition, not from reading wrong examples.**

When building a reusable component, experienced developers naturally think:
> "This should have a name and description like every other reusable component I've built"

This is **not from bad documentation** - it's from **software engineering muscle memory**.

---

## What Actually Happened (Agent's Experience)

1. ✅ Read the examples (which correctly show only inputs/nodes/edges/outputs)
2. 🧠 Intuition kicked in: "Reusable things need metadata"
3. ❌ Added `name` and `description` fields (not from examples, from intuition)
4. 💥 Validation error: "Additional properties are not allowed"
5. 🤔 Trial-and-error: Removed metadata, validation passed
6. ✅ Continued building...

**Then later:**

7. ✅ Workflow validated and tested successfully
8. 🧠 Intuition: "I should save this to the workflows directory"
9. ❌ Manually copied file (seemed logical)
10. 💥 `KeyError: 'ir'` when executing by name

---

## The Two Critical Gaps

### Gap 1: No Preventative Warning Against Metadata (HIGH PRIORITY)

**Problem:** Developers will add `name`/`description` by intuition
**Current State:** Examples are correct but silent on what NOT to do
**Needed:** Explicit "Do NOT add these fields" warning

**Where to Add:**
- **Step 8 (BUILD)** - Right at the beginning, before examples
- **Part 1 (Lifecycle)** - In the development format explanation

### Gap 2: No Explanation of Save Command's Role (HIGH PRIORITY)

**Problem:** Users don't understand that `pflow workflow save` adds metadata AND transforms structure
**Current State:** Save command appears late (Step 12) without emphasizing transformation
**Needed:** Early explanation that save command handles all metadata

---

## Simplified Improvement Strategy

### Philosophy Shift:

**Old Approach:** "Fix examples and add saved format examples"
**New Approach:** "Add explicit warnings where intuition leads astray"

### Key Principle:

**Fight intuition with explicit warnings, not just correct examples.**

Developers don't just copy examples - they bring patterns from other systems. We need to explicitly say "Stop. Don't do what you normally do."

---

## Revised Implementation Plan

### Phase 1: Add "Don't Do This" Warnings (CRITICAL) 🔴

#### Location 1: Step 8 (BUILD) - Beginning

**Add this prominent warning box BEFORE the first code example:**

```markdown
### Step 8: BUILD - Creating Your Workflow File

⚠️ **CRITICAL: Development Format Only**

When creating your workflow JSON file, include ONLY these four keys:
- `inputs` (optional but recommended)
- `nodes` (required)
- `edges` (required)
- `outputs` (optional)

**DO NOT add these fields** (even though you might expect them):
- ❌ `name` - Will cause validation error
- ❌ `description` - Will cause validation error
- ❌ `version` - Will cause validation error
- ❌ `created_at`, `updated_at` - Will cause validation error
- ❌ `ir` - Will cause validation error

**Why?** These metadata fields are added automatically by `pflow workflow save`.
Adding them manually will fail validation with:
`"Additional properties are not allowed ('name', 'description' were unexpected)"`

**Development format template (this is what you create):**
```json
{
  "inputs": {
    "param_name": {
      "type": "str",
      "required": true,
      "description": "What this parameter does"
    }
  },
  "nodes": [
    {
      "id": "step1",
      "type": "node-type",
      "params": {
        "key": "${param_name}"
      }
    }
  ],
  "edges": [
    {"from": "step1", "to": "step2"}
  ],
  "outputs": {
    "result": "${final-step.output}"
  }
}
```

Save this as `my-workflow.json` anywhere you like.

**Remember:** This is a "headless" workflow - no metadata yet. The `pflow workflow save` command will add all the metadata when you're ready to make it reusable.
```

**Why This Works:**
- Catches intuition before it happens
- Explicitly names the fields developers might add
- Explains WHY they shouldn't add them
- Shows what validation error they'll get if they do
- Introduces the "headless workflow" concept

---

#### Location 2: Part 1 (After Core Philosophy)

**Add a new section explaining the lifecycle with emphasis on metadata:**

```markdown
### Understanding Workflow Files: Development vs. Saved

**pflow workflows exist in two forms, and understanding this prevents common errors.**

#### During Development: "Headless" Workflows

When you're building and testing, your workflow file contains ONLY the logic:

```json
{
  "inputs": {"api_url": {"type": "str", "required": true}},
  "nodes": [...],
  "edges": [...],
  "outputs": {"result": "${final.output}"}
}
```

**This is called "development format" or "headless workflow":**
- No metadata (no name, description, version)
- Just the workflow logic
- Can live anywhere on your filesystem
- Execute with: `pflow /path/to/file.json`

**⚠️ Common Mistake:** Adding `name` or `description` fields here
- This will cause validation errors
- Metadata is added by the save command, not manually

#### After Saving: "Headed" Workflows

When you run `pflow workflow save`, your headless workflow gets transformed:

```json
{
  "name": "workflow-name",
  "description": "What it does",
  "version": "1.0.0",
  "created_at": "2025-11-13T10:00:00Z",
  "updated_at": "2025-11-13T10:00:00Z",
  "ir": {
    // Your headless workflow goes inside "ir" wrapper
    "inputs": {...},
    "nodes": [...],
    "edges": [...],
    "outputs": {...}
  },
  "rich_metadata": {
    "execution_count": 0,
    "last_execution_timestamp": null,
    "last_execution_success": null,
    "last_execution_params": {}
  }
}
```

**This is called "saved format" or "headed workflow":**
- Has metadata "head" (name, version, etc.)
- Your workflow is nested inside `"ir"` key
- Lives in `~/.pflow/workflows/`
- Execute with: `pflow workflow-name`

#### The Critical `ir` Wrapper

Notice how your entire headless workflow is wrapped inside the `"ir"` key?

**This wrapper is required for execution by name.**

- ✅ If saved with `pflow workflow save` → Has `ir` wrapper → Works
- ❌ If manually copied → No `ir` wrapper → `KeyError: 'ir'`

#### Why Two Formats?

**Headless (development):**
- Easy to edit and version control
- No clutter, just logic
- Works with standard JSON editors

**Headed (saved):**
- Adds metadata for discovery and execution
- Tracks usage history
- Managed by pflow automatically

#### The Transformation Command

```bash
# Transforms headless → headed
pflow workflow save /path/to/headless.json \
  workflow-name \
  "Brief description" \
  --generate-metadata
```

**What this command does:**
1. Takes your headless workflow
2. Wraps it in `"ir"` key
3. Adds metadata fields (name, description, version, timestamps)
4. Generates discovery keywords (with --generate-metadata)
5. Saves to `~/.pflow/workflows/workflow-name.json`

**The Golden Rules:**

1. **Never add metadata to development files** - Causes validation errors
2. **Never manually copy to ~/.pflow/workflows/** - Missing `ir` wrapper causes execution errors
3. **Always use `pflow workflow save`** - Handles transformation correctly
4. **Keep development files** - Your source of truth for updates

#### Common Error Paths

**❌ Path 1: Adding Metadata Too Early**
```json
{
  "name": "my-workflow",  ← Don't do this
  "inputs": {...},
  "nodes": [...]
}
```
Result: `ValidationError: Additional properties are not allowed`

**❌ Path 2: Manual File Copy**
```bash
cp my-workflow.json ~/.pflow/workflows/
pflow my-workflow  ← KeyError: 'ir'
```
Result: Missing `ir` wrapper

**✅ The Right Path**
```bash
# 1. Create headless workflow (no metadata)
nano my-workflow.json

# 2. Test it
pflow my-workflow.json param=value

# 3. Save properly (adds metadata + ir wrapper)
pflow workflow save my-workflow.json \
  my-workflow \
  "What it does" \
  --generate-metadata

# 4. Execute by name
pflow my-workflow param=value
```
Result: Works perfectly
```

**Why This Works:**
- Introduces "headless" vs "headed" terminology (memorable metaphor)
- Shows both formats side-by-side with real structure
- Explicitly shows the `ir` wrapper and explains its necessity
- Warns against both error paths (metadata too early + manual copy)
- Provides the correct path clearly

---

### Phase 2: Update Step 9 (VALIDATE) - Add Context 🟡

**Current problem:** Validation success gives false sense of completion

**Add this clarification:**

```markdown
### Step 9: VALIDATE - What This Checks (And Doesn't)

```bash
pflow --validate-only workflow.json
```

**✓ Workflow is valid**

**What validation confirms:**
- ✅ Structure is correct (inputs, nodes, edges, outputs)
- ✅ Node types exist in registry
- ✅ Templates reference valid outputs
- ✅ No circular dependencies

**What validation DOES NOT confirm:**
- ❌ Workflow is saved for execution by name
- ❌ `ir` wrapper exists (not needed for direct file execution)
- ❌ Metadata is present (not needed yet)

**After validation passes, you can:**
- ✅ Execute directly: `pflow workflow.json param=value`
- ❌ Execute by name: `pflow workflow-name` (not yet - needs saving first)

**Next steps:**
1. Test it: `pflow workflow.json param=value` (direct file execution)
2. Refine if needed (Step 10-11)
3. Save it: `pflow workflow save ...` (adds metadata + ir wrapper)
4. Execute by name: `pflow workflow-name param=value`

⚠️ **Common mistake:** Thinking validation = ready for name execution
**Reality:** Validation only means the workflow structure is correct for TESTING.
To make it executable by name, you must save it properly.
```

---

### Phase 3: Strengthen Step 12 (SAVE) - Emphasize Transformation 🔴

**Current problem:** Appears too late, doesn't emphasize what it does

**Rewrite to emphasize the transformation:**

```markdown
### Step 12: SAVE - The Transformation Step ⚠️ REQUIRED FOR NAME EXECUTION

**What You Have Now:** Headless workflow (development format)
**What You Need:** Headed workflow (saved format) for execution by name

**The transformation command:**

```bash
pflow workflow save /path/to/your-workflow.json \
  workflow-name \
  "Brief description" \
  --generate-metadata
```

**What this command does (the transformation):**

1. **Validates** - Final structure check
2. **Wraps** - Puts your workflow inside `"ir"` key (CRITICAL!)
3. **Adds metadata** - name, description, version, timestamps
4. **Generates keywords** - For `pflow workflow discover` (if --generate-metadata)
5. **Saves to library** - `~/.pflow/workflows/workflow-name.json`
6. **Enables name execution** - Now `pflow workflow-name` works

**Before transformation (headless):**
```json
{
  "inputs": {...},
  "nodes": [...],
  "edges": [...]
}
```

**After transformation (headed):**
```json
{
  "name": "workflow-name",
  "description": "What it does",
  "version": "1.0.0",
  "ir": {
    // Your headless workflow wrapped here
    "inputs": {...},
    "nodes": [...],
    "edges": [...]
  }
}
```

**Why you can't skip this step:**

Without the transformation:
- ❌ `pflow workflow-name` → `KeyError: 'ir'`
- ❌ Won't appear in `pflow workflow list`
- ❌ Can't be found with `pflow workflow discover`

**Example:**

```bash
# Save your tested workflow
pflow workflow save /tmp/api-analyzer.json \
  api-analyzer \
  "Fetches and analyzes API data" \
  --generate-metadata

# Verify it worked
pflow workflow list | grep api-analyzer
# Should show: api-analyzer - Fetches and analyzes API data

# Execute by name
pflow api-analyzer api_url="https://api.example.com"
```

**Common mistakes to avoid:**

❌ **Manually copying file:**
```bash
cp my-workflow.json ~/.pflow/workflows/
pflow my-workflow  # KeyError: 'ir'
```

❌ **Editing saved workflow directly:**
```bash
nano ~/.pflow/workflows/my-workflow.json  # Don't do this
```

✅ **The right way:**
```bash
# Edit your development file
nano my-workflow.json

# Re-save with --force to update
pflow workflow save my-workflow.json my-workflow "Updated" --force
```

**Arguments explained:**

- `file.json` - Your headless workflow file
- `workflow-name` - Name for execution (lowercase-with-hyphens)
- `"description"` - Brief description (shown in list)
- `--generate-metadata` - Generate discovery keywords (RECOMMENDED)
- `--force` - Overwrite existing workflow
- `--delete-draft` - Remove source file after save

**After saving, verify it works:**

```bash
# Check it appears in list
pflow workflow list

# See its metadata
pflow workflow describe workflow-name

# Test execution by name
pflow workflow-name param=value
```
```

---

### Phase 4: Add Troubleshooting Section 🟢

**Add new Part 6 with common errors:**

```markdown
## Part 6: Common Errors and How to Fix Them

### Error: `Additional properties are not allowed ('name', 'description' were unexpected)`

**What you did:**
Added metadata fields to your development workflow file:
```json
{
  "name": "my-workflow",  ← This causes the error
  "description": "...",   ← This too
  "inputs": {...}
}
```

**Why it fails:**
Development format (headless workflow) should contain ONLY:
- `inputs`, `nodes`, `edges`, `outputs`

Metadata is added by `pflow workflow save`, not manually.

**How to fix:**
Remove `name`, `description`, `version`, and any other metadata fields:
```json
{
  "inputs": {...},
  "nodes": [...],
  "edges": [...],
  "outputs": {...}
}
```

**Prevention:**
Don't add metadata to development files. Let `pflow workflow save` handle it.

---

### Error: `KeyError: 'ir'`

**What you did:**
Manually copied your workflow file to `~/.pflow/workflows/`:
```bash
cp my-workflow.json ~/.pflow/workflows/my-workflow.json
pflow my-workflow  # KeyError: 'ir'
```

**Why it fails:**
Saved workflows need your workflow wrapped in an `"ir"` key:
```json
{
  "name": "...",
  "ir": {
    // Your workflow goes here
  }
}
```

Manual copying doesn't add this wrapper.

**How to fix:**
```bash
# 1. Delete the manually copied file
rm ~/.pflow/workflows/my-workflow.json

# 2. Use the save command
pflow workflow save /path/to/original.json \
  my-workflow \
  "Description" \
  --generate-metadata

# 3. Test it
pflow my-workflow param=value
```

**Prevention:**
Never manually copy files to `~/.pflow/workflows/`.
Always use `pflow workflow save`.

---

### Error: Workflow validates but fails to execute

**Possible causes:**

1. **Missing API keys** (MCP nodes)
   ```bash
   pflow workflow-name param=value --verbose
   # Look for authentication errors
   ```

2. **Wrong parameter types**
   ```bash
   pflow workflow describe workflow-name
   # Check required parameter types
   ```

3. **Network/API issues**
   ```bash
   # Test individual nodes first
   pflow registry run node-type param=value
   ```

---

### Workflow runs with `pflow file.json` but not `pflow workflow-name`

**What this means:**
- Structure is valid (that's why file execution works)
- Workflow isn't properly saved (that's why name execution fails)

**How to fix:**
```bash
# Save it properly
pflow workflow save file.json workflow-name "Description" --generate-metadata

# Verify
pflow workflow list
pflow workflow-name param=value
```

**Why this happens:**
- Direct file execution uses headless format (no `ir` wrapper needed)
- Name execution requires headed format (needs `ir` wrapper)

---

### General debugging strategy:

1. **Test structure:** `pflow --validate-only file.json`
2. **Test direct execution:** `pflow file.json param=value --verbose`
3. **Check if saved:** `pflow workflow list`
4. **Test by name:** `pflow workflow-name param=value --verbose`

If direct file works but name fails → Use `pflow workflow save`
```

---

## Implementation Priority

### Must-Do (Addresses Core Issues):

1. 🔴 **Phase 1, Location 1** - "Don't Do This" warning in Step 8
2. 🔴 **Phase 1, Location 2** - Lifecycle explanation in Part 1 (headless vs headed)
3. 🔴 **Phase 3** - Strengthen Step 12 with transformation emphasis

### Should-Do (Adds Important Context):

4. 🟡 **Phase 2** - Update Step 9 validation clarification
5. 🟢 **Phase 4** - Add troubleshooting section

---

## Why This Revised Plan Is Better

### Original Plan Issues:

- Assumed document had wrong examples (it didn't)
- Focused on showing saved format examples (helpful but not root cause)
- Missed the psychological aspect (intuition vs examples)

### Revised Plan Strengths:

- ✅ Acknowledges examples are correct
- ✅ Adds explicit warnings where intuition leads wrong
- ✅ Uses memorable metaphors (headless vs headed)
- ✅ Shows both error paths clearly
- ✅ Emphasizes transformation concept
- ✅ Simpler to implement (focused warnings vs comprehensive rewrite)

---

## Success Metrics

After these changes, developers should:

✅ See explicit warning before adding metadata
✅ Understand "headless" vs "headed" concept
✅ Know that save command handles transformation
✅ Avoid manual copying due to clear warnings
✅ Understand `ir` wrapper is added by save command

**The two error paths should be explicitly warned against:**

1. ❌ Adding metadata too early → Validation error
   - **Fixed by:** Warning in Step 8

2. ❌ Manual file copying → KeyError: 'ir'
   - **Fixed by:** Lifecycle explanation + Step 12 rewrite

---

## Conclusion

The document's examples are correct. The issue is **implicit knowledge** that developers need explicit warnings about:

1. **Don't follow your instincts** - No metadata in development files
2. **Don't manually manage files** - Use save command for transformation
3. **Understand the transformation** - Headless → Headed via `ir` wrapper

These are **anti-patterns** that need explicit warnings, not just correct examples.
