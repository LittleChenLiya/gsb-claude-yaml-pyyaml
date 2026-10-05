"""
Explicit constructor contracts.

This module implements an opt-in wrapper around YAML constructors.  A
contract declares, for one explicit tag:

* the node kind the constructor accepts (``scalar``, ``sequence`` or
  ``mapping``) -- checked *before* the constructor callback runs, so a
  sequence can never be fed to a mapping-only constructor (and vice
  versa), and
* the category of value the constructor must return -- checked *after*
  the callback completes.  For generator constructors following the
  usual deferred-construction protocol (yield the object first, fill it
  in later), the check runs once the generator has been exhausted.

Every violation raises :class:`ContractError` carrying the tag and the
line/column mark of the offending node.  If deferred construction
fails, the generator is released (closed) and the error propagates, so
the caller never receives a half-constructed object.

Contracts are *not* enabled on the plain ``SafeLoader``; they require
the explicit :class:`ContractLoader` (or a subclass mixing in
:class:`ContractConstructor`).  Contracts also refuse to register
``tag:yaml.org,2002:python/...`` tags, so they cannot be used to open
the door to arbitrary Python object construction.

Example::

    class PointLoader(yaml.ContractLoader):
        pass

    def construct_point(loader, node):
        mapping = loader.construct_mapping(node, deep=True)
        return Point(mapping['x'], mapping['y'])

    PointLoader.add_contract('!Point', construct_point,
            node='mapping', returns=Point)

    point = yaml.load('!Point {x: 1, y: 2}', Loader=PointLoader)

Run the tests for this module with::

    PYTHONPATH=lib python -m pytest tests/test_contract.py -v
"""

__all__ = ['ContractError', 'ContractConstructor', 'ContractLoader']

from .error import *
from .nodes import *
from .reader import *
from .scanner import *
from .parser import *
from .composer import *
from .constructor import SafeConstructor, ConstructorError
from .resolver import *

import types

class ContractError(ConstructorError):
    """Raised when a constructor contract is violated."""
    pass

# Node kinds a contract may declare.  Scalars, sequences and mappings
# are deliberately distinct: a contract registered for one kind rejects
# the others before the callback runs.
_NODE_KINDS = {
    'scalar': ScalarNode,
    'sequence': SequenceNode,
    'mapping': MappingNode,
}

# Convenience return categories, mapped to the Python types a safe
# constructor is expected to produce for them.
_RETURN_CATEGORIES = {
    'scalar': str,
    'sequence': (list, tuple),
    'mapping': dict,
}

# Contracts must never enable arbitrary Python object construction.
_PYTHON_TAG_PREFIX = 'tag:yaml.org,2002:python/'


def _normalize_returns(tag, returns):
    if returns is None:
        return None
    if isinstance(returns, str):
        if returns in _RETURN_CATEGORIES:
            return _RETURN_CATEGORIES[returns]
        raise ValueError(
                "unknown return category %r for tag %r; expected one of %s "
                "or a Python type"
                % (returns, tag, ', '.join(sorted(_RETURN_CATEGORIES))))
    if isinstance(returns, type):
        return returns
    if isinstance(returns, tuple) and returns \
            and all(isinstance(item, type) for item in returns):
        return returns
    raise TypeError(
            "invalid return category %r for tag %r; expected 'scalar', "
            "'sequence', 'mapping', a type or a non-empty tuple of types"
            % (returns, tag))


def _describe_types(types_):
    if isinstance(types_, tuple):
        return ' or '.join(item.__name__ for item in types_)
    return types_.__name__


def _check_returns(tag, returns, data, node):
    if returns is None:
        return
    if not isinstance(data, returns):
        raise ContractError(None, None,
                "contract for tag %r requires the constructor to return %s, "
                "but it returned %s"
                % (tag, _describe_types(returns), type(data).__name__),
                node.start_mark)


def _guarded_generator(generator, tag, returns, node):
    # Follow the standard deferred-construction protocol: the first
    # yielded value is the (possibly incomplete) object, the remaining
    # steps fill it in.  Whatever happens, the underlying generator is
    # closed so it is never leaked, and a failure propagates instead of
    # handing a half-constructed object to the caller.
    try:
        data = next(generator)
    except StopIteration:
        generator.close()
        raise ContractError(None, None,
                "contract constructor for tag %r did not yield a value"
                % (tag,),
                node.start_mark)
    except BaseException:
        generator.close()
        raise
    try:
        yield data
        for dummy in generator:
            pass
    except BaseException:
        # Deferred construction failed (or this wrapper was closed
        # early): release the underlying generator and let the error
        # propagate.
        generator.close()
        raise
    else:
        generator.close()
    _check_returns(tag, returns, data, node)


def _make_contract_constructor(tag, constructor, node_kind, returns):
    expected_node = _NODE_KINDS[node_kind]

    def contract_constructor(loader, node):
        if not isinstance(node, expected_node):
            raise ContractError(None, None,
                    "contract for tag %r expects a %s node, "
                    "but found a %s node"
                    % (tag, node_kind, node.id),
                    node.start_mark)
        data = constructor(loader, node)
        if isinstance(data, types.GeneratorType):
            return _guarded_generator(data, tag, returns, node)
        _check_returns(tag, returns, data, node)
        return data

    contract_constructor.__name__ = 'contract(%s)' % (tag,)
    contract_constructor.__doc__ = constructor.__doc__
    return contract_constructor


class ContractConstructor(SafeConstructor):
    """
    SafeConstructor with explicit, opt-in constructor contracts.

    This mixin is deliberately *not* part of ``SafeLoader``; use
    ``ContractLoader`` or mix this class into a loader of your own.
    """

    @classmethod
    def add_contract(cls, tag, constructor, node='mapping', returns=None):
        """
        Register ``constructor`` for ``tag`` under an explicit contract.

        ``node`` declares the accepted node kind: 'scalar', 'sequence'
        or 'mapping' (checked before the callback runs).  ``returns``
        declares the expected return category: 'scalar', 'sequence',
        'mapping', a Python type or a tuple of types (checked after the
        callback, and after any deferred generator construction,
        completes).
        """
        if not isinstance(tag, str) or not tag:
            raise TypeError("contract tag must be a non-empty string")
        if tag.startswith(_PYTHON_TAG_PREFIX):
            raise ValueError(
                    "contracts must not register python object tags: %r"
                    % (tag,))
        if node not in _NODE_KINDS:
            raise ValueError(
                    "unknown node kind %r for tag %r; expected one of %s"
                    % (node, tag, ', '.join(sorted(_NODE_KINDS))))
        if not callable(constructor):
            raise TypeError(
                    "contract constructor for tag %r must be callable"
                    % (tag,))
        returns = _normalize_returns(tag, returns)
        cls.add_constructor(tag,
                _make_contract_constructor(tag, constructor, node, returns))


class ContractLoader(Reader, Scanner, Parser, Composer, ContractConstructor, Resolver):
    """
    A SafeLoader variant with explicit constructor contracts.

    Contracts are only active when this loader (or a subclass) is used
    explicitly; the plain ``SafeLoader`` never enables them.  Like
    ``SafeLoader``, this loader does not resolve python object tags.
    """

    def __init__(self, stream):
        Reader.__init__(self, stream)
        Scanner.__init__(self)
        Parser.__init__(self)
        Composer.__init__(self)
        SafeConstructor.__init__(self)
        Resolver.__init__(self)
