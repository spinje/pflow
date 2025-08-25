#!/usr/bin/env python3
"""Demonstration of the ShellNode capabilities."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pflow.nodes.shell import ShellNode


def demo_basic_command():
    """Demonstrate basic command execution."""
    print("=== Basic Command Demo ===")
    node = ShellNode()
    node.set_params({"command": "echo 'Hello from shell node!'"})
    shared = {}

    action = node.run(shared)
    print("Command: echo 'Hello from shell node!'")
    print(f"Output: {shared['stdout'].strip()}")
    print(f"Exit code: {shared['exit_code']}")
    print(f"Action: {action}")
    print()


def demo_pipes():
    """Demonstrate pipe support."""
    print("=== Pipe Command Demo ===")
    node = ShellNode()
    node.set_params({"command": "echo -e 'apple\\nbanana\\ncherry' | grep 'a' | wc -l"})
    shared = {}

    action = node.run(shared)
    print("Command: echo fruits | grep 'a' | wc -l")
    print(f"Lines with 'a': {shared['stdout'].strip()}")
    print(f"Action: {action}")
    print()


def demo_environment_variables():
    """Demonstrate environment variable support."""
    print("=== Environment Variables Demo ===")
    node = ShellNode()
    node.set_params({
        "command": 'echo "User: $MY_USER, Environment: $MY_ENV"',
        "env": {"MY_USER": "developer", "MY_ENV": "production"},
    })
    shared = {}

    action = node.run(shared)
    print("Command with custom env vars")
    print(f"Output: {shared['stdout'].strip()}")
    print()


def demo_working_directory():
    """Demonstrate working directory control."""
    print("=== Working Directory Demo ===")
    node = ShellNode()
    node.set_params({"command": "pwd", "cwd": "/tmp"})
    shared = {}

    action = node.run(shared)
    print("Command: pwd (with cwd=/tmp)")
    print(f"Working directory: {shared['stdout'].strip()}")
    print()


def demo_stdin_input():
    """Demonstrate stdin input."""
    print("=== Stdin Input Demo ===")
    node = ShellNode()
    node.set_params({"command": "grep 'important'"})
    shared = {"stdin": "line 1: not relevant\\nline 2: important data\\nline 3: also not relevant"}

    action = node.run(shared)
    print("Command: grep 'important' (with stdin)")
    print(f"Matched line: {shared['stdout'].strip()}")
    print()


def demo_error_handling():
    """Demonstrate error handling."""
    print("=== Error Handling Demo ===")

    # Command that fails
    node = ShellNode()
    node.set_params({"command": "ls /nonexistent_directory"})
    shared = {}

    action = node.run(shared)
    print("Command: ls /nonexistent_directory")
    print(f"Exit code: {shared['exit_code']}")
    print(f"Error output: {shared['stderr'].strip()[:50]}...")
    print(f"Action: {action}")
    print()

    # Same command with ignore_errors
    node = ShellNode()
    node.set_params({"command": "ls /nonexistent_directory", "ignore_errors": True})
    shared = {}

    action = node.run(shared)
    print("Same command with ignore_errors=true")
    print(f"Action: {action} (continues despite error)")
    print()


def demo_security():
    """Demonstrate security checks."""
    print("=== Security Demo ===")
    node = ShellNode()
    node.set_params({"command": "rm -rf /"})
    shared = {}

    try:
        action = node.run(shared)
    except ValueError as e:
        print(f"Dangerous command blocked: {e}")
    print()


def demo_complex_shell_script():
    """Demonstrate complex shell constructs."""
    print("=== Complex Shell Script Demo ===")
    node = ShellNode()
    node.set_params({"command": 'for i in 1 2 3; do echo "Processing item $i"; done'})
    shared = {}

    action = node.run(shared)
    print("Command: for loop")
    print(f"Output:\\n{shared['stdout']}")
    print()


if __name__ == "__main__":
    print("\\nShellNode Demonstration")
    print("=" * 50)
    print()

    demo_basic_command()
    demo_pipes()
    demo_environment_variables()
    demo_working_directory()
    demo_stdin_input()
    demo_error_handling()
    demo_security()
    demo_complex_shell_script()

    print("=" * 50)
    print("Demo complete! The ShellNode provides full shell power with:")
    print("✓ Pipe support (|, &&, ||)")
    print("✓ Environment variables")
    print("✓ Working directory control")
    print("✓ Stdin input")
    print("✓ Error handling")
    print("✓ Basic security checks")
    print("✓ Shell constructs (loops, conditions)")
