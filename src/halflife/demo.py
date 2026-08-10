"""Scripted demo against the showcase-ecommerce datapack.

Five memories are recorded the way an analytics agent would record them. Three
upstream changes then land — a breaking schema change, a redefined glossary
term, and an ownership handover — and exactly the memories that depend on them
should react. The two that do not depend on anything touched must stay green;
a tool that reddens everything is no more useful than one that reddens nothing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    GlossaryTermInfoClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SchemaMetadataClass,
)

from .client import HalfLifeClient
from .store import MemoryStore

PREFIX = "b2fd91"

ORDER_DETAILS = (
    f"urn:li:dataset:(urn:li:dataPlatform:snowflake,{PREFIX}.order_entry_db.analytics.order_details,PROD)"
)
CUSTOMERS = (
    f"urn:li:dataset:(urn:li:dataPlatform:dbt,{PREFIX}.order_entry_db.order_entry.customers,PROD)"
)
ORDERS = (
    f"urn:li:dataset:(urn:li:dataPlatform:dbt,{PREFIX}.order_entry_db.order_entry.orders,PROD)"
)
INVENTORIES = (
    f"urn:li:dataset:(urn:li:dataPlatform:dbt,{PREFIX}.order_entry_db.order_entry.inventories,PROD)"
)
ORDER_TOTAL_TERM = f"urn:li:glossaryTerm:{PREFIX}.42266719-3cab-42b8-a8d2-49d782876dbc"

#: The engineer who inherits the customers table partway through the demo.
NEW_OWNER = "urn:li:corpuser:datahub"

MEMORY_IDS = (
    "hl-demo-order-total",
    "hl-demo-customer-segment",
    "hl-demo-order-grain",
    "hl-demo-inventory-refresh",
    "hl-demo-revenue-join",
)

_MEMORIES = (
    {
        "id": "hl-demo-order-total",
        "title": "Order Total is computed before discounts",
        "text": (
            "When reporting order value from analytics.order_details, use the "
            "Order Total definition: the monetary value of an order including "
            "all line items, discounts and shipping. Do not recompute it from "
            "unit_price * quantity, which ignores order-level adjustments."
        ),
        "dependencies": [ORDER_DETAILS, ORDER_TOTAL_TERM],
    },
    {
        "id": "hl-demo-customer-segment",
        "title": "Customer segmentation uses customer_class on the customers table",
        "text": (
            "Segment customers with order_entry.customers.customer_class. "
            "Escalate segmentation questions to the owners of that table."
        ),
        "dependencies": [CUSTOMERS],
    },
    {
        "id": "hl-demo-order-grain",
        "title": "order_details is one row per order line",
        "text": (
            "analytics.order_details is line-level, not order-level. Aggregate "
            "before joining to anything order-grained or totals will double count."
        ),
        "dependencies": [ORDER_DETAILS],
    },
    {
        "id": "hl-demo-inventory-refresh",
        "title": "Inventory snapshots land nightly",
        "text": (
            "order_entry.inventories is a nightly snapshot, so intraday stock "
            "questions cannot be answered from it."
        ),
        "dependencies": [INVENTORIES],
    },
    {
        "id": "hl-demo-revenue-join",
        "title": "Join orders to order_details on order_id",
        "text": (
            "order_entry.orders joins to analytics.order_details on order_id. "
            "There is no surrogate key on either side."
        ),
        "dependencies": [ORDERS, ORDER_DETAILS],
    },
)


def seed(client: HalfLifeClient, console) -> None:
    store = MemoryStore(client)
    console.print("[bold]Recording demo memories[/]\n")

    for spec in _MEMORIES:
        memory = store.record(
            memory_id=spec["id"],
            title=spec["title"],
            text=spec["text"],
            dependencies=spec["dependencies"],
        )
        console.print(f"  [green]recorded[/] {memory.title}")
        for urn, fingerprint in memory.fingerprints.items():
            console.print(f"      [dim]{fingerprint}  {_short(urn)}[/]")

    _await_readable(store, len(_MEMORIES), console)

    console.print(
        "\n[dim]All five start VALID. Run [bold]halflife demo drift[/dim][dim] "
        "to change the world underneath them.[/]"
    )


#: Where the pre-drift state is stashed so the scenario can be replayed.
#: `datapack load` will not restore a field that drift removed, so without this
#: every run eats another column and the demo is not repeatable.
BACKUP = Path.home() / ".halflife" / "demo-backup.json"


def _backup(key: str, payload: dict) -> None:
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if BACKUP.exists():
        try:
            existing = json.loads(BACKUP.read_text())
        except ValueError:
            existing = {}
    # Never overwrite a pristine snapshot with an already-drifted one.
    existing.setdefault(key, payload)
    BACKUP.write_text(json.dumps(existing, indent=2))


def _restore_payload(key: str) -> dict | None:
    if not BACKUP.exists():
        return None
    try:
        return json.loads(BACKUP.read_text()).get(key)
    except ValueError:
        return None


def drift(client: HalfLifeClient, console) -> None:
    console.print("[bold]Applying three upstream changes[/]\n")

    _breaking_schema_change(client, console)
    _redefine_glossary_term(client, console)
    _hand_over_ownership(client, console)

    _await_visible(client, console)


#: How long to wait for GMS to make an emitted change queryable.
_PROPAGATION_TIMEOUT_S = 90
_POLL_INTERVAL_S = 3


def _await_readable(store: MemoryStore, expected: int, console) -> None:
    """Block until every seeded memory can be read back.

    Writes are ingested asynchronously, so `seed` can return before its own
    documents are retrievable. A `validate` run immediately afterwards would
    then silently operate on a partial set and skip memories entirely - which
    looks like a logic bug but is really a race.
    """
    deadline = time.monotonic() + _PROPAGATION_TIMEOUT_S

    console.print("\n[dim]waiting for DataHub to index the memories…[/]", end="")
    while time.monotonic() < deadline:
        if len(store.list_memories()) >= expected:
            console.print(" [green]ready[/]")
            return
        console.print(".", end="")
        time.sleep(_POLL_INTERVAL_S)

    console.print(f" [yellow]only some are readable after {_PROPAGATION_TIMEOUT_S}s[/]")


def _await_visible(client: HalfLifeClient, console) -> None:
    """Block until the breaking change is actually observable.

    GMS ingests aspects asynchronously, so emitting a change and immediately
    validating reports the *old* state and the demo silently produces the wrong
    answer. Waiting here rather than printing "give it a few seconds" means the
    documented command sequence works when run back to back.
    """
    from .models import ChangeCategory
    from .timeline import TimelineClient

    timeline = TimelineClient(client.config)
    deadline = time.monotonic() + _PROPAGATION_TIMEOUT_S

    console.print("\n[dim]waiting for DataHub to process the changes…[/]", end="")
    while time.monotonic() < deadline:
        events = timeline.changes(
            INVENTORIES,
            start=0,
            end=int(time.time() * 1000),
            categories=(ChangeCategory.TECHNICAL_SCHEMA,),
        )
        if any(e.is_breaking for e in events):
            console.print(" [green]ready[/]")
            console.print(
                "\n[dim]Now run [bold]halflife validate --apply[/dim][dim].[/]"
            )
            return
        console.print(".", end="")
        time.sleep(_POLL_INTERVAL_S)

    # Not fatal: validation still works, it just may need a second run.
    console.print(
        f" [yellow]still pending after {_PROPAGATION_TIMEOUT_S}s[/]\n"
        "[dim]Run [bold]halflife validate --apply[/dim][dim] anyway; if the "
        "inventory memory has not expired, run it once more.[/]"
    )


def _breaking_schema_change(client: HalfLifeClient, console) -> None:
    """Drop a column from inventories — a MAJOR, memory-killing change.

    Deliberately aimed at a table only one memory depends on. Breaking
    order_details instead would expire three memories at once and mask the
    subtler glossary and ownership outcomes behind a wall of red.
    """
    schema = client.graph.get_aspect(INVENTORIES, aspect_type=SchemaMetadataClass)
    if schema is None:
        console.print("  [red]skip[/] inventories has no schema")
        return

    _backup("inventories_schema", schema.to_obj())

    victim = _find_field(schema, "quantity_on_hand") or schema.fields[-1]
    schema.fields = [f for f in schema.fields if f.fieldPath != victim.fieldPath]
    client.graph.emit(MetadataChangeProposalWrapper(entityUrn=INVENTORIES, aspect=schema))
    console.print(
        f"  [red]breaking[/]  dropped column '{victim.fieldPath}' from order_entry.inventories"
    )


def _redefine_glossary_term(client: HalfLifeClient, console) -> None:
    """Redefine Order Total so anything built on the old meaning is doubtful."""
    info = client.graph.get_aspect(ORDER_TOTAL_TERM, aspect_type=GlossaryTermInfoClass)
    if info is None:
        console.print("  [red]skip[/] Order Total term not found")
        return

    _backup("order_total_term", info.to_obj())

    info.definition = (
        "The total monetary value of an order EXCLUDING discounts, taxes and "
        "shipping. Redefined by the finance team to align with the general ledger."
    )
    client.graph.emit(MetadataChangeProposalWrapper(entityUrn=ORDER_TOTAL_TERM, aspect=info))
    console.print("  [yellow]semantic[/]  redefined glossary term 'Order Total'")


def _hand_over_ownership(client: HalfLifeClient, console) -> None:
    """Move the customers table to a new owner — escalation must follow."""
    ownership = client.graph.get_aspect(CUSTOMERS, aspect_type=OwnershipClass)
    if ownership is not None:
        _backup("customers_ownership", ownership.to_obj())

    owner = OwnerClass(owner=NEW_OWNER, type=OwnershipTypeClass.TECHNICAL_OWNER)

    if ownership is None:
        ownership = OwnershipClass(owners=[owner])
    else:
        ownership.owners = [
            o for o in ownership.owners if o.owner != NEW_OWNER
        ] + [owner]

    client.graph.emit(MetadataChangeProposalWrapper(entityUrn=CUSTOMERS, aspect=ownership))
    console.print(f"  [cyan]ownership[/] customers table handed to {NEW_OWNER}")


def reset(client: HalfLifeClient, console) -> None:
    """Delete demo memories and their audit documents."""
    console.print("[bold]Removing demo memories[/]\n")

    removed = 0
    # Enumerate documents directly rather than through MemoryStore: audit
    # documents carry a different subtype, so listing memories alone would
    # leave them behind to accumulate across runs.
    for urn in _demo_document_urns(client):
        try:
            client.graph.delete_entity(urn=urn, hard=True)
            removed += 1
            console.print(f"  [dim]deleted[/] {urn.rsplit(':', 1)[-1]}")
        except Exception as exc:
            console.print(f"  [red]failed[/] {urn}: {exc}")

    console.print(f"\n[green]Removed {removed} document(s).[/]")
    _restore_entities(client, console)


def _find_field(schema: SchemaMetadataClass, name: str):
    for field in schema.fields:
        if field.fieldPath == name or field.fieldPath.endswith(f".{name}"):
            return field
    return None


def _short(urn: str) -> str:
    if "," in urn:
        parts = urn.split(",")
        if len(parts) >= 2:
            return parts[-2]
    return urn.rsplit(":", 1)[-1]


def _restore_entities(client: HalfLifeClient, console) -> None:
    """Put back the schema, definition and ownership that drift changed.

    `datapack load` upserts and will not restore a field that was removed, so
    the scenario would otherwise degrade a little further on every run.
    """
    restores = (
        ("inventories_schema", INVENTORIES, SchemaMetadataClass),
        ("order_total_term", ORDER_TOTAL_TERM, GlossaryTermInfoClass),
        ("customers_ownership", CUSTOMERS, OwnershipClass),
    )

    restored = 0
    for key, urn, aspect_class in restores:
        payload = _restore_payload(key)
        if payload is None:
            continue
        try:
            client.graph.emit(
                MetadataChangeProposalWrapper(
                    entityUrn=urn, aspect=aspect_class.from_obj(payload)
                )
            )
            restored += 1
        except Exception as exc:
            console.print(f"  [red]restore failed[/] {key}: {exc}")

    if restored:
        console.print(f"[green]Restored {restored} mutated aspect(s).[/]")
        BACKUP.unlink(missing_ok=True)
    else:
        console.print("[dim]Nothing to restore (drift has not run).[/]")


def _demo_document_urns(client: HalfLifeClient) -> list[str]:
    """Every document this demo created, memories and audits alike."""
    urns: list[str] = []
    scroll_id: str | None = None

    while True:
        params: dict = {"count": 200}
        if scroll_id:
            params["scrollId"] = scroll_id
        try:
            response = client.get_json("/openapi/v3/entity/document", params)
        except Exception:
            break

        entities = response.get("entities") or []
        for entity in entities:
            urn = entity.get("urn") or ""
            if urn.startswith("urn:li:document:hl-"):
                urns.append(urn)

        scroll_id = response.get("scrollId")
        if not scroll_id or not entities:
            break

    return urns
