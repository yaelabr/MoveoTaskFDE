#!/usr/bin/env python3
"""Small evaluation harness — no LLM required."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.hubs import get_hub, hubs_by_region, resolve_hubs  # noqa: E402
from app.risk import rank_results, score_hub  # noqa: E402
from app.weather import fetch_features  # noqa: E402


def _score_ids(hub_ids: list[str], sort_by: str = "risk_score"):
    hubs = []
    for hid in hub_ids:
        hub = get_hub(hid)
        if hub:
            hubs.append(hub)
    results = [score_hub(h, fetch_features(h)) for h in hubs]
    return rank_results(results, sort_by=sort_by)


def run_case(case: dict) -> tuple[bool, str]:
    mode = case["mode"]

    if mode == "resolve":
        found = resolve_hubs(case.get("hub_ids", []))
        if case.get("expect_empty"):
            return (len(found) == 0, f"resolved={ [h.id for h in found] }")
        return False, "unsupported resolve expectation"

    if mode == "metric":
        hub = get_hub(case["hub_id"])
        if not hub:
            return False, "hub missing"
        features = fetch_features(hub)
        lo, hi = case["expect_snow_pct_range"]
        ok = lo <= features.snow_days_pct <= hi
        return ok, f"snow_days_pct={features.snow_days_pct}"

    if mode == "deterministic":
        sort_by = case.get("sort_by", "risk_score")
        if "region" in case:
            hubs = hubs_by_region(case["region"])
            results = rank_results(
                [score_hub(h, fetch_features(h)) for h in hubs],
                sort_by=sort_by,
            )
        else:
            results = _score_ids(case.get("hub_ids", []), sort_by=sort_by)

        ids = [r.hub.id for r in results]

        if case.get("expect_empty"):
            return (len(ids) == 0, f"ids={ids}")

        if exact := case.get("expect_hub_ids_exact"):
            if set(ids) != set(exact):
                return False, f"expected exact {exact}, got {ids}"

        if subset := case.get("expect_hub_ids_subset"):
            if not set(subset).issubset(set(ids)):
                return False, f"expected subset {subset} in {ids}"

        if region := case.get("expect_top_region"):
            if not results or results[0].hub.region != region:
                top = results[0].hub.region if results else None
                return False, f"top region {top} != {region}"

        if case.get("expect_has_factors"):
            if not results or not results[0].factors:
                return False, "missing factors"
            if results[0].risk_score < 0 or results[0].risk_score > 100:
                return False, f"score out of range: {results[0].risk_score}"

        return True, f"ids={ids}"

    return False, f"unknown mode {mode}"


def main() -> int:
    cases = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))
    passed = 0
    print("Running weather-risk evals (deterministic; uses Open-Meteo)…\n")
    for case in cases:
        try:
            ok, detail = run_case(case)
        except Exception as exc:  # noqa: BLE001 — show eval failures clearly
            ok, detail = False, f"error: {exc}"
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['id']}: {case['description']}")
        print(f"       {detail}\n")
        if ok:
            passed += 1

    total = len(cases)
    print(f"{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
