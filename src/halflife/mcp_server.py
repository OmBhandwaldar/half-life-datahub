"""MCP server exposing memory as a tool.

Run alongside DataHub's own MCP server: DataHub answers "what is true about the
catalog right now", Half-Life answers "what have we learned before, and is it
still true". The second question is the one nothing else answers.

    halflife-mcp            # stdio, for Claude Code / Cursor
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .actions import Actuator
from .client import HalfLifeClient
from .models import MemoryStatus
from .recall import Recall
from .store import MemoryStore, now_ms, slugify
from .validator import Validator

mcp = FastMCP(
    "half-life",
    instructions=(
        "Durable memory for data agents, stored in DataHub and automatically "
        "expired when the metadata it was derived from changes.\n\n"
        "Call `recall` BEFORE investigating a data question — someone may have "
        "already worked it out. Call `record_memory` AFTER reaching a "
        "non-obvious conclusion, listing every dataset, column or glossary term "
        "you relied on, so the memory can be invalidated when they change.\n\n"
        "Expired memories are never returned. If `recall` reports that it "
        "withheld something, re-derive the answer from the catalog instead of "
        "asking for it again."
    ),
)


def _parts():
    client = HalfLifeClient()
    store = MemoryStore(client)
    return client, store


@mcp.tool()
def recall(query: str, limit: int = 5) -> dict:
    """Retrieve previously learned facts that are still trustworthy.

    Expired memories are never returned. Suspect memories come back with a
    warning describing what changed beneath them.
    """
    _, store = _parts()
    engine = Recall(store)

    results = engine.search(query, limit=limit)
    withheld = engine.excluded(query)

    return {
        "memories": [
            {
                "urn": r.memory.urn,
                "title": r.memory.title,
                "text": r.memory.text,
                "status": r.memory.status.value,
                "integrity_score": r.memory.integrity_score,
                "dependencies": r.memory.dependencies,
                "warning": r.warning,
            }
            for r in results
        ],
        "withheld_expired": [
            {
                "title": m.title,
                "reason": m.invalidation_reason,
                "guidance": "Re-derive this from the catalog; do not trust it.",
            }
            for m in withheld
        ],
    }


@mcp.tool()
def record_memory(
    title: str,
    text: str,
    dependencies: list[str],
    memory_id: str | None = None,
) -> dict:
    """Store a conclusion so future agents inherit it.

    `dependencies` must list every DataHub URN the conclusion rests on —
    datasets, schema fields or glossary terms. They are what allow the memory
    to be invalidated later, so a memory recorded without them cannot be
    protected.
    """
    if not dependencies:
        return {
            "error": (
                "dependencies must not be empty: a memory with no recorded "
                "provenance can never be invalidated, which is worse than no "
                "memory at all."
            )
        }

    _, store = _parts()
    memory = store.record(
        memory_id=memory_id or slugify(title),
        title=title,
        text=text,
        dependencies=dependencies,
    )
    return {
        "urn": memory.urn,
        "status": memory.status.value,
        "dependencies_fingerprinted": len(memory.fingerprints),
    }


@mcp.tool()
def validate_memories(urns: list[str] | None = None, apply: bool = True) -> dict:
    """Re-check memories against the current state of their dependencies.

    Returns every state transition. With `apply`, verdicts are written back to
    DataHub: expired memories are unpublished so they can no longer be recalled.
    """
    client, store = _parts()
    validator = Validator(client)
    actuator = Actuator(client)

    memories = [store.load(u) for u in urns] if urns else store.list_memories()
    memories = [m for m in memories if m is not None]

    transitions = []
    for memory in memories:
        verdict = validator.validate(memory, now=now_ms())
        actions = actuator.apply(verdict) if apply else []
        if verdict.changed:
            transitions.append(
                {
                    "urn": memory.urn,
                    "title": memory.title,
                    "from": verdict.previous_status.value,
                    "to": verdict.new_status.value,
                    "integrity_score": verdict.integrity_score,
                    "reason": verdict.reason,
                    "escalate_to": verdict.reroute_owners,
                    "actions": actions,
                }
            )

    return {
        "checked": len(memories),
        "changed": len(transitions),
        "transitions": transitions,
    }


@mcp.tool()
def explain_memory(urn: str) -> dict:
    """Show a memory's provenance and why it holds its current status."""
    client, store = _parts()
    memory = store.load(urn)
    if memory is None:
        return {"error": f"No memory found at {urn}"}

    verdict = Validator(client).validate(memory, now=now_ms())

    return {
        "urn": memory.urn,
        "title": memory.title,
        "status": memory.status.value,
        "integrity_score": memory.integrity_score,
        "recorded_at": memory.recorded_at,
        "last_validated_at": memory.last_validated_at,
        "invalidation_reason": memory.invalidation_reason,
        "dependencies": [
            {"urn": urn_, "fingerprint_at_record": memory.fingerprints.get(urn_)}
            for urn_ in memory.dependencies
        ],
        # Changes since the last check, not since recording: the watermark
        # advances once a verdict is applied, so this is empty for a memory
        # whose verdict has already been written. `invalidation_reason` is the
        # durable record of why it holds its current status.
        "changes_since_last_validation": [
            {
                "category": e.category.value,
                "severity": e.sem_ver_change.value,
                "element": e.element_id,
                "description": e.description,
            }
            for e in verdict.events
        ],
        "silent_drift": verdict.silent_drift,
        "would_become": verdict.new_status.value,
    }


@mcp.tool()
def memory_ledger() -> dict:
    """Every memory with its current integrity status."""
    _, store = _parts()
    memories = store.list_memories()

    return {
        "total": len(memories),
        "by_status": {
            status.value: sum(1 for m in memories if m.status is status)
            for status in MemoryStatus
        },
        "memories": [
            {
                "urn": m.urn,
                "title": m.title,
                "status": m.status.value,
                "integrity_score": m.integrity_score,
                "dependencies": len(m.dependencies),
                "reason": m.invalidation_reason,
            }
            for m in memories
        ],
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
