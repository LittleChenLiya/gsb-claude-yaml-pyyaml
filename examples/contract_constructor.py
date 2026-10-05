"""
Example: explicit constructor contracts (yaml.contract).

A contract wraps a constructor and declares, up front:

* which node kind it accepts  (checked *before* the callback runs), and
* which return category it must produce (checked *after* the callback,
  including after any deferred generator construction, completes).

Violations raise yaml.ContractError with the tag and the line/column of
the offending node.  Contracts are only active on yaml.ContractLoader
(or subclasses); the plain yaml.SafeLoader never enables them, and
python object tags cannot be registered.

Run this file directly:

    PYTHONPATH=lib python examples/contract_constructor.py

Run the accompanying tests with:

    PYTHONPATH=lib python -m pytest tests/test_contract.py -v
"""

import yaml


class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __repr__(self):
        return 'Point(x=%r, y=%r)' % (self.x, self.y)


# --- 1. A plain constructor under a "mapping in, Point out" contract. ---

def construct_point(loader, node):
    mapping = loader.construct_mapping(node, deep=True)
    return Point(mapping['x'], mapping['y'])


# --- 2. A deferred (generator) constructor under the same contract. ---
#
# It follows the standard PyYAML deferred-construction protocol: yield
# the object first, then fill it in.  The contract wrapper drives the
# generator to completion, closes it even on failure, and only then
# checks the return category -- a failure never hands the caller a
# half-constructed Point.

def construct_point_deferred(loader, node):
    point = Point(0, 0)
    yield point
    mapping = loader.construct_mapping(node, deep=True)
    point.x = mapping['x']
    point.y = mapping['y']


class PointLoader(yaml.ContractLoader):
    pass


PointLoader.add_contract('!Point', construct_point,
        node='mapping', returns=Point)
PointLoader.add_contract('!DeferredPoint', construct_point_deferred,
        node='mapping', returns=Point)


if __name__ == '__main__':
    # A legal mapping: the callback runs exactly once.
    print(yaml.load("!Point {x: 1, y: 2}", Loader=PointLoader))
    print(yaml.load("!DeferredPoint {x: 3, y: 4}", Loader=PointLoader))

    # A sequence where the contract demands a mapping: rejected before
    # the callback runs, with the tag and line/column in the error.
    try:
        yaml.load("!Point [1, 2]", Loader=PointLoader)
    except yaml.ContractError as error:
        print('rejected as contracted:')
        print(error)

