"""Tests for the per-load authorized tag loading API (yaml.authorized_*).

Run against the in-tree yaml package, e.g.:
    PYTHONPATH=lib python -m pytest tests/test_authorized_loader.py
"""

import threading

import pytest

import yaml


class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return (self.x, self.y) == (other.x, other.y)


@pytest.fixture
def registered_tags():
    """Register !Point / !Secret on SafeLoader and restore the global
    SafeLoader tables afterwards, so the default entry points and other
    tests are unaffected."""
    saved_constructors = yaml.SafeLoader.yaml_constructors.copy()
    saved_multi = yaml.SafeLoader.yaml_multi_constructors.copy()
    calls = {'point': 0, 'secret': 0}

    def point_constructor(loader, node):
        calls['point'] += 1
        return Point(*loader.construct_sequence(node))

    def secret_constructor(loader, node):
        calls['secret'] += 1
        return loader.construct_scalar(node)

    yaml.add_constructor('!Point', point_constructor, Loader=yaml.SafeLoader)
    yaml.add_constructor('!Secret', secret_constructor, Loader=yaml.SafeLoader)
    try:
        yield calls
    finally:
        yaml.SafeLoader.yaml_constructors = saved_constructors
        yaml.SafeLoader.yaml_multi_constructors = saved_multi


def test_authorized_tag_constructs(registered_tags):
    point = yaml.authorized_load("!Point [1, 2]\n", allowed_tags=['!Point'])
    assert point == Point(1, 2)
    assert registered_tags['point'] == 1


def test_unauthorized_tag_rejected_before_construction(registered_tags):
    with pytest.raises(yaml.UnauthorizedTagError) as excinfo:
        yaml.authorized_load("a: !Secret s3cr3t\n", allowed_tags=['!Point'])
    # Rejected before the constructor ran.
    assert registered_tags['secret'] == 0
    # The error carries line/column of the offending node.
    mark = excinfo.value.problem_mark
    assert (mark.line, mark.column) == (0, 3)
    assert "line 1, column 4" in str(excinfo.value)


def test_standard_safe_tags_still_available(registered_tags):
    data = yaml.authorized_load(
            "n: 1\nf: 1.5\nb: true\ns: text\nl: [1, 2]\nm: {k: v}\nz: null\n",
            allowed_tags=['!Point'])
    assert data == {'n': 1, 'f': 1.5, 'b': True, 's': 'text',
                    'l': [1, 2], 'm': {'k': 'v'}, 'z': None}


def test_multi_documents_share_one_snapshot(registered_tags):
    stream = "!Point [1, 2]\n---\n!Point [3, 4]\n"
    docs = list(yaml.authorized_load_all(stream, allowed_tags=['!Point']))
    assert docs == [Point(1, 2), Point(3, 4)]
    # Second document uses the same authorization: !Secret stays rejected.
    with pytest.raises(yaml.UnauthorizedTagError):
        list(yaml.authorized_load_all(
                "!Point [1, 2]\n---\n!Secret nope\n",
                allowed_tags=['!Point']))
    assert registered_tags['secret'] == 0


def test_registration_during_load_does_not_enter_snapshot(registered_tags):
    # A constructor that registers a new tag while the load is running.
    def sneaky_constructor(loader, node):
        yaml.add_constructor('!Late',
                lambda l, n: l.construct_scalar(n),
                Loader=yaml.SafeLoader)
        return loader.construct_scalar(node)

    yaml.add_constructor('!Sneaky', sneaky_constructor, Loader=yaml.SafeLoader)
    stream = "!Sneaky first\n---\n!Late second\n"
    with pytest.raises(yaml.UnauthorizedTagError) as excinfo:
        list(yaml.authorized_load_all(stream, allowed_tags=['!Sneaky']))
    assert "'!Late'" in str(excinfo.value)


def test_aliases_with_authorized_tags(registered_tags):
    data = yaml.authorized_load(
            "first: &p !Point [1, 2]\nsecond: *p\n",
            allowed_tags=['!Point'])
    assert data['first'] == Point(1, 2)
    assert data['second'] is data['first']
    # The constructor ran only once for the anchored node.
    assert registered_tags['point'] == 1


def test_python_tag_cannot_be_authorized(registered_tags):
    with pytest.raises(ValueError):
        yaml.authorized_loader(['tag:yaml.org,2002:python/object:os.system'])
    with pytest.raises(ValueError):
        yaml.authorized_load("x: 1\n",
                allowed_tags=['tag:yaml.org,2002:python/name:os.system'])


def test_python_tag_rejected_in_document(registered_tags):
    with pytest.raises(yaml.UnauthorizedTagError):
        yaml.authorized_load("!!python/object:os.system ['id']\n",
                allowed_tags=['!Point'])
    with pytest.raises(yaml.UnauthorizedTagError):
        yaml.authorized_load("!!python/name:os.system ''\n",
                allowed_tags=['!Point'])


def test_global_safeloader_table_unmodified(registered_tags):
    before = dict(yaml.SafeLoader.yaml_constructors)
    before_multi = dict(yaml.SafeLoader.yaml_multi_constructors)
    yaml.authorized_load("!Point [5, 6]\n", allowed_tags=['!Point'])
    assert yaml.SafeLoader.yaml_constructors == before
    assert yaml.SafeLoader.yaml_multi_constructors == before_multi
    # Default entry points keep their original behaviour.
    assert yaml.safe_load("a: 1\n") == {'a': 1}
    # safe_load still uses the *global* table (registered tags work there,
    # unregistered ones fail with the classic undefined-constructor error).
    assert yaml.safe_load("!Point [1, 2]\n") == Point(1, 2)
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load("!Unknown x\n")


def test_authorized_loader_isolated_from_later_registration(registered_tags):
    Loader = yaml.authorized_loader(['!Point'])
    # Registered after the snapshot was frozen: must not be visible.
    yaml.add_constructor('!Late',
            lambda loader, node: loader.construct_scalar(node),
            Loader=yaml.SafeLoader)
    assert yaml.load("!Point [7, 8]\n", Loader=Loader) == Point(7, 8)
    with pytest.raises(yaml.UnauthorizedTagError):
        yaml.load("!Late nope\n", Loader=Loader)


def test_parallel_loads_are_isolated(registered_tags):
    """Concurrent loads with different authorization lists do not leak
    constructors into each other."""
    results = {}
    errors = []

    def run(name, stream, allowed):
        try:
            for _ in range(50):
                results.setdefault(name, []).append(
                        yaml.authorized_load(stream, allowed_tags=allowed))
        except Exception as exc:  # pragma: no cover - failure path
            errors.append((name, exc))

    threads = [
        threading.Thread(target=run, args=(
            'point', "!Point [1, 2]\n", ['!Point'])),
        threading.Thread(target=run, args=(
            'empty', "k: v\n", [])),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert all(p == Point(1, 2) for p in results['point'])
    assert all(d == {'k': 'v'} for d in results['empty'])
    # A load authorized for !Secret must not see !Point's authorization
    # and vice versa, even while running concurrently.
    with pytest.raises(yaml.UnauthorizedTagError):
        yaml.authorized_load("!Secret x\n", allowed_tags=['!Point'])
    with pytest.raises(yaml.UnauthorizedTagError):
        yaml.authorized_load("!Point [1, 2]\n", allowed_tags=['!Secret'])
    assert registered_tags['secret'] == 0


def test_unknown_authorized_tag_rejected_at_freeze_time(registered_tags):
    with pytest.raises(ValueError):
        yaml.authorized_loader(['!NoSuchTag'])
    with pytest.raises(TypeError):
        yaml.authorized_loader([123])
