"""
Example: per-load tag authorization with AuthorizedSafeLoader.

This example shows how to extend SafeLoader with custom tags while
specifying an authorization list for each load.  Only the tag constructors
in the list (plus the standard safe YAML tags) are allowed to execute.  The
constructor table is frozen when the loader is instantiated, so constructors
registered later by other modules cannot leak into a load.  Python object
construction is never permitted.

Run with:

    python examples/authorized_loader_example.py
"""

import yaml
from yaml import authorized_safe_loader


# ---------------------------------------------------------------------------
# Custom classes and constructors
# ---------------------------------------------------------------------------

class Point:
    """A simple custom object constructed from a YAML mapping."""

    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return isinstance(other, Point) and self.x == other.x and self.y == other.y

    def __repr__(self):
        return 'Point(x=%r, y=%r)' % (self.x, self.y)


class Secret:
    """A custom object whose constructor must never run when unauthorized."""

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, Secret) and self.value == other.value

    def __repr__(self):
        return 'Secret(value=%r)' % self.value


# A counter to prove that the Secret constructor never runs.
secret_constructor_calls = 0


def point_constructor(loader, node):
    values = loader.construct_mapping(node)
    return Point(**values)


def secret_constructor(loader, node):
    global secret_constructor_calls
    secret_constructor_calls += 1
    value = loader.construct_scalar(node)
    return Secret(value)


# ---------------------------------------------------------------------------
# Register custom tags on the global SafeLoader
# ---------------------------------------------------------------------------

yaml.add_constructor('!Point', point_constructor, Loader=yaml.SafeLoader)
yaml.add_constructor('!Secret', secret_constructor, Loader=yaml.SafeLoader)


# ---------------------------------------------------------------------------
# Create an authorized loader that only allows !Point
# ---------------------------------------------------------------------------

# The authorization list is captured at class creation time.  The standard
# safe YAML tags (str, int, seq, map, etc.) are always available.
loader_cls = authorized_safe_loader(['!Point'])


# ---------------------------------------------------------------------------
# Example 1: Authorized tag constructs successfully
# ---------------------------------------------------------------------------

print('=== Example 1: Authorized tag ===')
result = yaml.load('!Point {x: 1, y: 2}', Loader=loader_cls)
print('Loaded:', result)
assert isinstance(result, Point)
assert result.x == 1 and result.y == 2
print()


# ---------------------------------------------------------------------------
# Example 2: Unauthorized tag is rejected before construction
# ---------------------------------------------------------------------------

print('=== Example 2: Unauthorized tag ===')
try:
    yaml.load('!Secret mysecret', Loader=loader_cls)
except yaml.constructor.ConstructorError as exc:
    print('Rejected:', exc.problem)
    print('Line:', exc.problem_mark.line + 1,
          'Column:', exc.problem_mark.column + 1)
assert secret_constructor_calls == 0, 'Secret constructor must not run'
print('Secret constructor calls:', secret_constructor_calls)
print()


# ---------------------------------------------------------------------------
# Example 3: Standard safe tags continue to work
# ---------------------------------------------------------------------------

print('=== Example 3: Standard safe tags ===')
result = yaml.load(
    'name: Alice\nage: 30\nhobbies: [reading, hiking]\n',
    Loader=loader_cls)
print('Loaded:', result)
assert result == {'name': 'Alice', 'age': 30,
                  'hobbies': ['reading', 'hiking']}
print()


# ---------------------------------------------------------------------------
# Example 4: Python object construction is never permitted
# ---------------------------------------------------------------------------

print('=== Example 4: Python tag rejected ===')
try:
    yaml.load('!!python/object:os.system "echo hi"', Loader=loader_cls)
except yaml.constructor.ConstructorError as exc:
    print('Rejected:', exc.problem)
print()


# ---------------------------------------------------------------------------
# Example 5: Multiple documents share the same authorization snapshot
# ---------------------------------------------------------------------------

