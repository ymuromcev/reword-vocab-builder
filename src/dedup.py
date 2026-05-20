"""Deduplicate a word list against a Reword backup index.

Implements RFC-006 / BL-06. Pure function: no I/O, no logging.
The caller (CLI) prints from the returned `DedupReport`.

Routing rules (per RFC-006):

- empty / whitespace word    -> skip, reason "empty-word"
- key not in backup_index    -> keep, reason "new"
- status "mastered"          -> skip, reason "mastered"
- status "active-long"       -> skip, reason "active-long"
- any other status           -> keep, reason == status
- duplicate key within input -> first kept, rest skipped "in-list-duplicate"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from src.backup_reader import ClassifiedWord, normalize_key

SKIP_STATUSES = frozenset({"mastered", "active-long"})

REASON_ORDER = (
    "new",
    "passive",
    "passive-long",
    "passive-mastered",
    "seen-only",
    "active",
    "mastered",
    "active-long",
    "in-list-duplicate",
    "empty-word",
)


@dataclass(frozen=True)
class DedupReport:
    kept: int
    skipped: int
    reasons: dict[str, int] = field(default_factory=dict)
    decisions: list[tuple[str, str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        header = f"Dedup: {self.kept} kept / {self.skipped} skipped"
        kept_reasons = [
            r for r in REASON_ORDER
            if r in self.reasons and _is_keep_reason(r)
        ]
        skip_reasons = [
            r for r in REASON_ORDER
            if r in self.reasons and not _is_keep_reason(r)
        ]
        label_width = max(
            (len(r) + 1 for r in kept_reasons + skip_reasons),
            default=0,
        )

        lines = [header]
        for r in kept_reasons:
            lines.append(f"  {(r + ':').ljust(label_width)} {self.reasons[r]}")
        if kept_reasons and skip_reasons:
            lines.append("  " + "─" * label_width)
        for r in skip_reasons:
            lines.append(f"  {(r + ':').ljust(label_width)} {self.reasons[r]}")
        return "\n".join(lines)


def _is_keep_reason(reason: str) -> bool:
    return reason in {
        "new",
        "passive",
        "passive-long",
        "passive-mastered",
        "seen-only",
        "active",
    }


def dedup(
    words: Iterable[dict],
    backup_index: dict[str, ClassifiedWord],
) -> tuple[list[dict], DedupReport]:
    """Filter `words` against `backup_index`, return (kept, report)."""
    kept: list[dict] = []
    reasons: dict[str, int] = {}
    decisions: list[tuple[str, str, str]] = []
    seen_keys: set[str] = set()

    for item in words:
        raw = item.get("word", "")
        key = normalize_key(raw)

        if not key:
            decision, reason = "skipped", "empty-word"
        elif key in seen_keys:
            decision, reason = "skipped", "in-list-duplicate"
        else:
            entry = backup_index.get(key)
            if entry is None:
                decision, reason = "kept", "new"
            elif entry.status in SKIP_STATUSES:
                decision, reason = "skipped", entry.status
            else:
                decision, reason = "kept", entry.status

        decisions.append((raw, decision, reason))
        reasons[reason] = reasons.get(reason, 0) + 1
        if decision == "kept":
            seen_keys.add(key)
            kept.append(item)

    report = DedupReport(
        kept=len(kept),
        skipped=len(decisions) - len(kept),
        reasons=reasons,
        decisions=decisions,
    )
    return kept, report


def dedup_only(
    words: Iterable[dict],
    backup_index: dict[str, ClassifiedWord],
) -> list[dict]:
    """Convenience wrapper that drops the report."""
    return dedup(words, backup_index)[0]
