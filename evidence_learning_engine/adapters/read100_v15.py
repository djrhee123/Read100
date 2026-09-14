from __future__ import annotations
from typing import Any, Dict
from ..core import evaluate_mastery, summarize_evidence_stats
from ..policies import READ100_V15_POLICY

def classify_from_stats(stats: Dict[str, Any]) -> str:
    metrics = {
        "first_total": int(stats.get("first_total") or 0),
        "first_right": int(stats.get("first_right") or 0),
        "hints": int(stats.get("hints") or 0),
        "recovered": int(stats.get("recovered") or 0),
        "transfer_total": int(stats.get("transfer_total") or 0),
        "transfer_right": int(stats.get("transfer_right") or 0),
        # Read100 v1.5 legacy classifier does not gate on completion/answer completeness.
        "completed": True,
        "answers_complete": True,
    }
    return evaluate_mastery(metrics, READ100_V15_POLICY)


def growth_block_from_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    metrics = {
        "first_total": int(stats.get("first_total") or 0),
        "first_right": int(stats.get("first_right") or 0),
        "hints": int(stats.get("hints") or 0),
        "recovered": int(stats.get("recovered") or 0),
        "transfer_total": int(stats.get("transfer_total") or 0),
        "transfer_right": int(stats.get("transfer_right") or 0),
        "completed": True,
        "answers_complete": True,
    }
    return summarize_evidence_stats(metrics, READ100_V15_POLICY)
