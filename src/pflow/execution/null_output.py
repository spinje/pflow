"""Silent output implementation for non-interactive execution."""

from typing import Callable, Optional

from .output_interface import OutputInterface


class NullOutput(OutputInterface):
    """Silent output implementation that discards all output."""

    def show_progress(self, message: str, is_error: bool = False) -> None:
        """Discard progress message."""
        pass  # Silent

    def show_result(self, data: str) -> None:
        """Discard result data."""
        pass  # Silent

    def show_error(self, title: str, details: Optional[str] = None) -> None:
        """Discard error message."""
        pass  # Silent

    def show_success(self, message: str) -> None:
        """Discard success message."""
        pass  # Silent

    def create_node_callback(self) -> Optional[Callable]:
        """No progress tracking in silent mode."""
        return None

    def is_interactive(self) -> bool:
        """Always non-interactive."""
        return False
