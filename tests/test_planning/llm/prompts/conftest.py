"""Pytest configuration for LLM prompt tests.

This file handles model overrides for cost-effective testing.
When PFLOW_TEST_MODEL environment variable is set, all LLM calls
will be redirected to use that model instead of the default.

It also tracks token usage and saves it to a file specified by
PFLOW_TOKEN_TRACKER_FILE environment variable.
"""

import json
import os

import pytest

# Global token tracking
_token_tracker = {"total_input": 0, "total_output": 0, "model_name": None, "call_count": 0}


@pytest.fixture(autouse=True, scope="session")
def override_llm_model():  # noqa: C901
    """Override LLM model for all tests if PFLOW_TEST_MODEL is set."""
    override_model = os.getenv("PFLOW_TEST_MODEL")
    tracker_file = os.getenv("PFLOW_TOKEN_TRACKER_FILE")

    if not override_model and not tracker_file:
        # No override or tracking requested
        yield
        return

    # Try to import and monkey-patch llm
    try:
        import llm

        # Store original
        original_get_model = llm.get_model

        # Track if we're already in a redirect to prevent infinite recursion
        _in_redirect = {"value": False}

        # Create wrapper that redirects to override model and tracks usage
        def wrapped_get_model(model_name: str, **kwargs):  # noqa: C901
            """Get model but use override if specified and track usage."""
            # Prevent infinite recursion - if we're already redirecting, just call original
            if _in_redirect["value"]:
                return original_get_model(model_name, **kwargs)

            # Use override model if specified and it's different from requested
            actual_model = model_name
            if override_model and model_name != override_model:
                actual_model = override_model
                print(f"  [Model Override] Redirecting {model_name} → {actual_model}")

            # Set flag to prevent recursion
            _in_redirect["value"] = True
            try:
                # Get the actual model
                try:
                    model = original_get_model(actual_model, **kwargs)
                except Exception as e:
                    # If model fails to load, try without kwargs
                    # This handles thread safety issues
                    try:
                        model = original_get_model(actual_model)
                    except Exception as e2:
                        # Re-raise original error
                        raise e from e2
            finally:
                _in_redirect["value"] = False

            # Store original prompt method
            original_prompt = model.prompt

            def wrapped_prompt(*args, **kwargs):
                """Wrapped prompt that captures token usage."""
                # Handle temperature for models that don't support it
                # Since we're overriding the model, we need to handle temperature compatibility here
                DEFAULT_TEMP_ONLY_MODELS = {
                    "gpt-5-nano",
                    "gpt-5-mini",
                    "gpt-5",
                }

                for model_prefix in DEFAULT_TEMP_ONLY_MODELS:
                    if model_prefix in actual_model.lower():
                        if "temperature" in kwargs:
                            original_temp = kwargs["temperature"]
                            # Remove temperature parameter entirely - use model's default
                            del kwargs["temperature"]
                            print(f"  [Temperature Fix] Removed temperature={original_temp} for {actual_model}")
                        break

                # Call original prompt
                response = original_prompt(*args, **kwargs)

                # Try to capture usage for tracking
                if response and hasattr(response, "usage") and callable(response.usage):
                    try:
                        usage = response.usage()
                        if usage and hasattr(usage, "input") and hasattr(usage, "output"):
                            _token_tracker["total_input"] += usage.input or 0
                            _token_tracker["total_output"] += usage.output or 0
                            _token_tracker["model_name"] = actual_model
                            _token_tracker["call_count"] += 1
                    except Exception:  # noqa: S110
                        pass  # Ignore errors in usage capture

                return response

            model.prompt = wrapped_prompt
            return model

        # Apply monkey-patch
        llm.get_model = wrapped_get_model

        yield

        # Restore original
        llm.get_model = original_get_model

        # Save token tracking data if file specified
        if tracker_file and _token_tracker["call_count"] > 0:
            try:
                # For parallel execution with pytest-xdist, append worker ID to filename
                worker_id = os.environ.get("PYTEST_XDIST_WORKER")
                if worker_id:
                    # Each worker writes to its own file
                    tracker_file = tracker_file.replace(".json", f".{worker_id}.json")

                with open(tracker_file, "w") as f:
                    json.dump(_token_tracker, f)
            except Exception:  # noqa: S110
                pass  # Ignore errors saving tracker data

    except ImportError:
        # llm not available, skip
        yield
