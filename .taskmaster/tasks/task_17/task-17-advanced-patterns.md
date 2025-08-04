# Task 17: Critical PocketFlow Patterns for Implementation

This document contains ONLY the essential patterns from production PocketFlow applications that directly solve problems the Natural Language Planner will face.

## Pattern 1: Two-Path Decision with Convergence

### Source: Website Chatbot
The chatbot's agent decision pattern maps perfectly to the planner's architecture.

**The Pattern:**
```python
# The decision node determines the path
agent_node - "explore" >> crawl_node  # Loop back for more info
agent_node - "answer" >> draft_answer_node  # Proceed to answer

# Both paths eventually converge at answer generation
```

**Application to Planner:**
```python
# WorkflowDiscoveryNode makes the routing decision
discovery_node - "generate" >> browse_node  # Path B: Create new
discovery_node - "found" >> param_map_node  # Path A: Use existing

# Both paths converge at parameter mapping
generate_path >> param_map_node  # Convergence point
```

**Key Insight**: The convergence point (ParameterMappingNode) is where both paths meet, serving as a verification gate that ensures all required parameters exist before execution.

## Pattern 2: Graceful Failure Recovery with exec_fallback

### Source: Cold Email Personalization
Shows how to handle failures elegantly without crashing the entire system.

**The Pattern:**
```python
class ContentRetrievalNode(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=1.0)
    
    def exec_fallback(self, prep_res, exc):
        """After all retries failed, return structured failure."""
        # prep_res contains the context we need for error reporting
        logger.error(f"Failed after {self.max_retries} attempts: {exc}")
        
        # Return structured result even on failure
        return {
            "success": False,
            "error": str(exc),
            "fallback_used": True,
            "context": prep_res.get("user_input", "")
        }
```

**Application to Planner:**
Each planner node should implement `exec_fallback` to handle LLM failures gracefully:

```python
class WorkflowGeneratorNode(Node):
    def prep(self, shared):
        # Return everything exec_fallback might need
        return shared  # Return full context for fallback
    
    def exec_fallback(self, prep_res, exc):
        """Fallback to simpler generation strategy."""
        # Can access full context from prep_res
        user_input = prep_res.get("user_input", "")
        
        # Return simplified workflow
        return {
            "workflow": {
                "nodes": [{"type": "llm", "params": {"prompt": user_input}}],
                "edges": []
            },
            "method": "fallback_template",
            "error": str(exc)
        }
```

**Critical Implementation Note**: Since `exec_fallback` only receives `(prep_res, exc)`, the `prep()` method should return whatever context the fallback needs - often the entire shared dict.

**IMPORTANT CLARIFICATION - When to Return `shared` from `prep()`:**

Returning the full `shared` dict from `prep()` is an **EXCEPTION PATTERN** used only when:
- `exec_fallback` needs context for error reporting or recovery
- You need to preserve user input for fallback strategies
- The node might need to recover gracefully with contextual information

For normal cases, return only what `exec()` needs:
```python
# NORMAL CASE - Return only what exec() needs
def prep(self, shared):
    return {
        "prompt": shared["prompt"],
        "model": shared.get("model", "default")
    }

# EXCEPTION CASE - Return full context for fallback
def prep(self, shared):
    return shared  # Only when exec_fallback needs the full context
```

This is a deliberate design choice, not the default pattern. Most nodes should return specific data from `prep()`, not the entire shared store.

## Pattern 3: Progressive Context Building

### Source: Codebase Knowledge Tutorial
Shows how to build understanding incrementally through multiple stages.

**The Pattern:**
```python
# Each node adds to the growing context
def post(self, shared, prep_res, exec_res):
    # Don't replace - augment
    shared["abstractions"] = exec_res["found_abstractions"]
    shared["context"] += f"\nFound {len(exec_res['found_abstractions'])} abstractions"
    
    # Build on previous discoveries
    shared["relationships"] = self._analyze_with_context(
        shared["abstractions"],  # Use previous stage output
        exec_res["current_analysis"]
    )
    return "default"
```

**Application to Planner:**
```python
# Discovery adds available components
shared["discovery_context"] = discovered_components

# Browsing adds selected components
shared["planning_context"] = shared["discovery_context"] + browsed_details

# Generation uses accumulated context
shared["generation_context"] = shared["planning_context"] + extracted_params

# Each stage builds on previous stages
```

