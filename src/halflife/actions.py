"""Apply a verdict back to the catalog.

This is the half of Half-Life that matters most: a verdict nobody can see is
worth nothing. Expiring a memory unpublishes it, so the next agent that calls
recall simply cannot inherit a fact that is no longer true — the protection is
structural rather than advisory.
"""

from __future__ import annotations

from datahub.sdk.document import Document

from .client import HalfLifeClient
from .config import SUBTYPE_AUDIT, property_urn
from .models import ChangeCategory, MemoryStatus, Verdict
from .store import MemoryStore, now_ms, truncate

TAG_EXPIRED = "urn:li:tag:halflife-expired"
TAG_SUSPECT = "urn:li:tag:halflife-suspect"


class Actuator:
    def __init__(self, client: HalfLifeClient) -> None:
        self._client = client
        self._store = MemoryStore(client)

    def apply(self, verdict: Verdict, write_audit: bool = True) -> list[str]:
        """Persist a verdict. Returns a list of the actions actually taken."""
        if not verdict.changed and not verdict.reroute_owners:
            return []

        actions: list[str] = []
        memory = verdict.memory
        document = self._client.get_document(memory.urn)
        if document is None:
            return []

        timestamp = now_ms()
        document.set_structured_property(
            property_urn("status"), [verdict.new_status.value]
        )
        document.set_structured_property(
            property_urn("integrity_score"), [verdict.integrity_score]
        )
        document.set_structured_property(
            property_urn("last_validated_at"), [timestamp]
        )
        if verdict.reason:
            document.set_structured_property(
                property_urn("invalidation_reason"), [truncate(verdict.reason)]
            )

        if verdict.changed:
            actions.append(
                f"status {verdict.previous_status.value} -> {verdict.new_status.value}"
            )

        if verdict.new_status is MemoryStatus.EXPIRED:
            # Quarantine: unpublished documents are excluded from recall.
            document.unpublish()
            document.add_tag(TAG_EXPIRED)
            actions.append("unpublished")
        elif verdict.new_status is MemoryStatus.SUSPECT:
            document.add_tag(TAG_SUSPECT)

        # Re-route escalation to whoever owns the changed dependency *now*,
        # which is the whole point: the original owner may have left.
        for owner in verdict.reroute_owners:
            document.add_owner(owner)
        if verdict.reroute_owners:
            actions.append(f"re-routed to {len(verdict.reroute_owners)} owner(s)")

        self._client.upsert(document)

        if write_audit and verdict.changed:
            audit_urn = self.write_audit(verdict, timestamp)
            if audit_urn:
                actions.append("audit document written")

        return actions

    def write_audit(self, verdict: Verdict, timestamp: int) -> str | None:
        """Record why a memory changed state, linked to both sides of the story."""
        memory = verdict.memory
        related = [memory.urn] + [e.target_urn for e in verdict.events]

        audit = Document.create_document(
            id=f"{memory.id}-audit-{timestamp}",
            title=f"Memory {verdict.new_status.value}: {memory.title}",
            text=_audit_body(verdict, timestamp),
            subtype=SUBTYPE_AUDIT,
            related_assets=list(dict.fromkeys(related)) or None,
            show_in_global_context=False,
        )
        try:
            self._client.upsert(audit)
        except Exception:
            return None
        return str(audit.urn)


def _audit_body(verdict: Verdict, timestamp: int) -> str:
    memory = verdict.memory
    lines = [
        f"# {verdict.previous_status.value} → {verdict.new_status.value}",
        "",
        f"**Memory:** {memory.title}",
        f"**Integrity score:** {verdict.integrity_score}/100",
        f"**Checked:** {timestamp}",
        "",
        "## Why",
        "",
        verdict.reason or "No reason recorded.",
        "",
    ]

    if verdict.events:
        lines += ["## Change events", ""]
        for event in verdict.events:
            element = f" `{event.element_id}`" if event.element_id else ""
            lines.append(
                f"- **{event.category.value}**{element} "
                f"({event.sem_ver_change.value}) — {event.description or event.change_type}"
            )
            lines.append(f"  - target: `{event.target_urn}`")
        lines.append("")

    if verdict.silent_drift:
        lines += [
            "## Silent drift",
            "",
            "These dependencies changed with no corresponding timeline event:",
            "",
        ]
        lines += [f"- `{urn}`" for urn in verdict.silent_drift]
        lines.append("")

    if verdict.reroute_owners:
        lines += ["## Escalation re-routed to", ""]
        lines += [f"- `{owner}`" for owner in verdict.reroute_owners]
        lines.append("")

    ownership_changed = any(
        e.category is ChangeCategory.OWNERSHIP for e in verdict.events
    )
    if ownership_changed:
        lines.append(
            "_Ownership of a dependency changed; notifications now go to the "
            "current owner rather than whoever recorded this memory._"
        )

    lines += ["", "---", "", "Generated by Half-Life."]
    return "\n".join(lines)
