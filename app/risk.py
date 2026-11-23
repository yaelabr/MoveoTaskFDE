from __future__ import annotations

from dataclasses import dataclass

from app.hubs import Hub

WEIGHTS = {
    "winter": 0.40,
    "flood": 0.35,
    "wind": 0.25,
}

# Transparent coastal bump for Gulf hubs (hurricane/flood proxy — not a CAT model).
GULF_COASTAL_BUMP = 15.0


@dataclass
class WeatherFeatures:
    snow_days_pct: float
    cold_days_pct: float
    heavy_precip_days_pct: float
    high_wind_days_pct: float
    is_gulf: bool


@dataclass
class FactorBreakdown:
    name: str
    value: float
    weight: float
    contribution: float


@dataclass
class RiskResult:
    hub: Hub
    risk_score: float
    factors: list[FactorBreakdown]
    features: WeatherFeatures
    assumptions: list[str]
    uncertainty: list[str]


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_hub(hub: Hub, features: WeatherFeatures) -> RiskResult:
    winter = _clamp(0.7 * features.snow_days_pct + 0.3 * features.cold_days_pct)
    flood_raw = features.heavy_precip_days_pct + (GULF_COASTAL_BUMP if features.is_gulf else 0.0)
    flood = _clamp(flood_raw)
    wind = _clamp(features.high_wind_days_pct)

    raw = {"winter": winter, "flood": flood, "wind": wind}
    factors: list[FactorBreakdown] = []
    total = 0.0
    for name, value in raw.items():
        weight = WEIGHTS[name]
        contribution = value * weight
        total += contribution
        factors.append(
            FactorBreakdown(
                name=name,
                value=round(value, 2),
                weight=weight,
                contribution=round(contribution, 2),
            )
        )

    assumptions = [
        "Risk score is a relative 0–100 KPI for comparing this curated hub set, not an absolute loss estimate.",
        "Historical window is the last 365 days from the Open-Meteo archive.",
        "Gulf 'hurricane/flood' exposure uses heavy-precip days plus a fixed coastal bump — not a storm catalogue.",
    ]
    uncertainty = [
        "Grid weather may differ from exact hub-site conditions.",
        "Coastal bump is a transparent heuristic; it does not model surge, seasonality peaks, or infrastructure.",
    ]

    return RiskResult(
        hub=hub,
        risk_score=round(_clamp(total), 2),
        factors=factors,
        features=features,
        assumptions=assumptions,
        uncertainty=uncertainty,
    )


def rank_results(
    results: list[RiskResult],
    sort_by: str = "risk_score",
) -> list[RiskResult]:
    if sort_by == "risk_score":
        return sorted(results, key=lambda r: r.risk_score, reverse=True)

    def factor_value(result: RiskResult) -> float:
        for factor in result.factors:
            if factor.name == sort_by:
                return factor.value
        return 0.0

    return sorted(results, key=factor_value, reverse=True)
