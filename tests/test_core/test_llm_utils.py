"""Tests for shared LLM parsing utilities."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from pflow.core.exceptions import LLMResponseParseError
from pflow.core.llm_client import AdapterResponse
from pflow.core.llm_utils import parse_structured_response


class Selection(BaseModel):
    node_ids: list[str]


def test_parse_structured_response_validates_schema() -> None:
    response = AdapterResponse(text='{"node_ids": ["a", "b"]}', model="openai/gpt-4o-mini", has_schema=True)

    result = parse_structured_response(response, Selection, model=response.model)

    assert result == {"node_ids": ["a", "b"]}


def test_parse_structured_response_rejects_invalid_field_type() -> None:
    response = AdapterResponse(text='{"node_ids": null}', model="openai/gpt-4o-mini", has_schema=True)

    with pytest.raises(LLMResponseParseError) as exc_info:
        parse_structured_response(response, Selection, model=response.model)

    assert "does not match expected schema Selection" in str(exc_info.value)
    assert exc_info.value.model == "openai/gpt-4o-mini"


def test_parse_structured_response_rejects_non_object_json() -> None:
    response = AdapterResponse(text="42", model="openai/gpt-4o-mini", has_schema=True)

    with pytest.raises(LLMResponseParseError) as exc_info:
        parse_structured_response(response, Selection, model=response.model)

    assert "must be an object" in str(exc_info.value)
