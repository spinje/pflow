# pflow Instructions Create - Improvement Report

**Date:** 2025-11-13
**Context:** After successfully creating a workflow but encountering issues with saving and executing it by name, this report identifies unclear sections in the `pflow instructions create` documentation.

## Executive Summary

The `pflow instructions create` documentation is comprehensive but contains a critical gap: **it does not clearly explain the two-phase workflow lifecycle (development vs. saved) and the structural transformation that occurs between them**. This led to manual file copying instead of using the proper `pflow workflow save` command, resulting in a `KeyError: 'ir'` when attempting to execute the workflow by name.

---

## Issues Identified

### 🔴 Critical Issue 1: Workflow Structure Lifecycle Not Explained

**Problem:**
The document shows workflow examples without clearly distinguishing between:
- **Development format** (what you create and test)
- **Saved format** (what gets stored in `~/.pflow/workflows/`)

**What Happened:**
1. Created workflow with this structure (after validation error taught me to remove name/description):
   ```json
   {
     "inputs": {...},
     "nodes": [...],
     "edges": [...],
     "outputs": {...}
   }
   ```

2. Manually copied it to `~/.pflow/workflows/slack-qa-sheets-automation.json` using `cp`

3. Attempted to run by name: `pflow slack-qa-sheets-automation ...`

4. Got error: `KeyError: 'ir'`

**Root Cause:**
The document never explains that:
- Development files are "raw" workflow definitions
- Saved workflows must be wrapped with metadata using `pflow workflow save`
- The save command transforms the structure by wrapping it in an `"ir"` key
- Manual file copying will NOT work

**Where This Should Be Explained:**
Right at the beginning of the "Complete Development Loop" section (Part 3), there should be a clear section titled:

```markdown
## Workflow Lifecycle: Development → Testing → Saving

### Phase 1: Development
Create a JSON file with this structure ONLY:
```json
{
  "inputs": {...},
  "nodes": [...],
  "edges": [...],
  "outputs": {...}
}
```
DO NOT include "name", "description", "version", "ir", or other metadata fields.
This is your working/development format.

### Phase 2: Testing
Test your workflow directly from the file:
```bash
pflow /path/to/your-workflow.json param1=value1 param2=value2
```

### Phase 3: Saving for Reuse
Once tested, save it properly (this adds required metadata):
```bash
pflow workflow save /path/to/your-workflow.json \
  workflow-name \
  "Brief description" \
  --generate-metadata
```

This command:
- Wraps your workflow in metadata structure
- Adds timestamps, version info
- Generates discovery keywords
- Saves to ~/.pflow/workflows/

⚠️ **CRITICAL:** Do NOT manually copy files to ~/.pflow/workflows/
Always use `pflow workflow save` or the workflow won't be executable by name.

### Phase 4: Execution by Name
After saving, run it by name:
```bash
pflow workflow-name param1=value1 param2=value2
```
```

---

### 🔴 Critical Issue 2: The `pflow workflow save` Command Is Buried

**Problem:**
The save command appears late in the document (Step 12) and is not emphasized as MANDATORY for workflow reuse.

**Current Location:**
Line ~920 in Step 12: "SAVE - Make It Reusable"

**Impact:**
- Users don't realize this is a required step, not optional
- Users think they can just copy the file
- The importance of `--generate-metadata` is unclear

**Recommendation:**
Move this information to:
1. The "Foundation & Mental Model" section as a key concept
2. Create a dedicated "Workflow Lifecycle" section before the development loop
3. Add a warning box in the validation step

**Suggested Warning Box:**
```markdown
⚠️ **IMPORTANT - Saving Workflows**

After validation, your workflow file is ready for testing but NOT ready for
execution by name. To make it reusable:

✅ DO: Use `pflow workflow save your-file.json name "description" --generate-metadata`
❌ DON'T: Copy files manually to ~/.pflow/workflows/

The save command wraps your workflow with required metadata that enables:
- Execution by name (pflow workflow-name)
- Discovery (pflow workflow discover)
- Version tracking and timestamps
```

