"""Persistence: memories are DataHub Documents, nothing more.

Half-Life deliberately keeps no database of its own. If the memory lives in the
catalog, then every agent and every human already has access to it through
tools they use anyway, and the integrity verdict travels with it.
"""

from __future__ import annotations

import time

from datahub.sdk.document import Document

from .client import HalfLifeClient
from .config import MAX_PROPERTY_BYTES, SUBTYPE_MEMORY, property_urn
from .fingerprint import decode, encode, fingerprint_all
from .models import Memory, MemoryStatus


def now_ms() -> int:
    return int(time.time() * 1000)


def truncate(text: str, limit: int = MAX_PROPERTY_BYTES) -> str:
    """Clamp a string to the Elasticsearch keyword ceiling, on a byte boundary."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[: limit - 1].decode("utf-8", errors="ignore") + "…"


class MemoryStore:
    def __init__(self, client: HalfLifeClient) -> None:
        self._client = client

    # ---- write -------------------------------------------------------------

    def record(
        self,
        memory_id: str,
        title: str,
        text: str,
        dependencies: list[str],
    ) -> Memory:
        """Capture a memory together with the state of everything it relies on."""
        timestamp = now_ms()
        fingerprints = fingerprint_all(self._client.snapshots(dependencies))

        document = Document.create_document(
            id=memory_id,
            title=title,
            text=text,
            subtype=SUBTYPE_MEMORY,
            related_assets=dependencies or None,
            # Memories are agent context, not human documentation, so they stay
            # out of global search until someone asks for them by relationship.
            show_in_global_context=False,
            structured_properties={
                property_urn("status"): [MemoryStatus.VALID.value],
                property_urn("dependencies"): list(dependencies),
                property_urn("fingerprint"): [truncate(encode(fingerprints))],
                property_urn("recorded_at"): [timestamp],
                property_urn("last_validated_at"): [timestamp],
                property_urn("integrity_score"): [100],
            },
        )
        self._client.upsert(document)

        return Memory(
            urn=str(document.urn),
            id=memory_id,
            title=title,
            text=text,
            dependencies=list(dependencies),
            fingerprints=fingerprints,
            status=MemoryStatus.VALID,
            recorded_at=timestamp,
            last_validated_at=timestamp,
            integrity_score=100,
        )

    # ---- read --------------------------------------------------------------

    def load(self, urn: str) -> Memory | None:
        document = self._client.get_document(urn)
        return self._to_memory(document) if document else None

    def list_memories(self) -> list[Memory]:
        """Every agent memory in the catalog, newest first."""
        memories = []
        for urn in self._memory_urns():
            memory = self.load(urn)
            if memory is not None:
                memories.append(memory)
        memories.sort(key=lambda m: m.recorded_at, reverse=True)
        return memories

    def _memory_urns(self) -> list[str]:
        """Find memory documents by subtype.

        This reads the entity store through the OpenAPI scroll endpoint rather
        than the search index. Search lags writes by up to 15 minutes, which
        would make a memory an agent just recorded invisible to the very next
        validation or recall — the two operations most likely to follow it.
        """
        urns: list[str] = []
        scroll_id: str | None = None

        while True:
            params = {"count": 200}
            if scroll_id:
                params["scrollId"] = scroll_id
            try:
                response = self._client.get_json("/openapi/v3/entity/document", params)
            except Exception:
                break

            entities = response.get("entities") or []
            for entity in entities:
                subtypes = _aspect(entity, "subTypes").get("typeNames") or []
                if SUBTYPE_MEMORY in subtypes and entity.get("urn"):
                    urns.append(entity["urn"])

            scroll_id = response.get("scrollId")
            if not scroll_id or not entities:
                break

        return urns

    def _to_memory(self, document: Document) -> Memory:
        props = _structured_values(document)

        return Memory(
            urn=str(document.urn),
            id=str(document.id),
            title=document.title or "",
            text=document.text or "",
            dependencies=[str(v) for v in props.get("dependencies", [])],
            fingerprints=decode(_first(props.get("fingerprint"))),
            status=_status(_first(props.get("status"))),
            recorded_at=_int(_first(props.get("recorded_at"))),
            last_validated_at=_int(_first(props.get("last_validated_at"))),
            invalidation_reason=_first(props.get("invalidation_reason")),
            integrity_score=_int(_first(props.get("integrity_score")), default=100),
        )


def _structured_values(document: Document) -> dict[str, list]:
    """Map Half-Life property short names to their values on a document."""
    values: dict[str, list] = {}
    raw = document.structured_properties or []

    for assignment in raw:
        urn = str(getattr(assignment, "propertyUrn", None) or "")
        if "." not in urn:
            continue
        short_name = urn.rsplit(".", 1)[-1]
        values[short_name] = list(getattr(assignment, "values", None) or [])

    return values


def _first(values: list | None):
    return values[0] if values else None


def _status(value) -> MemoryStatus:
    try:
        return MemoryStatus(str(value).upper())
    except (ValueError, AttributeError):
        return MemoryStatus.VALID


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _aspect(entity: dict, name: str) -> dict:
    """Unwrap the {aspectName: {"value": {...}}} envelope of the OpenAPI v3 API."""
    wrapper = entity.get(name)
    if not isinstance(wrapper, dict):
        return {}
    value = wrapper.get("value")
    return value if isinstance(value, dict) else {}
