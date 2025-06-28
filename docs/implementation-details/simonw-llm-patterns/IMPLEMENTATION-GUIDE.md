# Implementation Guide: Integrating LLM Patterns into pflow

This guide provides concrete, actionable steps for implementing Simon Willison's patterns in pflow, with code examples that respect pocketflow's architecture.

## Quick Start Checklist

```bash
# 1. Update dependencies
# pyproject.toml
dependencies = [
    "llm>=0.19.0",              # LLM functionality
    "click-default-group>=1.2.4", # Default command pattern
    "pocketflow==0.1.0",         # Core framework
    # existing deps...
]

# 2. Install
uv pip install -e .

# 3. Configure LLM
export OPENAI_API_KEY="your-key"
# or
llm keys set openai
```

## Task-Specific Implementations

### Task 2: Basic CLI Setup

**Current:** Basic click group
**Enhanced:** Professional CLI with default command

```python
# src/pflow/cli.py
import click
import sys
import signal
from click_default_group import DefaultGroup

def setup_shell_integration():
    """Set up Unix signal handlers."""
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(130))  # Ctrl+C
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # Broken pipe

@click.group(cls=DefaultGroup, default="run", default_if_no_args=True)
@click.version_option(version="0.1.0", prog_name="pflow")
@click.option('-v', '--verbose', is_flag=True, help='Verbose output')
@click.pass_context
def cli(ctx, verbose):
    """pflow - Plan Once, Run Forever.

    Natural language to deterministic workflows.
    """
    setup_shell_integration()

    # Initialize context
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['shared'] = {}  # Shared store for flow execution

# Now supports both:
# pflow "summarize this"       # Default 'run' command
# pflow run "summarize this"   # Explicit
# pflow registry list          # Other commands
```

### Task 8: Shell Pipe Integration

**Complete implementation with pocketflow integration:**

```python
# src/pflow/core/shell_integration.py
import sys
import os
import select

class ShellIntegration:
    """Handle Unix pipes and shell integration for pflow."""

    @staticmethod
    def is_stdin_piped():
        """Check if stdin has piped data."""
        return not sys.stdin.isatty()

    @staticmethod
    def has_stdin_data():
        """Check if stdin has data available (non-blocking)."""
        if sys.stdin.isatty():
            return False
        return select.select([sys.stdin], [], [], 0.0)[0]

    @staticmethod
    def read_stdin():
        """Read all stdin content."""
        if not sys.stdin.isatty():
            return sys.stdin.read()
        return None

    @staticmethod
    def populate_shared_store(shared):
        """Populate shared store with stdin if available."""
        stdin_content = ShellIntegration.read_stdin()
        if stdin_content:
            shared["stdin"] = stdin_content
            return True
        return False

    @staticmethod
    def safe_output(text, file=sys.stdout):
        """Output text safely, handling encoding issues."""
        if text is None:
            return

        try:
            print(text, file=file)
        except (BrokenPipeError, IOError):
            # Handle broken pipe gracefully
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
            sys.exit(0)
        except UnicodeEncodeError:
            # Handle encoding issues
            safe_text = text.encode('utf-8', errors='replace').decode('utf-8')
            print(safe_text, file=file)

# Usage in CLI
@cli.command()
@click.argument('workflow', nargs=-1)
@click.pass_context
def run(ctx, workflow):
    """Run a workflow from natural language or CLI syntax."""
    shared = ctx.obj['shared']

    # Check for piped input
    if ShellIntegration.populate_shared_store(shared):
        if ctx.obj['verbose']:
            click.echo(f"Received {len(shared['stdin'])} bytes from stdin", err=True)

    # Workflow execution...

    # Output for pipe chaining
    if "response" in shared:
        ShellIntegration.safe_output(shared["response"])
```

### Task 12: LLM Node Implementation

**Correct implementation following pocketflow patterns:**