---

### 🟡 Medium Issue 3: Validation Gives False Confidence

**Problem:**
The document emphasizes validation with `pflow --validate-only workflow.json`, which passes successfully. However, this only validates the IR structure, not whether the workflow is properly saved for execution by name.

**What Happened:**
```bash
pflow --validate-only /tmp/slack-qa-workflow-v2.json
# ✓ Workflow is valid

# User thinks: "Great! It's valid, I can use it now"
# Reality: It's only valid for direct file execution, not saved properly
```

**Recommendation:**
Update Step 9 (VALIDATE) to clarify:

```markdown
### Step 9: VALIDATE - Understanding Validation Scope

```bash
pflow --validate-only workflow.json
```

✓ This validates: Workflow structure, node types, templates, edges
✗ This does NOT validate: Proper saving for reuse by name

**Validation Success Means:**
- You can run it with: `pflow workflow.json param=value`
- You CANNOT yet run it with: `pflow workflow-name param=value`
- You still need to save it with: `pflow workflow save ...`
```

---

### 🟡 Medium Issue 4: Initial Validation Error Not Explained

**Problem:**
When I first created the workflow with `"name"` and `"description"` fields, I got:
```
Validation error at root: Additional properties are not allowed ('description', 'name' were unexpected)
```

This taught me the correct development format, but through trial and error. The document should prevent this confusion upfront.

**Current State:**
Step 8 (BUILD) shows examples without name/description, but doesn't explicitly state "DO NOT include these fields during development."

**Recommendation:**
Add a prominent callout in Step 8:

```markdown
### Step 8: BUILD - File Structure Rules

⚠️ **Development vs. Saved Format**

When creating your workflow JSON file, include ONLY these top-level keys:
- `inputs` (optional, but recommended)
- `nodes` (required)
- `edges` (required)
- `outputs` (optional)

DO NOT include:
- `name` - Added by save command
- `description` - Added by save command
- `version` - Added by save command
- `created_at` / `updated_at` - Added by save command
- `ir` - Internal wrapper added by save command
- `rich_metadata` - Generated by save command

If you include these fields, validation will fail with:
"Additional properties are not allowed"
```

---

### 🟡 Medium Issue 5: No Clear "Workflow File Locations" Guide

**Problem:**
The document mentions `~/.pflow/workflows/` and `.pflow/workflows/` but doesn't explain:
- When to use which location
- What each location is for
- Why you shouldn't manually put files there

**Recommendation:**
Add early in the document (Part 1 or Part 2):

```markdown
## Understanding Workflow File Locations

### During Development
**Location:** Anywhere you want (typically `/tmp/` or project directory)
```bash
# Create and test from any location
pflow /tmp/my-workflow.json param=value
pflow ./workflows/my-workflow.json param=value
```

### After Saving
**Location:** `~/.pflow/workflows/` (managed by pflow)
```bash
# Save command handles this automatically
pflow workflow save /tmp/my-workflow.json workflow-name "description"

# Now executable by name from anywhere
pflow workflow-name param=value
```

### Project-Specific Drafts (Optional)
**Location:** `.pflow/workflows/` in your project
- For workflows still in development
- Not automatically discoverable
- Can be saved to global library when ready

⚠️ **Never manually edit or copy files in ~/.pflow/workflows/**
Always use pflow commands to manage saved workflows.
```

---

### 🟡 Medium Issue 6: Examples Mix Development and Saved Formats

**Problem:**
Throughout the document, some code blocks show workflows with metadata fields, others don't. This creates confusion about which format to use when.

**Examples:**
- Line 150: Shows workflow WITH metadata (name, description) - this is SAVED format
- Line 400: Shows workflow WITHOUT metadata - this is DEVELOPMENT format
- No clear indication which is which

**Recommendation:**
Consistently label examples:

