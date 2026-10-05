"""
Tests for the explicit constructor contracts in ``yaml.contract``.

Run from the repository root with:

    PYTHONPATH=lib python -m pytest tests/test_contract.py -v

(on Windows: ``set PYTHONPATH=lib && python -m pytest tests/test_contract.py -v``)
"""

import pytest

import yaml


class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return isinstance(other, Point) \
                and (self.x, self.y) == (other.x, other.y)


def make_point_loader(construct_point, **contract):
    """A dedicated ContractLoader subclass with a single !Point contract."""
    class PointLoader(yaml.ContractLoader):
        pass
    PointLoader.add_contract('!Point', construct_point, **contract)
    return PointLoader


def recording_constructor(return_value):
    """A !Point constructor that records its calls."""
    calls = []

    def construct_point(loader, node):
        calls.append(node)
        mapping = loader.construct_mapping(node, deep=True)
        if return_value is not None:
            return return_value
        return Point(mapping['x'], mapping['y'])

    return construct_point, calls


def test_mapping_contract_rejects_sequence_before_callback():
    construct_point, calls = recording_constructor(None)
    PointLoader = make_point_loader(construct_point,
            node='mapping', returns=Point)

    with pytest.raises(yaml.ContractError) as excinfo:
        yaml.load("!Point [1, 2]\n", Loader=PointLoader)

    # Rejected before the callback ran.
    assert calls == []
    # The diagnostic carries the tag and the line/column mark.
    message = str(excinfo.value)
    assert "'!Point'" in message
    assert "mapping" in message and "sequence" in message
    assert "line 1" in message and "column" in message


def test_mapping_contract_rejects_scalar_before_callback():
    construct_point, calls = recording_constructor(None)
    PointLoader = make_point_loader(construct_point,
            node='mapping', returns=Point)

    with pytest.raises(yaml.ContractError):
        yaml.load("!Point 42\n", Loader=PointLoader)

    assert calls == []


def test_mapping_contract_accepts_mapping_once():
    construct_point, calls = recording_constructor(None)
    PointLoader = make_point_loader(construct_point,
            node='mapping', returns=Point)

    point = yaml.load("!Point {x: 1, y: 2}\n", Loader=PointLoader)

    assert point == Point(1, 2)
    assert len(calls) == 1


def test_wrong_return_category_has_clear_diagnostics():
    construct_point, calls = recording_constructor(['not', 'a', 'point'])
    PointLoader = make_point_loader(construct_point,
            node='mapping', returns=Point)

    with pytest.raises(yaml.ContractError) as excinfo:
        yaml.load("!Point {x: 1, y: 2}\n", Loader=PointLoader)

    message = str(excinfo.value)
    assert "'!Point'" in message
    assert "Point" in message      # expected category
    assert "list" in message       # actual category
    assert "line 1" in message and "column" in message


def test_scalar_contract_rejects_mapping_before_callback():
    calls = []

    def construct_name(loader, node):
        calls.append(node)
        return loader.construct_scalar(node)

    class NameLoader(yaml.ContractLoader):
        pass
    NameLoader.add_contract('!name', construct_name,
            node='scalar', returns='scalar')

    with pytest.raises(yaml.ContractError) as excinfo:
        yaml.load("!name {first: 1}\n", Loader=NameLoader)

    assert calls == []
    assert "scalar" in str(excinfo.value)

    assert yaml.load("!name bob\n", Loader=NameLoader) == "bob"
    assert len(calls) == 1


def test_deferred_constructor_failure_releases_generator():
    inner_generators = []

    def construct_point_deferred(loader, node):
        def deferred():
            data = Point(0, 0)          # half-constructed object
            yield data
            raise RuntimeError("deferred construction failed")
        generator = deferred()
        inner_generators.append(generator)
        return generator

    PointLoader = make_point_loader(construct_point_deferred,
            node='mapping', returns=Point)

    # The failure propagates: the caller never receives the half object.
    with pytest.raises(RuntimeError, match="deferred construction failed"):
        yaml.load("!Point {x: 1, y: 2}\n", Loader=PointLoader)

    # The deferred generator was released (closed), not leaked.
    assert len(inner_generators) == 1
    assert inner_generators[0].gi_frame is None


def test_deferred_constructor_success_is_checked_after_completion():
    def construct_point_deferred(loader, node):
        data = Point(0, 0)
        yield data
        mapping = loader.construct_mapping(node, deep=True)
        data.x = mapping['x']
        data.y = mapping['y']

    PointLoader = make_point_loader(construct_point_deferred,
            node='mapping', returns=Point)

    point = yaml.load("!Point {x: 3, y: 4}\n", Loader=PointLoader)
    assert point == Point(3, 4)


def test_deferred_constructor_wrong_return_category():
    def construct_point_deferred(loader, node):
        data = ['half', 'built']
        yield data
        loader.construct_mapping(node, deep=True)

    PointLoader = make_point_loader(construct_point_deferred,
            node='mapping', returns=Point)

    with pytest.raises(yaml.ContractError) as excinfo:
        yaml.load("!Point {x: 1, y: 2}\n", Loader=PointLoader)

    assert "list" in str(excinfo.value)


def test_safe_loader_does_not_enable_contracts():
    # The plain SafeLoader has no contract API at all.
    assert not hasattr(yaml.SafeLoader, 'add_contract')
    assert not hasattr(yaml.SafeLoader, 'add_contract_constructor')

    # And it does not resolve contracted tags.
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("!Point {x: 1, y: 2}\n", Loader=yaml.SafeLoader)


def test_contracts_do_not_enable_python_object_tags():
    class AnyLoader(yaml.ContractLoader):
        pass

    with pytest.raises(ValueError, match="python object tags"):
        AnyLoader.add_contract(
                'tag:yaml.org,2002:python/object:builtins.dict',
                lambda loader, node: {})

    # The contract loader does not resolve python object tags either.
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("!!python/object:builtins.dict {}\n",
                Loader=yaml.ContractLoader)


def test_contract_registration_validates_arguments():
    class AnyLoader(yaml.ContractLoader):
        pass

    with pytest.raises(ValueError, match="node kind"):
        AnyLoader.add_contract('!Thing', lambda loader, node: None,
                node='document')

    with pytest.raises(ValueError, match="return category"):
        AnyLoader.add_contract('!Thing', lambda loader, node: None,
                returns='document')

    with pytest.raises(TypeError):
        AnyLoader.add_contract('!Thing', "not callable")


def test_contracts_registered_on_subclass_do_not_leak():
    construct_point, calls = recording_constructor(None)
    PointLoader = make_point_loader(construct_point,
            node='mapping', returns=Point)

    # Registering on a subclass must not affect the base ContractLoader.
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("!Point {x: 1, y: 2}\n", Loader=yaml.ContractLoader)
    assert calls == []