```python
# src/pflow/nodes/llm_node.py
from pocketflow import Node
import llm
from typing import Optional, Dict, Any

class LLMNode(Node):
    """
    General-purpose LLM node using Simon Willison's llm library.

    Reads from shared store:
    - prompt or text or stdin: The input text
    - system (optional): System prompt
    - images (optional): List of image paths

    Writes to shared store:
    - response: The LLM's response
    - text: Same as response (for chaining)
    - llm_usage: Token usage statistics
    - llm_model: Model used
    """

    def __init__(self,
                 model: str = "gpt-4o-mini",
                 system: Optional[str] = None,
                 temperature: Optional[float] = None,
                 max_retries: int = 3,
                 **kwargs):
        # Initialize Node with retry capability
        super().__init__(max_retries=max_retries)

        self.model_name = model
        self.default_system = system
        self.options = {}

        if temperature is not None:
            self.options['temperature'] = temperature

        # Store any additional model-specific options
        self.options.update(kwargs)

    def prep(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """Extract prompt and context from shared store."""
        # Natural interface - check multiple possible keys
        prompt = (
            shared.get("prompt") or
            shared.get("text") or
            shared.get("stdin", "")
        )

        if not prompt:
            raise ValueError(
                "No prompt found in shared store. "
                "Checked keys: 'prompt', 'text', 'stdin'"
            )

        # System prompt can come from shared or node config
        system = shared.get("system", self.default_system)

        # Handle attachments for multimodal models
        attachments = []
        if "images" in shared:
            images = shared["images"]
            if isinstance(images, str):
                images = [images]

            for img_path in images:
                try:
                    attachments.append(llm.Attachment(path=img_path))
                except Exception as e:
                    if self.params.get('verbose'):
                        print(f"Warning: Could not load image {img_path}: {e}")

        return {
            "prompt": prompt,
            "system": system,
            "attachments": attachments
        }

    def exec(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        """Execute LLM call using llm library."""
        try:
            # Get model from llm library
            model = llm.get_model(self.model_name)

            # Build prompt arguments
            prompt_args = {
                "prompt": prep_res["prompt"],
                **self.options
            }

            if prep_res["system"]:
                prompt_args["system"] = prep_res["system"]

            if prep_res["attachments"]:
                prompt_args["attachments"] = prep_res["attachments"]

            # Execute prompt
            response = model.prompt(**prompt_args)

            return {
                "text": response.text(),
                "usage": response.usage() or {},
                "model": str(model.model_id)
            }

        except llm.UnknownModelError as e:
            # Provide helpful error message
            available = [m.model_id for m in llm.get_models()]
            raise ValueError(
                f"Unknown model: {self.model_name}\n"
                f"Available models: {', '.join(available[:5])}..."
                f"\nRun 'llm models' to see all available models."
            ) from e

    def exec_fallback(self, prep_res: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
        """Fallback strategy - try a simpler model."""
        if self.model_name != "gpt-4o-mini" and "rate limit" in str(exc).lower():
            # Try fallback model
            original = self.model_name
            self.model_name = "gpt-4o-mini"

            try:
                result = self.exec(prep_res)
                result["model"] = f"{result['model']} (fallback from {original})"
                return result
            except Exception:
                # Restore original model name and re-raise
                self.model_name = original
                raise exc

        # No fallback available
        raise exc

    def post(self, shared: Dict[str, Any], prep_res: Dict[str, Any],
             exec_res: Dict[str, Any]) -> str:
        """Store results in shared store."""
        # Primary output
        shared["response"] = exec_res["text"]

        # Also store as 'text' for easy chaining
        shared["text"] = exec_res["text"]

        # Metadata
        shared["llm_usage"] = exec_res["usage"]
        shared["llm_model"] = exec_res["model"]

        # Token count for cost tracking
        if "total_tokens" in exec_res["usage"]:
            shared["total_tokens"] = shared.get("total_tokens", 0) + exec_res["usage"]["total_tokens"]

        # Return default action
        return "default"
```

