"""Pydantic models for structured LLM output."""

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class NodeIR(BaseModel):
    """Node representation for IR generation."""

    id: str = Field(..., pattern="^[a-zA-Z0-9_-]+$")
    type: str = Field(..., description="Node type from registry")
    params: dict[str, Any] = Field(default_factory=dict)


class EdgeIR(BaseModel):
    """Edge representation for IR generation."""

    from_node: str = Field(..., alias="from")
    to_node: str = Field(..., alias="to")
    action: str = Field(default="default")


class FlowIR(BaseModel):
    """Flow IR for planner output generation."""

    ir_version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    nodes: list[NodeIR] = Field(..., min_length=1)
    edges: list[EdgeIR] = Field(default_factory=list)
    start_node: Optional[str] = None
    # Task 21 fields: workflows can declare their expected inputs/outputs
    inputs: Optional[dict[str, Any]] = None
    outputs: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict:
        """Convert to dict for validation with existing schema."""
        return self.model_dump(by_alias=True, exclude_none=True)


class WorkflowMetadata(BaseModel):
    """Structured metadata for workflow discovery and reuse.

    Critical for Path A success - enables workflows to be found
    with natural language variations.
    """

    suggested_name: str = Field(
        description="Concise, searchable name in kebab-case (max 50 chars)",
        max_length=50,
        pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )

    description: str = Field(
        description="Comprehensive description for discovery (100-500 chars)", min_length=100, max_length=500
    )

    search_keywords: list[str] = Field(
        description="Alternative terms users might search for", min_length=3, max_length=10
    )

    capabilities: list[str] = Field(description="What this workflow can do (bullet points)", min_length=2, max_length=6)

    typical_use_cases: list[str] = Field(description="When/why someone would use this", min_length=1, max_length=3)

    @field_validator("search_keywords")
    @classmethod
    def validate_keywords(cls, v: list[str]) -> list[str]:
        """Ensure keywords are unique and lowercase."""
        return list(dict.fromkeys(keyword.lower() for keyword in v))

    @field_validator("suggested_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure name is lowercase kebab-case."""
        return v.lower().replace("_", "-")
