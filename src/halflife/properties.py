"""Structured property definitions that carry a memory's provenance.

These are what make a memory auditable rather than just a note: the dependency
URNs, the fingerprint of their state at record time, and the lifecycle verdict
are all typed, queryable metadata on the Document itself — not prose buried in
its body.
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import HalfLifeClient
from .config import NAMESPACE

DOCUMENT_ENTITY_TYPE = "urn:li:entityType:datahub.document"

_STRING = "urn:li:dataType:datahub.string"
_NUMBER = "urn:li:dataType:datahub.number"
_URN = "urn:li:dataType:datahub.urn"


@dataclass(frozen=True)
class PropertySpec:
    name: str
    display_name: str
    description: str
    value_type: str
    cardinality: str = "SINGLE"

    @property
    def qualified_name(self) -> str:
        return f"{NAMESPACE}.{self.name}"

    @property
    def urn(self) -> str:
        return f"urn:li:structuredProperty:{self.qualified_name}"


SPECS: tuple[PropertySpec, ...] = (
    PropertySpec(
        "status",
        "Memory Status",
        "Lifecycle state of an agent memory: VALID, SUSPECT or EXPIRED.",
        _STRING,
    ),
    PropertySpec(
        "dependencies",
        "Memory Dependencies",
        "URNs of the metadata this memory was derived from.",
        _URN,
        cardinality="MULTIPLE",
    ),
    PropertySpec(
        "fingerprint",
        "Dependency Fingerprint",
        "JSON map of dependency URN to a hash of its state when the memory was recorded.",
        _STRING,
    ),
    PropertySpec(
        "recorded_at",
        "Recorded At",
        "Epoch milliseconds when the memory was written.",
        _NUMBER,
    ),
    PropertySpec(
        "last_validated_at",
        "Last Validated At",
        "Epoch milliseconds of the last integrity check; the Timeline query watermark.",
        _NUMBER,
    ),
    PropertySpec(
        "invalidation_reason",
        "Invalidation Reason",
        "Short causal summary of why this memory was marked suspect or expired.",
        _STRING,
    ),
    PropertySpec(
        "integrity_score",
        "Integrity Score",
        "Confidence that this memory still reflects reality, from 0 to 100.",
        _NUMBER,
    ),
)

BY_NAME = {spec.name: spec for spec in SPECS}


_CREATE = """
mutation CreateProperty(
  $id: String!, $qualifiedName: String!, $displayName: String!,
  $description: String!, $valueType: String!, $cardinality: PropertyCardinality!,
  $entityTypes: [String!]!
) {
  createStructuredProperty(input: {
    id: $id
    qualifiedName: $qualifiedName
    displayName: $displayName
    description: $description
    valueType: $valueType
    cardinality: $cardinality
    entityTypes: $entityTypes
  }) { urn }
}
"""


def bootstrap(client: HalfLifeClient) -> dict[str, str]:
    """Create every Half-Life property, skipping ones that already exist.

    Returns a name -> outcome map so callers can report what happened.
    """
    results: dict[str, str] = {}

    for spec in SPECS:
        if client.exists(spec.urn):
            results[spec.name] = "exists"
            continue
        try:
            client.graphql(
                _CREATE,
                {
                    "id": spec.qualified_name,
                    "qualifiedName": spec.qualified_name,
                    "displayName": spec.display_name,
                    "description": spec.description,
                    "valueType": spec.value_type,
                    "cardinality": spec.cardinality,
                    "entityTypes": [DOCUMENT_ENTITY_TYPE],
                },
            )
            results[spec.name] = "created"
        except Exception as exc:  # surfaced by the CLI rather than raised
            results[spec.name] = f"failed: {exc}"

    return results
