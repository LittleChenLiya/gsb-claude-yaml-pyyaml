"""Explicit key collision reporting for mapping construction.

Covers:

* typed collisions (``true`` vs ``1``) are distinguished from raw source
  duplicates, while the string ``"1"`` and the integer ``1`` stay distinct;
* reports keep both scalar tags and both source positions, and never rely on
  ``str(key)`` for identity;
* nested mappings are checked independently;
* strict loaders reject a colliding mapping before any mapping value is
  constructed, while the default loaders keep their last-value-wins
  semantics and merely record the collision;
* unhashable keys keep raising the original constructor error;
* merge keys are reported in the real flattened construction order.
"""

import pytest

import yaml


BOOL_TAG = "tag:yaml.org,2002:bool"
INT_TAG = "tag:yaml.org,2002:int"
STR_TAG = "tag:yaml.org,2002:str"


def default_loader_classes():
    classes = [yaml.SafeLoader, yaml.FullLoader]
    if hasattr(yaml, "CSafeLoader"):
        classes.append(yaml.CSafeLoader)
    if hasattr(yaml, "CFullLoader"):
        classes.append(yaml.CFullLoader)
    return classes


def strict_loader_classes():
    classes = [yaml.StrictSafeLoader, yaml.StrictFullLoader]
    if hasattr(yaml, "CStrictSafeLoader"):
        classes.append(yaml.CStrictSafeLoader)
    if hasattr(yaml, "CStrictFullLoader"):
        classes.append(yaml.CStrictFullLoader)
    return classes


def load_with(Loader, source):
    """Construct one document and return the data and the live loader."""
    loader = Loader(source)
    return loader.get_single_data(), loader


def construct(Loader, source):
    loader = Loader(source)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def test_true_and_one_are_not_duplicate_in_source():
    # Sanity check for the node identity rule used by the reports.
    from yaml.constructor import _same_key_source

    loader = yaml.SafeLoader("true: a\n1: b")
    try:
        node = loader.get_single_node()
    finally:
        loader.dispose()

    (bool_key, _), (int_key, _) = node.value
    assert bool_key.tag == BOOL_TAG
    assert int_key.tag == INT_TAG
    assert not _same_key_source(bool_key, int_key)


@pytest.mark.parametrize("Loader", default_loader_classes())
def test_default_loaders_keep_override_semantics_and_report_typed_collision(Loader):
    source = "true: first value\n1: second value\n"
    data, loader = load_with(Loader, source)
    try:
        # Default semantics: later key wins, including for typed collisions.
        assert data == {True: "second value"}

        assert len(loader.key_collisions) == 1
        collision = loader.key_collisions[0]
        assert collision.kind == "typed"
        assert collision.first_key is True
        assert collision.duplicate_key == 1
        assert collision.first_tag == BOOL_TAG
        assert collision.duplicate_tag == INT_TAG
        # Both scalar positions are kept on the report.
        assert collision.first_mark.line == 0
        assert collision.duplicate_mark.line == 1
        text = str(yaml.KeyCollisionError(collision))
        assert BOOL_TAG in text and INT_TAG in text
    finally:
        loader.dispose()


@pytest.mark.parametrize("Loader", default_loader_classes())
def test_string_one_and_int_one_are_distinct_keys(Loader):
    source = "'1': string value\n1: int value\n"
    data, loader = load_with(Loader, source)
    try:
        assert data == {"1": "string value", 1: "int value"}
        assert loader.key_collisions == []
    finally:
        loader.dispose()


@pytest.mark.parametrize("Loader", default_loader_classes())
def test_raw_duplicate_keys_are_reported_as_source_collisions(Loader):
    source = "foo: first\nfoo: second\n"
    data, loader = load_with(Loader, source)
    try:
        assert data == {"foo": "second"}
        assert len(loader.key_collisions) == 1
        collision = loader.key_collisions[0]
        assert collision.kind == "source"
        assert collision.first_tag == STR_TAG
        assert collision.duplicate_tag == STR_TAG
        assert collision.first_mark.column == 0
        assert collision.duplicate_mark.column == 0
        assert collision.first_mark.line == 0
        assert collision.duplicate_mark.line == 1
    finally:
        loader.dispose()


