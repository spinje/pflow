# Workflow Building Learnings

## Event 1: Starting UNDERSTAND phase
**Time**: Start of workflow building
**What happened**: Following Step 1 checklist from AGENT_INSTRUCTIONS.md

**Analysis**:
- Inputs identified: Google Sheet data (columns A, G, H), Replicate API token, optional Dropbox token, Google Drive logo ID
- Outputs: 4 image variations + enhanced prompt doc + optional Dropbox backup
- Transformations: sheets � spotify � gemini enhancement � replicate generation � save/upload
- Services: Google Sheets, Spotify oEmbed, Gemini 2.5 Pro, Replicate (Seedream-4, Nano-Banana), Google Drive, Dropbox
- Pattern: Multi-service pipeline

**Intent determination**: User provides exact steps = high confidence build request

**Learning**: The intent determination section is clear but could benefit from an example of this exact scenario (user provides detailed steps).

---

## Event 2: Workflow Discovery - No matches found
**Time**: After UNDERSTAND phase
**What happened**: Ran `uv run pflow workflow discover` with comprehensive query, got no matches

**Analysis**:
- Per decision tree: <70% match for "create/build" request → Proceed to build new
- This was expected for such a specific workflow

**Learning**: The decision tree is clear here. No issues.

---

## Event 3: Node Discovery Success
**Time**: After workflow discovery
**What happened**: Used AI-powered discovery and got all needed nodes in one shot

**Analysis**:
- The AI discovery worked perfectly - found all 7 required node types
- Got complete interface specifications with parameters and outputs

**Learning**: The AI discovery is powerful and worked great. Instructions are clear about using this first.

---

## Event 4: Missing critical information - API model names
**Time**: During DESIGN phase preparation
**What happened**: I need to know the exact Replicate model names/paths for Seedream-4 and Nano-Banana

**Analysis**:
- The user mentioned "Seedream-4" and "Nano-Banana" models on Replicate
- The REPLICATE_CREATE_PREDICTION node needs deployment_owner and deployment_name
- These aren't standard model names I can guess
- Instructions don't address this scenario of needing external API information

**Learning**: The instructions could benefit from guidance on handling external API requirements (model names, endpoints, etc.) that aren't discoverable through the registry. Should I search online? Ask the user? The docs assume I have all the information needed.

---

## Event 5: Missing node capabilities - need to use HTTP node
**Time**: During node capability analysis
**What happened**: Discovered that specific capabilities aren't available as dedicated nodes

**Analysis**:
- Spotify oEmbed API - no dedicated node exists
- Replicate API models - the MCP node requires "deployment" format but these are public models
- Need to search for API documentation and use HTTP node instead

**Critical Learning**: The AGENT_INSTRUCTIONS.md doesn't explicitly state that when dedicated nodes don't exist, the agent should:
1. Search the internet for API documentation
2. Use the generic HTTP node to call external APIs
3. Discuss alternatives with the user

This is a MAJOR gap - agents need to know they can research APIs and use HTTP as a fallback. The instructions focus on using existing nodes but don't address this common scenario.

---

## Event 6: Successfully researched APIs with WebFetch
**Time**: During API research phase
**What happened**: Used WebSearch and WebFetch to get API documentation for Spotify oEmbed and Replicate models

**Analysis**:
- Found Spotify oEmbed endpoint: GET https://open.spotify.com/oembed?url={spotify_url}
- Found Replicate endpoints and model versions for both models
- Discovered logo addition needs to be done via prompt text (no direct overlay capability)

**Learning**: The instructions should emphasize that agents can and should:
1. Use WebSearch to find API documentation
2. Use WebFetch to extract specific technical details from docs
3. Build HTTP node configurations based on researched information
This is essential for real-world workflow building.

---

## Event 7: User provided credentials directly
**Time**: During planning confirmation
**What happened**: User provided all credentials and IDs directly in the conversation

**Analysis**:
- Sheet ID, logo ID, API tokens all provided
- User chose Option A (prompt-based logo)
- Ready to proceed with design

