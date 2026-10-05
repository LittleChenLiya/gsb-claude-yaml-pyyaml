import pytest

import yaml


class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return isinstance(other, Point) and (self.x, self.y) == (other.x, other.y)

    def __repr__(self):
        return "Point(%r, %r)" % (self.x, self.y)


class PointLoader(yaml.SafeLoader):
    pass


def construct_point(loader, node):
    mapping = loader.construct_mapping(node)
    return Point(**mapping)


def construct_point_generator(loader, node):
    data = Point.__new__(Point)
    yield data
    mapping = loader.construct_mapping(node, deep=True)
    data.__dict__.update(mapping)


@pytest.fixture(autouse=True)
def _register_contracts():
    PointLoader.add_constructor(
        "!Point",
        yaml.ConstructorContract(
            "!Point", construct_point,
            node_types=("mapping",), returns=Point))
    PointLoader.add_constructor(
        "!PointGen",
        yaml.ConstructorContract(
            "!PointGen", construct_point_generator,
            node_types=("mapping",), returns=Point))
    yield
    PointLoader.yaml_constructors = PointLoader.yaml_constructors.copy()


def test_contract_accepts_mapping():
    value = yaml.load("!Point\nx: 1\ny: 2\n", PointLoader)
    assert value == Point(1, 2)


def test_contract_rejects_sequence_before_callback():
    calls = []

    def constructor(loader, node):
        calls.append(node)
        return construct_point(loader, node)

    PointLoader.add_constructor(
        "!PointSeq",
        yaml.ConstructorContract(
            "!PointSeq", constructor,
            node_types=("mapping",), returns=Point))
    with pytest.raises(yaml.ConstructorError) as exc_info:
        yaml.load("!PointSeq\n- 1\n- 2\n", PointLoader)
    assert "expected a MappingNode node, but found a sequence node" in str(exc_info.value)
    assert calls == []


def test_contract_rejects_scalar_before_callback():
    calls = []

    def constructor(loader, node):
        calls.append(node)
        return construct_point(loader, node)

    PointLoader.add_constructor(
        "!PointScalar",
        yaml.ConstructorContract(
            "!PointScalar", constructor,
            node_types=("mapping",), returns=Point))
    with pytest.raises(yaml.ConstructorError) as exc_info:
        yaml.load("!PointScalar 42\n", PointLoader)
    assert "expected a MappingNode node, but found a scalar node" in str(exc_info.value)
    assert calls == []


def test_contract_error_carries_tag_and_mark():
    with pytest.raises(yaml.ConstructorError) as exc_info:
        yaml.load("\n\n!Point\n- 1\n", PointLoader)
    error = exc_info.value
    assert error.problem_mark is not None
    assert error.problem_mark.line == 2
    assert error.problem_mark.column == 0
    assert "!Point" in error.problem


def test_contract_return_type_mismatch():
    def constructor(loader, node):
        loader.construct_mapping(node)
        return [1, 2]

    PointLoader.add_constructor(
        "!BadReturn",
        yaml.ConstructorContract(
            "!BadReturn", constructor,
            node_types=("mapping",), returns=Point))
    with pytest.raises(yaml.ConstructorError) as exc_info:
        yaml.load("!BadReturn\nx: 1\ny: 2\n", PointLoader)
    assert "expected a return value of type Point" in str(exc_info.value)
    assert "but found list" in str(exc_info.value)


def test_contract_return_category_mismatch():
    def constructor(loader, node):
        return [1, 2]

    PointLoader.add_constructor(
        "!BadCat",
        yaml.ConstructorContract(
            "!BadCat", constructor,
            node_types=None, returns="mapping"))
    with pytest.raises(yaml.ConstructorError) as exc_info:
        yaml.load("!BadCat 42\n", PointLoader)
    assert "expected a return value of type dict" in str(exc_info.value)


def test_contract_generator_deferred_finalization():
    value = yaml.load("!PointGen\nx: 3\ny: 4\n", PointLoader)
    assert value == Point(3, 4)


def test_contract_deferred_failure_releases_generator():
    released = []

    def constructor(loader, node):
        data = {}
        try:
            yield data
            raise RuntimeError("boom")
        finally:
            released.append(True)

    PointLoader.add_constructor(
        "!FailGen",
        yaml.ConstructorContract(
            "!FailGen", constructor,
            node_types=("mapping",), returns=dict))
    with pytest.raises(RuntimeError, match="boom"):
        yaml.load("!FailGen\na: 1\n", PointLoader)
    assert released == [True]