@pytest.mark.parametrize("Loader", strict_loader_classes())
def test_strict_loader_rejects_typed_collision(Loader):
    source = "true: first value\n1: second value\n"
    with pytest.raises(yaml.KeyCollisionError) as exc_info:
        construct(Loader, source)

    error = exc_info.value
    assert isinstance(error, yaml.constructor.ConstructorError)
    assert error.collision_kind == "typed"
    assert error.first_key is True
    assert error.duplicate_key == 1
    assert error.first_key_node.tag == BOOL_TAG
    assert error.duplicate_key_node.tag == INT_TAG
    assert error.problem_mark.line == 1
    assert error.collision.first_mark.line == 0
    message = str(error)
    assert BOOL_TAG in message and INT_TAG in message


@pytest.mark.parametrize("Loader", strict_loader_classes())
def test_strict_loader_accepts_string_one_and_int_one(Loader):
    source = "'1': string value\n1: int value\n"
    assert construct(Loader, source) == {"1": "string value", 1: "int value"}


@pytest.mark.parametrize("Loader", strict_loader_classes())
def test_strict_loader_rejects_raw_duplicate(Loader):
    with pytest.raises(yaml.KeyCollisionError) as exc_info:
        construct(Loader, "foo: a\nfoo: b\n")
    assert exc_info.value.collision_kind == "source"


@pytest.mark.parametrize("Loader", strict_loader_classes())
def test_strict_failure_does_not_run_value_constructors(Loader):
    # A one-off loader subclass so the registered constructor cannot leak to
    # the shared loader classes.
    constructed_values = []

    class ProbingLoader(Loader):
        pass

    def construct_probe(loader, node):
        constructed_values.append(node.value)
        return node.value

    ProbingLoader.add_constructor(
        "tag:example.com,2026:probe", construct_probe)

    source = "true: !probe first\n1: !probe second\n"
    with pytest.raises(yaml.KeyCollisionError) as exc_info:
        construct(ProbingLoader, source)

    assert exc_info.value.collision_kind == "typed"
    # Neither value node was constructed: the strict check runs before values.
    assert constructed_values == []


@pytest.mark.parametrize("Loader", strict_loader_classes())
def test_nested_mappings_are_checked_independently(Loader):
    source = (
        "outer:\n"
        "  true: a\n"
        "  1: b\n"
        "sibling:\n"
        "  ok: fine\n"
    )
    with pytest.raises(yaml.KeyCollisionError) as exc_info:
        construct(Loader, source)
    error = exc_info.value
    # The error points at the inner mapping and its inner duplicate key.
    assert error.context_mark.line == 1
    assert error.problem_mark.line == 2
    assert error.problem_mark.column == 2
    assert error.collision_kind == "typed"


@pytest.mark.parametrize("Loader", default_loader_classes())
def test_nested_mappings_record_collision_independently(Loader):
    source = (
        "outer:\n"
        "  true: a\n"
        "  1: b\n"
        "sibling:\n"
        "  ok: fine\n"
    )
    data, loader = load_with(Loader, source)
    try:
        assert data == {"outer": {1: "b"}, "sibling": {"ok": "fine"}}
        assert len(loader.key_collisions) == 1
        collision = loader.key_collisions[0]
        assert collision.kind == "typed"
        assert collision.first_mark.line == 1
        assert collision.duplicate_mark.line == 2
    finally:
        loader.dispose()


@pytest.mark.parametrize(
    "Loader", default_loader_classes() + strict_loader_classes())
