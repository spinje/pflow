"""Shared static/runtime validation for LLM structured-output schemas."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any, cast

from jsonschema import SchemaError
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012, Schema

from pflow.core.exceptions import LLMOutputSchemaError

_ROOT_SCHEMA_URI = "urn:pflow:llm-output-schema"
_REFERENCE_KEYWORDS = ("$ref", "$dynamicRef", "$recursiveRef")
_SIMPLE_JSON_PATH_KEY = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _child_json_path(parent: str, child: str | int) -> str:
    if isinstance(child, int):
        return f"{parent}[{child}]"
    if _SIMPLE_JSON_PATH_KEY.fullmatch(child):
        return f"{parent}.{child}"
    return f"{parent}[{json.dumps(child)}]"


def _schema_identity_paths(output_schema: dict[str, Any]) -> dict[int, str]:
    """Index authored object identities without deciding which dicts are schemas."""
    paths: dict[int, str] = {}
    visited: set[int] = set()

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            identity = id(value)
            paths.setdefault(identity, path)
            if identity in visited:
                return
            visited.add(identity)
            for key, child in value.items():
                walk(child, _child_json_path(path, str(key)))
        elif isinstance(value, list):
            identity = id(value)
            if identity in visited:
                return
            visited.add(identity)
            for index, child in enumerate(value):
                walk(child, _child_json_path(path, index))

    walk(output_schema, "$")
    return paths


def _resource_tree(
    resource: Resource[Schema],
    resolver: Any,
) -> Iterator[tuple[Resource[Schema], Any]]:
    """Yield schema resources with their draft-aware resolution scope."""
    yield resource, resolver
    for subresource in resource.subresources():
        resource_id = subresource.id()
        child_resolver = resolver.lookup(resource_id).resolver if resource_id else resolver
        yield from _resource_tree(subresource, child_resolver)


def _build_self_contained_registry(output_schema: dict[str, Any]) -> Registry[Schema]:
    """Build an offline registry and prove every authored reference resolves."""
    resource = Resource.from_contents(output_schema, default_specification=DRAFT202012)
    root_uri = resource.id() or _ROOT_SCHEMA_URI
    registry = Registry().with_resource(root_uri, resource).crawl()
    resolver = registry.resolver(root_uri)
    identity_paths = _schema_identity_paths(output_schema)
    current_path = "$"

    try:
        for current, current_resolver in _resource_tree(resource, resolver):
            contents = current.contents
            if not isinstance(contents, dict):
                continue
            current_path = identity_paths.get(id(contents), "$")
            for keyword in _REFERENCE_KEYWORDS:
                reference = contents.get(keyword)
                if isinstance(reference, str):
                    try:
                        current_resolver.lookup(reference)
                    except Unresolvable as exc:
                        schema_path = _child_json_path(current_path, keyword)
                        raise LLMOutputSchemaError(
                            f"Invalid output_schema at {schema_path}: reference {exc.ref!r} "
                            "cannot be resolved within the authored schema",
                            schema_path=schema_path,
                        ) from None
    except Unresolvable as exc:
        raise LLMOutputSchemaError(
            f"Invalid output_schema at {current_path}: reference {exc.ref!r} "
            "cannot be resolved within the authored schema",
            schema_path=current_path,
        ) from None

    return cast("Registry[Schema]", registry)


def prepare_output_schema_validator(output_schema: Any) -> Validator | None:
    """Validate an authored schema and return its offline draft-aware validator."""
    if output_schema is None:
        return None
    if not isinstance(output_schema, dict):
        raise LLMOutputSchemaError(
            f"Invalid output_schema: expected a JSON Schema dict, got {type(output_schema).__name__}",
            schema_path="$",
        )

    if "$schema" in output_schema:
        dialect = output_schema["$schema"]
        if not isinstance(dialect, str):
            raise LLMOutputSchemaError("Invalid output_schema: '$schema' must be a string", schema_path="$.$schema")
        validator_class = cast(
            "type[Validator] | None",
            validator_for(output_schema, default=cast(Any, None)),
        )
        if validator_class is None:
            raise LLMOutputSchemaError(
                f"Invalid output_schema: unsupported $schema dialect {dialect!r}",
                schema_path="$.$schema",
            )
    else:
        validator_class = validator_for(output_schema)

    try:
        validator_class.check_schema(output_schema)
    except SchemaError as exc:
        location = exc.json_path or "$"
        raise LLMOutputSchemaError(
            f"Invalid output_schema at {location}: {exc.message}",
            schema_path=location,
        ) from None

    registry = _build_self_contained_registry(output_schema)
    return validator_class(output_schema, registry=registry)
