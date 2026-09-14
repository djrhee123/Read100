from __future__ import annotations
from typing import Any, Dict, Iterable
from .policies import MasteryPolicy

CANONICAL_MASTERY_STATES = (
    "independent_mastery",
    "supported_mastery",
    "fragile_understanding",
    "needs_relearning",
)

UNDERSTOOD_STATES = {
    "independent_mastery",
    "supported_mastery",
    "fragile_understanding",
}

def _rate(right: int, total: int):
    return (right / total) if total else None

def evaluate_mastery(metrics: Dict[str, Any], policy: MasteryPolicy) -> str:
    """Deterministic mastery classification from normalized evidence metrics.

    Product adapters normalize their current storage/session representation to this
    metric contract. Policy differences are explicit so commonization does not
    silently change a product's legacy decisions.
    """
    ft = int(metrics.get("first_total") or 0)
    fr_count = int(metrics.get("first_right") or 0)
    tt = int(metrics.get("transfer_total") or 0)
    tr_count = int(metrics.get("transfer_right") or 0)
    hints = int(metrics.get("hints") or 0)
    recovered = int(metrics.get("recovered") or 0)
    completed = bool(metrics.get("completed", False))
    answers_complete = bool(metrics.get("answers_complete", False))

    if ft < policy.min_first_evidence:
        return policy.low_evidence_state
    if policy.require_completed and not completed:
        return policy.low_evidence_state
    if policy.require_answers_complete and not answers_complete:
        return policy.low_evidence_state

    first_rate = _rate(fr_count, ft) or 0.0
    transfer_rate = _rate(tr_count, tt)

    if tt and transfer_rate is not None and transfer_rate < policy.fragile_transfer_below and first_rate >= policy.fragile_first_rate:
        return "fragile_understanding"

    max_hints = max(1, round(ft * policy.max_hint_ratio))
    transfer_ok_for_independent = (not tt) or (transfer_rate is not None and transfer_rate >= policy.independent_transfer_min)
    recovery_ok_for_independent = (not policy.independent_requires_no_recovery) or recovered == 0
    if first_rate >= policy.independent_first_rate and transfer_ok_for_independent and hints <= max_hints and recovery_ok_for_independent:
        return "independent_mastery"

    transfer_ok_for_supported = (not tt) or (transfer_rate is not None and transfer_rate >= policy.supported_transfer_min)
    if recovered > 0 and transfer_ok_for_supported:
        return "supported_mastery"

    return "needs_relearning"

def compare_human_engine(human: str, engine: str) -> Dict[str, Any]:
    """Superset comparison contract used by Blind Human Validation."""
    return {
        "exactAgreement": human == engine,
        "falsePositive": engine == "independent_mastery" and human in {"fragile_understanding", "needs_relearning"},
        "falseNegative": engine in {"fragile_understanding", "needs_relearning"} and human in {"independent_mastery", "supported_mastery"},
        "binaryAgreement": (human in UNDERSTOOD_STATES) == (engine in UNDERSTOOD_STATES),
        "humanState": human,
        "engineState": engine,
    }

def aggregate_nature_growth(rows: Iterable[Dict[str, Any]], start_day: int, end_day: int) -> Dict[str, Any]:
    """Nature100 v2.8 four-day Growth Proof calculation, pure and deterministic."""
    rows = [dict(r) for r in rows]
    complete = [r for r in rows if bool(r.get("evidence_complete"))]
    days_required = end_day - start_day + 1
    vals = [int(r["first_right_rate"]) for r in complete if r.get("first_right_rate") is not None]
    transfers = [int(r["transfer_success"]) for r in complete if r.get("transfer_success") is not None]
    states = {st: sum(1 for r in complete if r.get("state") == st) for st in CANONICAL_MASTERY_STATES}
    metrics = {
        "daysRequired": days_required,
        "daysComplete": len(complete),
        "firstRightRate": round(sum(vals) / len(vals)) if vals else None,
        "hintCount": sum(int(r.get("hint_count") or 0) for r in complete),
        "recoveredCount": sum(int(r.get("recovered_count") or 0) for r in complete),
        "transferRate": round(100 * sum(1 for x in transfers if x) / len(transfers)) if transfers else None,
        "states": states,
    }
    return {"status": "PROVED" if len(complete) == days_required else "COLLECTING", "metrics": metrics}

def summarize_evidence_stats(metrics: Dict[str, Any], policy: MasteryPolicy) -> Dict[str, Any]:
    """Generic checkpoint summary over already-aggregated evidence counts."""
    ft=int(metrics.get("first_total") or 0); tt=int(metrics.get("transfer_total") or 0)
    first_rate=round(int(metrics.get("first_right") or 0)/ft*100) if ft else None
    transfer_rate=round(int(metrics.get("transfer_right") or 0)/tt*100) if tt else None
    hint_dependency=round(int(metrics.get("hints") or 0)/ft*100) if ft else None
    return {
        "mastery_state": evaluate_mastery(metrics, policy),
        "first_rate": first_rate,
        "transfer_rate": transfer_rate,
        "hint_dependency": hint_dependency,
    }
