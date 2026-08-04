from halflife.fingerprint import compare, decode, digest, encode, fingerprint_all


def test_ordering_does_not_change_digest():
    a = {"fields": ["b", "a"], "owners": ["x"]}
    b = {"fields": ["a", "b"], "owners": ["x"]}
    assert digest(a) == digest(b)


def test_empty_and_absent_are_equivalent():
    assert digest({"fields": ["a"], "terms": []}) == digest({"fields": ["a"]})


def test_field_type_change_moves_digest():
    before = {"fields": ["status:STRING:varchar"]}
    after = {"fields": ["status:NUMBER:int"]}
    assert digest(before) != digest(after)


def test_compare_detects_changed_and_missing():
    recorded = {"urn:a": "111111111111", "urn:b": "222222222222"}
    current = {"urn:a": "999999999999"}  # a changed, b unreadable
    assert compare(recorded, current) == ["urn:a", "urn:b"]


def test_compare_ignores_new_dependencies():
    recorded = {"urn:a": "111111111111"}
    current = {"urn:a": "111111111111", "urn:new": "333333333333"}
    assert compare(recorded, current) == []


def test_encode_decode_roundtrip():
    fingerprints = fingerprint_all({"urn:a": {"x": 1}, "urn:b": {"y": 2}})
    assert decode(encode(fingerprints)) == fingerprints


def test_decode_tolerates_garbage():
    assert decode(None) == {}
    assert decode("not json") == {}
    assert decode("[1,2]") == {}
