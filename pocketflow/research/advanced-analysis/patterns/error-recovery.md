# Error & Recovery Patterns for pflow

## Overview

This document extracts error handling and recovery patterns from 7 PocketFlow tutorial repositories that are suitable for pflow's CLI-first, deterministic workflow execution model. These patterns focus on batch/CLI mode operation without interactive UI elements.

---

## Pattern: Graceful Fallback with Default Values

- **Found in**: [PocketFlow-Tutorial-Website-Chatbot, Tutorial-Cursor, Tutorial-Cold-Email-Personalization]
- **Error Type**: External API failures, web scraping errors, missing data
- **Recovery Strategy**: Return safe default values instead of crashing
- **Implementation**: Use pocketflow's `exec_fallback` method
- **Code Example**:
```python
class CrawlWebPageNode(BatchNode):
    def exec(self, url_data):
        url_idx, url = url_data
        content, links = crawl_webpage(url)
        return url_idx, content, links

    def exec_fallback(self, url_data, exc):
        # Return safe defaults on failure
        url_idx, url = url_data
        logger.error(f"Failed to crawl {url}: {exc}")
        return url_idx, "Error crawling page", []
```
- **Task Mapping**:
  - Task 11 (File I/O nodes) - Handle file not found gracefully
  - Task 13 (GitHub node) - Handle API failures without crashing
  - Task 14 (CI/Shell nodes) - Continue workflow even if tests fail

---

## Pattern: Built-in Retry with Exponential Backoff

- **Found in**: [PocketFlow-Tutorial-Danganronpa-Simulator, Tutorial-Cold-Email-Personalization, Tutorial-AI-Paul-Graham]
- **Error Type**: Transient network failures, LLM API rate limits
- **Recovery Strategy**: Automatic retry with increasing wait times
- **Implementation**: Use pocketflow's node retry configuration
- **Code Example**:
```python
# Node instantiation with retry config
llm_node = LLMNode(max_retries=3, wait=10)
github_node = GitHubGetIssueNode(max_retries=5, wait=20)

# In flow creation
def create_workflow():
    # Nodes that hit external APIs get retry config
    analyze_node = AnalyzeNode(max_retries=3, wait=10)
    # Local operations don't need retries
    read_file_node = ReadFileNode()  # No retries for local ops

    read_file_node >> analyze_node
    return Flow(start=read_file_node)
```
- **Task Mapping**:
  - Task 12 (LLM node) - Retry on API failures
  - Task 13 (GitHub node) - Retry on network issues
  - Task 25 (Claude-code node) - Handle rate limits gracefully

---

## Pattern: Structured Output Validation

- **Found in**: [PocketFlow-Tutorial-Danganronpa-Simulator, Tutorial-AI-Paul-Graham, Tutorial-Youtube-Made-Simple]
- **Error Type**: Malformed LLM responses, parsing failures
- **Recovery Strategy**: Validate and re-request if invalid
- **Implementation**: Parse structured output (YAML/JSON) with validation
- **Code Example**:
```python
class LLMNode(Node):
    def exec(self, prompt):
        response = call_llm(prompt)

        # Try to parse structured output
        try:
            # Extract YAML from response
            yaml_content = response.split("```yaml")[1].split("```")[0]
            parsed = yaml.safe_load(yaml_content)

            # Validate required fields
            if 'decision' not in parsed:
                raise ValueError("Missing 'decision' field in response")

            return parsed

        except (IndexError, yaml.YAMLError, ValueError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            # Return safe default structure
            return {
                "decision": "continue",
                "reasoning": "Failed to parse response, continuing with default"
            }
```
- **Task Mapping**:
  - Task 12 (LLM node) - Ensure reliable structured output
  - Task 17 (Workflow generation) - Validate generated IR
  - Task 18 (Prompt templates) - Handle template parsing errors

---

## Pattern: Early Parameter Validation

