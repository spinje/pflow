"""Shared YAML parsing for author-supplied content that may carry templates.

pflow layers its own ``${...}`` template syntax on top of YAML. PyYAML knows
nothing about templates: it reads the ``{`` in an unquoted ``${...}`` as the
start of a nested flow mapping, so a flow-style value like ``{ x: ${y} }`` fails
to parse even though the block form ``x: ${y}`` and the quoted form
``{ x: "${y}" }`` both succeed.

Every site that ``yaml.safe_load``s author content capable of containing
templates must go through :func:`safe_load_preserving_templates`, so an unquoted
template parses the same way everywhere — single-line param, multi-line param,
fenced YAML code block, or external file. Splitting this across ad-hoc call sites
is how the inline form ends up working in one place and breaking in another.
"""

from __future__ import annotations

import re
import secrets
from typing import Any

import yaml

# Scans author text for the spans we must treat specially before handing it to YAML:
#   - A double- or single-quoted YAML scalar is left UNTOUCHED. YAML already parses
#     quotes correctly (including unescaping ``\"``), and a ``${...}`` inside quotes
#     never breaks the flow tokenizer — masking it would strip YAML's escape
#     processing and corrupt e.g. ``"${a ?? \"x\"}"``. Quoted scalars are YAML's job.
#   - A *bare* (unquoted) ``${...}`` template (group 1) is what we mask. It tolerates
#     one level of nested ``{}`` so a coalesce operand with an object/array literal
#     (``${a ?? {}}``) is captured whole rather than truncated at its first ``}``.
#     This is *at least* the extent the runtime TemplateResolver accepts, and a bit
#     broader (it also captures content the runtime rejects, e.g. ``${a ?? {"k": 1}}``);
#     over-capturing is harmless because the mask/restore round-trip is verbatim.
#     Deeper-than-one-level nesting (``${a ?? {"k": {...}}}``) is NOT matched, so its
#     ``{`` reaches YAML and surfaces as a normal YAML error — acceptable, since those
#     aren't valid runtime templates either.
# There is no ``$$`` escape handling here (a literal ``$${y}`` still needs its ``{``
# protected just the same).
_SCAN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"'  # double-quoted YAML scalar — left untouched
    r"|'(?:''|[^'])*'"  # single-quoted YAML scalar — left untouched
    r"|(\$\{(?:[^{}]|\{[^{}]*\})*\})"  # (group 1) a bare ${...} template — masked
)


def safe_load_preserving_templates(text: str) -> Any:
    """``yaml.safe_load`` author content, shielding ``${...}`` templates from YAML.

    Masks each template with a unique placeholder, parses, then restores the
    original template text in the result — and in any error message — so an
    unquoted template inside a flow map/sequence parses like the block form.

    Raises:
        yaml.YAMLError: For content malformed independently of its templates
            (e.g. ``{invalid: [unclosed``). The error text shows the author's
            original ``${...}``, never the internal placeholder.
    """
    placeholders: dict[str, str] = {}
    # A per-call nonce keeps the placeholder un-guessable, so authored content can
    # never collide with it — a collision would silently corrupt the parsed value.
    nonce = secrets.token_hex(4)

    def _mask(match: re.Match[str]) -> str:
        template = match.group(1)
        if template is None:
            # A quoted scalar — leave it for YAML to (un)escape; only bare templates
            # break the flow tokenizer. (Masking inside quotes would corrupt `\"`.)
            return match.group(0)
        key = f"__pflow_tpl_{nonce}_{len(placeholders)}__"
        placeholders[key] = template
        return key

    masked = _SCAN_RE.sub(_mask, text)
    if not placeholders:
        return yaml.safe_load(masked)
    try:
        parsed = yaml.safe_load(masked)
    except yaml.YAMLError as exc:
        # De-mask in place before surfacing so the error quotes the author's ${...},
        # never the internal placeholder; bare re-raise keeps the original traceback.
        _demask_error(exc, placeholders)
        raise
    return _restore(parsed, placeholders)


def _restore(obj: Any, placeholders: dict[str, str]) -> Any:
    """Recursively swap masked placeholders back to their ``${...}`` templates."""
    if isinstance(obj, str):
        return _restore_str(obj, placeholders)
    if isinstance(obj, list):
        return [_restore(item, placeholders) for item in obj]
    if isinstance(obj, dict):
        return {_restore(k, placeholders): _restore(v, placeholders) for k, v in obj.items()}
    return obj


def _restore_str(text: str, placeholders: dict[str, str]) -> str:
    """Replace each masked placeholder in ``text`` with its original template."""
    for key, template in placeholders.items():
        text = text.replace(key, template)
    return text


def _demask_error(exc: yaml.YAMLError, placeholders: dict[str, str]) -> yaml.YAMLError:
    """Restore templates in a YAML error in place so it quotes the author's source.

    PyYAML renders — and truncates — its source snippet from the masked buffer, so
    de-masking the already-formatted string can leave a split placeholder fragment
    (a long line truncated mid-placeholder). Instead we restore the templates in the
    structured marks and re-derive the pointer, so the snippet renders from author
    text with a correctly-placed caret. Placeholders carry no newlines, so a mark's
    line index is unchanged; only its column shifts.
    """
    for attr in ("context_mark", "problem_mark"):
        mark = getattr(exc, attr, None)
        if mark is None or mark.buffer is None:
            continue
        mark.pointer = len(_restore_str(mark.buffer[: mark.pointer], placeholders))
        mark.buffer = _restore_str(mark.buffer, placeholders)
        mark.column = mark.pointer - (mark.buffer.rfind("\n", 0, mark.pointer) + 1)
    for attr in ("problem", "context", "note"):
        text = getattr(exc, attr, None)
        if isinstance(text, str):
            setattr(exc, attr, _restore_str(text, placeholders))
    return exc
