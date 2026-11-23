# Architecture

Short design notes for the Weather Risk Intelligence Agent.

## Goals

- Answer analyst questions about hub weather disruption risk with clear reasoning.
- Keep scores **deterministic and inspectable** (code owns the KPI; the LLM does not invent numbers).
- Stay lean enough for a one-day take-home: few moving parts, easy to run locally.

## System architecture

```
┌──────────────┐  HTTP JSON   ┌─────────────────────────────┐
│ Streamlit UI │ ───────────► │ FastAPI (app/main.py)         │
│ ui/chat.py   │ ◄─────────── │ /chat /hubs /health /risk/*   │
└──────────────┘              └──────────────┬──────────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    ▼                        ▼                        ▼
           ┌────────────────┐      ┌─────────────────┐      ┌─────────────────┐
           │ Agent          │      │ Risk engine     │      │ Weather client  │
           │ (Gemini JSON   │      │ (deterministic  │      │ (Open-Meteo     │
           │  intent +      │      │  0–100 KPI)     │      │  archive)       │
           │  narration)    │      └────────┬────────┘      └────────┬────────┘
           └────────┬───────┘               │                        │
                    │                       ▼                        │
                    │              ┌─────────────────┐               │
                    └─────────────►│ data/hubs.json  │◄──────────────┘
                                   └─────────────────┘
```

### Request flow (`POST /chat`)

1. Streamlit sends `{ message, session_id? }` to FastAPI.
2. **Intent step:** Gemini returns a structured `IntentParse` object (Pydantic / JSON schema): intent type, hubs/region, sort factor, optional metric. Validated before use.
3. **Hub selection:** Resolve hubs from intent ids **and** cities named in the user text (so “Atlanta, Phoenix, Seattle” does not silently drop names the model omitted).
4. **Weather + score:** Fetch Open-Meteo daily archive features (~last 365 days), compute the KPI in `risk.py`, rank/compare in code.
5. **Narration step:** Gemini writes a short conversational answer **from those computed facts only**. Full factor tables stay in the structured response (UI “Structured details”).
6. Short chat history is kept in memory per `session_id` for follow-ups.

If Gemini is unavailable (quota/outage), heuristic intent + a template explanation still return deterministic scores so demos do not hard-fail.

### Components

| Component | Role | Why this shape |
|-----------|------|----------------|
| **Streamlit UI** | Chat client only | Fast to demo; no custom frontend build. Keeps UI thin so the API is the real product surface. |
| **FastAPI** | HTTP API the UI (and examiners) call | Clear contract; easy to curl without the LLM UI. |
| **Agent (`agent.py`)** | Orchestrates LLM ↔ tools/code | Separates “language” from “math.” Structured intent satisfies the JSON-schema requirement. |
| **Risk engine (`risk.py`)** | Weighted KPI + ranking | Transparent, unit-testable, independent of the LLM. |
| **Weather (`weather.py`)** | Open-Meteo archive client + process cache | Free, no API key, enough history for “last year” questions. |
| **Hubs (`hubs.py` + JSON)** | Curated hub registry | Fixed scope; versioned with the repo; no DB ops. |
| **Evals** | Smoke checks on weather + scoring | Prove deterministic path without burning Gemini quota. |

### Risk KPI (decision)

Score ∈ `[0, 100]` = weighted blend of:

- **winter (40%)** — snow days / cold days  
- **flood (35%)** — heavy-precip days; Gulf hubs get a fixed coastal bump  
- **wind (25%)** — high-wind days  

**Why three factors:** enough to answer the sample questions (winter, flood/hurricane proxy, overall risk) without pretending to be a catastrophe model.

**Why a Gulf coastal bump:** Open-Meteo alone does not give a true hurricane catalogue. A small, documented bump makes Gulf exposure visible while staying honest about uncertainty.

**Why relative framing in answers:** absolute scores on this toy KPI are often small; examiners care about ranking and drivers, not false precision.

## Repository structure

```
MoveoTaskFDE/
├── README.md              # Runbook + short overview
├── ARCHITECTURE.md        # This document
├── requirements.txt
├── .env.example           # GEMINI_* and API URL (no secrets)
├── data/
│   └── hubs.json          # Curated hubs (source of truth)
├── app/
│   ├── main.py            # FastAPI routes
│   ├── agent.py           # Gemini orchestration + fallbacks
│   ├── risk.py            # Deterministic scoring / ranking
│   ├── weather.py         # Open-Meteo + in-memory cache
│   ├── hubs.py            # Hub load / resolve
│   └── schemas.py         # Pydantic request/response + intent schema
├── ui/
│   └── chat.py            # Streamlit client
└── evals/
    ├── cases.json         # Small case set
    └── run_eval.py        # Runner (no LLM)
```

**Why flat `app/` (not a deep package tree):** junior take-home readability — one place for backend logic, obvious imports, minimal ceremony.

## Data storage choice

| Data | Storage | Why |
|------|---------|-----|
| Hubs | `data/hubs.json` in git | Tiny, static, reviewable; no migration/ops cost. |
| Weather responses | In-process dict cache keyed by hub id | Enough for a local demo session; avoids SQLite/Redis complexity. Resets on process restart (acceptable here). |
| Chat sessions | In-memory dict by `session_id` | Supports follow-ups for an interview demo only — not multi-instance production. |
| Secrets | `.env` (gitignored); `.env.example` tracked | Standard local config; never commit keys. |
| Eval cases | `evals/cases.json` in git | Versioned expectations next to the runner. |

**Why not Postgres/Redis:** out of scope for a one-day agent. Persistence is not required to demonstrate ranking, explanation, API, and evals. If this grew into a product, weather cache and sessions would move to a shared store; the risk engine and API shapes would stay.

## Explicit non-goals

Voice UI, scheduled risk-change alerts, and cloud deploy were deferred. The assignment marks them as bonuses; a narrow, reliable local demo was preferred over incomplete polish.
