from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from typing import TypeVar

from openai import APIStatusError, OpenAI

from app.hubs import Hub, all_hubs, get_hub, hubs_by_region, resolve_hubs
from app.risk import RiskResult, rank_results, score_hub
from app.schemas import ChatResponse, FactorOut, HubRiskOut, IntentParse
from app.weather import fetch_features

logger = logging.getLogger(__name__)

# In-memory short history for follow-ups: session_id -> list[{role, content}]
_SESSIONS: dict[str, list[dict[str, str]]] = {}

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# Free-tier friendly default. Full flash models often 404 for new keys or hit low quotas (429).
DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
)

T = TypeVar("T")


def _client() -> OpenAI:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add a free key from Google AI Studio."
        )
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("GEMINI_BASE_URL", GEMINI_BASE_URL),
    )


def _model_candidates() -> list[str]:
    primary = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    ordered: list[str] = []
    for name in (primary, *FALLBACK_MODELS):
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def _hub_catalog() -> str:
    lines = []
    for hub in all_hubs():
        lines.append(f"- {hub.id}: {hub.city}, {hub.state} ({hub.region})")
    return "\n".join(lines)


def _call_gemini(fn: Callable[[str], T], *, label: str) -> T:
    """Try preferred model then fallbacks; retry transient 429/503 per model."""
    client_errors: list[str] = []
    for model in _model_candidates():
        for attempt in range(3):
            try:
                return fn(model)
            except APIStatusError as exc:
                detail = ""
                try:
                    detail = exc.response.text[:240]
                except Exception:
                    detail = str(exc)
                client_errors.append(f"{model} attempt {attempt + 1}: {exc.status_code} {detail}")
                logger.warning("Gemini %s failed on %s: %s", label, model, detail)
                if exc.status_code in {429, 503} and attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                # 404 / hard failures -> next model
                break
            except Exception as exc:
                client_errors.append(f"{model} attempt {attempt + 1}: {type(exc).__name__}: {exc}")
                logger.warning("Gemini %s error on %s: %s", label, model, exc)
                if attempt < 2:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                break
    raise RuntimeError(f"Gemini {label} failed for all models. " + " | ".join(client_errors[:4]))


def heuristic_intent(message: str) -> IntentParse:
    """Offline intent parse so demos still work if Gemini is down."""
    text = message.lower()
    hub_ids: list[str] = []
    for hub in all_hubs():
        if hub.city.lower() in text or re.search(rf"\b{re.escape(hub.id)}\b", text):
            hub_ids.append(hub.id)

    region = None
    for name in ("midwest", "gulf", "south", "southeast", "mountain", "pacific", "southwest"):
        if name in text:
            region = name.title() if name != "midwest" else "Midwest"
            if name == "gulf":
                region = "Gulf"
            break

    sort_by = "risk_score"
    metric = "none"
    intent: str = "other"

    if any(w in text for w in ("snow", "snowfall", "percent", "%")) and hub_ids:
        intent = "metric"
        metric = "snow_days_pct"
    elif any(w in text for w in ("why", "explain")) and hub_ids:
        intent = "explain"
    elif any(w in text for w in ("compare", " vs ", "versus")) or len(hub_ids) >= 2:
        intent = "compare"
    elif any(w in text for w in ("rank", "most", "which hubs", "exposed", "highest")):
        intent = "rank"

    if any(w in text for w in ("winter", "snow", "cold")):
        sort_by = "winter"
    elif any(w in text for w in ("hurricane", "flood", "rain")):
        sort_by = "flood"
    elif "wind" in text:
        sort_by = "wind"

    return IntentParse(
        intent=intent if intent in {"rank", "compare", "metric", "explain", "other"} else "other",
        region=region,
        hub_ids=hub_ids,
        sort_by=sort_by,  # type: ignore[arg-type]
        metric=metric,  # type: ignore[arg-type]
        notes="heuristic_fallback",
    )


