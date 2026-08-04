"""Core domain types.

A *memory* is something an agent learned and wrote back to DataHub. It stays
trustworthy only as long as the metadata it was derived from stays put, so every
memory carries the URNs it depends on plus a fingerprint of their state at the
moment it was recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MemoryStatus(str, Enum):
    VALID = "VALID"
    SUSPECT = "SUSPECT"
    EXPIRED = "EXPIRED"


class SemVerChange(str, Enum):
    """DataHub's compatibility grading for a single change event."""

    MAJOR = "MAJOR"  # backwards incompatible
    MINOR = "MINOR"
    PATCH = "PATCH"
    NONE = "NONE"


class ChangeCategory(str, Enum):
    """Timeline API categories Half-Life subscribes to."""

    TECHNICAL_SCHEMA = "TECHNICAL_SCHEMA"
    OWNERSHIP = "OWNERSHIP"
    GLOSSARY_TERM = "GLOSSARY_TERM"
    DOCUMENTATION = "DOCUMENTATION"
    TAG = "TAG"


#: Categories queried during validation. TAG is deliberately excluded: tags are
#: organisational labels and do not change what a memory asserts.
VALIDATED_CATEGORIES = (
    ChangeCategory.TECHNICAL_SCHEMA,
    ChangeCategory.OWNERSHIP,
    ChangeCategory.GLOSSARY_TERM,
    ChangeCategory.DOCUMENTATION,
)


@dataclass(frozen=True)
class ChangeEvent:
    """One change reported by the Timeline API."""

    category: ChangeCategory
    change_type: str
    target_urn: str
    sem_ver_change: SemVerChange
    description: str
    timestamp: int
    element_id: str | None = None

    @property
    def is_breaking(self) -> bool:
        return self.sem_ver_change is SemVerChange.MAJOR


@dataclass
class Memory:
    """An agent memory, backed by a DataHub Document."""

    urn: str
    id: str
    title: str
    text: str
    dependencies: list[str] = field(default_factory=list)
    #: dependency URN -> short fingerprint captured when the memory was recorded
    fingerprints: dict[str, str] = field(default_factory=dict)
    status: MemoryStatus = MemoryStatus.VALID
    recorded_at: int = 0
    last_validated_at: int = 0
    invalidation_reason: str | None = None
    integrity_score: int = 100


@dataclass
class Verdict:
    """Outcome of validating a single memory."""

    memory: Memory
    previous_status: MemoryStatus
    new_status: MemoryStatus
    events: list[ChangeEvent] = field(default_factory=list)
    #: Dependencies whose fingerprint moved without a corresponding Timeline event.
    silent_drift: list[str] = field(default_factory=list)
    #: Current owners of changed dependencies, for escalation re-routing.
    reroute_owners: list[str] = field(default_factory=list)
    integrity_score: int = 100
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.new_status is not self.previous_status

    @property
    def expired(self) -> bool:
        return self.new_status is MemoryStatus.EXPIRED
