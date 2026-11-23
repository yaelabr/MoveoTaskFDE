from __future__ import annotations

from datetime import date, timedelta

import httpx

from app.hubs import Hub
from app.risk import WeatherFeatures

OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

# Simple process-local cache: hub_id -> features
_CACHE: dict[str, WeatherFeatures] = {}


def _pct(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * count / total, 2)


def _window() -> tuple[str, str]:
    end = date.today() - timedelta(days=5)  # archive lag buffer
    start = end - timedelta(days=364)
    return start.isoformat(), end.isoformat()


def fetch_features(hub: Hub, *, client: httpx.Client | None = None, use_cache: bool = True) -> WeatherFeatures:
    if use_cache and hub.id in _CACHE:
        return _CACHE[hub.id]

    start, end = _window()
    params = {
        "latitude": hub.lat,
        "longitude": hub.lon,
        "start_date": start,
        "end_date": end,
        "daily": "precipitation_sum,snowfall_sum,temperature_2m_max,wind_speed_10m_max",
        "timezone": "UTC",
    }

    owns_client = client is None
    client = client or httpx.Client(timeout=60.0)
    last_error: Exception | None = None
    daily = None
    try:
        for attempt in range(3):
            try:
                response = client.get(OPEN_METEO_ARCHIVE, params=params)
                response.raise_for_status()
                daily = response.json()["daily"]
                break
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
        if daily is None and last_error is not None:
            raise last_error
    finally:
        if owns_client:
            client.close()

    assert daily is not None

    precip = daily.get("precipitation_sum") or []
    snowfall = daily.get("snowfall_sum") or []
    tmax = daily.get("temperature_2m_max") or []
    wind = daily.get("wind_speed_10m_max") or []
    n = min(len(precip), len(snowfall), len(tmax), len(wind))

    snow_days = sum(1 for i in range(n) if (snowfall[i] or 0) > 0)
    cold_days = sum(1 for i in range(n) if tmax[i] is not None and tmax[i] <= 0)
    heavy_precip = sum(1 for i in range(n) if (precip[i] or 0) >= 20)
    high_wind = sum(1 for i in range(n) if (wind[i] or 0) >= 50)

    features = WeatherFeatures(
        snow_days_pct=_pct(snow_days, n),
        cold_days_pct=_pct(cold_days, n),
        heavy_precip_days_pct=_pct(heavy_precip, n),
        high_wind_days_pct=_pct(high_wind, n),
        is_gulf=hub.region.lower() == "gulf",
    )
    if use_cache:
        _CACHE[hub.id] = features
    return features


def clear_cache() -> None:
    _CACHE.clear()
