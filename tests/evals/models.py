from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from sports_data_mcp.tools.contract import ToolNameLiteral
from sports_data_mcp.types import QueryTypeLiteral, SportLiteral


class ExpectedPlan(BaseModel):
    tool: ToolNameLiteral
    args: dict


class SeedQuestion(BaseModel):
    id: str
    sport: SportLiteral
    tool_category: QueryTypeLiteral
    difficulty: Literal["easy", "medium", "hard"]
    phrasing: Literal["literal", "conversational"]
    question: str
    expected_plan: ExpectedPlan


class GoldenFact(BaseModel):
    fact_id: str
    sport: SportLiteral
    question: str
    expected_value: str
    stat: str
    source_url: str
    verified_against: str
