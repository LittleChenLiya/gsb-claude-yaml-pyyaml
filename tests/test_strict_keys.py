"""Directed tests for strict mapping key collision reporting.

Run with::

    PYTHONPATH=lib python -m pytest tests/test_strict_keys.py -q

In strict mode the constructor rejects duplicate or colliding mapping keys
before any value is constructed, reporting both scalar tags and positions.
The default loaders keep their silent override semantics.
"""

import pytest

import yaml


def loader_classes():
    classes = [yaml.SafeLoader, yaml.FullLoader, yaml.Loader]
    if hasattr(yaml, "CSafeLoader"):
        classes.append(yaml.CSafeLoader)
    return classes


@pytest.mark.parametrize("Loader", loader_classes())
def test_strict_duplicate_raw_text_rejected(Loader):
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load("a: 1\na: 2\n", Loader, strict=True)
    problem = str(exc_info.value.problem)
    assert "found duplicate key 'a'" in problem
    assert "tag:yaml.org,2002:str" in problem
    assert "line 1, column 1" in problem
    assert "line 2, column 1" in problem


@pytest.mark.parametrize("Loader", loader_classes())
def test_strict_colliding_keys_rejected(Loader):
    # true (bool) and 1 (int) construct to equal Python objects (True == 1).
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load("true: a\n1: b\n", Loader, strict=True)
    problem = str(exc_info.value.problem)
    assert "found colliding keys 'true' and '1'" in problem
    assert "tag:yaml.org,2002:bool" in problem
    assert "tag:yaml.org,2002:int" in problem
    assert "line 1, column 1" in problem
    assert "line 2, column 1" in problem


@pytest.mark.parametrize("Loader", loader_classes())
def test_strict_three_key_example(Loader):
    # Three keys: true, 1 and quoted "1". Strict mode must flag only the
    # true/1 collision; the quoted "1" is a distinct str key.
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load('true: a\n1: b\n"1": c\n', Loader, strict=True)
    problem = str(exc_info.value.problem)
    assert "found colliding keys 'true' and '1'" in problem
    assert "tag:yaml.org,2002:bool" in problem
    assert "tag:yaml.org,2002:int" in problem
    # The quoted str key must not be reported as part of the collision.
    assert problem.count("tag:yaml.org,2002:str") == 0


@pytest.mark.parametrize("Loader", loader_classes())
def test_strict_distinct_keys_accepted(Loader):
    # "1" (str) and 1 (int) must not be mixed up as the same key.
    result = yaml.load('"1": a\n1: b\n', Loader, strict=True)
    assert result == {"1": "a", 1: "b"}


@pytest.mark.parametrize("Loader", loader_classes())
def test_strict_nested_mapping_checked(Loader):
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load("outer:\n  true: a\n  1: b\n", Loader, strict=True)
    problem = str(exc_info.value.problem)
    assert "found colliding keys 'true' and '1'" in problem
    assert "line 2, column 3" in problem
    assert "line 3, column 3" in problem


@pytest.mark.parametrize("Loader", loader_classes())
def test_strict_unhashable_key_original_error(Loader):
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load("? [1, 2]: value\n", Loader, strict=True)
    assert "found unhashable key" in str(exc_info.value.problem)


@pytest.mark.parametrize("Loader", loader_classes())
def test_default_loader_override_unchanged(Loader):
    assert yaml.load("a: 1\na: 2\n", Loader) == {"a": 2}
    assert yaml.load("true: a\n1: b\n", Loader) == {True: "b"}


@pytest.mark.parametrize("Loader", loader_classes())
def test_strict_merge_keys_checked_in_construction_order(Loader):
    # The merged key (true) is prepended by flatten_mapping and must be
    # reported as the first key, not the explicit one.
    source = (
        "base: &base {true: 1}\n"
        "target:\n"
        "  <<: *base\n"
        "  1: 2\n"
    )
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load(source, Loader, strict=True)
    problem = str(exc_info.value.problem)
    assert "found colliding keys 'true' and '1'" in problem
    assert "first:" in problem
    assert "second:" in problem


def test_strict_failure_skips_value_constructors():
    constructed = []

    class TrackingLoader(yaml.SafeLoader):
        pass

    def tracking_constructor(loader, node):
        constructed.append(node.value)
        return node.value

    TrackingLoader.add_constructor("!track", tracking_constructor)

    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("true: !track a\n1: !track b\n", TrackingLoader, strict=True)
    assert constructed == []

    # Control: without a collision, value constructors do run.
    result = yaml.load("x: !track a\ny: !track b\n", TrackingLoader, strict=True)
    assert result == {"x": "a", "y": "b"}
    assert constructed == ["a", "b"]


def test_strict_loader_attribute():
    loader = yaml.SafeLoader("a: 1\na: 2\n", strict=True)
    try:
        with pytest.raises(yaml.constructor.ConstructorError):
            loader.get_single_data()
    finally:
        loader.dispose()
