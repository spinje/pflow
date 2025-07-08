# Patterns Discovered

## Pattern: Structured Logging Implementation
**Context**: When you need to add phase-based logging to a component for debugging and observability
**Solution**: Use module-level logger with phase tracking via extra dict
**Why it works**: Provides structured data for log analysis while maintaining clean code
**When to use**: Any component with distinct processing phases that need visibility

**Example**:
```python
import logging

# Module-level logger
logger = logging.getLogger(__name__)

class SomeProcessor:
    def process(self, data):
        # Log phase transitions with structured data
        logger.debug("Starting processing", extra={
            "phase": "init",
            "data_size": len(data)
        })

        try:
            # Validation phase
            logger.debug("Validating input", extra={
                "phase": "validation",
                "data_type": type(data).__name__
            })
            self._validate(data)

            # Processing phase
            logger.debug("Processing data", extra={
                "phase": "processing",
                "items_count": len(data.items())
            })
            result = self._process(data)

            # Completion
            logger.info("Processing complete", extra={
                "phase": "complete",
                "result_size": len(result)
            })

            return result

        except Exception as e:
            # Use logger.exception for caught exceptions being re-raised
            logger.exception("Processing failed", extra={
                "phase": "error",
                "error_type": type(e).__name__
            })
            raise
```

**Key Points**:
- Use `logger.debug()` for detailed phase tracking
- Use `logger.info()` for important completions
- Use `logger.exception()` when catching and re-raising exceptions
- Always include `phase` in the extra dict
- Add relevant context data (counts, types, etc.)
- Avoid reserved field names in extra dict