### Task 15: LLM Client for Planning

**Replace entire task - just use llm directly:**

```python
# src/pflow/planning/llm_client.py
import llm
import json
from typing import Optional

def call_llm_for_planning(prompt: str,
                         model: str = "claude-3-5-sonnet-latest",
                         temperature: float = 0.7) -> str:
    """
    Call LLM for workflow planning using llm library.

    This is a thin wrapper that handles JSON parsing and retries.
    """
    system_prompt = """You are a workflow planner for pflow.
    Generate valid JSON IR format for workflows.
    Only output JSON, no explanations."""

    try:
        llm_model = llm.get_model(model)
        response = llm_model.prompt(
            prompt,
            system=system_prompt,
            temperature=temperature
        )

        # Validate JSON
        result = response.text().strip()

        # Extract JSON if wrapped in markdown
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            result = result.split("```")[1].split("```")[0].strip()

        # Validate it's valid JSON
        json.loads(result)
        return result

    except json.JSONDecodeError:
        # Retry with more explicit prompt
        retry_prompt = f"{prompt}\n\nPlease output ONLY valid JSON, no other text."
        return call_llm_for_planning(retry_prompt, model="gpt-4o-mini", temperature=0.3)

    except Exception as e:
        # Fallback to simpler model
        if model != "gpt-4o-mini":
            return call_llm_for_planning(prompt, model="gpt-4o-mini", temperature=0.5)
        raise

# Usage in planner
def generate_workflow_ir(user_request: str, node_context: str) -> dict:
    """Generate workflow IR from natural language request."""
    prompt = f"""
Available nodes:
{node_context}

User request: {user_request}

Generate a workflow as JSON IR with this structure:
{{
    "nodes": [...],
    "edges": [...],
    "start_node": "..."
}}
"""

    json_str = call_llm_for_planning(prompt)
    return json.loads(json_str)
```

### Task 23: Execution Tracing

**Adapted for pocketflow's execution model:**

