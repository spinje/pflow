# MCP Server Utilities

`validation.py:validate_execution_parameters` checks parameter names, JSON
serializability/serialized size, and suspicious patterns at the MCP boundary.
These checks are not a code sandbox or a complete injection defense. Callers live
in `../services/execution_service.py`; new execution entry points must consider this
boundary explicitly rather than assume validation is automatic.

Shared implementations live in core:

- `core/validation_utils.py:generate_dummy_parameters` supplies validation placeholders.
- `core/security_utils.py:sanitize_parameters` owns redaction.

The exports here are compatibility shims; change shared behavior at its core owner.