def parse_intent(message: str, history: list[dict[str, str]] | None = None) -> IntentParse:
    history_text = ""
    if history:
        history_text = "Recent conversation:\n" + "\n".join(
            f"{m['role']}: {m['content']}" for m in history[-6:]
        )

    system = (
        "You extract analyst intent for a weather-risk hub tool. "
        "Only use hub ids from the catalog. "
        "intent=rank for ranking/filtering; compare for two+ hubs; "
        "metric for a specific statistic like snow-day percentage; "
        "explain for why a hub is risky; other otherwise. "
        "sort_by=winter for winter disruption questions; flood for hurricane/flood; "
        "wind for wind; else risk_score. "
        "metric=snow_days_pct when asked for snowfall day percentage."
    )
    user = (
        f"Hub catalog:\n{_hub_catalog()}\n\n"
        f"{history_text}\n\n"
        f"User message: {message}"
    )

    def _call(model: str) -> IntentParse:
        client = _client()
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=IntentParse,
            temperature=0.2,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is not None:
            return parsed
        content = completion.choices[0].message.content or "{}"
        return IntentParse.model_validate_json(content)

    try:
        return _call_gemini(_call, label="intent parse")
    except Exception as exc:
        logger.error("Falling back to heuristic intent: %s", exc)
        return heuristic_intent(message)


def _select_hubs(intent: IntentParse) -> list[Hub]:
    hubs: list[Hub] = []
    if intent.hub_ids:
        hubs = resolve_hubs(intent.hub_ids)
        if not hubs:
            hubs = [h for hid in intent.hub_ids if (h := get_hub(hid))]
    if not hubs and intent.region:
        hubs = hubs_by_region(intent.region)
    if not hubs and intent.intent in {"rank", "other"}:
        hubs = all_hubs()
    return hubs


def _score_many(hubs: list[Hub]) -> list[RiskResult]:
    return [score_hub(hub, fetch_features(hub)) for hub in hubs]


def _to_hub_risk_out(result: RiskResult) -> HubRiskOut:
    return HubRiskOut(
        id=result.hub.id,
        name=result.hub.name,
        city=result.hub.city,
        region=result.hub.region,
        risk_score=result.risk_score,
        factors=[
            FactorOut(
                name=f.name,
                value=f.value,
                weight=f.weight,
                contribution=f.contribution,
            )
            for f in result.factors
        ],
        snow_days_pct=result.features.snow_days_pct,
    )


def _facts_blob(intent: IntentParse, results: list[RiskResult]) -> str:
    payload = {
        "intent": intent.intent,
        "sort_by": intent.sort_by,
        "metric": intent.metric,
        "hubs": [
            {
                "id": r.hub.id,
                "city": r.hub.city,
                "region": r.hub.region,
                "risk_score": r.risk_score,
                "factors": {f.name: f.value for f in r.factors},
                "snow_days_pct": r.features.snow_days_pct,
            }
            for r in results
        ],
    }
    return json.dumps(payload, indent=2)


def _factor_value(result: RiskResult, name: str) -> float:
    for factor in result.factors:
        if factor.name == name:
            return factor.value
    return 0.0


