"""Scripted demo against the showcase-ecommerce datapack.

Five memories are recorded the way an analytics agent would record them. Three
upstream changes then land — a breaking schema change, a redefined glossary
term, and an ownership handover — and exactly the memories that depend on them
should react. The two that do not depend on anything touched must stay green;
a tool that reddens everything is no more useful than one that reddens nothing.
"""

from __future__ import annotations

import time

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

    console.print(
        "\n[dim]All five start VALID. Run [bold]halflife demo drift[/dim][dim] "
        "to change the world underneath them.[/]"
    )


def drift(client: HalfLifeClient, console) -> None:
    console.print("[bold]Applying three upstream changes[/]\n")

    _breaking_schema_change(client, console)
    _redefine_glossary_term(client, console)
    _hand_over_ownership(client, console)

    console.print(
        "\n[dim]Give DataHub a few seconds to compute the timeline, then run "
        "[bold]halflife validate --apply[/dim][dim].[/]"
    )


def _breaking_schema_change(client: HalfLifeClient, console) -> None:
    """Drop a column from order_details — a MAJOR, memory-killing change."""
    schema = client.graph.get_aspect(ORDER_DETAILS, aspect_type=SchemaMetadataClass)
    if schema is None:
        console.print("  [red]skip[/] order_details has no schema")
        return

    victim = _find_field(schema, "unit_price") or schema.fields[-1]
    schema.fields = [f for f in schema.fields if f.fieldPath != victim.fieldPath]
    client.graph.emit(MetadataChangeProposalWrapper(entityUrn=ORDER_DETAILS, aspect=schema))
    console.print(
        f"  [red]breaking[/]  dropped column '{victim.fieldPath}' from analytics.order_details"
    )


def _redefine_glossary_term(client: HalfLifeClient, console) -> None:
    """Redefine Order Total so anything built on the old meaning is doubtful."""
    info = client.graph.get_aspect(ORDER_TOTAL_TERM, aspect_type=GlossaryTermInfoClass)
    if info is None:
        console.print("  [red]skip[/] Order Total term not found")
        return

    info.definition = (
        "The total monetary value of an order EXCLUDING discounts, taxes and "
        "shipping. Redefined by the finance team to align with the general ledger."
    )
    client.graph.emit(MetadataChangeProposalWrapper(entityUrn=ORDER_TOTAL_TERM, aspect=info))
    console.print("  [yellow]semantic[/]  redefined glossary term 'Order Total'")


def _hand_over_ownership(client: HalfLifeClient, console) -> None:
    """Move the customers table to a new owner — escalation must follow."""
    ownership = client.graph.get_aspect(CUSTOMERS, aspect_type=OwnershipClass)
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

    store = MemoryStore(client)
    removed = 0
    for memory in store.list_memories():
        if memory.id.startswith("hl-demo") or "-audit-" in memory.id:
            try:
                client.graph.delete_entity(urn=memory.urn, hard=True)
                removed += 1
                console.print(f"  [dim]deleted[/] {memory.title}")
            except Exception as exc:
                console.print(f"  [red]failed[/] {memory.urn}: {exc}")

    console.print(f"\n[green]Removed {removed} document(s).[/]")
    console.print(
        "[dim]Restore the mutated entities with:  "
        "datahub datapack unload showcase-ecommerce && "
        "datahub datapack load showcase-ecommerce[/]"
    )


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
