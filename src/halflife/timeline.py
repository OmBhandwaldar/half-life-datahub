"""Client for DataHub's Timeline API.

Half-Life does not diff metadata itself where DataHub already does it. The
Timeline API reports field-level changes and grades each one for compatibility
(``MAJOR`` = backwards incompatible), which is exactly the signal needed to
decide whether a memory is merely suspect or outright dead.

Endpoint: ``GET /openapi/v2/timeline/v1/{urn}`` (DataHub server 0.8.28+).
"""

from __future__ import annotations

from urllib.parse import quote

import httpx

from .config import Config
from .models import ChangeCategory, ChangeEvent, SemVerChange, VALIDATED_CATEGORIES

#: Wire names that differ from the documented enum.
#:
#: The docs present ``OWNERSHIP`` as current and ``OWNER`` as a legacy alias, but
#: DataHub v1.5.0.6 returns HTTP 500 for ``OWNERSHIP`` on every URN — including
#: ones that do not exist — while ``OWNER`` works. We send what the server
#: accepts and normalise back to :class:`ChangeCategory` when parsing.
_WIRE_NAMES = {ChangeCategory.OWNERSHIP: "OWNER"}


def _wire(category: ChangeCategory) -> str:
    return _WIRE_NAMES.get(category, category.value)


class TimelineClient:
    def __init__(self, config: Config, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=30.0)

    def changes(
        self,
        urn: str,
        start: int,
        end: int,
        categories: tuple[ChangeCategory, ...] = VALIDATED_CATEGORIES,
    ) -> list[ChangeEvent]:
        """Return change events for ``urn`` between two epoch-millisecond bounds.

        A dependency that has no timeline (unsupported entity type, or nothing
        recorded yet) yields an empty list rather than an error — absence of
        history is not evidence of change, and the fingerprint check in
        :mod:`halflife.validator` is the backstop for that case.
        """
        events = self._collect(urn, categories, start, end)

        # The server does not honour `start`: it replays the entity's whole
        # computed history regardless, so a freshly recorded memory would be
        # judged against the ingestion that created its dependencies. Filter to
        # the window we actually asked for.
        return [e for e in events if e.timestamp > start]

    def _collect(
        self,
        urn: str,
        categories: tuple[ChangeCategory, ...],
        start: int,
        end: int,
    ) -> list[ChangeEvent]:
        try:
            return self._fetch(urn, categories, start, end)
        except httpx.HTTPError:
            # One unhealthy category must not blind us to the others, so retry
            # them individually and keep whatever succeeds.
            events: list[ChangeEvent] = []
            for category in categories:
                try:
                    events.extend(self._fetch(urn, (category,), start, end))
                except httpx.HTTPError:
                    continue
            events.sort(key=lambda e: e.timestamp)
            return events

    def _fetch(
        self,
        urn: str,
        categories: tuple[ChangeCategory, ...],
        start: int,
        end: int,
    ) -> list[ChangeEvent]:
        url = f"{self._config.gms_url}/openapi/v2/timeline/v1/{quote(urn, safe='')}"
        params = [("categories", _wire(c)) for c in categories]
        params += [("start", str(start)), ("end", str(end))]

        response = self._client.get(url, params=params, headers=self._config.auth_headers)
        if response.status_code == 404:
            return []
        response.raise_for_status()

        return _parse(response.json(), urn)


def _parse(payload: object, fallback_urn: str) -> list[ChangeEvent]:
    """Flatten the changeTransactions -> changeEvents nesting into a flat list."""
    events: list[ChangeEvent] = []

    if isinstance(payload, dict):
        transactions = payload.get("changeTransactions") or []
    elif isinstance(payload, list):
        # Some server versions return the transaction array directly.
        transactions = payload
    else:
        return events

    for transaction in transactions:
        if not isinstance(transaction, dict):
            continue
        timestamp = int(transaction.get("timestamp") or 0)
        for raw in transaction.get("changeEvents") or []:
            event = _parse_event(raw, timestamp, fallback_urn)
            if event is not None:
                events.append(event)

    events.sort(key=lambda e: e.timestamp)
    return events


def _parse_event(raw: object, transaction_ts: int, fallback_urn: str) -> ChangeEvent | None:
    if not isinstance(raw, dict):
        return None

    category = _coerce(ChangeCategory, raw.get("category"))
    if category is None:
        # Unknown category: ignore rather than guess at its severity.
        return None

    return ChangeEvent(
        category=category,
        # Documented as `changeType`; served as `operation`.
        change_type=str(raw.get("changeType") or raw.get("operation") or "MODIFY"),
        # Documented as `target`; served as `entityUrn`.
        target_urn=str(raw.get("target") or raw.get("entityUrn") or fallback_urn),
        sem_ver_change=_coerce(SemVerChange, raw.get("semVerChange")) or SemVerChange.NONE,
        description=str(raw.get("description") or ""),
        timestamp=int(raw.get("timestamp") or transaction_ts),
        element_id=_element_id(raw),
    )


def _element_id(raw: dict) -> str | None:
    """Identify the changed sub-element, preferring a readable field path.

    The live API returns a full schemaField URN in `modifier` plus a bare
    `fieldPath` under `parameters`; the latter is what belongs in a one-line
    reason a human will read.
    """
    parameters = raw.get("parameters")
    if isinstance(parameters, dict) and parameters.get("fieldPath"):
        return str(parameters["fieldPath"])

    value = raw.get("elementId") or raw.get("modifier")
    return str(value) if value else None


def _coerce(enum_cls, value: object):
    """Map a raw string onto an enum member, tolerating case and legacy aliases."""
    if not value:
        return None
    text = str(value).strip().upper()
    if enum_cls is ChangeCategory and text == "OWNER":
        text = "OWNERSHIP"  # legacy alias
    try:
        return enum_cls(text)
    except ValueError:
        return None
