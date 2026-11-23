# Weather Risk Intelligence Agent

Take-home for a logistics weather-risk use case: help analysts decide which US distribution hubs are most exposed to weather disruption.

**Design rule:** risk scores and rankings are computed in Python. Gemini only interprets the question (structured JSON) and explains the numbers. The model is not allowed to invent scores.

**Repo:** https://github.com/yaelabr/MoveoTaskFDE

## Architecture

```
Streamlit chat  →  FastAPI (/chat, /hubs, /health, /risk/*)
                      ├── Gemini (structured intent + narration)
                      ├── risk.py (deterministic 0–100 KPI)
                      └── Open-Meteo archive (~last 365 days)
                             ↑
                        data/hubs.json  (10 curated hubs)
```

**KPI weights:** winter 40% · flood/heavy precip 35% · wind 25%.  
Gulf hubs get a small, documented coastal bump on flood as a **hurricane/flood proxy** (not a catastrophe model).

## Prerequisites

- Python **3.10+**
- Free [Google AI Studio](https://aistudio.google.com/apikey) API key (chat only; ranking/evals work without it)

## Setup

```bash
git clone https://github.com/yaelabr/MoveoTaskFDE.git
cd MoveoTaskFDE

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# set GEMINI_API_KEY=... in .env
```

Keep `GEMINI_MODEL=gemini-3.5-flash-lite` (default). Older model ids often 404 for new keys; heavier Flash models burn free-tier quota quickly.

## Run

Start the **API first**, then the UI (two terminals, venv activated in both).

**Terminal 1 — API**

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — chat UI**

```bash
source .venv/bin/activate
streamlit run ui/chat.py
```

- API: http://127.0.0.1:8000  
- UI: http://127.0.0.1:8501 (Streamlit default)  
- Health: http://127.0.0.1:8000/health  

### Try these questions

1. Which hubs in the Midwest are most exposed to winter disruption?  
2. Compare Miami and Houston in terms of hurricane and flood exposure.  
3. What percentage of days in Denver last year had snowfall?  
4. Why is the Dallas hub's weather disruption risk high?  
5. Follow-up in the same chat: What about Chicago?  

### Without the LLM

Useful for demos if Gemini quota is tight:

- `GET /hubs`
- `GET /hubs/{id}/risk` (e.g. `/hubs/dal/risk`)
- `GET /risk/ranking`

If Gemini is unavailable, `/chat` still returns deterministic scores with a heuristic/template explanation.

## Evaluation

No Gemini key required (Open-Meteo + risk engine):

```bash
source .venv/bin/activate
python evals/run_eval.py
```

## Assumptions & uncertainty

- Fixed curated hub list (10 hubs), not a full real network  
- “Last year” ≈ last 365 days of Open-Meteo archive (short lag)  
- Scores are **relative** decision aids (0–100), not absolute loss estimates  
- Gulf hurricane/flood signal = heavy precip + transparent coastal bump  
- Grid weather may differ from exact hub-site conditions  
- LLM explains; code owns the KPI  

## Project layout

```
app/           FastAPI, agent, risk, weather, hubs
ui/chat.py     Streamlit client
data/hubs.json Curated hubs
evals/         Small deterministic eval harness
```