```python
# src/pflow/runtime/tracing.py
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

class ExecutionTracer:
    """Trace pocketflow execution for debugging and cost analysis."""

    def __init__(self, run_id: str, verbose: bool = False):
        self.run_id = run_id
        self.verbose = verbose
        self.start_time = time.time()
        self.events = []
        self.node_stack = []  # Track nested flows

    def flow_start(self, flow_name: str):
        """Record flow execution start."""
        event = {
            "type": "flow_start",
            "name": flow_name,
            "timestamp": time.time(),
            "depth": len(self.node_stack)
        }
        self.events.append(event)
        self.node_stack.append(flow_name)

        if self.verbose:
            indent = "  " * event["depth"]
            self._output(f"{indent}→ Flow: {flow_name}")

    def node_start(self, node_class: str, shared_snapshot: Dict[str, Any]):
        """Record node execution start."""
        # Snapshot relevant shared store state
        safe_snapshot = self._sanitize_shared(shared_snapshot)

        event = {
            "type": "node_start",
            "class": node_class,
            "timestamp": time.time(),
            "shared_keys": list(safe_snapshot.keys()),
            "depth": len(self.node_stack)
        }
        self.events.append(event)

        if self.verbose:
            indent = "  " * event["depth"]
            self._output(f"{indent}[{self._elapsed()}] → {node_class}")
            self._output(f"{indent}  Keys: {', '.join(event['shared_keys'])}")

    def node_complete(self, node_class: str, action: str,
                     shared_before: Dict[str, Any],
                     shared_after: Dict[str, Any]):
        """Record node completion with shared store changes."""
        # Calculate what changed
        added_keys = set(shared_after.keys()) - set(shared_before.keys())
        modified_keys = {
            k for k in shared_before.keys() & shared_after.keys()
            if shared_before[k] != shared_after[k]
        }

        event = {
            "type": "node_complete",
            "class": node_class,
            "timestamp": time.time(),
            "action": action,
            "added_keys": list(added_keys),
            "modified_keys": list(modified_keys),
            "depth": len(self.node_stack)
        }

        # Track token usage if LLM node
        if "llm_usage" in shared_after:
            usage = shared_after["llm_usage"]
            event["tokens"] = usage.get("total_tokens", 0)
            event["cost"] = self._estimate_cost(
                usage,
                shared_after.get("llm_model", "unknown")
            )

        self.events.append(event)

        if self.verbose:
            indent = "  " * event["depth"]
            duration = time.time() - self._last_start_time()
            self._output(f"{indent}  ✓ {duration:.2f}s → {action}")

            if added_keys or modified_keys:
                changes = list(added_keys) + [f"*{k}" for k in modified_keys]
                self._output(f"{indent}  Δ: {', '.join(changes)}")

            if "cost" in event:
                self._output(f"{indent}  💰 ${event['cost']:.4f}")

    def flow_complete(self, flow_name: str):
        """Record flow completion."""
        if self.node_stack and self.node_stack[-1] == flow_name:
            self.node_stack.pop()

        event = {
            "type": "flow_complete",
            "name": flow_name,
            "timestamp": time.time(),
            "depth": len(self.node_stack)
        }
        self.events.append(event)

        if self.verbose:
            indent = "  " * event["depth"]
            self._output(f"{indent}← Flow: {flow_name}")

    def save(self) -> Path:
        """Save trace to file."""
        trace_dir = Path.home() / ".pflow" / "traces"
        trace_dir.mkdir(parents=True, exist_ok=True)

        trace_file = trace_dir / f"{self.run_id}.json"

        # Calculate summary statistics
        total_duration = time.time() - self.start_time
        total_tokens = sum(e.get("tokens", 0) for e in self.events)
        total_cost = sum(e.get("cost", 0) for e in self.events)

        trace_data = {
            "run_id": self.run_id,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "duration": total_duration,
            "summary": {
                "total_tokens": total_tokens,
                "total_cost": total_cost,
                "node_executions": len([e for e in self.events if e["type"] == "node_complete"])
            },
            "events": self.events
        }

        with open(trace_file, "w") as f:
            json.dump(trace_data, f, indent=2)

        if self.verbose:
            self._output(f"\nExecution Summary:")
            self._output(f"  Duration: {total_duration:.2f}s")
            self._output(f"  Tokens: {total_tokens:,}")
            self._output(f"  Cost: ${total_cost:.4f}")
            self._output(f"  Trace: {trace_file}")

        return trace_file

    def _elapsed(self) -> str:
        """Get elapsed time as string."""
        return f"{time.time() - self.start_time:.1f}s"

    def _last_start_time(self) -> float:
        """Get timestamp of last start event."""
        for event in reversed(self.events):
            if event["type"] in ["node_start", "flow_start"]:
                return event["timestamp"]
        return self.start_time

    def _sanitize_shared(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive data from shared store snapshot."""
        # Don't include actual values, just keys and types
        return {k: type(v).__name__ for k, v in shared.items()}

    def _estimate_cost(self, usage: Dict[str, Any], model: str) -> float:
        """Estimate cost from token usage."""
        # Rough estimates per 1K tokens
        rates = {
            "gpt-4": 0.03,
            "gpt-4o": 0.005,
            "gpt-4o-mini": 0.00015,
            "gpt-3.5-turbo": 0.0015,
            "claude-3-5-sonnet": 0.003,
            "claude-3-haiku": 0.00025
        }

        # Find matching rate
        rate = 0.001  # default
        for model_prefix, model_rate in rates.items():
            if model_prefix in model.lower():
                rate = model_rate
                break

        total_tokens = usage.get("total_tokens", 0)
        return (total_tokens / 1000) * rate

    def _output(self, text: str):
        """Output trace information to stderr."""
        print(text, file=sys.stderr)

# Integration with pocketflow execution
class TracedNode(Node):
    """Wrapper to add tracing to any node."""

    def __init__(self, node: Node, tracer: ExecutionTracer):
        super().__init__()
        self.wrapped_node = node
        self.tracer = tracer

    def _run(self, shared: Dict[str, Any]) -> str:
        # Snapshot before
        shared_before = dict(shared)

        # Trace start
        self.tracer.node_start(self.wrapped_node.__class__.__name__, shared)

        # Execute wrapped node
        action = self.wrapped_node._run(shared)

        # Trace completion
        self.tracer.node_complete(
            self.wrapped_node.__class__.__name__,
            action,
            shared_before,
            shared
        )

        return action
```

