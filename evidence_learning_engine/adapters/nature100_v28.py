from __future__ import annotations
from typing import Any, Dict, Iterable
from ..core import evaluate_mastery, aggregate_nature_growth
from ..policies import NATURE100_V28_POLICY

TASKS = ("observe", "why", "predict", "transfer")

def normalize_session(session: Dict[str, Any]) -> Dict[str, Any]:
    first_total = first_right = hints = recovered = 0
    stats = session.get("taskStats") or {}
    answers = session.get("answers") or {}
    for task in TASKS:
        st = stats.get(task) or {}
        if int(st.get("attempts") or 0) > 0:
            first_total += 1
            if st.get("firstCorrect") is True:
                first_right += 1
            hints += int(st.get("hints") or 0)
            if st.get("firstCorrect") is False and st.get("resolvedAt"):
                recovered += 1

    transfer = answers.get("transfer") or {}
    transfer_success = transfer.get("correct") if isinstance(transfer, dict) and isinstance(transfer.get("correct"), bool) else None
    answers_complete = all(bool(answers.get(k)) for k in TASKS)
    return {
        "first_total": first_total,
        "first_right": first_right,
        "hints": hints,
        "recovered": recovered,
        "transfer_total": 1 if transfer_success is not None else 0,
        "transfer_right": 1 if transfer_success is True else 0,
        "completed": bool(session.get("completed")),
        "answers_complete": answers_complete,
        "transfer_success": transfer_success,
    }

def mastery_from_session(session: Dict[str, Any]) -> Dict[str, Any]:
    m = normalize_session(session)
    state = evaluate_mastery(m, NATURE100_V28_POLICY)
    rate = None if not m["first_total"] else round(100 * m["first_right"] / m["first_total"])
    return {
        "state": state,
        "firstTotal": m["first_total"],
        "firstRight": m["first_right"],
        "firstRightRate": rate,
        "hints": m["hints"],
        "recovered": m["recovered"],
        "transferSuccess": m["transfer_success"],
        "evidenceComplete": bool(m["completed"] and m["answers_complete"]),
    }

def growth_from_rows(rows: Iterable[Dict[str, Any]], start_day: int, end_day: int):
    return aggregate_nature_growth(rows, start_day, end_day)
