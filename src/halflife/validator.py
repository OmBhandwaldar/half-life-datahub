"""Decide whether a memory still deserves to be trusted.

Two independent signals feed the verdict:

* **Timeline events** — DataHub's own change history, already graded for
  compatibility. A ``MAJOR`` (backwards incompatible) change to something a
  memory depends on kills it outright; there is no sense in which a memory about
  a removed column is still true.
* **Fingerprint drift** — a dependency whose state moved with *no* timeline
  event to explain it. This is the "silent drift" case: lineage rewiring and
  unsupported entity types leave no timeline trail, so without this check a
  memory could rot invisibly.

Ownership changes never invalidate a memory — the facts are unaffected — but
they do re-route who gets told about it.
"""

from __future__ import annotations

from .client import HalfLifeClient
from .fingerprint import compare, fingerprint_all
from .models import (
    ChangeCategory,
    ChangeEvent,
    Memory,
    MemoryStatus,
    SemVerChange,
    Verdict,
)
from .timeline import TimelineClient

#: Categories where a non-breaking change still alters meaning enough to doubt
#: anything derived from it.
_SEMANTIC_CATEGORIES = (ChangeCategory.TECHNICAL_SCHEMA, ChangeCategory.GLOSSARY_TERM)


def _is_semantic(event: ChangeEvent) -> bool:
    """Does this change alter what a memory built on it would mean?

    Editing a glossary term's *definition* arrives as ``DOCUMENTATION`` rather
    than ``GLOSSARY_TERM`` — that category is reserved for terms being attached
    to or removed from entities. Redefining "Order Total" changes the meaning of
    every memory that relied on it, so it is treated as semantic even though a
    prose edit on a dataset is not.
    """
    if event.category is ChangeCategory.DOCUMENTATION:
        return event.target_urn.startswith("urn:li:glossaryTerm:")
    return event.category in _SEMANTIC_CATEGORIES and (
        event.sem_ver_change is SemVerChange.MINOR
    )

_PENALTY_MINOR_SEMANTIC = 30
_PENALTY_SILENT_DRIFT = 25
_PENALTY_DOCUMENTATION = 5


class Validator:
    def __init__(self, client: HalfLifeClient, timeline: TimelineClient | None = None) -> None:
        self._client = client
        self._timeline = timeline or TimelineClient(client.config)

    def validate(self, memory: Memory, now: int) -> Verdict:
        if memory.status is MemoryStatus.EXPIRED:
            # Terminal: an expired memory is not resurrected by later quiet.
            return Verdict(
                memory=memory,
                previous_status=MemoryStatus.EXPIRED,
                new_status=MemoryStatus.EXPIRED,
                integrity_score=memory.integrity_score,
                reason=memory.invalidation_reason or "Previously expired.",
            )

        since = memory.last_validated_at or memory.recorded_at
        events: list[ChangeEvent] = []
        urns_with_events: set[str] = set()

        for dependency in memory.dependencies:
            found = self._timeline.changes(dependency, start=since, end=now)
            if found:
                urns_with_events.add(dependency)
                events.extend(found)

        current = fingerprint_all(self._client.snapshots(memory.dependencies))
        drifted = compare(memory.fingerprints, current)
        silent_drift = [urn for urn in drifted if urn not in urns_with_events]

        status, score, reason = _judge(events, silent_drift)
        reroute = self._reroute_targets(events)

        return Verdict(
            memory=memory,
            previous_status=memory.status,
            new_status=status,
            events=events,
            silent_drift=silent_drift,
            reroute_owners=reroute,
            integrity_score=score,
            reason=reason,
        )

    def _reroute_targets(self, events: list[ChangeEvent]) -> list[str]:
        """Current owners of any dependency whose ownership changed."""
        changed = {e.target_urn for e in events if e.category is ChangeCategory.OWNERSHIP}
        owners: set[str] = set()
        for urn in changed:
            owners.update(self._client.owners_of(urn))
        return sorted(owners)


def _judge(
    events: list[ChangeEvent], silent_drift: list[str]
) -> tuple[MemoryStatus, int, str]:
    """Pure severity mapping — kept separate so it can be tested without a live server."""
    breaking = [e for e in events if e.is_breaking]
    if breaking:
        return MemoryStatus.EXPIRED, 0, _summarise_breaking(breaking)

    score = 100
    reasons: list[str] = []

    semantic = [e for e in events if _is_semantic(e)]
    for event in semantic:
        score -= _PENALTY_MINOR_SEMANTIC
        reasons.append(_describe(event))

    for urn in silent_drift:
        score -= _PENALTY_SILENT_DRIFT
        reasons.append(f"Silent drift: {_short(urn)} changed with no timeline event.")

    cosmetic = [
        e
        for e in events
        if e.category is ChangeCategory.DOCUMENTATION and not _is_semantic(e)
    ]
    for event in cosmetic:
        score -= _PENALTY_DOCUMENTATION
        reasons.append(_describe(event))

    score = max(0, min(100, score))

    if semantic or silent_drift:
        return MemoryStatus.SUSPECT, score, " ".join(reasons)

    ownership = [e for e in events if e.category is ChangeCategory.OWNERSHIP]
    if ownership:
        reasons.append("Ownership changed; escalation re-routed.")

    return MemoryStatus.VALID, score, " ".join(reasons) or "No relevant changes."


def _summarise_breaking(events: list[ChangeEvent]) -> str:
    first = events[0]
    extra = f" (+{len(events) - 1} more)" if len(events) > 1 else ""
    return f"Breaking change: {_describe(first)}{extra}"


def _describe(event: ChangeEvent) -> str:
    element = f" [{event.element_id}]" if event.element_id else ""
    detail = event.description or f"{event.change_type} on {_short(event.target_urn)}"
    return f"{event.category.value}{element}: {detail}"


def _short(urn: str) -> str:
    """Last meaningful segment of a URN, for readable one-line reasons."""
    if "," in urn:
        parts = urn.split(",")
        if len(parts) >= 2:
            return parts[-2].strip()
    return urn.rsplit(":", 1)[-1]