def test_contract_deferred_nested_failure_releases_generator():
    released = []

    def constructor(loader, node):
        data = {}
        try:
            yield data
            data.update(loader.construct_mapping(node, deep=True))
        finally:
            released.append(True)

    PointLoader.add_constructor(
        "!NestedFail",
        yaml.ConstructorContract(
            "!NestedFail", constructor,
            node_types=("mapping",), returns=dict))
    with pytest.raises(yaml.ConstructorError):
        yaml.load("!NestedFail\na: !NoSuchTag 1\n", PointLoader)
    assert released == [True]


def test_contract_pre_yield_failure_releases_generator():
    released = []

    def constructor(loader, node):
        try:
            raise RuntimeError("pre-yield boom")
            yield
        finally:
            released.append(True)

    PointLoader.add_constructor(
        "!PreFail",
        yaml.ConstructorContract(
            "!PreFail", constructor,
            node_types=("mapping",), returns=dict))
    with pytest.raises(RuntimeError, match="pre-yield boom"):
        yaml.load("!PreFail\na: 1\n", PointLoader)
    assert released == [True]


def test_contract_forbids_python_object_tags():
    for tag in (
        "tag:yaml.org,2002:python/object",
        "tag:yaml.org,2002:python/object:foo.Bar",
        "tag:yaml.org,2002:python/object/new:foo.Bar",
        "tag:yaml.org,2002:python/object/apply:foo.Bar",
        "tag:yaml.org,2002:python/name:foo",
        "tag:yaml.org,2002:python/module:foo",
    ):
        with pytest.raises(yaml.ConstructorError):
            yaml.ConstructorContract(tag, lambda loader, node: None)


def test_contract_not_enabled_on_safe_loader():
    with pytest.raises(yaml.ConstructorError):
        yaml.safe_load("!Point\nx: 1\n")


def test_contract_decorator():
    @yaml.constructor_contract("!Deco", node_types=("mapping",), returns=dict)
    def constructor(loader, node):
        return loader.construct_mapping(node)

    PointLoader.add_constructor("!Deco", constructor)
    value = yaml.load("!Deco\na: 1\n", PointLoader)
    assert value == {"a": 1}


def test_contract_multiple_node_types():
    def constructor(loader, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        return loader.construct_sequence(node)

    PointLoader.add_constructor(
        "!Multi",
        yaml.ConstructorContract(
            "!Multi", constructor,
            node_types=("scalar", "sequence"), returns=None))
    assert yaml.load("!Multi 42\n", PointLoader) == "42"
    assert yaml.load("!Multi\n- 1\n- 2\n", PointLoader) == [1, 2]
    with pytest.raises(yaml.ConstructorError):
        yaml.load("!Multi\na: 1\n", PointLoader)


def test_contract_no_node_type_check():
    def constructor(loader, node):
        return node.id

    PointLoader.add_constructor(
        "!Any",
        yaml.ConstructorContract(
            "!Any", constructor, node_types=None, returns=None))
    assert yaml.load("!Any 42\n", PointLoader) == "scalar"
    assert yaml.load("!Any\n- 1\n", PointLoader) == "sequence"
    assert yaml.load("!Any\na: 1\n", PointLoader) == "mapping"


def test_contract_returns_none_skips_return_check():
    def constructor(loader, node):
        return "anything"

    PointLoader.add_constructor(
        "!NoReturn",
        yaml.ConstructorContract(
            "!NoReturn", constructor,
            node_types=None, returns=None))
    assert yaml.load("!NoReturn 42\n", PointLoader) == "anything"


def test_contract_generator_return_mismatch_after_finalization():
    def constructor(loader, node):
        data = {}
        yield data
        data.update(loader.construct_mapping(node, deep=True))

    PointLoader.add_constructor(
        "!GenBad",
        yaml.ConstructorContract(
            "!GenBad", constructor,
            node_types=("mapping",), returns=Point))
    with pytest.raises(yaml.ConstructorError) as exc_info:
        yaml.load("!GenBad\na: 1\n", PointLoader)
    assert "expected a return value of type Point" in str(exc_info.value)


def test_contract_invalid_node_type_raises_value_error():
    with pytest.raises(ValueError):
        yaml.ConstructorContract("!X", lambda loader, node: None,
                                 node_types=("bogus",))


def test_contract_invalid_return_category_raises_value_error():
    with pytest.raises(ValueError):
        yaml.ConstructorContract("!X", lambda loader, node: None,
                                 returns="bogus")
