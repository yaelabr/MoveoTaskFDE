from __future__ import annotations

import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("WEATHER_AGENT_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="Weather Risk Agent", page_icon="☁️", layout="centered")
st.title("Weather Risk Intelligence Agent")
st.caption("Ask about hub weather disruption risk. Scores are computed in code; Gemini only helps interpret questions and explain.")

if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("meta"):
            with st.expander("Structured details"):
                st.json(msg["meta"])

prompt = st.chat_input("e.g. Which Midwest hubs are most exposed to winter disruption?")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Scoring hubs…"):
            try:
                response = httpx.post(
                    f"{API_URL}/chat",
                    json={"message": prompt, "session_id": st.session_state.session_id},
                    timeout=120.0,
                )
                if response.status_code >= 400:
                    answer = f"API error {response.status_code}: {response.text}"
                    meta = None
                else:
                    data = response.json()
                    st.session_state.session_id = data.get("session_id")
                    answer = data.get("answer", "")
                    meta = {
                        "intent": data.get("intent"),
                        "hubs": data.get("hubs"),
                        "assumptions": data.get("assumptions"),
                        "uncertainty": data.get("uncertainty"),
                    }
            except httpx.HTTPError as exc:
                answer = f"Could not reach API at {API_URL}. Is uvicorn running?\n\n{exc}"
                meta = None

        st.markdown(answer)
        if meta:
            with st.expander("Structured details"):
                st.json(meta)

    st.session_state.messages.append({"role": "assistant", "content": answer, "meta": meta})
