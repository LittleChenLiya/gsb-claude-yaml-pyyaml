"""Example: using a ConstructorContract to validate YAML constructors.

A ConstructorContract wraps a constructor function and enforces:

* the node type the constructor accepts (scalar / sequence / mapping);
* the category of value the constructor returns (a type, a tuple of
  types, or a named category such as ``scalar``, ``sequence``, ``mapping``).

The node is checked *before* the constructor is called and the returned
value is checked *after* the constructor (and any deferred generator
finalization) has finished.  Errors are ConstructorError instances that
carry the tag and the node's start mark (line and column).

The contract is explicit: it is not installed on any loader by default.
Register it with ``add_constructor`` to opt in.  A contract can never be
used to enable Python object tags (``!!python/object`` & co.).

Run this example with::

    python examples/constructor_contract.py
"""

import sys

sys.path.insert(0, "lib")

import yaml


class Point:
    """A simple value object constructed from a YAML mapping."""

    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __repr__(self):
        return "Point(x=%r, y=%r)" % (self.x, self.y)


def construct_point(loader, node):
    """Construct a Point from a mapping node."""
    mapping = loader.construct_mapping(node)
    return Point(**mapping)


def construct_point_generator(loader, node):
    """Construct a Point using the deferred generator protocol.

    The placeholder is yielded first so that recursive references can be
    resolved; the mapping is then filled in during finalization.
    """
    data = Point.__new__(Point)
    yield data
    mapping = loader.construct_mapping(node, deep=True)
    data.__dict__.update(mapping)


class PointLoader(yaml.SafeLoader):
    """A loader with the !Point contract registered."""


# Register an explicit contract: only mapping nodes are accepted and the
# constructor must return a Point instance.
point_contract = yaml.ConstructorContract(
    "!Point", construct_point,
    node_types=("mapping",), returns=Point)
PointLoader.add_constructor("!Point", point_contract)

# A generator-based contract: the return value is checked after the
# deferred generator has been finalized.
point_gen_contract = yaml.ConstructorContract(
    "!PointGen", construct_point_generator,
    node_types=("mapping",), returns=Point)
PointLoader.add_constructor("!PointGen", point_gen_contract)


def main():
    # 1. A valid mapping is accepted and the callback is invoked once.
    value = yaml.load("!Point\nx: 1\ny: 2\n", PointLoader)
    print("valid mapping:", value)

    # 2. A sequence is rejected before the callback is invoked.
    try:
        yaml.load("!Point\n- 1\n- 2\n", PointLoader)
    except yaml.ConstructorError as exc:
        print("sequence rejected:", exc.problem)

    # 3. A scalar is rejected before the callback is invoked.
    try:
        yaml.load("!Point 42\n", PointLoader)
    except yaml.ConstructorError as exc:
        print("scalar rejected:", exc.problem)

    # 4. A return-type mismatch is reported with a clear diagnosis.
    def construct_wrong(loader, node):
        loader.construct_mapping(node)
        return [1, 2]  # returns a list, not a Point

    wrong_contract = yaml.ConstructorContract(
        "!Wrong", construct_wrong,
        node_types=("mapping",), returns=Point)
    PointLoader.add_constructor("!Wrong", wrong_contract)
    try:
        yaml.load("!Wrong\nx: 1\ny: 2\n", PointLoader)
    except yaml.ConstructorError as exc:
        print("return mismatch:", exc.problem)

    # 5. A generator constructor is finalized via the deferred protocol.
    value = yaml.load("!PointGen\nx: 3\ny: 4\n", PointLoader)
    print("generator constructor:", value)

    # 6. A deferred failure releases the generator and does not hand out
    #    a half-constructed object.
    released = []

    def construct_fail(loader, node):
        data = {}
        try:
            yield data
            raise RuntimeError("boom")
        finally:
            released.append(True)

    fail_contract = yaml.ConstructorContract(
        "!Fail", construct_fail,
        node_types=("mapping",), returns=dict)
    PointLoader.add_constructor("!Fail", fail_contract)
    try:
        yaml.load("!Fail\na: 1\n", PointLoader)
    except RuntimeError as exc:
        print("deferred failure:", exc, "released:", released)

    # 7. SafeLoader does not have the contract enabled by default.
    try:
        yaml.safe_load("!Point\nx: 1\n")
    except yaml.ConstructorError as exc:
        print("safe loader does not enable !Point:", exc.problem[:50])

    # 8. Python object tags cannot be enabled by a contract.
    try:
        yaml.ConstructorContract(
            "tag:yaml.org,2002:python/object:foo.Bar",
            lambda loader, node: None)
    except yaml.ConstructorError as exc:
        print("python object tag rejected:", exc.problem[:60])


if __name__ == "__main__":
    main()
