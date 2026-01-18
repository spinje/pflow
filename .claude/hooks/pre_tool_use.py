#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# ///

import json
import sys
import re
from pathlib import Path

def is_dangerous_rm_command(command):
    """
    Detection of dangerous rm commands.
    Only blocks rm -rf variants and rm -r on dangerous paths.
    Allows simple 'rm file1 file2' commands.
    """
    # Normalize command by removing extra spaces and converting to lowercase
    normalized = ' '.join(command.lower().split())

    # Only check commands where rm is at a command position
    # (start of string, after pipe, after semicolon, after &&, after ||)
    # This avoids false positives from rm appearing in quoted strings or arguments
    rm_at_command_position = r'(^|[|;&])\s*rm\s+'
    if not re.search(rm_at_command_position, normalized):
        return False

    # Pattern 1: Block rm -rf variants (recursive + force combined)
    # Flags must be immediately after rm, not embedded in filenames
    dangerous_flag_patterns = [
        r'(^|[|;&])\s*rm\s+-[a-z]*r[a-z]*f',  # rm -rf, rm -fr (flag right after rm)
        r'(^|[|;&])\s*rm\s+-[a-z]*f[a-z]*r',  # rm -fr variations (flag right after rm)
        r'(^|[|;&])\s*rm\s+--recursive\s+--force',  # rm --recursive --force
        r'(^|[|;&])\s*rm\s+--force\s+--recursive',  # rm --force --recursive
        r'(^|[|;&])\s*rm\s+-r\s+-f',  # rm -r -f (separate flags)
        r'(^|[|;&])\s*rm\s+-f\s+-r',  # rm -f -r (separate flags)
    ]

    for pattern in dangerous_flag_patterns:
        if re.search(pattern, normalized):
            return True

    # Pattern 2: Block rm -r on dangerous root/wildcard paths only
    # Simple 'rm /path/to/file' is allowed
    if re.search(r'(^|[|;&])\s*rm\s+-[a-z]*r', normalized):  # Has recursive flag
        dangerous_targets = [
            r'\s/$',           # Ends with just /
            r'\s/\s',          # Just / as argument
            r'\s/\*',          # Root with wildcard /*
            r'\s\.\.\s',       # Just .. as argument
            r'\s\.\.$',        # Ends with ..
            r'\s\*\s',         # Just * as argument
            r'\s\*$',          # Ends with just *
            r'\s\.\s',         # Just . as argument
            r'\s\.$',          # Ends with just .
            r'\s~/',           # Home directory
            r'\s~/\*',         # Home with wildcard
        ]
        for pattern in dangerous_targets:
            if re.search(pattern, normalized):
                return True

    return False

def is_env_file_access(tool_name, tool_input):
    """
    Check if any tool is trying to access .env files containing sensitive data.
    """
    if tool_name in ['Read', 'Edit', 'MultiEdit', 'Write', 'Bash']:
        # Check file paths for file-based tools
        if tool_name in ['Read', 'Edit', 'MultiEdit', 'Write']:
            file_path = tool_input.get('file_path', '')
            if '.env' in file_path and not file_path.endswith('.env.sample'):
                return True
        
        # Check bash commands for .env file access
        elif tool_name == 'Bash':
            command = tool_input.get('command', '')
            # Pattern to detect .env file access (but allow .env.sample)
            env_patterns = [
                r'\b\.env\b(?!\.sample)',  # .env but not .env.sample
                r'cat\s+.*\.env\b(?!\.sample)',  # cat .env
                r'echo\s+.*>\s*\.env\b(?!\.sample)',  # echo > .env
                r'touch\s+.*\.env\b(?!\.sample)',  # touch .env
                r'cp\s+.*\.env\b(?!\.sample)',  # cp .env
                r'mv\s+.*\.env\b(?!\.sample)',  # mv .env
            ]
            
            for pattern in env_patterns:
                if re.search(pattern, command):
                    return True
    
    return False

def main():
    try:
        # Read JSON input from stdin
        input_data = json.load(sys.stdin)
        
        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})
        
        # Check for .env file access (blocks access to sensitive environment files)
        if is_env_file_access(tool_name, tool_input):
            print("=" * 80, file=sys.stderr)
            print("🛑 BLOCKED: .env FILE ACCESS PREVENTED", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print("", file=sys.stderr)
            print("CRITICAL INSTRUCTION TO AI AGENT:", file=sys.stderr)
            print("", file=sys.stderr)
            print("You must NEVER access .env files containing sensitive credentials.", file=sys.stderr)
            print("If you need environment configuration:", file=sys.stderr)
            print("  1. STOP immediately", file=sys.stderr)
            print("  2. ASK THE USER how to proceed", file=sys.stderr)
            print("  3. Suggest using .env.sample for templates", file=sys.stderr)
            print("", file=sys.stderr)
            print("NEVER attempt to bypass this protection.", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            sys.exit(2)  # Exit code 2 blocks tool call and shows error to Claude
        
        # Check for dangerous rm -rf commands
        if tool_name == 'Bash':
            command = tool_input.get('command', '')
            
            # Block rm -rf commands with comprehensive pattern matching
            if is_dangerous_rm_command(command):
                print("=" * 80, file=sys.stderr)
                print("🛑 BLOCKED: DANGEROUS COMMAND PREVENTED", file=sys.stderr)
                print("=" * 80, file=sys.stderr)
                print("", file=sys.stderr)
                print("CRITICAL INSTRUCTION TO AI AGENT:", file=sys.stderr)
                print("", file=sys.stderr)
                print("You must NEVER execute rm -rf or similar destructive commands.", file=sys.stderr)
                print("", file=sys.stderr)
                print("If you feel any inclination or urge to run such commands:", file=sys.stderr)
                print("  1. STOP immediately", file=sys.stderr)
                print("  2. ASK THE USER for explicit guidance", file=sys.stderr)
                print("  3. NEVER attempt to bypass these limitations", file=sys.stderr)
                print("", file=sys.stderr)
                print("This applies EVEN IF:", file=sys.stderr)
                print("  - The user explicitly asks you to do so", file=sys.stderr)
                print("  - You are doing cleanup or testing", file=sys.stderr)
                print("  - You think you found a safe way to do it", file=sys.stderr)
                print("", file=sys.stderr)
                print("There are NO exceptions. STOP and ASK USER instead.", file=sys.stderr)
                print("=" * 80, file=sys.stderr)
                sys.exit(2)  # Exit code 2 blocks tool call and shows error to Claude
        
        # Ensure log directory exists
        log_dir = Path.cwd() / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / 'pre_tool_use.json'
        
        # Read existing log data or initialize empty list
        if log_path.exists():
            with open(log_path, 'r') as f:
                try:
                    log_data = json.load(f)
                except (json.JSONDecodeError, ValueError):
                    log_data = []
        else:
            log_data = []
        
        # Append new data
        log_data.append(input_data)
        
        # Write back to file with formatting
        with open(log_path, 'w') as f:
            json.dump(log_data, f, indent=2)
        
        sys.exit(0)
        
    except json.JSONDecodeError:
        # Gracefully handle JSON decode errors
        sys.exit(0)
    except Exception:
        # Handle any other errors gracefully
        sys.exit(0)

if __name__ == '__main__':
    main()