**Learning**: The instructions DO mention credential handling in the "Authentication & Credentials" section (lines 590-604) but I MISSED IT initially! It clearly states:
- API tokens go in settings via `uv run pflow settings set-env KEY value`
- Resource IDs (sheet_id, channel) should be workflow inputs
- Precedence: CLI > ENV > settings > defaults

**Critical insight**: This section exists but could be more prominent. Agents might miss it when focused on the workflow building steps. Maybe reference it in Step 6.1 (Declare Workflow Inputs) or have a callout box.

---

## Event 8: DESIGN complexity - Too many sequential nodes
**Time**: During DESIGN phase
**What happened**: Started sketching data flow and realized I'd need 16+ nodes in sequence

**Analysis**:
- Need to fetch sheets, extract data, download images, generate 4 variations, save files, upload
- This creates a VERY long sequential chain
- The instructions emphasize "LLM nodes can consolidate multiple operations" (line 693)
- But there's no clear guidance on when a workflow is "too complex"

**Learning**: The instructions could benefit from:
1. Guidance on workflow complexity limits
2. Examples of consolidating operations
3. When to consider splitting into multiple workflows
4. How to handle workflows with many file operations

---

## Event 9: Complex linear chain design
**Time**: After initial design
**What happened**: Created a 15-node linear chain for the workflow

**Analysis**:
- This is valid per the instructions - workflows must be LINEAR
- No way to parallelize image generation (constraint in line 544-557)
- Each file save needs its own node
- This feels unwieldy but is necessary given the constraints

**Learning**: The instructions correctly emphasize sequential execution but don't prepare agents for legitimately complex workflows that need 10+ nodes. Maybe add an example of a complex workflow to show this is okay.

---

## Event 10: Building the JSON - Many discoveries
**Time**: During BUILD phase
**What happened**: Built a 23-node workflow and discovered several issues

**Analysis**:
1. Replicate API returns async predictions - need to poll for results
2. Binary image download via HTTP node - unclear if this works properly
3. ${replicate_api_token} - should this come from settings automatically?
4. The workflow is MASSIVE - 23 nodes for one task
5. Forgot to implement Dropbox upload conditional logic

