from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
HUBS_PATH = ROOT / "data" / "hubs.json"


class Hub(BaseModel):
    id: str
    name: str
    city: str
    state: str
    region: str
    lat: float
    lon: float


@lru_cache(maxsize=1)
def load_hubs() -> list[Hub]:
    raw = json.loads(HUBS_PATH.read_text(encoding="utf-8"))
    return [Hub.model_validate(item) for item in raw]


def all_hubs() -> list[Hub]:
    return list(load_hubs())


def get_hub(hub_id: str) -> Hub | None:
    needle = hub_id.strip().lower()
    for hub in load_hubs():
        if hub.id == needle:
            return hub
    return None


def hubs_by_region(region: str) -> list[Hub]:
    needle = region.strip().lower()
    return [h for h in load_hubs() if h.region.lower() == needle]


def resolve_hub(query: str) -> Hub | None:
    q = query.strip().lower()
    for hub in load_hubs():
        if hub.id == q or hub.city.lower() == q or q in hub.name.lower():
            return hub
    return None


def resolve_hubs(queries: list[str]) -> list[Hub]:
    found: list[Hub] = []
    seen: set[str] = set()
    for q in queries:
        hub = resolve_hub(q) or get_hub(q)
        if hub and hub.id not in seen:
            found.append(hub)
            seen.add(hub.id)
    return found


def hubs_mentioned_in_text(text: str) -> list[Hub]:
    """Find curated hubs named in free text (city / id / short name)."""
    lowered = text.lower()
    found: list[Hub] = []
    for hub in load_hubs():
        if (
            hub.city.lower() in lowered
            or f" {hub.id} " in f" {lowered} "
            or hub.id == lowered.strip()
        ):
            found.append(hub)
    return found
