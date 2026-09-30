"""Compatibility shim: the template language lives in ``pflow.core.templates``.

Kept only for the tests that still import this path; deleted in Task 170 phase 5.
New code imports ``pflow.core.templates``.
"""

from pflow.core.templates import Resolution, TemplateResolver, resolve

__all__ = ["Resolution", "TemplateResolver", "resolve"]