print('=== Example 5: Multi-document stream ===')
docs = yaml.load_all(
    '!Point {x: 1, y: 2}\n---\n!Point {x: 3, y: 4}\n',
    Loader=loader_cls)
results = list(docs)
print('Loaded documents:', results)
assert len(results) == 2
assert results[0] == Point(1, 2)
assert results[1] == Point(3, 4)
print()


# ---------------------------------------------------------------------------
# Example 6: A second document with an unauthorized tag is rejected
# ---------------------------------------------------------------------------

print('=== Example 6: Unauthorized tag in second document ===')
try:
    list(yaml.load_all(
        '!Point {x: 1, y: 2}\n---\n!Secret bad\n',
        Loader=loader_cls))
except yaml.constructor.ConstructorError as exc:
    print('Rejected:', exc.problem)
print()


# ---------------------------------------------------------------------------
# Example 7: Alias to an authorized tag works
# ---------------------------------------------------------------------------

print('=== Example 7: Alias to authorized tag ===')
result = yaml.load(
    'a: &point !Point {x: 1, y: 2}\nb: *point\n',
    Loader=loader_cls)
print('Loaded:', result)
assert result['a'] is result['b']  # same object via alias
print()


# ---------------------------------------------------------------------------
# Example 8: Alias to an unauthorized tag is rejected
# ---------------------------------------------------------------------------

print('=== Example 8: Alias to unauthorized tag ===')
try:
    yaml.load(
        'a: &secret !Secret hidden\nb: *secret\n',
        Loader=loader_cls)
except yaml.constructor.ConstructorError as exc:
    print('Rejected:', exc.problem)
print()


# ---------------------------------------------------------------------------
# Example 9: Registering a tag after loader creation does not enter snapshot
# ---------------------------------------------------------------------------

print('=== Example 9: Late registration does not enter snapshot ===')

def late_constructor(loader, node):
    raise RuntimeError('Late constructor should never be called')

# Another module registers !Late on SafeLoader after our loader class exists.
yaml.add_constructor('!Late', late_constructor, Loader=yaml.SafeLoader)

# The authorized loader's frozen table does not contain !Late.
assert '!Late' not in loader_cls.yaml_constructors
try:
    yaml.load('!Late foo', Loader=loader_cls)
except yaml.constructor.ConstructorError as exc:
    print('Rejected:', exc.problem)
print()


# ---------------------------------------------------------------------------
# Example 10: Parallel isolation between loaders
# ---------------------------------------------------------------------------

print('=== Example 10: Parallel isolation ===')
loader_a = authorized_safe_loader(['!Point'])
loader_b = authorized_safe_loader(['!Secret'])

# Loader A allows Point but not Secret.
assert isinstance(yaml.load('!Point {x: 1, y: 2}', Loader=loader_a), Point)
try:
    yaml.load('!Secret foo', Loader=loader_a)
except yaml.constructor.ConstructorError:
    print('Loader A: !Secret rejected (correct)')

# Loader B allows Secret but not Point.
assert isinstance(yaml.load('!Secret bar', Loader=loader_b), Secret)
try:
    yaml.load('!Point {x: 1, y: 2}', Loader=loader_b)
except yaml.constructor.ConstructorError:
    print('Loader B: !Point rejected (correct)')
print()


# ---------------------------------------------------------------------------
# Example 11: Global SafeLoader table is not modified
# ---------------------------------------------------------------------------

print('=== Example 11: Global SafeLoader table intact ===')
assert '!Point' in yaml.SafeLoader.yaml_constructors
assert '!Secret' in yaml.SafeLoader.yaml_constructors
print('Global SafeLoader table still contains !Point and !Secret')
print()


# ---------------------------------------------------------------------------
# Example 12: Existing safe_load entry point maintains original behaviour
# ---------------------------------------------------------------------------

print('=== Example 12: safe_load maintains original behaviour ===')
result = yaml.safe_load('{a: 1, b: [2, 3]}')
print('safe_load result:', result)
assert result == {'a': 1, 'b': [2, 3]}
print()


print('All examples passed!')
