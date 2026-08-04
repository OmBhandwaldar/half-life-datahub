"""Thin wrapper over the DataHub SDK and GraphQL API.

Everything Half-Life needs from DataHub goes through here: reading the metadata
a memory depends on, writing memories back as Documents, and resolving current
owners for escalation re-routing.
"""

from __future__ import annotations

from datahub.ingestion.graph.client import DataHubGraph
from datahub.sdk.document import Document
from datahub.sdk.main_client import DataHubClient

from .config import Config

# One query covers every dependency type we support. Inline fragments keep it to
# a single round trip per entity regardless of what that entity turns out to be.
_SNAPSHOT_QUERY = """
query Snapshot($urn: String!) {
  entity(urn: $urn) {
    urn
    type
    ... on Dataset {
      properties { description }
      schemaMetadata { fields { fieldPath type nativeDataType nullable } }
      ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } } }
      glossaryTerms { terms { term { urn } } }
      deprecation { deprecated }
    }
    ... on GlossaryTerm {
      properties { definition name }
      ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } } }
    }
    ... on Dashboard {
      properties { description }
      ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } } }
    }
    ... on Chart {
      properties { description }
      ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } } }
    }
  }
}
"""


class HalfLifeClient:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.from_env()
        self.sdk = DataHubClient(server=self.config.gms_url, token=self.config.token)

    @property
    def graph(self) -> DataHubGraph:
        return self.sdk._graph  # the SDK exposes no public accessor

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        return self.graph.execute_graphql(query, variables=variables or {})

    # ---- reads -------------------------------------------------------------

    def snapshot(self, urn: str) -> dict:
        """Fetch the parts of an entity a memory could plausibly depend on.

        Returns an empty dict when the entity cannot be read — the caller treats
        that as drift rather than as "unchanged", since a memory pointing at a
        vanished asset is exactly as untrustworthy as one pointing at a changed
        asset.
        """
        try:
            result = self.graphql(_SNAPSHOT_QUERY, {"urn": urn})
        except Exception:
            return {}

        entity = (result or {}).get("entity")
        if not entity:
            return {}

        snapshot: dict = {"type": entity.get("type")}

        properties = entity.get("properties") or {}
        if properties.get("description"):
            snapshot["description"] = properties["description"]
        if properties.get("definition"):
            snapshot["definition"] = properties["definition"]

        schema = entity.get("schemaMetadata") or {}
        if schema.get("fields"):
            # Field type is what breaks a memory, so fold it into the identity.
            snapshot["fields"] = [
                f"{f.get('fieldPath')}:{f.get('type')}:{f.get('nativeDataType')}"
                for f in schema["fields"]
            ]

        owners = _owner_urns(entity.get("ownership"))
        if owners:
            snapshot["owners"] = owners

        terms = entity.get("glossaryTerms") or {}
        if terms.get("terms"):
            snapshot["terms"] = [
                (t.get("term") or {}).get("urn") for t in terms["terms"] if t.get("term")
            ]

        deprecation = entity.get("deprecation") or {}
        if deprecation.get("deprecated"):
            snapshot["deprecated"] = True

        return snapshot

    def snapshots(self, urns: list[str]) -> dict[str, dict]:
        return {urn: self.snapshot(urn) for urn in urns}

    def owners_of(self, urn: str) -> list[str]:
        """Current owners of an entity — the escalation target after a change."""
        return list(self.snapshot(urn).get("owners", []))

    def upstreams(self, urn: str) -> list[str]:
        """Immediate upstream URNs, used to notice lineage rewiring."""
        query = """
        query Upstreams($urn: String!) {
          dataset(urn: $urn) {
            upstream: lineage(input: {direction: UPSTREAM, start: 0, count: 100}) {
              relationships { entity { urn } }
            }
          }
        }
        """
        try:
            result = self.graphql(query, {"urn": urn})
        except Exception:
            return []
        dataset = (result or {}).get("dataset") or {}
        relationships = ((dataset.get("upstream") or {}).get("relationships")) or []
        return sorted(
            r["entity"]["urn"] for r in relationships if (r.get("entity") or {}).get("urn")
        )

    def get_document(self, urn: str) -> Document | None:
        try:
            entity = self.sdk.entities.get(urn)
        except Exception:
            return None
        return entity if isinstance(entity, Document) else None

    # ---- writes ------------------------------------------------------------

    def upsert(self, entity) -> None:
        self.sdk.entities.upsert(entity)

    def exists(self, urn: str) -> bool:
        try:
            return self.graph.exists(urn)
        except Exception:
            return False


def _owner_urns(ownership: object) -> list[str]:
    if not isinstance(ownership, dict):
        return []
    urns = []
    for entry in ownership.get("owners") or []:
        owner = (entry or {}).get("owner") or {}
        if owner.get("urn"):
            urns.append(owner["urn"])
    return sorted(set(urns))
