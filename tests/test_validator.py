"""Severity mapping is the heart of the product, so it is tested in isolation."""

from halflife.models import ChangeCategory, ChangeEvent, MemoryStatus, SemVerChange
from halflife.validator import _judge


def event(category, sem_ver, element_id=None, description="changed"):
    return ChangeEvent(
        category=category,
        change_type="MODIFY",
        target_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,shop.orders,PROD)",
        sem_ver_change=sem_ver,
        description=description,
        timestamp=1_700_000_000_000,
        element_id=element_id,
    )


def test_no_changes_stays_valid():
    status, score, _ = _judge([], [])
    assert status is MemoryStatus.VALID
    assert score == 100


def test_breaking_schema_change_expires_memory():
    events = [event(ChangeCategory.TECHNICAL_SCHEMA, SemVerChange.MAJOR, "field:status")]
    status, score, reason = _judge(events, [])
    assert status is MemoryStatus.EXPIRED
    assert score == 0
    assert "Breaking change" in reason


def test_minor_glossary_change_makes_memory_suspect():
    events = [event(ChangeCategory.GLOSSARY_TERM, SemVerChange.MINOR)]
    status, score, _ = _judge(events, [])
    assert status is MemoryStatus.SUSPECT
    assert score == 70


def test_silent_drift_alone_makes_memory_suspect():
    status, score, reason = _judge([], ["urn:li:dataset:(x,y,PROD)"])
    assert status is MemoryStatus.SUSPECT
    assert score == 75
    assert "Silent drift" in reason


def test_ownership_change_does_not_invalidate():
    events = [event(ChangeCategory.OWNERSHIP, SemVerChange.MINOR)]
    status, score, reason = _judge(events, [])
    assert status is MemoryStatus.VALID
    assert score == 100
    assert "re-routed" in reason


def test_documentation_edit_dents_score_but_keeps_memory():
    events = [event(ChangeCategory.DOCUMENTATION, SemVerChange.PATCH)]
    status, score, _ = _judge(events, [])
    assert status is MemoryStatus.VALID
    assert score == 95


def test_breaking_change_wins_over_everything_else():
    events = [
        event(ChangeCategory.DOCUMENTATION, SemVerChange.PATCH),
        event(ChangeCategory.TECHNICAL_SCHEMA, SemVerChange.MAJOR),
    ]
    status, score, _ = _judge(events, ["urn:x"])
    assert status is MemoryStatus.EXPIRED
    assert score == 0


def test_score_never_goes_negative():
    events = [event(ChangeCategory.GLOSSARY_TERM, SemVerChange.MINOR) for _ in range(10)]
    _, score, _ = _judge(events, [])
    assert score == 0


# --- behaviours discovered against a live DataHub, not from the docs --------


def glossary_event(category, sem_ver, description="definition edited"):
    return ChangeEvent(
        category=category,
        change_type="MODIFY",
        target_urn="urn:li:glossaryTerm:b2fd91.42266719",
        sem_ver_change=sem_ver,
        description=description,
        timestamp=1_700_000_000_000,
    )


def test_glossary_definition_edit_is_semantic_despite_documentation_category():
    """DataHub reports a term's definition change as DOCUMENTATION."""
    events = [glossary_event(ChangeCategory.DOCUMENTATION, SemVerChange.MINOR)]
    status, score, _ = _judge(events, [])
    assert status is MemoryStatus.SUSPECT
    assert score == 70


def test_dataset_documentation_edit_stays_cosmetic():
    events = [event(ChangeCategory.DOCUMENTATION, SemVerChange.MINOR)]
    status, score, _ = _judge(events, [])
    assert status is MemoryStatus.VALID
    assert score == 95
