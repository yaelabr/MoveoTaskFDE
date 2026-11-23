# Weather Risk Intelligence Agent

Junior FDE take-home: rank/compare a small set of US logistics hubs by weather disruption risk. **Scores are computed in Python**; Gemini only parses questions and explains the numbers.

## Architecture (short)

```
Streamlit UI  →  FastAPI (/chat, /hubs, /health)
                    ├── Gemini (structured intent JSON + narration)
                    ├── risk.py (deterministic 0–100 KPI)
                    └── Open-Meteo archive (last ~365 days)
                           ↑
                      data/hubs.json
```

**Risk KPI:** weighted blend of `winter` (40%), `flood` (35%), `wind` (25%). Gulf hubs get a fixed coastal bump on flood as a transparent hurricane/flood *proxy* — not a catastrophe model.

## Setup

```bash
cd moveo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set GEMINI_API_KEY (see below)
```

## Run

Terminal 1 — API:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Terminal 2 — chat UI:

```bash
source .venv/bin/activate
streamlit run ui/chat.py
```

Useful without the LLM:

- `GET http://127.0.0.1:8000/hubs`
- `GET http://127.0.0.1:8000/hubs/dal/risk`
- `GET http://127.0.0.1:8000/risk/ranking`

## Eval

Does **not** need a Gemini key (uses Open-Meteo + risk engine):

```bash
source .venv/bin/activate
python evals/run_eval.py
```

## Assumptions & uncertainty

- Fixed curated hub list (~8), not a full real network
- “Last year” = last 365 days of Open-Meteo archive (with a few days lag)
- Scores are relative decision aids, not absolute loss estimates
- Gulf hurricane/flood signal = heavy precip + coastal bump
- LLM must not invent scores; code owns the KPI

## Gemini API key

1. Open [Google AI Studio](https://aistudio.google.com/apikey) and create a free API key  
2. Put it in `.env` as `GEMINI_API_KEY=...`  
3. Keep `GEMINI_MODEL=gemini-3.5-flash-lite` (free-tier friendly). Older ids like `gemini-2.0-flash` 404 for new keys; heavier flash models often hit free-tier quota (429).
4. Restart uvicorn  

Chat (`/chat` and Streamlit) needs the key. Hub listing and deterministic risk endpoints do not.

The agent tries lite/fallback Gemini models automatically. Only if all fail does it use heuristic intent + template explanation.