def test_nested_collision_does_not_poison_sibling_mapping(Loader):
    source = (
        "good:\n"
        "  true: a\n"
        "  '1': b\n"
        "also_good:\n"
        "  x: 1\n"
        "  y: 2\n"
    )
    assert construct(Loader, source) == {
        "good": {True: "a", "1": "b"},
        "also_good": {"x": 1, "y": 2},
    }


@pytest.mark.parametrize(
    "Loader", default_loader_classes() + strict_loader_classes())
def test_unhashable_keys_keep_original_error(Loader):
    source = "[one]: value\n"
    with pytest.raises(yaml.ConstructorError) as exc_info:
        construct(Loader, source)
    error = exc_info.value
    assert not isinstance(error, yaml.KeyCollisionError)
    assert "unhashable key" in str(error)


def test_three_key_example_default_loader_records_source_and_typed_reports():
    # Three keys collapse onto the same Python key: the raw duplicate integer
    # and the typed collision between the surviving integer and the boolean.
    source = "1: a\n1: b\ntrue: c\n"
    data, loader = load_with(yaml.SafeLoader, source)
    try:
        assert data == {1: "c"}
        kinds = [collision.kind for collision in loader.key_collisions]
        assert kinds == ["source", "typed"]

        source_collision, typed_collision = loader.key_collisions
        assert source_collision.first_tag == INT_TAG
        assert source_collision.duplicate_tag == INT_TAG
        assert source_collision.duplicate_mark.line == 1
        assert typed_collision.first_tag == INT_TAG
        assert typed_collision.duplicate_tag == BOOL_TAG
        assert typed_collision.first_mark.line == 0
        assert typed_collision.duplicate_mark.line == 2
    finally:
        loader.dispose()


@pytest.mark.parametrize("Loader", strict_loader_classes())
def test_three_key_example_strict_loader_fails_on_first_collision(Loader):
    constructed_values = []

    class ProbingLoader(Loader):
        pass

    def construct_probe(loader, node):
        constructed_values.append(node.value)
        return node.value

    ProbingLoader.add_constructor(
        "tag:example.com,2026:probe", construct_probe)

    source = "1: !probe a\n1: !probe b\ntrue: !probe c\n"
    with pytest.raises(yaml.KeyCollisionError) as exc_info:
        construct(ProbingLoader, source)

    error = exc_info.value
    assert error.collision_kind == "source"
    assert error.problem_mark.line == 1
    assert constructed_values == []


def test_merge_key_typed_collision_reported_in_flattened_order():
    source = (
        "base: &base\n"
        "  true: merged\n"
        "target:\n"
        "  <<: *base\n"
        "  1: explicit\n"
    )
    data, loader = load_with(yaml.SafeLoader, source)
    try:
        # Default override semantics: the explicit key wins over the merge.
        assert data["target"] == {1: "explicit"}
        target_collisions = [
            collision for collision in loader.key_collisions
            if collision.duplicate_mark.line == 4
        ]
        assert len(target_collisions) == 1
        collision = target_collisions[0]
        assert collision.kind == "typed"
        assert collision.first_tag == BOOL_TAG
        assert collision.duplicate_tag == INT_TAG
        assert collision.first_mark.line == 1
        assert collision.duplicate_mark.line == 4
    finally:
        loader.dispose()


def test_merge_key_source_collision_keeps_construction_order():
    source = (
        "base: &base\n"
        "  k: merged\n"
        "target:\n"
        "  <<: *base\n"
        "  k: explicit\n"
    )
    data, loader = load_with(yaml.SafeLoader, source)
    try:
        assert data["target"] == {"k": "explicit"}
        collisions = [
            collision for collision in loader.key_collisions
            if collision.duplicate_mark.line == 4
        ]
        assert len(collisions) == 1
        collision = collisions[0]
        assert collision.kind == "source"
        # The first occurrence is the merged key at its real source position.
        assert collision.first_key_node.value == "k"
        assert collision.first_mark.line == 1
        assert collision.duplicate_mark.line == 4
    finally:
        loader.dispose()
