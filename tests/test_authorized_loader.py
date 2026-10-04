"""
Tests for AuthorizedSafeLoader: per-load tag authorization for SafeLoader.
"""

import pytest

import yaml
from yaml import authorized_safe_loader


class Point:
    """A simple custom object that can be constructed from a mapping."""

    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return isinstance(other, Point) and self.x == other.x and self.y == other.y

    def __repr__(self):
        return 'Point(%r, %r)' % (self.x, self.y)


class Secret:
    """A custom object whose constructor must never run when unauthorized."""

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return 'Secret(%r)' % self.value


def make_point_constructor():
    def point_constructor(loader, node):
        values = loader.construct_mapping(node)
        return Point(**values)
    return point_constructor


def make_secret_constructor(counter):
    def secret_constructor(loader, node):
        counter[0] += 1
        value = loader.construct_scalar(node)
        return Secret(value)
    return secret_constructor


@pytest.fixture
def registered_tags():
    """Register !Point and !Secret on SafeLoader, then clean up afterwards."""
    yaml.add_constructor('!Point', make_point_constructor(), Loader=yaml.SafeLoader)
    secret_counter = [0]
    yaml.add_constructor('!Secret', make_secret_constructor(secret_counter),
                         Loader=yaml.SafeLoader)
    yield secret_counter
    for tag in ('!Point', '!Secret'):
        yaml.SafeLoader.yaml_constructors.pop(tag, None)


def test_authorized_tag_constructs(registered_tags):
    loader_cls = authorized_safe_loader(['!Point'])
    result = yaml.load('!Point {x: 1, y: 2}', Loader=loader_cls)
    assert isinstance(result, Point)
    assert result.x == 1
    assert result.y == 2


def test_unauthorized_tag_rejected_before_construction(registered_tags):
    secret_counter = registered_tags
    loader_cls = authorized_safe_loader(['!Point'])
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load('!Secret mysecret', Loader=loader_cls)
    assert 'not in the authorization list' in exc_info.value.problem
    assert secret_counter[0] == 0


def test_unauthorized_tag_rejected_with_line_and_column(registered_tags):
    loader_cls = authorized_safe_loader(['!Point'])
    source = 'a: 1\nb: 2\nc: !Secret hidden\nd: 4\n'
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load(source, Loader=loader_cls)
    mark = exc_info.value.problem_mark
    assert mark.line == 2
    assert mark.column == 3


def test_standard_safe_tags_always_available(registered_tags):
    loader_cls = authorized_safe_loader(['!Point'])
    result = yaml.load('{a: 1, b: [2, 3], c: hello}', Loader=loader_cls)
    assert result == {'a': 1, 'b': [2, 3], 'c': 'hello'}


def test_python_tag_rejected_even_when_authorized(registered_tags):
    loader_cls = authorized_safe_loader(
        ['!Point', 'tag:yaml.org,2002:python/object'])
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load('!!python/object:os.system "echo hi"', Loader=loader_cls)
    assert 'python object construction is not permitted' in exc_info.value.problem


def test_python_name_tag_rejected(registered_tags):
    loader_cls = authorized_safe_loader(['!Point'])
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load('!!python/name:os.system ""', Loader=loader_cls)
    assert 'python object construction is not permitted' in exc_info.value.problem


def test_tags_registered_after_creation_do_not_enter_snapshot(registered_tags):
    loader_cls = authorized_safe_loader(['!Point'])

    def evil_constructor(loader, node):
        raise RuntimeError('Evil constructor should never be called')
    yaml.add_constructor('!Evil', evil_constructor, Loader=yaml.SafeLoader)

    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load('!Evil foo', Loader=loader_cls)
    assert 'not in the authorization list' in exc_info.value.problem


def test_frozen_table_does_not_inherit_later_registrations(registered_tags):
    # The fixture registered !Secret before the loader class is created, so
    # it is correctly captured in the frozen table.
    loader_cls = authorized_safe_loader(['!Point'])
    assert '!Secret' in loader_cls.yaml_constructors

    # Register a new tag on SafeLoader after the loader class was created.
    def new_secret_constructor(loader, node):
        raise RuntimeError('Should not be called')
    yaml.add_constructor('!NewSecret', new_secret_constructor, Loader=yaml.SafeLoader)

    # The frozen table does not contain the newly registered tag.
    assert '!NewSecret' not in loader_cls.yaml_constructors
    # And loading it is rejected.
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load('!NewSecret hidden', Loader=loader_cls)


def test_global_safeloader_table_not_modified(registered_tags):
    before = dict(yaml.SafeLoader.yaml_constructors)
    loader_cls = authorized_safe_loader(['!Point'])
    after = dict(yaml.SafeLoader.yaml_constructors)
    assert before == after
    assert loader_cls.yaml_constructors is not yaml.SafeLoader.yaml_constructors


def test_existing_safe_load_still_works(registered_tags):
    result = yaml.safe_load('{a: 1, b: [2, 3]}')
    assert result == {'a': 1, 'b': [2, 3]}


def test_multiple_documents_share_authorization(registered_tags):
    loader_cls = authorized_safe_loader(['!Point'])
    docs = yaml.load_all(
        '!Point {x: 1, y: 2}\n---\n!Point {x: 3, y: 4}\n',
        Loader=loader_cls)
    results = list(docs)
    assert len(results) == 2
    assert results[0] == Point(1, 2)
    assert results[1] == Point(3, 4)


def test_second_document_with_unauthorized_tag_rejected(registered_tags):
    loader_cls = authorized_safe_loader(['!Point'])
    docs = yaml.load_all(
        '!Point {x: 1, y: 2}\n---\n!Secret bad\n',
        Loader=loader_cls)
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        list(docs)
    assert 'not in the authorization list' in exc_info.value.problem


def test_alias_to_authorized_tag_works(registered_tags):
    loader_cls = authorized_safe_loader(['!Point'])
    result = yaml.load(
        'a: &point !Point {x: 1, y: 2}\nb: *point\n',
        Loader=loader_cls)
    assert result['a'] is result['b']
    assert result['a'] == Point(1, 2)


def test_alias_to_unauthorized_tag_rejected(registered_tags):
    loader_cls = authorized_safe_loader(['!Point'])
    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        yaml.load(
            'a: &secret !Secret hidden\nb: *secret\n',
            Loader=loader_cls)
    assert 'not in the authorization list' in exc_info.value.problem


def test_parallel_loaders_are_isolated(registered_tags):
    loader_a = authorized_safe_loader(['!Point'])
    loader_b = authorized_safe_loader(['!Secret'])

    assert isinstance(yaml.load('!Point {x: 1, y: 2}', Loader=loader_a), Point)
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load('!Secret foo', Loader=loader_a)

    assert isinstance(yaml.load('!Secret bar', Loader=loader_b), Secret)
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load('!Point {x: 1, y: 2}', Loader=loader_b)


def test_same_authorization_list_creates_independent_instances(registered_tags):
    loader_a = authorized_safe_loader(['!Point'])
    loader_b = authorized_safe_loader(['!Point'])
    assert loader_a.yaml_constructors is not loader_b.yaml_constructors
    assert isinstance(yaml.load('!Point {x: 1, y: 2}', Loader=loader_a), Point)
    assert isinstance(yaml.load('!Point {x: 3, y: 4}', Loader=loader_b), Point)