### Task 29: Comprehensive Test Suite

**Testing patterns adapted for pocketflow:**

```python
# tests/conftest.py
import pytest
from click.testing import CliRunner
from pathlib import Path
import json

@pytest.fixture
def runner():
    """Provide CliRunner for testing CLI commands."""
    return CliRunner()

@pytest.fixture
def isolated_env(runner):
    """Provide isolated filesystem with test environment."""
    with runner.isolated_filesystem():
        # Set up test environment
        import os
        os.environ["PFLOW_HOME"] = str(Path.cwd() / "test_home")
        os.environ["LLM_USER_PATH"] = str(Path.cwd() / "test_home")

        # Create test directories
        Path("test_home").mkdir(exist_ok=True)

        yield runner

@pytest.fixture
def sample_workflow():
    """Provide a sample workflow IR."""
    return {
        "nodes": [
            {
                "id": "read1",
                "type": "read-file",
                "params": {"file_path": "input.txt"}
            },
            {
                "id": "llm1",
                "type": "llm",
                "params": {"model": "gpt-4o-mini"}
            },
            {
                "id": "write1",
                "type": "write-file",
                "params": {"file_path": "output.txt"}
            }
        ],
        "edges": [
            {"from": "read1", "to": "llm1"},
            {"from": "llm1", "to": "write1"}
        ],
        "start_node": "read1"
    }

# tests/test_cli_integration.py
import vcr
from pathlib import Path

def test_basic_workflow_execution(runner, isolated_env, sample_workflow):
    """Test end-to-end workflow execution."""
    # Create test files
    Path("input.txt").write_text("Hello, World!")
    Path("workflow.json").write_text(json.dumps(sample_workflow))

    # Execute workflow
    with vcr.use_cassette('fixtures/basic_workflow.yaml'):
        result = runner.invoke(cli, ['run', '--file', 'workflow.json'])

    assert result.exit_code == 0
    assert Path("output.txt").exists()

    # Verify LLM processed the content
    output = Path("output.txt").read_text()
    assert len(output) > len("Hello, World!")

def test_pipe_integration(runner, isolated_env):
    """Test Unix pipe handling."""
    # Create simple LLM-only workflow
    workflow = {
        "nodes": [{"id": "llm1", "type": "llm", "params": {}}],
        "edges": [],
        "start_node": "llm1"
    }
    Path("llm.json").write_text(json.dumps(workflow))

    # Test piped input
    with vcr.use_cassette('fixtures/pipe_test.yaml'):
        result = runner.invoke(
            cli,
            ['run', '--file', 'llm.json'],
            input="Summarize: The quick brown fox jumps over the lazy dog."
        )

    assert result.exit_code == 0
    assert "summary" in result.output.lower() or "fox" in result.output.lower()

def test_natural_language_planning(runner, isolated_env):
    """Test natural language to workflow compilation."""
    with vcr.use_cassette('fixtures/nl_planning.yaml'):
        result = runner.invoke(
            cli,
            ['run', 'read file test.txt and summarize it']
        )

    # Should either execute or show planned workflow
    assert result.exit_code == 0
    assert "read" in result.output.lower() or "summary" in result.output.lower()

def test_cli_syntax_parsing(runner, isolated_env):
    """Test CLI pipe syntax parsing."""
    # Create test file
    Path("data.txt").write_text("Test content for processing")

    with vcr.use_cassette('fixtures/cli_syntax.yaml'):
        result = runner.invoke(
            cli,
            ['run', 'read-file', '--path=data.txt', '>>', 'llm', '--prompt=Summarize']
        )

    assert result.exit_code == 0
    # Output should be the LLM's summary
    assert len(result.output.strip()) > 0

def test_error_handling(runner, isolated_env):
    """Test error handling and messages."""
    # Test missing file
    workflow = {
        "nodes": [{"id": "read1", "type": "read-file", "params": {"file_path": "missing.txt"}}],
        "edges": [],
        "start_node": "read1"
    }
    Path("bad.json").write_text(json.dumps(workflow))

    result = runner.invoke(cli, ['run', '--file', 'bad.json'])

    assert result.exit_code != 0
    assert "error" in result.output.lower() or "not found" in result.output.lower()

# tests/test_llm_node.py
from pflow.nodes.llm_node import LLMNode
import pytest

def test_llm_node_prep():
    """Test LLM node preparation phase."""
    node = LLMNode(model="gpt-4o-mini")

    # Test with prompt
    shared = {"prompt": "Test prompt"}
    prep_res = node.prep(shared)
    assert prep_res["prompt"] == "Test prompt"

    # Test fallback to text
    shared = {"text": "Test text"}
    prep_res = node.prep(shared)
    assert prep_res["prompt"] == "Test text"

    # Test fallback to stdin
    shared = {"stdin": "Test stdin"}
    prep_res = node.prep(shared)
    assert prep_res["prompt"] == "Test stdin"

    # Test missing prompt
    shared = {}
    with pytest.raises(ValueError, match="No prompt found"):
        node.prep(shared)

def test_llm_node_post():
    """Test LLM node post-processing phase."""
    node = LLMNode()
    shared = {}

    exec_res = {
        "text": "LLM response",
        "usage": {"total_tokens": 100},
        "model": "gpt-4o-mini"
    }

    action = node.post(shared, {}, exec_res)

    assert shared["response"] == "LLM response"
    assert shared["text"] == "LLM response"  # For chaining
    assert shared["llm_usage"]["total_tokens"] == 100
    assert shared["llm_model"] == "gpt-4o-mini"
    assert action == "default"
```

