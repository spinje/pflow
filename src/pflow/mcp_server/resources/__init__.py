"""MCP resources for pflow.

This module provides read-only data sources (resources) that MCP clients
can access to get information about pflow workflows and best practices.
"""

from . import instruction_resources

__all__ = ["instruction_resources"]
