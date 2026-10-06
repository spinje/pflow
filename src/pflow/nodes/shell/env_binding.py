"""How a shell step's ``env:`` map becomes the command's environment (ADR-0016).

One rule set, three callers: the validator and the compiler report ``env_problems``
for a literal map; ``ShellNode.prep()`` calls ``bind_env`` on the resolved map, so
every entry path (engine, batch item, single-node probe) binds the same way.
A value binds as ``core/templates.to_string(value)`` — exactly the text ``${x}``
produces inside any string.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass

from pflow.core.exceptions import NodeError
from pflow.core.templates import to_string

# Upper-cased name -> what replacing it does to the command. Compared case-insensitively
# (Windows names ignore case). A warning at validation, never a refusal: `env:` legitimately
# sets real variables.
SHELL_OWNED: Mapping[str, str] = {
    "PATH": "commands outside the new value will not be found",
    "HOME": "it decides `~` and where tools look for their config files",
    "IFS": "it decides how the shell splits words",
    "ENV": "it names a file the shell runs before the command",
    "BASH_ENV": "it names a file the shell runs before the command",
    "PS4": "the shell expands it when tracing",
    "LD_PRELOAD": "it names a library loaded into every program the command starts",
}

# Names a suggested binding name must not land on (ambient or shell-owned variables).
AMBIENT_NAMES: frozenset[str] = frozenset(SHELL_OWNED) | {
    "LANG",
    "USER",
    "TERM",
    "TZ",
    "TMPDIR",
    "SHELL",
    "PWD",
    "CI",
    "DEBUG",
    "EDITOR",
    "DISPLAY",
    "HOSTNAME",
    "LOGNAME",
}

_SHELL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class EnvBindingError(NodeError):
    """An ``env:`` entry cannot become an environment variable.

    Raised before the command starts (``prep()``, or ``exec()`` for the OS size
    refusal). Never a command exit code, so ``ignore_errors`` cannot swallow it.
    Deterministic: retrying cannot fix it, and a batch item fails without
    aborting a ``continue`` batch.
    """

    retriable = False
    batch_fatal = False

    def __init__(self, message: str) -> None:
        super().__init__(message, param="env")


@dataclass(frozen=True, slots=True)
class EnvProblem:
    """One reason an ``env:`` map cannot bind. ``name`` is None for a map-level problem."""

    name: str | None
    message: str
    fix: str

    def sentence(self) -> str:
        return f"{self.message} {self.fix}" if self.fix else self.message


def env_problems(env: object) -> list[EnvProblem]:
    """Why ``env`` cannot bind: not a map, a name sh cannot read, a case collision, a value
    whose text holds a NUL or cannot be encoded.

    ``None`` means no ``env:`` and has no problems. Each value is checked as the text it
    binds as (``to_string``), so a literal object holding a bad string is caught statically.
    """
    if env is None:
        return []
    if not isinstance(env, dict):
        return [EnvProblem(None, f"env must be a map of NAME: value — got {_a_type(env)}.", "")]
    problems: list[EnvProblem] = []
    first_spelling: dict[str, str] = {}
    for key, value in env.items():
        name = _as_written(key)
        if not isinstance(key, str) or not _SHELL_NAME.fullmatch(key):
            problems.append(EnvProblem(name, f"env name '{name}' cannot be read as a shell variable.", _name_fix(key)))
            continue
        if (other := first_spelling.setdefault(key.upper(), key)) != key:
            problems.append(
                EnvProblem(
                    None,
                    f"env names '{other}' and '{key}' differ only by case — on Windows they are one variable.",
                    "Keep one of them.",
                )
            )
        if problem := _value_problem(key, to_string(value)):
            problems.append(problem)
    return problems


def bind_env(env: object) -> dict[str, str]:
    """The environment variables ``env`` binds: each value as ``to_string(value)``.

    Always a fresh dict — never the caller's map. Raises ``EnvBindingError`` naming
    the variable when a name or value cannot bind.
    """
    if problems := env_problems(env):
        raise EnvBindingError(problems[0].sentence())
    if not isinstance(env, dict):  # None: no env: (env_problems rejected every other non-map)
        return {}
    return {name: to_string(value) for name, value in env.items()}


def merge_env(inherited: Mapping[str, str], bound: Mapping[str, str], *, ignore_case: bool) -> dict[str, str]:
    """The child environment: ``inherited`` overlaid with ``bound``; neither input is mutated.

    With ``ignore_case`` (Windows) the author's spelling wins: an inherited name equal
    to a bound one ignoring case is dropped, so the child never sees two of them.
    """
    if ignore_case:
        bound_upper = {name.upper() for name in bound}
        merged = {name: value for name, value in inherited.items() if name.upper() not in bound_upper}
    else:
        merged = dict(inherited)
    merged.update(bound)
    return merged


def oversized_error(bound: Mapping[str, str], command: str) -> EnvBindingError:
    """The OS refused to start the command (E2BIG): name the largest bound value and the command."""
    sizes = []
    if bound:
        name, value = max(bound.items(), key=lambda item: _byte_size(item[1]))
        sizes.append(f"largest: {name} {_human_size(_byte_size(value))} bound in env:")
    sizes.append(f"the command {_human_size(_byte_size(command))}")
    limit = _PLATFORM_LIMITS.get(sys.platform)
    return EnvBindingError(
        "The command could not start: its environment and arguments are too large for the operating system "
        f"({', '.join(sizes)}). Pass large values through stdin instead and remove them from env:"
        + (f" — {limit}." if limit else ".")
    )


# Only the current platform's limit is named; the Windows figure comes from CI first.
_PLATFORM_LIMITS: Mapping[str, str] = {
    "darwin": "on macOS the limit is about 1 MB for everything together",
    "linux": "on Linux one value can be at most 128 KB",
}


def _value_problem(name: str, text: str) -> EnvProblem | None:
    if "\0" in text:
        return EnvProblem(
            name,
            f"The value bound to {name} in env: contains a NUL byte, which an environment variable cannot hold.",
            _stdin_fix(name),
        )
    if sys.platform != "win32":
        try:
            os.fsencode(text)
        except UnicodeEncodeError:
            return EnvProblem(
                name,
                f"The value bound to {name} in env: contains a character the operating system cannot put "
                "in an environment variable.",
                f"Repair the invalid Unicode in the upstream value before binding {name} — "
                "passing the same text through stdin fails too.",
            )
    return None


def _stdin_fix(name: str) -> str:
    return f"Pass that value through stdin instead (`- stdin: ${{…}}`, read it with cat) and remove {name} from env:."


def _name_fix(key: object) -> str:
    if key is None or isinstance(key, bool):
        # The key was a YAML word (null, yes, off, …) — its spelling is lost, so never suggest one back.
        kind = "null" if key is None else "boolean"
        return f"YAML read this key as a {kind}, not text: quote the key so it stays the name you wrote."
    suggestion = _suggest_name(_as_written(key))
    return (
        "Use letters, digits and underscores, not starting with a digit — "
        f'e.g. {suggestion} — and read it as "${suggestion}" in the command.'
    )


def _as_written(key: object) -> str:
    """A YAML key as the author wrote it: ``true:`` / ``null:`` / ``1:`` arrive as Python values."""
    if key is None:
        return "null"
    if isinstance(key, bool):
        return "true" if key else "false"
    return str(key)


def _suggest_name(name: str) -> str:
    suggestion = re.sub(r"[^A-Za-z0-9_]", "_", name).upper() or "VALUE"
    if suggestion[0].isdigit():
        suggestion = f"VAR_{suggestion}"
    return f"{suggestion}_VALUE" if suggestion in AMBIENT_NAMES else suggestion


def _a_type(value: object) -> str:
    type_name = type(value).__name__
    return f"an {type_name}" if type_name[0] in "aeiou" else f"a {type_name}"


def _byte_size(text: str) -> int:
    return len(text.encode("utf-8", errors="surrogatepass"))


def _human_size(size: int) -> str:
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} MB"
    if size >= 1_000:
        return f"{round(size / 1_000)} KB"
    return f"{size} bytes"
