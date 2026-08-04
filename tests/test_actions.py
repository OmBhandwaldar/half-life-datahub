"""relatedAssets is fussy about entity types; these pin what we send it."""

from halflife.actions import _linkable_asset

DATASET = (
    "urn:li:dataset:(urn:li:dataPlatform:dbt,"
    "b2fd91.order_entry_db.order_entry.inventories,PROD)"
)


def test_schema_field_folds_up_to_its_dataset():
    """Schema-change events target the field, which cannot be a related asset."""
    field_urn = f"urn:li:schemaField:({DATASET},quantity_on_hand)"
    assert _linkable_asset(field_urn) == DATASET


def test_dataset_passes_through():
    assert _linkable_asset(DATASET) == DATASET


def test_glossary_term_passes_through():
    assert _linkable_asset("urn:li:glossaryTerm:x") == "urn:li:glossaryTerm:x"


def test_document_is_dropped():
    """Documents link through relatedDocuments, not relatedAssets."""
    assert _linkable_asset("urn:li:document:hl-demo-order-total") is None


def test_unknown_entity_type_is_dropped_rather_than_sent():
    assert _linkable_asset("urn:li:corpuser:alice") is None


def test_malformed_schema_field_is_dropped():
    assert _linkable_asset("urn:li:schemaField:(no-comma-here") is None
