# Task 42: Claude Code Agentic Node - Critical Implementation Insights

This document contains essential implementation guidance not captured in the spec or task file. Read this before implementing.

## 🚨 Critical SDK Facts

### What the SDK Actually Provides

```python
from claude_code_sdk import query, ClaudeCodeOptions
from claude_code_sdk.exceptions import (
    CLINotFoundError,      # CLI not installed
    CLIConnectionError,    # Connection/auth issues
    ProcessError,          # CLI process failed with exit code
    ClaudeSDKError         # Base exception
)
from claude_code_sdk.types import (
    AssistantMessage,      # Response container
    TextBlock,            # Text content
    ToolUseBlock          # Tool invocation details
)
```

### Actual ClaudeCodeOptions Parameters (Verified)

```python
@dataclass
class ClaudeCodeOptions:
    # These exist:
    model: str | None = None
    max_thinking_tokens: int = 8000  # NOT max_tokens!
    allowed_tools: list[str] = []
    system_prompt: str | None = None
    append_system_prompt: str | None = None
    max_turns: int | None = None
    cwd: str | Path | None = None  # Working directory
    add_dirs: list[str | Path] = []
    permission_mode: str | None = None  # "acceptEdits" for automation

    # These do NOT exist:
    # ❌ temperature - not supported
    # ❌ timeout - must be handled at asyncio level
    # ❌ max_tokens - it's max_thinking_tokens
```

## 🎯 Async-to-Sync Pattern (From MCP Node)

This is the EXACT pattern you should follow:

```python
def exec(self, prep_res: dict[str, Any]) -> str:
    """Execute synchronously by wrapping async."""
    # NO try/except here - let exceptions bubble up for retry mechanism!
    result = asyncio.run(self._exec_async(prep_res), debug=False)
    return "success" if result else "error"

async def _exec_async(self, prep_res: dict[str, Any]) -> dict:
    """Actual async implementation."""
    options = prep_res["options"]
    prompt = prep_res["prompt"]

    # Handle timeout at asyncio level (Python version aware)
    timeout_context = getattr(asyncio, "timeout", None)
    if timeout_context is not None:
        # Python 3.11+
        async with timeout_context(300):  # 300 second timeout
            return await self._call_claude(prompt, options)
    else:
        # Python 3.10
        return await asyncio.wait_for(
            self._call_claude(prompt, options),
            timeout=300
        )

async def _call_claude(self, prompt: str, options: ClaudeCodeOptions) -> dict:
    """Call Claude Code SDK."""
    result = {"text": "", "tool_uses": []}

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    result["text"] += block.text
                elif isinstance(block, ToolUseBlock):
                    result["tool_uses"].append({
                        "name": block.name,
                        "input": block.input
                    })

    return result
```

## 📋 Schema-to-Prompt Conversion

This is the core innovation - convert output schema to system prompt instructions:

```python
def _build_schema_prompt(self, output_schema: dict) -> str:
    """Convert output schema to JSON format instructions."""
    if not output_schema:
        return ""

    # Build JSON template
    json_template = {}
    descriptions = []

    for key, config in output_schema.items():
        type_str = config.get("type", "str")
        desc = config.get("description", f"Value for {key}")

        # Add to template
        json_template[key] = f"<{type_str}: {desc}>"
        descriptions.append(f"  - {key}: {desc}")

    # Create instruction prompt
    prompt = (
        "IMPORTANT: You must structure your final response as valid JSON.\n"
        "After completing your analysis and work, provide a JSON object with these exact keys:\n\n"
        f"{json.dumps(json_template, indent=2)}\n\n"
        "The JSON should be in a code block like this:\n"
        "```json\n"
        "{\n"
        "  // your actual values here\n"
        "}\n"
        "```\n\n"
        "Field descriptions:\n" + "\n".join(descriptions)
    )

    return prompt
```

## 🔍 JSON Extraction Strategies

Multiple strategies to extract JSON from Claude's response:

```python
import json
import re

def _extract_json(self, text: str) -> dict | None:
    """Extract JSON from Claude's response with multiple strategies."""

    # Strategy 1: JSON in code block
    code_block_pattern = r'```(?:json)?\s*\n(.*?)\n```'
    matches = re.findall(code_block_pattern, text, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # Strategy 2: Raw JSON object
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, text)
    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # Strategy 3: Last resort - find JSON-like structure
    try:
        # Find last { and matching }
        start = text.rfind('{')
        if start != -1:
            depth = 0
            for i, char in enumerate(text[start:], start):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        potential_json = text[start:i+1]
                        return json.loads(potential_json)
    except:
        pass

    return None  # Failed to extract