```markdown
**Development Format (what you create):**
```json
{
  "inputs": {...},
  "nodes": [...],
  "edges": [...]
}
```

**Saved Format (after pflow workflow save):**
```json
{
  "name": "workflow-name",
  "description": "...",
  "ir": {
    "inputs": {...},
    "nodes": [...],
    "edges": [...]
  }
}
```
```

---

### 🟢 Minor Issue 7: `--generate-metadata` Flag Not Explained

**Problem:**
The save command shows `--generate-metadata` flag but doesn't explain:
- What it does
- Why you should use it
- What happens if you don't use it

**Current State:**
```bash
pflow workflow save file.json name "desc" --generate-metadata  # Save workflow
```

**Recommendation:**
```markdown
### Saving With Metadata Generation

```bash
pflow workflow save workflow.json name "description" --generate-metadata
```

**The `--generate-metadata` flag:**
- Uses LLM to analyze your workflow
- Generates keywords for discovery (pflow workflow discover)
- Creates capability descriptions
- Enables better workflow matching

**Recommended:** Always use this flag for workflows you want to share or reuse.
Without it, your workflow won't be discoverable via `pflow workflow discover`.
```

---

### 🟢 Minor Issue 8: No Troubleshooting Section for Common Errors

**Problem:**
When I got `KeyError: 'ir'`, there was no troubleshooting guide to help diagnose the issue.

**Recommendation:**
Add a troubleshooting section at the end:

```markdown
## Common Errors and Solutions

### Error: `KeyError: 'ir'`
**Symptom:** Workflow runs fine with `pflow file.json` but fails with `pflow workflow-name`
**Cause:** Workflow file was manually copied to ~/.pflow/workflows/ instead of using save command
**Solution:**
```bash
# Remove the manually copied file
rm ~/.pflow/workflows/workflow-name.json

# Save it properly
pflow workflow save /path/to/file.json workflow-name "description" --generate-metadata
```

### Error: `Additional properties are not allowed ('name', 'description' were unexpected)`
**Cause:** Including metadata fields in development format
**Solution:** Remove `name`, `description`, `version`, `ir`, etc. from your JSON file.
Only include: `inputs`, `nodes`, `edges`, `outputs`

### Error: `pflow workflow-name: command not found`
**Cause:** Workflow not saved to library
**Solution:** Use `pflow workflow save` to add it to the library first
```

---

## Recommended Document Structure Changes

### Current Structure Issues:
1. Critical workflow lifecycle information is scattered
2. Save command appears too late (Step 12)
3. No clear separation between development and execution phases

### Proposed New Structure:

```markdown
Part 1: Foundation & Mental Model
  - Core Mission
  - Core Philosophy
  - **NEW: Workflow Lifecycle (Development → Testing → Saving → Execution)**
  - **NEW: File Structure: Development vs. Saved Format**
  - Two Fundamental Concepts (Edges vs Templates)
  - Mandatory First Step (workflow discover)

Part 2: Node & Tool Selection (unchanged)

Part 3: The Complete Development Loop
  Step 1: UNDERSTAND
  Step 2: DISCOVER WORKFLOWS
  Step 3: DISCOVER NODES
  Step 4: EXTERNAL API INTEGRATION
  Step 5: TEST MCP/HTTP NODES
  Step 6: DESIGN
  Step 7: PLAN & CONFIRM
  Step 8: BUILD (with file structure rules)
  Step 9: VALIDATE (with save reminder)
  Step 10: TEST
  Step 11: REFINE
  **Step 12: SAVE (moved up, made mandatory)**
  **NEW Step 13: VERIFY (test execution by name)**

Part 4: Building Workflows - Technical Reference (unchanged)

Part 5: Essential Commands (unchanged)

**NEW Part 6: Troubleshooting Common Issues**
```

---

## Specific Text Additions Needed

### 1. Add to Part 1, after "Core Philosophy"

