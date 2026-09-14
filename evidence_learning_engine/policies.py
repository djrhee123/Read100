from dataclasses import dataclass

@dataclass(frozen=True)
class MasteryPolicy:
    name: str
    min_first_evidence: int = 2
    require_completed: bool = False
    require_answers_complete: bool = False
    low_evidence_state: str = "needs_relearning"
    fragile_first_rate: float = 0.65
    fragile_transfer_below: float = 0.50
    independent_first_rate: float = 0.75
    independent_transfer_min: float = 0.67
    supported_transfer_min: float = 0.50
    max_hint_ratio: float = 0.20
    independent_requires_no_recovery: bool = False

NATURE100_V28_POLICY = MasteryPolicy(
    name="nature100-v2.8",
    require_completed=True,
    require_answers_complete=True,
    low_evidence_state="needs_relearning",
    independent_transfer_min=1.0,  # Nature transfer is a single boolean item.
    supported_transfer_min=1.0,
    independent_requires_no_recovery=True,
)

READ100_V15_POLICY = MasteryPolicy(
    name="read100-v1.5",
    require_completed=False,
    require_answers_complete=False,
    low_evidence_state="insufficient_evidence",
    independent_transfer_min=0.67,
    supported_transfer_min=0.50,
)
