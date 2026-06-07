"""Детерміністична оцінка верифікації (без LLM).

detect_conflict: перевіряє, чи кейси з однаковим ключем звітують суттєво
  різні суми (відносне відхилення > tol від максимуму).
assess_verification: повертає base verification_status для одного кейсу.
"""

from __future__ import annotations

from .schema import Case


def detect_conflict(cases_same_key: list[Case], *, tol: float = 0.10) -> bool:
    """True if any two non-None amounts differ by more than tol relative.

    Relative difference = |a - b| / max(|a|, |b|).
    None amounts are ignored.
    """
    amounts = [c.amount_uah for c in cases_same_key if c.amount_uah is not None]
    if len(amounts) < 2:
        return False
    max_val = max(abs(a) for a in amounts)
    if max_val == 0:
        return False
    min_val = min(abs(a) for a in amounts)
    return (max_val - min_val) / max_val > tol


def assess_verification(case: Case, *, conflicting: bool = False) -> str:
    """Returns verification_status string for a single case.

    Rules (in priority order):
    1. conflicting=True → "conflict"
    2. Any provenance entry with tier == 1 → "cross-checked"
    3. Otherwise → "auto"
    """
    if conflicting:
        return "conflict"
    for entry in case.provenance.values():
        if isinstance(entry, dict) and entry.get("tier") == 1:
            return "cross-checked"
    return "auto"