```markdown
### Workflow Lifecycle: From Creation to Reuse

**Understanding the Two Formats:**

Every workflow goes through a transformation:

**PHASE 1: Development Format**
What you create and edit:
```json
{
  "inputs": {"param": {"type": "string", "required": true, ...}},
  "nodes": [{...}],
  "edges": [{...}],
  "outputs": {...}
}
```
- Contains only workflow logic
- Can be anywhere on your filesystem
- Run with: `pflow /path/to/file.json`
- Cannot be executed by name

**PHASE 2: Saved Format**
What exists in ~/.pflow/workflows/ after save:
```json
{
  "name": "workflow-name",
  "description": "What it does",
  "version": "1.0.0",
  "created_at": "2025-11-13T...",
  "updated_at": "2025-11-13T...",
  "ir": {
    // Your workflow from Phase 1 goes here
    "inputs": {...},
    "nodes": [{...}],
    "edges": [{...}],
    "outputs": {...}
  },
  "rich_metadata": {
    "keywords": [...],
    "capabilities": [...]
  }
}
```
- Contains metadata wrapper + your workflow
- Must be in ~/.pflow/workflows/
- Created ONLY by: `pflow workflow save`
- Can be executed by name: `pflow workflow-name`

**The Critical Rule:**
🚫 Never manually copy files to ~/.pflow/workflows/
✅ Always use `pflow workflow save` to transition from Phase 1 to Phase 2

**Why This Matters:**
The `pflow workflow save` command does more than just copy:
- Wraps your workflow in the "ir" (Intermediate Representation) key
- Adds required metadata for execution engine
- Generates discovery keywords for `pflow workflow discover`
- Validates the workflow can be loaded by name

Without this transformation, you'll get: `KeyError: 'ir'`
```

---

### 2. Update Step 9 (VALIDATE) - Add Warning Box

```markdown
### Step 9: VALIDATE - Understanding Validation Scope

```bash
pflow --validate-only workflow.json
```

✓ **Workflow is valid**

**What this validation checks:**
- Workflow structure (inputs, nodes, edges, outputs)
- Node types exist in registry
- Template variables are valid
- Edges form valid linear chain
- Required parameters are present

**What this validation DOES NOT check:**
- Whether workflow is saved for execution by name
- Whether metadata wrapper exists
- Whether file is in correct location

⚠️ **Important:** A valid workflow can still fail to execute by name if not saved properly.

**Next Steps After Validation:**
1. Test it: `pflow workflow.json param=value`
2. Refine if needed (Step 10-11)
3. **Save it: `pflow workflow save workflow.json name "desc" --generate-metadata`**
4. Verify: `pflow name param=value`
```

---

### 3. Rewrite Step 12 (SAVE) - Make It More Prominent

```markdown
### Step 12: SAVE - Making Your Workflow Reusable ⚠️ CRITICAL STEP

**This step is MANDATORY if you want to:**
- Execute workflow by name: `pflow workflow-name`
- Share workflow with others
- Use workflow across different projects
- Enable workflow discovery

**The Save Command:**
```bash
pflow workflow save /path/to/your-workflow.json \
  workflow-name \
  "Brief description of what it does" \
  --generate-metadata
```

**What This Command Does:**
1. Validates your workflow one final time
2. Wraps it in required metadata structure (adds "ir" key)
3. Generates keywords and capabilities (LLM-powered)
4. Adds version, timestamps, and other metadata
5. Saves to ~/.pflow/workflows/workflow-name.json
6. Makes it executable by name from anywhere

**Arguments:**
- `/path/to/your-workflow.json` - Your development format file
- `workflow-name` - How you'll execute it (no spaces, use hyphens)
- `"description"` - Brief description for discovery
- `--generate-metadata` - **Recommended** - Enables workflow discovery

**Flags:**
- `--force` - Overwrite if workflow name already exists
- `--delete-draft` - Remove source file after successful save

**Example:**
```bash
# Save your tested workflow
pflow workflow save /tmp/api-analyzer.json \
  api-analyzer \
  "Fetches and analyzes API data with custom metrics" \
  --generate-metadata

