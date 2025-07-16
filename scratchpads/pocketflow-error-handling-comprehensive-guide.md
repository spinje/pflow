# PocketFlow Error Handling, Recovery & Retry: Comprehensive Guide

> **Ultra-comprehensive guide to PocketFlow error handling patterns, best practices, and implementation strategies**

## Table of Contents

1. [Core Error Handling Architecture](#core-error-handling-architecture)
2. [Action-Based Error Routing](#action-based-error-routing)
3. [Node-Level Error Handling](#node-level-error-handling)
4. [Flow-Level Error Patterns](#flow-level-error-patterns)
5. [Shared Store Error Communication](#shared-store-error-communication)
6. [Advanced Error Handling Patterns](#advanced-error-handling-patterns)
7. [Best Practices & Guidelines](#best-practices--guidelines)
8. [Common Pitfalls & Anti-Patterns](#common-pitfalls--anti-patterns)
9. [Integration with pflow CLI](#integration-with-pflow-cli)
10. [Reference Implementation Examples](#reference-implementation-examples)

---

## Core Error Handling Architecture

### Framework-Level Error Handling

PocketFlow implements a **node-centric, explicit error handling approach** with these core principles:

#### 1. **Node Lifecycle Error Boundaries**
- **`prep()`**: Handle data access errors (file not found, DB connection issues)
- **`exec()`**: Handle compute errors (LLM API failures, processing errors)
- **`post()`**: Handle data writing errors (disk space, permissions)

*Reference: `pocketflow/docs/core_abstraction/node.md`*

#### 2. **Built-in Retry Mechanism**
```python
# From pocketflow/__init__.py lines 60-76
def _exec(self, prep_res):
    for self.cur_retry in range(self.max_retries):
        try:
            return self.exec(prep_res)
        except Exception as e:
            if self.cur_retry == self.max_retries - 1:
                return self.exec_fallback(prep_res, e)
            if self.wait > 0:
                time.sleep(self.wait)
```

**Key Properties:**
- Only `exec()` method is retried (not `prep()` or `post()`)
- Configurable via `max_retries` (default: 1) and `wait` (default: 0 seconds)
- Final retry failure routes to `exec_fallback()` for graceful degradation
- Current retry attempt accessible via `self.cur_retry`

#### 3. **Flow-Level Error Propagation**
- Flows **do not catch exceptions** from nodes
- Failed nodes without fallback handling **stop the entire flow**
- No built-in flow-level retry or recovery mechanisms
- Errors propagate up to the caller of `flow.run(shared)`

*Reference: `pocketflow/__init__.py` lines 92-108*

---

## Action-Based Error Routing

### Core Routing Mechanism

PocketFlow uses **action strings** returned by nodes to determine flow transitions:

```python
# From pocketflow/__init__.py Flow._orch() method
def _orch(self, shared, params=None):
    curr, p, last_action = copy.copy(self.start_node), (params or {**self.params}), None
    while curr:
        if params is not None:
            curr.set_params(p)
        last_action = curr._run(shared)  # Node returns action string
        curr = copy.copy(self.get_next_node(curr, last_action))  # Route based on action
    return last_action
```

### Error Routing Patterns

#### 1. **Conditional Transitions Syntax**
```python
# Basic routing
node_a >> node_b  # Default transition

# Conditional routing
node_a - "success" >> node_b
node_a - "error" >> error_handler_node
node_a - "retry" >> node_a  # Self-loop for retries
```

#### 2. **Multi-Path Error Handling**
```python
# From text2sql example
execute_sql_node - "error_retry" >> debug_sql_node
debug_sql_node >> execute_sql_node  # Default loops back
execute_sql_node - "fatal_error" >> cleanup_node
```

#### 3. **Validation Loops**
```python
# From chat-guardrail example
user_input_node - "validate" >> guardrail_node
guardrail_node - "retry" >> user_input_node    # Loop back on invalid input
guardrail_node - "process" >> llm_node         # Continue on valid input
```

*Reference: `pocketflow/cookbook/35-pocketflow-chat-guardrail/`*

---

## Node-Level Error Handling

### 1. **Graceful Fallback Implementation**

#### Basic Fallback Pattern
```python
class RobustNode(Node):
    def exec_fallback(self, prep_res, exc):
        """Provide meaningful fallback instead of crashing."""
        # Log the error
        print(f"Node failed: {exc}")

        # Return safe default
        return "There was an error processing your request."
```

#### Advanced Fallback with Error Context
```python
class APINode(Node):
    def exec_fallback(self, prep_res, exc):
        """Fallback with error context in shared store."""
        shared = prep_res.get('shared', {})

        # Store error details
        shared['last_error'] = str(exc)
        shared['error_type'] = type(exc).__name__
        shared['failed_node'] = self.__class__.__name__

        # Provide context-aware fallback
        if isinstance(exc, ConnectionError):
            return "Service temporarily unavailable. Please try again later."
        elif isinstance(exc, TimeoutError):
            return "Request timed out. Please try again with a simpler query."
        else:
            return "An unexpected error occurred. Please contact support."
```

### 2. **Retry Configuration Strategies**

#### Transient Failure Handling
```python
class APICallNode(Node):
    def __init__(self):
        super().__init__(
            max_retries=3,    # Retry transient failures
            wait=1.0          # Wait 1 second between retries
        )

    def exec(self, prep_res):
        # API call that might fail transiently
        response = api_client.call()
        return response

    def exec_fallback(self, prep_res, exc):
        # After all retries failed
        return {"error": "API unavailable", "fallback": True}
```

#### Exponential Backoff Pattern
```python
class BackoffNode(Node):
    def __init__(self):
        super().__init__(max_retries=5, wait=0)

    def exec(self, prep_res):
        # Custom exponential backoff
        if hasattr(self, 'cur_retry') and self.cur_retry > 0:
            wait_time = 2 ** self.cur_retry  # 2, 4, 8, 16 seconds
            time.sleep(wait_time)

        return self.make_api_call()
```

*Reference: `pocketflow/cookbook/01-pocketflow-node/`*

### 3. **BatchNode Error Handling**

#### Failure Isolation Pattern
```python
class BatchProcessNode(BatchNode):
    def exec_fallback(self, prep_res, exc):
        """Return None for failed items to filter out later."""
        return None

    def post(self, shared, prep_res, exec_res_list):
        # Filter out failed items (None values)
        successful_results = [res for res in exec_res_list if res is not None]
        failed_count = len(exec_res_list) - len(successful_results)

        shared["successful_results"] = successful_results
        shared["failed_count"] = failed_count

        # Continue processing with partial results
        return successful_results
```

*Reference: `pocketflow/cookbook/11-pocketflow-majority-vote/`*

---

## Flow-Level Error Patterns

### 1. **Supervisor Pattern**

#### Quality Control with Retry Logic
```python
# Flow definition
agent_flow >> supervisor
supervisor - "retry" >> agent_flow  # Retry on rejection

class SupervisorNode(Node):
    def post(self, shared, prep_res, exec_res):
        if exec_res["valid"]:
            print(f"✅ Supervisor approved: {exec_res['reason']}")
            return  # Default action - flow continues
        else:
            print(f"❌ Supervisor rejected: {exec_res['reason']}")

            # Clean up bad answer and provide context
            shared["answer"] = None
            shared["context"] = shared.get("context", "") + \
                "\n\nNOTE: Previous answer attempt was rejected."

            return "retry"  # Route back to agent_flow
```

*Reference: `pocketflow/cookbook/36-pocketflow-supervisor/`*

### 2. **Self-Correcting Workflow Pattern**

#### Debug Loop with Attempt Limits
```python
class ExecuteSQL(Node):
    def post(self, shared, prep_res, exec_res):
        success, result_or_error, column_names = exec_res

        if success:
            shared["final_result"] = result_or_error
            return  # Default - flow continues
        else:
            # Error handling with retry limits
            shared["execution_error"] = result_or_error
            shared["debug_attempts"] = shared.get("debug_attempts", 0) + 1
            max_attempts = shared.get("max_debug_attempts", 3)

            if shared["debug_attempts"] >= max_attempts:
                shared["final_error"] = f"Failed after {max_attempts} attempts"
                return  # End flow
            else:
                return "error_retry"  # Route to DebugSQL node

class DebugSQL(Node):
    def post(self, shared, prep_res, exec_res):
        # Clear previous error and try again
        shared.pop("execution_error", None)
        shared["sql_query"] = exec_res  # Updated query
        return  # Default routes back to ExecuteSQL
```

*Reference: `pocketflow/cookbook/37-pocketflow-text2sql/`*

### 3. **Circuit Breaker Pattern**

#### Flow-Level Failure Protection
```python
class CircuitBreakerNode(Node):
    def __init__(self):
        super().__init__()
        self.failure_count = 0
        self.last_failure_time = 0
        self.circuit_open = False

    def prep(self, shared):
        # Check circuit breaker state
        if self.circuit_open:
            time_since_failure = time.time() - self.last_failure_time
            if time_since_failure > 60:  # 60 second recovery period
                self.circuit_open = False
                self.failure_count = 0
            else:
                return "circuit_open"

        return shared

    def post(self, shared, prep_res, exec_res):
        if prep_res == "circuit_open":
            return "circuit_open"

        # Update circuit breaker state
        if exec_res and exec_res.get("error"):
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= 5:  # Open circuit after 5 failures
                self.circuit_open = True
                return "circuit_open"
            else:
                return "error"
        else:
            self.failure_count = 0  # Reset on success
            return  # Default
```

---

## Shared Store Error Communication

### 1. **Error Context Preservation**

#### Comprehensive Error Information
```python
class ErrorAwareNode(Node):
    def store_error_context(self, shared, error, context=None):
        """Store comprehensive error information."""
        error_info = {
            "error_message": str(error),
            "error_type": type(error).__name__,
            "node_name": self.__class__.__name__,
            "timestamp": time.time(),
            "context": context or {},
            "stack_trace": traceback.format_exc() if hasattr(error, '__traceback__') else None
        }

        # Store in shared store
        shared["last_error"] = error_info
        shared["error_history"] = shared.get("error_history", [])
        shared["error_history"].append(error_info)

        return error_info

    def exec_fallback(self, prep_res, exc):
        shared = prep_res.get('shared', {})
        self.store_error_context(shared, exc, {"retry_attempt": self.cur_retry})
        return "error_fallback_triggered"
```

### 2. **State Cleanup and Recovery**

#### Proper State Management
```python
class StatefulNode(Node):
    def post(self, shared, prep_res, exec_res):
        if exec_res.get("error"):
            # Clean up partial state
            self.cleanup_partial_state(shared)

            # Preserve error context for debugging
            shared["cleanup_performed"] = True
            shared["partial_state_backup"] = shared.get("working_state", {})

            # Clear working state
            shared.pop("working_state", None)
            shared.pop("intermediate_results", None)

            return "error_cleanup"
        else:
            # Success - commit state
            shared["final_state"] = shared.get("working_state", {})
            return

    def cleanup_partial_state(self, shared):
        """Clean up any partial state that might cause issues."""
        cleanup_keys = ["temp_files", "open_connections", "locks"]
        for key in cleanup_keys:
            if key in shared:
                # Perform cleanup based on type
                if key == "temp_files":
                    for file_path in shared[key]:
                        try:
                            os.remove(file_path)
                        except FileNotFoundError:
                            pass
                shared.pop(key, None)
```

### 3. **Error Aggregation and Reporting**

#### Multi-Node Error Tracking
```python
class ErrorReporterNode(Node):
    def exec(self, prep_res):
        shared = prep_res

        # Aggregate all errors from flow
        error_summary = {
            "total_errors": len(shared.get("error_history", [])),
            "error_types": {},
            "failed_nodes": set(),
            "critical_errors": []
        }

        for error_info in shared.get("error_history", []):
            error_type = error_info["error_type"]
            node_name = error_info["node_name"]

            # Count error types
            error_summary["error_types"][error_type] = \
                error_summary["error_types"].get(error_type, 0) + 1

            # Track failed nodes
            error_summary["failed_nodes"].add(node_name)

            # Identify critical errors
            if error_type in ["ConnectionError", "TimeoutError", "AuthenticationError"]:
                error_summary["critical_errors"].append(error_info)

        # Store summary
        shared["error_summary"] = error_summary

        return error_summary
```

---

## Advanced Error Handling Patterns

### 1. **Async Error Handling**

#### Async Node Error Patterns
```python
class AsyncNode(Node):
    async def exec_async(self, prep_res):
        """Async execution with error handling."""
        try:
            result = await self.async_operation()
            return result
        except asyncio.TimeoutError:
            # Handle timeout specifically
            return {"error": "timeout", "partial_result": None}
        except Exception as e:
            # Let framework handle with exec_fallback_async
            raise

    async def exec_fallback_async(self, prep_res, exc):
        """Async fallback handling."""
        shared = prep_res.get('shared', {})

        # Async cleanup if needed
        await self.async_cleanup()

        # Store error context
        shared["async_error"] = str(exc)

        return "async_fallback_result"
```

*Reference: `pocketflow/__init__.py` lines 127-162*

### 2. **Hierarchical Error Handling**

#### Nested Flow Error Propagation
```python
class SubFlowNode(Node):
    def __init__(self, sub_flow):
        super().__init__()
        self.sub_flow = sub_flow

    def exec(self, prep_res):
        shared = prep_res

        # Create isolated context for sub-flow
        sub_shared = {
            "parent_context": shared,
            "isolation_level": "sub_flow"
        }

        try:
            result = self.sub_flow.run(sub_shared)

            # Merge results back to parent
            shared["sub_flow_result"] = result
            shared["sub_flow_errors"] = sub_shared.get("error_history", [])

            return result
        except Exception as e:
            # Sub-flow failed - handle gracefully
            shared["sub_flow_failure"] = str(e)
            shared["sub_flow_errors"] = sub_shared.get("error_history", [])

            # Decide whether to continue or fail
            if self.is_critical_sub_flow():
                raise  # Propagate critical failures
            else:
                return {"sub_flow_failed": True, "fallback_used": True}
```

### 3. **Compensating Actions Pattern**

#### Transactional Error Recovery
```python
class TransactionalNode(Node):
    def __init__(self):
        super().__init__()
        self.compensation_actions = []

    def exec(self, prep_res):
        shared = prep_res

        try:
            # Perform transactional operations
            result1 = self.operation_1()
            self.compensation_actions.append(lambda: self.undo_operation_1())

            result2 = self.operation_2()
            self.compensation_actions.append(lambda: self.undo_operation_2())

            # All operations successful
            self.compensation_actions.clear()
            return {"result1": result1, "result2": result2}

        except Exception as e:
            # Execute compensation actions in reverse order
            for action in reversed(self.compensation_actions):
                try:
                    action()
                except Exception as compensation_error:
                    shared["compensation_errors"] = \
                        shared.get("compensation_errors", [])
                    shared["compensation_errors"].append(str(compensation_error))

            self.compensation_actions.clear()
            raise  # Re-raise original exception
```

---

## Best Practices & Guidelines

### 1. **Error Handling Design Principles**

#### **Fail Fast, Recover Gracefully**
- Validate inputs early in `prep()` method
- Use explicit error checking rather than exception handling where possible
- Provide meaningful error messages to users
- Design for partial success in batch operations

#### **Idempotency for Retries**
```python
class IdempotentNode(Node):
    def exec(self, prep_res):
        # Check if operation already completed
        if prep_res.get("operation_id") in self.completed_operations:
            return self.completed_operations[prep_res["operation_id"]]

        # Perform operation
        result = self.perform_operation()

        # Cache result for retries
        self.completed_operations[prep_res["operation_id"]] = result
        return result
```

#### **Graceful Degradation Strategy**
- Always implement `exec_fallback()` for external dependencies
- Provide partial results when possible
- Use cached data when live data is unavailable
- Implement circuit breakers for unreliable services

### 2. **Error Communication Guidelines**

#### **Structured Error Information**
```python
class ErrorStructureNode(Node):
    def create_error_response(self, error_type, message, context=None):
        """Create structured error response."""
        return {
            "success": False,
            "error": {
                "type": error_type,
                "message": message,
                "context": context or {},
                "timestamp": time.time(),
                "node": self.__class__.__name__,
                "recoverable": error_type in ["timeout", "rate_limit", "temporary"]
            }
        }

    def exec_fallback(self, prep_res, exc):
        if isinstance(exc, TimeoutError):
            return self.create_error_response("timeout", "Operation timed out")
        elif isinstance(exc, ConnectionError):
            return self.create_error_response("connection", "Service unavailable")
        else:
            return self.create_error_response("unknown", str(exc))
```

#### **Error Context Enrichment**
```python
class ContextEnrichmentNode(Node):
    def enrich_error_context(self, shared, error_info):
        """Enrich error context with additional information."""
        context = {
            "flow_id": shared.get("flow_id"),
            "user_id": shared.get("user_id"),
            "session_id": shared.get("session_id"),
            "node_sequence": shared.get("node_execution_order", []),
            "shared_store_keys": list(shared.keys()),
            "execution_time": time.time() - shared.get("start_time", 0)
        }

        error_info["enriched_context"] = context
        return error_info
```

### 3. **Testing Error Scenarios**

#### **Comprehensive Error Testing**
```python
# Test file example
def test_node_error_handling():
    node = MyNode()
    shared = {"test_data": "invalid"}

    # Test normal execution
    result = node.run(shared)
    assert result is not None

    # Test error scenarios
    shared["simulate_error"] = "connection_error"
    result = node.run(shared)
    assert result["error"]["type"] == "connection"

    # Test retry behavior
    node.max_retries = 3
    shared["simulate_error"] = "transient_error"
    result = node.run(shared)
    assert node.cur_retry == 2  # Verify retries occurred

    # Test fallback behavior
    shared["simulate_error"] = "fatal_error"
    result = node.run(shared)
    assert result["fallback_used"] is True
```

---

## Common Pitfalls & Anti-Patterns

### 1. **Error Handling Anti-Patterns**

#### **❌ Silent Failures**
```python
# BAD: Silently ignoring errors
def exec_fallback(self, prep_res, exc):
    return None  # User has no idea what went wrong
```

#### **✅ Explicit Error Communication**
```python
# GOOD: Clear error communication
def exec_fallback(self, prep_res, exc):
    shared = prep_res.get('shared', {})
    shared["error_message"] = f"Operation failed: {str(exc)}"
    return {"error": True, "message": str(exc), "recoverable": False}
```

#### **❌ Infinite Retry Loops**
```python
# BAD: No retry limits
node - "retry" >> node  # Can loop forever
```

#### **✅ Bounded Retry Logic**
```python
# GOOD: Retry with limits
class BoundedRetryNode(Node):
    def post(self, shared, prep_res, exec_res):
        if exec_res.get("error"):
            attempts = shared.get("retry_attempts", 0) + 1
            shared["retry_attempts"] = attempts

            if attempts >= 3:
                return "max_retries_exceeded"
            else:
                return "retry"
        return  # Success
```

### 2. **State Management Pitfalls**

#### **❌ Shared State Corruption**
```python
# BAD: Not cleaning up on failure
def exec_fallback(self, prep_res, exc):
    # Leaves corrupted state in shared store
    return "error_occurred"
```

#### **✅ Proper State Cleanup**
```python
# GOOD: Clean up on failure
def exec_fallback(self, prep_res, exc):
    shared = prep_res.get('shared', {})

    # Clean up partial state
    shared.pop("working_data", None)
    shared.pop("temp_results", None)

    # Store error info
    shared["cleanup_performed"] = True

    return "error_with_cleanup"
```

### 3. **Resource Management Issues**

#### **❌ Resource Leaks on Errors**
```python
# BAD: Not cleaning up resources
def exec(self, prep_res):
    file_handle = open("data.txt")
    # If this fails, file handle is leaked
    result = self.process_file(file_handle)
    file_handle.close()
    return result
```

#### **✅ Proper Resource Management**
```python
# GOOD: Use context managers and cleanup
def exec(self, prep_res):
    try:
        with open("data.txt") as file_handle:
            result = self.process_file(file_handle)
        return result
    except FileNotFoundError:
        return {"error": "file_not_found", "fallback": "default_data"}

def exec_fallback(self, prep_res, exc):
    # Ensure any resources are cleaned up
    self.cleanup_resources()
    return {"error": True, "message": str(exc)}
```

---

## Integration with pflow CLI

### 1. **CLI Error Handling Requirements**

#### **User-Friendly Error Messages**
```python
class PflowNode(Node):
    def exec_fallback(self, prep_res, exc):
        """Provide CLI-friendly error messages."""
        shared = prep_res.get('shared', {})

        if isinstance(exc, FileNotFoundError):
            error_msg = f"File not found: {exc.filename}"
            suggestion = "Please check the file path and try again."
        elif isinstance(exc, PermissionError):
            error_msg = f"Permission denied: {exc.filename}"
            suggestion = "Please check file permissions or run with appropriate privileges."
        else:
            error_msg = f"Unexpected error: {str(exc)}"
            suggestion = "Please try again or contact support."

        # Store for CLI display
        shared["cli_error"] = {
            "message": error_msg,
            "suggestion": suggestion,
            "error_code": type(exc).__name__
        }

        return {"error": True, "cli_friendly": True}
```

#### **Progressive Error Disclosure**
```python
class DebugAwareNode(Node):
    def exec_fallback(self, prep_res, exc):
        shared = prep_res.get('shared', {})
        debug_mode = shared.get("debug_mode", False)

        error_info = {
            "message": str(exc),
            "type": type(exc).__name__
        }

        if debug_mode:
            error_info.update({
                "traceback": traceback.format_exc(),
                "shared_store_state": dict(shared),
                "node_config": self.get_config()
            })

        shared["error_detail"] = error_info
        return error_info
```

### 2. **Logging and Observability**

#### **Structured Logging for Errors**
```python
import logging

class ObservableNode(Node):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(f"pflow.{self.__class__.__name__}")

    def exec_fallback(self, prep_res, exc):
        shared = prep_res.get('shared', {})

        # Structured logging
        self.logger.error(
            "Node execution failed",
            extra={
                "node_name": self.__class__.__name__,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "retry_attempt": getattr(self, 'cur_retry', 0),
                "flow_id": shared.get("flow_id"),
                "execution_context": shared.get("execution_context", {})
            }
        )

        return {"error": True, "logged": True}
```

### 3. **Error Recovery in CLI Context**

#### **Interactive Error Recovery**
```python
class InteractiveRecoveryNode(Node):
    def exec_fallback(self, prep_res, exc):
        shared = prep_res.get('shared', {})

        if shared.get("interactive_mode"):
            # Present recovery options to user
            recovery_options = {
                "retry": "Try the operation again",
                "skip": "Skip this step and continue",
                "abort": "Stop the workflow",
                "modify": "Modify the input and retry"
            }

            shared["recovery_options"] = recovery_options
            return "interactive_recovery"
        else:
            # Non-interactive fallback
            return {"error": True, "message": str(exc)}
```

---

## Reference Implementation Examples

### 1. **Complete Error-Resilient Node**

```python
class ResilientFileProcessor(Node):
    def __init__(self):
        super().__init__(
            max_retries=3,
            wait=1.0
        )
        self.logger = logging.getLogger(f"pflow.{self.__class__.__name__}")

    def prep(self, shared):
        """Validate inputs and prepare for execution."""
        file_path = shared.get("file_path")

        if not file_path:
            raise ValueError("file_path is required")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        if not os.access(file_path, os.R_OK):
            raise PermissionError(f"Cannot read file: {file_path}")

        return shared

    def exec(self, prep_res):
        """Execute with comprehensive error handling."""
        file_path = prep_res["file_path"]

        try:
            with open(file_path, 'r') as f:
                content = f.read()

            # Simulate processing that might fail
            if "ERROR" in content:
                raise ValueError("Content contains ERROR marker")

            processed_content = content.upper()

            return {
                "success": True,
                "content": processed_content,
                "file_size": len(content),
                "processing_time": time.time()
            }

        except UnicodeDecodeError as e:
            self.logger.warning(f"Unicode decode error: {e}")
            # Try with different encoding
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()
            return {
                "success": True,
                "content": content.upper(),
                "encoding_fallback": True
            }

    def exec_fallback(self, prep_res, exc):
        """Comprehensive fallback handling."""
        shared = prep_res

        # Log error with context
        self.logger.error(
            f"File processing failed after {self.cur_retry + 1} attempts",
            extra={
                "file_path": shared.get("file_path"),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "retry_attempt": self.cur_retry
            }
        )

        # Store error context
        error_info = {
            "error": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "retry_attempts": self.cur_retry + 1,
            "fallback_used": True,
            "timestamp": time.time()
        }

        # Provide type-specific fallback
        if isinstance(exc, FileNotFoundError):
            error_info["cli_message"] = f"File not found: {shared.get('file_path')}"
            error_info["suggestion"] = "Please check the file path and try again."
        elif isinstance(exc, PermissionError):
            error_info["cli_message"] = "Permission denied accessing file"
            error_info["suggestion"] = "Please check file permissions."
        elif isinstance(exc, ValueError):
            error_info["cli_message"] = "File content validation failed"
            error_info["suggestion"] = "Please verify file content format."
        else:
            error_info["cli_message"] = f"Unexpected error: {str(exc)}"
            error_info["suggestion"] = "Please try again or contact support."

        # Store in shared store for other nodes
        shared["last_error"] = error_info

        return error_info

    def post(self, shared, prep_res, exec_res):
        """Post-processing with error handling."""
        if exec_res.get("error"):
            # Error occurred - clean up if necessary
            self.cleanup_temp_files(shared)
            return "error"

        # Success - store results
        shared["processed_content"] = exec_res["content"]
        shared["file_metadata"] = {
            "size": exec_res["file_size"],
            "processed_at": exec_res["processing_time"]
        }

        return  # Default transition

    def cleanup_temp_files(self, shared):
        """Clean up any temporary files created during processing."""
        temp_files = shared.get("temp_files", [])
        for temp_file in temp_files:
            try:
                os.remove(temp_file)
            except FileNotFoundError:
                pass  # Already cleaned up
        shared.pop("temp_files", None)
```

### 2. **Error-Resilient Flow Pattern**

```python
# Complete flow with error handling
validation_node = ValidationNode()
processing_node = ResilientFileProcessor()
error_handler = ErrorHandlerNode()
cleanup_node = CleanupNode()

# Flow with error routing
flow = Flow(
    validation_node,
    {
        validation_node: {
            "valid": processing_node,
            "invalid": error_handler
        },
        processing_node: {
            "error": error_handler,
            None: cleanup_node  # Default success path
        },
        error_handler: {
            "retry": validation_node,
            "abort": cleanup_node,
            None: cleanup_node
        }
    }
)

# Usage with comprehensive error handling
def run_with_error_handling(file_path):
    shared = {
        "file_path": file_path,
        "max_retries": 3,
        "error_history": [],
        "debug_mode": True
    }

    try:
        result = flow.run(shared)

        if shared.get("last_error"):
            # Handle error gracefully
            error_info = shared["last_error"]
            print(f"Error: {error_info['cli_message']}")
            print(f"Suggestion: {error_info['suggestion']}")
            return False
        else:
            print("File processed successfully")
            return True

    except Exception as e:
        print(f"Critical error: {str(e)}")
        return False
```

---

## Summary

PocketFlow's error handling system provides a **comprehensive, flexible framework** for building resilient workflows:

### Key Strengths:
- **Node-level retry with fallback** for transient failures
- **Action-based error routing** for complex recovery scenarios
- **Explicit error communication** through shared store
- **Flexible patterns** for different error handling strategies

### Critical Implementation Points:
1. **Always implement `exec_fallback()`** for external dependencies
2. **Use action strings** for error routing between nodes
3. **Store error context** in shared store for debugging
4. **Design for idempotency** when using retries
5. **Clean up state** on failures to prevent corruption

### For pflow CLI Integration:
- Provide user-friendly error messages
- Implement progressive error disclosure for debug mode
- Use structured logging for observability
- Design interactive recovery options where appropriate

This comprehensive approach ensures that pflow workflows can handle errors gracefully while maintaining user experience and system reliability.

---

*References:*
- *Core Framework: `pocketflow/__init__.py`*
- *Node Documentation: `pocketflow/docs/core_abstraction/node.md`*
- *Flow Documentation: `pocketflow/docs/core_abstraction/flow.md`*
- *Cookbook Examples: `pocketflow/cookbook/` (examples 35-41)*
- *Advanced Patterns: `pocketflow/cookbook/CLAUDE.md`*
