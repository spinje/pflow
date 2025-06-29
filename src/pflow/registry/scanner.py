"""Node discovery scanner for pflow registry."""

import importlib
import inspect
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Set up logging
logger = logging.getLogger(__name__)


@contextmanager
def temporary_syspath(paths: list[Path]) -> Iterator[None]:
    """Temporarily add paths to sys.path for imports."""
    original_path = sys.path.copy()
    try:
        # Add paths at the beginning for priority
        for path in reversed(paths):
            sys.path.insert(0, str(path))
        yield
    finally:
        sys.path = original_path


def camel_to_kebab(name: str) -> str:
    """Convert CamelCase to kebab-case."""
    # Handle consecutive capitals (e.g., "LLMNode" -> "LLM-Node")
    # First, handle the sequence of capitals followed by lowercase
    result = re.sub("([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    # Then handle normal case transitions (including digits)
    result = re.sub(r"([a-z\d])([A-Z])", r"\1-\2", result)
    return result.lower()


def get_node_name(cls: type) -> str:
    """Extract node name from class (explicit or kebab-case)."""
    # Check for explicit name attribute
    if hasattr(cls, "name") and isinstance(cls.name, str):
        return cls.name

    # Convert class name to kebab-case
    # Remove 'Node' suffix if present
    class_name = cls.__name__
    if class_name.endswith("Node"):
        class_name = class_name[:-4]

    return camel_to_kebab(class_name)


def path_to_module(file_path: Path, base_path: Path) -> str:
    """Convert file path to module import path."""
    # Get relative path from base
    try:
        relative = file_path.relative_to(base_path)
    except ValueError:
        # If not relative to base_path, use the full path
        relative = file_path

    # Remove .py extension and convert to module path
    parts = list(relative.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]

    return ".".join(parts)


def extract_metadata(cls: type, module_path: str, file_path: Path) -> dict[str, Any]:
    """Extract metadata from a node class."""
    return {
        "module": module_path,
        "class_name": cls.__name__,
        "name": get_node_name(cls),
        "docstring": inspect.getdoc(cls) or "",
        "file_path": str(file_path.absolute()),
    }


def _calculate_module_path(py_file: Path, directory: Path) -> str:
    """Calculate the module path for a Python file."""
    if "pflow" in str(py_file):
        # For pflow modules, calculate from src/
        src_path = py_file.parent
        while src_path.name != "src" and src_path.parent != src_path:
            src_path = src_path.parent
        if src_path.name == "src":
            return "pflow." + path_to_module(py_file, src_path / "pflow")
    return path_to_module(py_file, directory)


def _should_skip_file(py_file: Path) -> bool:
    """Check if a Python file should be skipped."""
    return "__pycache__" in str(py_file) or py_file.name.startswith("__")


def _scan_module_for_nodes(module: Any, module_path: str, py_file: Path, BaseNode: type) -> list[dict[str, Any]]:
    """Scan a single module for BaseNode subclasses."""
    nodes = []
    for _name, obj in inspect.getmembers(module):
        if (
            inspect.isclass(obj)
            and issubclass(obj, BaseNode)
            and obj is not BaseNode
            and obj.__module__ == module.__name__
        ):
            metadata = extract_metadata(obj, module_path, py_file)
            nodes.append(metadata)
            logger.info(f"Discovered node: {metadata['name']} ({metadata['class_name']})")
    return nodes


def scan_for_nodes(directories: list[Path]) -> list[dict[str, Any]]:
    """
    Scan directories for Python files containing BaseNode subclasses.

    SECURITY WARNING: This function uses importlib.import_module() which
    executes Python code. Only use with trusted source directories.
    In future versions with user-provided nodes, additional sandboxing
    will be required.

    Args:
        directories: List of directories to scan for node files

    Returns:
        List of dictionaries containing node metadata
    """
    discovered_nodes = []

    # Prepare paths for sys.path modification
    project_root = Path(__file__).parent.parent.parent.parent
    pocketflow_path = project_root / "pocketflow"

    syspaths = [project_root]
    if pocketflow_path.exists():
        syspaths.append(pocketflow_path)

    with temporary_syspath(syspaths):
        # Import pocketflow to get BaseNode reference
        try:
            import pocketflow

            BaseNode = pocketflow.BaseNode
        except ImportError:
            logger.exception("Failed to import pocketflow")
            return []

        for directory in directories:
            if not directory.exists():
                logger.warning(f"Directory does not exist: {directory}")
                continue

            # Find all Python files
            for py_file in directory.rglob("*.py"):
                if _should_skip_file(py_file):
                    continue

                module_path = _calculate_module_path(py_file, directory)

                # Try to import the module
                try:
                    logger.debug(f"Attempting to import: {module_path}")
                    module = importlib.import_module(module_path)
                except Exception as e:
                    logger.warning(f"Failed to import {module_path}: {e}")
                    continue

                # Inspect module for BaseNode subclasses
                discovered_nodes.extend(_scan_module_for_nodes(module, module_path, py_file, BaseNode))

    return discovered_nodes
