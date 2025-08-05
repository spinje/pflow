"""Pydantic models for structured LLM output."""

from typing import Any, Optional

from pydantic import BaseModel, Field


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