## Migration Path

### Week 1: Foundation
1. Add dependencies to `pyproject.toml`
2. Update CLI with default command pattern
3. Implement shell integration
4. Create basic LLMNode

### Week 2: Core Features
1. Implement execution tracing
2. Set up VCR testing
3. Add registry commands
4. Create planning integration

### Week 3: Polish
1. Add comprehensive tests
2. Implement error handling
3. Add configuration management
4. Documentation

## Key Principles

1. **Respect pocketflow's patterns**: Always use prep/exec/post
2. **Natural interfaces**: Use intuitive shared store keys
3. **Fail fast**: Clear errors in prep phase
4. **Test everything**: Use CliRunner and VCR
5. **Unix citizenship**: Proper signal and pipe handling

## Common Pitfalls to Avoid

1. **Don't access shared in exec()**: Only in prep() and post()
2. **Don't forget action strings**: Return from post() for flow control
3. **Don't skip error handling**: Use exec_fallback() for graceful degradation
4. **Don't ignore stdin**: Always check for piped input
5. **Don't hardcode models**: Make them configurable

## Verification Checklist

- [ ] All nodes follow prep/exec/post pattern
- [ ] Shell integration handles pipes correctly
- [ ] Tests use CliRunner with proper fixtures
- [ ] LLM calls happen only in exec() phase
- [ ] Error messages are clear and actionable
- [ ] Tracing provides useful debugging info
- [ ] Configuration follows hierarchical pattern

This implementation guide provides concrete, working code that integrates Simon Willison's patterns while fully respecting pocketflow's architecture.
