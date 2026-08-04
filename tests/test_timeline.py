"""Parsing is defensive because timeline payload shapes vary across versions."""

from halflife.models import ChangeCategory, SemVerChange
from halflife.timeline import _parse

URN = "urn:li:dataset:(urn:li:dataPlatform:hive,testDataset,PROD)"


def payload(events, timestamp=1_700_000_000_000):
    return {
        "changeTransactions": [
            {"timestamp": timestamp, "semVersion": "1.0.0", "changeEvents": events}
        ]
    }


def test_parses_documented_shape():
    events = _parse(
        payload(
            [
                {
                    "changeType": "ADD",
                    "category": "TECHNICAL_SCHEMA",
                    "target": URN,
                    "elementId": "field:property_id",
                    "semVerChange": "PATCH",
                    "description": "A forwards & backwards compatible change.",
                }
            ]
        ),
        URN,
    )
    assert len(events) == 1
    assert events[0].category is ChangeCategory.TECHNICAL_SCHEMA
    assert events[0].sem_ver_change is SemVerChange.PATCH
    assert events[0].element_id == "field:property_id"
    assert not events[0].is_breaking


def test_major_change_is_breaking():
    events = _parse(
        payload([{"category": "TECHNICAL_SCHEMA", "semVerChange": "MAJOR"}]), URN
    )
    assert events[0].is_breaking


def test_legacy_owner_alias_maps_to_ownership():
    events = _parse(payload([{"category": "OWNER", "semVerChange": "MINOR"}]), URN)
    assert events[0].category is ChangeCategory.OWNERSHIP


def test_bare_transaction_list_is_accepted():
    events = _parse(
        [{"timestamp": 1, "changeEvents": [{"category": "DOCUMENTATION"}]}], URN
    )
    assert len(events) == 1
    assert events[0].sem_ver_change is SemVerChange.NONE


def test_unknown_category_is_dropped_rather_than_guessed():
    events = _parse(payload([{"category": "SOMETHING_NEW"}]), URN)
    assert events == []


def test_missing_target_falls_back_to_queried_urn():
    events = _parse(payload([{"category": "DOCUMENTATION"}]), URN)
    assert events[0].target_urn == URN


def test_events_are_sorted_by_time():
    raw = {
        "changeTransactions": [
            {"timestamp": 200, "changeEvents": [{"category": "DOCUMENTATION"}]},
            {"timestamp": 100, "changeEvents": [{"category": "OWNERSHIP"}]},
        ]
    }
    events = _parse(raw, URN)
    assert [e.timestamp for e in events] == [100, 200]


def test_parses_live_payload_shape():
    """The served payload differs from the docs: entityUrn/operation/modifier.

    Captured verbatim from DataHub v1.5.0.6 rather than from documentation.
    """
    raw = [
        {
            "timestamp": 1785819400000,
            "changeEvents": [
                {
                    "entityUrn": URN,
                    "category": "TECHNICAL_SCHEMA",
                    "operation": "REMOVE",
                    "modifier": f"urn:li:schemaField:({URN},country_code)",
                    "parameters": {"fieldPath": "country_code"},
                    "semVerChange": "MAJOR",
                    "description": (
                        "A backwards incompatible change due to removal of "
                        "field: 'country_code'."
                    ),
                }
            ],
        }
    ]
    events = _parse(raw, "urn:li:dataset:(other,other,PROD)")
    assert len(events) == 1
    event = events[0]
    assert event.is_breaking
    assert event.change_type == "REMOVE"
    assert event.target_urn == URN  # from entityUrn, not the fallback
    assert event.element_id == "country_code"  # readable path, not the field URN


def test_element_id_falls_back_to_modifier_without_parameters():
    events = _parse(
        payload([{"category": "TECHNICAL_SCHEMA", "modifier": "field:xyz"}]), URN
    )
    assert events[0].element_id == "field:xyz"


def test_empty_and_malformed_payloads():
    assert _parse({}, URN) == []
    assert _parse(None, URN) == []
    assert _parse({"changeTransactions": [None]}, URN) == []
