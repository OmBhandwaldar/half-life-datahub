"""Configuration for Half-Life, read from the same env vars the DataHub CLI uses."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_GMS_URL = "http://localhost:8080"

#: Namespace for every structured property and tag Half-Life writes.
NAMESPACE = "halflife"

#: Document subtypes Half-Life creates.
SUBTYPE_MEMORY = "Agent Memory"
SUBTYPE_AUDIT = "Memory Audit"

#: Elasticsearch keyword ceiling for string-backed structured property values.
#: Values are truncated to stay under it; full detail lives in the audit document.
MAX_PROPERTY_BYTES = 32_766


@dataclass(frozen=True)
class Config:
    gms_url: str
    token: str | None

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            gms_url=os.environ.get("DATAHUB_GMS_URL", DEFAULT_GMS_URL).rstrip("/"),
            token=os.environ.get("DATAHUB_GMS_TOKEN") or None,
        )

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}


def property_urn(name: str) -> str:
    """URN of a Half-Life structured property, e.g. ``status`` -> the ``halflife.status`` URN."""
    return f"urn:li:structuredProperty:{NAMESPACE}.{name}"
