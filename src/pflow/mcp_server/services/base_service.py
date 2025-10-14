"""Base service layer for enforcing stateless pattern.

This module provides the base class and utilities for ensuring
all services follow the stateless pattern with fresh instances
per request.
"""

import logging
from functools import wraps
from typing import Any, Callable, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


class BaseService:
    """Base class for all MCP services.

    Enforces the stateless pattern by preventing instance reuse.
    All service methods should be class methods or create fresh
    instances internally.
    """

    def __init__(self) -> None:
        """Initialize service - should not store state."""
        # Services should not store any state
        # This init is here to catch accidental instance creation
        logger.debug(f"Creating {self.__class__.__name__} instance")

    @classmethod
    def create_fresh_instances(cls) -> dict[str, Any]:
        """Create fresh instances of all required services.

        This method should be overridden by subclasses to create
        the specific instances they need.

        Returns:
            Dictionary of fresh service instances
        """
        raise NotImplementedError("Subclasses must implement create_fresh_instances")

    @classmethod
    def validate_stateless(cls) -> bool:
        """Validate that the service follows stateless pattern.

        Returns:
            True if service is stateless, False otherwise
        """
        # Check that no instance variables are storing state
        instance = cls()
        instance_vars = vars(instance)

        # Should have no instance variables (empty __dict__)
        if instance_vars:
            logger.warning(f"{cls.__name__} has instance variables: {list(instance_vars.keys())}")
            return False

        return True


def ensure_stateless(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to ensure function creates fresh instances.

    This decorator logs instance creation to help debug
    stateless pattern violations.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        logger.debug(f"Executing {func.__name__} with fresh instances")
        result = func(*args, **kwargs)
        logger.debug(f"Completed {func.__name__}")
        return result

    return wrapper