- **Found in**: [Tutorial-Cursor, Tutorial-Codebase-Knowledge, Tutorial-Cold-Email-Personalization]
- **Error Type**: Missing required parameters, invalid input
- **Recovery Strategy**: Fail fast with clear error messages
- **Implementation**: Validate in prep() phase before execution
- **Code Example**:
```python
class GitHubGetIssueNode(Node):
    def prep(self, shared):
        # Check required parameters early
        repo = shared.get("repo") or self.params.get("repo")
        issue_number = shared.get("issue_number") or self.params.get("issue_number")

        if not repo:
            raise ValueError("Missing required parameter: 'repo'")
        if not issue_number:
            raise ValueError("Missing required parameter: 'issue_number'")

        # Validate format
        if not isinstance(issue_number, int) and not issue_number.isdigit():
            raise ValueError(f"Invalid issue number: {issue_number}")

        return repo, int(issue_number)
```
- **Task Mapping**:
  - Task 9 (Shared store validation) - Detect missing keys early
  - Task 11-14 (All nodes) - Validate inputs in prep phase
  - Task 8 (Shell integration) - Validate stdin data

---

## Pattern: Content-Based Result Caching

- **Found in**: [Tutorial-AI-Paul-Graham, Tutorial-Youtube-Made-Simple]
- **Error Type**: Redundant expensive operations
- **Recovery Strategy**: Cache by content hash to avoid re-execution
- **Implementation**: Hash-based cache keys for deterministic results
- **Code Example**:
```python
import hashlib
import json
import os

class LLMNode(Node):
    def __init__(self, cache_dir=".pflow_cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def exec(self, prompt):
        # Generate cache key from prompt
        cache_key = hashlib.sha256(prompt.encode()).hexdigest()
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")

        # Check cache first
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                logger.info(f"Cache hit for prompt hash {cache_key[:8]}")
                return json.load(f)

        # Execute and cache result
        result = call_llm(prompt)

        with open(cache_file, 'w') as f:
            json.dump(result, f)

        return result
```
- **Task Mapping**:
  - Task 24 (Caching system) - Content-based caching pattern
  - Task 12 (LLM node) - Avoid redundant API calls
  - Task 13 (GitHub node) - Cache issue data

---

## Pattern: Batch Error Isolation

- **Found in**: [PocketFlow-Tutorial-Website-Chatbot, Tutorial-Cold-Email-Personalization]
- **Error Type**: Partial batch failures
- **Recovery Strategy**: Process successful items, log failures
- **Implementation**: BatchNode with per-item error handling
- **Code Example**:
```python
class ProcessFilesNode(BatchNode):
    def prep(self, shared):
        return shared["file_paths"]  # List of files to process

    def exec(self, file_path):
        # Process single file
        with open(file_path, 'r') as f:
            return {"path": file_path, "content": f.read()}

    def exec_fallback(self, file_path, exc):
        # Handle single file failure
        logger.error(f"Failed to read {file_path}: {exc}")
        return {"path": file_path, "content": None, "error": str(exc)}

    def post(self, shared, prep_res, exec_res_list):
        # Separate successful and failed results
        successful = [r for r in exec_res_list if "error" not in r]
        failed = [r for r in exec_res_list if "error" in r]

        shared["processed_files"] = successful
        shared["failed_files"] = failed

        # Log summary
        logger.info(f"Processed {len(successful)} files, {len(failed)} failed")
```
- **Task Mapping**:
  - Task 11 (File nodes) - Handle multiple file operations
  - Task 14 (CI/Shell nodes) - Run multiple tests, isolate failures
  - Future: Batch processing patterns

---

## Pattern: Comprehensive Execution Logging

- **Found in**: [All repositories]
- **Error Type**: Debugging and observability needs
- **Recovery Strategy**: Log at key points for post-mortem analysis
- **Implementation**: Strategic logging with context
- **Code Example**:
```python
class WorkflowNode(Node):
    def prep(self, shared):
        logger.info(f"[{self.__class__.__name__}] Starting prep phase")
        logger.debug(f"Shared store keys: {list(shared.keys())}")

        input_data = shared.get("input_key")
        if not input_data:
            logger.error(f"Missing required input_key in shared store")
            raise ValueError("Missing required input")

        logger.info(f"[{self.__class__.__name__}] Prep complete, processing {len(input_data)} items")
        return input_data

    def exec(self, prep_data):
        logger.info(f"[{self.__class__.__name__}] Executing with {prep_data}")
        try:
            result = process_data(prep_data)
            logger.info(f"[{self.__class__.__name__}] Execution successful")
            return result
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] Execution failed: {e}")
            raise

    def post(self, shared, prep_res, exec_res):
        logger.info(f"[{self.__class__.__name__}] Writing results to shared store")
        shared["output_key"] = exec_res
        return "default"
```
- **Task Mapping**:
  - Task 23 (Execution tracing) - Foundation for trace system
  - All node tasks - Standard logging pattern