```

## 🔒 Security Patterns

### Authentication Check

```python
def _check_authentication(self) -> None:
    """Verify Claude CLI is installed and authenticated."""
    import subprocess

    # Check CLI installed
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode != 0:
            raise CLINotFoundError("Claude Code CLI not found")
    except FileNotFoundError:
        raise CLINotFoundError(
            "Claude Code CLI is not installed. "
            "Install with: npm install -g @anthropic-ai/claude-code"
        )

    # Check authentication
    result = subprocess.run(
        ["claude", "doctor"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False
    )

    if result.returncode != 0 or "not authenticated" in result.stdout.lower():
        raise ValueError(
            "Not authenticated with Claude Code. "
            "Run: claude auth login"
        )
```

### Dangerous Bash Patterns to Block

```python
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",           # Recursive root deletion
    r"rm\s+-rf\s+~",           # Home directory deletion
    r":\(\)\{\s*:\|\s*:\s*&\s*\};",  # Fork bomb
    r">\s*/dev/sda",           # Disk overwrite
    r"chmod\s+777\s+/",        # Overly permissive root
    r"curl.*\|.*sh",           # Remote code execution
    r"wget.*\|.*bash",         # Remote code execution
]

def _validate_bash_safety(self, command: str) -> None:
    """Check if bash command is safe to execute."""
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            raise ValueError(f"Dangerous command pattern detected: {pattern}")
```

## 🧪 Testing Patterns

### Mock the SDK Query Function

```python
from unittest.mock import patch, AsyncMock
from claude_code_sdk.types import AssistantMessage, TextBlock

@patch("pflow.nodes.claude.claude_code.query")
async def test_successful_execution(mock_query):
    """Test successful Claude Code execution."""

    # Create mock response
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[
            TextBlock(text='{"result": "success", "details": "Task completed"}')
        ])

    mock_query.return_value = mock_response()

    # Test the node
    node = ClaudeCodeNode()
    # ... rest of test
```

### Mock Authentication Check

```python
@patch("subprocess.run")
def test_auth_check(mock_run):
    """Test authentication verification."""

    # Mock successful auth check
    mock_run.side_effect = [
        Mock(returncode=0),  # claude --version succeeds
        Mock(returncode=0, stdout="Authenticated")  # claude doctor succeeds
    ]

    node = ClaudeCodeNode()
    node._check_authentication()  # Should not raise
```

## ⚠️ Common Pitfalls to Avoid

1. **Don't use temperature** - Parameter doesn't exist in SDK
2. **Don't catch exceptions in exec()** - Let them bubble up for retry mechanism
3. **Don't assume JSON parsing will work** - Always have fallback to raw text
4. **Don't use shell=True in subprocess** - Security risk
5. **Don't forget timeout handling** - Use asyncio timeout wrapper
6. **Don't hardcode tool names** - Use configurable whitelist
7. **Don't trust Claude's output format** - Always validate

## 📊 Retry Strategy

```python
def __init__(self):
    # Conservative retry strategy for expensive API calls
    super().__init__(
        max_retries=2,  # Total of 2 attempts
        wait=1.0        # Wait 1 second between retries
    )
```

**Why conservative?** Each retry costs API credits and time. Better to fail fast with clear error than retry expensive operations.

## 🔄 Integration with Planner

The planner will discover this node and use it like:

```json
{
  "nodes": [
    {
      "id": "analyze_code",
      "type": "claude-code",
      "params": {
        "task": "${user_request}",
        "output_schema": {
          "analysis": {"type": "str", "description": "Code analysis"},
          "recommendations": {"type": "list", "description": "Improvement suggestions"}
        },
        "working_directory": "${project_root}"
      }
    }
  ]
}
```

The node will automatically:
1. Convert the schema to prompt instructions
2. Execute Claude Code with those instructions
3. Parse JSON from response
4. Store in `shared["analysis"]` and `shared["recommendations"]`
5. Fallback to `shared["result"]` if parsing fails

## 🚀 Performance Considerations

- **Default timeout**: 300 seconds (5 minutes)
- **Response size**: Can be several MB for complex tasks
- **Memory usage**: Parse response incrementally if possible
- **API rate limits**: Handle 429 errors gracefully
- **Startup time**: Claude Code CLI has ~2-3 second startup overhead

## 🔮 Future SDK Changes to Watch

1. **Native structured outputs** - SDK may add built-in JSON mode
2. **Temperature parameter** - May be added in future versions
3. **Streaming improvements** - Currently async iteration only
4. **New tools** - More tools beyond Read/Write/Edit/Bash
5. **Better error messages** - Current errors are sometimes cryptic

## 📝 Implementation Checklist

- [ ] Install dependencies: `pip install claude-code-sdk`
- [ ] Verify CLI installed: `npm install -g @anthropic-ai/claude-code`
- [ ] Check authentication: `claude auth login`
- [ ] Implement async-to-sync wrapper exactly as shown
- [ ] Add schema-to-prompt conversion
- [ ] Implement multiple JSON extraction strategies
- [ ] Add subprocess authentication check
- [ ] Include dangerous pattern blocking
- [ ] Write comprehensive tests with mocks
- [ ] Test timeout handling
- [ ] Test schema parsing fallback
- [ ] Document any new tool names discovered
- [ ] Add logging for debugging
- [ ] Validate against spec test criteria

## 💡 Final Wisdom

The key innovation of this node is the **schema-as-system-prompt** approach. This turns an unstructured text generation API into a structured data API through clever prompt engineering. The fallback to raw text ensures we never lose data even when parsing fails.

Remember: Claude Code is expensive and powerful. Be conservative with retries, generous with timeouts, and paranoid about security. The node should be a reliable workhorse, not a clever showpiece.

Good luck with the implementation!