"""Deterministic fingerprints of the metadata a memory depends on.

The Timeline API is the primary drift signal, but it only covers some entity
types and categories — lineage changes, for instance, never appear there. A
fingerprint is a cheap second opinion: hash the parts of an entity a memory
could plausibly have relied on, and compare later. A hash that moved with no
corresponding timeline event is *silent drift*, which is the failure mode
DataHub names but nothing detects.

Snapshots are plain dicts so this module stays pure and unit-testable; fetching
them is :mod:`halflife.client`'s job.
"""

from __future__ import annotations

import hashlib
import json

#: Truncated digest length. Full SHA-256 is overkill here and the combined map
#: has to fit inside a structured property value.
DIGEST_CHARS = 12


def canonicalise(snapshot: dict) -> dict:
    """Normalise a snapshot so irrelevant ordering never looks like a change."""
    result: dict = {}
    for key, value in snapshot.items():
        if value is None or value == [] or value == {}:
            continue  # absent and empty are the same thing
        if isinstance(value, (list, set, tuple)):
            result[key] = sorted(str(v) for v in value)
        elif isinstance(value, dict):
            result[key] = canonicalise(value)
        else:
            result[key] = str(value)
    return result


def digest(snapshot: dict) -> str:
    """Short, stable hash of a single entity's snapshot."""
    payload = json.dumps(canonicalise(snapshot), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:DIGEST_CHARS]


def fingerprint_all(snapshots: dict[str, dict]) -> dict[str, str]:
    """Map dependency URN -> digest."""
    return {urn: digest(snapshot) for urn, snapshot in snapshots.items()}


def compare(recorded: dict[str, str], current: dict[str, str]) -> list[str]:
    """URNs whose fingerprint changed since the memory was recorded.

    Dependencies missing from ``current`` count as drifted: an entity that can no
    longer be read is at least as suspicious as one that changed. Dependencies
    absent from ``recorded`` are ignored, since there is no baseline to compare.
    """
    drifted = []
    for urn, recorded_digest in recorded.items():
        if current.get(urn) != recorded_digest:
            drifted.append(urn)
    return sorted(drifted)


def encode(fingerprints: dict[str, str]) -> str:
    """Serialise the fingerprint map for storage in a structured property."""
    return json.dumps(fingerprints, sort_keys=True, separators=(",", ":"))


def decode(raw: str | None) -> dict[str, str]:
    """Inverse of :func:`encode`, tolerant of missing or malformed values."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}