**Key Insight**: Don't replace context - augment it. Each stage should add to the shared understanding.

## Pattern 4: Multi-Tier Validation with Bounded Retries

### Source: Multiple Examples (Danganronpa, Cursor, Website Chatbot)
Shows how to validate at multiple levels with clear retry boundaries.

**The Pattern:**
```python
class ValidationNode(Node):
    def __init__(self):
        super().__init__(max_retries=1)  # Don't retry validation itself
    
    def exec(self, prep_res):
        workflow = prep_res["workflow"]
        errors = []
        
        # Tier 1: Structure
        if not self._validate_structure(workflow):
            errors.append({"level": "structure", "message": "Invalid IR structure"})
            
        # Tier 2: Nodes exist
        if not errors:  # Only if structure is valid
            for node in workflow.get("nodes", []):
                if node["type"] not in prep_res["registry"]:
                    errors.append({"level": "node", "message": f"Unknown node: {node['type']}"})
        
        # Tier 3: Templates valid
        if not errors:  # Only if nodes are valid
            template_errors = self._validate_templates(workflow, prep_res["params"])
            errors.extend(template_errors)
        
        return {"valid": len(errors) == 0, "errors": errors[:3]}  # Limit errors
    
    def post(self, shared, prep_res, exec_res):
        shared["validation_result"] = exec_res
        
        if not exec_res["valid"]:
            attempts = shared.get("generation_attempts", 0)
            if attempts < 3:  # Bounded retries
                shared["generation_attempts"] = attempts + 1
                shared["validation_errors"] = exec_res["errors"]
                return "retry"
            return "failed"
        
        return "valid"
```

**Key Insights:**
- Validate in tiers - don't check templates if structure is broken
- Limit error feedback to prevent overwhelming the LLM (top 3 errors)
- Bound retry attempts (max 3) to prevent infinite loops
- Track attempts in shared store for visibility

## Pattern 5: Structured LLM Output with JSON

### Source: All Examples (converted from YAML patterns)
Every example uses structured output from LLMs. While they use YAML, the planner needs JSON with Pydantic validation.

**The `llm` library has excellent built-in schema support for structured output!**

