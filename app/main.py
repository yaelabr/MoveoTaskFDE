from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import APIStatusError

from app.agent import handle_chat, score_all_hubs
from app.hubs import all_hubs, get_hub
from app.risk import score_hub
from app.schemas import ChatRequest, ChatResponse, FactorOut, HubOut, HubRiskOut
from app.weather import fetch_features

load_dotenv()

app = FastAPI(
    title="Weather Risk Intelligence Agent",
    description="Deterministic hub weather-risk scoring with a Gemini-backed chat agent.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/hubs", response_model=list[HubOut])
def list_hubs() -> list[HubOut]:
    return [HubOut.model_validate(h.model_dump()) for h in all_hubs()]


@app.get("/hubs/{hub_id}/risk", response_model=HubRiskOut)
def hub_risk(hub_id: str) -> HubRiskOut:
    hub = get_hub(hub_id)
    if not hub:
        raise HTTPException(status_code=404, detail=f"Unknown hub id: {hub_id}")
    result = score_hub(hub, fetch_features(hub))
    return HubRiskOut(
        id=result.hub.id,
        name=result.hub.name,
        city=result.hub.city,
        region=result.hub.region,
        risk_score=result.risk_score,
        factors=[
            FactorOut(name=f.name, value=f.value, weight=f.weight, contribution=f.contribution)
            for f in result.factors
        ],
        snow_days_pct=result.features.snow_days_pct,
    )


@app.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    try:
        return handle_chat(body.message, body.session_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except APIStatusError as exc:
        detail = exc.message
        try:
            detail = exc.response.text
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=f"Gemini API error: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.get("/risk/ranking", response_model=list[HubRiskOut])
def risk_ranking() -> list[HubRiskOut]:
    """Deterministic ranking helper (no LLM) — useful for demos and evals."""
    results = score_all_hubs()
    return [
        HubRiskOut(
            id=r.hub.id,
            name=r.hub.name,
            city=r.hub.city,
            region=r.hub.region,
            risk_score=r.risk_score,
            factors=[
                FactorOut(name=f.name, value=f.value, weight=f.weight, contribution=f.contribution)
                for f in r.factors
            ],
            snow_days_pct=r.features.snow_days_pct,
        )
        for r in results
    ]