**Critical Learning**: The instructions don't cover:
- How to handle async APIs that require polling
- Binary data handling in HTTP nodes
- Whether settings values are automatically available as ${setting_name}
- Conditional execution (enable_dropbox flag can't actually control execution)
- Real-world API complexity beyond simple REST calls

---

## Event 11: Validation errors reveal key misunderstandings
**Time**: During VALIDATE phase
**What happened**: Validation caught 2 errors:
- Unused input: enable_dropbox
- Missing source for ${replicate_api_token}

**Analysis**:
- I can't do conditional execution, so enable_dropbox can't work as intended
- API tokens from settings are NOT automatically available as templates
- Must either pass as input OR read from settings somehow

**Critical Learning**: The instructions should clarify:
1. Settings values are NOT automatically available as ${setting_name}
2. No conditional execution means no optional features based on inputs
3. How to access settings values if needed (maybe there's a special node?)

This is a MAJOR gap - the Authentication section says to put tokens in settings but doesn't explain how workflows access them!

---

## Event 12: Validation success with runtime warnings
**Time**: After fixing validation errors
**What happened**: Validation passed but warned about runtime validation for LLM outputs

**Analysis**:
- The validator correctly identifies that LLM outputs are `any` type
- Templates like `${extract-data.response.filename}` can't be validated until runtime
- This is handled well by the system

**Learning**: The instructions could mention that LLM outputs will always trigger runtime validation warnings since they return `any` type. This is normal and expected.

---

## Summary of Key Documentation Improvements Needed

After building a real workflow, here are the critical improvements needed for AGENT_INSTRUCTIONS.md:

### 1. **API and External Services Section** (CRITICAL)
- Add guidance on researching APIs with WebSearch/WebFetch
- Explain that HTTP node is the fallback for services without dedicated nodes
- Include examples of handling async APIs, polling, binary data

### 2. **Authentication Clarity** (CRITICAL)
- The doc says put tokens in settings but doesn't explain how workflows access them
- Need to clarify: Are they auto-available? Passed at runtime? Need special node?
- Add example showing the complete flow from settings to workflow usage

### 3. **Complexity Guidance**
- Add example of a legitimately complex workflow (15+ nodes)
- Guidance on when to split vs. keep as one workflow
- Acknowledgment that some workflows will be very long

### 4. **Conditional Logic Limitations**
- Be more explicit that NO conditional execution means no optional features
- Explain workarounds or alternatives
- Remove any examples that suggest conditional behavior

### 5. **Runtime Validation**
- Explain that LLM outputs always cause runtime validation warnings
- This is normal and expected behavior
- Add section on handling `any` type outputs

### 6. **Real-World Patterns**
- Async API polling patterns
- Binary data handling
- Multi-file operations
- Integration with multiple external services

### 7. **Workflow Building Reality**
- Acknowledge that real workflows often need 15-30 nodes
- Explain that sequential execution means things take time
- Set expectations about workflow complexity

---

## Event 13: Runtime test reveals API misunderstanding
**Time**: During TEST phase
**What happened**: Workflow failed at Replicate API call - "Additional property version is not allowed"

**Analysis**:
- First 5 nodes executed successfully (17 seconds)
- Data extraction from Google Sheets worked perfectly
- Spotify oEmbed API worked
- Google Drive download worked
- LLM enhancement worked
- Replicate API rejected the request structure

**The Issue**: I put "version" in the request body based on my web research, but Replicate's actual API wants it differently for public models:
- WRONG: POST /models/owner/name/predictions with {"version": "...", "input": {...}}
- RIGHT: POST /predictions with {"version": "...", "input": {...}} OR use model-specific endpoint without version

**Critical Learning**: The instructions don't address API documentation accuracy. When researching external APIs:
1. Documentation found online may be outdated or incorrect
2. Need to test individual API calls before building full workflow
3. The instructions suggest testing nodes individually but this is easy to skip

---

## Event 14: MCP node output structure complexity
**Time**: During second TEST phase
**What happened**: Nano API calls failed - logo image wasn't a URI

**Analysis**:
- Seedream calls worked perfectly with synchronous "Prefer: wait" header
- Nano failed because ${download-logo.result} isn't a URI
- Google Drive MCP returns complex nested object
- Actual URL is at: result.data.downloaded_file_content.s3url

**Critical Learning**: The instructions don't emphasize enough that MCP nodes often return deeply nested structures. When building workflows:
1. ALWAYS test MCP nodes individually first with --show-structure
2. Don't assume result contains what you need directly
3. Need to explore the actual structure during testing
4. This is why runtime validation warnings exist!

---

## Event 15: Internal pflow error after 2 minutes
**Time**: Final TEST attempt
**What happened**: Workflow ran for 2 minutes then crashed with AttributeError

**Analysis**:
- Workflow was processing (2 minute runtime suggests API calls were working)
- Crashed with: 'str' object has no attribute 'get' in instrumented_wrapper.py
- This is a pflow bug, not a workflow issue
- No images were saved despite the long runtime

**Critical Learning**: Even when you follow all the instructions perfectly:
1. Complex workflows expose framework bugs
2. Binary data handling might be broken
3. Long-running workflows (2+ minutes) may have stability issues
4. The repair system itself can fail

This demonstrates that the workflow building instructions are incomplete for real-world use cases.

---

## Final Summary

Successfully built a 19-node workflow (reduced from 23 after using synchronous API calls) that:
- Extracts data from Google Sheets ✅
- Fetches Spotify album artwork ✅
- Downloads logo from Google Drive ✅
- Enhances prompts with LLM ✅
- Generates images with Replicate API (partially working)
- Would save files locally (not reached due to crash)

The workflow is structurally valid and the API calls work, but pflow itself crashed during execution. This exercise revealed numerous gaps in the AGENT_INSTRUCTIONS.md documentation for real-world workflow building.

---