# Output:
# ✓ Saved workflow 'api-analyzer' to library
#   Location: /Users/you/.pflow/workflows/api-analyzer.json
#   ✨ Execute with: pflow api-analyzer api_url=<value> ...

# Now use it anywhere by name
pflow api-analyzer api_url="https://api.example.com" limit=100
```

**Verification:**
After saving, verify it works:
```bash
# List your saved workflows
pflow workflow list

# Test execution by name
pflow workflow-name param=value

# If you get KeyError: 'ir', the workflow wasn't saved properly
# Solution: Re-save it with the command above
```

🔴 **DO NOT:**
- Manually copy files to ~/.pflow/workflows/
- Edit files in ~/.pflow/workflows/ directly
- Try to create the metadata wrapper yourself

✅ **ALWAYS:**
- Use `pflow workflow save` command
- Let pflow manage the metadata structure
- Test execution by name after saving
```

---

## Summary of Key Improvements Needed

| Priority | Issue | Current State | Recommended Fix |
|----------|-------|---------------|-----------------|
| 🔴 Critical | Workflow lifecycle unclear | Scattered mentions | Add dedicated "Lifecycle" section in Part 1 |
| 🔴 Critical | Save command not emphasized | Buried in Step 12 | Move to Part 1, add warnings in validation step |
| 🔴 Critical | Two formats not distinguished | Examples mixed | Label all examples as "Development" or "Saved" format |
| 🟡 Medium | Validation gives false confidence | No clarification of scope | Add warning about what validation doesn't check |
| 🟡 Medium | Manual copying not discouraged | Not mentioned | Add explicit warnings against manual file management |
| 🟡 Medium | File locations unclear | Mentioned but not explained | Add "Workflow File Locations" guide |
| 🟢 Minor | --generate-metadata unexplained | Flag shown but not explained | Add description of what it does |
| 🟢 Minor | No troubleshooting section | Doesn't exist | Add Part 6: Common Errors and Solutions |

---

## Test: Would These Changes Have Prevented My Error?

**My Error Path:**
1. Created workflow JSON ✓
2. Validated successfully ✓
3. Manually copied to ~/.pflow/workflows/ ❌ **ERROR HERE**
4. Tried to execute by name
5. Got KeyError: 'ir'

**With Proposed Changes:**

1. Created workflow JSON ✓
2. Validated successfully ✓
3. **Saw warning in validation output: "A valid workflow can still fail to execute by name if not saved properly. Next step: Save it"**
4. **Read prominently placed Step 12 (or new Part 1 section) explaining the save command**
5. **Saw explicit warning: "DO NOT manually copy files to ~/.pflow/workflows/"**
6. Used `pflow workflow save` ✓
7. Executed by name successfully ✓

**Verdict:** ✅ Yes, these changes would have prevented the error.

---

## Conclusion

The `pflow instructions create` document is thorough in explaining workflow concepts, but needs critical improvements in explaining the **workflow lifecycle** and the **distinction between development and saved formats**. The most important change is adding a prominent section early in the document that explains:

1. What format to create (development format: just inputs/nodes/edges/outputs)
2. How to test (direct file execution)
3. **How to save properly (ONLY via pflow workflow save command)**
4. Why manual file management doesn't work (missing metadata wrapper and "ir" key)

These improvements will prevent users from making the same mistake I did: manually copying files and encountering the cryptic `KeyError: 'ir'` error.

---

**Report prepared by:** Claude (Sonnet 4.5)
**Workflow tested:** slack-qa-sheets-automation
**Error encountered:** KeyError: 'ir' when executing saved workflow by name
**Root cause:** Manual file copy instead of using `pflow workflow save`
**Prevention:** Documentation improvements outlined above
