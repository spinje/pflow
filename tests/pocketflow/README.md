# PocketFlow Framework Tests

These are the test suite for the embedded PocketFlow framework.

## About PocketFlow

PocketFlow is a lightweight Python framework for building agentic workflows, embedded in pflow under `src/pflow/pocketflow/`.

- **Copyright**: (c) 2024 Zachary Huang
- **License**: MIT License (see `src/pflow/pocketflow/LICENSE`)
- **Repository**: https://github.com/The-Pocket/PocketFlow

## Test Coverage

These tests validate the core PocketFlow framework functionality:
- Async flows and batch processing
- Node composition and execution
- Flow construction and error handling
- Parallel batch operations

## Running These Tests

```bash
# Run all pocketflow tests
uv run pytest tests/pocketflow/

# Run specific test file
uv run pytest tests/pocketflow/test_flow_basic.py
```

These tests are automatically included when you run `make test` or `pytest` from the project root.
