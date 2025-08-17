# 🔍 WorkflowDiscoveryNode

**Call #:** 1  
**Duration:** 0.00s  
**Trace ID:** `daca8a09-ba8e-4313-a4b2-293ac301bd90`  

## 📊 Token Usage

| Type | Count | Percentage |
|------|-------|------------|
| **Prompt** | 482 | 75.7% |
| **Response** | 155 | 24.3% |
| **Total** | 637 | 100% |


**Estimated Cost:** $0.003771 
(Prompt: $0.001446, Response: $0.002325)

## 📝 Prompt

*Length: 2,178 characters, ~324 words*

```

# Discovery Prompt

You are a workflow discovery system that determines if an existing workflow completely satisfies a user request.

<available_workflows>
## Available Nodes

### AI/LLM Operations
### llm
General-purpose LLM node for text processing.

### File Operations
### copy-file
Copy a file to a new location with automatic directory creation.

### delete-file
Delete a file from the filesystem with safety confirmation.

### move-file
Move a file to a new location with automatic directory creation.

### read-file
Read content from a file and add line numbers for display.

### write-file
Write content to a file with automatic directory creation.

### Git Operations
### git-checkout
Create or switch to a git branch.

### git-commit
Create a git commit.

### git-push
Push commits to remote repository.

### git-status
Get git repository status.

### github-create-pr
Create a GitHub pull request.

### github-get-issue
Get GitHub issue details.

### github-list-issues
List GitHub repository issues.

## Available Workflows

### llama-story-generator (workflow)
This workflow uses a large language model (LLM) to generate a short, creative story about llamas and saves the output to a file. It's a versatile tool for quickly producing engaging content on any topic, making it useful for writers, content creators, and educators. The workflow can be customized with different story prompts, model configurations, and output file paths to suit a variety of needs.

### test-12345 (workflow)
</available_workflows>

<user_request>
create a workflow that uses an llm to create a very short story about llamas and saves it to a file
</user_request>

Analyze whether any existing workflow COMPLETELY satisfies this request. A complete match means the workflow does everything the user wants without modification.

Return found=true ONLY if:
1. An existing workflow handles ALL aspects of the request
2. No additional nodes or modifications would be needed
3. The workflow's purpose directly aligns with the user's intent

If any part of the request isn't covered, return found=false to trigger workflow generation.

Be strict - partial matches should return found=false.
```

## 🤖 Response

*Length: 681 characters*

```json
{
  "found": true,
  "confidence": 0.95,
  "reasoning": "The user request is to \"create a workflow that uses an llm to create a very short story about llamas and saves it to a file.\" The available workflow \"llama-story-generator\" is described as \"This workflow uses a large language model (LLM) to generate a short, creative story about llamas and saves the output to a file.\" This is an exact match for the user's requirements: 1) Uses an LLM, 2) Creates a short story about llamas, 3) Saves it to a file. The workflow description explicitly states it does all three things the user requested without any need for modification.",
  "workflow_name": "llama-story-generator"
}
```

## 💭 Analysis Notes

*Add your observations here:*

- [ ] Prompt clarity
- [ ] Response accuracy
- [ ] Token efficiency
- [ ] Potential improvements
