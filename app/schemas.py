from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HubOut(BaseModel):
    id: str
    name: str
    city: str
    state: str
    region: str
    lat: float
    lon: float


class FactorOut(BaseModel):
    name: str
    value: float
    weight: float
    contribution: float


class HubRiskOut(BaseModel):
    id: str
    name: str
    city: str
    region: str
    risk_score: float
    factors: list[FactorOut]
    snow_days_pct: float | None = None


class IntentParse(BaseModel):
    """Structured intent extracted by the LLM before any scoring."""

    intent: Literal["rank", "compare", "metric", "explain", "other"]
    region: str | None = None
    hub_ids: list[str] = Field(default_factory=list)
    sort_by: Literal["risk_score", "winter", "flood", "wind"] | None = "risk_score"
    metric: Literal["snow_days_pct", "none"] | None = "none"
    notes: str | None = None


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    intent: str
    hubs: list[HubRiskOut]
    assumptions: list[str]
    uncertainty: list[str]
    session_id: str
