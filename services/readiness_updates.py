"""Blend a student's original assessment scores with recent quiz history.

Uses the existing quiz_attempts.results_json format and requires no database
migration. Keep the project's current services/readiness.py unchanged.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def _row_to_dict(value: Any) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "keys"):
        return {key: value[key] for key in value.keys()}
    return {}


def _get_skill_results(attempt: Any) -> list[dict]:
    row = _row_to_dict(attempt)
    raw = row.get("results_json", "{}")
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, Mapping) or not isinstance(payload.get("skills"), list):
        return []
    return [dict(item) for item in payload["skills"] if isinstance(item, Mapping)]


def blend_assessment_with_quiz_scores(
    assessment_scores: Mapping[str, Any],
    quiz_attempts: Sequence[Any] | None = None,
    assessment_weight: float = 0.70,
) -> dict[str, float]:
    """Blend baseline assessment scores with up to five recent quiz attempts.

    `quiz_attempts` must be newest first and have `results_json`, matching the
    current SQLite schema. The quiz trend uses recency weights 45%, 25%, 15%,
    10%, and 5%. The trend contributes 30% to the blended skill score by
    default; the original assessment contributes 70%. Thus a single weak test
    influences readiness but does not wipe out established performance.
    """
    baseline: dict[str, float] = {}
    for skill, raw in (assessment_scores or {}).items():
        try:
            baseline[str(skill)] = max(0.0, min(100.0, float(raw)))
        except (TypeError, ValueError):
            continue

    attempts = list(quiz_attempts or [])[:5]
    recency_weights = (0.45, 0.25, 0.15, 0.10, 0.05)
    trend_values: dict[str, list[tuple[str, float, float]]] = {}

    for index, attempt in enumerate(attempts):
        weight = recency_weights[index]
        for item in _get_skill_results(attempt):
            name = str(item.get("skill", "")).strip()
            if not name:
                continue
            try:
                score = max(0.0, min(100.0, float(item.get("score"))))
            except (TypeError, ValueError):
                continue
            trend_values.setdefault(name.casefold(), []).append((name, score, weight))

    assessment_weight = max(0.0, min(1.0, float(assessment_weight)))
    quiz_weight = 1.0 - assessment_weight
    blended = dict(baseline)

    for skill, original_score in baseline.items():
        entries = trend_values.get(skill.casefold(), [])
        if not entries:
            continue
        weights_total = sum(weight for _, _, weight in entries)
        if weights_total <= 0:
            continue
        quiz_trend = sum(score * weight for _, score, weight in entries) / weights_total
        blended[skill] = round(original_score * assessment_weight + quiz_trend * quiz_weight, 1)

    # For quiz skills absent from the baseline assessment, use observed history
    # as the skill evidence, rather than silently dropping the skill.
    baseline_keys = {name.casefold() for name in baseline}
    for skill_key, entries in trend_values.items():
        if skill_key in baseline_keys:
            continue
        weights_total = sum(weight for _, _, weight in entries)
        if weights_total <= 0:
            continue
        trend = sum(score * weight for _, score, weight in entries) / weights_total
        blended[entries[0][0]] = round(trend, 1)

    return blended