def _template_answer(intent: IntentParse, results: list[RiskResult]) -> str:
    """Conversational fallback when Gemini narration is unavailable."""
    if not results:
        return (
            "I couldn't match that to hubs in our curated list. "
            "Try a known city (Chicago, Miami, Denver, …) or a region like Midwest."
        )

    if intent.intent == "metric" and intent.metric == "snow_days_pct" and len(results) == 1:
        r = results[0]
        return (
            f"For {r.hub.city}, about **{r.features.snow_days_pct}%** of days in the last year "
            f"had snowfall, based on Open-Meteo archive data. "
            f"That's a day-count share, not storm severity."
        )

    sort_by = intent.sort_by or "risk_score"
    focus = {
        "winter": "winter disruption (snow/cold days)",
        "flood": "flood / heavy-precip exposure (with a coastal bump for Gulf hubs)",
        "wind": "high-wind days",
        "risk_score": "overall weather-disruption risk",
    }.get(sort_by, "overall weather-disruption risk")

    ranked_names = ", ".join(r.hub.city for r in results)
    top = results[0]
    top_detail = ""
    if sort_by == "winter":
        top_detail = f" with the highest winter factor ({_factor_value(top, 'winter')})"
    elif sort_by == "flood":
        top_detail = f" with the highest flood factor ({_factor_value(top, 'flood')})"
    elif sort_by == "wind":
        top_detail = f" with the highest wind factor ({_factor_value(top, 'wind')})"
    else:
        top_detail = f" with overall score {top.risk_score}"

    if intent.intent == "compare" and len(results) >= 2:
        a, b = results[0], results[1]
        answer = (
            f"Comparing on **{focus}**, **{a.hub.city}** currently looks more exposed than "
            f"**{b.hub.city}** in our curated set"
            f"{' (driven by' + top_detail + ')' if top_detail else ''}. "
            f"Full factor breakdowns are in the structured details."
        )
    elif intent.intent == "explain" and len(results) == 1:
        r = results[0]
        parts = ", ".join(f"{f.name} {f.value}" for f in r.factors)
        answer = (
            f"**{r.hub.city}**'s disruption risk score is **{r.risk_score}** on our 0–100 KPI. "
            f"The main drivers are {parts}. "
            f"These come from last-year Open-Meteo features (relative comparison, not loss estimates)."
        )
    else:
        scope = intent.region or "our curated hub list"
        answer = (
            f"For **{focus}** across {scope}, I'd rank them: **{ranked_names}**. "
            f"**{top.hub.city}** leads{top_detail}. "
            f"These are relative decision aids from last-year weather features — "
            f"open structured details for the full factor table."
        )

    answer += (
        " Assumptions: fixed hub list; Gulf hurricane/flood uses precip + a transparent coastal bump, "
        "not a storm catalogue."
    )
    if intent.notes == "heuristic_fallback":
        answer += " (Gemini was briefly unavailable, so this explanation used the deterministic fallback.)"
    return answer


def narrate_answer(message: str, intent: IntentParse, results: list[RiskResult]) -> str:
    if not results:
        return _template_answer(intent, results)

    if intent.intent == "metric" and intent.metric == "snow_days_pct" and len(results) == 1:
        return _template_answer(intent, results)

    system = (
        "You are a logistics weather-risk analyst assistant speaking in chat. "
        "Write a short conversational answer (2–5 sentences). "
        "Use ONLY the provided computed facts — never invent or alter scores. "
        "Lead with the ranking or comparison in plain language; mention 1–2 key numbers as evidence. "
        "Do NOT dump raw factor tables or JSON in the answer — those belong in structured details. "
        "End with one brief assumptions/uncertainty clause when relevant."
    )
    user = (
        f"User question: {message}\n\n"
        f"Computed facts (authoritative):\n{_facts_blob(intent, results)}\n\n"
        "Write the final conversational answer for the analyst."
    )

    def _call(model: str) -> str:
        client = _client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
        return (response.choices[0].message.content or "").strip()

    try:
        return _call_gemini(_call, label="narration")
    except Exception as exc:
        logger.error("Falling back to template narration: %s", exc)
        return _template_answer(intent, results)


def handle_chat(message: str, session_id: str | None = None) -> ChatResponse:
    sid = session_id or str(uuid.uuid4())
    history = _SESSIONS.setdefault(sid, [])

    intent = parse_intent(message, history)
    hubs = _select_hubs(intent)
    results = _score_many(hubs)
    sort_by = intent.sort_by or "risk_score"
    ranked = rank_results(results, sort_by=sort_by)

    answer = narrate_answer(message, intent, ranked)
    assumptions = ranked[0].assumptions if ranked else [
        "Fixed curated hub list only.",
    ]
    uncertainty = ranked[0].uncertainty if ranked else []

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": answer})
    _SESSIONS[sid] = history[-12:]

    return ChatResponse(
        answer=answer,
        intent=intent.intent,
        hubs=[_to_hub_risk_out(r) for r in ranked],
        assumptions=assumptions,
        uncertainty=uncertainty,
        session_id=sid,
    )


def score_all_hubs() -> list[RiskResult]:
    return rank_results(_score_many(all_hubs()))