---

## Pattern: CLI-Friendly Error Messages

- **Found in**: [Tutorial-Cursor, Tutorial-Codebase-Knowledge]
- **Error Type**: User input errors, configuration issues
- **Recovery Strategy**: Clear, actionable error messages to stderr
- **Implementation**: Human-readable errors with fix suggestions
- **Code Example**:
```python
import sys
import click

class FileNode(Node):
    def prep(self, shared):
        file_path = shared.get("file_path")

        if not file_path:
            click.echo("Error: No file path provided", err=True)
            click.echo("Usage: pflow read-file --path=<file>", err=True)
            sys.exit(1)

        if not os.path.exists(file_path):
            click.echo(f"Error: File not found: {file_path}", err=True)
            click.echo(f"Please check the file path and try again", err=True)
            sys.exit(1)

        if not os.access(file_path, os.R_OK):
            click.echo(f"Error: Permission denied reading: {file_path}", err=True)
            click.echo(f"Try: chmod +r {file_path}", err=True)
            sys.exit(1)

        return file_path
```
- **Task Mapping**:
  - Task 2 (CLI setup) - User-friendly error reporting
  - Task 8 (Shell integration) - Proper exit codes
  - All node tasks - Clear error messages

---

## Pattern: State Rollback on Failure

- **Found in**: [PocketFlow-Tutorial-Danganronpa-Simulator]
- **Error Type**: Partial state corruption on failure
- **Recovery Strategy**: Keep original state until success confirmed
- **Implementation**: Copy-on-write pattern for shared store updates
- **Code Example**:
```python
class TransactionalNode(Node):
    def post(self, shared, prep_res, exec_res):
        # Create a copy of the current state
        original_state = shared.get("app_state", {}).copy()

        try:
            # Attempt to update state
            new_state = original_state.copy()
            new_state.update(exec_res)

            # Validate new state
            if not self._validate_state(new_state):
                raise ValueError("Invalid state after update")

            # Commit the change
            shared["app_state"] = new_state
            logger.info("State update successful")

        except Exception as e:
            logger.error(f"State update failed, keeping original: {e}")
            # State remains unchanged on error
            shared["app_state"] = original_state
            # Optionally re-raise or return error action
            return "error"

        return "success"
```
- **Task Mapping**:
  - Task 9 (Shared store safety) - Prevent corruption
  - Task 11-14 (Node implementations) - Safe state updates
  - Future: Transactional workflows

---

## Pattern: Deterministic Failure Modes

- **Found in**: [Tutorial-AI-Paul-Graham, Tutorial-Youtube-Made-Simple]
- **Error Type**: Non-deterministic failures
- **Recovery Strategy**: Make failures predictable and reproducible
- **Implementation**: Remove randomness, use stable defaults
- **Code Example**:
```python
class DeterministicLLMNode(Node):
    def exec(self, prompt):
        try:
            # Force deterministic LLM behavior
            response = call_llm(
                prompt,
                temperature=0,  # No randomness
                seed=42,        # Fixed seed if supported
                max_retries=3   # Fixed retry count
            )
            return response

        except Exception as e:
            # Return deterministic error response
            logger.error(f"LLM call failed after retries: {e}")
            return {
                "error": True,
                "message": "LLM service unavailable",
                "fallback": "Please try again later",
                "timestamp": None  # Don't include time for determinism
            }
```
- **Task Mapping**:
  - Task 12 (LLM node) - Deterministic LLM calls
  - Task 17 (Workflow generation) - Predictable generation
  - All tasks - Ensure reproducible execution

---

## Summary: Best Practices for pflow Error Handling

1. **Fail Fast with Clear Messages**: Validate inputs early in prep() phase
2. **Use Built-in Retries**: Configure retry logic at node instantiation
3. **Return Safe Defaults**: Use exec_fallback for graceful degradation
4. **Log Comprehensively**: Every error should be traceable
5. **Make Errors Deterministic**: Same input = same error behavior
6. **Cache to Avoid Errors**: Reduce external dependencies
7. **Validate Structured Output**: Don't trust LLM responses
8. **Isolate Batch Failures**: Don't let one failure stop the workflow
9. **CLI-Friendly Output**: Clear, actionable error messages
10. **Preserve State Integrity**: Never corrupt the shared store

These patterns ensure pflow workflows are robust, debuggable, and suitable for production CLI usage without requiring interactive intervention.