**The Pattern (using llm's schema support):**
```python
from pydantic import BaseModel
from typing import List, Optional
import llm

class WorkflowDecision(BaseModel):
    """Pydantic model for structured LLM output."""
    decision: str  # "found" or "generate"
    reasoning: str
    selected_workflow: Optional[str] = None
    confidence: float

class WorkflowGeneratorNode(Node):
    def exec(self, prep_res):
        model = llm.get_model("anthropic/claude-sonnet-4-0")
        
        prompt = f"""Analyze if existing workflow satisfies the request.
        
        User request: {prep_res['user_input']}
        Available workflows: {prep_res['workflows']}
        
        Determine if an existing workflow completely satisfies the request."""
        
        # Use schema parameter for structured output
        response = model.prompt(prompt, schema=WorkflowDecision)
        
        # Get validated JSON directly
        result = response.json()  # Returns dict matching schema
        
        # Already validated by llm library!
        return result

class FlowIR(BaseModel):
    """Pydantic model for workflow IR generation."""
    ir_version: str = "0.1.0"
    nodes: List[dict]
    edges: List[dict]
    
class WorkflowGeneratorNode(Node):
    def exec(self, prep_res):
        model = llm.get_model("anthropic/claude-sonnet-4-0")
        
        prompt = f"""Generate a workflow for: {prep_res['user_input']}
        
        Available components:
        {prep_res['planning_context']}
        
        Generate a valid workflow using these components."""
        
        try:
            # Direct schema-based generation
            response = model.prompt(prompt, schema=FlowIR)
            workflow = response.json()
            
            # Add any extracted parameters as template variables
            workflow = self._add_template_variables(workflow, prep_res)
            return {"success": True, "workflow": workflow}
            
        except Exception as e:
            # Fallback for generation failures
            logger.error(f"Generation failed: {e}")
            return {
                "success": False,
                "workflow": self._get_fallback_workflow(prep_res),
                "error": str(e)
            }
```

**Key Insights:**
- Use Pydantic models for type safety
- Show the exact schema in the prompt
- Handle markdown code blocks in response
- Always have a fallback if parsing fails

## Pattern 6: Using Validation Errors for Better Retries

### Source: Website Chatbot, Codebase Knowledge
Shows how to use previous errors to improve subsequent attempts.

**The Pattern:**
```python
class WorkflowGeneratorNode(Node):
    def prep(self, shared):
        # Include previous errors in context
        return {
            "user_input": shared["user_input"],
            "context": shared["planning_context"],
            "previous_errors": shared.get("validation_errors", []),
            "attempt": shared.get("generation_attempts", 0)
        }
    
    def exec(self, prep_res):
        model = llm.get_model("anthropic/claude-sonnet-4-0")
        
        # Build prompt with error context
        prompt = f"Generate a workflow for: {prep_res['user_input']}\n"
        prompt += f"Available context: {prep_res['context']}\n"
        
        # Add previous errors if this is a retry
        if prep_res["attempt"] > 0 and prep_res["previous_errors"]:
            prompt += "\nPrevious attempt failed with these errors:\n"
            for error in prep_res["previous_errors"][:3]:  # Limit to 3
                prompt += f"- {error['level']}: {error['message']}\n"
            prompt += "\nPlease fix these specific issues in your new attempt.\n"
        
        prompt += "\nGenerate valid JSON IR that addresses all requirements."
        
        response = model.prompt(prompt)
        # ... parse and return workflow ...
```

**Key Insight**: Use validation errors as learning context for retry attempts, but limit to top 3 errors to avoid overwhelming the LLM.

## Pattern 7: Structured Shared Store Design

### Source: All Examples
Every production example uses a well-structured shared store with clear sections.

**The Pattern:**
```python
shared = {
    # === INPUT === (what came from user/CLI)
    "user_input": str,
    "initial_params": dict,
    
    # === DISCOVERY === (what we found)
    "available_workflows": list,
    "available_nodes": list,
    "discovery_result": dict,
    
    # === GENERATION === (what we're building)
    "generation_attempts": int,
    "validation_errors": list,  # Critical for retry context
    "generated_workflow": dict,
    
    # === OUTPUT === (what we return)
    "workflow_ir": dict,
    "execution_params": dict,
    "metadata": dict
}
```

**Key Insights:**
- Group related data with clear section comments
- Track validation_errors for retry improvements
- Track attempts for bounded retries
- Separate input/working/output data clearly

## What NOT to Do (Anti-Patterns to Avoid)

Based on the examples, here are patterns that would add unnecessary complexity:

### 1. Don't Use YAML Parsing
Use JSON with Pydantic models instead. The examples above show how to convert YAML patterns to JSON.

### 2. Don't Over-Engineer with BatchNode
The MVP doesn't need parallel processing. Keep it simple with sequential execution.

### 3. Don't Track Full History
Only track the current attempt's validation errors for retry context, not complete history.

### 4. Don't Use Complex State Machines
Keep the flow simple: discovery → decision → (generate OR reuse) → converge at validation.

## Implementation Checklist

When implementing each planner node:

- [ ] Define Pydantic models for structured LLM output
- [ ] Implement `exec_fallback()` for graceful failure handling
- [ ] Have `prep()` return enough context for fallback
- [ ] Build on previous context, don't replace it
- [ ] Include validation errors in retry prompts
- [ ] Validate in tiers with early exit on failure
- [ ] Limit error feedback to 3 most important
- [ ] Bound retries to maximum 3 attempts
- [ ] Track attempts and errors in shared store
- [ ] Return structured results even on failure
- [ ] Use clear action strings for routing

## Summary

These 7 patterns address the core challenges the planner will face:
1. **Two-path with convergence** - The exact branching pattern needed
2. **Graceful failure recovery** - Handle LLM failures without crashing
3. **Progressive context building** - Each stage adds to understanding
4. **Multi-tier validation** - Validate structure → nodes → templates
5. **Structured LLM output** - Get reliable JSON from LLM with Pydantic
6. **Error-driven retries** - Use validation errors to improve next attempt
7. **Organized shared store** - Clear data organization for debugging

Focus on these patterns. They're proven in production and directly solve Task 17's challenges.

---

*Curated from 7 production PocketFlow applications to include only patterns that will genuinely help implementation.*